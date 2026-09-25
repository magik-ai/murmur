#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write murmur's skills into Codex's skills folder, from this clone.

    install     write every skill of this clone there, print a JSON report
    status      what is there and what install would change, as JSON; changes nothing
    uninstall   remove the skills this script wrote, print a JSON report

Codex reads skills from ~/.agents/skills, the default; --dest names another folder, such as
~/.codex/skills for an older Codex, and so does MURMUR_SKILLS_DIR. A skill of the plugin,
plugin/skills/<name>, is written as murmur-<name>, the entry skill plugin/skills/murmur as
murmur, and the fleet's own skill, fleet/skills/fleet, as fleet.

Each one is a copy made for Codex. Its `name` is its folder's name, as the Agent Skills format
requires. ${CLAUDE_PLUGIN_ROOT}, which only Claude Code fills in, becomes this clone's plugin
folder, and a command /murmur:<name> becomes $murmur-<name>, as Codex calls a skill. A metadata
block in the frontmatter records the source folder and the clone's commit. The copies point
into this clone, so it must stay where it is, such as ~/work/murmur; a copy of murmur in one
of Claude Code's plugin folders is refused, since Claude Code changes or removes those.

That metadata is how a folder is known to be murmur's. Only such a folder is replaced or
removed; anything else under a skill's name is a conflict, reported and never touched, and
install then exits 1. install also removes a murmur folder whose source skill is gone, and the
links an older install left in ~/.codex/skills that point into this clone. Rerunning is safe:
a folder that is already what install would write is left as it is.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLONE = HERE.parent.parent
# Claude Code's own plugin folders: the cache, which changes with every update of the plugin,
# and the marketplace clone, which goes when the marketplace is removed.
PLUGINS = "/.claude/plugins/"
DEFAULT_DEST = "~/.agents/skills"
OLD_LINKS = Path.home() / ".codex" / "skills"
SOURCE_KEY, COMMIT_KEY = "murmur-source", "murmur-commit"
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
# A command such as /murmur:doctor, and not a path or an address that holds the same letters.
COMMAND = re.compile(r"(?<![\w./-])/murmur:([a-z0-9][a-z0-9-]*)")


def clone_root() -> Path:
    """The clone this script is in, which the copies will point into."""
    if PLUGINS in HERE.as_posix() + "/":
        where = "in one of Claude Code's plugin folders, which Claude Code changes or removes"
    elif not (CLONE / "plugin" / "skills").is_dir():
        where = "not in a clone of murmur"
    else:
        return CLONE
    raise SystemExit(
        f"{HERE} is {where}. Run this script from a clone that stays where it is: "
        "git clone https://github.com/magik-ai/murmur ~/work/murmur, then "
        "uv run ~/work/murmur/plugin/scripts/murmur_skills.py install. Nothing was changed.")


def commit_of(root: Path) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else "unknown"


def destination(args) -> Path:
    chosen = args.dest or os.environ.get("MURMUR_SKILLS_DIR") or DEFAULT_DEST
    return Path(chosen).expanduser().absolute()


def sources(root: Path) -> dict[str, Path]:
    """{folder name: source skill folder} for every skill of this clone."""
    found = {}
    for skill in sorted((root / "plugin" / "skills").glob("*/SKILL.md")):
        name = skill.parent.name
        found["murmur" if name == "murmur" else f"murmur-{name}"] = skill.parent
    fleet = root / "fleet" / "skills" / "fleet"
    if (fleet / "SKILL.md").is_file():
        found["fleet"] = fleet
    return found


def for_codex_text(text: str, root: Path) -> str:
    """The plugin folder where Claude Code would fill it in, and each command as Codex's."""
    text = text.replace("${CLAUDE_PLUGIN_ROOT}", str(root / "plugin"))
    return COMMAND.sub(r"$murmur-\1", text)


