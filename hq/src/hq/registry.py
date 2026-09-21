"""The session registry: who is live, who says hello, who says bye."""

import getpass
import re
import socket
import sys
from datetime import datetime, timedelta

from .claims import fetch_claims
from .config import load_config, require_repo
from .github import ensure_issue, find_issue, gh, gh_json
from .identity import (
    SESSION_SCOPED_SOURCES,
    SESSION_VARIABLES,
    identity_source,
    session_key,
    session_key_source,
    shared_identity_owner,
)
from .util import iso, now, run, slug

# A session that has not heartbeated in this long is shown as stale, not live.
STALE_SESSION_HOURS = 3


def cmd_hello(args):
    cfg = load_config()
    repo = require_repo(cfg)
    name = slug(args.name).lower()
    cfg.state.mkdir(parents=True, exist_ok=True)
    key = session_key()
    previous = cfg.identity_file.read_text().strip() if cfg.identity_file.exists() else ""
    if key:
        # This session's own name. Nothing another session does can move it, so
        # the rename below can no longer put someone else's signature on your work.
        cfg.session_dir.mkdir(parents=True, exist_ok=True)
        (cfg.session_dir / key).write_text(name + "\n")
    elif previous and previous != name:
        print(f"hq: note - this machine's identity file was '{previous}' and is now "
              f"'{name}'. This session exports no session id, so the file is all hq "
              f"has: with several live sessions on one machine, ALWAYS prefix "
              f"commands with HQ_AGENT={name}", file=sys.stderr)
    cfg.identity_file.write_text(name + "\n")
    cfg.identity_owner_file.write_text((key or "") + "\n")
    existing = find_issue(f"session: {name}")
    if existing:
        info = gh_json(["issue", "view", str(existing), "--repo", repo,
                        "--json", "updatedAt"])
        updated = datetime.fromisoformat(info["updatedAt"].replace("Z", "+00:00"))
        age_h = (now() - updated).total_seconds() / 3600
        if age_h < STALE_SESSION_HOURS:
            print(f"hq: WARNING - a session named '{name}' was live {age_h * 60:.0f} "
                  f"minutes ago. If that was not you, you are taking another agent's "
                  f"name (did it come from shared project memory?) - stop and ask "
                  f"the owner for YOUR codename.", file=sys.stderr)
    body = (f"machine: {socket.gethostname()} ({getpass.getuser()})\n"
            f"task: {args.task or '-'}\nstarted: {iso(now())}")
    number = ensure_issue(f"session: {name}", "session", body)
    gh(["issue", "comment", str(number), "--repo", repo,
        "--body", f"heartbeat {iso(now())} - {args.task or 'session start'}"])
    scope = f"session {key}" if key else "this machine (no session id available)"
    print(f"hello {name}: session #{number} registered; identity saved for {scope}")


def clear_local_identity(cfg, name):
    """Remove every local file that would still answer "you are `name`". True
    when something was removed.

    The session file is the easy half. The machine-wide file is the half that
    was missed: `hq hello` writes BOTH, so a bye that removed only the session
    file left a file that still named this agent, and `hq whoami` went on
    answering with it after the session had said goodbye. `require_identity`
    refuses to act on a machine file, so nothing was signed wrongly, but a
    goodbye that reports "identity cleared on this machine" has to be telling
    the truth.

    Only this session's own name is removed. The machine-wide file is shared
    state: when it holds another name, or was written by another session, it is
    that agent's to clear, not this one's.

    "Written by another session" includes a file with no recorded owner at all.
    A session that exports no session id writes one, and that session is not
    this one unless this one is keyless too: a session WITH a key would have
    recorded it when it said hello. So an unowned file may only be cleared by a
    keyless session, which is exactly the hello it undoes.
    """
    removed = False
    key = session_key()
    if key:
        mine = cfg.session_dir / key
        if mine.exists():
            mine.unlink()
            removed = True
    owner = shared_identity_owner(cfg)
    if (cfg.identity_file.exists()
            and cfg.identity_file.read_text().strip() == name
            and (owner or None) == (key or None)):
        cfg.identity_file.unlink()
        cfg.identity_owner_file.unlink(missing_ok=True)
        removed = True
    return removed


