#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Onboard one repository: ask, store, then write the files.

    questions   print the questions still unanswered, as JSON
    answer      store one answer in .murmur/config.toml
    apply       write the files from the answers, print a JSON report

Rerunning is safe. An answered question does not come back. Apart from
.murmur/config.toml, which holds the answers, no file that exists is
overwritten: the contract and the tracker rules get a <name>.murmur-new beside
them when they differ, the other files are left as they are, and an existing
CLAUDE.md or AGENTS.md gets a four-line pointer to the contract, once.

Codex reads AGENTS.md and never CLAUDE.md. `apply --agents-md` writes an
AGENTS.md that holds only a title and the pointer when the repository has none.
Claude Code reads AGENTS.md only while there is no CLAUDE.md, so a CLAUDE.md
written beside an AGENTS.md begins with the line @AGENTS.md, which imports it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

CONFIG = Path(".murmur/config.toml")
CONTRACT = Path(".murmur/contract.md")
MARKER = "<!-- murmur:contract -->"
TRACKERS = ["github-issues", "linear", "jira", "notion", "none"]
NEVER = ["merge", "force-push", "production-writes", "paid-provisioning"]


def run(args: list[str], cwd: Path | None = None) -> str:
    try:
        out = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def repo_root() -> Path:
    top = run(["git", "rev-parse", "--show-toplevel"])
    return Path(top) if top else Path.cwd()


def default_repo(root: Path) -> str:
    url = run(["git", "remote", "get-url", "origin"], root)
    if url:
        url = url.removesuffix(".git")
        match = re.search(r"[:/]([^/:]+/[^/]+)$", url)
        if match:
            return match.group(1)
    return root.name


FIELDS = ("id", "prompt", "type", "choices", "multiple", "default")


def questions_for(root: Path) -> list[dict]:
    rows = [
        ("repo", "Which repository is this, as owner/name?", "text", [], 0,
         default_repo(root)),
        ("base_branch", "Which branch does work start from, and merge back into?",
         "text", [], 0, "main"),
        ("tracker", "Where is work tracked?", "choice", TRACKERS, 0, "github-issues"),
        ("naming", "Who names an agent: you, once per session, or one fixed name?",
         "choice", ["owner-names-per-session", "fixed-name"], 0,
         "owner-names-per-session"),
        ("never_without_owner", "What never happens without you? Comma separated.",
         "choice", NEVER, 1, ",".join(NEVER)),
        ("coordination", "Where are branch claims recorded?", "choice",
         ["this-machine", "private-github-repo"], 0, "this-machine"),
        ("farm", "Is there a separate machine that runs agents?", "choice",
         ["yes", "not-yet"], 0, "not-yet"),
    ]
    out = []
    for row in rows:
        question = dict(zip(FIELDS, row))
        if not question.pop("multiple"):
            out.append(question)
        else:
            out.append({**question, "multiple": True})
    return out


def load_config(root: Path) -> dict:
    path = root / CONFIG
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        # Stop instead of starting over: `answer` and `apply` write the config back, so an
        # unreadable file read as empty would be replaced, and what the person wrote lost.
        raise SystemExit(
            f"{CONFIG} could not be read ({error}). Nothing was changed. Fix the file by "
            "hand, or move it away to answer the questions again."
        ) from None


def toml_value(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(str(item)) for item in value) + "]"
    return json.dumps(str(value))


def save_config(root: Path, config: dict) -> None:
    path = root / CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    order = [q["id"] for q in questions_for(root)]
    keys = [k for k in order if k in config] + [k for k in config if k not in order]
    body = ["# murmur configuration. Written by the init skill, safe to edit by hand."]
    body += [f"{key} = {toml_value(config[key])}" for key in keys]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def templates_dir() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [here.parent.parent / "templates", here.parent / "templates"]
    env = os.environ.get("MURMUR_TEMPLATES")
    if env:
        candidates.insert(0, Path(env))
    for path in candidates:
        if (path / "CLAUDE.md").is_file():
            return path
    raise SystemExit(
        "Templates not found. Looked in: "
        + ", ".join(str(p) for p in candidates)
        + ". Set MURMUR_TEMPLATES to the templates directory."
    )


