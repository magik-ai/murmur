"""hq must never sign one agent's work with another agent's name.

This is bin/hq-selftest, the script that grew out of the incident, rewritten as
pytest. Two sessions share a machine: alice registers, bob then registers, and a
third session never registers at all. Before the session-scoped identity files,
alice's mail went out headed `from bob`, because the last `hq hello` won and
there was one identity file per machine.
"""

import pytest

from hq import identity as ident


def test_a_neighbour_hello_does_not_rename_a_registered_session(as_session, register):
    as_session("alice-session")
    register("alice", "alice-session")
    as_session("bob-session")
    register("bob", "bob-session")

    as_session("alice-session")
    assert ident.identity() == "alice"


def test_an_unregistered_session_inherits_no_name(as_session, register):
    as_session("alice-session")
    register("alice", "alice-session")

    # A session that never said hello cannot prove which session it is, so the
    # machine-wide file another session wrote is not evidence about IT.
    as_session("stranger-session")
    assert ident.identity() is None


def test_a_clone_wide_config_does_not_outrank_a_session(as_session, register, git_checkout):
    """Second shape of the same bug.

    `git config hq.agent` reads per-worktree but is written to .git/config,
    which every linked worktree of the clone shares. One lane setting it renamed
    every agent working anywhere in that clone.
    """
    as_session("alice-session")
    register("alice", "alice-session")
    git_checkout("neighbour")

    assert ident.identity() == "alice"


def test_a_worktree_name_is_trusted_only_with_the_extension_on(as_session, git_checkout):
    """git documents `--worktree` as a synonym for `--local` while
    extensions.worktreeConfig is off, so without the extension a `--worktree`
    read hands back the very clone-wide value it exists to distinguish from."""
    import subprocess

    as_session("alice-session")
    path = git_checkout("neighbour")
    assert ident.worktree_agent() == ""

    subprocess.run(["git", "-C", str(path), "config",
                    "extensions.worktreeConfig", "true"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "--worktree",
                    "hq.agent", "lane-name"], check=True)
    assert ident.worktree_agent() == "lane-name"
    assert ident.identity_source() == ("lane-name", "worktree config")


def test_shared_state_can_be_read_but_never_acted_on(as_session, register, git_checkout):
    """Third shape, found on 2026-09-16.

    A session that said `hq bye` has no file of its own any more, so the next
    command falls through to shared state. Reading under a stale name is
    harmless; ACTING under it is not, and a second `hq bye` signed a different
    live agent off the board.
    """
    as_session("alice-session")
    register("alice", "alice-session")
    git_checkout("neighbour")
    from hq.config import load_config
    (load_config().session_dir / "alice-session").unlink()

    # Resolution still answers, and says where the answer came from.
    assert ident.identity_source() == ("neighbour", "clone config")
    # Reads may use it.
    assert ident.require_identity(strict=False) == "neighbour"
    # Writes may not.
    with pytest.raises(SystemExit) as refusal:
        ident.require_identity()
    assert "clone config" in str(refusal.value)
    assert "hello" in str(refusal.value)


def test_the_machine_file_refusal_names_the_session_that_owns_it(as_session, register):
    as_session("alice-session")
    register("alice", "alice-session")

    as_session("stranger-session")
    with pytest.raises(SystemExit) as refusal:
        ident.require_identity()
    assert "alice-session" in str(refusal.value)
    assert "alice" in str(refusal.value)


def test_hq_agent_overrides_everything(as_session, register, monkeypatch):
    as_session("alice-session")
    register("alice", "alice-session")
    monkeypatch.setenv("HQ_AGENT", "explicit")

    assert ident.identity_source() == ("explicit", "HQ_AGENT")
    assert ident.require_identity() == "explicit"


