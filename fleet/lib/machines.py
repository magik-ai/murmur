#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""The machines this farm owns: a registry, a provider, and no droplet that costs money invisibly.

A machine is a whole farm: systemd user services, tmux, worktrees, the dashboard, the installer
as it is. Two providers can be one: a DigitalOcean Droplet this farm creates, and any Linux box
you already reach over SSH. The design record is `fleet/docs/design/hosting.md`, section 4.

  fleet machines list [--json]
  fleet machines plan --provider do-droplet --name N --size S --region R [--pubkey-file F]
  fleet machines create --provider do-droplet --name N --size S --region R
                        --pubkey-file F --confirm-usd 48
  fleet machines add --name N --target user@host [--port P]
  fleet machines check N
  fleet machines adopt N
  fleet machines destroy N --confirm N
  fleet machines forget N
  fleet machines forget-attempt N

Four rules hold this file together:

  Nothing costs money invisibly. The order in `create` is: refuse a price that is not the live
  one, then under one lock refuse a name that already has a live row and write the row as
  `creating`, and only then call the provider. A retry after a timeout can never buy a second droplet, and a droplet that
  was made while the answer was lost still has a row that names its price.

  Nothing waits inside a request. `create` returns in seconds. The walk from `creating` to
  `preparing` to `needs-login` to `ready` is made by `list`, one short step per machine per
  pass, so a dashboard restart or a dropped connection loses nothing.

  One writer at a time. Every read-modify-write of the registry holds an flock on
  machines.toml.lock, and no provider call and no SSH happens while that lock is held.

  This file runs alone. The `/murmur:farm` skill runs it from a symlink inside the plugin, so it
  imports host_presets (its neighbour, symlinked with it) and nothing else of the fleet. That is
  why it carries its own ten-line TOML writer instead of importing models.py. scrub.py is used
  when it is there and skipped when it is not, so the plugin may carry two files or three.
"""
import argparse
import contextlib
import fcntl
import json
import math
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import host_presets  # noqa: E402

try:                                                    # optional neighbour, see the docstring
    import scrub as _scrub
except ImportError:                                     # pragma: no cover - the plugin may skip it
    _scrub = None

CONFIG = os.path.expanduser(os.environ.get("FLEET_CONFIG", "~/.config/fleet"))
STATE = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))
REGISTRY = os.path.join(CONFIG, "machines.toml")
LOCK = os.path.join(CONFIG, "machines.toml.lock")
FARM_ID_FILE = os.path.join(CONFIG, "farm-id")
KEY_DIR = os.path.join(STATE, "machines")
KEY = os.path.join(KEY_DIR, "id_ed25519")
KNOWN_HOSTS = os.path.join(KEY_DIR, "known_hosts")

FARM_USER = "farm"
IMAGE = "ubuntu-24-04-x64"
FIREWALL = "murmur-ssh-only"
TAG_FARM = "murmur-farm"
DASH_PORT = 7878

# States. Every one of them except `destroyed` still costs money on a droplet, and every row in
# one of them says so with the price.
CREATING = "creating"
PREPARING = "preparing"
NEEDS_LOGIN = "needs-login"
READY = "ready"
UNREACHABLE = "unreachable"
FAILED = "failed"
DESTROYED = "destroyed"
UNRECORDED = "unrecorded"

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
ADDRESS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:_-]{0,254}$")
PUBKEY_RE = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9-]+) [A-Za-z0-9+/=]+( .*)?$")
FIELDS = ("name", "provider", "user", "address", "port", "size", "monthly_usd", "region",
          "provider_id", "created_at", "state", "detail", "checked_at")

SSH_TIMEOUT = 15                     # a check never hangs a refresher for longer than this
PROVIDER_TIMEOUT = int(os.environ.get("FLEET_MACHINES_PROVIDER_TIMEOUT") or 60)
# A create whose answer was lost is pending, not failed: the droplet may exist. Its row waits on
# the tag list this long before it says that nothing appeared, and even then nothing is bought
# again until a person runs `forget-attempt` and confirms the price once more.
PENDING_WINDOW = int(os.environ.get("FLEET_MACHINES_PENDING_WINDOW") or 600)
PENDING_POLL = float(os.environ.get("FLEET_MACHINES_PENDING_POLL") or 10)
PENDING_NOTE = "pending: DigitalOcean's answer to the create was lost"
# A firewall just made or corrected says `waiting` for a moment: it is read back this many times,
# this many seconds apart, before a status that never reached `succeeded` refuses the create.
FIREWALL_READS = int(os.environ.get("FLEET_MACHINES_FIREWALL_READS") or 6)
FIREWALL_POLL = float(os.environ.get("FLEET_MACHINES_FIREWALL_POLL") or 5)


class Refused(Exception):
    """Something a person can fix, said in one sentence. Never a stack trace."""


# ------------------------------------------------------------------------------------- output

def clean(text):
    """A provider's own output, with every stored secret and token shape taken out of it."""
    if _scrub is None:
        return text or ""
    try:
        return _scrub.scrub(text or "", _scrub.stored_secrets(STATE))
    except Exception:                                   # pragma: no cover - scrubbing is best effort
        return text or ""


def one_line(text, limit=200):
    """A CLI's complaint as one line a table cell can hold."""
    flat = " ".join(clean(text).split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------- the registry and its lock

def _toml_string(value):
    """One TOML basic string: every quote, backslash and control character escaped."""
    out = []
    for char in str(value):
        if char in ("\\", '"'):
            out.append("\\" + char)
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append("\\u%04X" % ord(char))
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return _toml_string(value)


def dump_registry(rows):
    """The whole registry as text: one table per machine, every string quoted and escaped."""
    lines = ["# The machines this farm owns. Written by `fleet machines`; edit it while nothing",
             "# else is running, or your change is the one that gets lost.", ""]
    for name in sorted(rows):
        row = rows[name]
        lines.append("[" + (name if NAME_RE.match(name) else _toml_string(name)) + "]")
        for field in FIELDS:
            if field == "name" or row.get(field) in (None, ""):
                continue
            lines.append(f"{field} = {_toml_value(row[field])}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def read_registry():
    """Every row, by name. A registry that is not there yet is an empty one."""
    if not os.path.exists(REGISTRY):
        return {}
    try:
        import tomllib
    except ImportError:                                 # pragma: no cover - the farm needs 3.11
        raise Refused("this python has no tomllib; the farm needs python 3.11 or newer")
    try:
        with open(REGISTRY, "rb") as handle:
            parsed = tomllib.load(handle)
    except Exception as error:
        raise Refused(f"{REGISTRY} is not readable TOML ({error}); fix it by hand")
    rows = {}
    for name, table in parsed.items():
        if isinstance(table, dict):
            row = {field: table.get(field, "") for field in FIELDS}
            row["name"] = name
            rows[name] = row
    return rows


def write_registry(rows):
    """Replace the file in one step, so a write that does not finish leaves the old one whole."""
    os.makedirs(CONFIG, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=CONFIG, prefix="machines.toml.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(dump_registry(rows))
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, REGISTRY)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextlib.contextmanager
def locked():
    """The registry lock. Held around a read-modify-write and never around a provider call."""
    os.makedirs(CONFIG, exist_ok=True)
    handle = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def apply_changes(changes):
    """Re-read under the lock, fold in what we learned, write. Another writer's row survives."""
    if not changes:
        return
    with locked():
        rows = read_registry()
        for name, change in changes.items():
            if change is None:
                rows.pop(name, None)
                continue
            row = rows.get(name) or {field: "" for field in FIELDS}
            row["name"] = name
            row.update(change)
            rows[name] = row
        write_registry(rows)


def apply_step(name, started, change):
    """Fold one step's answer in, under the lock, only if the row is still where the step began.

    A step's SSH can run 15 seconds. If `destroy` (or anyone) moved the row meanwhile, the step
    answered a question about a machine that is no longer there, and writing its state would put
    a destroyed droplet back in the monthly total. Returns the row as it now stands, or None when
    the row is gone.
    """
    with locked():
        rows = read_registry()
        row = rows.get(name)
        if row is None:
            return None
        if (row.get("state") or "") == started:
            row.update(change)
            write_registry(rows)
        return dict(row)


# --------------------------------------------------------------------- the farm id and its key

WORDS = ("otter", "heron", "lynx", "ibis", "marten", "tern", "vole", "shrew", "wren", "pika",
         "kite", "eider", "loon", "stoat", "adder", "raven", "hare", "quail", "finch", "dace",
         "smew", "linnet", "merlin", "grebe", "auk", "skua", "crake", "dunlin", "gannet",
         "curlew", "fulmar", "puffin", "teal", "widgeon", "sanderling", "redshank")


def farm_id():
    """This farm's own word, made once.

    It goes into the tag `murmur-by-<farm id>` on every droplet this farm creates, so two farms
    on one DigitalOcean account never reconcile each other's machines. A word alone would
    collide once in a few dozen farms, so four hex characters ride with it.
    """
    if os.path.exists(FARM_ID_FILE):
        with open(FARM_ID_FILE, encoding="utf-8") as handle:
            existing = handle.read().strip()
        if existing:
            return existing
    made = "%s-%04x" % (random.choice(WORDS), random.randrange(0x10000))
    os.makedirs(CONFIG, exist_ok=True)
    with locked():                                      # two refreshers must not make two words
        if os.path.exists(FARM_ID_FILE):
            with open(FARM_ID_FILE, encoding="utf-8") as handle:
                existing = handle.read().strip()
            if existing:
                return existing
        with open(FARM_ID_FILE, "w", encoding="utf-8") as handle:
            handle.write(made + "\n")
    return made


def farm_tag():
    return "murmur-by-" + farm_id()


def ensure_machines_key():
    """This farm's own key for reaching its machines. The person's ~/.ssh is never touched."""
    if os.path.exists(KEY) and os.path.exists(KEY + ".pub"):
        return KEY
    os.makedirs(KEY_DIR, mode=0o700, exist_ok=True)
    os.chmod(KEY_DIR, 0o700)
    code, _out, err = run(["ssh-keygen", "-t", "ed25519", "-N", "", "-q",
                           "-C", "murmur-farm-" + farm_id(), "-f", KEY], timeout=30)
    if code != 0 or not os.path.exists(KEY + ".pub"):
        raise Refused(f"could not make this farm's machines key at {KEY}: {one_line(err)}")
    os.chmod(KEY, 0o600)
    return KEY


def machines_key_public():
    ensure_machines_key()
    with open(KEY + ".pub", encoding="utf-8") as handle:
        return handle.read().strip()


def key_fingerprint(public_path):
    """The MD5 fingerprint of a public key, the shape DigitalOcean lists keys by."""
    code, out, _err = run(["ssh-keygen", "-lf", public_path, "-E", "md5"], timeout=30)
    if code != 0:
        return ""
    for word in out.split():
        if word.startswith("MD5:"):
            return word[4:]
    return ""


def read_public_key(path):
    """One public key from a file, checked. A private key or a paragraph is refused."""
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as handle:
            body = handle.read().strip()
    except OSError as error:
        raise Refused(f"cannot read the public key file {path}: {error.strerror}")
    lines = [line for line in body.splitlines() if line.strip()]
    if len(lines) != 1 or not PUBKEY_RE.match(lines[0].strip()):
        raise Refused(f"{path} is not one line of ssh-ed25519, ssh-rsa or ecdsa-sha2-* public "
                      "key; pass the .pub file, never a private key")
    return lines[0].strip()


# ------------------------------------------------------------------------ running other people

def run(argv, timeout=PROVIDER_TIMEOUT, stdin_text=None, env=None):
    """(code, stdout, stderr). A missing binary is 127 and a timeout is 124; nothing raises."""
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env=env,
            input=stdin_text if stdin_text is not None else None,
            stdin=None if stdin_text is not None else subprocess.DEVNULL)
        return done.returncode, done.stdout or "", done.stderr or ""
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not installed on this farm"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]}: no answer in {timeout} seconds"
    except OSError as error:                            # pragma: no cover - a broken PATH entry
        return 127, "", f"{argv[0]}: {error.strerror}"


# The context pin_context() set, or None. A farm reads FLEET_DOCTL_CONTEXT; the laptop flow pins
# `murmur` instead, since on a laptop that variable and doctl's own DIGITALOCEAN_* settings belong
# to whatever else the person runs there, maybe another company's account.
PINNED_CONTEXT = None
DOCTL_ENV_PREFIX = "DIGITALOCEAN_"


def pin_context(context):
    """Every doctl call from here on names this context, whatever the environment says, and runs
    without the DIGITALOCEAN_* variables (a token, a context or a config file doctl would read
    from them in place of the named context)."""
    global PINNED_CONTEXT
    PINNED_CONTEXT = context


def doctl_env():
    """The environment for doctl: this one, less doctl's own settings once the context is
    pinned; None (inherit) otherwise."""
    if not PINNED_CONTEXT:
        return None
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith(DOCTL_ENV_PREFIX)}


