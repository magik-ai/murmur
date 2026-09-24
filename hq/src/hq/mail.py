"""Messages: one issue per mailbox, one comment per message, a local cursor."""

import json
from datetime import timedelta

from .config import load_config, require_repo
from .github import ensure_issue, find_issue, gh, gh_json
from .identity import require_identity
from .util import iso, now, slug


def cmd_msg(args):
    repo = require_repo()
    me = require_identity()
    target = slug(args.name).lower()
    number = ensure_issue(f"inbox: {target}", "inbox", f"Mailbox for {target}.")
    gh(["issue", "comment", str(number), "--repo", repo,
        "--body", f"**from {me}** ({iso(now())}):\n{args.text}"])
    print(f"sent to {target} (inbox issue #{number})")


FIRST_READ_WINDOW_HOURS = 24
INBOX_BYTE_CAP = 40000


def cmd_inbox(args):
    cfg = load_config()
    repo = require_repo(cfg)
    me = require_identity()
    lastread = {}
    if cfg.lastread_file.exists():
        lastread = json.loads(cfg.lastread_file.read_text() or "{}")
    # A name nobody has read as before is a NEW session, and it has no backlog to catch up on.
    # An unbounded `since` would hand it every broadcast ever sent, which can be more than a
    # spawner can paste into one prompt. Yesterday's announcements are context, not orders.
    default_since = iso(now() - timedelta(hours=FIRST_READ_WINDOW_HOURS))
    since = lastread.get(me) or default_since
    # The cursor is per NAME per machine and moves on every plain read: a watcher that
    # polls `hq inbox`, or a second call in the same step, consumes the mail for every
    # process signing as this name here. `--peek` reads without moving it; `--recent H`
    # re-shows the last H hours regardless of it; neither writes.
    peek = bool(getattr(args, "peek", False))
    recent_hours = getattr(args, "recent", None)
    if recent_hours is not None:
        since = iso(now() - timedelta(hours=float(recent_hours)))
        peek = True
    if getattr(args, "all", False):
        since = "1970-01-01T00:00:00Z"
    fresh = []
    for box in (me, "all"):
        number = find_issue(f"inbox: {box}")
        if not number:
            continue
        comments = gh_json(["issue", "view", str(number), "--repo", repo,
                            "--json", "comments"]).get("comments", [])
        fresh += [c for c in comments if c["createdAt"] > since]
    if not fresh:
        print(f"inbox empty (nothing after {since}; `hq inbox --recent 6` re-shows the "
              "last six hours without moving the cursor)")
    ordered = sorted(fresh, key=lambda c: c["createdAt"])
    # Newest mail is the mail that still changes what you do, so drop from the OLD end when the
    # office has been loud. Silent truncation would read as "you have no more mail".
    show_all = bool(getattr(args, "all", False))
    rendered, kept, budget = [], 0, (10 ** 9 if show_all else INBOX_BYTE_CAP)
    for comment in reversed(ordered):
        block = f"--- {comment['createdAt']}\n{comment['body']}\n"
        if budget - len(block.encode()) < 0 and rendered:
            break
        budget -= len(block.encode())
        rendered.append(block)
        kept += 1
    omitted = len(ordered) - kept
    if omitted > 0:
        print(f"[{omitted} older message(s) omitted to stay under {INBOX_BYTE_CAP} bytes - "
              f"'hq inbox --all' for the full history]\n")
    for block in reversed(rendered):
        print(block)
    if peek:
        if fresh:
            print(f"[peek: {kept} message(s) shown; the read cursor for '{me}' did not move]")
        return
    stamp = iso(now())
    lastread[me] = stamp
    cfg.state.mkdir(parents=True, exist_ok=True)
    cfg.lastread_file.write_text(json.dumps(lastread))
    if fresh:
        # Say out loud that this read consumed the mail: a second `hq inbox` in the same
        # step, or another process signing as this name on this machine, will now read
        # "inbox empty" for everything above.
        print(f"[read cursor for '{me}' on this machine advanced to {stamp}; "
              "`hq inbox --recent 6` re-shows recent mail without moving it]")
