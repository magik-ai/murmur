"""The push gate when the office is unreachable.

Fail-open is for NOT KNOWING. A claim already sitting in the local cache is
knowing: it is positive evidence that the branch belongs to somebody else, and
an outage does not make it less true. The guard used to wave those pushes
through, which is precisely the case it exists for.

Nothing here touches the network: `fetch_claims` returns False (unreachable)
and `claims_tree` is the cache.
"""

import argparse
from datetime import timedelta

import pytest

from hq import claims
from hq.util import iso, now

BRANCH = "feature/x"
# An ssh alias, so the test also proves the guard keys the claim by owner/name
# rather than by the raw remote URL.
REMOTE = "git@github-acme:acme/office.git"
PATH = "claims/acme-office/feature-x.json"


def claim(owner, hours=24):
    return {"repo": "acme/office", "branch": BRANCH, "owner": owner,
            "expires": iso(now() + timedelta(hours=hours))}


@pytest.fixture
def offline(monkeypatch):
    """The office is unreachable; the cache holds whatever the test puts there."""
    monkeypatch.setenv("HQ_REPO", "acme/office")
    cache = {}
    monkeypatch.setattr(claims, "fetch_claims", lambda strict, cfg=None: False)
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: cache)
    return cache


def check():
    claims.cmd_check_push(argparse.Namespace(repo=REMOTE, branch=BRANCH))


def test_a_cached_claim_by_someone_else_blocks_the_push(offline, monkeypatch, capsys):
    offline[PATH] = claim("bob")
    monkeypatch.setenv("HQ_AGENT", "alice")
    with pytest.raises(SystemExit) as stop:
        check()
    assert stop.value.code == 1
    error = capsys.readouterr().err
    assert "PUSH BLOCKED" in error
    assert "bob" in error
    # It must say the claim came from the cache: an agent needs to know the
    # office is down, not conclude that hq is broken.
    assert "cache" in error
    assert "outage is not permission" in error


def test_my_own_cached_claim_does_not_block_me(offline, monkeypatch, capsys):
    offline[PATH] = claim("alice")
    monkeypatch.setenv("HQ_AGENT", "alice")
    check()
    error = capsys.readouterr().err
    assert "BLOCKED" not in error
    # And the line says what was actually absent. The cache DOES hold a claim on
    # this branch here: what it does not hold is one by anybody else.
    assert "no live claim by another agent" in error


def test_an_expired_cached_claim_does_not_block(offline, monkeypatch, capsys):
    offline[PATH] = claim("bob", hours=-1)
    monkeypatch.setenv("HQ_AGENT", "alice")
    check()
    assert "BLOCKED" not in capsys.readouterr().err


def test_a_silent_cache_fails_open_with_a_warning(offline, monkeypatch, capsys):
    """Offline hands-on work is never blocked by an absence of information."""
    monkeypatch.setenv("HQ_AGENT", "alice")
    check()
    error = capsys.readouterr().err
    assert "fail-open" in error
    assert "pushing unverified" in error


def test_a_claim_on_another_branch_is_not_this_branch(offline, monkeypatch, capsys):
    offline["claims/acme-office/other.json"] = claim("bob")
    monkeypatch.setenv("HQ_AGENT", "alice")
    check()
    assert "BLOCKED" not in capsys.readouterr().err


def test_the_sovereign_is_warned_and_let_through(offline, monkeypatch, capsys):
    offline[PATH] = claim("bob")
    monkeypatch.setenv("HQ_OWNER", "alice")
    monkeypatch.setenv("HQ_AGENT", "alice")
    check()
    error = capsys.readouterr().err
    assert "sovereign push allowed" in error
    assert "BLOCKED" not in error


def test_without_a_configured_owner_nobody_is_sovereign(offline, monkeypatch):
    offline[PATH] = claim("bob")
    monkeypatch.setenv("HQ_AGENT", "alice")
    with pytest.raises(SystemExit):
        check()


def test_an_unresolvable_identity_is_blocked_not_waved_through(offline, capsys):
    """No HQ_AGENT, no session file, no git config: hq cannot tell whether this
    branch is its own, so the claim stands."""
    offline[PATH] = claim("bob")
    with pytest.raises(SystemExit) as stop:
        check()
    assert stop.value.code == 1
    assert "PUSH BLOCKED" in capsys.readouterr().err


