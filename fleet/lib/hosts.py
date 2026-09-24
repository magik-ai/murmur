#!/usr/bin/env python3
"""The hosting providers this farm can reach: is the CLI there, and is it logged in.

Reading only. The design record is `fleet/docs/design/hosting.md`, sections 3 and 7.

  fleet hosts list [--json]
  fleet hosts check <provider> [--json]

Two rules:

  A login is made by the provider's own CLI, in a terminal, by the person. This file only
  looks: it runs the preset's read-only whoami and says what it saw. Nothing here logs in,
  and nothing here takes a credential through a page or a chat.

  A slow provider is not a logged out provider. A whoami that does not answer in 15 seconds is
  `no_answer`, never `logged_out`, because a person who reads "not logged in" will go and log
  in again, and the third time they will paste a token somewhere they should not.

What a provider CLI prints is scrubbed before it can reach a log or a job record.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import host_presets  # noqa: E402

try:                                                    # the plugin may carry two files, not three
    import scrub as _scrub
except ImportError:                                     # pragma: no cover
    _scrub = None

STATE = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))

# Section 7 gives a provider check 15 seconds of its own, inside the refresher's 60. A farm on
# a slow link, and this repository's tests, may say otherwise with FLEET_WHOAMI_TIMEOUT.
WHOAMI_TIMEOUT = int(os.environ.get("FLEET_WHOAMI_TIMEOUT") or 15)
LOGGED_IN, LOGGED_OUT, NOT_INSTALLED, NO_ANSWER = (
    "logged_in", "logged_out", "not_installed", "no_answer")


class Refused(Exception):
    """Something a person can fix, said in one sentence."""


def clean(text):
    if _scrub is None:
        return text or ""
    try:
        return _scrub.scrub(text or "", _scrub.stored_secrets(STATE))
    except Exception:                                   # pragma: no cover - best effort
        return text or ""


def one_line(text, limit=200):
    flat = " ".join(clean(text).split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------------------- the check

def run(argv, timeout=WHOAMI_TIMEOUT):
    """(code, stdout, stderr). A missing binary is 127 and a timeout is 124; nothing raises."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout or "", done.stderr or ""
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not installed on this farm"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]}: no answer in {timeout} seconds"
    except OSError as error:                            # pragma: no cover - a broken PATH entry
        return 127, "", f"{argv[0]}: {error.strerror}"


def whoami_argv(preset):
    """The read-only check, with this farm's own doctl context in place of the shipped one.

    A farm that keeps its DigitalOcean login in doctl's default context sets
    FLEET_DOCTL_CONTEXT to nothing, and then the flag goes away entirely.
    """
    context = os.environ.get("FLEET_DOCTL_CONTEXT", host_presets.DOCTL_CONTEXT)
    argv, skip = [], False
    for word in preset["whoami"]:
        if skip:
            skip = False
            continue
        if word == "--context":
            if not context:
                skip = True                             # drop the flag and its value
                continue
            argv += ["--context", context]
            skip = True
            continue
        argv.append(word)
    return argv


def account_of(preset, output):
    """The account a provider names in its own JSON, or None where it documents none."""
    try:
        parsed = json.loads(output or "")
    except ValueError:
        return None
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    if not isinstance(parsed, dict):
        return None
    if "account" in preset["whoami"] and "get" in preset["whoami"]:
        return parsed.get("email") or None
    return None


def check(preset):
    """(login_state, account, detail, checked_at). The one place a provider is asked anything."""
    argv = whoami_argv(preset)
    if "{target}" in " ".join(argv):
        # There is nothing to log in to: ssh uses the person's own key, one machine at a time,
        # and `fleet machines check` is what asks whether a given machine answers.
        if not shutil.which(preset["cli"]):
            return NOT_INSTALLED, None, "ssh is not on this farm's PATH", now()
        return (LOGGED_IN, None,
                "no login: ssh uses your own key, and a machine is checked by "
                "`fleet machines check`", now())

    if not shutil.which(preset["cli"]):
        return NOT_INSTALLED, None, f"{preset['cli']} is not on this farm's PATH", now()

    code, out, err = run(argv)
    if code == 124:
        return NO_ANSWER, None, one_line(err), now()
    if code == 127:
        return NOT_INSTALLED, None, one_line(err), now()
    if code != 0 and "unknown command" in (err + " " + out).lower():
        # The CLI is there and is too old for this provider: logging in again would not help,
        # and a person told "not logged in" would try exactly that.
        return (NOT_INSTALLED, None,
                f"this {preset['cli']} has no `{' '.join(argv[1:2])}` command: install a "
                f"{preset['cli']} that has it", now())
    if code != 0:
        return LOGGED_OUT, None, one_line(err or out) or "the CLI has no credentials", now()
    account = account_of(preset, out)
    return LOGGED_IN, account, (f"logged in as {account}" if account else "logged in"), now()


def row(preset):
    """One provider as GET /api/hosts draws it (design record, section 7)."""
    state, account, detail, checked = check(preset)
    return {
        "id": preset["id"],
        "label": preset["label"],
        "summary": preset["summary"],
        "color": preset["color"],
        "job": preset["job"],
        "stage": preset["stage"],
        "cli": preset["cli"],
        "cli_installed": bool(shutil.which(preset["cli"])),
        "login_state": state,
        "account": account,
        "detail": detail,
        "checked_at": checked,
        "login": preset["login"],
        "install": preset["install"],
        "terms": preset["terms"],
        "pricing": preset["pricing"],
        "sizes": preset["sizes"],
        "regions": preset["regions"],
        "engines": preset["engines"],
        "docs": preset["docs"],
    }


def rows(presets):
    """Every provider, checked at the same time.

    The dashboard's refresher gives `fleet hosts list --json` 60 seconds and each check inside
    it 15, so providers asked one after the other might not fit. They are asked together.
    """
    if len(presets) == 1:
        return [row(presets[0])]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(presets)) as pool:
        return list(pool.map(row, presets))


# ------------------------------------------------------------------------------- the commands

def cmd_list(args):
    answer = {"providers": rows(host_presets.presets())}
    if args.json:
        print(json.dumps(answer, indent=2))
        return 0
    for provider in answer["providers"]:
        print(f"{provider['id']:<11} {provider['job']:<8} {provider['login_state']:<14} "
              f"{provider['detail']}")
    return 0


def cmd_check(args):
    preset = host_presets.preset(args.provider)
    if not preset:
        raise Refused(f"{args.provider} is not a provider this farm knows: "
                      + ", ".join(p["id"] for p in host_presets.presets()))
    answer = row(preset)
    if args.json:
        print(json.dumps(answer, indent=2))
        return 0
    print(f"{answer['id']}: {answer['login_state']}, {answer['detail']}")
    if answer["login_state"] == NOT_INSTALLED:
        print(f"install it:  {answer['install']}")
    if answer["login_state"] == LOGGED_OUT:
        print(f"log in:      {answer['login']}")
    return 0


def parser():
    ap = argparse.ArgumentParser(prog="fleet hosts", description=__doc__.splitlines()[0])
    subs = ap.add_subparsers(dest="command", required=True)

    listing = subs.add_parser("list", help="every provider: CLI and login")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(run=cmd_list)

    checking = subs.add_parser("check", help="ask one provider now")
    checking.add_argument("provider")
    checking.add_argument("--json", action="store_true")
    checking.set_defaults(run=cmd_check)
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return args.run(args)
    except Refused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:                           # pragma: no cover
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