def cmd_bye(_):
    # `strict=False` for the same reason the local cleanup comes first: a config
    # file hq cannot read used to stop `hq bye` before it removed anything, and
    # every later `hq bye` stopped in exactly the same place, so the name lived
    # on that machine until somebody fixed the file by hand. The local half
    # needs no value out of that file: where the state dir is comes from HQ_HOME
    # or the default, and removing a local file signs nothing. The office half
    # cannot run without a repo, so the config problem is the exit below.
    cfg = load_config(strict=False)
    # Local cleanup FIRST, before ANYTHING that can stop the command - and the
    # name it works on is the one hq resolves, not the narrower one hq may sign
    # with. Two requirements used to come first and each left the identity on
    # disk: the head office repo (an unconfigured machine, or one whose `gh` was
    # down, said bye and kept the file), and `require_identity`, which refuses a
    # name from shared state. The second one locked a whole kind of machine out:
    # a session that exports no session id has nowhere to write but the shared
    # machine file, `hq hello` supports that and warns about it, and then every
    # `hq bye` there hit the refusal before the cleanup, so the name could never
    # be removed at all. Clearing a local file signs nothing, so it does not
    # need a name hq may act under - only a name that is this session's to take,
    # which `clear_local_identity` decides file by file.
    name, source = identity_source(cfg)
    cleared = clear_local_identity(cfg, name) if name else False
    # Say what the local half did, or the one-line exits below read as "hq bye
    # did nothing". Only claim what actually happened: a bye that found nothing
    # of its own to remove must not report a cleanup.
    report = (f"bye {name}: identity cleared on this machine" if cleared
              else f"bye {name or 'this session'}: nothing of this session was "
                   "left on this machine")
    if cfg.error or not cfg.repo or source not in SESSION_SCOPED_SOURCES:
        print(report, file=sys.stderr)
    if cfg.error:
        # One line, and honest about which half did not happen. The state dir
        # was resolved without that file, so say where the cleanup looked.
        sys.exit(f"hq: {cfg.error}; the local cleanup above used {cfg.state}, "
                 "and no registry issue was closed - fix the config file and "
                 "run `hq bye` again")
    repo = require_repo(cfg)
    if source not in SESSION_SCOPED_SOURCES:
        # The office half DOES write under a name, so it keeps the full rule.
        # Saying `no identity` here would be about the file this command just
        # removed itself; say what is still open instead, and how to close it.
        if not name:
            sys.exit("hq: no identity - run `hq hello <name>` first (or set HQ_AGENT)")
        sys.exit(
            f"hq: the registry issue for '{name}' was NOT closed: that name comes "
            f"from the {source}, which every session on this machine shares, so hq "
            f"will not close an issue with it. Finish with: HQ_AGENT={name} hq bye"
        )
    try:
        number = find_issue(f"session: {name}")
        if number:
            gh(["issue", "close", str(number), "--repo", repo,
                "--comment", f"bye {iso(now())}"])
    except SystemExit:
        # Say what the local half did here too. The exit line below is about the
        # office alone, so on its own it reads as a `hq bye` that did nothing,
        # and the obvious answer to that is to run it again.
        print(report, file=sys.stderr)
        # The local cleanup already happened - that is the whole point of doing
        # it first - so this session no longer has a name to resolve, and a
        # plain `hq bye` on the retry would exit with `no identity` about the
        # file this command removed itself. The issue would then stay open with
        # nobody able to close it. Hand back the one command that finishes the
        # job, while the name is still on screen.
        if cleared:
            print(f"hq: the local identity was cleared before this failure, so a "
                  f"plain `hq bye` can no longer name this session. Once the "
                  f"problem above is fixed, close the registry issue with: "
                  f"HQ_AGENT={name} hq bye", file=sys.stderr)
        raise
    print(f"bye {name}")


