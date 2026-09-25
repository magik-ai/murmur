"""What hq does with bytes it did not write: git output, under any locale.

hq reads names out of git - `git config hq.agent`, a remote URL, a claim file -
and it runs on machines whose locale it does not choose. Decoding that output
with the machine's locale and the strict error handler turned two ordinary
things into a crash of the push gate, and the pre-push hook reads any non-zero
exit from the gate as a blocked push.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hq.util import run

SRC = str(Path(__file__).resolve().parent.parent / "src")


def emits(data):
    """A command that writes exactly `data` to stdout, on any platform.

    Not `printf 'Jos\\xe9'`: \\xHH is a GNU printf feature, and BSD printf,
    which is the `printf` on macOS, prints the characters instead. The stray
    byte a test is named after would then never be produced, and a check like
    `startswith("Jos")` would still pass on the literal "Josxe9". CI runs on
    ubuntu only and could not catch that.

    python writes the bytes the same way everywhere, and it is the interpreter
    already running the test.
    """
    return [sys.executable, "-c",
            "import sys; sys.stdout.buffer.write(%r)" % (data,)]


def test_a_stray_byte_in_git_output_does_not_crash_hq():
    """A byte that is not valid UTF-8 costs one character, not the command."""
    result = run(emits(b"Jos\xe9"))
    assert result.returncode == 0
    # The whole string, not a prefix: the bad byte becomes U+FFFD, the rest of
    # the name survives, and nothing is truncated.
    assert result.stdout == "Jos\N{REPLACEMENT CHARACTER}"


def test_utf8_output_is_decoded_as_utf8():
    result = run(emits("José".encode("utf-8")))
    assert result.stdout == "José"


def ascii_locale_env(home):
    """An environment whose locale cannot represent an accented name.

    `LC_ALL=C` is not exotic: it is what cron, systemd units and bare CI
    containers hand a process. PEP 538 would otherwise coerce it to C.UTF-8 and
    hide the bug, so coercion is off, as it is on any machine whose locale is a
    real non-UTF-8 one rather than the C default.
    """
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "HQ_HOME": str(home / "state"),
        "PYTHONPATH": SRC,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONUTF8": "0",
    })
    for variable in ("HQ_AGENT", "HQ_REPO", "HQ_OWNER"):
        env.pop(variable, None)
    return env


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_the_push_gate_survives_an_accented_agent_name_under_an_ascii_locale(tmp_path):
    """End to end, through the real CLI.

    `git config hq.agent José`-style names are ordinary, and under LC_ALL=C
    reading one with the locale's decoder raises UnicodeDecodeError inside
    `check-push`. The gate would exit 1 with a traceback, and the hook turns
    that into a refused push - for every push on that machine, not just this
    one.
    """
    home = tmp_path / "home"
    (home / ".config" / "hq").mkdir(parents=True)
    (home / ".config" / "hq" / "config.toml").write_bytes(
        b'repo = "acme/office"\n')
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "config", "hq.agent",
                    "José"], check=True)

    result = subprocess.run(
        [sys.executable, "-m", "hq.cli", "check-push",
         "git@github.com:acme/thing.git", "some-branch"],
        cwd=checkout, env=ascii_locale_env(home),
        capture_output=True, text=True, errors="replace", timeout=60,
    )
    # Exit 0: nothing here is a claim by anybody else.
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    # And it is not merely surviving: the gate ran, rather than falling open on
    # a crash it could not read.
    assert "push gate failed unexpectedly" not in result.stderr
