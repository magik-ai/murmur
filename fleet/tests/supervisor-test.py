#!/usr/bin/env python3
"""Exercise the supervisor's decision logic in a THROWAWAY FLEET_STATE with a stub spawn — so it
never touches the hot farm and never really spawns. Proves: opt-in skip, deliver-on-outcome,
respawn-on-exit, cooldown, give-up cap."""
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = tempfile.mkdtemp(prefix="fleet-sup-test-")
STATE = os.path.join(ROOT, "state")
os.makedirs(STATE)
os.makedirs(os.path.join(ROOT, "briefs"))
brief = os.path.join(ROOT, "briefs", "b.md")
open(brief, "w").write("test brief")

# a stub `fleet` that records the call AND writes a fresh CHILD state record with respawn_count=0
# and a newer started_at (outside the bootstrap grace, see below) — exactly like real cmd_spawn. This is what makes the child govern the
# lane next tick, and is what the earlier (weaker) stub missed, hiding the respawn-storm bug.
STUB = os.path.join(ROOT, "fleet-stub")
calls = os.path.join(ROOT, "spawn-calls.log")
open(STUB, "w").write(f'''#!/usr/bin/env python3
import sys, os, json, time
a = sys.argv[1:]
open("{calls}", "a").write(" ".join(a) + "\\n")
# parse --lane/--project/--restart/--issues out of the spawn args, mint a child record
kv = {{}}
i = 0
while i < len(a):
    if a[i].startswith("--") and i + 1 < len(a) and not a[i+1].startswith("--"):
        kv[a[i][2:]] = a[i+1]; i += 2
    else:
        i += 1
lane = kv.get("lane", "x"); proj = kv.get("project", "p")
slug = f"{{lane}}-child-{{int(time.time()*1000)%100000}}"
rec = {{"slug": slug, "project": proj, "lane": lane, "engine": kv.get("engine","codex"),
       "repo": "o/r", "worktree": "{ROOT}", "brief_path": "{brief}",
       "restart": kv.get("restart"), "done_when": kv.get("done-when"),
       "issues": kv.get("issues"), "respawn_count": 0, "status": "starting",
       # Newer than the parent record (now - 300), so the child governs the lane, and older than
       # the bootstrap grace (120 s), so the next tick sees an exited child rather than one still
       # booting. The earlier value, one second in the FUTURE, sat outside grace only while the
       # next tick landed inside that second; a slower machine turned the storm case into a lane
       # waiting out its grace for ever, and the suite flaked on CI.
       "started_at": int(time.time()) - 200}}
json.dump(rec, open(os.path.join("{STATE}", slug + ".json"), "w"))
print("spawned " + slug)
''')
os.chmod(STUB, 0o755)

b_file = os.path.join(ROOT, "b-delivered.txt")   # stays ABSENT -> B must respawn
c_file = os.path.join(ROOT, "c-delivered.txt")   # created below  -> C must deliver


def rec(slug, lane, **extra):
    # exited lanes started in the PAST (they ran, then exited); default them past the bootstrap
    # grace so the respawn path is exercised. A fresh spawn overrides started_at explicitly.
    r = {"slug": slug, "project": "p", "lane": lane, "engine": "codex", "repo": "o/r",
         "worktree": ROOT, "started_at": int(time.time()) - 300, "status": "starting",
         "brief_path": brief, "respawn_count": 0}
    r.update(extra)
    json.dump(r, open(os.path.join(STATE, slug + ".json"), "w"))


# A: no policy -> must be ignored entirely
rec("a-1", "lane-a")
# B: until-file, file ABSENT, unit inactive -> must respawn
rec("b-1", "lane-b", restart="until-file:" + b_file, done_when="file:" + b_file)
# C: until-file, file PRESENT -> must mark delivered, never respawn
open(c_file, "w").write("done")
rec("c-1", "lane-c", restart="until-file:" + c_file, done_when="file:" + c_file)
# E: until-file ABSENT but just spawned (unit still booting) -> must NOT respawn yet (bootstrap grace)
rec("e-1", "lane-e", restart="until-file:/no/such/e", done_when="file:/no/such/e",
    started_at=int(time.time()))
# F: until-file ABSENT and old (would respawn) but the LANE was retired via `kill --retire` -> skip
rec("f-1", "lane-f", restart="until-file:/no/such/f", done_when="file:/no/such/f")
os.makedirs(os.path.join(ROOT, ".retired"), exist_ok=True)
open(os.path.join(ROOT, ".retired", "p__lane-f"), "w").close()

env = dict(os.environ, FLEET_STATE=ROOT, FLEET_BIN=STUB, FLEET_CONFIG=ROOT,
           FLEET_RESPAWN_MAX="3")   # process-wide cap (env-tunable), applies to children too

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