def for_codex(text: str, name: str, source: Path, root: Path, commit: str) -> str:
    """A SKILL.md made for Codex: the text as for_codex_text makes it, and in the frontmatter
    `name` set to the folder's name and murmur's two metadata keys."""
    text = for_codex_text(text, root)
    match = FRONT.match(text)
    head = match.group(1).splitlines() if match else []
    body = text[match.end():] if match else text
    lines = [f"name: {name}" if line.startswith("name:") else line for line in head]
    if f"name: {name}" not in lines:
        lines.insert(0, f"name: {name}")
    if "metadata:" in lines:                              # the skill's own metadata is kept
        at = lines.index("metadata:") + 1
        child = lines[at] if at < len(lines) else ""
        pad = child[:len(child) - len(child.lstrip())] or "  "
    else:
        lines.append("metadata:")
        at, pad = len(lines), "  "
    lines[at:at] = [f"{pad}{SOURCE_KEY}: {json.dumps(str(source))}",
                    f"{pad}{COMMIT_KEY}: {json.dumps(commit)}"]
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def wanted(name: str, source: Path, root: Path, commit: str) -> dict[str, bytes]:
    """{path in the folder: bytes} of the folder install writes for one skill."""
    files = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(source).as_posix()
        data = path.read_bytes()
        if rel == "SKILL.md":
            data = for_codex(data.decode("utf-8"), name, source, root, commit).encode("utf-8")
        elif path.suffix == ".md":
            data = for_codex_text(data.decode("utf-8"), root).encode("utf-8")
        files[rel] = data
    return files


