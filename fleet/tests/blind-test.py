#!/usr/bin/env python3
"""Regression guard for the 'blind supervisor duplicates' incident: when the GitHub API fails
(rate limit / outage), a delivery check must return UNKNOWN and the daemon must NOT respawn.
Before the fix, a failed `gh` returned "" which read as 'not delivered' -> respawn storm ->
duplicate lanes and duplicate PRs."""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = tempfile.mkdtemp(prefix="fleet-blind-test-")
os.makedirs(os.path.join(ROOT, "state"))
BIN = os.path.join(ROOT, "bin")
os.makedirs(BIN)

# stub gh that FAILS like a rate-limited API: non-zero exit, empty stdout, error on stderr
gh = os.path.join(BIN, "gh")
open(gh, "w").write('#!/bin/bash\necho "API rate limit exceeded" >&2\nexit 1\n')
os.chmod(gh, 0o755)

calls = os.path.join(ROOT, "spawn-calls.log")
STUB = os.path.join(BIN, "fleet")
open(STUB, "w").write(f'#!/bin/bash\necho "$@" >> {calls}\necho "spawned stub"\n')
os.chmod(STUB, 0o755)

brief = os.path.join(ROOT, "b.md"); open(brief, "w").write("brief")


def rec(slug, lane, **extra):
    r = {"slug": slug, "project": "p", "lane": lane, "engine": "codex", "repo": "o/r",
         "worktree": ROOT, "started_at": int(time.time()), "status": "ended",
         "brief_path": brief, "respawn_count": 0}
    r.update(extra)
    json.dump(r, open(os.path.join(ROOT, "state", slug + ".json"), "w"))


# a governed lane whose delivery can only be answered by gh — and gh is down
rec("a-1", "lane-pr", restart="until-merged", done_when="pr-merged")
# a governed multi-issue lane — its scope check also needs gh
rec("b-1", "lane-scope", restart="until-merged", issues="101,102")

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
a = json.load(open(os.path.join(ROOT, "state", "a-1.json")))
b = json.load(open(os.path.join(ROOT, "state", "b-1.json")))

ok = True
def chk(n, c):
    global ok; print(("  PASS " if c else "  FAIL ") + n); ok = ok and c

chk("API down -> NO respawn (the storm that duplicated lanes)", "lane-pr" not in spawned)
chk("API down -> scope lane NOT respawned either", "lane-scope" not in spawned)
chk("API down -> lane NOT falsely marked delivered", a.get("outcome") != "met")
chk("API down -> scope NOT falsely reported dropped", not b.get("scope"))
chk("heartbeat reports unknown, not silence", "unknown=" in out.stdout and "lane-pr" in out.stdout)
chk("nothing spawned at all", spawned.strip() == "")

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
subprocess.run(["rm", "-rf", ROOT])
sys.exit(0 if ok else 1)
