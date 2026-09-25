#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check the setup of one repository and say, in one word, where it stands.

    uv run murmur_doctor.py          look, change nothing
    uv run murmur_doctor.py --fix    repair only what is safe to repair

The last line is the status, one of:

    setup-required   something needed is missing; the rows marked missing say what
    current          everything checked is in place
    warnings         it works, but something will cause trouble later
    repaired         a safe repair was made, and nothing else is wrong

A repair is safe when it touches no content a person wrote: making a shipped
hook executable, or creating a config file that does not exist from the
defaults. A config file that exists is never rewritten, even when it cannot be
read. Nothing else is ever changed here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path

CONFIG = Path(".murmur/config.toml")
CONTRACT = Path(".murmur/contract.md")
KEYS = [
    "repo",
    "base_branch",
    "tracker",
    "naming",
    "never_without_owner",
    "coordination",
    "farm",
]
STALE_DAYS = 7
# The agents run in Claude Code or in Codex, and one of the two is enough.
ENGINES = ("claude", "codex")

# What init writes. The pointer is the block it puts in CLAUDE.md and AGENTS.md, which Claude
# Code and Codex read, and which send an agent to the contract.
MARKER = "<!-- murmur:contract -->"
PR_TEMPLATE = Path(".github/PULL_REQUEST_TEMPLATE.md")
INIT_FILES = [PR_TEMPLATE, Path("docs/GOTCHAS.md")]
GENERATED = Path(".claude/generated-files.txt")
SETUP_FILES = [CONFIG, CONTRACT, Path(".claude/tracker.md"), *INIT_FILES, GENERATED,
               Path("CLAUDE.md"), Path("AGENTS.md")]
AGAIN = "run murmur_init.py apply again, or /murmur:init"
# The blanks murmur_init.py lists when it writes CLAUDE.md from the template: upper-case words
# in angle brackets, never a single letter such as the T of Result<T>, outside HTML comments.
# The role words are no blanks: the session hook says what they mean here.
PLACEHOLDER = re.compile(r"<[A-Z][A-Z0-9_]+(?: [A-Z0-9_]+)*>")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
ROLE_WORDS = {"<OWNER>", "<TRACKER>", "<FARM>"}

OK, WARN, MISSING, OPTIONAL, FIXED = "ok", "warning", "missing", "optional", "fixed"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, check: str, state: str, detail: str) -> None:
        self.rows.append((check, state, detail))

    def states(self) -> list[str]:
        return [state for _, state, _ in self.rows]

    def render(self) -> str:
        head = ("Check", "State", "Detail")
        rows = [head, *self.rows]
        w0 = max(len(r[0]) for r in rows)
        w1 = max(len(r[1]) for r in rows)
        out = [f"{head[0]:<{w0}}  {head[1]:<{w1}}  {head[2]}"]
        out.append(f"{'-' * w0}  {'-' * w1}  {'-' * 40}")
        for check, state, detail in self.rows:
            out.append(f"{check:<{w0}}  {state:<{w1}}  {detail}")
        return "\n".join(out)


def run(args: list[str], timeout: int = 10, cwd: Path | None = None):
    try:
        return subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None


def repo_root() -> Path | None:
    result = run(["git", "rev-parse", "--show-toplevel"])
    if result is None or result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def default_config(root: Path) -> dict:
    result = run(["git", "remote", "get-url", "origin"], cwd=root)
    repo = root.name
    if result is not None and result.returncode == 0:
        url = result.stdout.strip().removesuffix(".git")
        tail = url.rsplit(":", 1)[-1].strip("/")
        parts = [p for p in tail.replace(":", "/").split("/") if p]
        if len(parts) >= 2:
            repo = "/".join(parts[-2:])
    return {
        "repo": repo,
        "base_branch": "main",
        "tracker": "github-issues",
        "naming": "owner-names-per-session",
        "never_without_owner": [
            "merge",
            "force-push",
            "production-writes",
            "paid-provisioning",
        ],
        "coordination": "this-machine",
        "farm": "not-yet",
    }


