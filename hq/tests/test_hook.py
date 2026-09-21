"""`hq hook` installs the guard, and says one line when it cannot.

This command runs while a machine is being set up, usually from a script that
loops over worktrees, so its failures have to be readable by whoever reads that
script's output later. Every ordinary way of getting it wrong used to end in a
stack trace instead.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hq.hook import HOOK, cmd_hook


def hook_cmd(path, force=False):
    return cmd_hook(argparse.Namespace(dir=str(path), force=force))


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "checkout"
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    return path


def test_the_guard_is_installed_and_executable(repo, capsys):
    hook_cmd(repo)

    installed = repo / ".git" / "hooks" / "pre-push"
    assert installed.read_text() == HOOK
    assert os.access(installed, os.X_OK)
    assert "pre-push guard installed" in capsys.readouterr().out


def test_a_directory_that_is_not_a_repository_is_one_line(tmp_path):
    with pytest.raises(SystemExit) as stop:
        hook_cmd(tmp_path)

    assert "not inside a git repository" in str(stop.value)
    assert "Traceback" not in str(stop.value)


def test_a_directory_that_does_not_exist_is_one_line(tmp_path):
    with pytest.raises(SystemExit) as stop:
        hook_cmd(tmp_path / "nowhere")

    assert "is not a directory" in str(stop.value)


def test_a_machine_without_git_is_one_line(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(SystemExit) as stop:
        hook_cmd(repo)

    assert "`git` is not installed" in str(stop.value)


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes anywhere")
def test_a_hooks_directory_hq_may_not_write_is_one_line(repo):
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hooks.chmod(0o500)
    try:
        with pytest.raises(SystemExit) as stop:
            hook_cmd(repo)
    finally:
        hooks.chmod(0o700)

    assert "cannot write the pre-push guard" in str(stop.value)
    assert "\n" not in str(stop.value)


def test_every_failure_message_is_a_single_line(tmp_path):
    """The point of all of the above: a setup script's log stays readable."""
    with pytest.raises(SystemExit) as stop:
        hook_cmd(tmp_path)

    assert "\n" not in str(stop.value)
    assert sys.exc_info()[0] is None


def test_a_hook_hq_did_not_write_is_never_replaced_silently(repo):
    """A repo's own pre-push hook is somebody's guard, and losing one is the
    kind of failure that surfaces months later as a check that quietly stopped
    running."""
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    theirs = hooks / "pre-push"
    theirs.write_text("#!/bin/sh\n# the team's secret scanner\nexit 0\n")

    with pytest.raises(SystemExit) as stop:
        hook_cmd(repo)

    assert theirs.read_text().endswith("exit 0\n")      # untouched
    assert "hq did not write it" in str(stop.value)
    assert "--force" in str(stop.value)


def test_force_replaces_a_foreign_hook(repo):
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-push").write_text("#!/bin/sh\nexit 0\n")

    hook_cmd(repo, force=True)

    assert (hooks / "pre-push").read_text() == HOOK


def test_an_older_hq_guard_is_upgraded_in_place(repo, capsys):
    """Every version of the guard carries the marker, so re-running `hq hook`
    is still how a worktree picks up a fixed one - no --force, no prompt."""
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-push").write_text(
        "#!/usr/bin/env bash\n# agent-hq pre-push guard: an older version\n"
        "hq check-push \"$repo_url\" \"$branch\"\n")

    hook_cmd(repo)

    assert (hooks / "pre-push").read_text() == HOOK
    assert "pre-push guard installed" in capsys.readouterr().out


SRC = str(Path(__file__).resolve().parent.parent / "src")


def test_a_directory_that_is_not_a_repository_exits_1_through_the_cli(tmp_path):
    """The same failure, driven the way a stranger meets it.

    `hq hook .` is the one setup command the README hands somebody who has just
    installed hq, and getting the directory wrong is the ordinary way to get it
    wrong. Through the CLI it has to be one line on stderr and exit 1, with no
    stack trace: the tests above assert the message, but the exit status and the
    absence of a traceback are properties of the process, not of `cmd_hook`.
    """
    target = tmp_path / "not-a-repo"
    target.mkdir()
    env = dict(os.environ, PYTHONPATH=SRC)

    result = subprocess.run(
        [sys.executable, "-m", "hq.cli", "hook", str(target)],
        capture_output=True, text=True, errors="replace", timeout=60, env=env)

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "CalledProcessError" not in result.stderr
    assert result.stderr.strip().count("\n") == 0
    assert "not inside a git repository" in result.stderr
