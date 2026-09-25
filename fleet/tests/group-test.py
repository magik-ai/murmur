#!/usr/bin/env python3
"""End-to-end grouped-lane contract in an isolated git world.

Uses the real fleet spawn path with only process launch/GitHub stubbed. It never
touches the farm state, registered projects, or network remotes.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(tempfile.mkdtemp(prefix="fleet-group-test-"))
STATE, CONFIG, BIN = ROOT / "state", ROOT / "config", ROOT / "bin"
ORIGIN, PROJECT = ROOT / "origin.git", ROOT / "project"
for directory in (STATE / "state", CONFIG, BIN):
    directory.mkdir(parents=True, exist_ok=True)
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

FLEET = Path(_require(str(Path(sys.argv[1] if len(sys.argv) > 1
                                else Path(__file__).resolve().parents[1] / "bin" / "fleet")
                           .expanduser().resolve()),
                       "fleet", "Pass the path to bin/fleet in the checkout under test."))
GH_STATE, GH_CALLS = ROOT / "gh-state", ROOT / "gh-calls"
SYSTEMD_CALLS, SYSTEMD_FAIL = ROOT / "systemd-calls", ROOT / "systemd-fail"
ENV = dict(os.environ, FLEET_STATE=str(STATE), FLEET_CONFIG=str(CONFIG),
           FLEET_LHM_URL="http://127.0.0.1:1", PATH=str(BIN) + ":" + os.environ["PATH"])


def call(args, cwd=None, check=True, env=None):
    result = subprocess.run(args, cwd=cwd, env=env or ENV, text=True, capture_output=True)
    if check and result.returncode:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"command failed: {args}")
    return result


def git(*args, cwd=PROJECT, check=True):
    return call(["git", "-C", str(cwd), *args], check=check)


def check(name, condition, detail=""):
    global OK
    print(("  PASS " if condition else "  FAIL ") + name +
          (f"  [{detail}]" if detail and not condition else ""))
    OK = OK and condition


def lane(group, name):
    data = json.loads((STATE / "groups" / f"{group}.json").read_text())
    return next(item for item in data["lanes"] if item["name"] == name)


def commit(worktree, path, text, message):
    target = Path(worktree, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    git("add", path, cwd=worktree)
    git("commit", "-m", message, cwd=worktree)


subprocess.run(["git", "init", "-q", "--bare", str(ORIGIN)], check=True)
subprocess.run(["git", "clone", "-q", str(ORIGIN), str(PROJECT)], check=True)
git("config", "user.name", "test-base")
git("config", "user.email", "test-base@fleet.local")
(PROJECT / "README.md").write_text("base\n")
git("add", "README.md")
git("commit", "-m", "base")
git("branch", "-M", "main")
git("push", "-q", "-u", "origin", "main")
(CONFIG / "projects.toml").write_text(
    f'[demo]\nrepo = "example/demo"\npath = "{PROJECT}"\nbranch = "main"\n')

# Keep spawn's dashboard and transient process launch inert.
(BIN / "tmux").write_text("#!/bin/sh\nexit 0\n")
(BIN / "systemd-run").write_text(f'''#!/bin/sh
printf '%s\\n' "$*" >> "{SYSTEMD_CALLS}"
[ -f "{SYSTEMD_FAIL}" ] && exit 1
exit 0
''')
(BIN / "systemctl").write_text("#!/bin/sh\nexit 0\n")
(BIN / "hq").write_text("#!/bin/sh\nexit 0\n")
(BIN / "esbuild").write_text('''#!/bin/sh
case "$(cat "$1")" in
  *BROKEN_SYNTAX*) echo "synthetic parse failure" >&2; exit 1 ;;
esac
exit 0
''')
(BIN / "gh").write_text(f'''#!/bin/sh
printf '%s\\n' "$*" >> "{GH_CALLS}"
if [ "$1 $2" = "pr list" ]; then
  [ -f "{GH_STATE}" ] && cat "{GH_STATE}"
  exit 0
elif [ "$1 $2" = "pr create" ]; then
  url="https://github.test/example/demo/pull/1"
  printf '%s\\n' "$url" > "{GH_STATE}"
  printf '%s\\n' "$url"
fi
''')
for path in BIN.iterdir():
    path.chmod(0o755)

OK = True

try:
    clean_spec = ROOT / "clean.toml"
    clean_spec.write_text('''branch_base = "main"

[[lanes]]
name = "alpha"
task = "Add the alpha slice."
territory = ["alpha/**"]
engine = "codex"
effort = "low"

[[lanes]]
name = "beta"
task = "Add the beta slice."
territory = ["beta/**"]
engine = "codex"
effort = "low"
''')
    started = call([str(FLEET), "group", "start", "clean", "--project", "demo",
                    "--spec", str(clean_spec)])
    alpha, beta = lane("clean", "alpha"), lane("clean", "beta")
    check("start spawns both lanes", "spawned 2 isolated lanes" in started.stdout)
    check("each lane has its group branch",
          alpha["branch"] == "group/clean/alpha" and beta["branch"] == "group/clean/beta")
    check("territories are recorded",
          alpha["territory"] == ["alpha/**"] and beta["territory"] == ["beta/**"])
    check("per-lane authors are worktree-local",
          git("config", "--worktree", "user.name", cwd=alpha["worktree"]).stdout.strip() ==
          "group-clean-alpha" and
          git("config", "--worktree", "user.name", cwd=beta["worktree"]).stdout.strip() ==
          "group-clean-beta")
    hook_path = Path(git("config", "--worktree", "core.hooksPath",
                         cwd=alpha["worktree"]).stdout.strip())
    check("pre-push guards live outside the disposable worktree",
          hook_path == STATE / "hooks" / alpha["slug"] and
          (hook_path / "pre-push").is_file() and
          not str(hook_path).startswith(str(alpha["worktree"])))
    run_script = STATE / "logs" / f"{alpha['slug']}.run.sh"
    systemd_args = SYSTEMD_CALLS.read_text()
    check("spawned unit receives its isolated fleet environment",
          f"--setenv=FLEET_STATE={STATE}" in systemd_args and
          f"--setenv=FLEET_CONFIG={CONFIG}" in systemd_args and
          f'export FLEET_STATE="{STATE}"' in run_script.read_text() and
          f'export FLEET_CONFIG="{CONFIG}"' in run_script.read_text())
    brief = (STATE / "groups" / "briefs" / "clean" / "alpha.md").read_text()
    check("hard no-PR contract is prepended", brief.startswith("GROUP CONTRACT") and
          "do NOT open a PR" in brief)
    initial_status = json.loads(
        call([str(FLEET), "group", "status", "clean", "--json"]).stdout)
    check("status JSON reports unpushed lanes as working",
          all(item["status"] == "working" for item in initial_status["lanes"]))

    overlap_spec = ROOT / "overlap.toml"
    overlap_spec.write_text('''[[lanes]]
name = "one"
task = "one"
territory = ["src/**"]
[[lanes]]
name = "two"
task = "two"
territory = ["src/screens/*.py"]
''')
    before = len(list((STATE / "state").glob("*.json")))
    refused = call([str(FLEET), "group", "start", "refused", "--project", "demo",
                    "--spec", str(overlap_spec)], check=False)
    after = len(list((STATE / "state").glob("*.json")))
    check("overlapping territories are refused before spawn",
          refused.returncode != 0 and "overlapping lane territories" in refused.stderr and
          before == after and not (STATE / "groups" / "refused.json").exists())

    # `git clean -xfd` is routine build hygiene. It must not be able to disarm the guard.
    git("clean", "-xfd", cwd=alpha["worktree"])
    check("git clean cannot remove the external pre-push guard", (hook_path / "pre-push").is_file())

    # Deliberately violate alpha's territory after cleaning. The real pre-push hook must reject it.
    commit(alpha["worktree"], "beta/stolen.py", "stolen = True\n", "wrong territory")
    blocked = git("push", "-u", "origin", alpha["branch"], cwd=alpha["worktree"], check=False)
    blocked_status = json.loads(call([str(FLEET), "group", "status", "clean", "--json"]).stdout)
    alpha_status = next(item for item in blocked_status["lanes"] if item["lane"] == "alpha")
    check("sibling-owned edit is blocked before push",
          blocked.returncode != 0 and "GROUP PUSH BLOCKED" in blocked.stderr and
          not git("ls-remote", "--heads", "origin", alpha["branch"]).stdout.strip())
    check("status JSON reports blocked", alpha_status["status"] == "blocked" and
          alpha_status["offending_files"] == ["beta/stolen.py"])

    # If a broken guard allowed the negative probe through, remove only that throwaway remote ref
    # so the rest of this isolated suite can continue and report the remaining independent checks.
    git("push", "-q", "origin", f":refs/heads/{alpha['branch']}", check=False)
    git("reset", "--hard", "HEAD^", cwd=alpha["worktree"])
    commit(alpha["worktree"], "alpha/alpha.py", "VALUE = 'alpha'\n", "alpha slice")
    commit(beta["worktree"], "beta/beta.js", "const beta = true;\n", "beta slice")
    git("push", "-q", "-u", "origin", alpha["branch"], cwd=alpha["worktree"])
    git("push", "-q", "-u", "origin", beta["branch"], cwd=beta["worktree"])
    status = json.loads(call([str(FLEET), "group", "status", "clean", "--json"]).stdout)
    check("status JSON reports pushed heads and counts",
          all(item["status"] == "pushed" and item["head_sha"] and item["files_changed"] == 1
              for item in status["lanes"]))
    authors = [git("log", "-1", "--format=%an <%ae>", cwd=item["worktree"]).stdout.strip()
               for item in (alpha, beta)]
    check("commits retain distinct lane attribution",
          authors == ["group-clean-alpha <alpha@fleet.local>",
                      "group-clean-beta <beta@fleet.local>"], str(authors))

    dry = call([str(FLEET), "group", "assemble", "clean", "--dry-run"])
    check("disjoint dry-run reports order and per-lane files",
          dry.returncode == 0 and "alpha/alpha.py" in dry.stdout and
          "beta/beta.js" in dry.stdout and "clean assembly" in dry.stdout and
          "no PR was opened" in dry.stdout)

    real = call([str(FLEET), "group", "assemble", "clean"])
    calls = GH_CALLS.read_text().splitlines()
    check("real assembly opens exactly one PR", real.stdout.rstrip().endswith("/pull/1") and
          sum(line.startswith("pr create ") for line in calls) == 1)
    check("assembly never merges a PR", not any(line.startswith("pr merge ") for line in calls))
    check("integration branch is pushed",
          bool(git("ls-remote", "--heads", "origin", "group/clean/integration").stdout.strip()))
    call([str(FLEET), "group", "assemble", "clean"])
    calls = GH_CALLS.read_text().splitlines()
    check("real assembly is idempotent and still has exactly one PR",
          sum(line.startswith("pr create ") for line in calls) == 1)

    # Collision detection: declarations are disjoint, but both branches bypass the hook and add
    # the same undeclared file. Assembly must report, abort, and never auto-resolve.
    collision_spec = ROOT / "collision.toml"
    collision_spec.write_text('''[[lanes]]
name = "left"
task = "left"
territory = ["left/**"]
engine = "codex"
effort = "low"
[[lanes]]
name = "right"
task = "right"
territory = ["right/**"]
engine = "codex"
effort = "low"
''')
    call([str(FLEET), "group", "start", "collision", "--project", "demo",
          "--spec", str(collision_spec)])
    left, right = lane("collision", "left"), lane("collision", "right")
    commit(left["worktree"], "collision.txt", "left\n", "left collision")
    commit(right["worktree"], "collision.txt", "right\n", "right collision")
    git("push", "--no-verify", "-q", "-u", "origin", left["branch"], cwd=left["worktree"])
    git("push", "--no-verify", "-q", "-u", "origin", right["branch"], cwd=right["worktree"])
    collided = call([str(FLEET), "group", "assemble", "collision", "--dry-run"], check=False)
    collision_status = json.loads(
        call([str(FLEET), "group", "status", "collision", "--json"]).stdout)
    check("overlapping changes report collision with no auto-resolve",
          collided.returncode == 3 and "COLLISION" in collided.stdout and
          all(item["status"] == "collision" for item in collision_status["lanes"]) and
          collision_status["collisions"][-1]["files"] == ["collision.txt"])
    check("conflicted merge was aborted and integration was not pushed",
          not git("ls-remote", "--heads", "origin",
                  "group/collision/integration").stdout.strip())

    quote_spec = ROOT / "quote.toml"
    quote_spec.write_text('''[[lanes]]
name = "quoted"
task = 'Use """triple quotes""" and rename the CTA to "Continue"'
territory = ["quoted/**"]
engine = "codex"
effort = "low"
''')
    quoted = call([str(FLEET), "group", "start", "quoted", "--project", "demo",
                   "--spec", str(quote_spec)], check=False)
    check("quoted and triple-quoted brief text survives spawn",
          quoted.returncode == 0 and lane("quoted", "quoted")["slug"])

    slash_brief = ROOT / "slash-brief.md"
    slash_brief.write_text('Describe """Python docstrings""". End with a backslash: \\')
    slash_spec = ROOT / "slash.toml"
    slash_spec.write_text(f'''[[lanes]]
name = "slash"
brief = "{slash_brief.name}"
territory = ["slash/**"]
engine = "codex"
effort = "low"
''')
    slash = call([str(FLEET), "group", "start", "slash", "--project", "demo",
                  "--spec", str(slash_spec)], check=False)
    check("brief ending in a backslash survives spawn",
          slash.returncode == 0 and lane("slash", "slash")["slug"])

    long_brief = ROOT / "long-brief.md"
    long_brief.write_text("Long safe brief.\n" + ("x" * 125_000))
    long_spec = ROOT / "long.toml"
    long_spec.write_text(f'''[[lanes]]
name = "long"
brief = "{long_brief.name}"
territory = ["long/**"]
engine = "codex"
effort = "low"
''')
    long_result = call([str(FLEET), "group", "start", "long", "--project", "demo",
                       "--spec", str(long_spec)], check=False)
    long_lane = lane("long", "long")
    long_wt = Path(long_lane.get("worktree") or ROOT / "missing")
    spill = STATE / "briefs" / f"{long_lane.get('slug')}.prompt.md"
    check("oversize prompt spills outside the git worktree",
          long_result.returncode == 0 and spill.is_file() and
          not (long_wt / ".fleet-task.md").exists() and
          not git("status", "--short", cwd=long_wt).stdout.strip())

    SYSTEMD_FAIL.touch()
    rollback_spec = ROOT / "rollback.toml"
    rollback_spec.write_text('''[[lanes]]
name = "rollback"
task = "Fail only at process launch."
territory = ["rollback/**"]
engine = "codex"
effort = "low"
''')
    rollback = call([str(FLEET), "group", "start", "rollback", "--project", "demo",
                    "--spec", str(rollback_spec)], check=False)
    SYSTEMD_FAIL.unlink()
    rollback_records = [
        json.loads(path.read_text()) for path in (STATE / "state").glob("*.json")
        if path.read_text().strip()
    ]
    rollback_branch_exists = (
        git("show-ref", "--verify", "--quiet",
            "refs/heads/group/rollback/rollback", check=False).returncode == 0
    )
    rollback_hooks = list((STATE / "hooks").glob("rollback-*"))
    rollback_logs = list((STATE / "logs").glob("rollback-*"))
    check("failed launch rolls back branch, worktree, state, hooks and logs",
          rollback.returncode != 0 and
          not any(item.get("branch") == "group/rollback/rollback"
                  for item in rollback_records) and
          not rollback_branch_exists and not rollback_hooks and not rollback_logs,
          json.dumps({
              "returncode": rollback.returncode,
              "state": [item.get("branch") for item in rollback_records
                        if item.get("branch") == "group/rollback/rollback"],
              "branch": rollback_branch_exists,
              "hooks": [str(item) for item in rollback_hooks],
              "logs": [str(item) for item in rollback_logs],
              "stderr": rollback.stderr,
          }))

    syntax_spec = ROOT / "syntax.toml"
    syntax_spec.write_text('''[[lanes]]
name = "tsx"
task = "Add a TSX component."
territory = ["ui/**"]
engine = "codex"
effort = "low"
''')
    call([str(FLEET), "group", "start", "syntax", "--project", "demo",
          "--spec", str(syntax_spec)])
    syntax_lane = lane("syntax", "tsx")
    commit(syntax_lane["worktree"], "ui/broken.tsx", "BROKEN_SYNTAX\n", "broken tsx")
    git("push", "-q", "-u", "origin", syntax_lane["branch"], cwd=syntax_lane["worktree"])
    syntax = call([str(FLEET), "group", "assemble", "syntax", "--dry-run"], check=False)
    check("TSX syntax parser can reject an invalid assembled file",
          syntax.returncode != 0 and "syntax sanity failed" in syntax.stderr)

    marker_spec = ROOT / "marker.toml"
    marker_spec.write_text('''[[lanes]]
name = "marker"
task = "Add a text file."
territory = ["notes/**"]
engine = "codex"
effort = "low"
''')
    call([str(FLEET), "group", "start", "marker", "--project", "demo",
          "--spec", str(marker_spec)])
    marker_lane = lane("marker", "marker")
    commit(marker_lane["worktree"], "notes/conflict.txt", "left\n=======\nright\n",
           "partial conflict")
    git("push", "-q", "-u", "origin", marker_lane["branch"], cwd=marker_lane["worktree"])
    marker = call([str(FLEET), "group", "assemble", "marker", "--dry-run"], check=False)
    check("standalone conflict divider is rejected",
          marker.returncode != 0 and "conflict-marker sweep failed" in marker.stderr)

    print("\nRESULT:", "ALL PASS" if OK else "FAILURES ABOVE")
finally:
    shutil.rmtree(ROOT, ignore_errors=True)

raise SystemExit(0 if OK else 1)