def generated_example() -> Path:
    here = Path(__file__).resolve().parent
    for path in [
        here.parent / "hooks" / "generated-files.example.txt",
        templates_dir() / "hooks" / "generated-files.example.txt",
    ]:
        if path.is_file():
            return path
    raise SystemExit("The generated-files example is missing from the plugin.")


def cmd_questions(root: Path) -> int:
    config = load_config(root)
    pending = [q for q in questions_for(root) if not config.get(q["id"])]
    print(json.dumps(pending, indent=2))
    return 0


def cmd_answer(root: Path, qid: str, value: str) -> int:
    known = {q["id"]: q for q in questions_for(root)}
    question = known.get(qid)
    if question is None:
        print(f"Unknown question: {qid}. Known: {', '.join(known)}", file=sys.stderr)
        return 1
    value = value.strip()
    if not value:
        value = str(question["default"])
    if question.get("multiple"):
        picked = [part.strip() for part in value.split(",") if part.strip()]
        bad = [p for p in picked if p not in question["choices"]]
        if bad or not picked:
            print(f"{qid}: pick from {question['choices']}", file=sys.stderr)
            return 1
        stored: object = picked
    elif question["type"] == "choice":
        if value not in question["choices"]:
            print(f"{qid}: pick one of {question['choices']}", file=sys.stderr)
            return 1
        stored = value
    elif question["type"] == "bool":
        stored = value.lower() in {"y", "yes", "true", "1"}
    else:
        stored = value
    config = load_config(root)
    config[qid] = stored
    save_config(root, config)
    print(json.dumps({"stored": {qid: stored}, "config": str(CONFIG)}))
    return 0


def section(text: str, heading: str) -> str:
    keep: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.strip() == heading
            if inside:
                keep.append(line)
            continue
        if inside:
            keep.append(line)
    return "\n".join(keep).rstrip()


def rebase_text(text: str, base: str) -> str:
    if base == "main":
        return text
    return text.replace("`main`", f"`{base}`").replace("origin/main", f"origin/{base}")


NAME_LINES = {
    "fixed-name": "Agents here use one fixed name, which the owner gives you. If you do not"
    " know it, ask.",
    "owner-names-per-session": "Your name comes from the owner, per session, never"
    " from memory.",
}
CLAIM_LINES = {
    "private-github-repo": "Claims live in a private coordination repository. Claim a"
    " branch there before you create or push it, and release it when the PR merges.",
    "this-machine": "There is no shared claims store yet: one session works on one"
    " branch at a time, the branch name is the claim, and a second session on the"
    " same branch is a mistake. Add a private coordination repository when two"
    " sessions or two machines need to share this repository.",
}
FARM_LINES = {
    "yes": "Heavy and parallel runs belong on the separate agent machine.",
    "not-yet": "There is no separate agent machine yet, so everything runs here.",
}
SECTIONS = [
    "## 0. Core contract",
    "## 2. Golden Workflow: 10 gates",
    "## 3. Commits",
    "## 7. Don'ts",
]


# What stands in a fresh CLAUDE.md for each section the contract holds, so that every rule is
# written once and a reference such as "the Golden Workflow" still finds its section.
MOVED = "This section is in [`.murmur/contract.md`](.murmur/contract.md)."


def without_contract_sections(template: str) -> str:
    """The template with each of SECTIONS cut down to its heading and the MOVED line."""
    keep: list[str] = []
    moved = False
    for line in template.splitlines():
        if line.startswith("## "):
            moved = line.strip() in SECTIONS
            keep.append(line)
            if moved:
                keep.extend(["", MOVED, ""])
            continue
        if not moved:
            keep.append(line)
    return "\n".join(keep) + "\n"


