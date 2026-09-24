"""Presence: any command that acts under a name keeps that name live.

`hq who` and the dashboard call a session live while its session issue was
updated in the last three hours, and only `hq hello` used to touch that issue.
On 2026-09-24 the owner had four agents working and the Mail tab showed two:
the other two had said hello in the morning and then only sent mail, claimed
branches and read their inbox, none of which counted.

No GitHub here: the office is a dict, and every `gh` call is recorded. The
heartbeat's detached child runs in-process (see conftest), except in the tests
that start a real one against a fake `gh` on PATH.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta

import pytest

from hq import claims, mail, presence, registry
from hq.config import load_config
from hq.util import iso, now

SESSION = 7
# The real launcher, before conftest swaps in the in-process child.
START_CHILD = presence.start_child


@pytest.fixture
def office(monkeypatch):
    """alice is registered (session issue #7) and has one message waiting."""
    monkeypatch.setenv("HQ_REPO", "acme/office")
    monkeypatch.setenv("HQ_AGENT", "alice")
    calls = {"heartbeats": [], "lookups": [], "sent": []}
    sessions = {"session: alice": SESSION}

    def find_session(title):
        calls["lookups"].append(title)
        return sessions.get(title)

    def presence_gh(args, **_kwargs):
        calls["heartbeats"].append(args)

    monkeypatch.setattr(presence, "find_issue", find_session)
    monkeypatch.setattr(presence, "gh", presence_gh)

    boxes = {1: [{"createdAt": iso(now() - timedelta(hours=1)), "body": "hi alice"}]}
    monkeypatch.setattr(mail, "find_issue",
                        lambda title: {"inbox: alice": 1, "inbox: all": 2}.get(title))
    monkeypatch.setattr(mail, "gh_json",
                        lambda args: {"comments": boxes.get(int(args[2]), [])})
    monkeypatch.setattr(mail, "ensure_issue", lambda title, label, body: 3)
    monkeypatch.setattr(mail, "gh", lambda args, **_kw: calls["sent"].append(args))
    calls["sessions"] = sessions
    return calls


def stamp(hours_ago):
    path = presence.stamp_path("alice")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(iso(now() - timedelta(hours=hours_ago)) + "\n")


def stamp_age_minutes():
    text = presence.stamp_path("alice").read_text().strip()
    return (now() - presence.datetime.fromisoformat(text.replace("Z", "+00:00"))
            ).total_seconds() / 60


def send(text="status: green"):
    mail.cmd_msg(argparse.Namespace(name="bob", text=text))


def inbox(**flags):
    args = argparse.Namespace(peek=False, recent=None, all=False)
    for key, value in flags.items():
        setattr(args, key, value)
    mail.cmd_inbox(args)


def test_a_stale_stamp_posts_one_heartbeat_and_moves_the_stamp(office):
    """The regression: alice said hello hours ago and has been sending mail
    since. Without the fix, nothing but hello ever touched issue #7."""
    stamp(hours_ago=2)
    send()
    assert len(office["heartbeats"]) == 1
    heartbeat = office["heartbeats"][0]
    assert heartbeat[:3] == ["issue", "comment", str(SESSION)]
    assert heartbeat[heartbeat.index("--repo") + 1] == "acme/office"
    assert heartbeat[heartbeat.index("--body") + 1].startswith("heartbeat ")
    assert stamp_age_minutes() < 1
    assert len(office["sent"]) == 1         # and the message still went


def test_a_missing_stamp_posts_one_heartbeat(office):
    send()
    assert len(office["heartbeats"]) == 1
    assert presence.stamp_path("alice").exists()


def test_a_fresh_stamp_costs_no_call_at_all(office):
    stamp(hours_ago=0.5)
    send()
    inbox()
    assert office["heartbeats"] == []
    assert office["lookups"] == []          # not even the issue listing


def test_a_busy_hour_posts_one_heartbeat_not_one_per_command(office):
    send("one")
    send("two")
    inbox(peek=True)
    assert len(office["heartbeats"]) == 1
    assert len(office["sent"]) == 2


def test_two_commands_at_once_start_one_child(office, monkeypatch):
    """The review's schedule: two commands for the same name both read a stale
    stamp, and wait for each other there before either writes it. Without the
    lock both went on to post. With it, the second cannot re-read the stamp
    until the first has rewritten it, so the rendezvous times out and only one
    child starts."""
    stamp(hours_ago=2)
    rendezvous = threading.Barrier(2, timeout=0.5)
    due = presence.heartbeat_due

    def due_then_meet(name, cfg=None):
        result = due(name, cfg)
        try:
            rendezvous.wait()
        except threading.BrokenBarrierError:
            pass
        return result

    started = []

    def start(name):
        # The hour is claimed before the child starts, never after.
        assert stamp_age_minutes() < 1
        started.append(name)

    monkeypatch.setattr(presence, "heartbeat_due", due_then_meet)
    monkeypatch.setattr(presence, "start_child", start)
    cfg = load_config()
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        presence.keep_alive("alice", cfg))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(results) == [False, True]
    assert started == ["alice"]


def test_the_stamps_are_private_to_the_account(office):
    old = os.umask(0o022)
    try:
        send()
        presence.mark_heartbeat("bob")
    finally:
        os.umask(old)
    directory = load_config().presence_dir
    assert directory.stat().st_mode & 0o777 == 0o700
    for name in ("alice", "bob"):
        assert presence.stamp_path(name).stat().st_mode & 0o777 == 0o600
    assert load_config().state.joinpath("presence.lock").stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in directory.iterdir()) == ["alice", "bob"]


