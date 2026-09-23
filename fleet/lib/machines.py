#!/usr/bin/env python3
"""The machines this farm owns: a registry, a provider, and no droplet that costs money invisibly.

A machine is a whole farm: systemd user services, tmux, worktrees, the dashboard, the installer
as it is. Two providers can be one: a DigitalOcean Droplet this farm creates, and any Linux box
you already reach over SSH. (A runner, one lane in a remote sandbox, is `fleet hosts` and
`fleet runner`, not this file.) The design record is `fleet/docs/design/hosting.md`, section 4.

  fleet machines list [--json]
  fleet machines plan --provider do-droplet --name N --size S --region R [--pubkey-file F]
  fleet machines create --provider do-droplet --name N --size S --region R
                        --pubkey-file F --confirm-usd 48
  fleet machines add --name N --target user@host [--port P]
  fleet machines check N
  fleet machines adopt N
  fleet machines destroy N --confirm N
  fleet machines forget N

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
PROVIDER_TIMEOUT = 60


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

def run(argv, timeout=PROVIDER_TIMEOUT, stdin_text=None):
    """(code, stdout, stderr). A missing binary is 127 and a timeout is 124; nothing raises."""
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            input=stdin_text if stdin_text is not None else None,
            stdin=None if stdin_text is not None else subprocess.DEVNULL)
        return done.returncode, done.stdout or "", done.stderr or ""
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not installed on this farm"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]}: no answer in {timeout} seconds"
    except OSError as error:                            # pragma: no cover - a broken PATH entry
        return 127, "", f"{argv[0]}: {error.strerror}"


def with_context(argv):
    """A doctl argv with this farm's context on it, as `doctl auth init --context murmur` made it.

    Every doctl call goes through here, the ones that create things most of all: a firewall made
    in another account's default context would leave the new droplet with no firewall at all.
    """
    context = os.environ.get("FLEET_DOCTL_CONTEXT", host_presets.DOCTL_CONTEXT)
    argv = [str(a) for a in argv]
    return argv + ["--context", context] if context else argv


def doctl(*args, **kwargs):
    """doctl, run with this farm's context."""
    return run(with_context(["doctl"] + list(args)), **kwargs)


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
    port = str(row.get("port") or "").strip()
    if port and port != "22":
        argv += ["-p", port]
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
            price = row.get("price_monthly")
            if price is None:
                break
            return round(float(price), 2), "live", "the price DigitalOcean gives today"
    return fallback, "list", (f"DigitalOcean's size list does not carry {size_slug}, so this is "
                              f"the {host_presets.LIST_PRICE_NOTE}")


def cloud_init(person_key, machines_key):
    """The whole first boot of a new droplet, as one cloud-config file.

    A user `farm` without sudo (so nothing on the box can be changed by a stolen agent token),
    both keys that may reach it, the packages the installer needs plus gh from GitHub's own apt
    repository exactly as farm/install.sh adds it, lingering services, and the dashboard bound
    to loopback before the installer ever runs. The loopback line is a runcmd run as the user,
    never write_files, which runs before the user exists and would leave root owning its home.
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
        "apt-get update -qq",
        "apt-get install -y -qq gh",
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
        "runcmd:",
    ]
    lines += [f"  - {json.dumps(command)}" for command in commands]
    return "\n".join(lines) + "\n"


def create_argv(name, size, region, key_id, user_data_path):
    """The exact droplet create, without --wait: nothing waits inside a request."""
    return ["doctl", "compute", "droplet", "create", name,
            "--image", IMAGE,
            "--size", size,
            "--region", region,
            "--tag-names", ",".join(["murmur", TAG_FARM, farm_tag()]),
            "--ssh-keys", str(key_id),
            "--user-data-file", user_data_path,
            "-o", "json"]


def firewall_argv():
    """SSH in, everything out. A DigitalOcean firewall with no outbound rules also cuts the
    farm off from GitHub and the model providers, which is the trap the research found."""
    return ["doctl", "compute", "firewall", "create",
            "--name", FIREWALL,
            "--tag-names", TAG_FARM,
            "--inbound-rules", ("protocol:tcp,ports:22,address:0.0.0.0/0 "
                                "protocol:tcp,ports:22,address:::/0"),
            "--outbound-rules", ("protocol:tcp,ports:0,address:0.0.0.0/0 "
                                 "protocol:udp,ports:0,address:0.0.0.0/0 "
                                 "protocol:icmp,address:0.0.0.0/0 "
                                 "protocol:tcp,ports:0,address:::/0 "
                                 "protocol:udp,ports:0,address:::/0")]


def plan_commands(name, size, region):
    """The commands `create` will run, for a person to read before they spend anything."""
    return [with_context(argv) for argv in (
        ["doctl", "compute", "ssh-key", "import", "murmur-farm-" + farm_id(),
         "--public-key-file", KEY + ".pub", "-o", "json"],
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
    return rows, ""


def public_address(droplet):
    for entry in ((droplet.get("networks") or {}).get("v4") or []):
        if entry.get("type") == "public" and entry.get("ip_address"):
            return entry["ip_address"]
    return ""


def droplet_price(droplet):
    price = (droplet.get("size") or {}).get("price_monthly")
    if price is None:
        listed = host_presets.size("do-droplet", droplet.get("size_slug") or "")
        price = listed["monthly_usd"] if listed else 0
    return round(float(price or 0), 2)


def ensure_key_imported():
    """This farm's public key on the account, imported once and found by fingerprint after."""
    ensure_machines_key()
    fingerprint = key_fingerprint(KEY + ".pub")
    rows, error = doctl_json("compute", "ssh-key", "list", "-o", "json", timeout=PROVIDER_TIMEOUT)
    if rows is None:
        raise Refused(f"DigitalOcean did not list this account's SSH keys: {error}")
    # The JSON key names doctl prints for a key are UNVERIFIED in the research pass, so the
    # fingerprint is matched first and the name is the fallback.
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


