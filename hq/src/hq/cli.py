"""The command line: argument parsing, `hq init`, `hq install`, dispatch.

`bin/hq` in a clone and the `hq` console script of the installed package both
end up in `main()` here, so a checkout and an installed copy behave the same.
"""

import argparse
import sys
from pathlib import Path

from . import presence
from .claims import cmd_check_push, cmd_claim, cmd_claims, cmd_release
from .config import (
    DEFAULTS,
    ConfigError,
    config_path,
    load_config,
    read_config_file,
    toml_string,
)
from .hook import cmd_hook
from .mail import cmd_inbox, cmd_msg
from .registry import cmd_bye, cmd_feed, cmd_hello, cmd_who, cmd_whoami

# How long a claim lives unless the claimer says otherwise.
DEFAULT_TTL_HOURS = 24

USAGE = """hq - names, branch claims and mail for coding agents that share one
GitHub login.

hq keeps its state in a GitHub repository you choose, the head office, so it
does not depend on any one machine being up. Claims are files on the office's
`claims` branch, and a git push decides who got there first. Sessions and mail
are GitHub issues, read and written with `gh`.

Point hq at your head office once with `hq init`. The environment variables
HQ_REPO, HQ_OWNER, HQ_BOT_NAME, HQ_BOT_EMAIL and HQ_HOME override the file.

Commands:
  hq init --repo O/N [--owner NAME]
                                   write the config file
  hq install                       link this clone's bin/hq into the bin dir
  hq hello NAME [--task T]         register this session and save its name
  hq bye                           end this session and close its issue
  hq who                           list live sessions
  hq whoami                        the name hq would sign with, and where it came
                                   from; exits 1 when that name is not this
                                   session's own. Run it before acting.
  hq claim BRANCH [--repo O/N] [--ttl H] [--note T]
                                   claim a branch (for 24 hours unless --ttl)
  hq release BRANCH [--repo O/N] [--force]
                                   give a claim back
  hq claims [--repo O/N]           list active claims
  hq feed [--hours H]              the whole office as one timeline (default 24h)
  hq msg NAME TEXT                 message an agent ('all' broadcasts)
  hq inbox [--peek] [--recent H] [--all]
                                   mail for this name; a plain read moves the
                                   read cursor, --peek and --recent never do
  hq hook DIR [--force]            install the pre-push guard in the clone at DIR
                                   (--force replaces a hook hq did not write)
  hq check-push REPO BRANCH        used by the hook; exit 1 = blocked

Run `hq COMMAND --help` for the options of one command.
"""


def from_argv(value):
    """Text typed on the command line, as UTF-8, whatever the locale was.

    Under a non-UTF-8 locale python decodes argv with the surrogateescape error
    handler, so any byte the locale cannot spell arrives as a lone surrogate:
    `--owner Jose\u0301` typed on a UTF-8 terminal reaches `hq init` as a pair of
    surrogates rather than a character. Those are not text, they are the
    original bytes in disguise, so they go back to bytes and are read as UTF-8 -
    which is what the terminal sent, and what the config file stores.

    Input that is genuinely not UTF-8 keeps its escapes, and the round-trip
    check below refuses it in one line rather than writing a config file hq
    cannot read.
    """
    try:
        return value.encode("utf-8", "surrogateescape").decode("utf-8")
    except UnicodeDecodeError:
        return value