def with_context(argv):
    """A doctl argv with this farm's context on it, as `doctl auth init --context murmur` made it.

    Every doctl call goes through here, the ones that create things most of all: a firewall made
    in another account's default context would leave the new droplet with no firewall at all.
    """
    context = PINNED_CONTEXT or os.environ.get("FLEET_DOCTL_CONTEXT", host_presets.DOCTL_CONTEXT)
    argv = [str(a) for a in argv]
    return argv + ["--context", context] if context else argv


def doctl(*args, **kwargs):
    """doctl, run with this farm's context."""
    return run(with_context(["doctl"] + list(args)), env=doctl_env(), **kwargs)


def doctl_json(*args, **kwargs):
    """(rows, error sentence). doctl prints a JSON list even for a single object."""
    code, out, err = doctl(*args, **kwargs)
    if code != 0:
        return None, one_line(err or out) or f"doctl exited {code}"
    try:
        parsed = json.loads(out or "[]")
    except ValueError:
        return None, "doctl answered something that is not JSON"
    if isinstance(parsed, dict):
        return [parsed], ""
    return (parsed if isinstance(parsed, list) else []), ""


def ssh_argv(row, remote):
    """Every SSH this farm makes: its own key, its own known-hosts file, and a short timeout."""
    argv = ["ssh", "-i", KEY,
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
            "-o", "LogLevel=ERROR"]
    # The port is always on the command line, 22 when the row names none: a Port in the
    # person's ssh config (a `Host *` that says 2222) never moves this farm's own ssh.
    argv += ["-p", str(row.get("port") or "").strip() or "22"]
    return argv + [f"{row.get('user') or FARM_USER}@{row['address']}", remote]


def ssh_run(row, remote):
    ensure_machines_key()
    os.makedirs(KEY_DIR, mode=0o700, exist_ok=True)
    return run(ssh_argv(row, remote), timeout=SSH_TIMEOUT)


KNOWN_HOSTS_EDIT = threading.Lock()


def forget_host_key(address):
    """DigitalOcean reuses addresses, and accept-new refuses a host key that changed."""
    if not address:
        return
    os.makedirs(KEY_DIR, mode=0o700, exist_ok=True)
    with KNOWN_HOSTS_EDIT:                              # ssh-keygen -R rewrites the whole file
        run(["ssh-keygen", "-R", address, "-f", KNOWN_HOSTS], timeout=30)


# ---------------------------------------------------------------------------- prices and plans

def usd(value):
    """A price as a finite positive number of dollars, or None.

    float() takes "nan", "inf" and "-48", and every comparison with nan is false, so a price a
    person typed or a provider sent is parsed here before it is compared with anything.
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def live_price(size_slug):
    """(monthly usd, source, note). The provider's price when it answers, the preset's when not.

    A stale number is how a person confirms $48 and pays $52, so the live price wins whenever
    doctl can give one, and the fallback says out loud how old it is.
    """
    listed = host_presets.size("do-droplet", size_slug)
    fallback = listed["monthly_usd"] if listed else 0
    if not shutil.which("doctl"):
        return fallback, "list", (f"doctl is not installed on this farm, so this is the "
                                  f"{host_presets.LIST_PRICE_NOTE}")
    rows, error = doctl_json("compute", "size", "list", "-o", "json", timeout=30)
    if rows is None:
        return fallback, "list", (f"DigitalOcean did not answer with a price ({error}), so this "
                                  f"is the {host_presets.LIST_PRICE_NOTE}")
    for row in rows:
        if row.get("slug") == size_slug:
            price = usd(row.get("price_monthly"))
            if price is None:
                return fallback, "list", (f"DigitalOcean's price for {size_slug} is not a "
                                          f"usable number, so this is the "
                                          f"{host_presets.LIST_PRICE_NOTE}")
            return round(price, 2), "live", "the price DigitalOcean gives today"
    return fallback, "list", (f"DigitalOcean's size list does not carry {size_slug}, so this is "
                              f"the {host_presets.LIST_PRICE_NOTE}")


TAILSCALE_HELPER = "/usr/local/sbin/murmur-tailscale-up"
TAILSCALE_SUDOERS = "/etc/sudoers.d/murmur-tailscale"

# The one root program the `farm` user may run. The auth key arrives on stdin, is kept in a 0600
# file under /run for as long as `tailscale up` reads it, and is deleted whatever happens. It is
# never on an argv, in the user data or in a log.
TAILSCALE_HELPER_BODY = """#!/bin/sh
# murmur: join this farm to a tailnet. Written by cloud-init, owned by root.
# The auth key arrives on stdin and never on an argv.
set -eu
umask 077
key=$(mktemp /run/murmur-tailscale-key.XXXXXX)
trap 'rm -f "$key"' EXIT
head -c 4096 > "$key"
if [ ! -s "$key" ]; then
  echo "murmur-tailscale-up: no auth key on stdin" >&2
  exit 2
