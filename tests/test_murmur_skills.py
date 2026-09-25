"""plugin/scripts/murmur_skills.py: murmur's skills written into Codex's skills folder.

Every test builds a clone of its own in a temporary folder (the script and the skills, committed)
and a HOME of its own, so no real ~/.agents or ~/.codex is read or written. Nothing here needs
Codex or the network.

  python3 tests/test_murmur_skills.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = Path("plugin") / "scripts" / "murmur_skills.py"
SKILLS = sorted(path.parent.name for path in (REPO / "plugin" / "skills").glob("*/SKILL.md"))
FOLDERS = {"murmur" if name == "murmur" else f"murmur-{name}" for name in SKILLS} | {"fleet"}


def frontmatter(text):
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    return match.group(1).splitlines() if match else []


def body(text):
    return re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)


class Skills(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="murmur-skills-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.clone = self.make_clone(self.tmp / "work" / "murmur")
        self.dest = self.home / ".agents" / "skills"

    def git(self, *args, cwd):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                               *args], cwd=cwd, check=True, capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "HOME": str(self.home)})

    def make_clone(self, root, extra=None):
        """What a clone holds that the script reads, committed: the script and the skills."""
        files = [SCRIPT, Path("fleet/skills/fleet/SKILL.md")]
        files += [Path("plugin/skills") / name / "SKILL.md" for name in SKILLS]
        for rel in files:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, root / rel)
        for rel, text in (extra or {}).items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        self.git("init", "-q", cwd=root)
        self.git("add", "-A", cwd=root)
        self.git("commit", "-q", "-m", "A clone", cwd=root)
        return root

    def skills(self, *args, clone=None, expect=0, **env):
        script = (clone or self.clone) / SCRIPT
        done = subprocess.run([sys.executable, str(script), *args], capture_output=True,
                              text=True, timeout=60,
                              env={"PATH": "/usr/bin:/bin", "HOME": str(self.home), **env})
        self.assertNotIn("Traceback", done.stderr)
        self.assertEqual(done.returncode, expect, done.stdout + done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def source_of(self, folder, clone=None):
        clone = clone or self.clone
        if folder == "fleet":
            return clone / "fleet" / "skills" / "fleet"
        return clone / "plugin" / "skills" / ("murmur" if folder == "murmur" else
                                              folder.removeprefix("murmur-"))

    def names(self, rows):
        return {Path(row["path"]).name for row in rows}

    def test_install_writes_each_skill_as_codex_reads_it(self):
        report = self.skills("install")
        self.assertEqual(self.names(report["written"]), FOLDERS)
        self.assertEqual((report["unchanged"], report["conflicts"], report["removed"]),
                         ([], [], []))
        self.assertEqual(set(os.listdir(self.dest)), FOLDERS)
        commit = self.git("rev-parse", "HEAD", cwd=self.clone).stdout.strip()
        self.assertEqual(report["commit"], commit)
        for folder in FOLDERS:
            with self.subTest(folder=folder):
                text = (self.dest / folder / "SKILL.md").read_text()
                source = self.source_of(folder)
                head = frontmatter(text)
                # The Agent Skills format wants the name to be the folder's name.
                self.assertEqual([line for line in head if line.startswith("name:")],
                                 [f"name: {folder}"])
                self.assertEqual(head[-3:], ["metadata:", f'  murmur-source: "{source}"',
                                             f'  murmur-commit: "{commit}"'])
                # Codex fills in no ${CLAUDE_PLUGIN_ROOT}, and calls a skill $murmur-<name>.
                self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", text)
                self.assertNotRegex(text, r"(?<![\w./-])/murmur:[a-z]")
                original = (source / "SKILL.md").read_text()
                expected = re.sub(r"(?<![\w./-])/murmur:([a-z0-9-]+)", r"$murmur-\1",
                                  original.replace("${CLAUDE_PLUGIN_ROOT}",
                                                   str(self.clone / "plugin")))
                self.assertEqual(body(text), body(expected))
        init = (self.dest / "murmur-init" / "SKILL.md").read_text()
        self.assertIn(f"uv run {self.clone}/plugin/scripts/murmur_init.py apply", init)
        self.assertIn("`$murmur-doctor`", init)

    def test_the_entry_skill_is_written_as_murmur(self):
        entry = ("---\nname: murmur\ndescription: The front door.\n---\n\n"
                 "In Claude Code the commands are `/murmur:<name>`; run /murmur:init first.\n"
                 "The scripts are in ${CLAUDE_PLUGIN_ROOT}/scripts.\n")
        clone = self.make_clone(self.tmp / "entry" / "murmur",
                                {"plugin/skills/murmur/SKILL.md": entry})
        report = self.skills("install", clone=clone)
        self.assertIn("murmur", self.names(report["written"]))
        text = (self.dest / "murmur" / "SKILL.md").read_text()
        self.assertEqual(frontmatter(text)[0], "name: murmur")
        self.assertIn("run $murmur-init first", text)
        self.assertIn("`/murmur:<name>`", text)                # a pattern, not a command
        self.assertIn(f"in {clone}/plugin/scripts.", text)

    def test_a_second_run_changes_nothing(self):
        self.skills("install")
        seen = {path: (path.stat().st_ino, path.stat().st_mtime_ns)
                for path in self.dest.rglob("*")}
        report = self.skills("install")
        self.assertEqual(self.names(report["unchanged"]), FOLDERS)
        self.assertEqual((report["written"], report["conflicts"], report["removed"]),
                         ([], [], []))
        self.assertEqual({path: (path.stat().st_ino, path.stat().st_mtime_ns)
                          for path in self.dest.rglob("*")}, seen)

    def test_a_folder_murmur_did_not_write_is_never_touched(self):
        self.dest.mkdir(parents=True)
        theirs = "---\nname: murmur-init\ndescription: my own init\n---\n"
        (self.dest / "murmur-init").mkdir()
        (self.dest / "murmur-init" / "SKILL.md").write_text(theirs)
        (self.dest / "murmur-farm").write_text("a file\n")
        (self.dest / "fleet").symlink_to(self.tmp / "elsewhere")
        (self.dest / "notes").mkdir()
        report = self.skills("install", expect=1)
        self.assertEqual({row["name"]: row["why"] for row in report["conflicts"]}, {
            "murmur-init": "a folder murmur did not write",
            "murmur-farm": "a file murmur did not write",
            "fleet": f"a link to {self.tmp / 'elsewhere'}"})
        self.assertEqual(self.names(report["written"]),
                         FOLDERS - {"murmur-init", "murmur-farm", "fleet"})
        self.assertEqual((self.dest / "murmur-init" / "SKILL.md").read_text(), theirs)
        self.assertEqual((self.dest / "murmur-farm").read_text(), "a file\n")
        self.assertEqual(os.readlink(self.dest / "fleet"), str(self.tmp / "elsewhere"))
        # uninstall removes what murmur wrote, and only that.
        report = self.skills("uninstall")
        self.assertEqual(self.names(report["removed"]),
                         FOLDERS - {"murmur-init", "murmur-farm", "fleet"})
        self.assertEqual(sorted(os.listdir(self.dest)),
                         ["fleet", "murmur-farm", "murmur-init", "notes"])

    def test_another_clones_copies_are_replaced_and_a_skill_that_is_gone_removed(self):
        retired = "---\nname: retired\ndescription: An old skill.\n---\n"
        old = self.make_clone(self.tmp / "old" / "murmur",
                              {"plugin/skills/retired/SKILL.md": retired})
        self.skills("install", clone=old)
        self.assertTrue((self.dest / "murmur-retired").is_dir())
        # While the old clone has its source, its extra skill stays.
        report = self.skills("install")
        self.assertEqual(self.names(report["written"]), FOLDERS)
        self.assertEqual(report["removed"], [])
        for folder in FOLDERS:
            self.assertIn(f'  murmur-source: "{self.source_of(folder)}"',
                          frontmatter((self.dest / folder / "SKILL.md").read_text()))
        shutil.rmtree(old)
        report = self.skills("install")
        self.assertEqual(report["removed"], [{"path": str(self.dest / "murmur-retired"),
                                              "why": "its source skill is gone"}])
        self.assertFalse((self.dest / "murmur-retired").exists())
        self.assertEqual(self.names(report["unchanged"]), FOLDERS)

    def test_links_an_older_install_left_in_codex_skills_go(self):
        codex = self.home / ".codex" / "skills"
        codex.mkdir(parents=True)
        (codex / "fleet").symlink_to(self.clone / "fleet" / "skills" / "fleet")  # fleet/install.sh
        (codex / "murmur-init").symlink_to(self.clone / "plugin" / "skills" / "init")
        (codex / "theirs").symlink_to(self.tmp / "elsewhere")
        (codex / "real").mkdir()
        report = self.skills("install")
        self.assertEqual(self.names(report["removed"]), {"fleet", "murmur-init"})
        self.assertEqual(sorted(os.listdir(codex)), ["real", "theirs"])
        self.assertEqual(self.names(report["written"]), FOLDERS)

    def test_codex_skills_can_be_the_destination_for_an_older_codex(self):
        codex = self.home / ".codex" / "skills"
        codex.mkdir(parents=True)
        (codex / "fleet").symlink_to(self.clone / "fleet" / "skills" / "fleet")
        planned = self.skills("install", "--dest", "~/.codex/skills", "--dry-run")
        self.assertEqual(planned["dest"], str(codex))
        self.assertEqual((self.names(planned["written"]), planned["conflicts"]), (FOLDERS, []))
        self.assertTrue((codex / "fleet").is_symlink())               # a dry run changes nothing
        self.skills("install", "--dest", "~/.codex/skills")
        self.assertFalse((codex / "fleet").is_symlink())
        self.assertEqual(frontmatter((codex / "fleet" / "SKILL.md").read_text())[0],
                         "name: fleet")
        self.assertFalse(self.dest.exists())

    def test_the_folder_comes_from_dest_then_the_environment_then_the_default(self):
        self.assertEqual(self.skills("status")["dest"], str(self.home / ".agents" / "skills"))
        elsewhere = self.tmp / "skills"
        report = self.skills("install", MURMUR_SKILLS_DIR=str(elsewhere))
        self.assertEqual(report["dest"], str(elsewhere))
        self.assertEqual(set(os.listdir(elsewhere)), FOLDERS)
        report = self.skills("status", "--dest", str(self.dest),
                             MURMUR_SKILLS_DIR=str(elsewhere))
        self.assertEqual(report["dest"], str(self.dest))
        self.assertFalse(self.dest.exists())

    def test_status_and_dry_runs_change_nothing(self):
        planned = self.skills("install", "--dry-run")
        self.assertTrue(planned["dry_run"])
        self.assertEqual(self.names(planned["written"]), FOLDERS)
        self.assertFalse(self.dest.exists())
        states = lambda: {row["name"]: row["state"]  # noqa: E731
                          for row in self.skills("status")["skills"]}
        self.assertEqual(set(states().values()), {"missing"})
        self.skills("install")
        self.assertEqual(set(states().values()), {"current"})
        with open(self.dest / "murmur-farm" / "SKILL.md", "a", encoding="utf-8") as handle:
            handle.write("edited\n")
        shutil.rmtree(self.dest / "murmur-doctor")
        (self.dest / "murmur-doctor").mkdir()
        (self.dest / "murmur-doctor" / "SKILL.md").write_text("---\nname: mine\n---\n")
        shutil.rmtree(self.dest / "fleet")
        found = states()
        self.assertEqual((found["murmur-farm"], found["murmur-doctor"], found["fleet"],
                          found["murmur-init"]), ("outdated", "conflict", "missing", "current"))
        self.assertFalse((self.dest / "fleet").exists())
        planned = self.skills("uninstall", "--dry-run")
        self.assertEqual(self.names(planned["removed"]), FOLDERS - {"murmur-doctor", "fleet"})
        self.assertTrue((self.dest / "murmur-farm").is_dir())
        self.skills("uninstall")
        self.assertEqual(os.listdir(self.dest), ["murmur-doctor"])

    def test_a_copy_in_claude_codes_plugin_folders_is_refused(self):
        plugins = self.home / ".claude" / "plugins"
        cache = plugins / "cache" / "murmur" / "murmur" / "0.1.0"
        (cache / "scripts").mkdir(parents=True)
        shutil.copy2(REPO / SCRIPT, cache / "scripts")
        shutil.copytree(REPO / "plugin" / "skills", cache / "skills")
        marketplace = self.make_clone(plugins / "marketplaces" / "murmur")
        for script in (cache / "scripts" / SCRIPT.name, marketplace / SCRIPT):
            with self.subTest(script=script):
                done = subprocess.run([sys.executable, str(script), "install"],
                                      capture_output=True, text=True, timeout=60,
                                      env={"PATH": "/usr/bin:/bin", "HOME": str(self.home)})
                self.assertEqual(done.returncode, 1)
                self.assertIn("Claude Code's plugin folders", done.stderr)
                self.assertIn("git clone https://github.com/magik-ai/murmur ~/work/murmur",
                              done.stderr)
                self.assertFalse(self.dest.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