def test_an_unconfigured_hq_warns_instead_of_blocking_every_push(monkeypatch, capsys):
    """A hook can outlive its config. Refusing every push in that state would
    be a worse failure than the one the guard prevents, so check-push is the
    single command that does not exit 1 on a missing config."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    check()
    error = capsys.readouterr().err
    assert "no head office repo configured" in error
    assert "hq init" in error


def test_a_reachable_office_blocks_on_a_live_claim(monkeypatch, capsys):
    monkeypatch.setenv("HQ_REPO", "acme/office")
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setattr(claims, "fetch_claims", lambda strict, cfg=None: True)
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {PATH: claim("bob")})
    with pytest.raises(SystemExit) as stop:
        check()
    assert stop.value.code == 1
    error = capsys.readouterr().err
    assert "PUSH BLOCKED" in error
    assert "cache" not in error  # the office answered; this is not a stale read


def write_config(text):
    from hq import config as conf
    path = conf.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_malformed_config_warns_instead_of_blocking_every_push(monkeypatch, capsys):
    """A push gate that dies on a stray character in config.toml blocks every
    push on the machine. The config problem is not evidence of a claim, so it
    fails OPEN, loudly, exactly like an unreachable office."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    path = write_config('repo = "acme/office\nowner = alice"\n[[[\n')
    check()
    error = capsys.readouterr().err
    assert "pushing unverified" in error
    assert "fail-open" in error
    assert str(path) in error


def test_an_unreadable_config_warns_instead_of_blocking_every_push(monkeypatch, capsys):
    """Same rule for a file hq is not allowed to read: a permissions accident
    must not become a machine-wide push freeze."""
    import os

    if os.geteuid() == 0:
        pytest.skip("root reads a chmod 000 file, so there is nothing to test")
    monkeypatch.delenv("HQ_REPO", raising=False)
    path = write_config('repo = "acme/office"\n')
    path.chmod(0o000)
    try:
        check()
    finally:
        path.chmod(0o600)
    error = capsys.readouterr().err
    assert "pushing unverified" in error
    assert "fail-open" in error
    assert str(path) in error


def test_a_readable_config_still_gates_the_push(monkeypatch, capsys):
    """The fail-open above is about NOT KNOWING. A config file hq can read is
    knowing, and the claim in it still blocks."""
    write_config('repo = "acme/office"\n')
    monkeypatch.delenv("HQ_REPO", raising=False)
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setattr(claims, "fetch_claims", lambda strict, cfg=None: True)
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {PATH: claim("bob")})
    with pytest.raises(SystemExit) as stop:
        check()
    assert stop.value.code == 1
    assert "PUSH BLOCKED" in capsys.readouterr().err


def test_a_config_that_is_not_utf8_warns_instead_of_blocking_every_push(
        monkeypatch, capsys):
    """The third way a config file can be unusable, after malformed and
    unreadable: bytes that are not UTF-8 at all.

    One accented name saved by an editor in latin-1 is enough. `read_text`
    raises `UnicodeDecodeError` there, and that is a `ValueError`, not an
    `OSError` - so it sailed straight past the fail-open handler and left the
    gate as a traceback with exit 1. The pre-push hook turns ANY non-zero exit
    into a blocked push, so this froze every push on the machine: the exact
    failure the fail-open rule exists to prevent.
    """
    monkeypatch.delenv("HQ_REPO", raising=False)
    path = conf_path()
    path.write_bytes(b'repo = "acme/office"\nowner = "Jos\xe9"\n')
    check()
    error = capsys.readouterr().err
    assert "pushing unverified" in error
    assert "fail-open" in error
    assert str(path) in error