fi
tailscale up --authkey "file:$key"
"""


def cloud_init(person_key, machines_key, tailscale=False, node=False):
    """The whole first boot of a new droplet, as one cloud-config file.

    A user `farm` without sudo (so nothing on the box can be changed by a stolen agent token),
    both keys that may reach it, the packages the installer needs plus gh from GitHub's own apt
    repository exactly as farm/install.sh adds it, lingering services, and the dashboard bound
    to loopback before the installer ever runs. The loopback line is a runcmd run as the user,
    never write_files, which runs before the user exists and would leave root owning its home.

    Two choices add to it. `tailscale` installs the Tailscale package (never a key: the key
    goes to the helper over ssh stdin after boot) and the one root helper the `farm` user may
    run with `sudo -n`, and nothing else. `node` installs Node and npm from the distribution,
    so the `farm` user can install Codex into a prefix it owns.
    """
    keys = [key for key in (machines_key, person_key) if key]
    gh_list = ("echo \"deb [arch=$(dpkg --print-architecture) "
               "signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] "
               "https://cli.github.com/packages stable main\" "
               "> /etc/apt/sources.list.d/github-cli.list")
    commands = [
        "mkdir -p -m 755 /etc/apt/keyrings",
        ("curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg "
         "-o /etc/apt/keyrings/githubcli-archive-keyring.gpg"),
        "chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg",
        gh_list,
    ]
    if tailscale:
        # Tailscale's own apt repository for Ubuntu 24.04 (noble), the image this file names.
        commands += [
            ("curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg "
             "-o /usr/share/keyrings/tailscale-archive-keyring.gpg"),
            ("curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list "
             "-o /etc/apt/sources.list.d/tailscale.list"),
        ]
    commands += [
        "apt-get update -qq",
        "apt-get install -y -qq gh" + (" tailscale" if tailscale else ""),
    ]
    if tailscale:
        # A sudoers file that does not parse would lock sudo for every user of the box.
        commands.append(f"visudo -cf {TAILSCALE_SUDOERS} || rm -f {TAILSCALE_SUDOERS}")
    commands += [
        f"loginctl enable-linger {FARM_USER}",
        (f"runuser -u {FARM_USER} -- sh -c 'mkdir -p ~/.config/fleet && "
         "echo FLEET_DASH_BIND=127.0.0.1 >> ~/.config/fleet/env'"),
    ]
    lines = [
        "#cloud-config",
        "# murmur farm, first boot. Written by `fleet machines`; nothing here is a secret.",
        "users:",
        "  - default",
        f"  - name: {FARM_USER}",
        "    shell: /bin/bash",
        "    ssh_authorized_keys:",
    ]
    lines += [f"      - {json.dumps(key)}" for key in keys]
    lines += [
        "# root keeps key-only SSH for administration; no password ever opens this box.",
        "disable_root: false",
        "ssh_pwauth: false",
        "package_update: true",
        "packages:",
        "  - git",
        "  - tmux",
        "  - python3",
        "  - curl",
        "  - ca-certificates",
    ]
    if node:
        lines += ["  - nodejs", "  - npm"]
    if tailscale:
        # `""` after the path allows the helper with no arguments at all, and nothing else.
        sudoers = f'{FARM_USER} ALL=(root) NOPASSWD: {TAILSCALE_HELPER} ""\n'
        lines += [
            "write_files:",
            f"  - path: {TAILSCALE_HELPER}",
            "    owner: root:root",
            "    permissions: '0755'",
            f"    content: {json.dumps(TAILSCALE_HELPER_BODY)}",
            f"  - path: {TAILSCALE_SUDOERS}",
            "    owner: root:root",
            "    permissions: '0440'",
            f"    content: {json.dumps(sudoers)}",
        ]
    lines.append("runcmd:")
    lines += [f"  - {json.dumps(command)}" for command in commands]
    return "\n".join(lines) + "\n"


def droplet_tags():
    """The only tags a new droplet carries: `murmur-farm`, which the murmur firewall attaches by,
    and this farm's own `murmur-by-<farm id>`, which the reconcile finds it by. No generic tag:
    every tag on a droplet is one more way for a firewall this farm does not own to cover it."""
    return [TAG_FARM, farm_tag()]


def create_argv(name, size, region, key_id, user_data_path):
    """The exact droplet create, without --wait: nothing waits inside a request."""
    return ["doctl", "compute", "droplet", "create", name,
            "--image", IMAGE,
            "--size", size,
            "--region", region,
            "--tag-names", ",".join(droplet_tags()),
            "--ssh-keys", str(key_id),
            "--user-data-file", user_data_path,
            "-o", "json"]


SSH_FROM = ("0.0.0.0/0", "::/0")
INBOUND_RULES = " ".join(f"protocol:tcp,ports:22,address:{address}" for address in SSH_FROM)
OUTBOUND_RULES = ("protocol:tcp,ports:0,address:0.0.0.0/0 "
                  "protocol:udp,ports:0,address:0.0.0.0/0 "
                  "protocol:icmp,address:0.0.0.0/0 "
                  "protocol:tcp,ports:0,address:::/0 "
                  "protocol:udp,ports:0,address:::/0 "
                  "protocol:icmp,address:::/0")
# What a farm must be let out on: every port of these, to everywhere. DigitalOcean lets nothing
# out that no outbound rule allows, so without them the box cannot fetch a package, reach GitHub,
# join a tailnet or talk to a model.
OUT_PROTOCOLS = ("tcp", "udp", "icmp")
ALL_PORTS = ("", "0", "all", "1-65535")


def firewall_argv():
    """SSH in, everything out. A DigitalOcean firewall with no outbound rules also cuts the
    farm off from GitHub and the model providers."""
    return ["doctl", "compute", "firewall", "create",
            "--name", FIREWALL,
            "--tag-names", TAG_FARM,
            "--inbound-rules", INBOUND_RULES,
            "--outbound-rules", OUTBOUND_RULES]


def firewall_update_argv(firewall_id, droplet_ids=()):
    """The same firewall, rewritten whole: `update` replaces every rule, tag and droplet it
    has, so the droplets it already covers are named again and nothing drops out of it."""
    argv = ["doctl", "compute", "firewall", "update", str(firewall_id),
            "--name", FIREWALL,
            "--tag-names", TAG_FARM,
            "--inbound-rules", INBOUND_RULES,
            "--outbound-rules", OUTBOUND_RULES]
    ids = [str(each) for each in droplet_ids if str(each).strip()]
    if ids:
        argv += ["--droplet-ids", ",".join(ids)]
    return argv


def tag_argv():
    """The `murmur-farm` tag, made before the firewall that names it: DigitalOcean's firewall
    create and update take existing tags only, and a fresh account has none."""
    return ["doctl", "compute", "tag", "create", TAG_FARM]


def ensure_tag():
    """Make the `murmur-farm` tag; one that already exists is fine."""
    code, out, err = doctl(*tag_argv()[1:], timeout=PROVIDER_TIMEOUT)
    if code != 0 and "already exist" not in (err + out).lower():
        raise Refused(f"DigitalOcean refused the {TAG_FARM} tag the firewall is attached by: "
                      f"{one_line(err or out)}")


def firewall_expected():
    """The one firewall a farm may sit behind, as data: `normalize_firewall` of a right one
    equals this and nothing else does. Inbound is tcp 22 from 0.0.0.0/0 and ::/0 and nothing
    more; outbound is tcp and udp on every port and icmp to the same two; no deny rule anywhere;
    the `murmur-farm` tag; and DigitalOcean's word that the rules are in force."""
    return {
        "status": "succeeded",
        "tags": (TAG_FARM,),
        "inbound": frozenset(("allow", "tcp", "22", "addresses", address)
                             for address in SSH_FROM),
        "outbound": frozenset(("allow", protocol, "all", "addresses", address)
                              for protocol in OUT_PROTOCOLS for address in SSH_FROM),
    }


def normalize_ports(protocol, ports):
    """One spelling for a port range: every port is "all" whether doctl says 0, all, 1-65535 or
    nothing, and icmp has no ports at all."""
    ports = str(ports if ports is not None else "").strip().lower()
    if protocol == "icmp" or ports in ALL_PORTS:
        return "all"
    return ports


def normalize_rules(rules, side):
    """A side's rules as a set of atoms, one for each thing a rule names: (action, protocol,
    ports, kind, value). Order, duplicates and how the targets are split over rules stop
    mattering; a rule that names nothing is kept as an atom of its own, so it still differs."""
    atoms = set()
    for rule in rules or []:
        if not isinstance(rule, dict):
            atoms.add(("?", "?", "?", "rule", str(rule)))
            continue
        protocol = str(rule.get("protocol") or "").strip().lower()
        action = str(rule.get("action") or "allow").strip().lower()
        ports = normalize_ports(protocol, rule.get("ports"))
        targets = rule.get(side) or {}
        named = False
        if isinstance(targets, dict):
            for kind, values in targets.items():
                values = values if isinstance(values, list) else [values]
                for value in values:
                    if value is None or str(value).strip() == "":
                        continue
                    atoms.add((action, protocol, ports, str(kind), str(value).strip().lower()))
                    named = True
        if not named:
            atoms.add((action, protocol, ports, "nothing", ""))
    return frozenset(atoms)


def normalize_firewall(row):
    """What doctl printed for a firewall, reduced to the fields the spec compares."""
    return {
        "status": str(row.get("status") or "").strip().lower(),
        "tags": tuple(sorted({str(tag).strip() for tag in row.get("tags") or []})),
        "inbound": normalize_rules(row.get("inbound_rules"), "sources"),
        "outbound": normalize_rules(row.get("outbound_rules"), "destinations"),
    }


