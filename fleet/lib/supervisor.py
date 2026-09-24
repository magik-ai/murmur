#!/usr/bin/env python3
"""fleet supervisor — the native reconcile loop behind `fleet daemon`.

Replaces the pattern every orchestrator hand-rolls in bash:
a lane is a ONE-PASS process, but the WORK is not — so a lane that exits before it delivered
must be respawned, and a lane that "finished" without delivering must be told apart from one
that succeeded. This module owns that judgment natively.

Design that matters:
  * Everything is keyed by (project, LANE), never slug — because a respawn mints a NEW slug, so
    "is this lane alive?" and "did this lane deliver?" only make sense at the lane level. This is
    exactly why a bash watcher greps `lane.*running` instead of tracking pids.
  * OPT-IN. A lane is only ever touched if its record carries an explicit `restart` policy. Every
    existing lane — and every lane an orchestrator's own watcher already manages — has no policy
    and is invisible here. The daemon cannot disturb a running fleet it wasn't told to own.
  * Outcome is a CONTRACT, not a status. `done_when` says what "delivered" means; until it holds,
    an exited lane is a FAILURE to be retried, not a success.

Safe to run every ~60s. Reads records + `systemctl --user is-active` + a little `gh`; writes only
its own bookkeeping back into the records and a heartbeat line to stdout.
"""
import glob
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from events import append_event
except Exception:
    def append_event(*a, **k):
        pass

STATE = os.environ.get("FLEET_STATE", os.path.expanduser("~/.fleet"))
STATE_DIR = os.path.join(STATE, "state")
BRIEF_DIR = os.path.join(STATE, "briefs")
FLEET = os.environ.get("FLEET_BIN", os.path.expanduser("~/.local/bin/fleet"))
DEFAULT_COOLDOWN = int(os.environ.get("FLEET_RESPAWN_COOLDOWN", "600"))   # s between respawns
DEFAULT_MAX = int(os.environ.get("FLEET_RESPAWN_MAX", "10"))              # backstop per lane
# The CLI writes a lane's state record and THEN starts its systemd unit, so for a moment a
# just-spawned lane has a record but no active unit. A tick landing in that window reads the lane
# as exited and respawns it — a duplicate racing the spawn that is still booting (the double-spawn
# / TOCTOU storm). Leave a record this young alone; the unit will be up by the next tick.
BOOTSTRAP_GRACE = int(os.environ.get("FLEET_BOOTSTRAP_GRACE", "120"))     # s to let a spawn boot
# The mirror of bootstrap on the way DOWN: a lane's unit goes inactive the moment the agent exits,
# but a PR it just opened (gh create) can lag GitHub's API by seconds. A tick in that window sees
# "exited, no PR" and respawns a FRESH branch — the duplicate-PR storm. updated_at is a PARSER
# field the daemon never rewrites, so it freezes at exit and this window closes on its own; respawn
# of a genuinely dropped lane just waits it out.
TEARDOWN_GRACE = int(os.environ.get("FLEET_TEARDOWN_GRACE", "180"))       # s for a PR to become visible
_RESPAWN_FALLBACK = {}  # (project, lane) -> highest attempted count in this process


def sh(cmd, timeout=45):
    """Best-effort stdout, "" on failure. Use ONLY where a failure may safely read as empty."""
    ok, out = sh_checked(cmd, timeout)
    return out if ok else ""


def sh_checked(cmd, timeout=45):
    """(ok, stdout). ok=False on exception, timeout, OR non-zero exit — a rate-limited `gh` exits
    non-zero with an empty stdout, which is indistinguishable from "found nothing" unless the
    return code is checked. Every delivery/scope decision must use THIS, not sh()."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return False, (r.stderr or "").strip()
        return True, (r.stdout or "").strip()
    except Exception as e:
        return False, str(e)


def _atomic_write_json(path, data):
    """Durably publish JSON without sharing a temp path with another writer."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    except Exception as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        print(f"fleet supervisor: cannot write {path}: {exc}", file=sys.stderr)
        return False


def _save_record(rec):
    """Atomically save a lane record; a failed save is visible to the daemon journal."""
    path = rec["_path"]
    data = {k: v for k, v in rec.items() if k != "_path"}
    return _atomic_write_json(path, data)


