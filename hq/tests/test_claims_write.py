"""Taking or dropping a claim is the one thing hq WRITES to the office.

Every step of it is a git plumbing command nobody but hq runs, so a raw
failure there would be a stack trace ending in `git update-index` - which tells
an agent nothing about the only question that matters: does somebody hold this
branch now, or not.
"""

import argparse
import json
import subprocess

import pytest

from hq import claims
from hq.config import config_path, load_config, toml_string


@pytest.fixture
def cache_repo(monkeypatch):
    """A cache clone that is a real git repo, with the office out of the way."""
    monkeypatch.setenv("HQ_REPO", "acme/office")
    cfg = load_config()
    cfg.cache.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(cfg.cache)], check=True)
    monkeypatch.setattr(claims, "fetch_claims", lambda strict, cfg=None: True)
    return cfg


def change(message="claim acme/thing#topic by alice"):
    claims.commit_claims_change({"claims/acme-thing/topic.json": "{}\n"}, [], message)


def test_a_push_that_never_answers_says_it_may_or_may_not_have_landed(cache_repo,
                                                                      monkeypatch):
    """The one failure hq must not describe as either outcome.

    A push that timed out may have reached the office with the answer lost on
    the way back. Reporting "not taken" could hand the branch to a second agent;
    reporting "taken" could claim one nobody holds. hq names the ambiguity and
    the command that settles it.
    """
    real = claims.run

    def hang(cmd, **kwargs):
        if "push" in cmd:
            raise subprocess.TimeoutExpired(cmd, claims.PUSH_TIMEOUT)
        return real(cmd, **kwargs)

    monkeypatch.setattr(claims, "run", hang)

    with pytest.raises(SystemExit) as stop:
        change()

    said = str(stop.value)
    assert "may or may not have landed" in said
    assert "hq claims" in said
    assert "Traceback" not in said


def test_a_cache_hq_cannot_write_is_one_line_and_says_nothing_was_pushed(cache_repo):
    """The index file is hq's own scratch state. When it cannot be written -
    a read-only state dir, a leftover directory in its place - the commit is
    never built, so nothing reached the office and the answer is not ambiguous.
    """
    cache_repo.claims_index.parent.mkdir(parents=True, exist_ok=True)
    cache_repo.claims_index.mkdir()          # a directory where git wants a file

    with pytest.raises(SystemExit) as stop:
        change()

    said = str(stop.value)
    assert "cannot build the claims commit" in said
    assert "nothing was pushed" in said


def test_a_machine_without_git_does_not_traceback_through_the_plumbing(cache_repo,
                                                                       tmp_path,
                                                                       monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(SystemExit) as stop:
        change()

    assert "cannot build the claims commit" in str(stop.value)


def test_a_claim_is_still_written_when_the_office_answers(cache_repo, monkeypatch):
    """The guard rails must not have broken the ordinary path: the claim file
    is in the pushed commit's tree."""
    pushed = {}
    real = claims.run

    def capture(cmd, **kwargs):
        if "push" in cmd:
            pushed["commit"] = cmd[-1].split(":")[0]
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real(cmd, **kwargs)

    monkeypatch.setattr(claims, "run", capture)
    change()

    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", pushed["commit"]],
        cwd=cache_repo.cache, capture_output=True, text=True, check=True).stdout
    assert "claims/acme-thing/topic.json" in listing


def test_cmd_claim_reaches_the_same_one_line(cache_repo, monkeypatch, tmp_path):
    """Through the command an agent actually types, not just the helper."""
    monkeypatch.setenv("HQ_AGENT", "alice")
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {})
    real = claims.run

    def hang(cmd, **kwargs):
        if "push" in cmd:
            raise subprocess.TimeoutExpired(cmd, claims.PUSH_TIMEOUT)
        return real(cmd, **kwargs)

    monkeypatch.setattr(claims, "run", hang)

    with pytest.raises(SystemExit) as stop:
        claims.cmd_claim(argparse.Namespace(branch="topic", repo="acme/thing",
                                            ttl=24, note=None))

    assert "may or may not have landed" in str(stop.value)


# The compare-and-swap itself, against a real head office on disk: a bare repo,
# empty like the one `gh repo create` makes, reached through clone_url_template.
# Each agent acts from a state dir of its own, as if on a machine of its own.


@pytest.fixture
def office(tmp_path, monkeypatch):
    path = tmp_path / "office.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(path)], check=True)
    config = config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('repo = "acme/office"\n'
                      f"clone_url_template = {toml_string(str(path))}\n")

    class Office:
        def become(self, agent):
            monkeypatch.setenv("HQ_AGENT", agent)
            monkeypatch.setenv("HQ_HOME", str(tmp_path / f"state-{agent}"))

        def claim(self, agent, ttl=24):
            self.become(agent)
            claims.cmd_claim(argparse.Namespace(branch="topic", repo="acme/thing",
                                                ttl=ttl, note=None))

        def holder(self):
            shown = subprocess.run(
                ["git", "--git-dir", str(self.path), "show",
                 "claims:claims/acme-thing/topic.json"],
                capture_output=True, text=True, check=True).stdout
            return json.loads(shown)["owner"]

        def lands_first(self, agent, then):
            """Make the next push lose the race: `agent` claims the branch,
            start to finish, just before it."""
            real = claims.run
            raced = []

            def run(cmd, **kwargs):
                if "push" in cmd and not raced:
                    raced.append(agent)
                    self.claim(agent)
                    self.become(then)
                return real(cmd, **kwargs)

            monkeypatch.setattr(claims, "run", run)
            return raced

    found = Office()
    found.path = path
    return found


def test_two_agents_claiming_one_branch_at_once_cannot_both_win(office):
    """bob's first push loses to alice's. His retry must read alice's claim and
    stop, not write over it: if both were told "claimed", one of them would go
    on working on a branch the gate then refuses to let them push."""
    raced = office.lands_first("alice", then="bob")

    with pytest.raises(SystemExit) as stop:
        office.claim("bob")

    assert raced == ["alice"]                        # bob's first push did lose
    assert "CLAIMED by alice" in str(stop.value)      # and bob is told who won
    assert office.holder() == "alice"


def test_a_release_that_loses_the_race_leaves_the_new_claim_alone(office):
    """bob's claim has run out and he releases it just as alice claims the
    branch. His retry must not delete the claim that landed first."""
    office.claim("bob", ttl=-1)
    raced = office.lands_first("alice", then="bob")

    office.become("bob")
    with pytest.raises(SystemExit) as stop:
        claims.cmd_release(argparse.Namespace(branch="topic", repo="acme/thing",
                                              force=False))

    assert raced == ["alice"]
    assert "claim belongs to alice" in str(stop.value)
    assert office.holder() == "alice"


def test_claims_commits_carry_an_address_github_links_to_nobody(office):
    """The author of a claims commit is hq's bot identity, and its default
    address is on a reserved domain, so GitHub cannot link it to any account."""
    office.claim("alice")
    author = subprocess.run(
        ["git", "--git-dir", str(office.path), "log", "-1", "--format=%an <%ae>",
         "claims"], capture_output=True, text=True, check=True).stdout.strip()
    assert author == "hq <hq@example.invalid>"