def firewall_faults(row):
    """What is wrong with a firewall that carries our name, as sentences; empty when it is ours.

    A firewall is checked, never trusted by its name, and it is checked whole: the normalized
    firewall must equal `firewall_expected()`. Any difference at all is a fault, and there is one
    remedy for every fault: rewrite the firewall to the spec, read it back, compare again. The
    sentences only say what differs; the equality decides.
    """
    have, want = normalize_firewall(row), firewall_expected()
    if have == want:
        return []
    faults = []
    if have["status"] != want["status"]:
        faults.append(f"DigitalOcean says its status is {have['status'] or 'unknown'}, "
                      "not succeeded, so its rules may not be in force")
    faults += inbound_faults(have["inbound"], want["inbound"])
    faults += side_faults(have["outbound"], want["outbound"], "out")
    if have["tags"] != want["tags"]:
        if TAG_FARM not in have["tags"]:
            faults.append(f"it does not carry the {TAG_FARM} tag, so a new droplet is not covered")
        else:
            faults.append(f"it carries tags other than {TAG_FARM} "
                          f"({', '.join(t for t in have['tags'] if t != TAG_FARM)}), so it "
                          "covers droplets that are not this farm's")
    if not faults:                                      # pragma: no cover - a guard, not a path
        faults.append("it differs from the one firewall a farm may sit behind")
    return faults


def describe(atoms):
    """The targets of some atoms, in words: `0.0.0.0/0 or ::/0`, `tag bastion`, `nothing`."""
    words = []
    for _, _, _, kind, value in sorted(atoms):
        if kind == "addresses":
            words.append(value)
        elif kind == "nothing":
            words.append("nothing")
        else:
            words.append(f"{kind} {value}")
    return " or ".join(words)


def grouped(atoms):
    """Atoms by (action, protocol, ports), in a stable order."""
    groups = {}
    for atom in atoms:
        groups.setdefault(atom[:3], set()).add(atom)
    return sorted(groups.items())


def inbound_faults(have, want):
    """What the inbound rules get wrong, as sentences."""
    if not have:
        return ["it lets nothing in, so ssh cannot reach the farm"]
    faults = []
    ssh = ("allow", "tcp", "22")
    for (action, protocol, ports), atoms in grouped(have - want):
        if (action, protocol, ports) == ssh:
            continue
        if action != "allow":
            faults.append(f"it has a {action} rule on {protocol or 'something'} port {ports}, "
                          "and the only inbound rule may be an allow for tcp 22")
        else:
            faults.append(f"it lets in {protocol or 'something'} on port {ports} from "
                          f"{describe(atoms)}, and only tcp 22 may come in")
    # The laptop's address is not known and changes, so ssh must come in from anywhere: a tcp 22
    # rule narrowed to other sources leaves the person unable to reach the farm they paid for.
    missing = [atom[4] for atom in sorted(want - have)]
    extra = {atom for atom in have - want if atom[:3] == ssh}
    if missing:
        sentence = (f"its tcp 22 rules do not allow {' or '.join(missing)}, so ssh from this "
                    "laptop, whose address is not known and changes, may not reach the farm")
        if extra:
            sentence += f" (they allow {describe(extra)} instead)"
        faults.append(sentence)
    elif extra:
        faults.append(f"its tcp 22 rules also allow {describe(extra)}, and ssh comes in from "
                      "0.0.0.0/0 and ::/0 only")
    return faults


def side_faults(have, want, way):
    """What the outbound rules get wrong, as sentences."""
    if not have:
        return ["it lets nothing out, so the farm cannot fetch packages or reach GitHub, "
                "Tailscale or the model"]
    faults = []
    for (action, protocol, ports), atoms in grouped(have - want):
        if action != "allow":
            faults.append(f"it has a {action} rule on {protocol or 'something'} port {ports} "
                          f"{way} to {describe(atoms)}, and DigitalOcean puts a deny above "
                          "every allow, so the farm may not reach packages, GitHub, Tailscale "
                          "or the model")
        else:
            faults.append(f"it also lets {protocol or 'something'} {way} on port {ports} to "
                          f"{describe(atoms)}, beyond tcp, udp and icmp to everywhere")
    for protocol in OUT_PROTOCOLS:
        missing = [atom[4] for atom in sorted(want - have) if atom[1] == protocol]
        if missing:
            faults.append(f"it does not let {protocol} {way} on every port to "
                          f"{' or '.join(missing)}, so the farm may not reach packages, GitHub, "
                          "Tailscale or the model")
    return faults


def outbound_faults(outbound):
    """What the outbound rules get wrong against the spec, as sentences; empty when they are
    exactly tcp, udp and icmp on every port to 0.0.0.0/0 and ::/0."""
    return side_faults(normalize_rules(outbound, "destinations"),
                       firewall_expected()["outbound"], "out")


def pending_only(faults):
    """True when the only fault is a status DigitalOcean has not settled yet."""
    return len(faults) == 1 and "status is waiting" in faults[0]


def firewall_label(row):
    """A firewall as a person finds it in the console: its name and its id."""
    return f"{row.get('name') or 'unnamed'} (id {row.get('id') or 'unknown'})"


def firewalls_over(rows, tags, droplet_ids):
    """Every firewall that will apply to a droplet carrying `tags`: one attached by any of those
    tags, or one that names by id any of `droplet_ids`. DigitalOcean adds up the allow rules of
    every firewall over a droplet, so each one here counts, not only the one with our name."""
    tags, droplet_ids = set(tags), {str(each) for each in droplet_ids}
    over = []
    for row in rows:
        by_tag = tags & {str(tag).strip() for tag in row.get("tags") or []}
        by_id = droplet_ids & {str(each).strip() for each in row.get("droplet_ids") or []}
        if by_tag or by_id:
            over.append(row)
    return over


def foreign_firewalls(rows):
    """The sentence that stops a create, or "" when the only firewall over a new droplet will be
    the one murmur firewall.

    The set is computed from the tags the droplet will carry and, since a droplet has no id before
    it is made, from the ids of the droplets already on this farm's tag. Any firewall in it that
    is not `murmur-ssh-only`, and a second one by that name, stops the run and is named. This
    farm never edits or detaches a firewall it does not own: the person decides.
    """
    droplets, error = droplets_on_our_tag()
    if error:
        raise Refused(f"DigitalOcean did not list this farm's droplets ({error}), so the "
                      "firewalls over a new droplet cannot be known")
    ids = [droplet.get("id") for droplet in droplets if droplet.get("id") is not None]
    over = firewalls_over(rows, droplet_tags(), ids)
    others = [row for row in over if row.get("name") != FIREWALL]
    ours = [row for row in rows if row.get("name") == FIREWALL]
    if len(ours) > 1:
        return (f"{len(ours)} firewalls are named {FIREWALL} "
                f"({', '.join(firewall_label(row) for row in ours)}), and a farm sits behind "
                "exactly one. Delete the extra ones in the DigitalOcean console, then run this "
                "again")
    if others:
        tags = ", ".join(droplet_tags())
        return (f"a new droplet would also sit behind "
                f"{', '.join(firewall_label(row) for row in others)}, attached by one of its "
                f"tags ({tags}) or naming this farm's droplets by id. DigitalOcean adds up the "
                f"allow rules of every firewall over a droplet, so {FIREWALL} alone would not "
                "decide what reaches the farm. This farm never edits a firewall it does not "
                "own: detach that firewall from those tags and droplets in the DigitalOcean "
                "console, or delete it, then run this again")
    return ""


def read_back_firewall():
    """Read `murmur-ssh-only` back after a create or a correction, and refuse unless it is right.

    DigitalOcean answers `waiting` for a moment after a write, so a waiting status alone is read
    again a few times; anything else wrong, or still waiting at the end, refuses.
    """
    for attempt in range(max(1, FIREWALL_READS)):
        rows, error = doctl_json("compute", "firewall", "list", "-o", "json",
                                 timeout=PROVIDER_TIMEOUT)
        if rows is None:
            raise Refused(f"DigitalOcean did not list the firewalls after the change: {error}")
        ours = [row for row in rows if row.get("name") == FIREWALL]
        if not ours:
            raise Refused(f"the {FIREWALL} firewall is not on the list after it was made")
        foreign = foreign_firewalls(rows)
        if foreign:
            raise Refused(foreign)
        faults = [fault for row in ours for fault in firewall_faults(row)]
        if not faults:
            return FIREWALL
        if not pending_only(faults) or attempt + 1 >= max(1, FIREWALL_READS):
            raise Refused(f"the {FIREWALL} firewall is still wrong after the correction: "
                          f"{'; '.join(faults)}")
        time.sleep(FIREWALL_POLL)
    return FIREWALL                                     # pragma: no cover - the loop returns