def tick():
    return subprocess.run([sys.executable, SUP], env=env, capture_output=True, text=True).stdout.strip()


print("tick 1:", tick())
spawned = open(calls).read().splitlines() if os.path.exists(calls) else []
b_respawned = any("lane-b" in c for c in spawned)
c_respawned = any("lane-c" in c for c in spawned)
a_touched = any("lane-a" in c for c in spawned)
c_rec = json.load(open(os.path.join(STATE, "c-1.json")))

ok = True
def check(name, cond):
    global ok
    print(("  PASS " if cond else "  FAIL ") + name); ok = ok and cond

check("A (no policy) never touched", not a_touched)
check("B (outcome unmet) respawned", b_respawned)
check("C (outcome met) NOT respawned", not c_respawned)
check("C marked delivered", c_rec.get("outcome") == "met" and c_rec.get("status") == "delivered")
e_respawned = any("lane-e" in c for c in spawned)
check("E (fresh spawn, unit still booting) NOT respawned — bootstrap grace", not e_respawned)
f_respawned = any("lane-f" in c for c in spawned)
check("F (retired lane) NOT respawned despite unmet policy — kill --retire", not f_respawned)

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("sup_under_test", SUP)
_sup = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_sup)
check("grace: a fresh record is within grace", _sup.within_bootstrap_grace({"started_at": time.time() - 5}))
check("grace: an old record is past grace", not _sup.within_bootstrap_grace({"started_at": time.time() - 300}))
check("grace: a missing timestamp is NOT grace (no eternal skip of stale debris)",
      not _sup.within_bootstrap_grace({"started_at": 0}))
_sup.RETIRED_DIR = os.path.join(ROOT, ".retired")
check("retire: a retired lane is recognised", _sup.lane_retired("p", "lane-f"))
check("retire: a non-retired lane is not", not _sup.lane_retired("p", "lane-b"))

# teardown grace: a pr-based lane that exited seconds ago must not be respawned — its PR (gh create)
# may not be API-visible yet. Keyed on updated_at, a parser field the daemon never rewrites.
check("teardown: a just-exited lane is within grace",
      _sup.within_teardown_grace({"updated_at": time.time() - 10}))
check("teardown: a long-exited lane is past grace",
      not _sup.within_teardown_grace({"updated_at": time.time() - 300}))
check("teardown: a missing timestamp is NOT grace (no eternal skip)",
      not _sup.within_teardown_grace({"updated_at": 0}))

import glob as _glob


def ledger(lane):
    return os.path.join(STATE, ".respawn", f"p__{lane}.json")


def clear_cooldown(lane):
    lp = ledger(lane)
    if os.path.exists(lp):
        d = json.load(open(lp)); d["last_respawn"] = 0; json.dump(d, open(lp, "w"))


# tick 2 immediately: B is in ledger cooldown -> must NOT respawn again (even though tick 1 minted
# a CHILD record with respawn_count=0 that now governs the lane).
print("tick 2 (immediate):", tick())
check("B respected cooldown across the child handoff (still 1 spawn)",
      sum("lane-b" in c for c in open(calls).read().splitlines()) == 1)

# THE STORM TEST: a lane that always fails. Clear the cooldown each tick and confirm it stops at
# respawn_max instead of respawning forever — the exact bug the child-record handoff hid.
rec("d-1", "lane-storm", restart="until-file:/no/such", done_when="file:/no/such")
for _ in range(8):
    clear_cooldown("lane-storm")
    tick()
storm_spawns = sum("lane-storm" in c for c in open(calls).read().splitlines())
check("storm-prone lane capped at respawn_max=3 (no unbounded storm)", storm_spawns == 3)
gave_up = any(json.load(open(f)).get("status") == "gave_up"
              for f in _glob.glob(os.path.join(STATE, "lane-storm*.json")) + [os.path.join(STATE, "d-1.json")]
              if os.path.exists(f))
check("storm lane eventually marked gave_up", gave_up)

# B's file appears -> the governing child delivers; no extra respawn.
open(b_file, "w").write("done")
print("tick 3 (B outcome now met):", tick())
delivered_b = any(json.load(open(f)).get("outcome") == "met"
                  for f in _glob.glob(os.path.join(STATE, "lane-b*.json")) + [os.path.join(STATE, "b-1.json")]
                  if os.path.exists(f))
check("B delivered once its file appeared", delivered_b)
check("B did NOT respawn after delivering", sum("lane-b" in c for c in open(calls).read().splitlines()) == 1)

print("\nRESULT:", "ALL PASS" if ok else "FAILURES ABOVE")
subprocess.run(["rm", "-rf", ROOT])
sys.exit(0 if ok else 1)
