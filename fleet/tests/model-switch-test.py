#!/usr/bin/env python3
"""The stream parser notices when the model answering a lane is not the one it started on.

Both directions: a lane that stays on its model (including the alias/snapshot and context-suffix
spellings of one model, and Claude Code's own "<synthetic>" notices) must record nothing, or every
card would cry wolf; a lane moved to another model mid-run must say so once, in its record and in
the event log. Isolated FLEET_STATE, never touches the real farm."""
import json
import os
import subprocess
import sys
import tempfile

# This checkout's parser, never the installed one: on the farm FLEET_HOME points at the live copy.
PARSER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "parse_stream.py")

P = F = 0


def check(ok, name, got=None):
    global P, F
    if ok:
        P += 1
        print(f"  PASS  {name}")
    else:
        F += 1
        print(f"  FAIL  {name} -- got: {got}")


def assistant(model, text="working", parent=None):
    ev = {"type": "assistant", "parent_tool_use_id": parent,
          "message": {"model": model, "content": [{"type": "text", "text": text}]}}
    if parent:
        ev["subagent_type"] = "Explore"
    return ev


def run(slug, events):
    root = tempfile.mkdtemp(prefix="fleet-model-switch-test-")
    os.makedirs(os.path.join(root, "state"))
    json.dump({"slug": slug, "project": "p", "lane": slug, "engine": "claude", "model": "opus",
               "branch": "", "worktree": "/nonexistent", "status": "starting"},
              open(os.path.join(root, "state", slug + ".json"), "w"))
    stream = "\n".join(json.dumps(e) for e in events) + "\n"
    proc = subprocess.run([sys.executable, PARSER, slug], input=stream, text=True,
                          env={**os.environ, "FLEET_STATE": root}, capture_output=True, timeout=30)
    # A crashed parser leaves the record untouched, which every "records nothing" check would pass.
    check(proc.returncode == 0, f"{slug}: parser exited cleanly", proc.stderr[-300:])
    state = json.load(open(os.path.join(root, "state", slug + ".json")))
    log = os.path.join(root, "events.jsonl")
    switched = []
    if os.path.exists(log):
        switched = [e for e in map(json.loads, open(log)) if e.get("kind") == "model-switched"]
    return state, switched


INIT = {"type": "system", "subtype": "init", "session_id": "s1", "model": "claude-opus-5-5[1m]"}
RESULT = {"type": "result", "subtype": "success", "result": "done"}

print("=== a lane that stays on its model records nothing ===")
state, ev = run("steady", [INIT, assistant("claude-opus-5-5"),
                           assistant("<synthetic>", "API Error: overloaded"),
                           assistant("claude-opus-5-5"), RESULT])
check("model_switch" not in state, "same model, context suffix and a synthetic notice: no switch",
      state.get("model_switch"))
check(ev == [], "no model-switched event", ev)

state, ev = run("subagent", [INIT, assistant("claude-opus-5-5"),
                             assistant("claude-haiku-4-5-20251001", "exploring", parent="toolu_1"),
                             assistant("claude-opus-5-5"), RESULT])
check("model_switch" not in state, "a haiku subagent under an opus lane: no switch",
      state.get("model_switch"))
check(ev == [], "no model-switched event for a subagent", ev)

state, ev = run("snapshot", [{**INIT, "model": "claude-haiku-4-5"},
                             assistant("claude-haiku-4-5-20251001"), RESULT])
check("model_switch" not in state, "alias vs dated snapshot of one model: no switch",
      state.get("model_switch"))

print("=== a lane moved to another model says so, once ===")
state, ev = run("flagged", [INIT, assistant("claude-opus-5-5"), assistant("claude-opus-5"),
                            assistant("claude-opus-5"), RESULT])
sw = state.get("model_switch") or {}
check(sw.get("from") == "claude-opus-5-5[1m]" and sw.get("to") == "claude-opus-5",
      "record names from and to", sw)
check(len(ev) == 1 and ev[0].get("model_to") == "claude-opus-5",
      "exactly one model-switched event", ev)

state, ev = run("twice", [INIT, assistant("claude-opus-5"), assistant("claude-sonnet-5"), RESULT])
check((state.get("model_switch") or {}).get("to") == "claude-sonnet-5",
      "a second move updates the record", state.get("model_switch"))
check(len(ev) == 2, "each new model is one event", ev)

print("=== no init model: the first answer is the baseline ===")
state, ev = run("noinit", [{"type": "system", "subtype": "init", "session_id": "s1"},
                           assistant("claude-sonnet-5"), assistant("claude-sonnet-5"), RESULT])
check("model_switch" not in state and state.get("model_actual") == "claude-sonnet-5",
      "baseline taken from the first answer", state)

print(f"\nRESULT pass={P} fail={F}")
sys.exit(1 if F else 0)