def ensure_firewall():
    """The `murmur-ssh-only` firewall, attached by tag, so every future droplet gets it."""
    rows, error = doctl_json("compute", "firewall", "list", "-o", "json",
                             timeout=PROVIDER_TIMEOUT)
    if rows is None:
        raise Refused(f"DigitalOcean did not list this account's firewalls: {error}")
    for row in rows:
        if row.get("name") == FIREWALL:
            return row.get("id") or FIREWALL
    code, out, err = doctl(*firewall_argv()[1:], timeout=PROVIDER_TIMEOUT)
    if code != 0:
        raise Refused(f"DigitalOcean refused the {FIREWALL} firewall: {one_line(err or out)}")
    return FIREWALL


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


def cmd_create(args):
    if args.provider != "do-droplet":
        raise Refused("only do-droplet can be created; your own machine is `fleet machines add`")
    check_arguments(args)
    person_key = read_public_key(args.pubkey_file)

    # The price is a provider call, so it is asked for before the lock is taken. The name check
    # and the `creating` row then happen under one lock with nothing in between: two presses at
    # once find each other's row, and only one of them ever reaches the provider.
    price, source, note = live_price(args.size)
    if abs(float(args.confirm_usd) - float(price)) > 0.005:
        raise Refused(f"the price moved: you confirmed ${float(args.confirm_usd):g} a month and "
                      f"{args.size} costs ${price:g} a month ({note}). Nothing was created; "
                      f"run `fleet machines plan` again and confirm the new price")
    if source != "live":
        raise Refused(f"DigitalOcean did not give a live price for {args.size} ({note}), so this "
                      "farm will not buy a droplet on an old number; log doctl in and try again")

    started = now()
    row = {"name": args.name, "provider": "do-droplet", "user": FARM_USER, "address": "",
           "port": "", "size": args.size, "monthly_usd": price, "region": args.region,
           "provider_id": "", "created_at": started, "state": CREATING, "checked_at": started,
           "detail": "this farm has asked DigitalOcean for it"}
    with locked():                                      # the row exists before the provider call
        rows = read_registry()
        if live_row(rows, args.name):
            raise Refused(f"{args.name} already has a live row ({rows[args.name]['state']}); "
                          "a retry must never buy a second droplet. Pick another name, or "
                          f"`fleet machines destroy {args.name} --confirm {args.name}`")
        rows[args.name] = row
        write_registry(rows)

    def failed(step, message):
        """Mark the row failed, and give back the refusal for the caller to raise."""
        apply_changes({args.name: {
            "state": FAILED, "checked_at": now(),
            "detail": (f"DigitalOcean refused at {step}: {message}. Run `fleet machines list`, "
                       f"destroy any droplet named {args.name} in the DigitalOcean console, "
                       f"then `fleet machines forget {args.name}`")}})
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
            out.write(cloud_init(person_key, machines_key_public()))
        os.chmod(user_data, 0o600)
        code, out_text, err = doctl(*create_argv(args.name, args.size, args.region, key_id,
                                                 user_data)[1:], timeout=PROVIDER_TIMEOUT)
    finally:
        try:
            os.unlink(user_data)
        except OSError:
            pass

    if code != 0:
        raise failed("the droplet create", one_line(err or out_text))
    try:
        made = json.loads(out_text or "[]")
    except ValueError:
        made = []
    made = made if isinstance(made, list) else [made]
    if not made or not made[0].get("id"):
        raise failed("the droplet create", "DigitalOcean answered without a droplet id; the "
                                           "next `fleet machines list` picks it up by name")

    apply_changes({args.name: {"provider_id": str(made[0]["id"]), "checked_at": now(),
                               "detail": "DigitalOcean is building it"}})
    print(f"{args.name}: droplet {made[0]['id']} asked for, ${price:g} a month until it is "
          "destroyed")
    print("`fleet machines list` walks it to needs-login and then prints the finish command")
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
                                      ("forget", cmd_forget, "drop a row; nothing is destroyed")):
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