def _read_json_retry(path, description="state record"):
    """Retry one transient/torn read, then report it instead of silently dropping it."""
    last = None
    for attempt in range(2):
        try:
            with open(path) as handle:
                return json.load(handle)
        except Exception as exc:
            last = exc
            if attempt == 0:
                time.sleep(0.01)
    print(f"fleet supervisor: unreadable {description} {path}: {last}", file=sys.stderr)
    return None


def load_records():
    recs = []
    for fp in glob.glob(os.path.join(STATE_DIR, "*.json")):
        r = _read_json_retry(fp)
        if not isinstance(r, dict):
            continue
        r["_path"] = fp
        recs.append(r)
    return recs


def unit_active(slug):
    return sh(["systemctl", "--user", "is-active", f"fleet-{slug}"]) == "active"


def lane_running(recs, project, lane):
    """Any slug of this lane whose systemd unit is still active."""
    return any(r.get("project") == project and r.get("lane") == lane and r.get("slug")
               and unit_active(r["slug"]) for r in recs)


def within_bootstrap_grace(rec, now=None):
    """True while a record is young enough that its unit may still be coming up. Gates RESPAWN
    only — never the delivered/PR checks — so a lane that genuinely finished fast is still seen."""
    now = now if now is not None else time.time()
    started = rec.get("started_at") or rec.get("updated_at") or 0
    return 0 < (now - started) < BOOTSTRAP_GRACE


def within_teardown_grace(rec, now=None):
    """True while a pr-based lane exited too recently to trust a 'no open PR' read: the PR it just
    created may not be API-visible yet. Gates RESPAWN for pr-open/pr-merged lanes only. Keyed on
    updated_at (a parser field the daemon never rewrites), so the window closes as time passes."""
    now = now if now is not None else time.time()
    ended = rec.get("updated_at") or rec.get("last_activity") or 0
    return 0 < (now - ended) < TEARDOWN_GRACE


RETIRED_DIR = os.path.join(STATE, ".retired")


def lane_retired(project, lane):
    """A lane explicitly retired via `fleet kill --retire`: never respawn it, whatever the unmet
    policy on its record says. Lane-scoped (project__lane) so it outlives the slug a respawn would
    mint — killing the instance without retiring the LANE is exactly what let a zombie come back."""
    return os.path.exists(os.path.join(RETIRED_DIR, f"{project}__{lane}"))


def branch_prefix(lane):
    # spawn names branches fleet/<lane>-<HHMMSS>; a PR's head branch carries the whole run.
    return f"fleet/{lane}-"


def _pr_count(rec, lane, state):
    """Count PRs for an exact recorded head; old pending specs fall back to a narrowed search."""
    repo = rec.get("repo") or _repo_for(rec.get("project"))
    branch = rec.get("branch")
    cmd = ["gh", "pr", "list", "-R", repo, "--state", state, "--limit", "1"]
    if branch:
        cmd += ["--head", branch, "--json", "number", "--jq", "length"]
    else:
        # Pending specs do not currently persist their dependency's exact head. Narrow server-side
        # first, then retain the prefix check for old records until bin/fleet can persist that head.
        prefix = branch_prefix(lane)
        cmd += ["--search", f"head:{prefix}", "--limit", "100", "--json", "headRefName",
                "--jq", f'[.[] | select(.headRefName | startswith("{prefix}"))] | length']
    ok, n = sh_checked(cmd)
    if not ok or not n.isdigit():
        return None
    return int(n)


def has_open_pr(rec, lane):
    """True/False when GitHub answered; None when the duplicate-PR guard is blind."""
    n = _pr_count(rec, lane, "open")
    return None if n is None else n > 0


def outcome_met(rec, contract):
    """Has this lane delivered what `done_when` demands? Lane-keyed, not slug-keyed."""
    if not contract or contract == "exit":
        return None                      # no contract -> not tracked (daemon won't respawn)
    project_repo = rec.get("repo") or _repo_for(rec.get("project"))
    lane = rec.get("lane")
    if contract == "pr-open":
        n = _pr_count({**rec, "repo": project_repo}, lane, "all")
        return None if n is None else n > 0
    if contract == "pr-merged":
        n = _pr_count({**rec, "repo": project_repo}, lane, "merged")
        return None if n is None else n > 0
    if contract.startswith("file:"):
        path = contract[5:]
        if not os.path.isabs(path):
            path = os.path.join(rec.get("worktree", ""), path)
        return os.path.exists(path)
    if contract.startswith("issue-closed:"):
        num = contract.split(":", 1)[1].lstrip("#")
        ok, st = sh_checked(["gh", "issue", "view", num, "-R", project_repo, "--json", "state",
                             "--jq", ".state"])
        if not ok or not st:
            return None                  # UNKNOWN
        return st.upper() == "CLOSED"
    return None


