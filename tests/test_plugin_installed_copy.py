"""The plugin as a person gets it: copied into Claude Code's cache, and nothing else.

Claude Code copies an installed plugin's own directory into its cache and follows symlinks
while it copies; anything the plugin reaches outside that directory is simply not there. These
tests run the plugin's scripts from such a copy, so a script that reads a file outside the
plugin directory fails here, and not only for the people who installed it from the marketplace.
"""
import ast
import importlib.util
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
VERSION = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]


def installed_copy(root: Path) -> Path:
    """The cache layout: <cache>/<marketplace>/<plugin>/<version>, symlinks followed."""
    target = root / "cache" / "murmur" / "murmur" / VERSION
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
        # The CLAUDE.md came first, with no AGENTS.md to import.
        self.assertFalse((self.project / "CLAUDE.md").read_text().startswith("@AGENTS.md"))

    def test_an_agents_md_the_person_wrote_keeps_its_text_and_gets_the_pointer_once(self):
        (self.project / "AGENTS.md").write_text("# Our product\n\nWhat it is.\n")
        first = self.apply_report("--agents-md")
        self.assertEqual(first["AGENTS.md"]["action"], "appended")
        self.assertEqual(self.apply_report("--agents-md")["AGENTS.md"]["action"], "skipped")
        text = (self.project / "AGENTS.md").read_text()
        self.assertTrue(
            text.startswith("# Our product\n\nWhat it is.\n\n<!-- murmur:contract -->\n"), text)
        self.assertEqual(text.count("<!-- murmur:contract -->"), 1)
        # Claude Code reads AGENTS.md only while there is no CLAUDE.md: the new one imports it.
        law = (self.project / "CLAUDE.md").read_text()
        self.assertTrue(law.startswith("@AGENTS.md\n\n<!--"), law[:80])
        self.assertIn("importing AGENTS.md", first["CLAUDE.md"]["note"])
        self.assertEqual(first["CLAUDE.md"]["action"], "wrote")

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
        # What init fills in is no blank any more, the role words never were (the session hook
        # says what they mean), and the template's comment only names the blanks.
        for gone in ("<ORG>", "<REPO>", "<PRODUCT>", "<OWNER>", "<TRACKER>", "<FARM>",
                     "<PLACEHOLDER>"):
            self.assertNotIn(gone, blanks)
        self.assertIn("<OWNER>", law)
        # Every other upper-case word in angle brackets outside a comment is on the list.
        bare = re.sub(r"<!--.*?-->", "", law, flags=re.DOTALL)
        found = set(re.findall(r"<[A-Z][A-Z0-9_ ]+>", bare)) - {"<OWNER>", "<TRACKER>", "<FARM>"}
        self.assertEqual(found, set(blanks))

    def test_the_contract_carries_the_generated_files_rule(self):
        # Codex has no hook to stop an edit, so the rule reaches it through the contract. The
        # list is written by the same run, so the first contract names it already.
        rule = ("Never edit a file that `.claude/generated-files.txt` lists by hand: regenerate "
                "it with the command written beside its entry.")
        report = self.apply_report()
        self.assertEqual(list(report)[:2], [".murmur/config.toml", ".murmur/contract.md"])
        self.assertEqual(report[".murmur/contract.md"]["action"], "wrote")
        self.assertIn(rule, (self.project / ".murmur" / "contract.md").read_text())
        again = self.apply_report()[".murmur/contract.md"]
        self.assertEqual((again["action"], again["note"]), ("skipped", "identical"))
        # Without a list there is nothing to guard, and no rule.
        spec = importlib.util.spec_from_file_location(
            "murmur_init", self.plugin / "scripts" / "murmur_init.py")
        init = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(init)
        config = init.load_config(self.project)
        template = (self.plugin / "templates" / "CLAUDE.md").read_text()
        self.assertNotIn("generated-files.txt", init.build_contract(config, template))
        self.assertIn(rule, init.build_contract(config, template, guarded=True))

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

    def test_skills_are_never_written_from_the_installed_copy(self):
        # The copies would point into a folder that goes with the next update of the plugin.
        result = self.run_script("murmur_skills.py", "install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("not in a clone of murmur", result.stderr)
        self.assertFalse((self.tmp / ".agents").exists())

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

    def git(self, *args, cwd=None):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp)}
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                       cwd=cwd or self.project, env=env, check=True, capture_output=True)

    def origin(self):
        """A bare repository as origin, and a first commit on main pushed to it."""
        origin = self.tmp / "origin.git"
        self.git("init", "-q", "--bare", str(origin), cwd=self.tmp)
        self.git("remote", "add", "origin", str(origin))
        self.git("commit", "-q", "--allow-empty", "-m", "First")
        self.git("branch", "-M", "main")
        self.git("push", "-q", "-u", "origin", "main")
        return origin

    def pushed_setup(self):
        """init with the defaults, committed on main and pushed to origin; init's report."""
        self.origin()
        report = self.apply_report()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "Set up murmur")
        self.git("push", "-q")
        return report

    def whole_setup(self):
        """pushed_setup with every blank in CLAUDE.md filled in, and that pushed too."""
        blanks = self.pushed_setup()["CLAUDE.md"]["placeholders"]
        law = self.project / "CLAUDE.md"
        text = law.read_text()
        for blank in blanks:
            text = text.replace(blank, "Ada")
        law.write_text(text + "\nA handler returns `Result<T>`.\n")
        self.git("commit", "-q", "-am", "Fill in the blanks")
        self.git("push", "-q")

    def doctor(self, *programs):
        """The doctor's rows as {check: (state, detail)}, its status and its exit code. The PATH
        holds git and, for each program named, a stand-in that exits 0 (`gh auth status` too),
        so a claude or codex installed on this machine never answers for the one missing."""
        path = Path(tempfile.mkdtemp(prefix="bin-", dir=self.tmp))
        (path / "git").symlink_to(shutil.which("git", path="/usr/bin:/bin") or shutil.which("git"))
        for name in programs:
            (path / name).write_text("#!/bin/sh\nexit 0\n")
            (path / name).chmod(0o755)
        result = subprocess.run([sys.executable, str(self.plugin / "scripts" / "murmur_doctor.py")],
                                cwd=self.project, env={"PATH": str(path), "HOME": str(self.tmp)},
                                capture_output=True, text=True, timeout=60)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        rows = {}
        for line in result.stdout.splitlines()[2:]:
            found = re.match(r"(\S.*?)  +(ok|warning|missing|optional|fixed)  +(.*)$", line)
            if found:
                rows[found.group(1)] = (found.group(2), found.group(3))
        return rows, result.stdout.rpartition("status: ")[2].strip(), result.returncode

    def test_doctor_takes_claude_or_codex_as_the_engine_and_says_which(self):
        self.pushed_setup()
        for engines in (("claude",), ("codex",), ("claude", "codex")):
            with self.subTest(engines=engines):
                rows, _status, code = self.doctor("uv", "gh", *engines)
                state, detail = rows["engines"]
                self.assertEqual(state, "ok")
                for name in ("claude", "codex"):
                    said = f"{name} at " if name in engines else f"{name} is not on the path"
                    self.assertIn(said, detail)
                self.assertEqual(code, 0)
        rows, status, code = self.doctor("uv", "gh")
        self.assertEqual(rows["engines"], (
            "missing", "neither claude nor codex is on the path, the agents run in one of them"))
        self.assertNotIn("claude", rows)
        self.assertEqual((status, code), ("setup-required", 1))

    def test_doctor_follows_the_setup_from_apply_to_the_base_branch_at_origin(self):
        origin = self.origin()
        blanks = self.apply_report()["CLAUDE.md"]["placeholders"]
        rows, status, code = self.doctor("uv", "gh", "claude")
        self.assertEqual((status, code), ("warnings", 0))
        for check in ("init files", "generated files", "CLAUDE.md", "murmur-new files"):
            self.assertEqual(rows[check][0], "ok", check)
        self.assertEqual(rows["AGENTS.md"][0], "optional")
        # The doctor counts the same blanks init listed.
        self.assertEqual(rows["placeholders"], (
            "warning", f"{len(blanks)} still to fill in CLAUDE.md: {', '.join(blanks[:4])} and "
                       f"{len(blanks) - 4} more; replace each one, or delete its line"))
        state, detail = rows["setup pushed"]
        self.assertEqual(state, "warning")
        self.assertIn("not committed: .claude/generated-files.txt, .claude/tracker.md", detail)
        self.assertIn(".murmur/contract.md, CLAUDE.md, docs/GOTCHAS.md;", detail)
        self.assertTrue(detail.endswith(
            "; lanes start from origin/main, so commit the setup, push it and merge its"
            " pull request"), detail)

        # Pushed on a branch of its own, and not merged yet: main at origin has no contract.
        self.git("switch", "-q", "-c", "murmur-setup")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "Set up murmur")
        self.git("push", "-q", "-u", "origin", "murmur-setup")
        rows, _status, _code = self.doctor("uv", "gh", "claude")
        not_yet = ("warning", "origin/main has no .murmur/contract.md as of the last fetch; lanes "
                              "start from origin/main, so merge the pull request that carries it "
                              "(or push it), then git fetch")
        self.assertEqual(rows["setup pushed"], not_yet)

        # Merged from another clone: the doctor never fetches, so it sees the merge only after
        # this clone has fetched it.
        other = self.tmp / "other"
        self.git("clone", "-q", "-b", "main", str(origin), str(other), cwd=self.tmp)
        self.git("merge", "-q", "--no-ff", "-m", "Merge the setup", "origin/murmur-setup",
                 cwd=other)
        self.git("push", "-q", "origin", "main", cwd=other)
        self.assertEqual(self.doctor("uv", "gh", "claude")[0]["setup pushed"], not_yet)
        self.git("fetch", "-q")
        rows, _status, _code = self.doctor("uv", "gh", "claude")
        self.assertEqual(rows["setup pushed"],
                         ("ok", "committed, and origin/main has .murmur/contract.md"))

    def test_doctor_warns_of_what_init_left_undone_and_never_calls_it_setup_required(self):
        self.whole_setup()
        rows, status, code = self.doctor("uv", "gh", "claude")
        # A single letter in angle brackets is no blank, and neither is the template's comment
        # or a role word.
        self.assertEqual(rows["placeholders"], ("ok", "none left in CLAUDE.md"))
        self.assertEqual((status, code), ("current", 0), rows)
        # Without the list of generated files the guard is off, which is the person's to choose.
        (self.project / ".claude" / "generated-files.txt").unlink()
        rows, status, code = self.doctor("uv", "gh", "claude")
        self.assertEqual(rows["generated files"], (
            "optional", ".claude/generated-files.txt is not there, so the guard is off"))
        self.assertEqual((status, code), ("current", 0), rows)
        # Codex reads AGENTS.md, and this repository has none.
        rows, status, code = self.doctor("uv", "gh", "codex")
        self.assertEqual(rows["AGENTS.md"], (
            "warning", "not there, and codex is on the path: Codex reads AGENTS.md, never "
                       "CLAUDE.md; run murmur_init.py apply --agents-md"))
        self.assertEqual((status, code), ("warnings", 0))

        github = self.project / ".github"
        (github / "PULL_REQUEST_TEMPLATE.md").rename(github / "pull_request_template.md")
        (self.project / "docs" / "GOTCHAS.md").unlink()
        law = self.project / "CLAUDE.md"
        law.write_text(law.read_text().split("<!-- murmur:contract -->")[0])
        (self.project / "AGENTS.md").write_text("# Ours\n")
        (self.project / ".gitignore").write_text(".claude/\n")
        (self.project / ".claude" / "tracker.md.murmur-new").write_text("newer rules\n")
        (self.project / "docs" / "notes.md.murmur-new").write_text("newer notes\n")
        rows, status, code = self.doctor("uv", "gh", "codex")
        self.assertEqual((status, code), ("warnings", 0))
        again = "run murmur_init.py apply again, or /murmur:init"
        # The pull request template counts wherever GitHub finds one.
        self.assertEqual(rows["init files"], ("warning", f"missing: docs/GOTCHAS.md; {again}"))
        self.assertEqual(rows["CLAUDE.md"],
                         ("warning", f"no pointer to .murmur/contract.md; {again}"))
        self.assertEqual(rows["AGENTS.md"], (
            "warning", f"no pointer to .murmur/contract.md, so Codex never reads it; {again}"))
        # One of them git ignores, and it is found by its name.
        self.assertEqual(rows["murmur-new files"], (
            "warning", "2 waiting: .claude/tracker.md.murmur-new, docs/notes.md.murmur-new; "
                       "compare each with the file beside it and keep one"))
        self.assertTrue(rows["setup pushed"][1].startswith("not committed: AGENTS.md, CLAUDE.md;"),
                        rows["setup pushed"])

        # init again puts back what it writes, and the pointers; the rest is the person's.
        self.apply_report()
        rows, _status, _code = self.doctor("uv", "gh", "codex")
        for check in ("init files", "generated files", "CLAUDE.md", "AGENTS.md"):
            self.assertEqual(rows[check][0], "ok", check)
        self.assertEqual(rows["murmur-new files"][0], "warning")


if __name__ == "__main__":
    unittest.main()
