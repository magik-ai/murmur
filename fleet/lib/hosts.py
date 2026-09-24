#!/usr/bin/env python3
"""The hosting providers this farm can reach: is the CLI there, is it logged in, are its secrets.

Reading only, and one writing command that never prints what it writes. The design record is
`fleet/docs/design/hosting.md`, sections 3 and 7.

  fleet hosts list [--json]
  fleet hosts check <provider> [--json]
  fleet hosts secret <provider> <NAME> [--account LABEL]      # the value on stdin, never argv

Three rules:

  A login is made by the provider's own CLI, in a terminal, by the person. This file only
  looks: it runs the preset's read-only whoami and says what it saw. Nothing here logs in,
  and nothing here takes a credential through a page or a chat.

  A slow provider is not a logged out provider. A whoami that does not answer in 15 seconds is
  `no_answer`, never `logged_out`, because a person who reads "not logged in" will go and log
  in again, and the third time they will paste a token somewhere they should not.

  A secret is read from stdin, written to a 0600 file in a 0700 directory, and never echoed,
  never put on an argv, never named in an error. What a provider CLI prints is scrubbed before
  it can reach a log or a job record.
"""
import argparse
import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import host_presets  # noqa: E402

try:                                                    # the plugin may carry two files, not three
    import scrub as _scrub
except ImportError:                                     # pragma: no cover
    _scrub = None

STATE = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))
SECRETS = os.path.join(STATE, "secrets", "hosts")
TESTED = os.path.join(STATE, "hosts")

# Section 7 gives a provider check 15 seconds of its own, inside the refresher's 60. A farm on
# a slow link, and this repository's tests, may say otherwise with FLEET_WHOAMI_TIMEOUT.
WHOAMI_TIMEOUT = int(os.environ.get("FLEET_WHOAMI_TIMEOUT") or 15)
# The build a provider's check needs, where a released CLI may predate it (the research pass,
# internal/research/report-hosting-cli.md).
BUILD_NEEDED = {
    "do-agents": ("the harness-runtime commands merged into doctl on 2026-09-22 and a released "
                  "build may not carry them yet; install a doctl built after that day"),
}
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


# ------------------------------------------------------------------------------------ secrets

def secret_path(provider, name):
    return os.path.join(SECRETS, provider, name)


def accounts_path(provider):
    """Which subscription each secret belongs to. Not a secret, so it lives outside secrets/:
    everything under secrets/ is a value the scrub hunts for, and a label there would be
    redacted from the very sentences that are meant to show it."""
    return os.path.join(TESTED, provider, "accounts.json")


def account_labels(provider):
    try:
        with open(accounts_path(provider), encoding="utf-8") as handle:
            labels = json.load(handle)
    except (OSError, ValueError):
        return {}
    return labels if isinstance(labels, dict) else {}


def secret_rows(preset):
    """What the page draws: one row per secret the provider needs, stored or not."""
    rows = []
    labels = account_labels(preset["id"])
    for name in preset["secrets"]:
        path = secret_path(preset["id"], name)
        stored = False
        try:
            stored = os.path.getsize(path) > 0
        except OSError:
            stored = False
        rows.append({"name": name, "stored": stored, "account": str(labels.get(name) or "")})
    return rows


