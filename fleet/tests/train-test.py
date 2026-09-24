#!/usr/bin/env python3
"""Train/DAG gate (P1-5) in isolation: a pending spec fires only once its dependency lane meets
the condition. Stubbed gh + spawn; never touches the farm."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = tempfile.mkdtemp(prefix="fleet-train-test-")
os.makedirs(os.path.join(ROOT, "state"))
os.makedirs(os.path.join(ROOT, "pending"))
BIN = os.path.join(ROOT, "bin")
os.makedirs(BIN)

# stub gh: dep lane "lane-a" has a MERGED PR (headRefName fleet/lane-a-...); "lane-x" has none.
gh = os.path.join(BIN, "gh")
open(gh, "w").write(r'''#!/usr/bin/env python3
import sys
a = sys.argv[1:]
if a[:2] == ["pr", "list"]:
    merged = "merged" in a
    # emulate --jq length of PRs whose head starts with the queried branch prefix
    jq = a[a.index("--jq")+1] if "--jq" in a else ""
    if "fleet/lane-a-" in jq and merged:
        print("1")
    else:
        print("0")
    sys.exit(0)
print("")
''')
os.chmod(gh, 0o755)

# stub fleet spawn: record the call
calls = os.path.join(ROOT, "spawn-calls.log")
STUB = os.path.join(BIN, "fleet")
open(STUB, "w").write(f'#!/bin/bash\necho "$@" >> {calls}\necho "spawned stub"\n')
os.chmod(STUB, 0o755)

brief = os.path.join(ROOT, "b.md"); open(brief, "w").write("brief")


def pending(lane, after):
    json.dump({"lane": lane, "project": "p", "after": after, "engine": "codex",
               "brief_path": brief, "restart": "until-merged", "done_when": "pr-merged",
               "effort": "xhigh", "by": "tester"},
              open(os.path.join(ROOT, "pending", lane + ".json"), "w"))


# B waits on lane-a (merged -> should fire); C waits on lane-x (not merged -> should NOT fire)
pending("lane-b", "lane-a:pr-merged")
pending("lane-c", "lane-x:pr-merged")

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
    os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "supervisor.py")),
    "supervisor.py",
    "This suite drives the supervisor directly; bin/fleet cannot be run by python3.")
out = subprocess.run([sys.executable, SUP], env=env, capture_output=True, text=True)
print("tick:", out.stdout.strip())
if out.stderr.strip():
    print("STDERR:", out.stderr.strip()[:300])

spawned = open(calls).read() if os.path.exists(calls) else ""
b_gone = not os.path.exists(os.path.join(ROOT, "pending", "lane-b.json"))
c_stays = os.path.exists(os.path.join(ROOT, "pending", "lane-c.json"))

ok = True
def chk(n, c):
    global ok; print(("  PASS " if c else "  FAIL ") + n); ok = ok and c

chk("dep-met gate FIRED (spawn called for lane-b)", "lane-b" in spawned)
chk("fired spec removed", b_gone)
chk("fired spawn carried the policy (--restart until-merged)", "until-merged" in spawned and "--brief-file" in spawned)
chk("dep-UNmet gate did NOT fire (lane-c)", "lane-c" not in spawned)
chk("unmet spec stays pending", c_stays)
chk("heartbeat shows gated-fired", "gated-fired=['lane-b<-lane-a:pr-merged']" in out.stdout)

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
subprocess.run(["rm", "-rf", ROOT])
sys.exit(0 if ok else 1)
