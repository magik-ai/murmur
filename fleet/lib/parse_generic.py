#!/usr/bin/env python3
"""Engine-agnostic parser for a generic model CLI (qwen, etc). It does not try to understand the
model's JSON shape — it keeps the SAME per-agent state file the other parsers write by tracking
the last non-empty line as activity and settling status on close via find_pr. Enough for the
fleet, dashboard, capacity guard and event stream to treat any CLI uniformly."""
import json
import os
import re
import subprocess
import sys
import time

STATE = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))
slug = sys.argv[1]
statefile = os.path.join(STATE, "state", slug + ".json")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from events import append_event
except Exception:
    def append_event(*a, **k):
        pass
_last = {"v": None}
_state_blocked = {"v": False}


def load():
    try:
        with open(statefile) as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            raise ValueError("state record is not a JSON object")
        return state
    except FileNotFoundError:
        return _fallback_state()
    except Exception as exc:
        try:
            with open(statefile, errors="replace") as handle:
                raw = handle.read(65536)
        except OSError:
            raw = ""
        state = _fallback_state(raw)
        if not _liveness_vouched(state):
            # Keep the unreadable record at its canonical path. Sweep treats that as an ABORT,
            # while replacing it with a parseable record lacking branch/worktree would re-arm
            # deletion of this parser's own live worktree.
            _state_blocked["v"] = True
            detail = "missing project and/or branch/worktree liveness identity"
            print(f"fleet parser: refusing to replace unreadable state {statefile}: "
                  f"{exc}; {detail}", file=sys.stderr, flush=True)
            append_event(slug, state, "state-read-failed", state_path=statefile,
                         recovery="blocked-missing-liveness")
            return state
        quarantine = f"{statefile}.corrupt.{time.time_ns()}.{os.getpid()}"
        try:
            os.replace(statefile, quarantine)
        except OSError as quarantine_exc:
            _state_blocked["v"] = True
            print(f"fleet parser: cannot read or quarantine {statefile}: "
                  f"{exc}; {quarantine_exc}", file=sys.stderr, flush=True)
            return _fallback_state(raw)
        print(f"fleet parser: quarantined unreadable state at {quarantine}: {exc}",
              file=sys.stderr, flush=True)
        append_event(slug, state, "state-read-failed", quarantined=quarantine)
        return state


def _fallback_state(raw=""):
    parts = slug.rsplit("-", 2)
    state = {"slug": slug}
    if len(parts) == 3:
        state["lane"] = parts[0]
    if os.environ.get("FLEET_PROJECT"):
        state["project"] = os.environ["FLEET_PROJECT"]
    for key in ("lane", "project", "branch", "worktree", "engine", "brief_path",
                "restart", "done_when", "issues", "spawned_by"):
        match = re.search(rf'"{key}"\s*:\s*("(?:\\.|[^"\\])*")', raw)
        if match:
            try:
                state[key] = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
    return state


def _liveness_vouched(state):
    """Sweep can protect a live lane only when project plus branch or worktree survived."""
    return bool(state.get("project") and (state.get("branch") or state.get("worktree")))


def _write_state(s):
    directory = os.path.dirname(statefile)
    os.makedirs(directory, exist_ok=True)
    tmp = f"{statefile}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(tmp, "x") as f:
            json.dump(s, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, statefile)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def save(s):
    s["updated_at"] = int(time.time())
    if _state_blocked["v"]:
        append_event(slug, s, "state-write-failed", error="unreadable record not quarantined")
        return False
    last = None
    for attempt in range(2):
        try:
            _write_state(s)
            break
        except Exception as exc:
            last = exc
            if attempt == 0:
                time.sleep(0.05)
    else:
        print(f"fleet parser: state write failed for {statefile}: {last}",
              file=sys.stderr, flush=True)
        append_event(slug, s, "state-write-failed", error=str(last))
        return False
    st = s.get("status")
    if st and st != _last["v"]:
        _last["v"] = st
        append_event(slug, s, "status", status=st, pr=s.get("pr_url"),
                     activity=s.get("last_activity"))
    return True


def find_pr(state):
    branch, wt = state.get("branch", ""), state.get("worktree", "")
    if not branch or not os.path.isdir(wt):
        return True, None
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--json", "url", "--limit", "1"],
            cwd=wt, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            return False, None
        arr = json.loads(result.stdout or "[]")
        return True, arr[0]["url"] if arr else None
    except Exception:
        return False, None


s = load()
s["status"] = "running"
save(s)

_saw_event = False
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    # try to pull human text out of a json line; else use the raw line
    act = line
    try:
        o = json.loads(line)
        _saw_event = True
        if isinstance(o, dict):
            for k in ("text", "message", "content", "delta", "command", "output"):
                v = o.get(k)
                if isinstance(v, str) and v.strip():
                    act = v.strip()
                    break
    except Exception:
        pass
    s["last_activity"] = act[:120]
    save(s)

if not _saw_event and s.get("status") in ("starting", "running"):
    # Nothing ever arrived on the stream: no session, no turn, no activity. The lane did not finish
    # early, it never began - and "ended" makes those two identical on the card and in `fleet
    # status`, which is how a failed launch gets investigated as a mysterious empty result.
    s["status"] = "failed"
    s["result_text"] = (s.get("result_text")
                        or "the engine exited before its first turn - the lane never started")
    save(s)
elif s.get("status") in ("starting", "running"):
    pr_known, pr = find_pr(s)
    s["pr_url"] = pr
    s["status"] = "pr_open" if pr else "ended"
    if not pr_known:
        s["pr_lookup"] = "unknown"
save(s)