def ensure_firewall():
    """The `murmur-ssh-only` firewall, attached by tag, so every future droplet gets it.

    The tag is made first. Then every firewall in the account is listed, and any other firewall
    that would also sit over the new droplet refuses before anything is written (see
    `foreign_firewalls`). Then the firewall is found by name and compared whole with
    `firewall_expected()`. One that differs in any way is rewritten to the spec, and every create
    or correction is read back and compared again; if it still differs, this refuses and the
    caller creates nothing.
    """
    ensure_tag()
    rows, error = doctl_json("compute", "firewall", "list", "-o", "json",
                             timeout=PROVIDER_TIMEOUT)
    if rows is None:
        raise Refused(f"DigitalOcean did not list this account's firewalls: {error}")
    foreign = foreign_firewalls(rows)                   # before any write, ours included
    if foreign:
        raise Refused(foreign)
    ours = [row for row in rows if row.get("name") == FIREWALL]
    if not ours:
        code, out, err = doctl(*firewall_argv()[1:], timeout=PROVIDER_TIMEOUT)
        if code != 0:
            raise Refused(f"DigitalOcean refused the {FIREWALL} firewall: {one_line(err or out)}")
        return read_back_firewall()
    changed = False
    for row in ours:
        faults = firewall_faults(row)
        if not faults:
            continue
        firewall_id = row.get("id")
        if not firewall_id:
            raise Refused(f"the {FIREWALL} firewall is wrong ({'; '.join(faults)}) and "
                          "DigitalOcean gave no id to correct it by")
        code, out, err = doctl(*firewall_update_argv(firewall_id, row.get("droplet_ids") or [])[1:],
                               timeout=PROVIDER_TIMEOUT)
        if code != 0:
            raise Refused(f"the {FIREWALL} firewall is wrong ({'; '.join(faults)}) and "
                          f"DigitalOcean refused the correction: {one_line(err or out)}")
        changed = True
    return read_back_firewall() if changed else FIREWALL


def plan_commands(name, size, region):
    """The commands `create` will run, for a person to read before they spend anything."""
    return [with_context(argv) for argv in (
        ["doctl", "compute", "ssh-key", "import", "murmur-farm-" + farm_id(),
         "--public-key-file", KEY + ".pub", "-o", "json"],
        tag_argv(),
        firewall_argv(),
        create_argv(name, size, region, "<this farm's key id>", "<the cloud-init file above>"),
    )]


# -------------------------------------------------------------------------------- the provider

def droplets_on_our_tag():
    """(rows, error). Every droplet this farm created, by its own tag."""
    if not shutil.which("doctl"):
        return [], "doctl is not installed on this farm"
    rows, error = doctl_json("compute", "droplet", "list", "--tag-name", farm_tag(),
                             "-o", "json", timeout=PROVIDER_TIMEOUT)
    if rows is None:
        return [], error
    # The tag is checked here too: a droplet another farm made, even one with the same name, is
    # never ours to adopt, whatever a list filter did or did not do.
    return [row for row in rows if farm_tag() in (row.get("tags") or [])], ""


def pending(row):
    """A create whose answer was lost: the row is `creating` and has no droplet id yet."""
    return (row.get("provider") == "do-droplet" and row.get("state") == CREATING
            and not row.get("provider_id"))


def seconds_since(stamp):
    try:
        import calendar
        return time.time() - calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return 0.0


def matching_droplets(name):
    """(droplets on this farm's tag with this name, error). The reconcile before any create."""
    droplets, error = droplets_on_our_tag()
    if error:
        return None, error
    return [d for d in droplets if d.get("name") == name], ""


def listed(droplets):
    return ", ".join(f"{d.get('name')} (id {d.get('id')}, "
                     f"{public_address(d) or 'no address yet'})" for d in droplets)


def adopt_pending(name, droplet):
    """Write a found droplet's id into a pending row, only if the row is still pending."""
    with locked():
        rows = read_registry()
        row = rows.get(name)
        if row is None or not pending(row):
            return row
        row.update({"provider_id": str(droplet.get("id")), "checked_at": now(),
                    "detail": "found on this farm's tag after a lost answer; adopted, "
                              "not bought again"})
        write_registry(rows)
        return dict(row)


