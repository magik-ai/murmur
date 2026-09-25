"""The plugin as a person gets it: copied into Claude Code's cache, and nothing else.

Claude Code copies an installed plugin's own directory into its cache and follows symlinks
while it copies; anything the plugin reaches outside that directory is simply not there. These
tests run the plugin's scripts from such a copy, so a script that reads a file outside the
plugin directory fails here, and not only for the people who installed it from the marketplace.
"""
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugin"


def installed_copy(root: Path) -> Path:
    """The cache layout: <cache>/<marketplace>/<plugin>/<version>, symlinks followed."""
    target = root / "cache" / "murmur" / "murmur" / "0.1.0"
    shutil.copytree(PLUGIN, target, symlinks=False)
    return target


class InstalledCopy(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="murmur-plugin-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.plugin = installed_copy(self.tmp)
        self.project = self.tmp / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)

    def run_script(self, name, *args):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp)}
        return subprocess.run([sys.executable, str(self.plugin / "scripts" / name), *args],
                              cwd=self.project, env=env, capture_output=True, text=True,
                              timeout=60)

    def test_init_applies_from_the_installed_copy(self):
        result = self.run_script("murmur_init.py", "apply", "--defaults")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Templates not found", result.stdout + result.stderr)
        self.assertTrue((self.project / "CLAUDE.md").is_file())

    def test_the_contract_carries_every_section_it_names(self):
        # murmur_init.py copies sections of templates/CLAUDE.md by their exact headings, so a
        # heading renamed in the template would drop its section from every contract silently.
        tree = ast.parse((self.plugin / "scripts" / "murmur_init.py").read_text())
        sections = next(ast.literal_eval(node.value) for node in tree.body
                        if isinstance(node, ast.Assign)
                        and [getattr(t, "id", "") for t in node.targets] == ["SECTIONS"])
        result = self.run_script("murmur_init.py", "apply", "--defaults")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        contract = (self.project / ".murmur" / "contract.md").read_text()
        for heading in sections:
            self.assertIn(heading + "\n", contract)

    def test_a_fresh_claude_md_leaves_the_contracts_sections_to_the_contract(self):
        # Every rule is written once: the four sections are in .murmur/contract.md, and a fresh
        # CLAUDE.md keeps only their headings, each with one line that points there.
        tree = ast.parse((self.plugin / "scripts" / "murmur_init.py").read_text())
        sections = next(ast.literal_eval(node.value) for node in tree.body
                        if isinstance(node, ast.Assign)
                        and [getattr(t, "id", "") for t in node.targets] == ["SECTIONS"])
        template = (self.plugin / "templates" / "CLAUDE.md").read_text()
        result = self.run_script("murmur_init.py", "apply", "--defaults")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        law = (self.project / "CLAUDE.md").read_text()
        contract = (self.project / ".murmur" / "contract.md").read_text()
        pointer = "This section is in [`.murmur/contract.md`](.murmur/contract.md)."
        for heading in sections:
            body = template.split(heading + "\n", 1)[1].split("\n## ", 1)[0].strip()
            first_rule = body.splitlines()[0]
            self.assertIn(heading + "\n\n" + pointer + "\n", law, heading)
            self.assertNotIn(first_rule, law, heading)
            self.assertIn(first_rule, contract, heading)
        self.assertIn("Agent work in this repository follows `.murmur/contract.md`.", law)
        self.assertIn("## 1. Repo and contract map", law)

    def apply_report(self, *args):
        """{path: entry} of the report `apply --defaults` prints."""
        result = self.run_script("murmur_init.py", "apply", "--defaults", *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return {entry["path"]: entry for entry in json.loads(result.stdout)["files"]}

    def test_agents_md_is_written_only_when_asked(self):
        # Codex reads AGENTS.md and never CLAUDE.md, so --agents-md gives a repository without one
        # an AGENTS.md that points to the contract. Without the flag there is still none.
        self.assertNotIn("AGENTS.md", self.apply_report())
        self.assertFalse((self.project / "AGENTS.md").exists())
        self.run_script("murmur_init.py", "answer", "--id", "base_branch", "--value", "develop")
        entry = self.apply_report("--agents-md")["AGENTS.md"]
        self.assertEqual(entry["action"], "wrote")
        text = (self.project / "AGENTS.md").read_text()
        self.assertTrue(text.startswith("# AGENTS.md\n\n<!-- murmur:contract -->\n"), text)
        self.assertIn("Agent work in this repository follows `.murmur/contract.md`.", text)
        self.assertIn("branch from `develop`", text)
        again = self.apply_report("--agents-md")["AGENTS.md"]
        self.assertEqual((again["action"], again["note"]), ("skipped", "pointer there"))
        self.assertEqual((self.project / "AGENTS.md").read_text(), text)

    def test_an_agents_md_the_person_wrote_keeps_its_text_and_gets_the_pointer_once(self):
        (self.project / "AGENTS.md").write_text("# Our product\n\nWhat it is.\n")
        self.assertEqual(self.apply_report("--agents-md")["AGENTS.md"]["action"], "appended")
        self.assertEqual(self.apply_report("--agents-md")["AGENTS.md"]["action"], "skipped")
        text = (self.project / "AGENTS.md").read_text()
        self.assertTrue(text.startswith("# Our product\n\nWhat it is.\n\n<!-- murmur:contract -->\n"),
                        text)
        self.assertEqual(text.count("<!-- murmur:contract -->"), 1)

    def test_a_fresh_claude_md_lists_the_placeholders_still_to_fill(self):
        entry = self.apply_report()["CLAUDE.md"]
        self.assertEqual(entry["action"], "wrote")
        self.assertEqual(entry["note"], "from the template, some placeholders still to fill")
        law = (self.project / "CLAUDE.md").read_text()
        blanks = entry["placeholders"]
        for blank in ("<NAME>", "<DOC>", "<PATH>", "<VERSION>", "<CTO>", "<KIND OF WORK>"):
            self.assertIn(blank, blanks)
        self.assertEqual(len(blanks), len(set(blanks)))
        for blank in blanks:
            self.assertIn(blank, law)
        # What init fills in is no blank any more, and the template's comment only names them.
        for gone in ("<ORG>", "<REPO>", "<PRODUCT>", "<TRACKER>", "<PLACEHOLDER>"):
            self.assertNotIn(gone, blanks)
        # Every upper-case blank the file still holds outside a comment is on the list.
        bare = re.sub(r"<!--.*?-->", "", law, flags=re.DOTALL)
        self.assertEqual(set(re.findall(r"<[A-Z][A-Z0-9_ ]+>", bare)), set(blanks))

    def test_a_claude_md_the_person_wrote_gets_no_placeholder_list(self):
        (self.project / "CLAUDE.md").write_text("# Ours\n\nBuild with `make <TARGET>`.\n")
        entry = self.apply_report()["CLAUDE.md"]
        self.assertEqual(entry["action"], "appended")
        self.assertNotIn("placeholders", entry)

    def run_hook(self, *python_path):
        env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(self.tmp),
               "CLAUDE_PROJECT_DIR": str(self.project),
               "PYTHONPATH": ":".join(str(path) for path in python_path)}
        done = subprocess.run(["bash", str(self.plugin / "hooks" / "session-context.sh")],
                              cwd=self.project, env=env, capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_the_session_hook_reads_the_answers(self):
        self.assertEqual(self.run_script("murmur_init.py", "apply", "--defaults").returncode, 0)
        context = self.run_hook()
        self.assertIn("# This repository (from `.murmur/config.toml`)", context)
        self.assertIn("Never without <OWNER>: merge, force-push", context)

    def test_the_session_hook_reads_the_answers_without_tomllib(self):
        # A Mac's own python3 is 3.9, which has no tomllib. The hook must not tell every
        # session there that the configuration could not be read.
        self.assertEqual(self.run_script("murmur_init.py", "apply", "--defaults").returncode, 0)
        old_python = self.tmp / "old-python"
        old_python.mkdir()
        (old_python / "tomllib.py").write_text('raise ImportError("No module named \'tomllib\'")\n')
        context = self.run_hook(old_python)
        self.assertNotIn("could not be read", context)
        self.assertIn("# This repository (from `.murmur/config.toml`)", context)
        self.assertIn("Branch claims: this machine only.", context)
        self.assertIn("Never without <OWNER>: merge, force-push", context)

    def test_the_copy_holds_everything_the_scripts_read(self):
        self.assertTrue((self.plugin / "templates" / "CLAUDE.md").is_file())
        self.assertTrue((self.plugin / "hooks" / "generated-files.example.txt").is_file())

    def test_the_copy_carries_the_machines_library_as_files(self):
        for name in ("machines.py", "host_presets.py", "scrub.py"):
            path = self.plugin / "lib" / name
            self.assertTrue(path.is_file(), name)
            self.assertFalse(path.is_symlink(), name)

    def test_every_script_uv_runs_says_it_needs_python_3_11_and_nothing_else(self):
        # The farm skill runs lib/machines.py with `uv run`, like the scripts: without this block
        # uv would not know the file needs Python 3.11 and no third-party package.
        block = ('# /// script\n# requires-python = ">=3.11"\n# dependencies = []\n# ///\n')
        for path in sorted((self.plugin / "scripts").glob("*.py")) + [
                self.plugin / "lib" / "machines.py"]:
            self.assertTrue(path.read_text().startswith("#!/usr/bin/env python3\n" + block),
                            path.name)

    def test_farm_plans_from_the_installed_copy(self):
        # The answers a person gave, and their public key; no doctl on PATH, so the plan says
        # it is the list price and would refuse to buy on it.
        ssh = self.tmp / ".ssh"
        ssh.mkdir(mode=0o700)
        (ssh / "id_ed25519.pub").write_text(
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPERSONPERSONPERSON person@laptop\n")
        murmur = self.tmp / ".config" / "murmur"
        murmur.mkdir(parents=True, mode=0o700)
        (murmur / "farm.json").write_text(json.dumps({"answers": {
            "name": "farm", "size": "s-4vcpu-8gb", "region": "fra1", "access": "tunnel",
            "codex": "no", "accounts": "", "hq_repo": "",
            "key": str(ssh / "id_ed25519")}}))
        result = self.run_script("murmur_farm.py", "plan")
        said = result.stdout + result.stderr
        self.assertNotIn("Traceback", said)
        self.assertEqual(result.returncode, 0, said)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["sentence"], "Create farm, $48 a month until you destroy it")
        self.assertIn("#cloud-config", plan["cloud_init"])
        self.assertIn("not a live price", plan["said"])

    def test_doctor_runs_from_the_installed_copy(self):
        result = self.run_script("murmur_doctor.py")
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def broken_config(self):
        """A config the person wrote with a typo in it: an unclosed string."""
        config = self.project / ".murmur" / "config.toml"
        config.parent.mkdir()
        text = 'repo = "acme/storefront"\ntracker = "linear\n# my notes: keep linear\n'
        config.write_text(text)
        return config, text

    def test_doctor_fix_never_rewrites_a_config_it_cannot_read(self):
        config, text = self.broken_config()
        result = self.run_script("murmur_doctor.py", "--fix")
        said = result.stdout + result.stderr
        self.assertNotIn("Traceback", said)
        self.assertEqual(config.read_text(), text)
        self.assertIn(".murmur/config.toml could not be read", said)
        self.assertNotIn(".murmur/config.toml is not there", said)
        self.assertIn("status: setup-required", said)

    def test_init_stops_at_a_config_it_cannot_read(self):
        config, text = self.broken_config()
        for args in (("questions",), ("answer", "--id", "tracker", "--value", "jira"),
                     ("apply", "--defaults")):
            result = self.run_script("murmur_init.py", *args)
            self.assertEqual(result.returncode, 1, args)
            self.assertNotIn("Traceback", result.stderr, args)
            self.assertIn("could not be read", result.stderr, args)
            self.assertEqual(config.read_text(), text, args)

    def test_doctor_finds_a_base_branch_with_a_slash_in_its_name(self):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp)}

        def git(*args, cwd=self.project):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                            *args], cwd=cwd, env=env, check=True, capture_output=True)

        origin = self.tmp / "origin.git"
        git("init", "-q", "--bare", str(origin), cwd=self.tmp)
        git("commit", "-q", "--allow-empty", "-m", "first")
        git("branch", "-M", "release/2.x")
        git("remote", "add", "origin", str(origin))
        git("push", "-q", "origin", "release/2.x")
        self.run_script("murmur_init.py", "answer", "--id", "base_branch", "--value",
                        "release/2.x")
        result = self.run_script("murmur_doctor.py")
        self.assertRegex(result.stdout, r"base branch +ok +release/2\.x exists on origin")


if __name__ == "__main__":
    unittest.main()
