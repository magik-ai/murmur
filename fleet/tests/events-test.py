#!/usr/bin/env python3
"""End-to-end: the patched parser still writes the record correctly AND emits events; the reader
filters by --since/--lane. Isolated FLEET_STATE — never touches the real farm."""
import json
import os
import subprocess
import sys
import tempfile

# The library under test is this checkout's, not whatever lives at a fixed path: a suite that
# exercises another checkout reports on code nobody changed.
FLEET_HOME = os.environ.get("FLEET_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLEET_LIB = os.path.join(os.path.expanduser(FLEET_HOME), "lib")
if not os.path.isfile(os.path.join(FLEET_LIB, "events.py")):
    raise SystemExit(f"no lib/events.py under {FLEET_HOME}: pass the checkout in FLEET_HOME")
ROOT = tempfile.mkdtemp(prefix="fleet-events-test-")
os.makedirs(os.path.join(ROOT, "state"))
os.makedirs(os.path.join(ROOT, "logs"))
slug = "demo-lane-120000-9999"

# seed the record the way spawn would (so the parser has lane/branch/worktree)
json.dump({"slug": slug, "project": "p", "lane": "demo-lane", "engine": "codex",
           "branch": "fleet/demo-lane-120000", "worktree": "/nonexistent",
           "status": "starting"},
          open(os.path.join(ROOT, "state", slug + ".json"), "w"))

# a synthetic codex --json stream: thread start -> work -> turn.completed (terminal)
stream = "\n".join(json.dumps(x) for x in [
    {"type": "thread.started", "thread_id": "t1"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}},
    {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 50}},
]) + "\n"

env = dict(os.environ, FLEET_STATE=ROOT)
r = subprocess.run([sys.executable, os.path.join(FLEET_LIB, "parse_codex.py"), slug],
                   input=stream, env=env, capture_output=True, text=True)

ok = True
def check(name, cond, detail=""):
    global ok
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    ok = ok and cond

if r.returncode != 0:
    print("  parser CRASHED:", r.stderr[:300]); sys.exit(1)

rec = json.load(open(os.path.join(ROOT, "state", slug + ".json")))
check("record still written (status settled)", rec.get("status") in ("done_no_pr", "pr_open", "ended"), rec.get("status"))
check("tokens captured (parser logic intact)", rec.get("tokens_out") == 50, str(rec.get("tokens_out")))

evpath = os.path.join(ROOT, "events.jsonl")
check("events.jsonl created", os.path.exists(evpath))
evs = [json.loads(l) for l in open(evpath)] if os.path.exists(evpath) else []
kinds = [e.get("status") for e in evs if e.get("kind") == "status"]
check("emitted running -> terminal transitions", "running" in kinds and any(k in kinds for k in ("done_no_pr", "ended")), str(kinds))
check("one event per status (deduped, not per line)", len(kinds) == len(set(kinds)), str(kinds))
check("events carry lane+project", all(e.get("lane") == "demo-lane" and e.get("project") == "p" for e in evs))

# reader: --since filters, --lane filters, --json shape
out = subprocess.run([sys.executable, os.path.join(FLEET_LIB, "events.py"),
                      "--lane", "demo-lane", "--json"], env=env, capture_output=True, text=True).stdout
lines = [json.loads(l) for l in out.strip().splitlines() if l.strip()]
check("reader --lane returns this lane's events", len(lines) == len(evs) and lines[0]["lane"] == "demo-lane")
out2 = subprocess.run([sys.executable, os.path.join(FLEET_LIB, "events.py"),
                       "--lane", "other-lane", "--json"], env=env, capture_output=True, text=True).stdout
check("reader --lane filters OUT other lanes", out2.strip() == "")
future = evs[-1]["ts"] + 10
out3 = subprocess.run([sys.executable, os.path.join(FLEET_LIB, "events.py"),
                       "--since", str(future), "--json"], env=env, capture_output=True, text=True).stdout
check("reader --since (future) returns nothing", out3.strip() == "")

print("\nRESULT:", "ALL PASS" if ok else "FAILURES ABOVE")
subprocess.run(["rm", "-rf", ROOT])
sys.exit(0 if ok else 1)
