"""Small shared helpers: subprocess, time, slugs, remote URLs."""

import re
import subprocess
import sys
from datetime import datetime, timezone

# How long a network git operation may take before hq decides it is offline.
NET_TIMEOUT = 8


class MissingTool(FileNotFoundError):
    """A program hq shells out to is not installed, or is not on PATH.

    A subclass of `FileNotFoundError`, so every handler that already catches
    that keeps working; what it adds is the NAME of the program. Without it the
    two ways `subprocess` raises FileNotFoundError - a missing program and a
    missing `cwd` - are indistinguishable, and hq reported one as the other.
    """

    def __init__(self, program):
        self.program = program
        super().__init__(f"`{program}` is not installed or not on PATH - hq needs "
                         "python, git and gh, and nothing else")


def run(cmd, check=True, timeout=None, capture=True, cwd=None):
    """Every subprocess hq runs, decoded as UTF-8 and never in the locale.

    `text=True` alone decodes with the machine's locale encoding and the strict
    error handler, which makes two ordinary things fatal. Under a non-UTF-8
    locale - `LC_ALL=C` in a cron job, a bare CI runner, a systemd unit - an
    accented agent name in `git config hq.agent` raised UnicodeDecodeError, and
    that crashed the pre-push gate, which the hook reads as a blocked push: one
    name froze every push on the machine. A stray byte in any git output did the
    same on any locale.

    UTF-8 is what git actually writes, so this decodes more correctly, not just
    more safely; `errors="replace"` means a byte hq cannot read costs one
    character in a name rather than the command.
    """
    try:
        return subprocess.run(
            cmd, check=check, timeout=timeout, cwd=cwd,
            capture_output=capture, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as error:
        # Two different absences raise this: the program is not on PATH, or
        # `cwd` does not exist. Only the first is a missing tool, and only
        # `filename` tells them apart - it is the program for the first and the
        # directory for the second.
        if error.filename in (None, cmd[0]):
            raise MissingTool(cmd[0]) from None
        raise


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def parse_repo(url):
    """owner/name out of any remote URL form, or None.

    An ~/.ssh/config alias (`git@github-alias:acme/fleet.git`) hides the real hostname, so a
    github.com-only pattern silently fails on it. That is worse than it sounds: the pre-push guard
    then keys claims by the raw URL, matches nothing, and waves every push through.
    """
    m = re.search(r"github\.com[:/]+([^/]+)/([^/.]+)", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    # scp-like form, any host or host alias: [user@]host:owner/name[.git]
    m = re.match(r"^(?:[\w.-]+@)?[\w.-]+:([^/\s]+)/([^/\s.]+?)(?:\.git)?/?$", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    # ssh://[user@]host/owner/name[.git]
    m = re.match(r"^ssh://(?:[\w.-]+@)?[\w.-]+/([^/\s]+)/([^/\s.]+?)(?:\.git)?/?$", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return None


def detect_repo():
    try:
        url = run(["git", "remote", "get-url", "origin"]).stdout.strip()
    except Exception:
        sys.exit("hq: not inside a git repo with an origin remote - pass --repo owner/name")
    repo = parse_repo(url)
    if not repo:
        sys.exit(f"hq: cannot parse owner/name from origin url {url!r} - pass --repo")
    return repo
