#!/usr/bin/env python3
"""The newcomer docs, the skills and the landing page tell one story.

Nothing else tests these files, and each fact below appears in several of them:
the line to paste into an agent, the folder murmur lives in, the plugin's
version, the skills' names and the scripts they run, and the links between the
docs. A change to one copy that misses another fails here.

    python3 tests/test_docs_agree.py -v
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPT = "Install murmur for this repo: https://github.com/magik-ai/murmur"
NEWCOMER_DOCS = [
    "README.md", "INSTALL.md", "docs/getting-started.md", "docs/README.md",
    "docs/12-the-machine.md", "plugin/README.md", "farm/README.md", "hq/README.md",
    "fleet/README.md", "fleet/docs/QUICKSTART.md",
]
SKILL_DIRS = sorted((ROOT / "plugin" / "skills").glob("*/SKILL.md")) + [
    ROOT / "fleet" / "skills" / "fleet" / "SKILL.md"]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "no front matter"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if value:
            fields[key.strip()] = value.strip()
    return fields


def bullets(text: str) -> list[str]:
    """Each list item as one line, with its wrapped continuation lines joined."""
    items: list[str] = []
    for line in text.splitlines():
        if re.match(r"\s*[-*] ", line):
            items.append(line.strip())
        elif items and line.startswith("  ") and line.strip():
            items[-1] += " " + line.strip()
    return items


def github_anchor(heading: str) -> str:
    text = re.sub(r"[`*_\[\]()<>]", "", heading.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def anchors(path: Path) -> set[str]:
    found, seen = set(), {}
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        match = re.match(r"#{1,6}\s+(.*)", line)
        if match:
            base = github_anchor(match.group(1))
            count = seen.get(base, 0)
            found.add(base if count == 0 else f"{base}-{count}")
            seen[base] = count + 1
    return found


class OneStory(unittest.TestCase):
    def test_the_line_to_paste_is_the_same_everywhere(self):
        for rel in ("README.md", "docs/getting-started.md", "site/index.html",
                    "plugin/README.md"):
            with self.subTest(rel):
                self.assertIn(PROMPT, read(rel))

    def test_murmur_lives_in_one_folder(self):
        for rel in NEWCOMER_DOCS + [str(p.relative_to(ROOT)) for p in SKILL_DIRS]:
            with self.subTest(rel):
                self.assertNotIn("~/.murmur", read(rel))

    def test_no_doc_calls_sonnet_the_default(self):
        """Claude lanes default to opus (fleet/bin/fleet); a doc that says
        otherwise sends the reader to the wrong model."""
        prose = re.compile(r"sonnet[^.\n]{0,40}\bis the default|default (model )?is sonnet", re.I)
        for rel in NEWCOMER_DOCS + [str(p.relative_to(ROOT)) for p in SKILL_DIRS]:
            text = read(rel)
            with self.subTest(rel):
                self.assertIsNone(prose.search(text))
                for item in bullets(text):
                    if re.search(r"\bsonnet\b", item, re.I) and not re.search(r"\bopus\b", item, re.I):
                        self.assertNotRegex(item, re.compile(r"\b(it|this) is the default", re.I))

    def test_the_two_versions_agree(self):
        market = json.loads(read(".claude-plugin/marketplace.json"))
        plugin = json.loads(read("plugin/.claude-plugin/plugin.json"))
        self.assertEqual(market["plugins"][0]["version"], plugin["version"])

    def test_every_skill_is_named_after_its_folder(self):
        for skill in SKILL_DIRS:
            with self.subTest(skill.parent.name):
                fields = frontmatter(skill.read_text(encoding="utf-8"))
                self.assertEqual(fields.get("name"), skill.parent.name)
                self.assertTrue(0 < len(fields.get("description", "")) <= 1024)

    def test_every_script_a_skill_or_command_runs_exists(self):
        plugin = ROOT / "plugin"
        files = [*plugin.glob("skills/*/SKILL.md"), *plugin.glob("commands/*.md"),
                 plugin / "hooks" / "hooks.json"]
        for path in files:
            for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", path.read_text()):
                with self.subTest(f"{path.relative_to(ROOT)}: {rel}"):
                    self.assertTrue((plugin / rel).exists())

    def test_links_between_the_docs_resolve(self):
        for rel in NEWCOMER_DOCS:
            source = ROOT / rel
            text = re.sub(r"```.*?```", "", source.read_text(encoding="utf-8"), flags=re.S)
            for target in re.findall(r"\]\(([^)\s]+)\)", text):
                if re.match(r"[a-z]+:", target):
                    continue
                path_part, _, anchor = target.partition("#")
                dest = (source.parent / path_part).resolve() if path_part else source
                with self.subTest(f"{rel} -> {target}"):
                    self.assertTrue(dest.exists(), f"missing {dest}")
                    if anchor and dest.suffix == ".md":
                        self.assertIn(anchor, anchors(dest))

    def test_no_copy_button_holds_several_slash_commands(self):
        for copy in re.findall(r'data-copy="([^"]*)"', read("site/index.html")):
            lines = [line for line in copy.split("&#10;") if line.startswith("/")]
            with self.subTest(copy[:40]):
                self.assertLessEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