def write_config(root: Path, config: dict) -> None:
    path = root / CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# murmur configuration. Created by the doctor from the defaults."]
    for key in KEYS:
        value = config[key]
        if isinstance(value, list):
            rendered = "[" + ", ".join(json.dumps(v) for v in value) + "]"
        else:
            rendered = json.dumps(value)
        lines.append(f"{key} = {rendered}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_remote(root: Path, report: Report, base: str) -> None:
    result = run(["git", "remote"], cwd=root)
    names = result.stdout.split() if result and result.returncode == 0 else []
    if not names:
        report.add("git remote", MISSING, "no remote is configured, so nothing to push to")
        return
    remote = "origin" if "origin" in names else names[0]
    listing = run(["git", "ls-remote", "--heads", remote], timeout=5, cwd=root)
    if listing is None:
        report.add("git remote", WARN, f"{remote} did not answer within five seconds")
        return
    if listing.returncode != 0:
        report.add("git remote", WARN, f"{remote} refused the connection, check access")
        return
    # Each line is "<sha>\trefs/heads/<name>", and a name may hold a slash (release/2.x).
    heads = {line.split("\t", 1)[-1].removeprefix("refs/heads/")
             for line in listing.stdout.splitlines() if line}
    report.add("git remote", OK, f"{remote} answered, {len(heads)} branches")
    if base in heads:
        report.add("base branch", OK, f"{base} exists on {remote}")
    else:
        report.add("base branch", WARN, f"{base} is not on {remote}, check the name")


def check_config(root: Path, report: Report, fix: bool) -> dict:
    path = root / CONFIG
    if not path.exists():
        if fix:
            config = default_config(root)
            write_config(root, config)
            report.add("config", FIXED, f"{CONFIG} created from the defaults")
            return config
        report.add("config", MISSING, f"{CONFIG} is not there, run the init skill")
        return {}
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        # The file is the person's, so --fix leaves it alone: the defaults would replace
        # whatever they wrote in it.
        report.add("config", MISSING, f"{CONFIG} could not be read ({error}), fix it by hand")
        return {}
    absent = [key for key in KEYS if not config.get(key)]
    if absent:
        report.add("config", MISSING, "unanswered: " + ", ".join(absent))
    else:
        report.add("config", OK, f"{len(KEYS)} answers, repo {config['repo']}")
    return config


def check_contract(root: Path, report: Report) -> None:
    path = root / CONTRACT
    if path.is_file() and path.read_text(encoding="utf-8").strip():
        lines = len(path.read_text(encoding="utf-8").splitlines())
        report.add("contract", OK, f"{CONTRACT}, {lines} lines")
    else:
        report.add("contract", MISSING, f"{CONTRACT} is not there, run the init skill")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def has_pr_template(root: Path) -> bool:
    """GitHub takes a pull request template from .github, docs or the root, in any case and
    with any extension, or from a PULL_REQUEST_TEMPLATE folder in one of them."""
    return any(folder.is_dir() and any(entry.name.lower().startswith("pull_request_template")
                                       for entry in folder.iterdir())
               for folder in (root / ".github", root / "docs", root))


def check_init_files(root: Path, report: Report) -> None:
    missing = [rel for rel in INIT_FILES if not (root / rel).is_file()]
    if PR_TEMPLATE in missing and has_pr_template(root):
        missing.remove(PR_TEMPLATE)                       # the repository keeps its own
    if missing:
        names = ", ".join(str(rel) for rel in missing)
        report.add("init files", WARN, f"missing: {names}; {AGAIN}")
    else:
        report.add("init files", OK, "the pull request template and docs/GOTCHAS.md")
    # The list is the person's to keep or delete: without it, nothing is guarded.
    if (root / GENERATED).is_file():
        report.add("generated files", OK, f"{GENERATED} names the files never edited by hand")
    else:
        report.add("generated files", OPTIONAL, f"{GENERATED} is not there, so the guard is off")


def check_pointers(root: Path, report: Report) -> None:
    claude, agents = root / "CLAUDE.md", root / "AGENTS.md"
    if not claude.is_file():
        report.add("CLAUDE.md", WARN, f"not there, so nothing points to {CONTRACT}; {AGAIN}")
    elif MARKER not in read_text(claude):
        report.add("CLAUDE.md", WARN, f"no pointer to {CONTRACT}; {AGAIN}")
    else:
        report.add("CLAUDE.md", OK, f"points to {CONTRACT}")
    if not agents.is_file() and shutil.which("codex"):
        report.add("AGENTS.md", WARN, "not there, and codex is on the path: Codex reads "
                   "AGENTS.md, never CLAUDE.md; run murmur_init.py apply --agents-md")
    elif not agents.is_file():
        report.add("AGENTS.md", OPTIONAL, "not there; for Codex, murmur_init.py apply "
                   "--agents-md writes one that points to the contract")
    elif MARKER not in read_text(agents):
        report.add("AGENTS.md", WARN, f"no pointer to {CONTRACT}, so Codex never reads it; "
                   f"{AGAIN}")
    else:
        report.add("AGENTS.md", OK, f"points to {CONTRACT}")


def check_placeholders(root: Path, report: Report) -> None:
    path = root / "CLAUDE.md"
    if not path.is_file():
        return
    found = PLACEHOLDER.findall(COMMENT.sub("", read_text(path)))
    blanks = [blank for blank in dict.fromkeys(found) if blank not in ROLE_WORDS]
    if not blanks:
        report.add("placeholders", OK, "none left in CLAUDE.md")
        return
    shown = ", ".join(blanks[:4]) + (f" and {len(blanks) - 4} more" if len(blanks) > 4 else "")
    report.add("placeholders", WARN, f"{len(blanks)} still to fill in CLAUDE.md: {shown}; "
               "replace each one, or delete its line")


def check_pending(root: Path, report: Report) -> None:
    """The <name>.murmur-new files init wrote beside files that differ, wherever they are. The
    ones beside its own files are looked for by name too, in case git ignores them."""
    found = {f"{rel}.murmur-new" for rel in SETUP_FILES if (root / f"{rel}.murmur-new").is_file()}
    listing = run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                   "*.murmur-new"], cwd=root)
    if listing is not None and listing.returncode == 0:
        found.update(p for p in listing.stdout.split("\0") if p and (root / p).is_file())
    if found:
        report.add("murmur-new files", WARN, f"{len(found)} waiting: {', '.join(sorted(found))}; "
                   "compare each with the file beside it and keep one")
    else:
        report.add("murmur-new files", OK, "none waiting")