def test_the_session_key_reports_which_variable_answered(monkeypatch):
    """The order is a contract: HQ_SESSION_ID is hq's own variable, the rest
    belong to somebody else and may vanish without notice."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "from-the-runtime")
    assert ident.session_key_source() == ("from-the-runtime", "CLAUDE_CODE_SESSION_ID")

    monkeypatch.setenv("HQ_SESSION_ID", "from-the-spawner")
    assert ident.session_key_source() == ("from-the-spawner", "HQ_SESSION_ID")


def test_no_session_variable_means_no_key():
    assert ident.session_key_source() == (None, None)


def test_a_sovereign_is_only_whoever_the_config_names(monkeypatch):
    assert ident.is_sovereign("alice") is False  # nobody configured: nobody sovereign
    monkeypatch.setenv("HQ_OWNER", "alice")
    assert ident.is_sovereign("alice") is True
    assert ident.is_sovereign("bob") is False


def test_bye_clears_this_session_before_it_needs_the_office(monkeypatch, capsys,
                                                            as_session, register):
    """`hq bye` used to require the head office repo first. On a machine that
    was never configured - or whose `gh` was down - it exited before the local
    cleanup, so the name stayed on disk after its session had left, ready for
    the next session to inherit. The local half needs nothing but this machine,
    so it happens first."""
    import argparse

    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.delenv("HQ_REPO", raising=False)
    as_session("session-one")
    register("alice", "session-one")
    cfg = load_config()
    mine = cfg.session_dir / "session-one"
    assert mine.exists()

    with pytest.raises(SystemExit) as stop:
        cmd_bye(argparse.Namespace())

    assert not mine.exists()                     # the identity is gone
    assert "hq init" in str(stop.value)          # and the office is still named
    assert "identity cleared" in capsys.readouterr().err


def test_bye_leaves_no_file_that_still_answers_with_this_name(monkeypatch, as_session,
                                                              register):
    """The other half of the same cleanup.

    `hq hello` writes TWO local files: the session file and the machine-wide
    one. A bye that removed only the session file left a file that still
    answered `hq whoami` with a name whose session had ended. Nothing was signed
    with it, because `require_identity` refuses a machine file, but the goodbye
    said `identity cleared on this machine` while the name was still on disk.
    """
    import argparse

    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.delenv("HQ_REPO", raising=False)
    as_session("session-one")
    register("alice", "session-one")
    cfg = load_config()

    with pytest.raises(SystemExit):
        cmd_bye(argparse.Namespace())

    assert not (cfg.session_dir / "session-one").exists()
    assert not cfg.identity_file.exists()
    assert not cfg.identity_owner_file.exists()
    assert ident.identity() is None            # nothing left answers with it


def test_bye_does_not_clear_a_machine_file_that_belongs_to_another_session(
        monkeypatch, as_session, register):
    """The machine-wide file is shared state, so a bye may only take its own.

    alice said hello last, so the machine file is hers. bob, running with
    HQ_AGENT in a session that never registered, says bye: his goodbye must not
    delete the file that names alice, or bob's exit takes a live agent's
    identity with it - the very mis-attribution hq exists to prevent.
    """
    import argparse

    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.delenv("HQ_REPO", raising=False)
    as_session("alice-session")
    register("alice", "alice-session")

    as_session("bob-session")
    monkeypatch.setenv("HQ_AGENT", "bob")
    cfg = load_config()

    with pytest.raises(SystemExit):
        cmd_bye(argparse.Namespace())

    assert cfg.identity_file.read_text().strip() == "alice"
    assert cfg.identity_owner_file.read_text().strip() == "alice-session"


def test_bye_reports_a_cleanup_only_when_there_was_one(monkeypatch, capsys, as_session):
    """A session that never registered has nothing of its own on this machine.
    Saying `identity cleared` there is a false report of work done."""
    import argparse

    from hq.registry import cmd_bye

    monkeypatch.delenv("HQ_REPO", raising=False)
    as_session("session-one")
    monkeypatch.setenv("HQ_AGENT", "bob")

    with pytest.raises(SystemExit):
        cmd_bye(argparse.Namespace())

    err = capsys.readouterr().err
    assert "identity cleared" not in err
    assert "nothing of this session" in err


def test_bye_clears_the_identity_on_a_machine_with_no_session_id(monkeypatch, capsys,
                                                                 as_session, register):
    """The keyless machine could say hello and never say goodbye.

    `hq hello` supports a session that exports no session id: it writes the
    machine-wide file and warns that every command needs HQ_AGENT. `hq bye` in
    that same session resolved that same file, and then refused to ACT under it
    - a refusal that came BEFORE the local cleanup, so the name stayed on disk,
    and no later run of `hq bye` could remove it either, because each one hit
    the same refusal. The half that needs nothing but this machine now happens
    first, whatever source the name came from.
    """
    import argparse

    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.delenv("HQ_REPO", raising=False)
    as_session(None)
    register("alice", None)
    cfg = load_config()
    assert cfg.identity_file.exists()

    with pytest.raises(SystemExit) as stop:
        cmd_bye(argparse.Namespace())

    assert not cfg.identity_file.exists()
    assert not cfg.identity_owner_file.exists()
    assert ident.identity() is None
    assert "hq init" in str(stop.value)
    assert "identity cleared" in capsys.readouterr().err


def test_bye_says_the_registry_issue_is_still_open_and_how_to_close_it(
        monkeypatch, as_session, register):
    """The office half of a keyless goodbye, which hq still may not sign.

    The local cleanup is this machine's business; closing the session issue
    writes to the office under a name, and a name from the shared machine file
    is not this session's to write with. hq says exactly that, and gives the one
    command that finishes the job, instead of exiting with `no identity` about
    the file it just removed itself.
    """
    import argparse

    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.setenv("HQ_REPO", "acme/office")
    as_session(None)
    register("alice", None)
    cfg = load_config()

    with pytest.raises(SystemExit) as stop:
        cmd_bye(argparse.Namespace())

    message = str(stop.value)
    assert "HQ_AGENT=alice hq bye" in message   # how to finish
    assert "machine file" in message            # why hq stopped
    assert not cfg.identity_file.exists()       # the local half still happened


def test_bye_does_not_take_a_keyless_agents_identity(monkeypatch, as_session, register):
    """A machine file nobody claimed is still not everybody's.

    alice said hello from a session that exports no session id, so the machine
    file records no owner. A later session that HAS a key reads that file (a
    stale hint is harmless) but must not delete it: the keyless session it
    belongs to is still live, and the file is the only identity it has.
    """
    import argparse

    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.delenv("HQ_REPO", raising=False)
    as_session(None)
    register("alice", None)

    as_session("session-two")
    cfg = load_config()

    with pytest.raises(SystemExit):
        cmd_bye(argparse.Namespace())

    assert cfg.identity_file.read_text().strip() == "alice"


# A config file hq cannot read is the third way `hq bye` used to keep a name on
# a machine, after the missing repo and the refusal to act under shared state.
# It was the worst of the three: every later `hq bye` stopped in the same place,
# so the identity stayed until somebody fixed the file by hand.


def broken_config(text=b'repo = "acme/office\n[[[\n'):
    from hq.config import config_path

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text)
    return path


def bye():
    import argparse

    from hq.registry import cmd_bye

    return cmd_bye(argparse.Namespace())


def test_bye_clears_the_identity_when_the_config_file_cannot_be_parsed(
        monkeypatch, capsys, as_session, register):
    """The local half depends on nothing inside that file: where the state dir
    is comes from HQ_HOME or the default, and removing a local file signs
    nothing. So it runs, and the config problem is the exit."""
    from hq.config import load_config

    as_session("session-one")
    register("alice", "session-one")
    cfg = load_config()                      # read the paths while the file is fine
    path = broken_config()

    with pytest.raises(SystemExit) as stop:
        bye()

    assert not (cfg.session_dir / "session-one").exists()
    assert not cfg.identity_file.exists()
    assert not cfg.identity_owner_file.exists()
    assert str(path) in str(stop.value)      # and it says what is still wrong
    assert "hq bye" in str(stop.value)       # and what to do after fixing it
    assert "identity cleared" in capsys.readouterr().err


def test_bye_clears_the_identity_when_the_config_file_cannot_be_read(
        monkeypatch, capsys, as_session, register):
    """Same rule for a permissions accident, and with the repo in the
    environment: the office half still cannot run, the local half still must."""
    import os

    from hq.config import load_config

    if os.geteuid() == 0:
        pytest.skip("root reads a chmod 000 file, so there is nothing to test")
    monkeypatch.setenv("HQ_REPO", "acme/office")
    as_session("session-one")
    register("alice", "session-one")
    cfg = load_config()
    path = broken_config(b'repo = "acme/office"\n')
    path.chmod(0o000)
    try:
        with pytest.raises(SystemExit) as stop:
            bye()
    finally:
        path.chmod(0o600)

    assert not (cfg.session_dir / "session-one").exists()
    assert not cfg.identity_file.exists()
    assert str(path) in str(stop.value)
    assert "identity cleared" in capsys.readouterr().err


@pytest.fixture
def without_git(tmp_path, monkeypatch):
    """A machine where `git` is not installed: PATH holds nothing at all."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    return empty