def remove(path):
    """Delete a config file hq has decided not to keep, and never fail doing it.

    A config file hq wrote but cannot read is worse than no config file: every
    later command stops on it, and `hq init` itself refuses to overwrite a file
    that exists. So the failure paths clean up after themselves - and a failure
    to clean up is not worth a traceback of its own.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def verify_written(path, values):
    """Read the file back through the parser every other command uses.

    Escaping is only half the promise. `hq init` is the last moment anyone is
    watching, so it proves the round-trip instead of assuming it: a config file
    hq cannot read is worse than no config file at all.
    """
    try:
        written = read_config_file(path)
    except ConfigError as error:
        remove(path)
        sys.exit(f"hq: wrote a config file hq cannot read back ({error}); "
                 "removed it, nothing was configured")
    wrong = sorted(key for key, value in values.items() if written.get(key) != value)
    if wrong:
        remove(path)
        sys.exit(f"hq: the config file did not round-trip ({', '.join(wrong)}); "
                 "removed it, nothing was configured")


def cmd_init(args):
    """Write the config file. This is the one command that needs no config."""
    path = config_path()
    if path.exists() and not args.force:
        sys.exit(f"hq: {path} already exists - edit it, or pass --force to overwrite")
    if "/" not in args.repo:
        sys.exit(f"hq: --repo wants owner/name, got {args.repo!r}")
    values = {
        "repo": from_argv(args.repo),
        "owner": from_argv(args.owner or ""),
        "bot_name": from_argv(args.bot_name or DEFAULTS["bot_name"]),
        "bot_email": from_argv(args.bot_email or DEFAULTS["bot_email"]),
    }
    if args.home:
        values["home"] = from_argv(args.home)
    # Every value goes through `toml_string`: a quote or a backslash in what the
    # user typed must not be able to produce a file hq cannot read.
    lines = [
        "# hq configuration. The environment variables HQ_REPO, HQ_OWNER,",
        "# HQ_BOT_NAME, HQ_BOT_EMAIL and HQ_HOME override repo, owner, bot_name,",
        "# bot_email and home.",
        "",
        f"repo = {toml_string(values['repo'])}",
        f"owner = {toml_string(values['owner'])}"
        "  # may push to claimed branches and release any claim; empty means nobody",
        f"bot_name = {toml_string(values['bot_name'])}",
        f"bot_email = {toml_string(values['bot_email'])}",
    ]
    if "home" in values:
        lines.append(f"home = {toml_string(values['home'])}")
    lines += [
        "# home = \"~/.agent-hq\"          # state and cache clone",
        "# bin_dir = \"~/.local/bin\"      # where `hq install` links the CLI",
        '# clone_url_template = "https://github.com/{repo}.git"',
        "",
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # UTF-8 explicitly, never the machine's locale encoding: under LC_ALL=C
        # `write_text` would encode as ASCII, so `hq init --bot-name Jose\u0301`
        # would die with a UnicodeEncodeError traceback and leave a zero-byte
        # config.toml that the next `hq init` refuses to overwrite.
        # `surrogateescape` puts bytes that arrived through argv back exactly as
        # they came in, so a name typed on a UTF-8 terminal survives a locale
        # that cannot spell it; anything that is genuinely not UTF-8 is caught
        # below by the round-trip.
        path.write_text("\n".join(lines), encoding="utf-8",
                        errors="surrogateescape")
    except (OSError, UnicodeError) as error:
        # One line, like every other failure here. A locked-down config
        # directory is an ordinary first-run accident, and a PermissionError
        # traceback tells the person setting up the machine nothing.
        remove(path)  # never leave a half-written config file behind
        sys.exit(f"hq: cannot write the config file {path} ({error}); "
                 "nothing was configured")
    verify_written(path, values)
    print(f"hq configured: {path}")
    print(f"  repo  {values['repo']}")
    print(f"  owner {values['owner'] or '(nobody)'}")


def clone_script():
    """`bin/hq` of the clone this code runs from, or None.

    None means hq is an installed package: there is no clone to link, and the
    installer already put an `hq` on PATH.
    """
    candidate = Path(__file__).resolve().parent.parent.parent / "bin" / "hq"
    return candidate if candidate.is_file() else None


def cmd_install(_):
    """Put an `hq` in the bin dir. Nothing here touches the head office.

    It links this clone's `bin/hq` and needs no configured repo at all. The
    head office holds claims and mailboxes, not a copy of hq, and its cache
    clone is made by the commands that read the office.
    """
    source = clone_script()
    if source is None:
        print("hq: nothing to link - this hq is an installed package, so the "
              "installer owns the `hq` command. To upgrade it, update the murmur "
              "clone it came from and run one of these in that clone's hq/ "
              "directory:")
        print("  uv tool install --reinstall --from . hq-cli")
        print("  pipx install --force .")
        return
    target = load_config().bin_dir / "hq"
    try:
        source.chmod(0o755)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target.is_symlink() and target.resolve() == source.resolve()):
            target.unlink(missing_ok=True)
            target.symlink_to(source)
    except OSError as error:
        # One line, never a traceback: this runs on machines being set up by a
        # script, and a stack trace there tells nobody what to do next.
        sys.exit(f"hq: cannot link {target} -> {source} ({error})")
    print(f"hq installed: {target} -> {source}")
    print("  upgrade with `git pull` in this clone; the symlink follows it")


def speak_utf8():
    """Print UTF-8 whatever the machine's locale says.

    hq prints names, branches and notes that were typed on somebody else's
    machine. Under a non-UTF-8 locale python encodes stdout as ASCII and raises
    on the first accented character, so `hq init --owner Jose\u0301` would
    write its config file correctly and then die with a traceback printing the
    summary, and an accented note in one claim could break `hq claims` for
    everybody. Mojibake in a terminal is a bad day; a traceback instead of the
    answer is a broken tool.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass  # a stream that cannot be reconfigured still prints ASCII


