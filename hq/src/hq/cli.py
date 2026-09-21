"""The command line: argument parsing, `hq init`, `hq install`, dispatch.

`bin/hq` in a clone and the `hq` console script of the installed package both
end up in `main()` here, so a checkout and an installed copy behave the same.
"""

import argparse
import sys
from pathlib import Path

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

USAGE = """hq - personal agent coordination CLI.

One CLI, installed identically on every machine, so coordination keeps working
when any one host is down: the head office is a GitHub repo, not a host. Claims
use plain git (push = compare-and-swap); registry and messages use GitHub
issues via `gh`.

Which head office, and who owns it, comes from a config file (see `hq init`),
never from the source: nothing in this package names one organisation.

Commands:
  hq init --repo O/N [--owner NAME]
                                   write the config file this CLI reads
  hq install                       symlink this clone's bin/hq into the bin dir
  hq hello NAME [--task T]         register this session (and set local identity)
  hq bye                           close this session's registry issue
  hq who                           list live sessions
  hq claim BRANCH [--repo O/N] [--ttl H] [--note T]
  hq release BRANCH [--repo O/N] [--force]
  hq whoami                        the name hq would sign with, and where it came
                                   from; exits 1 when that name is not this
                                   session's own. Run it before acting.
  hq claims [--repo O/N]           list active claims
  hq feed [--hours H]              the whole office as one timeline (default 24h)
  hq msg NAME TEXT                 message an agent ('all' broadcasts)
  hq inbox [--peek] [--recent H]   unread messages for this identity (--peek/--recent
                                   never move the read cursor: use them in watchers)
  hq hook DIR [--force]            install the pre-push guard into a worktree/repo
                                   (--force replaces a hook hq did not write)
  hq check-push REPO BRANCH        used by the hook; exit 1 = blocked
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
    hq cannot read is worse than no config file at all, and the old init exited
    0 on exactly that.
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
        "# hq configuration. Environment variables override every key here:",
        "# HQ_REPO, HQ_OWNER, HQ_BOT_NAME, HQ_BOT_EMAIL, HQ_HOME.",
        "",
        f"repo = {toml_string(values['repo'])}",
        f"owner = {toml_string(values['owner'])}"
        "  # sovereign; empty means nobody overrides a claim",
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
        # `write_text` encodes as ASCII, so `hq init --bot-name Jose\u0301` died
        # with a UnicodeEncodeError traceback and left a zero-byte config.toml
        # that the next `hq init` then refused to overwrite. `surrogateescape`
        # puts bytes that arrived through argv back exactly as they came in, so
        # a name typed on a UTF-8 terminal survives a locale that cannot spell
        # it; anything that is genuinely not UTF-8 is caught below by the
        # round-trip, which is the existing promise rather than a new one.
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
    print(f"  owner {values['owner'] or '(nobody is sovereign)'}")


def clone_script():
    """`bin/hq` of the clone this code runs from, or None.

    None means hq is an installed package: there is no clone to link, and the
    installer already put an `hq` on PATH.
    """
    candidate = Path(__file__).resolve().parent.parent.parent / "bin" / "hq"
    return candidate if candidate.is_file() else None


def cmd_install(_):
    """Put an `hq` in the bin dir. Nothing here touches the head office.

    It used to clone the head office into the cache and symlink
    `<cache>/bin/hq`, which assumed every head office repo was a copy of hq's
    own source: a head office that holds claims and mailboxes and nothing else
    produced a traceback on an install. The cache clone is now made lazily by
    the commands that read the office, and this command needs no configured
    repo at all.
    """
    source = clone_script()
    if source is None:
        print("hq: nothing to link - this hq is an installed package, so the "
              "installer owns the `hq` command. To install or upgrade:")
        print("  uv tool install --from . hq-cli     # in a clone of agent-hq")
        print("  pipx install .                      # the same, with pipx")
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
    on the first accented character, so `hq init --owner Jose\u0301` wrote its
    config file correctly and then died with a traceback printing the summary,
    and an accented note in one claim could break `hq claims` for everybody.
    Mojibake in a terminal is a bad day; a traceback instead of the answer is a
    broken tool.
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
    parser could not read froze the push instead of gating it, and a branch
    name is not hq's to choose: `refs/heads/-weird` is a legal ref, and the
    hook hands it over as `-weird`, which argparse reads as an option and
    rejects. The hook now passes `--` so such a branch is CHECKED rather than
    waved through, but hooks already installed in a hundred worktrees do not
    update themselves, and the gate has to be right when it is called wrongly:
    a gate that cannot read its own arguments knows nothing about any claim,
    and not knowing is never evidence of one.

    argparse has already printed the usage line, so the reason is on stderr
    above the warning.
    """
    try:
        return ap.parse_args()
    except SystemExit as stop:
        if stop.code in (0, None) or sys.argv[1:2] != ["check-push"]:
            raise
        print("hq: WARNING - the push gate could not read its own arguments "
              f"({' '.join(sys.argv[1:])}); pushing unverified (fail-open)",
              file=sys.stderr)
        raise SystemExit(0) from None


def main():
    speak_utf8()
    ap = argparse.ArgumentParser(prog="hq", description=USAGE,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="write the config file")
    p.add_argument("--repo", required=True, metavar="OWNER/NAME")
    p.add_argument("--owner", help="the sovereign; omit if nobody is")
    p.add_argument("--bot-name", dest="bot_name")
    p.add_argument("--bot-email", dest="bot_email")
    p.add_argument("--home", help="state directory (default ~/.agent-hq)")
    p.add_argument("--force", action="store_true")
    sub.add_parser("install")
    p = sub.add_parser("hello"); p.add_argument("name"); p.add_argument("--task")
    sub.add_parser("bye")
    sub.add_parser("whoami")
    sub.add_parser("who")
    p = sub.add_parser("claim"); p.add_argument("branch"); p.add_argument("--repo")
    p.add_argument("--ttl", type=float, default=DEFAULT_TTL_HOURS, metavar="HOURS")
    p.add_argument("--note")
    p = sub.add_parser("release"); p.add_argument("branch"); p.add_argument("--repo")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("claims"); p.add_argument("--repo")
    p = sub.add_parser("feed"); p.add_argument("--hours", type=float, default=24)
    p = sub.add_parser("msg"); p.add_argument("name"); p.add_argument("text")
    p = sub.add_parser("inbox")
    p.add_argument("--peek", action="store_true",
                   help="show unread mail without moving the read cursor (for watchers)")
    p.add_argument("--recent", metavar="HOURS", type=float,
                   help="re-show the last HOURS of mail regardless of the cursor; never moves it")
    p.add_argument("--all", action="store_true",
        help="every message ever sent, not just what is still actionable")
    p = sub.add_parser("hook"); p.add_argument("dir")
    p.add_argument("--force", action="store_true",
                   help="replace a pre-push hook hq did not write")
    p = sub.add_parser("check-push"); p.add_argument("repo"); p.add_argument("branch")
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