def wait_pending(name, window=None, poll=None, budget=None):
    """Poll this farm's tag for a pending create's droplet, and adopt it when it appears.

    The window runs from the attempt, not from this call, so a rerun an hour later asks once and
    says so rather than waiting again. `budget` caps this call alone (a caller whose own run is
    capped returns with the row still pending and simply calls again). Nothing here ever
    creates anything. Returns the row.
    """
    window = PENDING_WINDOW if window is None else window
    poll = PENDING_POLL if poll is None else poll
    stop_at = None if budget is None else time.time() + budget
    while True:
        row = read_registry().get(name)
        if row is None or not pending(row):
            return row
        found, error = matching_droplets(name)
        if found is not None and len(found) == 1:
            return adopt_pending(name, found[0])
        if found is not None and len(found) > 1:
            raise Refused(f"{len(found)} droplets named {name} carry this farm's tag "
                          f"({listed(found)}); nothing is adopted or bought. Destroy the ones "
                          "you do not want in the DigitalOcean console, then run this again")
        if seconds_since(row.get("created_at")) >= window:
            minutes = max(1, int(window // 60))
            detail = (f"{PENDING_NOTE}, and no droplet named {name} appeared on this farm's tag "
                      f"in {minutes} minute{'' if minutes == 1 else 's'}. Nothing is bought "
                      "again on its own: "
                      f"`forget-attempt {name}`, then confirm the price again")
            if error:
                detail += f" (the last list failed: {error})"
            apply_step(name, CREATING, {"detail": detail, "checked_at": now()})
            return read_registry().get(name)
        if stop_at is not None and time.time() >= stop_at:
            return row
        time.sleep(poll)


def public_address(droplet):
    for entry in ((droplet.get("networks") or {}).get("v4") or []):
        if entry.get("type") == "public" and entry.get("ip_address"):
            return entry["ip_address"]
    return ""


def droplet_price(droplet):
    price = usd((droplet.get("size") or {}).get("price_monthly"))
    if price is None:
        listed = host_presets.size("do-droplet", droplet.get("size_slug") or "")
        price = usd(listed["monthly_usd"]) if listed else None
    return round(price or 0, 2)


def ensure_key_imported():
    """This farm's public key on the account, imported once and found by fingerprint after."""
    ensure_machines_key()
    fingerprint = key_fingerprint(KEY + ".pub")
    rows, error = doctl_json("compute", "ssh-key", "list", "-o", "json", timeout=PROVIDER_TIMEOUT)
    if rows is None:
        raise Refused(f"DigitalOcean did not list this account's SSH keys: {error}")
    # The JSON key names doctl prints for a key are UNVERIFIED, so the fingerprint is matched
    # first and the name is the fallback.
    wanted_name = "murmur-farm-" + farm_id()
    for row in rows:
        if fingerprint and str(row.get("fingerprint") or "").endswith(fingerprint):
            return row.get("id") or row.get("fingerprint")
        if row.get("name") == wanted_name:
            return row.get("id") or row.get("fingerprint")
    rows, error = doctl_json("compute", "ssh-key", "import", wanted_name,
                             "--public-key-file", KEY + ".pub", "-o", "json",
                             timeout=PROVIDER_TIMEOUT)
    if rows is None or not rows:
        raise Refused(f"DigitalOcean did not take this farm's public key: {error}")
    return rows[0].get("id") or rows[0].get("fingerprint")


# ---------------------------------------------------------------------------- rows for a reader

def finish_command(row):
    """The one command a person runs from their laptop, from the design record, section 4."""
    return (f"ssh -t {row.get('user') or FARM_USER}@{row['address']} "
            "'gh auth login && gh repo clone magik-ai/murmur ~/work/murmur -- -q && "
            "bash ~/work/murmur/farm/install.sh --remote'")


def tunnel_command(row):
    return (f"ssh -N -L {DASH_PORT}:127.0.0.1:{DASH_PORT} "
            f"{row.get('user') or FARM_USER}@{row['address']}")


def billed(row):
    """Money is running on this row right now.

    A destroyed droplet costs nothing, and neither does a failed row the provider never made a
    droplet for. Everything else a droplet can be, including `creating` and `unreachable`,
    bills until somebody destroys it.
    """
    if row.get("provider") != "do-droplet":
        return False
    if row.get("state") == DESTROYED:
        return False
    if row.get("state") == FAILED and not row.get("provider_id"):
        return False
    return True


def price_sentence(row):
    money = float(row.get("monthly_usd") or 0)
    if not money:
        return "this droplet is billing; `fleet machines list` shows what DigitalOcean charges"
    if row.get("state") == FAILED:
        return (f"${money:g} a month runs until this droplet is destroyed, if the provider made "
                "one at all")
    return f"${money:g} a month runs until this droplet is destroyed"


def presented(row):
    """One row as the dashboard and the skill read it (design record, section 7)."""
    shown = {field: row.get(field, "") for field in FIELDS}
    shown["monthly_usd"] = float(row.get("monthly_usd") or 0)
    detail = row.get("detail") or ""
    if billed(row):
        detail = f"{detail} {price_sentence(row)}".strip() if detail else price_sentence(row)
    shown["detail"] = detail
    shown["finish_command"] = finish_command(row) if (
        row.get("state") == NEEDS_LOGIN and row.get("address")) else ""
    shown["tunnel_command"] = tunnel_command(row) if (
        row.get("state") == READY and row.get("address")) else ""
    return shown


def this_farm():
    """The farm the command runs on. It is always first and is never in the registry.

    The address is left empty: the alias is an ssh name on the person's laptop, not an address,
    and which of this box's own addresses a person reaches it at is not something it can know.
    """
    name = os.environ.get("FLEET_FARM_ALIAS") or os.uname().nodename
    return {"name": name, "address": ""}


# --------------------------------------------------------------------------------- the commands

def step_one_machine(name, row):
    """One short step towards ready, for one machine. Returns the fields that changed.

    A pass over the registry does at most one provider call or one SSH per machine, so a
    refresher's 45 seconds are never spent on a single slow box, and a ready machine is never
    touched at all (Check is what reaches into one of those).
    """
    state = row.get("state") or ""
    if state in (READY, DESTROYED, FAILED, UNRECORDED):
        return {}

    if row.get("provider") == "do-droplet" and state == CREATING:
        if not row.get("provider_id"):
            return {}
        rows, error = doctl_json("compute", "droplet", "get", str(row["provider_id"]),
                                 "-o", "json", timeout=PROVIDER_TIMEOUT)
        if rows is None:
            return {"detail": f"DigitalOcean did not answer for this droplet: {error}",
                    "checked_at": now()}
        if not rows:
            return {"state": DESTROYED, "checked_at": now(),
                    "detail": "the provider no longer has this droplet; billing has stopped"}
        address = public_address(rows[0])
        if not address:
            return {"detail": "DigitalOcean is building it; no address yet", "checked_at": now()}
        forget_host_key(address)
        return {"address": address, "state": PREPARING, "checked_at": now(),
                "detail": "first boot is installing packages"}

    if not row.get("address"):
        return {}

    if state in (PREPARING, CREATING):
        code, out, err = ssh_run(row, "cloud-init status")
        text = (out + " " + err).strip()
        if code == 0 and "status: done" in out:
            return {"state": NEEDS_LOGIN, "checked_at": now(),
                    "detail": "first boot finished; run the finish command from your laptop"}
        if code in (124, 255, 127):
            return {"detail": f"waiting for SSH ({one_line(text)})", "checked_at": now()}
        return {"state": PREPARING, "checked_at": now(),
                "detail": f"first boot: {one_line(out) or 'running'}"}

    if state in (NEEDS_LOGIN, UNREACHABLE):
        code, out, err = ssh_run(row, "bash -lc 'fleet capacity'")
        if code == 0:
            return {"state": READY, "checked_at": now(), "detail": "the farm answers"}
        if state == UNREACHABLE:
            return {"checked_at": now(), "detail": one_line(err or out) or "no answer over SSH"}
        return {"checked_at": now(),
                "detail": "prepared; the two logins and the installer are left"}

    return {}


def cmd_list(args):
    rows = read_registry()
    changes = {}
    provider_error = ""
    droplets = []

    wants_provider = shutil.which("doctl") and (
        os.path.exists(FARM_ID_FILE)
        or any(row.get("provider") == "do-droplet" for row in rows.values()))
    if wants_provider:
        droplets, provider_error = droplets_on_our_tag()

    by_id = {str(d.get("id")): d for d in droplets}
    by_name = {d.get("name"): d for d in droplets}

    if not provider_error and wants_provider:
        for name, row in rows.items():
            if row.get("provider") != "do-droplet":
                continue
            if not row.get("provider_id"):
                found = by_name.get(name)
                if found and row.get("state") not in (DESTROYED, FAILED):
                    changes[name] = {"provider_id": str(found.get("id")),
                                     "detail": "found by name after a lost answer"}
                elif pending(row) and seconds_since(row.get("created_at")) >= PENDING_WINDOW:
                    changes[name] = {"checked_at": now(), "detail": (
                        f"{PENDING_NOTE}, and nothing named {name} appeared on this farm's tag; "
                        f"nothing is bought again on its own: `fleet machines forget-attempt "
                        f"{name}`, then confirm the price again")}
                continue
            if str(row["provider_id"]) not in by_id and row.get("state") != DESTROYED:
                changes[name] = {"state": DESTROYED, "checked_at": now(),
                                 "detail": "the provider no longer lists this droplet; "
                                           "billing has stopped"}

    for name, change in changes.items():               # a step reads the row we just learned of
        rows[name].update(change)
    apply_changes(changes)                              # kept even if this pass is cut short

    # The machines are stepped together, and each one's answer is written the moment it comes:
    # five silent boxes at a 15 second SSH each must fit the refresher's 60 seconds, and a pass
    # that is killed half way keeps everything it learned before that.
    def step(name):
        started = rows[name].get("state") or ""
        try:
            change = step_one_machine(name, rows[name])
        except Refused as error:
            change = {"detail": str(error), "checked_at": now()}
        if change:
            rows[name] = apply_step(name, started, change) or rows[name]

    busy = [name for name in rows if rows[name].get("state") not in (READY, DESTROYED, FAILED,
                                                                     UNRECORDED)]
    if busy:
        ensure_machines_key()                           # made once, before the threads race for it
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(busy), 8)) as pool:
            list(pool.map(step, busy))

    shown = [presented(rows[name]) for name in sorted(rows)]
    known_ids = {str(rows[name].get("provider_id")) for name in rows}
    for droplet in droplets:
        if str(droplet.get("id")) in known_ids:
            continue
        shown.append(presented({
            "name": droplet.get("name") or f"droplet-{droplet.get('id')}",
            "provider": "do-droplet", "user": FARM_USER, "address": public_address(droplet),
            "port": "", "size": droplet.get("size_slug") or "",
            "monthly_usd": droplet_price(droplet),
            "region": (droplet.get("region") or {}).get("slug") or "",
            "provider_id": str(droplet.get("id")), "created_at": droplet.get("created_at") or "",
            "state": UNRECORDED, "checked_at": now(),
            "detail": "this farm created it and the registry does not have it; Adopt writes the "
                      "row, Destroy stops the billing",
        }))

    total = round(sum(row["monthly_usd"] for row in shown if billed(row)), 2)
    # `error` is the field section 7 of the design record names: when DigitalOcean was not asked
    # or did not answer, the rows are the registry's word alone, and the page must say so.
    answer = {"this": this_farm(), "total_monthly_usd": total, "machines": shown,
              "error": provider_error or ""}

    if args.json:
        print(json.dumps(answer, indent=2))
        return 0

    farm = answer["this"]
    print(f"this farm    {farm['name']}" + (f"  ({farm['address']})" if farm["address"] else ""))
    if not shown:
        print("no other machines; `fleet machines plan --provider do-droplet ...` prices one")
    for row in shown:
        print(f"{row['name']:<16} {row['provider']:<11} {row['address'] or '-':<16} "
              f"{row['size'] or '-':<14} {row['state']:<12} {row['detail']}")
    paying = sum(1 for row in shown if billed(row))
    print(f"total        ${total:g} a month for {paying} "
          f"{'machine' if paying == 1 else 'machines'} that bill, {len(shown)} "
          f"{'row' if len(shown) == 1 else 'rows'} in all")
    if provider_error:
        print(f"note         DigitalOcean was not asked or did not answer: {provider_error}")
    return 0


def check_arguments(args):
    if not NAME_RE.match(args.name or ""):
        raise Refused("a machine name is lower case letters, digits and -, starting with a "
                      "letter, 2 to 31 characters")
    if getattr(args, "size", None) and not host_presets.size("do-droplet", args.size):
        offered = ", ".join(s["slug"] for s in host_presets.preset("do-droplet")["sizes"])
        raise Refused(f"{args.size} is not a size this farm offers: {offered}")
    if getattr(args, "region", None) and args.region not in \
            host_presets.preset("do-droplet")["regions"]:
        offered = ", ".join(host_presets.preset("do-droplet")["regions"])
        raise Refused(f"{args.region} is not a region this farm offers: {offered}")


def live_row(rows, name):
    """The row that makes a name unusable: anything but destroyed, or failed with no droplet."""
    row = rows.get(name)
    if not row:
        return None
    if row.get("state") == DESTROYED:
        return None
    if row.get("state") == FAILED and not row.get("provider_id"):
        return None
    return row


def cmd_plan(args):
    if args.provider != "do-droplet":
        raise Refused("only do-droplet can be planned; your own machine is `fleet machines add`")
    check_arguments(args)
    price, source, note = live_price(args.size)
    person_key = read_public_key(args.pubkey_file) if args.pubkey_file else ""
    rendered = cloud_init(person_key or "<your SSH public key, required by create>",
                          machines_key_public())
    listed = host_presets.size("do-droplet", args.size)
    answer = {
        "provider": args.provider, "name": args.name, "size": args.size, "region": args.region,
        "monthly_usd": price, "price_source": source, "price_note": note,
        "size_label": listed["label"], "farm_tag": farm_tag(),
        "commands": plan_commands(args.name, args.size, args.region),
        "cloud_init": rendered,
        "warnings": ([] if person_key else
                     ["create needs --pubkey-file: without your own public key on the machine, "
                      "the finish command and the tunnel cannot log in from your laptop"]),
    }
    if args.json:
        print(json.dumps(answer, indent=2))
        return 0
    print(f"{args.name}: a DigitalOcean droplet, {listed['label']}, {args.region}")
    print(f"price      ${price:g} a month ({note})")
    print(f"buy it     fleet machines create --provider do-droplet --name {args.name} "
          f"--size {args.size} --region {args.region} --pubkey-file <your key> "
          f"--confirm-usd {price:g}")
    # shlex.join, because a person copies these: the firewall rules carry spaces.
    print("commands   " + "\n           ".join(shlex.join(argv) for argv in answer["commands"]))
    for warning in answer["warnings"]:
        print(f"warning    {warning}")
    print("cloud-init")
    for line in rendered.splitlines():
        print("  " + line)
    return 0