def test_a_name_with_no_session_issue_posts_nothing(office):
    office["sessions"].clear()
    send()
    assert office["heartbeats"] == []
    assert len(office["sent"]) == 1


@pytest.mark.parametrize("failure", [
    SystemExit("hq: `gh issue comment` failed (API rate limit exceeded) - check "
               "`gh auth status`"),
    OSError("network is unreachable"),
])
def test_a_failing_heartbeat_does_not_fail_the_command(office, monkeypatch, capsys,
                                                       failure):
    def refuse(args, **_kwargs):
        raise failure

    monkeypatch.setattr(presence, "gh", refuse)
    send()
    assert len(office["sent"]) == 1
    # The child swallows it: nobody is reading its stderr, and the command's
    # own output stays the command's.
    assert "presence" not in capsys.readouterr().err
    # The attempt is stamped, so a rate-limited office is not asked again by
    # every command for the next hour.
    assert stamp_age_minutes() < 1


def test_a_failing_lookup_does_not_fail_the_command(office, monkeypatch, capsys):
    def down(title):
        raise SystemExit("hq: `gh issue list` did not answer within 30s")

    monkeypatch.setattr(presence, "find_issue", down)
    inbox()
    captured = capsys.readouterr()
    assert "hi alice" in captured.out
    assert "presence" not in captured.err


def test_a_child_that_cannot_start_does_not_fail_the_command(office, monkeypatch,
                                                             capsys):
    def no_fork(name):
        raise OSError("Resource temporarily unavailable")

    monkeypatch.setattr(presence, "start_child", no_fork)
    send()
    assert len(office["sent"]) == 1
    err = capsys.readouterr().err
    assert len(err.strip().splitlines()) == 1
    assert "could not refresh the presence of 'alice'" in err


def fake_gh(tmp_path, monkeypatch, seconds):
    """Put a `gh` on PATH that logs each call, sleeps, then fails as GitHub
    would. Returns the log. The real child runs the real `hq _heartbeat`."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    log = tmp_path / "gh-calls"
    script = bin_dir / "gh"
    script.write_text(f"#!/bin/sh\necho \"$*\" >> '{log}'\nsleep {seconds}\n"
                      "echo 'HTTP 502: bad gateway' >&2\nexit 1\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def wait_for(path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().splitlines()
        time.sleep(0.05)
    return []


def test_a_slow_failing_office_does_not_slow_the_command(office, monkeypatch, tmp_path):
    """The review's blocker: each `gh` call may take 30 seconds to time out,
    and the heartbeat used to make them before the command could go on. Here
    the office takes 3 seconds to fail; the command must not wait for it."""
    log = fake_gh(tmp_path, monkeypatch, seconds=3)
    started = []

    def start(name):
        started.append(name)
        START_CHILD(name)

    monkeypatch.setattr(presence, "start_child", start)
    began = time.monotonic()
    send()
    assert time.monotonic() - began < 1.5
    assert len(office["sent"]) == 1
    assert started == ["alice"]
    # The child did run, detached, and reached the (fake) office once.
    calls = wait_for(log)
    assert len(calls) == 1 and calls[0].startswith("issue list --repo acme/office")
    send("again")
    assert started == ["alice"]


def test_the_child_prints_nothing_and_exits_zero_when_the_office_fails(
        monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_REPO", "acme/office")
    log = fake_gh(tmp_path, monkeypatch, seconds=0)
    child = subprocess.run(presence.child_argv("alice"), capture_output=True,
                           text=True, timeout=30,
                           env={**os.environ, "PYTHONPATH": str(presence.Path(
                               presence.__file__).resolve().parent.parent)})
    assert (child.returncode, child.stdout, child.stderr) == (0, "", "")
    assert len(log.read_text().splitlines()) == 1


def test_peek_counts_as_activity_and_still_leaves_the_cursor(office, capsys):
    inbox(peek=True)
    assert len(office["heartbeats"]) == 1
    assert "hi alice" in capsys.readouterr().out
    assert not load_config().lastread_file.exists()


def test_a_plain_read_heartbeats_and_moves_the_cursor(office):
    inbox()
    assert len(office["heartbeats"]) == 1
    assert "alice" in json.loads(load_config().lastread_file.read_text())


def test_release_keeps_the_name_live_too(office, monkeypatch, capsys):
    monkeypatch.setattr(claims, "fetch_claims", lambda **_kw: True)
    monkeypatch.setattr(claims, "claims_tree", lambda cfg=None: {})
    claims.cmd_release(argparse.Namespace(branch="topic", repo="acme/thing",
                                          force=False))
    assert "no claim on acme/thing#topic" in capsys.readouterr().out
    assert len(office["heartbeats"]) == 1


def test_a_name_from_shared_state_is_never_heartbeated(office, monkeypatch, git_checkout):
    """A read may resolve a name from the clone config, but that name may be
    another agent's: refreshing it would keep somebody else looking live."""
    from hq import identity

    monkeypatch.delenv("HQ_AGENT")
    git_checkout("alice")
    assert identity.require_identity(strict=False) == "alice"
    assert office["heartbeats"] == []
    assert office["lookups"] == []


def test_hello_stamps_so_the_next_command_does_not_repeat_it(office, monkeypatch):
    monkeypatch.setattr(registry, "find_issue", lambda title: None)
    monkeypatch.setattr(registry, "ensure_issue", lambda title, label, body: SESSION)
    said = []
    monkeypatch.setattr(registry, "gh", lambda args, **_kw: said.append(args))
    registry.cmd_hello(argparse.Namespace(name="alice", task="the presence fix"))
    assert said[0][said[0].index("--body") + 1].startswith("heartbeat ")
    send()
    assert office["heartbeats"] == []
