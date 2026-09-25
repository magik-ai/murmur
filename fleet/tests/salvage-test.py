import os, pathlib, sys, subprocess, tempfile
# FLEET_HOME, else the checkout this file lives in. Never a hardcoded path: that tests somebody
# else's tree while you read the result as your own.
FLEET_HOME = pathlib.Path(os.environ.get("FLEET_HOME") or pathlib.Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(FLEET_HOME / "lib"))
import salvage as S

ok = True
def check(name, cond):
    global ok
    print(("  PASS " if cond else "  FAIL ") + name)
    ok = ok and cond

def g(cwd, *a): return subprocess.run(["git","-C",cwd,*a], capture_output=True, text=True)

root = tempfile.mkdtemp()
origin = os.path.join(root, "origin.git")
subprocess.run(["git","init","-q","--bare","-b","main",origin], check=True)
# seed main via a scratch clone
work = os.path.join(root, "work")
subprocess.run(["git","clone","-q",origin,work], check=True)
for k,v in (("user.email","t@t"),("user.name","t")): g(work,"config",k,v)
open(os.path.join(work,"a"),"w").write("1"); g(work,"add","-A"); g(work,"commit","-qm","base")
g(work,"push","-q","origin","main")

# a lane worktree with a committed-but-UNPUSHED commit (the data-loss case)
wt = os.path.join(root, "lane")
g(work,"worktree","add","-q","-b","demo-lane",wt)
for k,v in (("user.email","t@t"),("user.name","t")): g(wt,"config",k,v)
open(os.path.join(wt,"b"),"w").write("2"); g(wt,"add","-A"); g(wt,"commit","-qm","lane work")
lane_sha = g(wt,"rev-parse","HEAD").stdout.strip()

# 1. unpushed work is detected
check("unpushed commit is detected", S.unpushed_shas(wt) == [lane_sha])

# 2. salvage pushes it to the hidden namespace, commit survives on origin
saved, detail = S.salvage(wt, "demo-lane-145224")
check("salvage reports saved", saved and "demo-lane-145224" in detail)
refs = g(work,"ls-remote","origin","refs/fleet-salvage/*").stdout
check("salvage ref exists on origin with the lane commit",
      "refs/fleet-salvage/demo-lane-145224" in refs and lane_sha in refs)
# THE pattern: prove the commit would have been LOST without salvage — it is NOT in any branch...
branches = g(work,"ls-remote","origin","refs/heads/*").stdout
check("proof of loss: the commit is in NO branch on origin (only the salvage ref saved it)",
      lane_sha not in branches)

# 3. pushed work must NOT spam the namespace (negative)
g(wt,"push","-q","origin","HEAD:refs/heads/demo-lane")
saved2, detail2 = S.salvage(wt, "demo-lane-again")
check("already-pushed work is not salvaged", (not saved2) and detail2 == "nothing unpushed")

# 4. cleanup drops a salvage ref once its tip lands in origin/main; keeps one that has not
#    land demo-lane into main
g(work,"fetch","-q","origin"); g(work,"merge","-q","origin/demo-lane"); g(work,"push","-q","origin","main")
# a second salvage ref whose commit never lands
open(os.path.join(wt,"c"),"w").write("3"); g(wt,"add","-A"); g(wt,"commit","-qm","orphan")
S.salvage(wt, "orphan-lane")
g(work,"fetch","-q","origin")
dropped = S.cleanup_landed(work, "main")
check("cleanup drops the landed salvage ref",
      "refs/fleet-salvage/demo-lane-145224" in dropped)
check("cleanup keeps the not-yet-landed salvage ref",
      "refs/fleet-salvage/orphan-lane" not in dropped)
remaining = g(work,"ls-remote","origin","refs/fleet-salvage/*").stdout
check("graveyard stays clean: only the orphan salvage ref remains",
      "orphan-lane" in remaining and "demo-lane-145224" not in remaining)

# 5. unsafe slug is refused (no path traversal into the ref namespace)
bad, _ = S.salvage(wt, "../evil")
check("unsafe slug refused", not bad)

print("RESULT: " + ("ALL PASS" if ok else "FAILURES"))
sys.exit(0 if ok else 1)
