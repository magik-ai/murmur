#!/usr/bin/env python3
"""Consume `codex exec --json` on stdin and keep the SAME per-agent state file
the Claude parser writes, so the fleet, dashboard and capacity guard stay
engine-agnostic.

Codex event stream (verified live):
    thread.started {thread_id}
  → turn.started
  → item.completed {item:{type, text|command|…}}   (repeats)
  → turn.completed {usage:{input_tokens, output_tokens, …}}   ← terminal

Codex reports no dollar cost (it runs on the ChatGPT subscription), so
`cost_usd` stays null for codex agents; tokens come from turn.completed.
"""
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
_last_emitted = {"v": None}
_state_blocked = {"v": False}

STATE = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))
slug = sys.argv[1]
statefile = os.path.join(STATE, "state", slug + ".json")
lastfile = os.path.join(STATE, "logs", slug + ".last")


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
    if st and st != _last_emitted["v"]:
        _last_emitted["v"] = st
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


def activity(item):
    """One line of 'what is it doing right now' from a Codex item."""
    kind = item.get("type") or "item"
    for key in ("command", "text", "path", "message", "title"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return f"{kind}: {v.strip()[:80]}"
    return kind


s = load()
s["status"] = "running"
save(s)

_saw_event = False
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
        _saw_event = True
    except Exception:
        continue
    t = ev.get("type")

    if t == "thread.started":
        s["session_id"] = ev.get("thread_id") or s.get("session_id")

    elif t == "item.completed":
        a = activity(ev.get("item") or {})
        if a:
            s["last_activity"] = a

    elif t == "turn.completed":
        u = ev.get("usage") or {}
        s["tokens_in"] = u.get("input_tokens")
        s["tokens_out"] = u.get("output_tokens")
        pr_known, pr = find_pr(s)
        s["pr_url"] = pr
        if pr:
            s["status"] = "pr_open"
        elif pr_known:
            s["status"] = "done_no_pr"
        else:
            s["status"] = "ended"
            s["pr_lookup"] = "unknown"

    elif t in ("error", "turn.failed"):
        s["status"] = "failed"
        s["result_text"] = str(ev)[:400]

    save(s)

# stdin closed → codex exited. Settle the status and pick up its final message.
if not _saw_event and s.get("status") in ("starting", "running"):
    # Nothing ever arrived on the stream: no session, no turn, no activity. The lane did not finish
    # early, it never began - and "ended" makes those two identical on the card and in `fleet
    # status`, which is how a failed launch gets investigated as a mysterious empty result.
    s["status"] = "failed"
    s["result_text"] = (s.get("result_text")
                        or "codex exited before its first turn - the lane never started")
elif s.get("status") in ("starting", "running"):
    pr_known, pr = find_pr(s)
    s["pr_url"] = pr
    s["status"] = "pr_open" if pr else "ended"
    if not pr_known:
        s["pr_lookup"] = "unknown"
if os.path.exists(lastfile):
    try:
        s["result_text"] = open(lastfile).read().strip()[:400]
    except Exception:
        pass
save(s)