def build_contract(config: dict, template: str) -> str:
    base = config["base_branch"]
    tracker = config["tracker"]
    never = ", ".join(config["never_without_owner"]) or "nothing is reserved"
    if tracker == "none":
        tracked = (
            "There is no tracker. The pull request is the record, and"
            " `.claude/tracker.md` says how it is kept."
        )
    else:
        tracked = (
            f"Work is tracked in {tracker}. Taking a task, linking the pull request"
            " and posting evidence: `.claude/tracker.md`."
        )
    head = f"""{MARKER}
# The contract for agent work in this repository

Repository `{config['repo']}`. Work starts from `{base}` and merges back into `{base}`.

## What never happens without the owner

These actions need the owner's explicit word, every time: {never}.
A green pipeline is permission to merge, never the decision to merge.

## Identity and claims

{NAME_LINES[config['naming']]}
{CLAIM_LINES[config['coordination']]}
Never touch a branch another agent has claimed: no push, no rebase, no merge.

## Where the work is written down

{tracked}
{FARM_LINES[config['farm']]}

"""
    parts = [section(template, heading) for heading in SECTIONS]
    tail = (
        "\n\n## The rest\n\n"
        "The long form of this method, with the reasoning behind each rule, is the "
        "murmur handbook: https://github.com/magik-ai/murmur/tree/main/docs. This file "
        "is the part that binds.\n"
    )
    return rebase_text(head + "\n\n".join(p for p in parts if p) + tail, base)


def fill_template(text: str, config: dict) -> str:
    repo = config["repo"]
    product = repo.split("/")[-1]
    tracker = config["tracker"]
    out = text.replace("<ORG>/<REPO>", repo).replace("<PRODUCT>", product)
    out = out.replace("<TRACKER>", "no tracker" if tracker == "none" else tracker)
    return rebase_text(out, config["base_branch"])


# A blank the person fills in: upper-case words in angle brackets, such as <NAME> or
# <KIND OF WORK>. A single letter is not one, so a type such as Result<T> is not taken for a
# blank, and neither is anything inside an HTML comment, where the template's own <PLACEHOLDER>
# names the blanks instead of being one. The role words are no blanks either: they may stay,
# and the session hook tells every agent what they mean in this repository.
PLACEHOLDER = re.compile(r"<[A-Z][A-Z0-9_]+(?: [A-Z0-9_]+)*>")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
ROLE_WORDS = {"<OWNER>", "<TRACKER>", "<FARM>"}


def placeholders(text: str) -> list[str]:
    """The blanks still in the text, each once, in the order they first appear."""
    found = PLACEHOLDER.findall(COMMENT.sub("", text))
    return [blank for blank in dict.fromkeys(found) if blank not in ROLE_WORDS]


def place(root: Path, rel: Path, content: str, mode: str, report: list[dict]) -> None:
    """mode "once": leave anything already there. mode "managed": write alongside."""
    target = root / rel
    if target.is_file():
        current = target.read_text(encoding="utf-8")
        if current == content:
            report.append({"path": str(rel), "action": "skipped", "note": "identical"})
            return
        if mode == "once":
            report.append(
                {"path": str(rel), "action": "skipped", "note": "exists, left as it is"}
            )
            return
        beside = target.with_name(target.name + ".murmur-new")
        beside.write_text(content, encoding="utf-8")
        note = f"{rel} exists and differs, compare the two and keep one"
        where = str(beside.relative_to(root))
        report.append({"path": where, "action": "alongside", "note": note})
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    report.append({"path": str(rel), "action": "wrote", "note": ""})


def pointer_block(base: str) -> str:
    return "\n".join([
        MARKER,
        "Agent work in this repository follows `.murmur/contract.md`.",
        f"Read it before the first action, and branch from `{base}`, never commit"
        " to it.",
        "Run the doctor command when anything about the setup looks wrong.",
    ])


