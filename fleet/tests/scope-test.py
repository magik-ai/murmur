#!/usr/bin/env python3
"""Scope-manifest enforcement (P0-4) in a throwaway FLEET_STATE with a stubbed `gh` — proves a
lane with --issues cannot 'deliver' while any issue is dropped, and that delivered/dropped is
classified correctly. Never touches the real farm."""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = tempfile.mkdtemp(prefix="fleet-scope-test-")
STATE = os.path.join(ROOT, "state")
os.makedirs(STATE)
os.makedirs(os.path.join(ROOT, "briefs"))
brief = os.path.join(ROOT, "briefs", "b.md")
open(brief, "w").write("brief")

# stub `gh`: PR list references #101 and #102 (open/merged); issue 103 is CLOSED; 104 is OPEN.
BIN = os.path.join(ROOT, "bin")
os.makedirs(BIN)
gh = os.path.join(BIN, "gh")
open(gh, "w").write(r'''#!/usr/bin/env python3
import sys
a = sys.argv[1:]
# gh pr list ... --jq '.[] | (.title + " " + (.body//""))'
if a[:2] == ["pr", "list"]:
    # merged state returns nothing; open state returns two refs
    if "merged" in a:
        print("")
    else:
        print("fixes #101 and closes #102")   # closing keywords -> both count as delivered
    sys.exit(0)
# gh issue view N --json state --jq .state
if a[:2] == ["issue", "view"]:
    n = a[2]
    print("CLOSED" if n == "103" else "OPEN")
    sys.exit(0)
print("")
''')
os.chmod(gh, 0o755)

# stub `fleet` spawn (records calls)
STUB = os.path.join(BIN, "fleet")
calls = os.path.join(ROOT, "spawn-calls.log")
open(STUB, "w").write(f'#!/bin/bash\necho "$@" >> {calls}\necho "spawned stub"\n')
os.chmod(STUB, 0o755)


# started_at an hour ago: a lane that has run and exited. A record started "now" sits inside the
# supervisor's bootstrap grace (FLEET_BOOTSTRAP_GRACE, 120 s), which holds every respawn, so the
# respawn assertion below would measure the grace instead of the scope check.
def rec(slug, lane, **extra):
    r = {"slug": slug, "project": "p", "lane": lane, "engine": "codex", "repo": "o/r",
         "worktree": ROOT, "started_at": int(time.time()) - 3600, "status": "starting",
         "brief_path": brief, "respawn_count": 0}
    r.update(extra)
    json.dump(r, open(os.path.join(STATE, slug + ".json"), "w"))


# Lane with 4 issues: 101,102 referenced by a PR; 103 closed; 104 open+unreferenced = DROPPED.
rec("s-1", "lane-scope", restart="until-merged", issues="101,102,103,104")
# Lane fully covered: 101 (referenced), 103 (closed) -> all delivered.
rec("s-2", "lane-done", restart="until-merged", issues="101,103")

env = dict(os.environ, FLEET_STATE=ROOT, FLEET_BIN=STUB, FLEET_CONFIG=ROOT,
           PATH=BIN + ":" + os.environ["PATH"])

def _require(path, wanted, hint):
    """A suite pointed at the wrong file measures nothing and reports it as a failure of the code."""
    import os as _os
    import sys as _sys
    name = _os.path.basename(path)
    if name != wanted:
        _sys.exit(f"{_sys.argv[0]}: expected a path to {wanted}, got {path!r}.\n"
                  f"  {hint}\n"
                  f"  Refusing to run: the result would be meaningless, not merely wrong.")
    if not _os.path.exists(path):
        _sys.exit(f"{_sys.argv[0]}: {path} does not exist.")
    return path

SUP = _require(
    os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/work/fleet/lib/supervisor.py"),
    "supervisor.py",
    "This suite drives the supervisor directly; bin/fleet cannot be run by python3.")
out = subprocess.run([sys.executable, SUP], env=env, capture_output=True, text=True)
print("tick:", out.stdout.strip())
if out.stderr.strip():
    print("STDERR:", out.stderr.strip()[:300])

s1 = json.load(open(os.path.join(STATE, "s-1.json")))
s2 = json.load(open(os.path.join(STATE, "s-2.json")))
spawned = open(calls).read().splitlines() if os.path.exists(calls) else []

ok = True
def check(name, cond):
    global ok
    print(("  PASS " if cond else "  FAIL ") + name); ok = ok and cond

check("scope delivered = [101,102,103]", s1.get("scope", {}).get("delivered") == [101, 102, 103])
check("scope dropped = [104]", s1.get("scope", {}).get("dropped") == [104])
check("dropped-scope lane respawned (not abandoned)", any("lane-scope" in c for c in spawned))
check("dropped-scope lane NOT marked delivered", s1.get("status") != "delivered")
check("fully-covered lane delivered", s2.get("outcome") == "met" and s2.get("status") == "delivered")
check("fully-covered lane NOT respawned", not any("lane-done" in c for c in spawned))
check("dropped-scope surfaced in heartbeat", "lane-scope:[104]" in out.stdout)

print("\nRESULT:", "ALL PASS" if ok else "FAILURES ABOVE")
subprocess.run(["rm", "-rf", ROOT])
sys.exit(0 if ok else 1)