def test_a_binary_config_warns_instead_of_blocking_every_push(monkeypatch, capsys):
    """The same, for a file that is not text at all - a truncated download, or
    something written over the config by accident."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    path = conf_path()
    path.write_bytes(b"\x00\x8d\xff\xfe binary junk \x00")
    check()
    error = capsys.readouterr().err
    assert "pushing unverified" in error
    assert "fail-open" in error


def conf_path():
    from hq import config as conf
    path = conf.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_an_unforeseen_crash_in_the_gate_fails_open(monkeypatch, capsys):
    """The general case behind the three config fixes above.

    Every one of them was the same shape: an exception nobody expected reached
    the top of `check-push`, the command exited 1 with a traceback, and the
    pre-push hook read that as a blocked push - so every push on the machine
    froze until somebody read the stack trace. The gate now treats anything
    unforeseen the way it treats an unreachable office: one warning line, and
    out of the way. A crash is not evidence of a claim.
    """
    monkeypatch.setenv("HQ_REPO", "acme/office")
    monkeypatch.setenv("HQ_AGENT", "alice")

    def explode(*_args, **_kwargs):
        raise RuntimeError("git went missing")

    monkeypatch.setattr(claims, "fetch_claims", explode)
    check()  # no SystemExit: exit 0, the push goes through
    error = capsys.readouterr().err
    assert "push gate failed unexpectedly" in error
    assert "RuntimeError: git went missing" in error
    assert "fail-open" in error


def test_the_fail_open_guard_does_not_swallow_a_block(offline, monkeypatch, capsys):
    """The guard above must not become a hole in the gate: a real claim by
    somebody else still exits 1, because that exit is a decision rather than a
    crash."""
    offline[PATH] = claim("bob")
    monkeypatch.setenv("HQ_AGENT", "alice")
    with pytest.raises(SystemExit) as stop:
        check()
    assert stop.value.code == 1
    assert "PUSH BLOCKED" in capsys.readouterr().err


# A branch name is not hq's to choose. `refs/heads/-weird` is a ref git accepts
# and pushes like any other, and the pre-push hook hands the name over as
# `-weird` - which argparse reads as an option, not as an argument.


def run_cli(monkeypatch, *argv):
    """Drive the real command line, not just `cmd_check_push`.

    The bug these tests guard lives in argument parsing, so it is invisible to a
    test that builds a `Namespace` by hand: by then the parse has already
    happened.
    """
    from hq import cli

    monkeypatch.setattr("sys.argv", ["hq", *argv])
    cli.main()


def test_a_branch_argparse_reads_as_an_option_does_not_block_the_push(
        offline, monkeypatch, capsys):
    """Exit 2 from the parser was a blocked push.

    The hook turns any non-zero exit from `check-push` into a refused push, and
    argparse answers a usage error with 2. So pushing `refs/heads/-weird` was
    refused on a machine where nothing was claimed at all, and no message named
    a claim, because there was none: the gate never ran. A gate that cannot read
    its own arguments knows nothing, and not knowing is never evidence of a
    claim.
    """
    monkeypatch.setenv("HQ_AGENT", "alice")
    with pytest.raises(SystemExit) as stop:
        run_cli(monkeypatch, "check-push", REMOTE, "-weird")
    assert stop.value.code == 0                  # the push goes through
    error = capsys.readouterr().err
    assert "could not read its own arguments" in error
    assert "fail-open" in error


def test_the_separator_lets_the_gate_check_that_branch_properly(
        offline, monkeypatch, capsys):
    """Fail-open is the safety net, not the answer. With `--`, which is what the
    hook now passes, the same branch is gated like any other and a live claim on
    it still blocks."""
    offline["claims/acme-office/weird.json"] = dict(claim("bob"), branch="-weird")
    monkeypatch.setenv("HQ_AGENT", "alice")
    with pytest.raises(SystemExit) as stop:
        run_cli(monkeypatch, "check-push", "--", REMOTE, "-weird")
    assert stop.value.code == 1
    assert "PUSH BLOCKED" in capsys.readouterr().err


def test_the_installed_hook_passes_the_gate_arguments_after_a_separator():
    from hq.hook import HOOK

    assert 'check-push -- "$repo_url" "$branch"' in HOOK


def test_a_usage_error_in_another_command_is_still_an_error(monkeypatch, capsys):
    """The fail-open is the push gate's alone. Every other command is a person
    at a terminal, who is owed the usage line and a non-zero exit."""
    with pytest.raises(SystemExit) as stop:
        run_cli(monkeypatch, "claim")            # no branch given
    assert stop.value.code == 2
    assert "usage" in capsys.readouterr().err


def test_check_push_help_still_exits_zero(monkeypatch, capsys):
    with pytest.raises(SystemExit) as stop:
        run_cli(monkeypatch, "check-push", "--help")
    assert stop.value.code == 0
    assert "fail-open" not in capsys.readouterr().out


# A config file hq cannot read is a gap in what hq knows about the OFFICE. The
# local claims cache lives under HQ_HOME or the default state dir, so it is
# usually still readable. The gate used to stop at the warning, so appending one
# stray character to config.toml turned a blocked push into an allowed one on
# the very same machine, with the very same claim still on disk.
#
# "Usually" is the case below it: `home` IS a config file key, so a machine set
# up with `hq init --home` has its state dir named in the unreadable file too.
# Then the cache hq searches is not the machine's own, and the gate has to say
# so rather than report that silence as an absence of claims.


def test_a_malformed_config_still_blocks_on_a_cached_claim(monkeypatch, capsys):
    """The finding, exactly: same cache, same claim, one broken config file."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    path = write_config('repo = "acme/office"\n[[[\n')
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {PATH: claim("bob")})

    with pytest.raises(SystemExit) as stop:
        check()

    assert stop.value.code == 1
    error = capsys.readouterr().err
    assert "PUSH BLOCKED" in error
    assert "bob" in error
    assert str(path) in error          # the config problem is still reported
    assert "cache" in error            # and the claim is named as a cached read
    assert "fail-open" not in error    # this push was not waved through