def add_pointer(root: Path, rel: Path, base: str, report: list[dict]) -> None:
    target = root / rel
    if not target.is_file():
        return
    text = target.read_text(encoding="utf-8")
    if MARKER in text:
        report.append({"path": str(rel), "action": "skipped", "note": "pointer there"})
        return
    joiner = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    target.write_text(text + joiner + pointer_block(base) + "\n", encoding="utf-8")
    report.append({"path": str(rel), "action": "appended", "note": "pointer added"})


def cmd_apply(root: Path, use_defaults: bool = False, agents_md: bool = False) -> int:
    config = load_config(root)
    questions = questions_for(root)
    missing = [q["id"] for q in questions if not config.get(q["id"])]
    if missing and use_defaults:
        for q in questions:
            if q["id"] in missing:
                default = q["default"]
                config[q["id"]] = default.split(",") if q.get("multiple") else default
        missing = []
    if missing:
        print(json.dumps({"status": "setup-required", "missing": missing,
                          "hint": "answer them, or run apply --defaults"}))
        return 1
    templates = templates_dir()
    law = (templates / "CLAUDE.md").read_text(encoding="utf-8")
    report: list[dict] = []
    save_config(root, config)
    report.append({"path": str(CONFIG), "action": "wrote", "note": "your answers"})
    sources = [
        (".claude/tracker.md", templates / "trackers" / f"{config['tracker']}.md", "managed"),
        (".github/PULL_REQUEST_TEMPLATE.md", templates / "PULL_REQUEST_TEMPLATE.md", "once"),
        ("docs/GOTCHAS.md", templates / "GOTCHAS.md", "once"),
        (".claude/generated-files.txt", generated_example(), "once"),
    ]
    place(root, CONTRACT, build_contract(config, law), "managed", report)
    for rel, source, mode in sources:
        place(root, Path(rel), source.read_text(encoding="utf-8"), mode, report)
    base = config["base_branch"]
    if (root / "CLAUDE.md").is_file():
        add_pointer(root, Path("CLAUDE.md"), base, report)
    else:
        # Claude Code reads AGENTS.md only while there is no CLAUDE.md, so a new CLAUDE.md
        # imports the AGENTS.md the repository already has.
        imports = (root / "AGENTS.md").is_file()
        fresh = (("@AGENTS.md\n\n" if imports else "")
                 + fill_template(without_contract_sections(law), config) + "\n"
                 + pointer_block(base) + "\n")
        place(root, Path("CLAUDE.md"), fresh, "managed", report)
        if imports:
            report[-1]["note"] = ("from the template, importing AGENTS.md so Claude Code still "
                                  "reads it; some placeholders still to fill")
        else:
            report[-1]["note"] = "from the template, some placeholders still to fill"
        report[-1]["placeholders"] = placeholders(fresh)
    if (root / "AGENTS.md").is_file():
        add_pointer(root, Path("AGENTS.md"), base, report)
    elif agents_md:
        place(root, Path("AGENTS.md"), "# AGENTS.md\n\n" + pointer_block(base) + "\n", "once",
              report)
        report[-1]["note"] = "a title and the pointer to the contract, for Codex"
    summary = {
        "status": "applied",
        "repo": config["repo"],
        "base_branch": base,
        "tracker": config["tracker"],
        "files": report,
    }
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("questions", help="print the unanswered questions as JSON")
    answer = subs.add_parser("answer", help="store one answer")
    answer.add_argument("--id", required=True)
    answer.add_argument("--value", required=True)
    apply = subs.add_parser("apply", help="write the files and print a report")
    apply.add_argument("--defaults", action="store_true",
                       help="fill every unanswered question with its default first")
    apply.add_argument("--agents-md", action="store_true",
                       help="also write AGENTS.md, with the pointer, when there is none")
    args = parser.parse_args()
    root = repo_root()
    if args.command == "questions":
        return cmd_questions(root)
    if args.command == "answer":
        return cmd_answer(root, args.id, args.value)
    return cmd_apply(root, use_defaults=args.defaults, agents_md=args.agents_md)


if __name__ == "__main__":
    sys.exit(main())