def check_published(root: Path, report: Report, base: str) -> None:
    """A lane starts from origin/<base>, so the setup reaches a lane only once it is there."""
    if not (root / CONTRACT).is_file():
        return                                            # nothing to push yet
    here = [str(rel) for rel in SETUP_FILES if (root / rel).is_file()]
    status = run(["git", "status", "--porcelain", "--untracked-files=all", "--", *here], cwd=root)
    lines = status.stdout.splitlines() if status is not None and status.returncode == 0 else []
    # Each line is "XY <path>", or "XY <old> -> <new>" for a rename.
    loose = sorted({line[3:].split(" -> ")[-1] for line in lines if line})
    faults = [f"not committed: {', '.join(loose)}"] if loose else []
    # The base branch as this clone last fetched it. The doctor never fetches.
    shown = run(["git", "cat-file", "-e", f"refs/remotes/origin/{base}:{CONTRACT}"], cwd=root)
    if shown is None or shown.returncode != 0:
        faults.append(f"origin/{base} has no {CONTRACT} as of the last fetch")
    if faults:
        # Committed but not on the base branch yet usually means a pull request waits.
        advice = ("commit the setup, push it and merge its pull request" if loose else
                  "merge the pull request that carries it (or push it), then git fetch")
        report.add("setup pushed", WARN, "; ".join(faults) + f"; lanes start from origin/{base},"
                   f" so {advice}")
    else:
        report.add("setup pushed", OK, f"committed, and origin/{base} has {CONTRACT}")


def plugin_hooks() -> list[Path]:
    hooks = Path(__file__).resolve().parent.parent / "hooks"
    return sorted(hooks.glob("*.sh")) if hooks.is_dir() else []


def check_hooks(report: Report, fix: bool) -> None:
    scripts = plugin_hooks()
    if not scripts:
        report.add("hooks", WARN, "no hook scripts found next to this script")
        return
    dull = [p for p in scripts if not os.access(p, os.X_OK)]
    if not dull:
        report.add("hooks", OK, f"{len(scripts)} hook scripts are executable")
        return
    if fix:
        for path in dull:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        report.add("hooks", FIXED, f"made {len(dull)} hook scripts executable")
        return
    names = ", ".join(p.name for p in dull)
    report.add("hooks", WARN, f"not executable: {names}, fixable")