def adopt_existing(name, size="", region=""):
    """The reconcile before any create: adopt the one droplet on this farm's tag with this name.

    Returns the adopted row, or None when there is no such droplet. Nothing is bought here and no
    price is asked, since the droplet already bills. A list that fails, more than one candidate,
    or a live row for the name refuses.
    """
    found, error = matching_droplets(name)
    if found is None:
        raise Refused(f"DigitalOcean did not list this farm's droplets ({error}), so nothing is "
                      "bought: a droplet this farm already has would be bought twice")
    if len(found) > 1:
        raise Refused(f"{len(found)} droplets named {name} already carry this farm's tag "
                      f"({listed(found)}); nothing is bought or adopted")
    if not found:
        return None
    droplet = found[0]
    address = public_address(droplet)
    if address:
        forget_host_key(address)
    with locked():
        rows = read_registry()
        if live_row(rows, name):
            raise Refused(f"{name} already has a live row ({rows[name]['state']})")
        rows[name] = {
            "name": name, "provider": "do-droplet", "user": FARM_USER, "address": address,
            "port": "", "size": droplet.get("size_slug") or size,
            "monthly_usd": droplet_price(droplet),
            "region": (droplet.get("region") or {}).get("slug") or region,
            "provider_id": str(droplet.get("id")),
            "created_at": droplet.get("created_at") or now(),
            "state": PREPARING if address else CREATING, "checked_at": now(),
            "detail": "already on this farm's tag; adopted, not bought again"}
        write_registry(rows)
        return dict(rows[name])


def create_droplet(name, size, region, person_key, confirm_usd, tailscale=False, node=False):
    """Buy one droplet at the price a person typed, or adopt the one that already exists.

    Returns ("created" | "adopted" | "pending", row). The order is the one the module docstring
    promises, with the reconcile first: a droplet on this farm's tag with this name is never
    bought again, and a create whose answer was lost leaves the row pending, never failed.
    """
    typed = usd(confirm_usd)
    if typed is None:
        raise Refused(f"{confirm_usd!r} is not a price: a confirmed price is a finite number "
                      "of dollars above zero. Nothing was created; run `fleet machines plan` "
                      "and confirm the price it shows")
    price, source, note = live_price(size)
    if usd(price) is None:
        raise Refused(f"there is no usable price for {size} ({note}), so nothing was created")
    if abs(typed - usd(price)) > 0.005:
        raise Refused(f"the price moved: you confirmed ${typed:g} a month and "
                      f"{size} costs ${price:g} a month ({note}). Nothing was created; "
                      f"run `fleet machines plan` again and confirm the new price")
    if source != "live":
        raise Refused(f"DigitalOcean did not give a live price for {size} ({note}), so this "
                      "farm will not buy a droplet on an old number; log doctl in and try again")

    with locked():
        rows = read_registry()
    if live_row(rows, name):
        raise Refused(f"{name} already has a live row ({rows[name]['state']}); "
                      "a retry must never buy a second droplet. Pick another name, or "
                      f"`fleet machines destroy {name} --confirm {name}`")
    row = adopt_existing(name, size, region)
    if row:
        return "adopted", row

    # The name check and the `creating` row happen under one lock with nothing in between: two
    # presses at once find each other's row, and only one of them ever reaches the provider.
    started = now()
    row = {"name": name, "provider": "do-droplet", "user": FARM_USER, "address": "",
           "port": "", "size": size, "monthly_usd": price, "region": region,
           "provider_id": "", "created_at": started, "state": CREATING, "checked_at": started,
           "detail": "this farm has asked DigitalOcean for it"}
    with locked():                                      # the row exists before the provider call
        rows = read_registry()
        if live_row(rows, name):
            raise Refused(f"{name} already has a live row ({rows[name]['state']}); "
                          "a retry must never buy a second droplet. Pick another name, or "
                          f"`fleet machines destroy {name} --confirm {name}`")
        rows[name] = row
        write_registry(rows)

    def failed(step, message):
        """Mark the row failed, and give back the refusal for the caller to raise. Only for a
        step before the create call: none of them can have made a droplet."""
        apply_changes({name: {
            "state": FAILED, "checked_at": now(),
            "detail": (f"DigitalOcean refused at {step}: {message}. No droplet was asked for; "
                       f"`fleet machines forget {name}` drops the row")}})
        return Refused(f"the droplet was not created ({step}): {message}. The row is marked "
                       "failed and says what to check")

    try:
        key_id = ensure_key_imported()
    except Refused as error:
        raise failed("the SSH key import", str(error))
    try:
        ensure_firewall()
    except Refused as error:
        raise failed("the firewall", str(error))

    handle, user_data = tempfile.mkstemp(prefix="murmur-cloud-init.", suffix=".yaml")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(cloud_init(person_key, machines_key_public(), tailscale=tailscale,
                                 node=node))
        os.chmod(user_data, 0o600)
        code, out_text, err = doctl(*create_argv(name, size, region, key_id, user_data)[1:],
                                    timeout=PROVIDER_TIMEOUT)
    finally:
        try:
            os.unlink(user_data)
        except OSError:
            pass

    made = []
    if code == 0:
        try:
            made = json.loads(out_text or "[]")
        except ValueError:
            made = []
        made = made if isinstance(made, list) else [made]
    if code != 0 or not made or not made[0].get("id"):
        # Not failed: a timeout or an error after DigitalOcean took the order still leaves a
        # droplet that bills. The row stays `creating` with no id, which is what pending means.
        why = one_line(err or out_text) if code != 0 else "the answer carried no droplet id"
        apply_changes({name: {"checked_at": now(),
                              "detail": (f"{PENDING_NOTE} ({why}); this farm watches its tag "
                                         "for the droplet and never buys it again on its own")}})
        return "pending", read_registry().get(name)

    apply_changes({name: {"provider_id": str(made[0]["id"]), "checked_at": now(),
                          "detail": "DigitalOcean is building it"}})
    return "created", read_registry().get(name)


def cmd_create(args):
    if args.provider != "do-droplet":
        raise Refused("only do-droplet can be created; your own machine is `fleet machines add`")
    check_arguments(args)
    person_key = read_public_key(args.pubkey_file)
    outcome, row = create_droplet(args.name, args.size, args.region, person_key,
                                  args.confirm_usd)
    if outcome == "pending" and args.wait_pending:
        row = wait_pending(args.name, window=args.wait_pending)
        if row and row.get("provider_id"):
            outcome = "adopted"
    price = float(row.get("monthly_usd") or 0)
    if outcome == "pending":
        print(f"{args.name}: {row.get('detail')}", file=sys.stderr)
        print(f"`fleet machines list` adopts it when it appears; if it never does, "
              f"`fleet machines forget-attempt {args.name}` and confirm the price again",
              file=sys.stderr)
        return 3
    if outcome == "adopted":
        print(f"{args.name}: droplet {row['provider_id']} was already on this farm's tag; "
              f"adopted, not bought again (${price:g} a month until it is destroyed)")
        return 0
    print(f"{args.name}: droplet {row['provider_id']} asked for, ${price:g} a month until it is "
          "destroyed")
    print("`fleet machines list` walks it to needs-login and then prints the finish command")
    return 0


def forget_attempt(name):
    """Drop a pending create that never showed up, so a new one may be confirmed and bought.

    It is refused while the attempt is younger than the pending window, and it asks the tag one
    last time: a droplet that did appear is adopted instead of forgotten.
    """
    row = read_registry().get(name)
    if row is None:
        raise Refused(f"there is no machine called {name} in the registry")
    if not pending(row):
        raise Refused(f"{name} is not a pending create ({row.get('state')}); forget-attempt is "
                      "only for a create whose answer was lost")
    age = seconds_since(row.get("created_at"))
    if age < PENDING_WINDOW:
        raise Refused(f"the create of {name} was asked for {int(age)} seconds ago; its droplet "
                      f"may still appear, so wait until {max(1, PENDING_WINDOW // 60)} minutes "
                      "have passed and run this again")
    found, error = matching_droplets(name)
    if found is None:
        raise Refused(f"DigitalOcean did not list this farm's droplets ({error}), so the attempt "
                      "is kept: forgetting it now could buy the same droplet twice")
    if len(found) > 1:
        raise Refused(f"{len(found)} droplets named {name} carry this farm's tag "
                      f"({listed(found)}); nothing is forgotten")
    if found:
        return "adopted", adopt_pending(name, found[0])
    with locked():
        rows = read_registry()
        if rows.get(name) is not None and pending(rows[name]):
            rows.pop(name)
            write_registry(rows)
    return "forgotten", None


def cmd_forget_attempt(args):
    if not NAME_RE.match(args.name or ""):
        raise Refused("a machine name is lower case letters, digits and -")
    outcome, row = forget_attempt(args.name)
    if outcome == "adopted":
        print(f"{args.name}: droplet {row['provider_id']} appeared on this farm's tag; adopted "
              "instead of forgotten")
        return 0
    print(f"{args.name}: the lost attempt is forgotten. A new create needs the price confirmed "
          "again")
    return 0


