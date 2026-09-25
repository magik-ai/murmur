"""Reading mail: the first-read window, the byte cap, and the cursor.

An unbounded first read would hand a brand new lane every broadcast ever sent,
which can be more than a spawner can paste into one prompt: so a first read
shows one day, and one read shows at most INBOX_BYTE_CAP bytes. And a plain
read CONSUMES: the cursor is per name per machine, so a watcher polling
`hq inbox` eats mail that nobody then sees.

No GitHub here: the two functions that reach the network are replaced.
"""

import argparse
import json
from datetime import timedelta

import pytest

from hq import mail
from hq.util import iso, now


def message(hours_ago, body):
    return {"createdAt": iso(now() - timedelta(hours=hours_ago)), "body": body}


@pytest.fixture
def office(monkeypatch):
    """An office whose mailboxes are a dict, not a GitHub repo."""
    monkeypatch.setenv("HQ_REPO", "acme/office")
    monkeypatch.setenv("HQ_AGENT", "alice")
    boxes = {}

    def find_issue(title):
        return {"inbox: alice": 1, "inbox: all": 2}.get(title)

    def gh_json(args):
        number = int(args[2])
        return {"comments": boxes.get(number, [])}

    monkeypatch.setattr(mail, "find_issue", find_issue)
    monkeypatch.setattr(mail, "gh_json", gh_json)
    return boxes


def read(**flags):
    args = argparse.Namespace(peek=False, recent=None, all=False)
    for key, value in flags.items():
        setattr(args, key, value)
    mail.cmd_inbox(args)


def test_a_first_read_shows_the_last_day_and_not_the_whole_archive(office, capsys):
    office[1] = [message(72, "ancient history"), message(30, "yesterday morning"),
                 message(2, "still actionable")]
    read()
    out = capsys.readouterr().out
    assert "still actionable" in out
    assert "ancient history" not in out
    assert "yesterday morning" not in out


def test_a_read_moves_the_cursor_and_the_next_read_is_empty(office, capsys):
    from hq.config import load_config

    office[1] = [message(2, "the only message")]
    read()
    first = capsys.readouterr().out
    assert "the only message" in first
    assert "read cursor for 'alice'" in first

    cursor = json.loads(load_config().lastread_file.read_text())
    assert "alice" in cursor

    read()
    assert "inbox empty" in capsys.readouterr().out


def test_peek_shows_the_same_mail_and_leaves_the_cursor_alone(office, capsys):
    from hq.config import load_config

    office[1] = [message(2, "for the watcher")]
    read(peek=True)
    out = capsys.readouterr().out
    assert "for the watcher" in out
    assert "did not move" in out
    assert not load_config().lastread_file.exists()

    # The watcher consumed nothing, so the agent still gets its mail.
    read()
    assert "for the watcher" in capsys.readouterr().out


def test_recent_re_shows_old_mail_without_moving_the_cursor(office, capsys):
    from hq.config import load_config

    office[1] = [message(2, "said once")]
    read()
    capsys.readouterr()
    read(recent=6)
    out = capsys.readouterr().out
    assert "said once" in out
    assert "did not move" in out
    cursor = json.loads(load_config().lastread_file.read_text())
    read(recent=6)
    assert json.loads(load_config().lastread_file.read_text()) == cursor


def test_the_byte_cap_drops_the_oldest_and_says_so(office, capsys):
    """Newest mail is the mail that still changes what you do, so truncation
    happens at the OLD end, and never silently."""
    filler = "x" * 2000
    office[1] = [message(20 - index, f"message {index:02d} {filler}")
                 for index in range(40)]
    read()
    out = capsys.readouterr().out
    assert len(out.encode()) < mail.INBOX_BYTE_CAP + 2000
    assert "message 39" in out      # newest kept
    assert "message 00" not in out  # oldest dropped
    assert f"older message(s) omitted to stay under {mail.INBOX_BYTE_CAP} bytes" in out
    assert "hq inbox --all" in out


def test_all_lifts_both_limits(office, capsys):
    filler = "x" * 2000
    office[1] = [message(500, f"old news {filler}")] + [
        message(20 - index, f"message {index:02d} {filler}") for index in range(40)]
    read(all=True)
    out = capsys.readouterr().out
    assert "old news" in out
    assert "message 00" in out
    assert "omitted" not in out


def test_a_single_oversized_message_is_still_shown(office, capsys):
    """The cap must not be able to produce an empty inbox out of a full one."""
    office[1] = [message(1, "y" * (mail.INBOX_BYTE_CAP * 2))]
    read()
    out = capsys.readouterr().out
    assert "yyy" in out
    assert "inbox empty" not in out


def test_broadcast_and_personal_mail_arrive_together(office, capsys):
    office[1] = [message(3, "just for alice")]
    office[2] = [message(1, "for everyone")]
    read()
    out = capsys.readouterr().out
    assert "just for alice" in out
    assert "for everyone" in out