_REF_CACHE = {}   # repo -> (fetched_at, set-of-issue-numbers); TTL-bounded, NOT a default arg


# A PR "delivers" an issue only when it CLOSES it — "Fixes #123" / "Closes #123" / "Resolves #123"
# (GitHub's own closing-keyword grammar). A bare "#123" mention is a cross-reference, not delivery,
# and counting it would falsely mark an issue delivered and HIDE a real drop (the whole point of
# the manifest is to catch drops). The keyword prefix also sidesteps 3-digit hex colours (#012) and
# numeric URL fragments matching as issue numbers.
_CLOSES_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.IGNORECASE)


def referenced_issues(repo, ttl=45):
    """Issue numbers a PR (open or merged) declares it CLOSES. TTL-cached (never frozen for the
    daemon's lifetime — a default-arg cache would report stale references forever, keeping a
    delivered issue 'dropped')."""
    hit = _REF_CACHE.get(repo)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    refs = set()
    for state in ("open", "merged"):
        ok, out = sh_checked(["gh", "pr", "list", "-R", repo, "--state", state, "--limit", "300",
                              "--json", "title,body",
                              "--jq", ".[] | (.title + \" \" + (.body // \"\"))"])
        if not ok:
            return None                  # UNKNOWN — do not let an API failure read as "no PR references"
        for m in _CLOSES_RE.findall(out):
            refs.add(int(m))
    # NEVER cache an empty result: a failed/empty gh call is indistinguishable from "no PRs yet",
    # and freezing empty would classify every issue as dropped until the TTL expired. Re-checking
    # an empty set next tick is two cheap gh calls; a false "dropped" alarm is not cheap.
    if refs:
        _REF_CACHE[repo] = (time.time(), refs)
    return refs


def scope_report(rec, repo):
    """Per-issue delivered/dropped for a lane's --issues manifest. An issue is DELIVERED if it is
    closed or referenced by an open/merged PR; otherwise DROPPED — the 'delivered 1 of 3' bug."""
    raw = (rec.get("issues") or "").strip()
    if not raw:
        return None
    nums = [int(x) for x in re.split(r"[,\s]+", raw) if x.strip().isdigit()]
    if not nums:
        return None
    refs = referenced_issues(repo)
    if refs is None:
        return None                      # UNKNOWN — a blind scope check must not cry "dropped"
    delivered, dropped = [], []
    for n in nums:
        if n in refs:
            delivered.append(n)
            continue
        ok, st = sh_checked(["gh", "issue", "view", str(n), "-R", repo, "--json", "state",
                             "--jq", ".state"])
        if not ok or not st:
            return None                  # UNKNOWN for the whole manifest — better silent than false
        (delivered if st.upper() == "CLOSED" else dropped).append(n)
    return {"delivered": delivered, "dropped": dropped}


def _repo_for(project):
    """Resolve a project's owner/name from the fleet projects registry."""
    reg = os.path.join(os.environ.get("FLEET_CONFIG", os.path.expanduser("~/.config/fleet")),
                       "projects.toml")
    if project and os.path.exists(reg):
        want = False
        for ln in open(reg):
            ln = ln.strip()
            if ln.startswith("[") and ln.strip("[]") == project:
                want = True
            elif ln.startswith("[") and want:
                break
            elif want and ln.startswith("repo"):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _ledger_path(project, lane):
    d = os.path.join(STATE_DIR, ".respawn")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{project}__{lane}.json")


class LaneLockError(Exception):
    """A per-lane lock could not be acquired; other lanes must still reconcile."""

    def __init__(self, path, cause):
        super().__init__(f"{path}: {cause}")
        self.path = path
        self.cause = cause