def cmd_add(args):
    check_arguments(args)
    target = args.target or ""
    if "@" not in target:
        raise Refused("--target is user@host, for example farm@192.0.2.10")
    user, _, address = target.partition("@")
    if not USER_RE.match(user) or not ADDRESS_RE.match(address):
        raise Refused(f"{target} is not a user@host this farm will put on a command line")
    port = str(args.port or "").strip()
    if port and (not port.isdigit() or not 1 <= int(port) <= 65535):
        raise Refused(f"{port} is not a port number")

    with locked():
        rows = read_registry()
        if live_row(rows, args.name):
            raise Refused(f"{args.name} already has a live row ({rows[args.name]['state']})")
    forget_host_key(address)
    row = {"name": args.name, "provider": "ssh", "user": user, "address": address, "port": port,
           "size": "", "monthly_usd": 0, "region": "", "provider_id": "", "created_at": now(),
           "state": UNREACHABLE, "checked_at": "", "detail": "added; checking SSH"}
    apply_changes({args.name: row})
    print(f"{args.name}: registered as {target}; nothing was bought")
    return check_one(args.name)


def check_one(name):
    rows = read_registry()
    row = rows.get(name)
    if not row:
        raise Refused(f"there is no machine called {name}")
    if row.get("state") == DESTROYED:
        raise Refused(f"{name} is destroyed; `fleet machines forget {name}` drops the row")

    if row.get("provider") == "do-droplet" and not row.get("address") and row.get("provider_id"):
        change = step_one_machine(name, row)
        apply_changes({name: change})
        row.update(change)

    if not row.get("address"):
        print(f"{name}: no address yet; `fleet machines list` carries it on")
        return 0

    change = {"checked_at": now()}
    code, out, err = (0, "", "")
    if row.get("provider") == "do-droplet" and row.get("state") in (CREATING, PREPARING):
        # Only a droplet in its first boot has a first boot to wait for. A machine you already
        # have never had one, and a machine that has finished one is asked the only question
        # that matters after that, whether the farm answers: a Check must never walk a row
        # backwards from needs-login to preparing.
        code, out, err = ssh_run(row, "cloud-init status")
    booting = code == 0 and out and "status: done" not in out
    if code in (124, 255):
        change.update({"state": UNREACHABLE, "detail": one_line(err or out) or "no answer"})
    elif booting:
        change.update({"state": PREPARING, "detail": f"first boot: {one_line(out)}"})
    else:
        code, out, err = ssh_run(row, "bash -lc 'fleet capacity'")
        if code == 0:
            change.update({"state": READY, "detail": "the farm answers"})
        elif code in (124, 255):
            change.update({"state": UNREACHABLE, "detail": one_line(err or out) or "no answer"})
        else:
            change.update({"state": NEEDS_LOGIN,
                           "detail": "SSH works and the fleet is not installed yet"})
    apply_changes({name: change})
    row.update(change)
    print(f"{name}: {change['state']}, {change['detail']}")
    if change["state"] == NEEDS_LOGIN:
        print("finish it from your laptop:\n  " + finish_command(row))
    if change["state"] == READY:
        print("reach its dashboard:\n  " + tunnel_command(row))
    return 0


def cmd_check(args):
    if not NAME_RE.match(args.name or ""):
        raise Refused("a machine name is lower case letters, digits and -")
    return check_one(args.name)


def cmd_adopt(args):
    if not NAME_RE.match(args.name or ""):
        raise Refused("a machine name is lower case letters, digits and -")
    with locked():
        rows = read_registry()
    if live_row(rows, args.name):
        raise Refused(f"{args.name} already has a row; adopt is for a droplet this farm made "
                      "and the registry does not have")
    droplets, error = droplets_on_our_tag()
    if error:
        raise Refused(f"DigitalOcean did not list this farm's droplets: {error}")
    found = [d for d in droplets if d.get("name") == args.name]
    if not found:
        raise Refused(f"DigitalOcean has no droplet called {args.name} on this farm's tag "
                      f"({farm_tag()})")
    droplet = found[0]
    address = public_address(droplet)
    if address:
        forget_host_key(address)
    apply_changes({args.name: {
        "name": args.name, "provider": "do-droplet", "user": FARM_USER, "address": address,
        "port": "", "size": droplet.get("size_slug") or "",
        "monthly_usd": droplet_price(droplet),
        "region": (droplet.get("region") or {}).get("slug") or "",
        "provider_id": str(droplet.get("id")), "created_at": droplet.get("created_at") or now(),
        "state": PREPARING if address else CREATING, "checked_at": now(),
        "detail": "adopted from DigitalOcean's own facts"}})
    print(f"{args.name}: adopted, droplet {droplet.get('id')}, "
          f"${droplet_price(droplet):g} a month")
    return 0


def cmd_destroy(args):
    if not NAME_RE.match(args.name or ""):
        raise Refused("a machine name is lower case letters, digits and -")
    if args.confirm != args.name:
        raise Refused(f"destroying a machine deletes its disk and stops its billing; repeat the "
                      f"name to mean it: --confirm {args.name}")
    with locked():
        rows = read_registry()
    row = rows.get(args.name)
    if not row:
        droplets, _error = droplets_on_our_tag()
        found = [d for d in droplets if d.get("name") == args.name]
        if not found:
            raise Refused(f"there is no machine called {args.name}")
        row = {"name": args.name, "provider": "do-droplet",
               "provider_id": str(found[0].get("id")), "state": UNRECORDED,
               "monthly_usd": droplet_price(found[0])}
    if row.get("provider") != "do-droplet":
        raise Refused(f"{args.name} is your own machine: this farm did not buy it and will not "
                      f"delete it. `fleet machines forget {args.name}` drops the row")
    if not row.get("provider_id"):
        raise Refused(f"{args.name} has no droplet id, so there is nothing to destroy; "
                      f"`fleet machines forget {args.name}` drops the row")
    code, out, err = doctl("compute", "droplet", "delete", str(row["provider_id"]), "--force",
                           timeout=PROVIDER_TIMEOUT)
    if code != 0:
        raise Refused(f"DigitalOcean refused to delete droplet {row['provider_id']}: "
                      f"{one_line(err or out)}")
    apply_changes({args.name: dict(row, state=DESTROYED, checked_at=now(), address="",
                                   detail=f"destroyed on {now()}; the disk is gone and the "
                                          "billing has stopped")})
    print(f"{args.name}: droplet {row['provider_id']} deleted; billing has stopped")
    return 0


def cmd_forget(args):
    if not NAME_RE.match(args.name or ""):
        raise Refused("a machine name is lower case letters, digits and -")
    with locked():
        rows = read_registry()
    row = rows.get(args.name)
    if not row:
        raise Refused(f"there is no machine called {args.name} in the registry")
    state = row.get("state")
    own = row.get("provider") != "do-droplet"
    if not (own or state == DESTROYED or (state == FAILED and not row.get("provider_id"))):
        raise Refused(f"{args.name} is a droplet in {state} and may still be billing; "
                      f"`fleet machines destroy {args.name} --confirm {args.name}` stops it, "
                      "and then it can be forgotten")
    apply_changes({args.name: None})
    print(f"{args.name}: dropped from the registry; nothing was destroyed")
    return 0


# --------------------------------------------------------------------------------------- argv

def parser():
    ap = argparse.ArgumentParser(prog="fleet machines", description=__doc__.splitlines()[0])
    subs = ap.add_subparsers(dest="command", required=True)

    listing = subs.add_parser("list", help="the registry, reconciled and advanced one step")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(run=cmd_list)

    plan = subs.add_parser("plan", help="the commands, the cloud-init and the live price")
    plan.add_argument("--provider", default="do-droplet")
    plan.add_argument("--name", required=True)
    plan.add_argument("--size", default=host_presets.DEFAULT_SIZE)
    plan.add_argument("--region", default=host_presets.preset("do-droplet")["regions"][0])
    plan.add_argument("--pubkey-file")
    plan.add_argument("--json", action="store_true")
    plan.set_defaults(run=cmd_plan)

    create = subs.add_parser("create", help="buy a droplet, at a price you confirm")
    create.add_argument("--provider", default="do-droplet")
    create.add_argument("--name", required=True)
    create.add_argument("--size", default=host_presets.DEFAULT_SIZE)
    create.add_argument("--region", default=host_presets.preset("do-droplet")["regions"][0])
    create.add_argument("--pubkey-file", required=True)
    create.add_argument("--confirm-usd", required=True, type=float)
    create.add_argument("--wait-pending", type=int, default=0,
                        help="seconds to watch the tag for a create whose answer was lost")
    create.set_defaults(run=cmd_create)

    add = subs.add_parser("add", help="a machine you already have")
    add.add_argument("--name", required=True)
    add.add_argument("--target", required=True)
    add.add_argument("--port")
    add.set_defaults(run=cmd_add)

    for name, function, help_text in (("check", cmd_check, "SSH into one machine and say what"
                                                           " state it is in"),
                                      ("adopt", cmd_adopt, "write the row of a droplet this"
                                                           " farm made and lost"),
                                      ("forget", cmd_forget, "drop a row; nothing is destroyed"),
                                      ("forget-attempt", cmd_forget_attempt,
                                       "drop a lost create that never appeared")):
        sub = subs.add_parser(name, help=help_text)
        sub.add_argument("name")
        sub.set_defaults(run=function)

    destroy = subs.add_parser("destroy", help="delete a droplet and stop its billing")
    destroy.add_argument("name")
    destroy.add_argument("--confirm", required=True)
    destroy.set_defaults(run=cmd_destroy)
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