def parse_args(ap):
    """The command line, with one exception: a usage error in `check-push`.

    `argparse` answers a usage error with exit 2, and the pre-push hook reads
    ANY non-zero exit from `check-push` as a blocked push. So an argument the
    parser could not read would freeze the push instead of gating it, and a
    branch name is not hq's to choose: `refs/heads/-weird` is a legal ref, and
    a hook hands it over as `-weird`, which argparse reads as an option and
    rejects. hq's own hook passes `--`, so such a branch is CHECKED rather than
    waved through. But an older copy of the hook, or a hook another tool wrote,
    may leave the `--` out, and the gate has to be right when it is called
    wrongly: a gate that cannot read its own arguments knows nothing about any
    claim, and not knowing is never evidence of one.

    argparse has already printed the usage line, so the reason is on stderr
    above the warning.
    """
    try:
        return ap.parse_args()
    except SystemExit as stop:
        if stop.code in (0, None) or sys.argv[1:2] != ["check-push"]:
            raise
        print("hq: WARNING - the push check could not read its own arguments "
              f"({' '.join(sys.argv[1:])}); pushing unverified (fail-open)",
              file=sys.stderr)
        raise SystemExit(0) from None


def main():
    if sys.argv[1:2] == [presence.CHILD_COMMAND]:
        # The detached heartbeat child (see `presence.keep_alive`): handled
        # before argparse so it stays out of `hq --help`.
        raise SystemExit(presence.child_main(sys.argv[2:]))
    speak_utf8()
    ap = argparse.ArgumentParser(prog="hq", description=USAGE,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--repo", required=True, metavar="OWNER/NAME",
                   help="the head office repository")
    p.add_argument("--owner", metavar="NAME",
                   help="the name that may push to claimed branches and release any "
                        "claim; omit for nobody")
    p.add_argument("--bot-name", dest="bot_name", metavar="NAME",
                   help=f"author name of claims commits (default {DEFAULTS['bot_name']})")
    p.add_argument("--bot-email", dest="bot_email", metavar="EMAIL",
                   help=f"author email of claims commits (default {DEFAULTS['bot_email']})")
    p.add_argument("--home", metavar="DIR", help="state directory (default ~/.agent-hq)")
    p.add_argument("--force", action="store_true", help="overwrite an existing config file")
    sub.add_parser("install")
    p = sub.add_parser("hello"); p.add_argument("name")
    p.add_argument("--task", help="one line about what this session works on")
    sub.add_parser("bye")
    sub.add_parser("whoami")
    sub.add_parser("who")
    p = sub.add_parser("claim"); p.add_argument("branch")
    p.add_argument("--repo", metavar="OWNER/NAME",
                   help="the repository the branch is in (default: the origin remote)")
    p.add_argument("--ttl", type=float, default=DEFAULT_TTL_HOURS, metavar="HOURS",
                   help=f"how long the claim lasts (default {DEFAULT_TTL_HOURS})")
    p.add_argument("--note", help="shown next to the claim in `hq claims`")
    p = sub.add_parser("release"); p.add_argument("branch")
    p.add_argument("--repo", metavar="OWNER/NAME",
                   help="the repository the branch is in (default: the origin remote)")
    p.add_argument("--force", action="store_true",
                   help="release a claim that belongs to another agent")
    p = sub.add_parser("claims")
    p.add_argument("--repo", metavar="OWNER/NAME", help="only claims in this repository")
    p = sub.add_parser("feed")
    p.add_argument("--hours", type=float, default=24, help="how far back to look (default 24)")
    p = sub.add_parser("msg"); p.add_argument("name"); p.add_argument("text")
    p = sub.add_parser("inbox")
    p.add_argument("--peek", action="store_true",
                   help="show unread mail without moving the read cursor (for watchers)")
    p.add_argument("--recent", metavar="HOURS", type=float,
                   help="re-show the last HOURS of mail regardless of the cursor; never moves it")
    p.add_argument("--all", action="store_true",
        help="every message ever sent, with no size cap; moves the read cursor "
             "unless --peek or --recent is given too")
    p = sub.add_parser("hook")
    p.add_argument("dir", help="a clone or worktree; the guard covers the whole clone")
    p.add_argument("--force", action="store_true",
                   help="replace a pre-push hook hq did not write")
    p = sub.add_parser("check-push")
    p.add_argument("repo", help="remote URL or OWNER/NAME")
    p.add_argument("branch")
    args = parse_args(ap)
    {
        "init": cmd_init,
        "install": cmd_install, "hello": cmd_hello, "bye": cmd_bye, "who": cmd_who,
        "whoami": cmd_whoami,
        "claim": cmd_claim, "release": cmd_release, "claims": cmd_claims,
        "msg": cmd_msg, "inbox": cmd_inbox, "hook": cmd_hook, "feed": cmd_feed,
        "check-push": cmd_check_push,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
