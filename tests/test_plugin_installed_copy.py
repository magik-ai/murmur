"""The plugin as a person gets it: copied into Claude Code's cache, and nothing else.

Claude Code copies an installed plugin's own directory into its cache and follows symlinks
while it copies; anything the plugin reaches outside that directory is simply not there. These
tests run the plugin's scripts from such a copy, so a script that reads a file outside the
plugin directory fails here, and not only for the people who installed it from the marketplace.
"""
import ast
import json
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

    def test_the_copy_holds_everything_the_scripts_read(self):
        self.assertTrue((self.plugin / "templates" / "CLAUDE.md").is_file())
        self.assertTrue((self.plugin / "hooks" / "generated-files.example.txt").is_file())

    def test_the_copy_carries_the_machines_library_as_files(self):
        for name in ("machines.py", "host_presets.py", "scrub.py"):
            path = self.plugin / "lib" / name
            self.assertTrue(path.is_file(), name)
            self.assertFalse(path.is_symlink(), name)

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