@contextlib.contextmanager
def _lane_lock(project, lane):
    """Serialize the complete respawn decision for one lane, including the spawn call."""
    lock = None
    path = os.path.join(STATE_DIR, ".respawn", f"{project}__{lane}.json.lock")
    try:
        path = _ledger_path(project, lane) + ".lock"
        lock = open(path, "a+")
        fcntl.flock(lock, fcntl.LOCK_EX)
    except OSError as exc:
        if lock is not None:
            lock.close()
        raise LaneLockError(path, exc) from exc
    try:
        yield
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError as exc:
            print(f"fleet supervisor: cannot unlock lane {project}/{lane}: {exc}",
                  file=sys.stderr)
        lock.close()


@contextlib.contextmanager
def daemon_lock():
    """Non-blocking singleton lock shared by the service loop and manual daemon ticks."""
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "supervisor.lock"), "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_ledger(project, lane):
    """Per-LANE respawn bookkeeping (count, last_respawn), kept in a sidecar keyed by lane — NOT
    on the slug record. A respawn mints a fresh child record with respawn_count=0 that then governs
    the lane; storing counters on the record would reset the cooldown and the give-up cap every
    generation (an unbounded respawn storm). The ledger survives the slug handoff."""
    path = _ledger_path(project, lane)
    if not os.path.exists(path):
        return {"count": 0, "last_respawn": 0}
    led = _read_json_retry(path)
    if not isinstance(led, dict):
        return None
    try:
        return {"count": int(led.get("count", 0)),
                "last_respawn": float(led.get("last_respawn", 0))}
    except (TypeError, ValueError) as exc:
        print(f"fleet supervisor: invalid respawn ledger {path}: {exc}", file=sys.stderr)
        return None


def write_ledger(project, lane, led):
    return _atomic_write_json(_ledger_path(project, lane), led)


def _gate_ledger_path(pending_path):
    directory = os.path.join(STATE_DIR, ".gates")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, os.path.basename(pending_path))