def test_a_machine_without_git_still_knows_who_this_session_is(as_session, register,
                                                               without_git):
    """git is one of five places a name can come from, and hq asks it first.

    A missing git raised FileNotFoundError out of the first question, so the
    four sources that need no git were never reached: `hq whoami` could not
    answer a question about a file on this disk.
    """
    as_session("alice-session")
    register("alice", "alice-session")

    assert ident.worktree_agent() == ""          # no answer, not a crash
    assert ident.repo_agent() == ""
    assert ident.identity_source() == ("alice", "session file")


def test_bye_clears_the_identity_on_a_machine_without_git(monkeypatch, capsys,
                                                          as_session, register,
                                                          without_git):
    """The same crash, where it cost the most.

    `hq bye` does its local cleanup before anything that can stop it, because a
    machine that cannot reach its office must still be able to drop its name.
    Resolving that name went through git, so on a machine without git the
    command died before removing anything - and so did every later `hq bye`,
    which is the for-ever stale identity of finding 7 in a second disguise.
    """
    import argparse

    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.delenv("HQ_REPO", raising=False)
    as_session("session-one")
    register("alice", "session-one")
    cfg = load_config()

    with pytest.raises(SystemExit) as stop:
        cmd_bye(argparse.Namespace())

    assert not cfg.identity_file.exists()
    assert not (cfg.session_dir / "session-one").exists()
    assert ident.identity() is None
    assert "hq init" in str(stop.value)
    assert "identity cleared" in capsys.readouterr().err