def test_a_malformed_config_with_a_silent_cache_still_fails_open(monkeypatch, capsys):
    """The rule the block above must not break: no claim, no block."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    write_config('repo = "acme/office"\n[[[\n')
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {})

    check()

    error = capsys.readouterr().err
    assert "pushing unverified" in error
    assert "fail-open" in error


def test_a_malformed_config_does_not_block_me_with_my_own_cached_claim(
        monkeypatch, capsys):
    monkeypatch.delenv("HQ_REPO", raising=False)
    write_config('repo = "acme/office"\n[[[\n')
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {PATH: claim("alice")})

    check()

    assert "BLOCKED" not in capsys.readouterr().err


def test_a_malformed_config_lets_the_sovereign_through_with_a_note(
        monkeypatch, capsys):
    """HQ_OWNER survives a broken file, so the sovereign rule survives with it."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    write_config('repo = "acme/office"\n[[[\n')
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setenv("HQ_OWNER", "alice")
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {PATH: claim("bob")})

    check()

    error = capsys.readouterr().err
    assert "sovereign push allowed" in error
    assert "BLOCKED" not in error


def test_a_broken_config_does_not_stop_the_gate_resolving_a_name(
        monkeypatch, capsys):
    """Reading the cache means knowing whose claim it is, and the name comes
    from this session, not from the file hq cannot read. Resolving it through
    the ordinary path would load the config strictly and exit 1 - which the
    fail-open wrapper does not catch, because a `SystemExit` is a decision. The
    session file below is the source that needs a config to find."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    monkeypatch.delenv("HQ_AGENT", raising=False)
    monkeypatch.setenv("HQ_SESSION_ID", "session-one")
    from hq.config import load_config
    cfg = load_config()
    cfg.session_dir.mkdir(parents=True, exist_ok=True)
    (cfg.session_dir / "session-one").write_text("alice\n")
    write_config('repo = "acme/office"\n[[[\n')
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {PATH: claim("alice")})

    check()

    error = capsys.readouterr().err
    assert "BLOCKED" not in error      # alice's own claim, read under her own name
    assert "push gate failed unexpectedly" not in error


def test_a_broken_config_says_the_state_dir_it_searched_may_be_wrong(
        monkeypatch, capsys):
    """The cache fallback above reads `cfg.state`, and `home` is a config file
    key. On a machine set up with `hq init --home`, the state dir is named in
    the very file hq cannot read, so `cfg.state` falls back to `~/.agent-hq`:
    hq searches a cache that is not this machine's, finds nothing, and used to
    report that as `holds no live claim` - a claim two directories away waved
    through by the branch that exists to catch exactly that."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    monkeypatch.delenv("HQ_HOME", raising=False)   # the sandbox sets it; a real machine need not
    write_config('repo = "acme/office"\nhome = "/moved/elsewhere"\n[[[\n')
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {})

    check()

    error = capsys.readouterr().err
    assert "fail-open" in error
    assert "may not be this machine's state dir" in error
    assert "HQ_HOME" in error