def held(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*")) if path.is_file()}


def murmur_source(folder: Path) -> str | None:
    """The source a folder this script wrote records; None for any other folder."""
    skill = folder / "SKILL.md"
    if folder.is_symlink() or not skill.is_file():
        return None
    match = FRONT.match(skill.read_text(encoding="utf-8", errors="replace"))
    if not match:
        return None
    found = re.search(rf"^\s+{SOURCE_KEY}:\s*(.+?)\s*$", match.group(1), re.MULTILINE)
    if not found:
        return None
    try:
        return str(json.loads(found.group(1)))
    except ValueError:
        return found.group(1)


def conflict(target: Path, gone: list[Path]) -> str | None:
    """Why the name is not murmur's to write, or None when it is free or holds murmur's."""
    if target in gone or not (target.exists() or target.is_symlink()):
        return None
    if target.is_symlink():
        return f"a link to {os.readlink(target)}"
    if not target.is_dir():
        return "a file murmur did not write"
    if murmur_source(target) is None:
        return "a folder murmur did not write"
    return None


def old_links(root: Path) -> list[Path]:
    """The links an older install left in ~/.codex/skills that point into this clone."""
    if not OLD_LINKS.is_dir():
        return []
    inside = os.path.realpath(root) + os.sep
    return [link for link in sorted(OLD_LINKS.iterdir())
            if link.is_symlink() and os.path.realpath(link).startswith(inside)]


def stale(dest: Path, names: set[str]) -> list[Path]:
    """murmur's folders whose source skill is gone: renamed, or removed from its clone."""
    if not dest.is_dir():
        return []
    found = []
    for folder in sorted(dest.iterdir()):
        source = murmur_source(folder) if folder.name not in names else None
        if source is not None and not (Path(source) / "SKILL.md").is_file():
            found.append(folder)
    return found


def mode_for_folders() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return 0o777 & ~mask


def write_folder(target: Path, files: dict[str, bytes]) -> None:
    """Build the folder beside its place, then rename it in: whoever reads the skills sees the
    old one or the new one, never half of one."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for rel, data in files.items():
            (fresh / rel).parent.mkdir(parents=True, exist_ok=True)
            (fresh / rel).write_bytes(data)
        fresh.chmod(mode_for_folders())
        if target.exists():
            remove_folder(target, keep=fresh)
        else:
            fresh.rename(target)
    except BaseException:
        shutil.rmtree(fresh, ignore_errors=True)
        raise


def remove_folder(target: Path, keep: Path | None = None) -> None:
    """Move the folder out of the way under a hidden name, put `keep` in its place, delete it."""
    old = Path(tempfile.mkdtemp(prefix=f".{target.name}.old.", dir=target.parent))
    old.rmdir()
    target.rename(old)
    if keep is not None:
        keep.rename(target)
    shutil.rmtree(old, ignore_errors=True)


def entry(name: str, target: Path, source: Path, **more) -> dict:
    return {"name": name, "path": str(target), "source": str(source), **more}


def cmd_install(args) -> int:
    root = clone_root()
    commit, dest = commit_of(root), destination(args)
    report = {"clone": str(root), "commit": commit, "dest": str(dest), "dry_run": args.dry_run,
              "written": [], "unchanged": [], "conflicts": [], "removed": []}
    gone = old_links(root)
    for link in gone:
        report["removed"].append({"path": str(link), "why": "a link into this clone that an "
                                  "older install left"})
        if not args.dry_run:
            link.unlink()
    skills = sources(root)
    for name, source in skills.items():
        target = dest / name
        why = conflict(target, gone)
        if why:
            report["conflicts"].append(entry(name, target, source, why=why))
            continue
        files = wanted(name, source, root, commit)
        if target.is_dir() and target not in gone and held(target) == files:
            report["unchanged"].append(entry(name, target, source))
            continue
        if not args.dry_run:
            write_folder(target, files)
        report["written"].append(entry(name, target, source))
    for folder in stale(dest, set(skills)):
        report["removed"].append({"path": str(folder), "why": "its source skill is gone"})
        if not args.dry_run:
            remove_folder(folder)
    print(json.dumps(report, indent=2))
    return 1 if report["conflicts"] else 0


def cmd_status(args) -> int:
    root = clone_root()
    commit, dest = commit_of(root), destination(args)
    gone = old_links(root)
    skills = sources(root)
    rows = []
    for name, source in skills.items():
        target = dest / name
        why = conflict(target, gone)
        if why:
            rows.append(entry(name, target, source, state="conflict", why=why))
        elif target in gone or not target.exists():
            rows.append(entry(name, target, source, state="missing"))
        elif held(target) == wanted(name, source, root, commit):
            rows.append(entry(name, target, source, state="current"))
        else:
            rows.append(entry(name, target, source, state="outdated"))
    print(json.dumps({"clone": str(root), "commit": commit, "dest": str(dest), "skills": rows,
                      "stale": [str(folder) for folder in stale(dest, set(skills))],
                      "old_links": [str(link) for link in gone]}, indent=2))
    return 0


def cmd_uninstall(args) -> int:
    root = clone_root()
    dest = destination(args)
    removed = []
    for link in old_links(root):
        removed.append({"path": str(link), "why": "a link into this clone that an older "
                        "install left"})
        if not args.dry_run:
            link.unlink()
    for folder in sorted(dest.iterdir()) if dest.is_dir() else []:
        if murmur_source(folder) is not None:
            removed.append({"path": str(folder), "why": "a skill murmur wrote"})
            if not args.dry_run:
                remove_folder(folder)
    print(json.dumps({"clone": str(root), "dest": str(dest), "dry_run": args.dry_run,
                      "removed": removed}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subs = parser.add_subparsers(dest="command", required=True)
    for name, run, text in (("install", cmd_install, "write the skills, print a report"),
                            ("status", cmd_status, "say what is there, change nothing"),
                            ("uninstall", cmd_uninstall, "remove the skills murmur wrote")):
        sub = subs.add_parser(name, help=text)
        sub.add_argument("--dest", help=f"the skills folder (default: $MURMUR_SKILLS_DIR, "
                                        f"else {DEFAULT_DEST})")
        if name != "status":
            sub.add_argument("--dry-run", action="store_true",
                             help="say what would change, change nothing")
        sub.set_defaults(run=run)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