def check_tool(report: Report, name: str, why: str, required: bool) -> str | None:
    found = shutil.which(name)
    if found:
        report.add(name, OK, f"on the path at {found}")
        return found
    report.add(name, MISSING if required else WARN, f"not on the path, {why}")
    return None


def check_engines(report: Report) -> None:
    found = {name: shutil.which(name) for name in ENGINES}
    if not any(found.values()):
        report.add("engines", MISSING,
                   "neither claude nor codex is on the path, the agents run in one of them")
        return
    report.add("engines", OK, "; ".join(f"{name} at {path}" if path else
                                        f"{name} is not on the path"
                                        for name, path in found.items()))


def check_gh(report: Report) -> None:
    if not shutil.which("gh"):
        report.add("gh", WARN, "not on the path, the tracker and PR steps need it")
        return
    result = run(["gh", "auth", "status"], timeout=10)
    if result is None:
        report.add("gh", WARN, "gh auth status did not answer in time")
    elif result.returncode == 0:
        report.add("gh", OK, "signed in")
    else:
        report.add("gh", WARN, "installed but not signed in, run gh auth login")


def check_tracker(root: Path, report: Report, config: dict) -> None:
    tracker = config.get("tracker")
    path = root / ".claude/tracker.md"
    if path.is_file():
        report.add("tracker", OK, f"{tracker}, rules in .claude/tracker.md")
    elif tracker == "none":
        report.add("tracker", OK, "no tracker, the pull request is the record")
    elif tracker:
        report.add("tracker", WARN, f"{tracker} chosen but .claude/tracker.md is absent")
    else:
        report.add("tracker", MISSING, "no answer yet, run the init skill")


def check_stale_branches(root: Path, report: Report) -> None:
    fmt = "%(refname:short)\t%(upstream)\t%(committerdate:unix)"
    result = run(["git", "for-each-ref", "--format", fmt, "refs/heads"], cwd=root)
    if result is None or result.returncode != 0:
        report.add("stale branches", WARN, "could not read the local branches")
        return
    cutoff = time.time() - STALE_DAYS * 86400
    stale = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[1]:
            continue
        try:
            when = float(parts[2])
        except ValueError:
            continue
        if when < cutoff:
            stale.append(parts[0])
    if not stale:
        report.add("stale branches", OK, "none older than a week without a remote")
        return
    shown = ", ".join(stale[:4]) + (" and more" if len(stale) > 4 else "")
    report.add("stale branches", WARN, f"{len(stale)} unpushed and idle: {shown}")


def check_optional(report: Report, config: dict) -> None:
    if config.get("coordination") == "private-github-repo":
        report.add("head office", OK, "claims are shared through a private repository")
    else:
        report.add("head office", OPTIONAL, "not set up, claims stay on this machine")
    if config.get("farm") == "yes":
        report.add("agent machine", OK, "a separate machine runs agents")
    else:
        report.add("agent machine", OPTIONAL, "not set up, everything runs here")


def final_status(report: Report) -> str:
    states = report.states()
    if MISSING in states:
        return "setup-required"
    if WARN in states:
        return "warnings"
    if FIXED in states:
        return "repaired"
    return "current"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fix",
        action="store_true",
        help="repair only what is safe: hook permissions, a missing config",
    )
    args = parser.parse_args()
    report = Report()
    root = repo_root()
    if root is None:
        report.add("git repository", MISSING, "this directory is not a git checkout")
        print(report.render())
        print("\nstatus: setup-required")
        return 1
    report.add("git repository", OK, str(root))
    config = check_config(root, report, args.fix)
    base = config.get("base_branch") or "main"
    check_remote(root, report, base)
    check_contract(root, report)
    check_init_files(root, report)
    check_pointers(root, report)
    check_placeholders(root, report)
    check_pending(root, report)
    check_published(root, report, base)
    check_hooks(report, args.fix)
    check_tool(report, "uv", "the scripts here run with uv run", True)
    check_gh(report)
    check_tracker(root, report, config)
    check_engines(report)
    check_stale_branches(root, report)
    check_optional(report, config)
    status = final_status(report)
    print(report.render())
    print(f"\nstatus: {status}")
    return 0 if status in {"current", "repaired", "warnings"} else 1


if __name__ == "__main__":
    sys.exit(main())
