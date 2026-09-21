"""`gh` fails for ordinary reasons, and none of them is worth a stack trace.

An expired token, a head office repo this login cannot see, GitHub down, `gh`
not installed at all: every one of those used to come out of hq as a
`CalledProcessError` traceback ending in the full argv. The sentence `gh` itself
printed about the cause was buried in it, and an agent reading the trace could
not tell whether hq was broken or its own auth was.
"""

import argparse
import subprocess
import types

import pytest

from hq import github


def answer(returncode=0, stdout="", stderr=""):
    """A finished subprocess, as `run` returns one."""
    def fake(cmd, *_args, **_kwargs):
        return types.SimpleNamespace(args=cmd, returncode=returncode,
                                     stdout=stdout, stderr=stderr)
    return fake


def one_line(stop):
    """A SystemExit message that is a single line of prose, not a trace."""
    message = str(stop.value)
    assert "\n" not in message
    assert "Traceback" not in message
    return message


def test_a_gh_that_is_not_installed_is_one_line(monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory: 'gh'")

    monkeypatch.setattr(github, "run", missing)
    with pytest.raises(SystemExit) as stop:
        github.gh(["issue", "list"])
    assert "gh" in one_line(stop)


def test_a_gh_that_refuses_says_what_gh_said(monkeypatch):
    """gh exits 4 when the token cannot see the repo. The cause is in gh's own
    stderr, so hq repeats it rather than printing its own guess."""
    monkeypatch.setattr(github, "run", answer(
        returncode=4, stderr="gh: Could not resolve to a Repository with the name "
                             "'acme/office'.\n"))
    with pytest.raises(SystemExit) as stop:
        github.gh(["issue", "list", "--repo", "acme/office"])
    message = one_line(stop)
    assert "Could not resolve" in message
    assert "gh auth status" in message          # and what to check next


def test_a_gh_that_never_answers_is_one_line(monkeypatch):
    def hang(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["gh"], timeout=30)

    monkeypatch.setattr(github, "run", hang)
    with pytest.raises(SystemExit) as stop:
        github.gh(["issue", "list"])
    assert "30s" in one_line(stop)


def test_unreadable_json_from_gh_is_one_line(monkeypatch):
    monkeypatch.setattr(github, "run", answer(stdout="not json at all"))
    with pytest.raises(SystemExit) as stop:
        github.gh_json(["issue", "list"])
    assert "gh issue list" in one_line(stop)


def test_an_issue_create_that_prints_no_url_is_one_line(monkeypatch):
    monkeypatch.setattr(github, "require_repo", lambda *_a, **_k: "acme/office")
    monkeypatch.setattr(github, "find_issue", lambda _title: None)
    monkeypatch.setattr(github, "run", answer(stdout="Creating issue in acme/office"))
    with pytest.raises(SystemExit) as stop:
        github.ensure_issue("session: alice", "session", "body")
    assert "acme/office" in one_line(stop)


def test_a_gh_that_works_still_works(monkeypatch):
    monkeypatch.setattr(github, "run", answer(
        stdout='[{"number": 7, "title": "session: alice"}]'))
    assert github.gh_json(["issue", "list"]) == [{"number": 7,
                                                  "title": "session: alice"}]


def test_bye_clears_the_identity_before_gh_can_fail(monkeypatch, capsys,
                                                    as_session, register):
    """The ordering finding 7 asked for, held against this failure too: the
    local cleanup is done by the time `gh` is called, so a login that cannot
    reach the office does not leave the name on the machine."""
    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.setenv("HQ_REPO", "acme/office")
    as_session("session-one")
    register("alice", "session-one")
    monkeypatch.setenv("HQ_AGENT", "alice")
    cfg = load_config()
    monkeypatch.setattr(github, "run", answer(returncode=4, stderr="gh: not found\n"))

    with pytest.raises(SystemExit) as stop:
        cmd_bye(argparse.Namespace())

    assert not (cfg.session_dir / "session-one").exists()
    assert not cfg.identity_file.exists()
    assert "gh" in one_line(stop)


def test_a_failed_bye_says_what_the_local_half_did(monkeypatch, capsys,
                                                   as_session, register):
    """The local cleanup happened; the exit line is about the office half only.

    Without the report line, `hq bye` against a `gh` that cannot answer reads as
    a command that did nothing at all, and the obvious response is to run it
    again - which then says `no identity`, about the file this very command
    removed. Both halves are on screen now: what was cleared, and the one
    command that still closes the registry issue.
    """
    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.setenv("HQ_REPO", "acme/office")
    as_session("session-one")
    register("alice", "session-one")
    cfg = load_config()
    monkeypatch.setattr(github, "run", answer(returncode=4, stderr="gh: not found\n"))

    with pytest.raises(SystemExit) as stop:
        cmd_bye(argparse.Namespace())

    assert "gh" in one_line(stop)                    # the cause is still the exit
    error = capsys.readouterr().err
    assert "bye alice: identity cleared on this machine" in error
    assert "HQ_AGENT=alice hq bye" in error
    assert not cfg.identity_file.exists()