def test_with_hq_home_set_the_gate_does_not_hedge_about_the_state_dir(
        monkeypatch, capsys):
    """The hedge is about NOT KNOWING which state dir is this machine's. HQ_HOME
    is read whatever the config file does, so with it set there is nothing to
    hedge about and the line stays one line."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    write_config('repo = "acme/office"\nhome = "/moved/elsewhere"\n[[[\n')
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {})

    check()

    error = capsys.readouterr().err
    assert "fail-open" in error
    assert "may not be this machine's state dir" not in error


def test_a_cached_claim_is_evidence_whatever_the_state_dir_was(
        monkeypatch, capsys):
    """The hedge belongs to silence alone. A claim FOUND in that cache is
    positive evidence however hq got to the directory, so the block must not be
    softened by a note saying hq may have looked in the wrong place."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    monkeypatch.delenv("HQ_HOME", raising=False)
    write_config('repo = "acme/office"\nhome = "/moved/elsewhere"\n[[[\n')
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {PATH: claim("bob")})

    with pytest.raises(SystemExit) as stop:
        check()

    assert stop.value.code == 1
    error = capsys.readouterr().err
    assert "PUSH BLOCKED" in error
    assert "may not be this machine's state dir" not in error


# HQ_REPO alone is a complete answer to "where is the office": the environment
# is read whatever the config file does, and with the file merely ABSENT the
# gate asks the office and blocks on what it finds. A file hq cannot READ was
# worse than no file at all - it stopped the gate at the local cache - so a
# stray character downgraded a machine a spawner had configured correctly to a
# guess, on every push, while the office would have answered.


def test_a_broken_config_still_asks_the_office_when_the_environment_names_it(
        monkeypatch, capsys):
    """The finding: same environment, same office, one broken file."""
    monkeypatch.setenv("HQ_REPO", "acme/office")
    monkeypatch.setenv("HQ_AGENT", "alice")
    write_config('repo = "acme/office"\n[[[\n')
    monkeypatch.setattr(claims, "fetch_claims", lambda strict, cfg=None: True)
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {PATH: claim("bob")})

    with pytest.raises(SystemExit) as stop:
        check()

    assert stop.value.code == 1
    error = capsys.readouterr().err
    assert "PUSH BLOCKED" in error
    assert "cannot parse the config file" in error  # the file problem is still said
    assert "cache" not in error                     # but the OFFICE answered, not the cache


def test_an_office_the_environment_names_lets_a_clean_branch_through(
        monkeypatch, capsys):
    """The other half of asking: an unclaimed branch is not blocked by the
    broken file either."""
    monkeypatch.setenv("HQ_REPO", "acme/office")
    monkeypatch.setenv("HQ_AGENT", "alice")
    write_config('repo = "acme/office"\n[[[\n')
    monkeypatch.setattr(claims, "fetch_claims", lambda strict, cfg=None: True)
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {})

    check()

    error = capsys.readouterr().err
    assert "BLOCKED" not in error
    assert "fail-open" not in error   # nothing was unverified: the office answered


def test_a_broken_config_and_an_unreachable_office_still_fall_back_to_the_cache(
        monkeypatch, capsys):
    """Carrying on to the office must not lose the cache fallback: when the
    office does not answer either, a claim on disk still blocks."""
    monkeypatch.setenv("HQ_REPO", "acme/office")
    monkeypatch.setenv("HQ_AGENT", "alice")
    write_config('repo = "acme/office"\n[[[\n')
    monkeypatch.setattr(claims, "fetch_claims", lambda strict, cfg=None: False)
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {PATH: claim("bob")})

    with pytest.raises(SystemExit) as stop:
        check()

    assert stop.value.code == 1
    error = capsys.readouterr().err
    assert "PUSH BLOCKED" in error
    assert "cache" in error


