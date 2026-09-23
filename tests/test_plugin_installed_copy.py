"""The plugin as a person gets it: copied into Claude Code's cache, and nothing else.

Claude Code copies an installed plugin's own directory into its cache and follows symlinks
while it copies; anything the plugin reaches outside that directory is simply not there. The
init script once looked for the templates one level above the plugin, so /murmur:init stopped
with "Templates not found" for everyone who installed from the marketplace, while every run
from a clone of this repository kept working.
"""
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
    target = root / "cache" / "murmur" / "murmur" / "0.0.1"
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

    def test_the_copy_holds_everything_the_scripts_read(self):
        self.assertTrue((self.plugin / "templates" / "CLAUDE.md").is_file())
        self.assertTrue((self.plugin / "hooks" / "generated-files.example.txt").is_file())

    def test_doctor_runs_from_the_installed_copy(self):
        result = self.run_script("murmur_doctor.py")
        self.assertNotIn("Traceback", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
