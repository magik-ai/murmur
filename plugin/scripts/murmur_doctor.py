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
    check_hooks(report, args.fix)
    check_tool(report, "uv", "the scripts here run with uv run", True)
    check_gh(report)
    check_tracker(root, report, config)
    check_tool(report, "claude", "the agents run in it", True)
    check_stale_branches(root, report)
    check_optional(report, config)
    status = final_status(report)
    print(report.render())
    print(f"\nstatus: {status}")
    return 0 if status in {"current", "repaired", "warnings"} else 1


if __name__ == "__main__":
    sys.exit(main())