def test_a_broken_config_and_an_unreachable_office_and_a_silent_cache_fail_open(
        monkeypatch, capsys):
    """And the rule none of this may break: not knowing is not a block."""
    monkeypatch.setenv("HQ_REPO", "acme/office")
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.delenv("HQ_HOME", raising=False)
    write_config('repo = "acme/office"\nhome = "/moved/elsewhere"\n[[[\n')
    monkeypatch.setattr(claims, "fetch_claims", lambda strict, cfg=None: False)
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {})

    check()

    error = capsys.readouterr().err
    assert "fail-open" in error
    # the office was asked and did not answer, so the hedge about WHICH cache
    # hq fell back to applies here as well
    assert "may not be this machine's state dir" in error


# The two above put the claim in a monkeypatched `claims_tree`, which answers
# the same for every state dir. These two put it in a real cache on disk, under
# a state dir named ONLY in the config file, because the question they ask is
# which directory the gate actually reads - and they are the pair an operator
# lives: same machine, same claim, one appended character, then HQ_HOME.


def seed_cache(state, files):
    """A real claims cache under `state`, the way hq keeps one."""
    import json
    import os
    import subprocess

    cache = state / "repo"
    cache.mkdir(parents=True)
    env = dict(os.environ, GIT_INDEX_FILE=str(state / "seed.index"),
               GIT_AUTHOR_NAME="hq", GIT_AUTHOR_EMAIL="hq@example.invalid",
               GIT_COMMITTER_NAME="hq", GIT_COMMITTER_EMAIL="hq@example.invalid")

    def git(*args, stdin=None):
        return subprocess.run(["git", *args], cwd=cache, env=env, input=stdin,
                              capture_output=True, text=True,
                              check=True).stdout.strip()

    git("init", "--quiet", ".")
    git("read-tree", "--empty")
    for path, content in files.items():
        blob = git("hash-object", "-w", "--stdin", stdin=json.dumps(content))
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
    git("update-ref", "refs/remotes/origin/claims",
        git("commit-tree", git("write-tree"), "-m", "seed"))
    return cache


def config_naming(state):
    from hq.config import toml_string

    return f'repo = "acme/office"\nhome = {toml_string(str(state))}\n'


def test_a_state_dir_named_only_in_the_broken_file_is_not_the_one_hq_reads(
        tmp_path, monkeypatch, capsys):
    """The reproduction, end to end: bob's claim is in a cache under a moved
    state dir, and the office is down, so the cache is what decides. Readable
    file, `home` honoured, push blocked. One stray character later the same
    push goes through - and the line no longer offers the empty default
    directory's silence as an answer about this branch."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    monkeypatch.delenv("HQ_HOME", raising=False)   # the file is the only source
    monkeypatch.setenv("HQ_AGENT", "alice")
    state = tmp_path / "moved-state"
    seed_cache(state, {PATH: claim("bob")})
    monkeypatch.setattr(claims, "fetch_claims", lambda strict, cfg=None: False)

    write_config(config_naming(state))
    with pytest.raises(SystemExit) as stop:
        check()
    assert stop.value.code == 1
    assert "PUSH BLOCKED" in capsys.readouterr().err

    path = write_config(config_naming(state) + "[[[\n")
    check()                                        # exit 0: not knowing is not a block

    error = capsys.readouterr().err
    assert str(path) in error
    assert "fail-open" in error
    assert "could not be read" in error            # what the file could not tell hq
    assert "HQ_HOME" in error                      # and the way to be sure
    assert "does not exist" in error               # this machine has no default state dir
    assert str(state) not in error                 # the cache with the claim was not read


def test_hq_home_reaches_that_same_cache_through_the_same_broken_file(
        tmp_path, monkeypatch, capsys):
    """And the other half of the advice: with HQ_HOME set to that state dir, the
    unreadable file costs nothing. The gate reads the cache that holds bob's
    claim and blocks, with no hedge, because nothing about where to look was
    lost with the file."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    monkeypatch.setenv("HQ_AGENT", "alice")
    state = tmp_path / "moved-state"
    seed_cache(state, {PATH: claim("bob")})
    monkeypatch.setenv("HQ_HOME", str(state))
    write_config(config_naming(state) + "[[[\n")

    with pytest.raises(SystemExit) as stop:
        check()

    assert stop.value.code == 1
    error = capsys.readouterr().err
    assert "PUSH BLOCKED" in error
    assert "bob" in error
    assert "local cache" in error                  # the office was never asked
    assert str(state) in error
    assert "may not be this machine's state dir" not in error