def _pending_identity(path):
    """Identity for one publication of a pending path, including identical later requeues."""
    stat = os.stat(path)
    return {
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _gate_problem(problems, lane, reason, spec=None, **extra):
    problems.append(f"{lane}({reason})")
    record = spec if isinstance(spec, dict) else {"lane": lane}
    append_event(lane, record, f"gate-{reason.split('@', 1)[0]}", reason=reason, **extra)


def _remove_fired_gate(pending_path, ledger_path, spec, problems):
    """Delete an acknowledged pending spec without ever reissuing its spawn."""
    lane = spec.get("lane") or os.path.basename(pending_path)[:-5]
    try:
        os.remove(pending_path)
    except OSError as exc:
        print(f"fleet supervisor: fired gate cannot remove {pending_path}: {exc}",
              file=sys.stderr)
        _gate_problem(problems, lane, "remove-failed", spec, error=str(exc),
                      path=pending_path)
        return False
    try:
        os.remove(ledger_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        # Harmless for correctness: a future publication has a different file identity.
        print(f"fleet supervisor: cannot clean gate ledger {ledger_path}: {exc}",
              file=sys.stderr)
    return True


def latest_per_lane(recs):
    """Newest record per (project, lane) — its policy governs the lane."""
    best = {}
    for r in recs:
        if not r.get("lane"):
            continue
        k = (r.get("project"), r.get("lane"))
        if k not in best or r.get("started_at", 0) > best[k].get("started_at", 0):
            best[k] = r
    return best


def respawn(rec):
    brief = rec.get("brief_path")
    if not brief or not os.path.exists(os.path.expanduser(brief)):
        return False, "no brief_path to respawn from"
    cmd = [FLEET, "spawn", "--project", rec["project"], "--lane", rec["lane"],
           "--engine", rec.get("engine", "codex"), "--brief-file", os.path.expanduser(brief),
           "--restart", rec["restart"], "--done-when", rec.get("done_when", "pr-open")]
    # --issues MUST propagate, or a respawned multi-issue lane's child loses its scope manifest and
    # silently stops being scope-enforced.
    for flag, key in (("--effort", "effort"), ("--model", "model"), ("--by", "spawned_by"), ("--account", "account"),
                      ("--icon", "by_icon"), ("--color", "by_color"), ("--issues", "issues")):
        if rec.get(key):
            cmd += [flag, rec[key]]
    out = sh(cmd, timeout=120)
    return ("spawned" in out), out.splitlines()[0] if out else "spawn produced no output"


def process_pending(problems=None):
    """Fire train/DAG-gated spawns (`fleet spawn --after <lane>[:cond]`) whose dependency has
    delivered. A pending spec in ~/.fleet/pending/<lane>.json is launched and removed once its
    `after` lane meets the condition (default pr-merged).

    A durable attempt marker is published BEFORE spawn. If the daemon dies during the external
    spawn, the next tick reports the ambiguous attempt and fails closed instead of issuing a
    duplicate lane. A successful marker makes failed pending-file deletion safe to retry."""
    pend_dir = os.path.join(STATE, "pending")
    fired = []
    problems = problems if problems is not None else []
    if not os.path.isdir(pend_dir):
        return fired
    for fp in sorted(glob.glob(os.path.join(pend_dir, "*.json"))):
        spec = _read_json_retry(fp, "pending spec")
        lane_hint = os.path.basename(fp)[:-5]
        if not isinstance(spec, dict):
            _gate_problem(problems, lane_hint, "read-failed", path=fp)
            continue
        dep, _, cond = (spec.get("after") or "").partition(":")
        cond = cond or "pr-merged"
        lane = spec.get("lane")
        project = spec.get("project")
        if not dep or not lane or not project:
            detail = "missing after, lane, or project"
            print(f"fleet supervisor: invalid pending spec {fp}: {detail}", file=sys.stderr)
            _gate_problem(problems, lane or lane_hint, "invalid", spec, error=detail, path=fp)
            continue
        repo = _repo_for(project)
        depmet = outcome_met({"lane": dep, "project": project, "repo": repo}, cond)
        if not depmet:
            continue
        try:
            identity = _pending_identity(fp)
            ledger_path = _gate_ledger_path(fp)
            with _lane_lock(".gate", lane):
                ledger = None
                if os.path.exists(ledger_path):
                    ledger = _read_json_retry(ledger_path, "gate ledger")
                    if not isinstance(ledger, dict):
                        _gate_problem(problems, lane, "ledger-read-failed", spec,
                                      path=ledger_path)
                        continue
                if not ledger or ledger.get("pending_identity") != identity:
                    ledger = {"pending_identity": identity, "count": 0, "last_attempt": 0,
                              "state": "pending"}

                state = ledger.get("state")
                if state == "spawned":
                    _remove_fired_gate(fp, ledger_path, spec, problems)
                    continue
                if state == "attempting":
                    detail = "previous spawn outcome is ambiguous"
                    print(f"fleet supervisor: gate {lane} blocked: {detail} ({ledger_path})",
                          file=sys.stderr)
                    _gate_problem(problems, lane, "ambiguous", spec, path=ledger_path)
                    continue

                try:
                    count = int(ledger.get("count", 0))
                    last_attempt = float(ledger.get("last_attempt", 0))
                except (TypeError, ValueError) as exc:
                    print(f"fleet supervisor: invalid gate ledger {ledger_path}: {exc}",
                          file=sys.stderr)
                    _gate_problem(problems, lane, "ledger-read-failed", spec,
                                  error=str(exc), path=ledger_path)
                    continue
                if count >= DEFAULT_MAX:
                    _gate_problem(problems, lane, f"gave-up@{count}", spec,
                                  path=ledger_path)
                    continue
                if time.time() - last_attempt < DEFAULT_COOLDOWN:
                    problems.append(f"{lane}(cooldown)")
                    continue

                attempt = {
                    "pending_identity": identity,
                    "count": count + 1,
                    "last_attempt": time.time(),
                    "state": "attempting",
                }
                if not _atomic_write_json(ledger_path, attempt):
                    _gate_problem(problems, lane, "accounting-failed", spec,
                                  path=ledger_path)
                    continue

                cmd = [FLEET, "spawn", "--project", project, "--lane", lane,
                       "--engine", spec.get("engine", "codex")]
                if spec.get("brief_path"):
                    cmd += ["--brief-file", os.path.expanduser(spec["brief_path"])]
                for flag, key in (("--model", "model"), ("--effort", "effort"), ("--account", "account"),
                                  ("--by", "by"), ("--icon", "icon"), ("--color", "color"),
                                  ("--restart", "restart"), ("--done-when", "done_when"),
                                  ("--issues", "issues")):
                    if spec.get(key):
                        cmd += [flag, spec[key]]
                spawn_ok, out = sh_checked(cmd, timeout=120)
                if not spawn_ok or "spawned" not in out:
                    failed = {**attempt, "state": "failed", "detail": out[:200]}
                    if not _atomic_write_json(ledger_path, failed):
                        _gate_problem(problems, lane, "ambiguous", spec,
                                      path=ledger_path)
                    else:
                        _gate_problem(problems, lane, "spawn-failed", spec,
                                      count=count + 1, detail=out[:200])
                    continue

                spawned = {**attempt, "state": "spawned"}
                if not _atomic_write_json(ledger_path, spawned):
                    # The durable pre-spawn "attempting" marker remains and prevents duplicates.
                    _gate_problem(problems, lane, "ack-write-failed", spec,
                                  path=ledger_path)
                append_event(lane, spec, "gate-fired", after=spec.get("after"),
                             count=count + 1)
                fired.append(f"{lane}<-{spec['after']}")
                _remove_fired_gate(fp, ledger_path, spec, problems)
        except LaneLockError as exc:
            print(f"fleet supervisor: gate lock failed for {project}/{lane}: {exc.cause}",
                  file=sys.stderr)
            _gate_problem(problems, lane, "lock-failed", spec, error=str(exc.cause),
                          path=exc.path)
        except OSError as exc:
            # Stat/ledger-directory failures are accounting failures, not permission to spawn.
            print(f"fleet supervisor: cannot account for pending gate {fp}: {exc}",
                  file=sys.stderr)
            _gate_problem(problems, lane, "accounting-failed", spec, error=str(exc),
                          path=fp)
    return fired


def reconcile(verbose=True):
    gate_waiting = []
    fired = process_pending(gate_waiting)
    recs = load_records()
    governed = latest_per_lane(recs)
    acted, delivered, waiting, dropped_scope, unknown = [], [], [], [], []
    supervised = 0
    for (project, lane), rec in governed.items():
        if lane_retired(project, lane):
            continue                                  # retired by `fleet kill --retire`
        policy = rec.get("restart")
        if not policy or policy == "never":
            continue                                  # not ours to supervise
        supervised += 1
        # Never touch a record while its lane is still running — the parser owns that file, and a
        # supervisor write would race it. All reads/decisions/writes below are for exited lanes.
        if lane_running(recs, project, lane):
            continue
        repo = rec.get("repo") or _repo_for(project)
        # Scope manifest: if the lane owns several issues, the SCOPE is the done condition,
        # overriding done_when. A lane cannot be "delivered" while any issue is dropped.
        scope = scope_report(rec, repo) if rec.get("issues") else None
        if scope is not None:
            if scope != rec.get("scope"):
                rec["scope"] = scope
                _save_record(rec)
            met = not scope["dropped"]
            if scope["dropped"]:
                dropped_scope.append(f"{lane}:{scope['dropped']}")
                append_event(rec.get("slug"), rec, "dropped-scope", dropped=scope["dropped"])
        else:
            met = outcome_met(rec, rec.get("done_when", "pr-open"))
        if met is None:
            # The delivery check could not be answered (API failure / rate limit / no contract).
            # Unknown is NOT "undelivered": respawning here is how a blind supervisor duplicates
            # every lane it governs. Leave the lane alone and try again next tick.
            unknown.append(lane)
            continue
        if met:
            if rec.get("outcome") != "met":
                rec["outcome"] = "met"
                rec["status"] = "delivered"
                _save_record(rec)
                append_event(rec.get("slug"), rec, "delivered")
                # a fresh reuse of this lane name later should start with a clean respawn count
                try:
                    os.remove(_ledger_path(project, lane))
                except OSError:
                    pass
                _RESPAWN_FALLBACK.pop((project, lane), None)
            delivered.append(lane)
            continue
        # An OPEN PR is the deliverable, merely unmerged. `pr-merged` reads that as unmet, but the
        # agent cannot merge its own PR — it needs review, green CI and the queue — so respawning
        # here does not retry the work, it mints a FRESH branch and a DUPLICATE PR, again and
        # again; wait for the open PR to resolve instead.
        # A PR closed unmerged leaves no open PR, so a genuinely dropped lane still respawns.
        # Scoped to pr-merged: a `until-file:` lane may hold an open PR and still owe its report.
        if rec.get("done_when") == "pr-merged":
            open_pr = has_open_pr(rec, lane)
            if open_pr is None:
                unknown.append(lane)
                continue
            if open_pr:
                waiting.append(f"{lane}(pr-open)")
                continue
        # Bootstrap grace: a freshly spawned lane whose unit has not gone active yet is NOT an
        # exited lane — respawning it duplicates a spawn still booting. Wait one tick.
        if within_bootstrap_grace(rec):
            waiting.append(f"{lane}(bootstrap-grace)")
            continue
        # Teardown grace: a pr-based lane that exited moments ago may have opened a PR the GitHub
        # API cannot see yet. Respawning here mints a duplicate branch. Wait for the PR to surface.
        if rec.get("done_when") in ("pr-open", "pr-merged") and within_teardown_grace(rec):
            waiting.append(f"{lane}(teardown-grace)")
            continue
        # exited without delivering -> respawn, bounded by the LANE ledger (survives the child
        # record that a respawn mints and that would otherwise reset these counters every tick).
        try:
            with _lane_lock(project, lane):
                led = read_ledger(project, lane)
                if led is None:
                    waiting.append(f"{lane}(ledger-unreadable)")
                    append_event(rec.get("slug"), rec, "ledger-read-failed")
                    continue
                fallback = _RESPAWN_FALLBACK.get((project, lane), 0)
                count = max(led["count"], fallback)
                # DEFAULT_MAX / DEFAULT_COOLDOWN are the authority (env-tunable): a per-record
                # override cannot work here — a respawn mints a child record that would not carry
                # it — so the cap is held against the LANE ledger that survives the handoff.
                if count >= DEFAULT_MAX:
                    rec["outcome"] = "unmet"
                    rec["status"] = "gave_up"
                    _save_record(rec)
                    waiting.append(f"{lane}(gave-up@{count})")
                    continue
                if time.time() - led["last_respawn"] < DEFAULT_COOLDOWN:
                    waiting.append(f"{lane}(cooldown)")
                    continue
                # Persist the attempt BEFORE spawning. If accounting cannot be vouched for, the only
                # safe action is no spawn: otherwise a full disk re-arms an unbounded per-tick loop.
                next_count = count + 1
                next_ledger = {"count": next_count, "last_respawn": time.time()}
                if not write_ledger(project, lane, next_ledger):
                    _RESPAWN_FALLBACK[(project, lane)] = next_count
                    waiting.append(f"{lane}(ledger-write-failed)")
                    append_event(rec.get("slug"), rec, "ledger-write-failed", count=next_count)
                    continue
                _RESPAWN_FALLBACK[(project, lane)] = next_count
                ok, detail = respawn(rec)
                rec["status"] = "respawned" if ok else "respawn_failed"
                _save_record(rec)
                append_event(rec.get("slug"), rec, "respawned" if ok else "respawn-failed",
                             count=next_count, detail=detail)
                acted.append(f"{lane}->{'ok' if ok else 'FAIL'}({next_count})")
        except LaneLockError as exc:
            print(f"fleet supervisor: lane lock failed for {project}/{lane}: {exc.cause}",
                  file=sys.stderr)
            waiting.append(f"{lane}(lock-failed)")
            append_event(rec.get("slug"), rec, "lane-lock-failed",
                         error=str(exc.cause), path=exc.path)
            continue
    if verbose:
        ts = time.strftime("%H:%M:%S", time.gmtime())
        print(f"[{ts}] supervise: supervised={supervised}/{len(governed)} lanes "
              f"respawned={acted or '-'} delivered={delivered or '-'} "
              f"dropped-scope={dropped_scope or '-'} unknown={unknown or '-'} "
              f"gated-fired={fired or '-'} "
              f"gated-waiting={gate_waiting or '-'} "
              f"waiting={waiting or '-'}", flush=True)
    return {"supervised": supervised, "total_lanes": len(governed),
            "respawned": acted, "delivered": delivered, "dropped_scope": dropped_scope,
            "unknown": unknown, "gate_fired": fired, "gate_waiting": gate_waiting}


def loop(interval):
    print(f"fleet supervisor up (interval {interval}s, cooldown {DEFAULT_COOLDOWN}s, "
          f"max {DEFAULT_MAX}/lane)", flush=True)
    while True:
        try:
            reconcile()
        except Exception as e:
            print(f"[supervise] error: {e}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "loop":
        with daemon_lock() as acquired:
            if acquired:
                loop(int(os.environ.get("FLEET_DAEMON_INTERVAL", "60")))
    else:
        with daemon_lock() as acquired:
            if acquired:
                reconcile()   # one-shot, for `fleet daemon tick` and tests
