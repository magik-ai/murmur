#!/usr/bin/env python3
"""Grouped fleet lanes: disjoint branches assembled into one integration PR.

Runtime state is additive and isolated under $FLEET_STATE/groups.  The ordinary
lane state records remain authoritative for the spawned worker process.
"""
import argparse
import contextlib
import fcntl
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib


STATE = Path(os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet")))
CONFIG = Path(os.path.expanduser(os.environ.get("FLEET_CONFIG", "~/.config/fleet")))
GROUPS = STATE / "groups"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class GroupError(RuntimeError):
    pass


def run(args, cwd=None, check=True, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise GroupError(f"{' '.join(args)} failed: {detail}")
    return result


def group_path(name):
    return GROUPS / f"{name}.json"


@contextlib.contextmanager
def group_lock(name):
    GROUPS.mkdir(parents=True, exist_ok=True)
    with open(GROUPS / f"{name}.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def load_group(name):
    try:
        return json.loads(group_path(name).read_text())
    except FileNotFoundError as exc:
        raise GroupError(f"no such group: {name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise GroupError(f"cannot read group {name}: {exc}") from exc


def save_group(group):
    GROUPS.mkdir(parents=True, exist_ok=True)
    path = group_path(group["name"])
    tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(group, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def project_config(name):
    path = CONFIG / "projects.toml"
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError as exc:
        raise GroupError(f"project registry missing: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise GroupError(f"invalid project registry: {exc}") from exc
    project = data.get(name)
    if not isinstance(project, dict):
        raise GroupError(f"project '{name}' is not registered")
    project = dict(project)
    project["path"] = os.path.expanduser(str(project.get("path", "")))
    if not project["path"] or not Path(project["path"], ".git").exists():
        raise GroupError(f"registered project path is missing: {project['path']}")
    project["branch"] = str(project.get("branch") or "main")
    return project


def validate_name(value, kind):
    if not SAFE_NAME.fullmatch(value):
        raise GroupError(f"invalid {kind} '{value}'; use letters, digits, '.', '_' or '-'")
    return value


def normalize_glob(value):
    value = str(value).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    value = value.rstrip("/")
    if not value or value.startswith("/") or any(part == ".." for part in value.split("/")):
        raise GroupError(f"territory must be a repository-relative path glob: {value!r}")
    return value


def segment_intersects(left, right):
    """Whether two shell-style, non-slash segment globs share at least one string."""
    alphabet = {chr(i) for i in range(32, 127) if chr(i) != "/"}
    alphabet.update(ch for ch in left + right if ch != "/")
    alphabet.add("\u2603")

    def atom(pattern, pos):
        ch = pattern[pos]
        if ch == "*":
            return "star", None, pos + 1
        if ch == "?":
            return "char", lambda _c: True, pos + 1
        if ch == "[":
            end = pattern.find("]", pos + 1)
            if end > pos + 1:
                raw = pattern[pos + 1:end]
                negated = raw[:1] in ("!", "^")
                if negated:
                    raw = raw[1:]
                allowed = set()
                idx = 0
                while idx < len(raw):
                    if idx + 2 < len(raw) and raw[idx + 1] == "-":
                        allowed.update(chr(n) for n in range(ord(raw[idx]), ord(raw[idx + 2]) + 1))
                        idx += 3
                    else:
                        allowed.add(raw[idx]); idx += 1
                return "char", ((lambda c: c not in allowed) if negated
                                else (lambda c: c in allowed)), end + 1
        return "char", lambda c, want=ch: c == want, pos + 1

    def epsilon(pattern, states):
        states = set(states)
        changed = True
        while changed:
            changed = False
            for pos in tuple(states):
                if pos < len(pattern) and pattern[pos] == "*" and pos + 1 not in states:
                    states.add(pos + 1); changed = True
        return states

    start = (frozenset(epsilon(left, {0})), frozenset(epsilon(right, {0})), False)
    queue, seen = [start], {start}
    while queue:
        ls, rs, consumed = queue.pop()
        if consumed and len(left) in ls and len(right) in rs:
            return True
        for char in alphabet:
            ln, rn = set(), set()
            for pos in ls:
                if pos >= len(left):
                    continue
                kind, accepts, nxt = atom(left, pos)
                if kind == "star" or accepts(char):
                    ln.add(pos if kind == "star" else nxt)
            for pos in rs:
                if pos >= len(right):
                    continue
                kind, accepts, nxt = atom(right, pos)
                if kind == "star" or accepts(char):
                    rn.add(pos if kind == "star" else nxt)
            if not ln or not rn:
                continue
            state = (frozenset(epsilon(left, ln)), frozenset(epsilon(right, rn)), True)
            if state not in seen:
                seen.add(state); queue.append(state)
    return False


def globs_intersect(left, right):
    """Exact intersection for slash-separated globs with whole-segment **."""
    a, b = left.split("/"), right.split("/")
    queue, seen = [(0, 0)], set()
    while queue:
        i, j = queue.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if i == len(a) and j == len(b):
            return True
        if i < len(a) and a[i] == "**":
            queue.append((i + 1, j))
        if j < len(b) and b[j] == "**":
            queue.append((i, j + 1))
        if i == len(a) or j == len(b):
            continue
        if a[i] == "**" and b[j] == "**":
            queue.extend(((i + 1, j), (i, j + 1)))
        elif a[i] == "**":
            queue.append((i, j + 1))
        elif b[j] == "**":
            queue.append((i + 1, j))
        elif segment_intersects(a[i], b[j]):
            queue.append((i + 1, j + 1))
    return False


def path_matches(path, pattern):
    parts, glob_parts = path.split("/"), pattern.split("/")
    queue, seen = [(0, 0)], set()
    while queue:
        i, j = queue.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if i == len(parts) and j == len(glob_parts):
            return True
        if j == len(glob_parts):
            continue
        if glob_parts[j] == "**":
            queue.append((i, j + 1))
            if i < len(parts):
                queue.append((i + 1, j))
        elif i < len(parts) and fnmatch.fnmatchcase(parts[i], glob_parts[j]):
            queue.append((i + 1, j + 1))
    return False


def read_spec(path):
    try:
        raw = tomllib.loads(Path(path).read_text())
    except FileNotFoundError as exc:
        raise GroupError(f"spec not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise GroupError(f"invalid group spec: {exc}") from exc
    rows = raw.get("lanes")
    if not isinstance(rows, list) or not rows:
        raise GroupError("group spec needs one or more [[lanes]] entries")
    lanes = []
    for row in rows:
        if not isinstance(row, dict):
            raise GroupError("each [[lanes]] entry must be a table")
        name = validate_name(str(row.get("name", "")), "lane name")
        territory = row.get("territory")
        if isinstance(territory, str):
            territory = [territory]
        if not isinstance(territory, list) or not territory:
            raise GroupError(f"lane '{name}' must declare a non-empty territory")
        territory = [normalize_glob(item) for item in territory]
        task, brief = row.get("task"), row.get("brief")
        if bool(task) == bool(brief):
            raise GroupError(f"lane '{name}' needs exactly one of task or brief")
        lane = {"name": name, "territory": territory}
        if task:
            lane.update({"brief": str(task), "brief_source": "inline"})
        else:
            brief_path = (Path(path).resolve().parent / str(brief)).resolve()
            try:
                lane.update({"brief": brief_path.read_text(), "brief_source": str(brief_path)})
            except OSError as exc:
                raise GroupError(f"cannot read brief for lane '{name}': {exc}") from exc
        for key in ("engine", "model", "effort", "by"):
            if row.get(key):
                lane[key] = str(row[key])
        lanes.append(lane)
    names = [lane["name"] for lane in lanes]
    if len(names) != len(set(names)):
        raise GroupError("lane names must be unique within a group")
    overlaps = []
    for idx, left in enumerate(lanes):
        for right in lanes[idx + 1:]:
            for a in left["territory"]:
                for b in right["territory"]:
                    if globs_intersect(a, b):
                        overlaps.append((left["name"], a, right["name"], b))
    if overlaps:
        lines = ["overlapping lane territories; no agents were spawned:"]
        lines.extend(f"  {a}: {aglob}  overlaps  {b}: {bglob}"
                     for a, aglob, b, bglob in overlaps)
        raise GroupError("\n".join(lines))
    return raw, lanes


def lane_contract(group_name, lane):
    globs = ", ".join(lane["territory"])
    return (f"GROUP CONTRACT — {group_name}/{lane['name']}\n"
            f"Commit and push your OWN branch group/{group_name}/{lane['name']}; do NOT open a PR.\n"
            f"Stay strictly inside your declared file territory: {globs}.\n"
            "The orchestrator alone assembles lane branches and opens the integration PR.\n\n")


def find_spawn_record(branch):
    for path in (STATE / "state").glob("*.json"):
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("branch") == branch:
            return record
    raise GroupError(f"spawn completed but no lane state was recorded for {branch}")


def cmd_start(args):
    name = validate_name(args.name, "group name")
    raw, lanes = read_spec(args.spec)  # overlap validation MUST precede every spawn/state write
    project = project_config(args.project)
    branch_base = str(raw.get("branch_base") or project["branch"])
    if run(["git", "check-ref-format", "--branch", branch_base], check=False).returncode:
        raise GroupError(f"invalid branch base: {branch_base}")
    if group_path(name).exists():
        raise GroupError(f"group '{name}' already exists")

    group = {
        "name": name, "project": args.project, "branch_base": branch_base,
        "integration_branch": f"group/{name}/integration", "status": "starting",
        "created_at": int(time.time()), "lanes": [], "collisions": [],
    }
    for lane in lanes:
        lane.update({"branch": f"group/{name}/{lane['name']}", "status": "working",
                     "author_name": f"group-{name}-{lane['name']}",
                     "author_email": f"{lane['name']}@fleet.local", "slug": None})
        group["lanes"].append(lane)
    with group_lock(name):
        save_group(group)

    briefs = GROUPS / "briefs" / name
    briefs.mkdir(parents=True, exist_ok=True)
    fleet = os.environ.get("FLEET_BIN") or str(Path(__file__).resolve().parent.parent / "bin/fleet")
    for lane in group["lanes"]:
        brief_path = briefs / f"{lane['name']}.md"
        brief_path.write_text(lane_contract(name, lane) + lane["brief"])
        command = [fleet, "spawn", "--project", args.project, "--lane", lane["name"],
                   "--brief-file", str(brief_path)]
        for flag, key in (("--engine", "engine"), ("--model", "model"),
                          ("--effort", "effort"), ("--by", "by")):
            if lane.get(key):
                command.extend((flag, lane[key]))
        env = dict(os.environ, FLEET_SPAWN_BRANCH=lane["branch"],
                   FLEET_SPAWN_BASE=branch_base,
                   FLEET_SPAWN_GIT_NAME=lane["author_name"],
                   FLEET_SPAWN_GIT_EMAIL=lane["author_email"],
                   FLEET_GROUP_NAME=name, FLEET_GROUP_LANE=lane["name"],
                   FLEET_SPAWN_NO_PR="1")
        result = run(command, check=False, env=env)
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            error = f"spawn failed: {detail}"
            with group_lock(name):
                fresh = load_group(name)
                failed = next(item for item in fresh["lanes"]
                              if item["name"] == lane["name"])
                failed.update(status="blocked", error=error)
                fresh["status"] = "blocked"
                save_group(fresh)
            raise GroupError(error)
        record = find_spawn_record(lane["branch"])
        lane["slug"], lane["worktree"] = record["slug"], record["worktree"]
        with group_lock(name):
            fresh = load_group(name)
            spawned = next(item for item in fresh["lanes"] if item["name"] == lane["name"])
            spawned.update(slug=record["slug"], worktree=record["worktree"])
            save_group(fresh)
    with group_lock(name):
        fresh = load_group(name)
        if fresh.get("status") not in ("blocked", "collision"):
            fresh["status"] = "working"
        save_group(fresh)
    print(f"group {name}: spawned {len(lanes)} isolated lanes")


def changed_files(repo, base, head):
    result = run(["git", "-C", repo, "diff", "--name-only", f"origin/{base}...{head}"],
                 check=False)
    if result.returncode:
        raise GroupError(f"cannot diff {head} against origin/{base}: {(result.stderr or '').strip()}")
    return sorted(line for line in result.stdout.splitlines() if line)


def update_lane(name, lane_name, **fields):
    with group_lock(name):
        group = load_group(name)
        lane = next((item for item in group["lanes"] if item["name"] == lane_name), None)
        if lane is None:
            raise GroupError(f"lane '{lane_name}' is not in group '{name}'")
        lane.update(fields)
        if "status" in fields:
            statuses = {item.get("status") for item in group["lanes"]}
            if "collision" in statuses:
                group["status"] = "collision"
            elif "blocked" in statuses:
                group["status"] = "blocked"
            elif group.get("status") != "pr_open":
                group["status"] = "working"
        save_group(group)


def cmd_guard(args):
    group = load_group(args.name)
    lane = next((item for item in group["lanes"] if item["name"] == args.lane), None)
    if lane is None:
        raise GroupError(f"lane '{args.lane}' is not in group '{args.name}'")
    repo = lane.get("worktree") or os.getcwd()
    files = changed_files(repo, group["branch_base"], "HEAD")
    outside = [path for path in files
               if not any(path_matches(path, glob) for glob in lane["territory"])]
    sibling_hits = {}
    for sibling in group["lanes"]:
        if sibling["name"] == lane["name"]:
            continue
        hits = [path for path in files
                if any(path_matches(path, glob) for glob in sibling["territory"])]
        if hits:
            sibling_hits[sibling["name"]] = hits
    offenders = sorted(set(outside).union(*(set(v) for v in sibling_hits.values())))
    if offenders:
        update_lane(args.name, args.lane, status="blocked", offending_files=offenders,
                    sibling_hits=sibling_hits, guard_checked_at=int(time.time()))
        print(f"GROUP PUSH BLOCKED: lane {args.lane} changed files outside its territory:",
              file=sys.stderr)
        for path in offenders:
            owners = [name for name, paths in sibling_hits.items() if path in paths]
            suffix = f" (owned by sibling {', '.join(owners)})" if owners else ""
            print(f"  {path}{suffix}", file=sys.stderr)
        print("Commit remains local; fix the territory violation before pushing.", file=sys.stderr)
        return 1
    if lane.get("status") == "blocked":
        update_lane(args.name, args.lane, status="working", offending_files=[], sibling_hits={},
                    guard_checked_at=int(time.time()))
    return 0


def remote_sha(repo, branch):
    result = run(["git", "-C", repo, "ls-remote", "--heads", "origin", branch], check=False)
    if result.returncode or not result.stdout.strip():
        return ""
    return result.stdout.split()[0]


def status_payload(name):
    group = load_group(name)
    project = project_config(group["project"])
    repo = project["path"]
    rows = []
    for lane in group["lanes"]:
        pushed = remote_sha(repo, lane["branch"])
        local = run(["git", "-C", repo, "rev-parse", "--verify", lane["branch"]], check=False)
        local_sha = local.stdout.strip() if local.returncode == 0 else ""
        head = local_sha or pushed
        try:
            files = changed_files(repo, group["branch_base"], head) if head else []
        except GroupError:
            files = []
        state = lane.get("status")
        if state not in ("blocked", "collision"):
            state = "pushed" if pushed and (not local_sha or pushed == local_sha) else "working"
        row = {"lane": lane["name"], "status": state, "branch": lane["branch"],
               "head_sha": head or None, "files_changed": len(files), "files": files,
               "territory": lane["territory"], "slug": lane.get("slug")}
        for key in ("offending_files", "sibling_hits", "collision_files", "collision_with"):
            if lane.get(key):
                row[key] = lane[key]
        rows.append(row)
    return {"name": group["name"], "project": group["project"],
            "branch_base": group["branch_base"],
            "integration_branch": group["integration_branch"],
            "status": group.get("status"), "pr_url": group.get("pr_url"),
            "collisions": group.get("collisions", []), "lanes": rows}


def cmd_status(args):
    payload = status_payload(args.name)
    if args.json:
        print(json.dumps(payload))
        return
    print(f"GROUP {payload['name']}  project={payload['project']}  base={payload['branch_base']}")
    print(f"  {'LANE':<18} {'STATUS':<10} {'FILES':>5} {'HEAD':<12} BRANCH")
    for lane in payload["lanes"]:
        print(f"  {lane['lane'][:18]:<18} {lane['status']:<10} {lane['files_changed']:>5} "
              f"{(lane['head_sha'] or '-')[:12]:<12} {lane['branch']}")
        if lane.get("collision_files"):
            print(f"    collision with {', '.join(lane.get('collision_with', []))}: "
                  f"{', '.join(lane['collision_files'])}")
        elif lane.get("offending_files"):
            print(f"    blocked files: {', '.join(lane['offending_files'])}")


def fetch_branch(repo, branch):
    probe = run(["git", "-C", repo, "ls-remote", "--exit-code", "--heads", "origin", branch],
                check=False)
    if probe.returncode == 2:
        return False
    if probe.returncode:
        raise GroupError(f"cannot inspect remote branch {branch}: "
                         f"{(probe.stderr or probe.stdout).strip()}")
    ref = f"refs/remotes/origin/{branch}"
    result = run(["git", "-C", repo, "fetch", "-q", "origin",
                  f"refs/heads/{branch}:{ref}"], check=False)
    if result.returncode:
        raise GroupError(f"cannot fetch lane branch {branch}: "
                         f"{(result.stderr or result.stdout).strip()}")
    return True


def record_collision(group, current, previous, files):
    names = sorted(set(previous + [current]))
    collision = {"lanes": names, "files": sorted(files), "at": int(time.time())}
    with group_lock(group["name"]):
        fresh = load_group(group["name"])
        fresh["status"] = "collision"
        fresh.setdefault("collisions", []).append(collision)
        for lane in fresh["lanes"]:
            if lane["name"] in names:
                lane["status"] = "collision"
                lane["collision_files"] = collision["files"]
                lane["collision_with"] = [n for n in names if n != lane["name"]]
        save_group(fresh)


def sanity(repo, files, parser_root=None):
    marker = re.compile(r"^(?:<<<<<<<(?: .*)?|=======|>>>>>>>(?: .*)?)$")
    bad_markers, syntax = [], []

    def esbuild_for(rel):
        candidates = []
        for root in (Path(repo), Path(parser_root) if parser_root else None):
            if root is None:
                continue
            parent = Path(rel).parent
            for relative in (parent, *parent.parents):
                candidates.append(root / relative / "node_modules" / ".bin" / "esbuild")
        global_esbuild = shutil.which("esbuild")
        if global_esbuild:
            candidates.append(Path(global_esbuild))
        return next((str(candidate) for candidate in candidates
                     if candidate.is_file() and os.access(candidate, os.X_OK)), None)

    for rel in files:
        path = Path(repo, rel)
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
            if b"\0" not in data:
                text = data.decode("utf-8", errors="replace")
                if any(marker.match(line) for line in text.splitlines()):
                    bad_markers.append(rel)
        except OSError:
            continue
        command = None
        if path.suffix == ".py":
            command = [sys.executable, "-m", "py_compile", str(path)]
        elif path.suffix in (".js", ".mjs", ".cjs") and shutil.which("node"):
            command = ["node", "--check", str(path)]
        elif path.suffix in (".jsx", ".ts", ".tsx"):
            parser = esbuild_for(rel)
            if not parser:
                syntax.append({
                    "file": rel,
                    "error": "no esbuild parser is installed; refusing to claim syntax passed",
                })
            else:
                command = [parser, str(path), "--log-level=error", "--outfile=/dev/null"]
        if command:
            result = run(command, check=False)
            if result.returncode:
                syntax.append({"file": rel, "error": (result.stderr or result.stdout).strip()})
    if bad_markers:
        raise GroupError("conflict-marker sweep failed: " + ", ".join(bad_markers))
    if syntax:
        raise GroupError("syntax sanity failed:\n" + "\n".join(
            f"  {item['file']}: {item['error']}" for item in syntax))


def existing_pr(repo_name, branch):
    result = run(["gh", "pr", "list", "-R", repo_name, "--state", "open", "--head", branch,
                  "--json", "url", "--jq", ".[0].url // \"\""], check=False)
    if result.returncode:
        raise GroupError(f"cannot check for an existing integration PR: "
                         f"{(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def cmd_assemble(args):
    group = load_group(args.name)
    project = project_config(group["project"])
    repo, base = project["path"], group["branch_base"]
    run(["git", "-C", repo, "fetch", "-q", "origin", base])
    pushed = []
    for lane in sorted(group["lanes"], key=lambda item: item["name"]):
        if fetch_branch(repo, lane["branch"]):
            sha = remote_sha(repo, lane["branch"])
            files = changed_files(repo, base, f"origin/{lane['branch']}")
            pushed.append((lane, sha, files))
    if not pushed:
        raise GroupError("no pushed lane branches to assemble")

    print("assembly order:")
    for lane, sha, files in pushed:
        print(f"  {lane['name']}  {sha[:12]}  {len(files)} file(s)")
        for path in files:
            print(f"    {path}")

    assembly_root = GROUPS / "assembly"
    assembly_root.mkdir(parents=True, exist_ok=True)
    worktree = tempfile.mkdtemp(prefix=f"{group['name']}-", dir=assembly_root)
    run(["git", "-C", repo, "worktree", "add", "-q", "--detach", worktree,
         f"origin/{base}"])
    merged, files_by_lane = [], {}
    merge_env = dict(os.environ, GIT_AUTHOR_NAME=f"group-{group['name']}-integration",
                     GIT_AUTHOR_EMAIL=f"{group['name']}@fleet.local",
                     GIT_COMMITTER_NAME=f"group-{group['name']}-integration",
                     GIT_COMMITTER_EMAIL=f"{group['name']}@fleet.local")
    try:
        for lane, _sha, files in pushed:
            result = run(["git", "-C", worktree, "merge", "--no-ff", "--no-edit",
                          f"origin/{lane['branch']}"], check=False, env=merge_env)
            files_by_lane[lane["name"]] = set(files)
            if result.returncode:
                unresolved = run(["git", "-C", worktree, "diff", "--name-only", "--diff-filter=U"],
                                 check=False).stdout.splitlines()
                run(["git", "-C", worktree, "merge", "--abort"], check=False)
                if not unresolved:
                    detail = (result.stderr or result.stdout).strip()
                    raise GroupError(f"merge of lane {lane['name']} failed: {detail}")
                previous = [name for name in merged
                            if set(unresolved).intersection(files_by_lane.get(name, set()))]
                if not previous and merged:
                    previous = [merged[-1]]
                record_collision(group, lane["name"], previous, unresolved)
                print(f"COLLISION: {lane['name']} conflicts with {', '.join(previous) or 'base'}")
                for path in unresolved:
                    print(f"  {path}")
                return 3
            merged.append(lane["name"])

        all_files = sorted(set().union(*(set(files) for _lane, _sha, files in pushed)))
        sanity(worktree, all_files, parser_root=repo)
        validation = project.get("validation") or project.get("validate")
        if validation:
            result = subprocess.run(str(validation), cwd=worktree, shell=True, text=True)
            if result.returncode:
                raise GroupError(f"project validation failed ({result.returncode}): {validation}")
        print("clean assembly; conflict-marker and syntax sanity checks passed")
        if validation:
            print(f"project validation passed: {validation}")
        if args.dry_run:
            print("dry-run: integration branch was not pushed and no PR was opened")
            return 0

        integration = group["integration_branch"]
        repo_name = str(project.get("repo") or "")
        if not repo_name:
            raise GroupError(f"project '{group['project']}' has no GitHub repo configured")
        old_integration = remote_sha(repo, integration)
        push = ["git", "-C", worktree, "push", "-u"]
        if old_integration:
            push.append(f"--force-with-lease=refs/heads/{integration}:{old_integration}")
        push.extend(("origin", f"HEAD:refs/heads/{integration}"))
        run(push)
        pr_url = existing_pr(repo_name, integration)
        if not pr_url:
            body_path = GROUPS / f"{group['name']}-pr.md"
            lines = [f"## Fleet group `{group['name']}`", "",
                     "One integration branch assembled from isolated lane branches:", ""]
            for lane, _sha, files in pushed:
                lines.append(f"- `{lane['name']}` — `{', '.join(lane['territory'])}` — "
                             f"{lane['author_name']} <{lane['author_email']}> — {len(files)} file(s)")
            lines.extend(("", "## Validation", "",
                          "- Deterministic `--no-ff` lane merges completed without conflicts.",
                          "- Conflict-marker sweep and per-file syntax sanity passed.",
                          "- This PR is intentionally not merged; human review owns merge approval."))
            body_path.write_text("\n".join(lines) + "\n")
            result = run(["gh", "pr", "create", "-R", repo_name, "--base", base,
                          "--head", integration, "--title", f"Fleet group {group['name']}",
                          "--body-file", str(body_path)])
            output = result.stdout.strip().splitlines()
            if not output:
                raise GroupError("gh pr create succeeded without returning a PR URL")
            pr_url = output[-1]
        with group_lock(group["name"]):
            fresh = load_group(group["name"])
            fresh["status"] = "pr_open"
            fresh["pr_url"] = pr_url
            fresh["assembled_at"] = int(time.time())
            save_group(fresh)
        print(pr_url)
        return 0
    finally:
        run(["git", "-C", repo, "worktree", "remove", "--force", worktree], check=False)
        shutil.rmtree(worktree, ignore_errors=True)


def parser():
    root = argparse.ArgumentParser(prog="fleet group")
    sub = root.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("name")
    start.add_argument("--project", required=True)
    start.add_argument("--spec", required=True)
    start.set_defaults(func=cmd_start)
    status = sub.add_parser("status")
    status.add_argument("name")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)
    assemble = sub.add_parser("assemble")
    assemble.add_argument("name")
    assemble.add_argument("--dry-run", action="store_true")
    assemble.set_defaults(func=cmd_assemble)
    guard = sub.add_parser("guard", help=argparse.SUPPRESS)
    guard.add_argument("name")
    guard.add_argument("lane")
    guard.set_defaults(func=cmd_guard)
    return root


def main():
    args = parser().parse_args()
    try:
        result = args.func(args)
        return int(result or 0)
    except GroupError as exc:
        print(f"fleet group: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