@contextlib.contextmanager
def accounts_locked(provider):
    """An flock on accounts.json.lock, held around the read-modify-write of the labels."""
    os.makedirs(os.path.dirname(accounts_path(provider)), exist_ok=True)
    handle = os.open(accounts_path(provider) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def store_secret(provider, name, value, label):
    """0600 in a 0700 directory, the label in accounts.json. The value is never printed."""
    folder = os.path.join(SECRETS, provider)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    for walk in (os.path.dirname(SECRETS), SECRETS, folder):    # every level: a rename needs
                                                                # only write on the parent
        try:
            os.chmod(walk, 0o700)
        except OSError:                                 # pragma: no cover - someone else's file
            pass
    path = os.path.join(folder, name)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        out.write(value)
    os.chmod(path, 0o600)
    with accounts_locked(provider):                    # two stores at once keep both labels
        labels = account_labels(provider)
        if label:
            labels[name] = label
        else:
            labels.pop(name, None)
        handle, tmp = tempfile.mkstemp(dir=os.path.dirname(accounts_path(provider)),
                                       prefix="accounts.", suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(labels, out, indent=2, sort_keys=True)
        os.replace(tmp, accounts_path(provider))


def tested(provider):
    """The last Test on this farm, written by the runners lane, or None."""
    path = os.path.join(TESTED, provider, "tested.json")
    try:
        with open(path, encoding="utf-8") as handle:
            answer = json.load(handle)
    except (OSError, ValueError):
        return None
    return answer if isinstance(answer, dict) else None


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
    if preset["cli"] == "railway":
        return parsed.get("email") or parsed.get("name") or None
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
        needed = BUILD_NEEDED.get(preset["id"], f"a {preset['cli']} that has this command")
        return (NOT_INSTALLED, None,
                f"this {preset['cli']} has no `{' '.join(argv[1:2])}` command: {needed}", now())
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
        "secrets": secret_rows(preset),
        "tested": tested(preset["id"]),
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
    it 15, so five providers asked one after the other could not fit. They are asked together.
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
        stored = sum(1 for secret in provider["secrets"] if secret["stored"])
        print(f"{provider['id']:<11} {provider['job']:<8} {provider['login_state']:<14} "
              f"secrets {stored}/{len(provider['secrets'])}  {provider['detail']}")
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
    for secret in answer["secrets"]:
        mark = "stored" if secret["stored"] else "not stored"
        label = f" ({secret['account']})" if secret["account"] else ""
        print(f"secret       {secret['name']}: {mark}{label}")
    return 0


def cmd_secret(args):
    preset = host_presets.preset(args.provider)
    if not preset:
        raise Refused(f"{args.provider} is not a provider this farm knows")
    if args.name not in preset["secrets"]:
        wanted = ", ".join(preset["secrets"]) or "no secrets at all"
        raise Refused(f"{preset['label']} needs {wanted}, not {args.name}")
    if sys.stdin.isatty():
        raise Refused("the value is read from stdin, so it never reaches an argv or your "
                      f"shell history: printf %s \"$TOKEN\" | fleet hosts secret "
                      f"{args.provider} {args.name}")
    value = sys.stdin.read().strip()
    if not value:
        raise Refused(f"nothing arrived on stdin, so {args.name} was not stored")
    if args.account and not args.account.replace("-", "").replace("_", "").replace(
            " ", "").isalnum():
        raise Refused("--account is a short label: letters, digits, spaces, - and _")
    store_secret(args.provider, args.name, value, (args.account or "").strip())
    label = f" for {args.account}" if args.account else ""
    print(f"{args.provider}: {args.name} stored{label}, mode 600 in "
          f"{os.path.join(SECRETS, args.provider)}")
    print("its value was not printed and never will be; a lane's log and the job records are "
          "scrubbed of it")
    return 0


def parser():
    ap = argparse.ArgumentParser(prog="fleet hosts", description=__doc__.splitlines()[0])
    subs = ap.add_subparsers(dest="command", required=True)

    listing = subs.add_parser("list", help="every provider: CLI, login, secrets, last test")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(run=cmd_list)

    checking = subs.add_parser("check", help="ask one provider now")
    checking.add_argument("provider")
    checking.add_argument("--json", action="store_true")
    checking.set_defaults(run=cmd_check)

    secret = subs.add_parser("secret", help="store a runner secret, value on stdin only")
    secret.add_argument("provider")
    secret.add_argument("name")
    secret.add_argument("--account", default="")
    secret.set_defaults(run=cmd_secret)
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
