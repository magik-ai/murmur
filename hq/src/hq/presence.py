"""Presence: a busy agent must not look gone.

`hq who` and the dashboard count a session as live while its session issue was
updated in the last few hours. If only `hq hello` commented on it, an agent that
said hello once in the morning and then worked all day, sending mail, claiming
and releasing branches, reading its inbox, would look stale by lunchtime.

So every command that acts under a name refreshes that name's presence, at most
once an hour per name per machine. A local stamp holds the time of the last
attempt: while it is fresh, nothing is called; when it is stale or missing, the
same heartbeat comment `hq hello` posts goes on the name's open session issue.
The check and the stamp happen under one lock, so a burst of commands that all
find the stamp stale still posts once.
No session issue means nothing is posted: `hq hello` is still what registers a
session.

A heartbeat never fails the command it rides on, and never slows it: the post
goes out from a detached child process (the hidden `hq _heartbeat NAME`), so the
command returns at once whatever GitHub does, and the child swallows its own
errors. Each GitHub call may take up to 30 seconds to time out; done inline, a
slow office could add up to a minute to the first command of the hour.
"""

import fcntl
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .config import load_config, require_repo
from .github import find_issue, gh
from .util import iso, now, slug

# At most one heartbeat per name per machine in this long. Well inside the
# three hours after which `hq who` calls a session stale.
HEARTBEAT_EVERY = timedelta(hours=1)

# The hidden subcommand the detached child runs. Not in `hq --help`: nobody
# types it, `keep_alive` starts it.
CHILD_COMMAND = "_heartbeat"


def heartbeat_body(what):
    """The comment `hq hello` posts, and the one every later heartbeat posts."""
    return f"heartbeat {iso(now())} - {what}"


def stamp_path(name, cfg=None):
    cfg = cfg or load_config()
    return cfg.presence_dir / slug(name).lower()


def lock_path(cfg=None):
    """One lock for every stamp, beside their directory: a name is slugged into
    `presence.d/`, so no name can land on it."""
    cfg = cfg or load_config()
    return cfg.state / "presence.lock"


def write_stamp(name, cfg=None):
    """Write the stamp whole or not at all (a temporary file, then a rename), so
    a reader never sees half a time and takes the stamp for missing.

    Private to the account: which names this machine acts under, and when,
    is nobody else's business. The directory is 0700 and each stamp 0600
    (mkstemp's mode) whatever the umask."""
    path = stamp_path(name, cfg)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_mode & 0o077:
        path.parent.chmod(0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as out:
            out.write(iso(now()) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def mark_heartbeat(name, cfg=None):
    """Record that this machine heartbeated for `name` just now (`hq hello`
    posted one itself). Never raises: a stamp that cannot be written costs one
    extra heartbeat, not the command."""
    try:
        write_stamp(name, cfg)
    except OSError:
        pass


def heartbeat_due(name, cfg=None):
    """True when the stamp is missing, unreadable, or older than an hour."""
    try:
        text = stamp_path(name, cfg).read_text().strip()
        last = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (OSError, ValueError):
        return True
    return now() - last >= HEARTBEAT_EVERY


def claim_hour(name, cfg=None):
    """True for exactly one caller per hour per name on this machine, however
    many commands start at once.

    Two commands can both read a stale stamp. So the stamp is re-read under an
    exclusive lock and, only if it is still due, rewritten before the lock is
    released: the second command to get the lock finds a fresh stamp and posts
    nothing. A stamp that cannot be written
    raises, and then nothing is posted, since a heartbeat per command is what
    the stamp exists to prevent.
    """
    path = lock_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if not heartbeat_due(name, cfg):
            return False
        write_stamp(name, cfg)
        return True
    finally:
        os.close(fd)  # and with it the lock


def keep_alive(name, cfg=None):
    """Refresh `name`'s session issue if this machine has not done so in the
    last hour. Returns True when a heartbeat child was started.

    A fresh stamp is read without the lock and costs nothing more; only a due
    one goes on to claim the hour. The stamp moves on every ATTEMPT, before
    the child starts and whatever comes of it: a heartbeat that later fails
    leaves the stamp written, and the next one comes an hour later, not
    sooner. A heartbeat that failed because GitHub is rate limiting would
    otherwise be retried by every later command, each costing an issue listing,
    which is the opposite of what a rate limit asks for; one missed heartbeat
    still leaves two hours before the session reads as stale.
    """
    try:
        cfg = cfg or load_config()
        if not heartbeat_due(name, cfg) or not claim_hour(name, cfg):
            return False
        start_child(name)
        return True
    except (Exception, SystemExit) as error:
        # Only the lock, the stamp or starting the child can fail here, and
        # none should; what GitHub does is the child's business and never
        # reaches this.
        reason = (" ".join(str(error).split()).removeprefix("hq: ")[:200]
                  or type(error).__name__)
        print(f"hq: note - could not refresh the presence of '{name}' ({reason}); "
              "carrying on", file=sys.stderr)
        return False


def child_argv(name):
    return [sys.executable, "-m", "hq.cli", CHILD_COMMAND, name]


def start_child(name):
    """Start `hq _heartbeat NAME` detached and return without waiting for it.

    Its own session, so a terminal's Ctrl-C or hangup aimed at the command does
    not reach it; stdin, stdout and stderr on /dev/null, so it never writes
    into the command's output or holds a pipe the caller is reading to EOF.
    The package's own directory goes first on PYTHONPATH: the clone wrapper
    `bin/hq` runs hq uninstalled, and the child must import the same copy.
    """
    env = dict(os.environ)
    package_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(
        [package_root] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    subprocess.Popen(child_argv(name), env=env, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True)


def post_heartbeat(name, cfg=None):
    """The child's work: comment on `name`'s open session issue. No session
    issue means nothing is posted. Swallows every error, since nobody is
    listening: returns True when a heartbeat was posted."""
    try:
        cfg = cfg or load_config()
        repo = require_repo(cfg)
        # The title `hq hello` gives the issue, whatever case HQ_AGENT was typed in.
        number = find_issue(f"session: {slug(name).lower()}")
        if not number:
            return False
        gh(["issue", "comment", str(number), "--repo", repo,
            "--body", heartbeat_body("active")])
        return True
    except (Exception, SystemExit):
        # `gh` reports its failures as SystemExit. The stamp is already written,
        # so the next attempt for this name comes an hour later, not sooner.
        return False


def child_main(argv):
    """`hq _heartbeat NAME`: post one heartbeat, print nothing, exit 0."""
    if len(argv) == 1:
        post_heartbeat(argv[0])
    return 0