def cmd_whoami(_):
    """Answer 'who does hq think I am, and why' before anything is signed with it.

    Cheap, offline, and the one step that turns a silent mis-attribution into a
    visible one: run it before any action that writes under a name, on the farm or in
    the office."""
    name, source = identity_source()
    key, variable = session_key_source()
    where = (f"session {key} from {variable}" if key
             else "no session key: this process sets none of "
                  + ", ".join(SESSION_VARIABLES))
    if not name:
        print(f"whoami: no identity ({where})")
        print("  run `hq hello <your-name>` in THIS session, or set HQ_AGENT")
        sys.exit(1)
    scoped = source in SESSION_SCOPED_SOURCES
    print(f"whoami: {name}  (source: {source}; {where})")
    if key and variable != "HQ_SESSION_ID":
        print(f"  note: the session key comes from {variable}, a fallback hq does not"
              " control.")
        print("  A spawner should export HQ_SESSION_ID so this session keeps its own name.")
    if not scoped:
        print(f"  WARNING: the {source} is shared with every session on this machine,")
        print("  so hq will refuse to act under this name. Run `hq hello <your-name>`")
        print("  in THIS session, or prefix commands with HQ_AGENT=<your-name>.")
        sys.exit(1)


def cmd_who(_):
    items = gh_json(["issue", "list", "--repo", require_repo(), "--state", "open",
                     "--label", "session", "--json", "title,updatedAt,body"])
    if not items:
        print("no live sessions")
        return
    for item in sorted(items, key=lambda i: i["updatedAt"], reverse=True):
        updated = datetime.fromisoformat(item["updatedAt"].replace("Z", "+00:00"))
        age_h = (now() - updated).total_seconds() / 3600
        mark = "STALE" if age_h > STALE_SESSION_HOURS else "live"
        first = (item.get("body") or "").splitlines()[:1]
        print(f"{item['title'][9:]:18} {mark:5} updated {age_h:4.1f}h ago  {first[0] if first else ''}")


def cmd_feed(args):
    """One human timeline of the whole office: messages, claims, sessions.
    Built for the owner - ask any agent to run it, or run it yourself; no
    channels to watch, no links to chase."""
    cfg = load_config()
    repo = require_repo(cfg)
    since = now() - timedelta(hours=args.hours)
    events = []

    # Mail: every comment across every inbox issue.
    boxes = gh_json(["issue", "list", "--repo", repo, "--state", "all",
                     "--label", "inbox", "--limit", "100", "--json", "number,title"])
    for box in boxes:
        target = box["title"].removeprefix("inbox: ")
        comments = gh_json(["issue", "view", str(box["number"]), "--repo", repo,
                            "--json", "comments"]).get("comments", [])
        for c in comments:
            when = datetime.fromisoformat(c["createdAt"].replace("Z", "+00:00"))
            if when < since:
                continue
            body = c["body"]
            m = re.match(r"\*\*from ([^*]+)\*\* \([^)]*\):\n?", body)
            sender = m.group(1).strip() if m else "?"
            text = body[m.end():].strip() if m else body.strip()
            text = " ".join(text.split())
            events.append((when, f"[mail] {sender} -> {target}: {text}"))

    # Claims: the claims branch commit log IS the ledger.
    if fetch_claims(strict=False, cfg=cfg):
        log = run(["git", "log", "--format=%aI\t%s", "origin/claims"],
                  cwd=cfg.cache, check=False).stdout
        for line in log.splitlines():
            stamp, _, subject = line.partition("\t")
            try:
                when = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if when >= since:
                events.append((when, f"[claim] {subject}"))

    # Sessions: registry issues with fresh heartbeats.
    for item in gh_json(["issue", "list", "--repo", repo, "--state", "all",
                         "--label", "session", "--limit", "100",
                         "--json", "title,state,updatedAt"]):
        when = datetime.fromisoformat(item["updatedAt"].replace("Z", "+00:00"))
        if when < since:
            continue
        state = "left" if item["state"].lower() == "closed" else "active"
        events.append((when, f"[session] {item['title'].removeprefix('session: ')} {state}"))

    if not events:
        print(f"office quiet for the last {args.hours:g}h")
        return
    for when, line in sorted(events):
        print(f"{when.astimezone().strftime('%d %b %H:%M')}  {line}")