def test_a_bye_that_fails_at_the_office_says_how_to_finish(monkeypatch, capsys,
                                                           as_session, register):
    """The local cleanup happens first, on purpose, and that has a cost.

    Once the local files are gone this session has no name to resolve, so if the
    office half then fails - an expired token, a head office `gh` cannot see,
    GitHub down - the retry would exit with `no identity` about the very file
    the first run removed, and the registry issue would stay open with nobody
    able to close it. The failing run hands back the one command that finishes
    the job, while the name is still on screen.
    """
    import argparse

    from hq import registry
    from hq.config import load_config
    from hq.registry import cmd_bye

    monkeypatch.setenv("HQ_REPO", "acme/office")
    as_session("session-one")
    register("alice", "session-one")
    cfg = load_config()

    def gh_is_down(_title):
        raise SystemExit("hq: `gh issue list` failed (GitHub is down) - check "
                         "`gh auth status`")

    monkeypatch.setattr(registry, "find_issue", gh_is_down)

    with pytest.raises(SystemExit) as stop:
        cmd_bye(argparse.Namespace())

    assert "gh issue list" in str(stop.value)       # the cause is still the exit
    hint = capsys.readouterr().err
    assert "HQ_AGENT=alice hq bye" in hint          # and the way to finish is on screen
    assert not cfg.identity_file.exists()           # the local half did happen
    assert ident.identity() is None


def test_a_goodbye_that_works_closes_the_issue_and_says_so(monkeypatch, capsys,
                                                           as_session, register):
    """The ordinary path, so the guard above cannot quietly break it."""
    import argparse

    from hq import registry
    from hq.registry import cmd_bye

    monkeypatch.setenv("HQ_REPO", "acme/office")
    as_session("session-one")
    register("alice", "session-one")
    closed = []
    monkeypatch.setattr(registry, "find_issue", lambda title: 7)
    monkeypatch.setattr(registry, "gh", lambda args, **kw: closed.append(args))

    cmd_bye(argparse.Namespace())

    assert closed and closed[0][:2] == ["issue", "close"]
    assert "bye alice" in capsys.readouterr().out
