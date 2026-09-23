#!/usr/bin/env python3
"""Consume `claude --output-format stream-json` on stdin and keep a live
state file for one fleet agent updated: ~/.fleet/state/<slug>.json.

Defensive about the exact event schema — it extracts what it can and never
crashes the pipeline on an unexpected shape. Detects the terminal `result`
event to mark the agent done and resolve its PR.
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
    # A truncated JSON object often still contains its identity fields before the torn tail.
    # Salvage only JSON strings, decoding escapes through json.loads rather than trusting regex text.
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
    branch = state.get("branch", "")
    wt = state.get("worktree", "")
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


def short_activity(ev):
    """Best-effort one-line 'what is it doing right now'."""
    e = ev.get("event") or {}
    et = e.get("type")
    if et == "content_block_start":
        cb = e.get("content_block", {})
        if cb.get("type") == "tool_use":
            return "tool: " + cb.get("name", "?")
    if et == "content_block_delta":
        d = e.get("delta", {})
        if d.get("type") == "text_delta" and d.get("text", "").strip():
            return d["text"].strip()[:90]
    msg = ev.get("message") or {}
    for c in msg.get("content", []) or []:
        if c.get("type") == "tool_use":
            return "tool: " + c.get("name", "?")
        if c.get("type") == "text" and c.get("text", "").strip():
            return c["text"].strip()[:90]
    return None


def _model_family(name):
    """'claude-opus-5-5[1m]' -> 'claude-opus-5-5', 'claude-haiku-4-5-20251001' -> 'claude-haiku-4-5'.

    The init event may carry a context suffix the API's message.model never does, and an alias
    and its dated snapshot are one model. Only an 8-digit date is dropped: a plain prefix match
    would call claude-opus-5 the same model as claude-opus-5-5."""
    return re.sub(r"-\d{8}$", "", (name or "").split("[", 1)[0].strip().lower())


def _same_model(a, b):
    return _model_family(a) == _model_family(b)


def note_answering_model(state, ev):
    """Record when the model answering is not the one the lane started on.

    A lane can change model mid-run without saying so: a safety flag moves the session to an
    older model, and `--fallback-model` moves it on overload. Either way the card still shows the
    model it was spawned with, and a review that finished on another model reads as if it had
    not. Returns the new model when this event is the first sign of a change, else None."""
    # A subagent's replies ride in the parent stream tagged with the Task call that started it;
    # a sonnet or haiku subagent under an opus lane is the lane working, not the lane moving.
    if ev.get("parent_tool_use_id"):
        return None
    model = (ev.get("message") or {}).get("model")
    # Claude Code stamps its own error and notice messages "<synthetic>": no model answered them.
    if not isinstance(model, str) or not model or model.startswith("<"):
        return None
    started = state.get("model_actual")
    if not isinstance(started, str) or not started:
        state["model_actual"] = model
        return None
    if _same_model(model, started):
        return None
    last = (state.get("model_switch") or {}).get("to")
    if last and _same_model(model, last):
        return None
    state["model_switch"] = {"from": started, "to": model, "at": int(time.time())}
    return model


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

    if t == "system" and ev.get("subtype") == "init":
        s["session_id"] = ev.get("session_id") or s.get("session_id")
        if ev.get("model"):
            s["model_actual"] = ev["model"]
        s["api_key_source"] = ev.get("apiKeySource")

    elif t in ("assistant", "stream_event", "user"):
        a = short_activity(ev)
        if a:
            s["last_activity"] = a
        if t == "assistant":
            switched_to = note_answering_model(s, ev)
            if switched_to:
                append_event(slug, s, "model-switched", model_from=s["model_switch"]["from"],
                             model_to=switched_to)

    elif t == "rate_limit_event":
        # surface quota pressure so the orchestrator can flex the fleet
        s["rate_limit"] = {k: v for k, v in ev.items() if k != "type"}

    elif t == "result":
        s["cost_usd"] = ev.get("total_cost_usd") or ev.get("cost_usd")
        u = ev.get("usage") or {}
        s["tokens_in"] = u.get("input_tokens")
        s["tokens_out"] = u.get("output_tokens")
        s["num_turns"] = ev.get("num_turns")
        s["duration_ms"] = ev.get("duration_ms")
        s["stop_reason"] = ev.get("stop_reason")
        s["result_text"] = (ev.get("result") or "")[:400]
        is_err = bool(ev.get("is_error")) or ev.get("subtype") == "error"
        pr_known, pr = find_pr(s)
        s["pr_url"] = pr
        if is_err:
            s["status"] = "failed"
        elif pr:
            s["status"] = "pr_open"
        elif not pr_known:
            s["status"] = "ended"
            s["pr_lookup"] = "unknown"
        else:
            s["status"] = "done_no_pr"

    save(s)

# stdin closed → the claude process exited. If we never saw a result, mark ended.
if not _saw_event and s.get("status") in ("starting", "running"):
    # Nothing ever arrived on the stream: no session, no turn, no activity. The lane did not finish
    # early, it never began - and "ended" makes those two identical on the card and in `fleet
    # status`, which is how a failed launch gets investigated as a mysterious empty result.
    s["status"] = "failed"
    s["result_text"] = (s.get("result_text")
                        or "claude exited before its first turn - the lane never started")
    save(s)
elif s.get("status") in ("starting", "running"):
    pr_known, pr = find_pr(s)
    s["pr_url"] = pr
    s["status"] = "pr_open" if pr else "ended"
    if not pr_known:
        s["pr_lookup"] = "unknown"
    save(s)
