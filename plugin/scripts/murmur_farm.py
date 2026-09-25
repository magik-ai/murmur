#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""A farm on DigitalOcean from this laptop, one step at a time.

    preflight       doctl and its `murmur` login, an ssh key that works without a terminal,
                    GitHub, and which ways to reach the page this laptop can use
    questions       the questions still unanswered, as JSON
    answer          store one answer
    plan            the commands, the cloud-init file and the price; nothing is created
    apply           buy the droplet at the price typed back (--confirm-usd with --quote), or
                    adopt the one already bought, then wait for its first boot
    ssh-config      the `Host <name>` block in ~/.ssh/config, and the first, pinning probe
    finish          GitHub on the box (your terminal), then clone and install, non-interactive
    tailscale       join the box to your tailnet, or fall back to the tunnel and say why
    logins          Claude subscriptions and Codex: the commands for your terminal, verified
    open            the dashboard in your browser (a tunnel, or the tailnet address)
    forget-attempt  drop a create whose answer was lost and whose droplet never appeared
    status          where the flow stands and the next step

Every step prints one JSON object and is safe to run again: a stopped run resumes where it
stopped. The design record is fleet/docs/design/one-click-farm.md. The rules it holds to:

  Nothing interactive runs here. A login is a command printed for the person's own terminal,
  then verified by this script without a terminal.
  A purchase is never repeated. Before any create the farm's own tag is reconciled, a create
  whose answer was lost is pending (never failed), and a typed price buys one attempt only.
  No token or key is printed, logged or put on an argv. The DigitalOcean token stays in doctl's
  own config; the dashboard token goes to the browser through a one-shot 0600 file; the
  Tailscale key goes to the box on ssh's stdin.
  The person's current doctl context is never switched; every call names `--context murmur`.

The droplet, its registry row and the farm id are fleet/lib/machines.py's, reached through
plugin/lib, so this script and `fleet machines` are one implementation.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import http.client
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import host_presets  # noqa: E402
import machines  # noqa: E402

# Every doctl call this flow makes, here or in machines.py, names the `murmur` context: an
# inherited FLEET_DOCTL_CONTEXT or DIGITALOCEAN_CONTEXT may point at another account entirely.
machines.pin_context(host_presets.DOCTL_CONTEXT)

HOME = os.path.expanduser("~")
MURMUR = os.path.join(HOME, ".config", "murmur")
KNOWN = os.path.join(MURMUR, "known_hosts")
STATE_FILE = os.path.join(MURMUR, "farm.json")
TS_KEY = os.path.join(MURMUR, "tailscale.key")
SSH_DIR = os.path.join(HOME, ".ssh")
# The person's own ssh config, and the system config ssh reads after it. Both can be pointed
# elsewhere, so a test never reads or writes the machine's real ones.
DEFAULT_SSH_CONFIG = os.path.join(SSH_DIR, "config")
SSH_CONFIG = os.environ.get("MURMUR_SSH_CONFIG") or DEFAULT_SSH_CONFIG
DEFAULT_KEY = os.path.join(SSH_DIR, "id_ed25519")

# The box. The user is always `farm` (cloud-init makes it), so every remote path is written out
# in full: nothing is left for the laptop's shell, or the box's `bash -c`, to expand.
FARM_HOME = "/home/farm"
LOCAL_BIN = FARM_HOME + "/.local/bin"
FLEET_BIN = LOCAL_BIN + "/fleet"
CLAUDE_BIN = LOCAL_BIN + "/claude"
CODEX_BIN = LOCAL_BIN + "/codex"
REMOTE_ENV = FARM_HOME + "/.config/fleet/env"
REMOTE_REPO = FARM_HOME + "/work/murmur"
REMOTE_CACHE = FARM_HOME + "/.cache/murmur"
ACCOUNTS_DIR = FARM_HOME + "/.fleet/claude-accounts"
REPO = os.environ.get("MURMUR_FARM_REPO", "magik-ai/murmur")
DASH_PORT = 7878
REMOTE_DASH_PORT = int(os.environ.get("MURMUR_FARM_REMOTE_PORT") or DASH_PORT)
TAILSCALE_HELPER = "/usr/local/sbin/murmur-tailscale-up"
UNIT = "fleet-dashboard.service"

MARK_BEGIN = "# >>> murmur farm: written by /murmur:farm, rewritten on every run >>>"
MARK_END = "# <<< murmur farm <<<"
# The port a new droplet's ssh and its firewall answer on.
SSH_PORT = "22"
# The address the plan's rehearsal writes into the block: TEST-NET-1 (RFC 5737), which no
# machine answers and no config names.
PLACEHOLDER = "192.0.2.1"
SYSTEM_SSH_CONFIG = os.environ.get("MURMUR_SYSTEM_SSH_CONFIG") or "/etc/ssh/ssh_config"

POLL = float(os.environ.get("MURMUR_FARM_POLL") or 10)
REACH_SECONDS = float(os.environ.get("MURMUR_FARM_REACH_SECONDS") or 30)
OPEN_LINGER = float(os.environ.get("MURMUR_FARM_OPEN_LINGER") or 20)

ACCOUNT_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.~+/=-]{8,512}$")

# Waiting on the person is its own exit code, so the skill can tell "do this, then run me again"
# from "this is wrong".
DONE, REFUSED, WAITING = 0, 1, 2


class Stop(Exception):
    """A step that cannot go on. `code` is REFUSED or WAITING; `commands` are for the person."""

    def __init__(self, said, code=REFUSED, commands=(), **extra):
        super().__init__(said)
        self.said = said
        self.code = code
        self.commands = list(commands)
        self.extra = extra


# ------------------------------------------------------------------------------------ state

def ensure_murmur_dir():
    """~/.config/murmur, mode 0700, before any probe: the known-hosts file and the tunnel's
    control socket live here, and ssh only warns about a known-hosts file it cannot open."""
    os.makedirs(MURMUR, mode=0o700, exist_ok=True)
    os.chmod(MURMUR, 0o700)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            state = json.load(handle)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    ensure_murmur_dir()
    tmp = STATE_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def answers(state):
    return state.setdefault("answers", {})


def need(state, *keys):
    missing = [key for key in keys if answers(state).get(key) in (None, "")]
    if missing:
        raise Stop(f"unanswered: {', '.join(missing)}; run `questions` and `answer` first")
    return [answers(state)[key] for key in keys]


def run(argv, timeout=60, stdin_text=None):
    return machines.run([str(a) for a in argv], timeout=timeout, stdin_text=stdin_text)


def platform_name():
    return os.environ.get("MURMUR_PLATFORM") or platform.system()


def is_wsl():
    path = os.environ.get("MURMUR_PROC_VERSION", "/proc/version")
    try:
        with open(path, encoding="utf-8") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


# ------------------------------------------------------------------------------------ ssh

def host_key_options():
    """On every ssh this script runs or prints for a farm, on the command line, where no config
    file can loosen them: trust a new droplet's key once, refuse a changed one."""
    return ["-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={KNOWN}"]


def login_options():
    """Port 22 and user farm, on the command line of every ssh this script runs or prints for a
    farm: a later change to the person's config can move neither."""
    return ["-p", SSH_PORT, "-l", machines.FARM_USER]


def ssh_words(name, tty=False, batch=True, extra=()):
    words = ["ssh"] + (["-t"] if tty else []) + host_key_options() + login_options()
    if batch:
        words += ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    return words + list(extra) + [name]


def remote_string(words):
    """A remote command as the one string ssh hands the box's shell, quoted so it arrives as
    written. A remote word never carries `~` or `$`."""
    return shlex.join([str(w) for w in words])


def on_farm(name, words, timeout=60, stdin_text=None):
    """(code, stdout, stderr) of one command on the farm. ssh's own failure (255: refused, a
    changed host key, a key it will not take) stops the step, so it is never read as the
    command's answer."""
    code, out, err = run(ssh_words(name) + [remote_string(words)], timeout=timeout,
                         stdin_text=stdin_text)
    if code == 255:
        raise Stop(f"ssh to {name} failed, so nothing more runs on it: "
                   f"{machines.one_line(err or out) or 'exit 255'}")
    return code, out, err


def printed(name, words, tty=True, extra=()):
    """A command for the person's own terminal, exactly as it must be typed."""
    return shlex.join(ssh_words(name, tty=tty, batch=False, extra=extra)
                      + [remote_string(words)])


def ssh_g(name, config=None):
    """What ssh would really use for this name, with this script's host key options on the line
    (each setting's first value, the first identity file among them). `-p` and `-l` are left
    off, so the port and the user are the ones the config gives a plain `ssh <name>`."""
    chosen = ["-F", config] if config else []
    code, out, err = run(["ssh", "-G"] + chosen + host_key_options() + [name], timeout=20)
    if code != 0:
        raise Stop(f"`ssh -G {name}` failed: {machines.one_line(err or out)}")
    seen = {}
    for line in out.splitlines():
        key, _, value = line.partition(" ")
        seen.setdefault(key.lower(), value.strip())
    return seen


# `ssh -G` settings that carry a connection past its HostName, or check its host key under
# another name. This script sets none of them, so on the farm's name any of them means ssh goes
# (or trusts) somewhere the checked address does not show. ssh -G prints each as its lowercase
# key, and leaves ProxyCommand and ProxyJump out when they are unset or `none`.
ROUTING = (("proxycommand", "ProxyCommand"), ("proxyjump", "ProxyJump"),
           ("hostkeyalias", "HostKeyAlias"))


def marked_section(lines):
    """(begin, end) line indexes of this script's marked section, or None when it has none.

    Anything but one begin marker followed by one end marker is refused, and nothing is written:
    a begin with no end would make the section run to the end of the file, and a rewrite would
    swallow the Host blocks after it.
    """
    begins = [i for i, line in enumerate(lines) if line.strip() == MARK_BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == MARK_END]
    if not begins and not ends:
        return None
    if len(begins) == 1 and len(ends) == 1 and begins[0] < ends[0]:
        return begins[0], ends[0]
    if len(begins) > 1:
        fault = (f"line {begins[1] + 1} is a second begin marker (the first is on line "
                 f"{begins[0] + 1})")
    elif len(ends) > 1:
        fault = f"line {ends[1] + 1} is a second end marker (the first is on line {ends[0] + 1})"
    elif not ends:
        fault = f"line {begins[0] + 1} opens the section and no end marker `{MARK_END}` closes it"
    elif not begins:
        fault = f"line {ends[0] + 1} closes the section and no begin marker `{MARK_BEGIN}` opens it"
    else:
        fault = f"the end marker on line {ends[0] + 1} comes before the begin marker on line " \
                f"{begins[0] + 1}"
    raise Stop(f"the murmur section of {SSH_CONFIG} is broken: {fault}. Fix that line by hand "
               "(put the missing marker back where the section ends, or delete the stray one) "
               "and run this step again; the file was not changed")


def section_hosts(lines):
    """{name: {option: value}} of the Host blocks inside this script's marked section."""
    bounds = marked_section(lines)
    if bounds is None:
        return {}
    hosts, current = {}, None
    for line in lines[bounds[0] + 1:bounds[1]]:
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        if words[0].lower() == "host" and len(words) > 1:
            current = words[1]
            hosts[current] = {}
        elif current:
            hosts[current][words[0].lower()] = " ".join(words[1:])
    return hosts


# ssh reads an Include at most this deep, and so does the scan below.
INCLUDE_DEPTH = 16


def config_words(line):
    """(keyword, arguments) of one ssh_config line, or None for a blank line or a comment. ssh
    takes `Keyword value` and `Keyword=value` alike, and quoted arguments."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    match = re.match(r"([A-Za-z]+)\s*(?:=\s*|\s+|$)(.*)$", text)
    if not match:
        return None
    try:
        words = shlex.split(match.group(2), comments=True)
    except ValueError:
        words = match.group(2).split()
    return match.group(1).lower(), words


def include_path(word, base=None):
    """One Include argument as the absolute path ssh looks at: `~` is the home folder, and a
    relative path is under ~/.ssh for the user config and under the system config's own folder
    (/etc/ssh) for the system one."""
    path = os.path.expanduser(word)
    return path if os.path.isabs(path) else os.path.join(base or SSH_DIR, path)


def included_files(words, base=None):
    """The files one Include line names, found as ssh finds them (see include_path), a glob's
    matches in sorted order."""
    found = []
    for word in words:
        found += sorted(glob.glob(include_path(word, base)))
    return found


def config_lines(path=None, depth=0, base=None):
    """(file, line number, keyword, arguments, text) of every line ssh reads from the person's
    config: ~/.ssh/config outside this script's marked section, and in place of each Include
    line the files it names, to ssh's own depth. `base` is where a relative Include is found."""
    top = path is None
    path = path or SSH_CONFIG
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    bounds = marked_section(lines) if top else None
    rows = []
    for index, line in enumerate(lines):
        if bounds and bounds[0] <= index <= bounds[1]:
            continue
        parsed = config_words(line)
        if not parsed:
            continue
        keyword, words = parsed
        rows.append((path, index + 1, keyword, words, line.strip()))
        if keyword == "include" and depth < INCLUDE_DEPTH:
            for included in included_files(words, base):
                rows += config_lines(included, depth + 1, base)
    return rows


def every_config_line():
    """Every line ssh reads for a plain `ssh <name>`, in its order: the person's config and what
    it Includes, then the system config and what that Includes. ssh reads both, so a name the
    system config claims is as taken as one the person's own config claims."""
    return (config_lines() +
            config_lines(SYSTEM_SSH_CONFIG, base=os.path.dirname(SYSTEM_SSH_CONFIG)))


def where(path, number, text):
    """A config line as a person finds it: `~/.ssh/config line 3: Host farm`."""
    shown = "~" + path[len(HOME):] if path.startswith(HOME + os.sep) else path
    return f"{shown} line {number}: {text}"


def named_patterns(keyword, words):
    """The host patterns a Host line, or a Match line's host and originalhost criteria, name."""
    if keyword == "host":
        return words
    found = []
    if keyword == "match":
        for index, word in enumerate(words[:-1]):
            if word.lower() in ("host", "originalhost"):
                found += words[index + 1].split(",")
    return found


def claims(name):
    """The Host and Match lines of the person's config, or of the system config, that name this
    name exactly, outside this script's own section. A wildcard (`Host *`, `Host f*`) names no
    name: what it gives this one, the rehearsal at `plan` sees."""
    return [where(path, number, text)
            for path, number, keyword, words, text in every_config_line()
            if name in [pattern.lower() for pattern in named_patterns(keyword, words)]]


def name_is_free(name):
    """A name no Host or Match line of the person's ssh config or the system config names, or
    only this script's own marked section does.

    A literal claim, not a guess from what ssh prints: a `Host farm` block is the person's own
    even when every setting in it equals ssh's defaults, and the new farm's block would take the
    name over from it.
    """
    taken = claims(name)
    if taken:
        return False, (f"an ssh config ssh reads already has a block for `{name}` "
                       f"({'; '.join(taken)}); pick another name for the new farm, so the login "
                       "and the install never reach that machine and its name stays yours")
    return True, ""


# The options of this script's block, in the order it writes them.
BLOCK_OPTIONS = (("hostname", "HostName"), ("port", "Port"), ("user", "User"),
                 ("identityfile", "IdentityFile"), ("identitiesonly", "IdentitiesOnly"),
                 ("stricthostkeychecking", "StrictHostKeyChecking"),
                 ("userknownhostsfile", "UserKnownHostsFile"))


def read_ssh_config():
    try:
        with open(SSH_CONFIG, encoding="utf-8") as handle:
            return handle.read().splitlines()
    except FileNotFoundError:
        return []


def config_with_block(lines, name, address, key):
    """The config's lines with this farm's Host block written into the marked section.

    The section sits before the first Host or Match line, so a later `Host *` cannot hand this
    name another user, port or address; the lines above that are global and stay where they
    are. `write_ssh_block` writes exactly this, and `rehearse` resolves exactly this.
    """
    hosts = section_hosts(lines)
    hosts[name] = {"hostname": address, "port": SSH_PORT, "user": machines.FARM_USER,
                   "identityfile": key, "identitiesonly": "yes",
                   "stricthostkeychecking": "accept-new", "userknownhostsfile": KNOWN}
    block = [MARK_BEGIN]
    for host in sorted(hosts):
        options = hosts[host]
        block.append(f"Host {host}")
        for option, spelled in BLOCK_OPTIONS:
            if options.get(option):
                block.append(f"  {spelled} {options[option]}")
    block.append(MARK_END)

    lines = list(lines)
    bounds = marked_section(lines)
    if bounds:
        lines[bounds[0]:bounds[1] + 1] = block
    else:
        at = len(lines)
        for index, line in enumerate(lines):
            first = (line.split() or [""])[0].lower()
            if first in ("host", "match"):
                at = index
                break
        lines[at:at] = block + ([""] if at < len(lines) else [])
    return lines


def write_ssh_block(name, address, key):
    """Write or rewrite this farm's Host block inside the marked section of ~/.ssh/config."""
    os.makedirs(SSH_DIR, mode=0o700, exist_ok=True)
    lines = config_with_block(read_ssh_config(), name, address, key)
    tmp = SSH_CONFIG + ".murmur.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    os.replace(tmp, SSH_CONFIG)


def resolution_faults(seen, address, key):
    """[(ssh_config keyword, sentence)] of every way `ssh -G` for the farm's name differs from
    where this script sends it: the address, port 22, user farm, the script's key offered first,
    no proxy or host key alias, and the host key rules. Empty when ssh goes where it must."""
    faults = []
    if seen.get("hostname") != address:
        faults.append(("hostname", f"it goes to {seen.get('hostname')}, not {address}"))
    if seen.get("port") != SSH_PORT:
        faults.append(("port", f"it connects to port {seen.get('port')}, not {SSH_PORT}"))
    if seen.get("user") != machines.FARM_USER:
        faults.append(("user", f"it logs in as {seen.get('user')}, not {machines.FARM_USER}"))
    first = seen.get("identityfile") or ""
    if os.path.expanduser(first) != key:
        faults.append(("identityfile", f"it offers the key {first or '(none)'} first, not "
                                       f"{key}"))
    if seen.get("stricthostkeychecking") != "accept-new":
        faults.append(("stricthostkeychecking",
                       f"host keys are checked as {seen.get('stricthostkeychecking')}"))
    if (seen.get("userknownhostsfile") or "").split(" ")[0] != KNOWN:
        faults.append(("userknownhostsfile",
                       f"known hosts are read from {seen.get('userknownhostsfile')}"))
    for keyword, spelled in ROUTING:
        if seen.get(keyword) and seen[keyword].lower() != "none":
            faults.append((keyword, f"it goes through {spelled} {seen[keyword]}"))
    return faults


def causes(keyword, value):
    """The person's config lines that set this option, as `file line N: text`: the ones whose
    value is the one ssh reports first, else every one that sets it."""
    rows = [(path, number, words, text)
            for path, number, found, words, text in every_config_line() if found == keyword]
    same = [row for row in rows if " ".join(row[2]).lower() == (value or "").lower()]
    return [where(path, number, text) for path, number, _words, text in (same or rows)]


def explained(faults, seen):
    """Each fault with the config lines behind it, as one phrase."""
    phrases = []
    for keyword, sentence in faults:
        lines = causes(keyword, seen.get(keyword))
        phrases.append(f"{sentence} (set by {'; '.join(lines)})" if lines else
                       f"{sentence} (no line of your ssh config or {SYSTEM_SSH_CONFIG} "
                       f"sets {keyword})")
    return "; ".join(phrases)


def config_word(path):
    """A path as one ssh_config argument: quoted when it holds a space or a quote."""
    if not re.search(r'[\s"\'\\]', path):
        return path
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def rehearsal_lines(lines, base, folder, copies, depth=0):
    """These config lines as the rehearsal writes them: every Include made to name, by absolute
    path, what ssh would really read for it.

    ssh reads a relative Include under ~/.ssh in the user config and under /etc/ssh in the
    system config, and a file an Include names keeps the config's side. The rehearsal file is
    one user config, so a relative path copied into it from the system config would be looked
    for under ~/.ssh. Each Include argument is therefore resolved against `base`, and each file
    it matches is replaced by a scratch copy in `folder`, made the same way, to ssh's own depth.
    One line stays one line, so line numbers stay the original file's."""
    written = []
    for line in lines:
        parsed = config_words(line)
        if not parsed or parsed[0] != "include":
            written.append(line)
            continue
        paths = []
        for word in parsed[1]:
            matched = included_files([word], base) if depth < INCLUDE_DEPTH else []
            paths += ([rehearsal_copy(path, base, folder, copies, depth + 1) for path in matched]
                      or [include_path(word, base)])
        written.append("Include " + " ".join(config_word(path) for path in paths))
    return written


def rehearsal_copy(path, base, folder, copies, depth):
    """A scratch copy of one config file with its Includes made absolute (rehearsal_lines), or
    the path itself when it cannot be read (ssh skips it as well)."""
    key = (os.path.realpath(path), depth)
    if key not in copies:
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except (OSError, UnicodeDecodeError):
            return path
        copy = os.path.join(folder, f"{len(copies) + 1:03d}-{os.path.basename(path)}")
        copies[key] = copy
        with open(copy, "w", encoding="utf-8") as handle:
            handle.write("\n".join(rehearsal_lines(lines, base, folder, copies, depth)) + "\n")
    return copies[key]


def resolve_as_ssh(name, lines):
    """`ssh -G` for this name with these user config lines, read the way ssh reads its configs:
    a scratch copy of the lines that ends with `Include` of a scratch copy of the system config,
    so the person's config comes first and the system config (and what it Includes) after it,
    exactly as a plain `ssh <name>` reads them. `-F` alone would skip the system config. Every
    Include in the copies names an absolute path, found where the real ssh would look for it."""
    ensure_murmur_dir()
    folder = tempfile.mkdtemp(prefix="murmur-ssh-rehearsal.", dir=MURMUR)
    try:
        copies = {}
        user = rehearsal_lines(list(lines), SSH_DIR, folder, copies)
        system = rehearsal_copy(SYSTEM_SSH_CONFIG, os.path.dirname(SYSTEM_SSH_CONFIG), folder,
                                copies, 0)
        scratch = os.path.join(folder, "config")
        with open(scratch, "w", encoding="utf-8") as handle:
            handle.write("\n".join(user + ["", "Match all",
                                           f"Include {config_word(system)}"]) + "\n")
        return ssh_g(name, config=scratch)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def rehearse(name, key):
    """Before any purchase: where ssh will really send this name once the block is written.

    The person's config is copied to a scratch file with the exact block `ssh-config` will
    write, at the exact place it will write it, holding a placeholder address, and the system
    config after it as ssh reads it. `ssh -G -F <scratch>` must then go to the placeholder, on
    port 22, as farm, with this script's key first, no proxy, and the host key rules. Anything
    else refuses, naming the setting and the line of the person's config behind it.
    """
    # A config line that names the name, the system config's included, may have appeared since
    # the name was answered: the block would take the name over from it, so no quote either.
    free, why = name_is_free(name)
    if not free:
        raise Stop(f"{why}. Nothing was bought; answer the name question again, then run "
                   "`plan` again")
    seen = resolve_as_ssh(name, config_with_block(read_ssh_config(), name, PLACEHOLDER, key))
    faults = resolution_faults(seen, PLACEHOLDER, key)
    if faults:
        raise Stop(f"with the block this script would write, `ssh {name}` would not reach the "
                   f"new farm as it must: {explained(faults, seen)}. Nothing was bought. Change "
                   "that line of your ssh config and run `plan` again")


def check_resolution(name, address, key):
    """After the block is written and before any remote command: the rehearsal's checks, run on
    the real config against the droplet's real address. With the configs pointed elsewhere (a
    test), it reads those, in ssh's order, instead of the machine's own."""
    moved = SSH_CONFIG != DEFAULT_SSH_CONFIG or "MURMUR_SYSTEM_SSH_CONFIG" in os.environ
    seen = resolve_as_ssh(name, read_ssh_config()) if moved else ssh_g(name)
    faults = resolution_faults(seen, address, key)
    if faults:
        raise Stop(f"`ssh {name}` does not reach the new farm as it must "
                   f"({explained(faults, seen)}). An earlier line in ~/.ssh/config wins over "
                   "this script's section; nothing was run on the farm")


def remote_ready(state):
    """The farm's name and address, checked, for any step that runs a command on the box."""
    name = need(state, "name")[0]
    farm = state.get("farm") or {}
    if not farm.get("pinned") or not farm.get("address"):
        raise Stop("the ssh step has not run yet; run `ssh-config` first", code=WAITING)
    check_resolution(name, farm["address"], key_paths(state)[0])
    return name, farm["address"]


# ------------------------------------------------------------------------------ preflight

def key_paths(state):
    key = answers(state).get("key") or DEFAULT_KEY
    return key, key + ".pub"


def key_works_without_a_terminal(key, pub):
    """(True, how) when a batch ssh can use this key: no passphrase, or the agent holds it.
    The public key `ssh-keygen -y` prints is thrown away; a passphrase never reaches an argv."""
    code, _out, _err = run(["ssh-keygen", "-y", "-P", "", "-f", key], timeout=20)
    if code == 0:
        return True, "the key has no passphrase"
    try:
        with open(pub, encoding="utf-8") as handle:
            wanted = " ".join(handle.read().split()[:2])
    except OSError:
        wanted = ""
    code, out, _err = run(["ssh-add", "-L"], timeout=20)
    if code == 0 and wanted and any(" ".join(line.split()[:2]) == wanted
                                    for line in out.splitlines()):
        return True, "the ssh agent holds the key"
    return False, ""


def tailscale_on_laptop():
    """(usable, reason). Only true where the browser runs, on a laptop that is on a tailnet."""
    if is_wsl():
        return False, ("this is WSL: the browser is on the Windows side, and so is Tailscale, "
                       "so the page is reached through the tunnel (WSL forwards it to Windows)")
    code, out, err = run(["tailscale", "status", "--json"], timeout=20)
    if code == 127:
        return False, "Tailscale is not installed on this laptop"
    try:
        backend = (json.loads(out or "{}") or {}).get("BackendState", "")
    except ValueError:
        backend = ""
    if backend != "Running":
        return False, (f"Tailscale on this laptop is not connected ({backend or 'no answer'}"
                       f"{': ' + machines.one_line(err) if err and not backend else ''})")
    return True, ""


def doctl_login_command():
    """`doctl auth init --context murmur` for the person's terminal. A DIGITALOCEAN_* variable
    there would win over what they paste (a token in DIGITALOCEAN_ACCESS_TOKEN is saved under
    `murmur` without a prompt), so the line unsets each one this laptop has."""
    login = host_presets.preset("do-droplet")["login"]
    inherited = sorted(key for key in os.environ
                       if key.upper().startswith(machines.DOCTL_ENV_PREFIX))
    if not inherited:
        return login
    return shlex.join(["env"] + [part for key in inherited for part in ("-u", key)]) \
        + " " + login


def cmd_preflight(args, state):
    ensure_murmur_dir()
    checks = []

    def check(check_id, ok, said, command="", ask=""):
        checks.append({"id": check_id, "ok": bool(ok), "said": said, "command": command,
                       "ask": ask})

    darwin = platform_name() == "Darwin"
    if not shutil.which("doctl") and darwin and shutil.which("brew") and args.install_doctl:
        code, _out, err = run(["brew", "install", "doctl"], timeout=900)
        if code != 0:
            check("doctl", False, f"`brew install doctl` failed: {machines.one_line(err)}")
    if shutil.which("doctl"):
        check("doctl", True, "doctl is installed")
        rows, error = machines.doctl_json("account", "get", "-o", "json", timeout=30)
        if rows:
            email = (rows[0] or {}).get("email") or "an account"
            check("doctl-login", True, f"doctl's `{machines.host_presets.DOCTL_CONTEXT}` context "
                                       f"is logged in as {email}")
        else:
            check("doctl-login", False,
                  "doctl has no working `murmur` login. Run this in your own terminal and paste "
                  "a DigitalOcean API token there (never here); your current doctl context is "
                  f"not changed ({error})",
                  command=doctl_login_command())
    elif not any(c["id"] == "doctl" for c in checks):
        if darwin and shutil.which("brew"):
            check("doctl", False, "doctl is not installed; Homebrew can install it",
                  ask="install doctl with `brew install doctl`? (run preflight --install-doctl)")
        else:
            check("doctl", False, "doctl is not installed: "
                  + host_presets.preset("do-droplet")["install"])

    key, pub = key_paths(state)
    if not os.path.exists(pub) and args.make_key and not os.path.exists(key):
        os.makedirs(SSH_DIR, mode=0o700, exist_ok=True)
        code, _out, err = run(["ssh-keygen", "-t", "ed25519", "-N", "", "-q",
                               "-C", "murmur-farm", "-f", key], timeout=60)
        if code != 0:
            check("ssh-key", False, f"ssh-keygen failed: {machines.one_line(err)}")
    if os.path.exists(pub):
        try:
            machines.read_public_key(pub)
            check("ssh-key", True, f"the key {pub}")
        except machines.Refused as error:
            check("ssh-key", False, str(error))
        works, how = key_works_without_a_terminal(key, pub)
        if works:
            check("ssh-key-batch", True, how)
        else:
            add = (["ssh-add", "--apple-use-keychain", key] if darwin else ["ssh-add", key])
            check("ssh-key-batch", False,
                  "the key has a passphrase and the ssh agent does not hold it, so this "
                  "script's ssh (which has no terminal) cannot use it. Add it to the agent in "
                  "your own terminal; the passphrase is typed there, never here",
                  command=shlex.join(add))
        answers(state)["key"] = key
    elif not any(c["id"] == "ssh-key" for c in checks):
        check("ssh-key", False, f"there is no ssh key at {pub}",
              ask="make one with `ssh-keygen -t ed25519` and no passphrase? (run preflight "
                  "--make-key); for a key with a passphrase, run ssh-keygen -t ed25519 in your "
                  "own terminal, then ssh-add it")

    code, _out, _err = run(["gh", "auth", "status"], timeout=30)
    check("github", code == 0, "GitHub is logged in on this laptop" if code == 0 else
          "GitHub is not logged in on this laptop (the farm gets its own login later)",
          command="" if code == 0 else "gh auth login")

    usable, reason = tailscale_on_laptop()
    state["access_options"] = ["tunnel", "tailscale"] if usable else ["tunnel"]
    state["tailscale_reason"] = reason
    ready = all(c["ok"] for c in checks)
    state["preflight_ok"] = ready
    save_state(state)
    commands = [c["command"] for c in checks if c["command"] and not c["ok"]]
    said = ("ready: nothing is bought until you type the price back" if ready else
            "not ready: " + "; ".join(c["said"] for c in checks if not c["ok"]))
    return (DONE if ready else WAITING), {
        "said": said, "checks": checks, "access_options": state["access_options"],
        "tailscale": reason or "this laptop is on a tailnet", "run_in_your_terminal": commands}


# ------------------------------------------------------------------------------ questions

REGION_BY_ZONE = [
    ("Europe/London", "lon1"), ("Europe/Dublin", "lon1"), ("Europe/Lisbon", "lon1"),
    ("Europe/Amsterdam", "ams3"), ("Europe/Brussels", "ams3"), ("Europe/", "fra1"),
    ("America/Toronto", "tor1"), ("America/Montreal", "tor1"),
    ("America/Los_Angeles", "sfo3"), ("America/Vancouver", "sfo3"), ("America/Denver", "sfo3"),
    ("America/Phoenix", "sfo3"), ("America/", "nyc3"), ("Asia/Kolkata", "blr1"),
    ("Asia/Calcutta", "blr1"), ("Asia/", "sgp1"), ("Australia/", "syd1"),
]


def laptop_timezone():
    zone = os.environ.get("TZ", "").lstrip(":")
    if zone:
        return zone
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return ""


def nearest_region():
    zone = laptop_timezone()
    offered = host_presets.preset("do-droplet")["regions"]
    for prefix, region in REGION_BY_ZONE:
        if zone.startswith(prefix) and region in offered:
            return region
    return "fra1"


def live_sizes():
    """The preset's sizes with DigitalOcean's price today when doctl answers."""
    rows, _error = machines.doctl_json("compute", "size", "list", "-o", "json", timeout=30) \
        if shutil.which("doctl") else (None, "")
    live = {row.get("slug"): row.get("price_monthly") for row in (rows or [])}
    sizes = []
    for size in host_presets.preset("do-droplet")["sizes"]:
        price = machines.usd(live.get(size["slug"]))
        entry = {"slug": size["slug"], "label": size["label"],
                 "monthly_usd": round(price, 2) if price is not None
                 else size["monthly_usd"],
                 "price": "today's price" if price is not None else host_presets.LIST_PRICE_NOTE}
        if size["vcpu"] <= 2:
            # farm/install.sh sizes the memory limits to a machine this small.
            entry["note"] = ("cheaper, for light work: a new agent starts while at least 1 GB "
                             "of memory is free")
        sizes.append(entry)
    return sizes


def questions(state):
    options = state.get("access_options") or ["tunnel"]
    return [
        {"id": "name", "prompt": "The farm's name (its ssh name on this laptop, and the "
                                 "droplet's name)", "default": "farm", "choices": []},
        {"id": "size", "prompt": "Its size", "default": host_presets.DEFAULT_SIZE,
         "choices": live_sizes()},
        {"id": "region", "prompt": "Where it runs (nearest by this laptop's time zone)",
         "default": nearest_region(),
         "choices": host_presets.preset("do-droplet")["regions"]},
        {"id": "access", "prompt": "How you reach its dashboard: an ssh tunnel (nothing to "
                                   "install) or Tailscale (your tailnet)",
         "default": "tunnel", "choices": options,
         "note": state.get("tailscale_reason") or ""},
        {"id": "codex", "prompt": "Also run Codex agents on it?", "default": "no",
         "choices": ["no", "yes"]},
        {"id": "accounts", "prompt": "Further Claude subscriptions, after the first, as short "
                                     "names separated by commas (empty for one subscription)",
         "default": "", "choices": []},
        {"id": "hq_repo", "prompt": "The head office repository to join (owner/name), or "
                                    "empty for a new one of your own", "default": "",
         "choices": []},
    ]


def cmd_questions(args, state):
    rows = questions(state)
    if not args.all:
        rows = [row for row in rows if row["id"] not in answers(state)]
    return DONE, {"questions": rows}


def cmd_answer(args, state):
    value = (args.value or "").strip()
    known = {row["id"]: row for row in questions(state)}
    if args.id not in known:
        raise Stop(f"there is no question {args.id}; the questions are {', '.join(known)}")
    row = known[args.id]
    if value == "":
        value = row["default"]
    if args.id == "name":
        if not machines.NAME_RE.match(value):
            raise Stop("a farm name is lower case letters, digits and -, starting with a "
                       "letter, 2 to 31 characters")
        free, why = name_is_free(value)
        if not free:
            raise Stop(why)
    elif args.id == "size":
        if value not in [size["slug"] for size in row["choices"]]:
            raise Stop(f"{value} is not a size offered here: "
                       + ", ".join(size["slug"] for size in row["choices"]))
    elif args.id in ("region", "access", "codex"):
        if value not in row["choices"]:
            extra = f" ({row.get('note')})" if row.get("note") else ""
            raise Stop(f"{value} is not one of {', '.join(row['choices'])}{extra}")
    elif args.id == "accounts":
        names = [part.strip() for part in value.split(",") if part.strip()]
        for account in names:
            if not ACCOUNT_RE.match(account) or account in ("default", "auto"):
                raise Stop(f"{account} is not a plain account name (lower case, digits and -, "
                           "not `default` or `auto`)")
        if len(set(names)) != len(names):
            raise Stop("two subscriptions have the same name")
        value = ",".join(names)
    elif args.id == "hq_repo" and value and not REPO_RE.match(value):
        raise Stop("the head office repository is owner/name, for example you/agent-hq-office")
    answers(state)[args.id] = value
    save_state(state)
    return DONE, {"said": f"{args.id}: {value or '(empty)'}", "id": args.id, "value": value}


# ---------------------------------------------------------------------------------- plan

def person_key(state):
    _key, pub = key_paths(state)
    try:
        return machines.read_public_key(pub)
    except machines.Refused as error:
        raise Stop(f"{error}; run `preflight` first")


# What a quote binds besides its price: every answer that changes what is bought or how it is
# built. Apply recomputes each one and buys nothing if any differs from the plan the person saw.
QUOTE_TERMS = ("name", "size", "region", "image", "access", "codex", "hq_repo",
               "cloud_init_sha256")


def plan_terms(state):
    """(the cloud-init file, the terms a quote binds), from the answers as they stand now."""
    name, size, region, access = need(state, "name", "size", "region", "access")
    codex = answers(state).get("codex") == "yes"
    cloud = machines.cloud_init(person_key(state), machines.machines_key_public(),
                                tailscale=access == "tailscale", node=codex)
    return cloud, {"name": name, "size": size, "region": region, "image": machines.IMAGE,
                   "access": access, "codex": codex,
                   "hq_repo": answers(state).get("hq_repo") or "",
                   "cloud_init_sha256": hashlib.sha256(cloud.encode("utf-8")).hexdigest()}


def plan_changes(quote, terms):
    """The terms that differ between a quote and the plan as it stands now, as phrases."""
    changes = []
    for term in QUOTE_TERMS:
        then, now = quote.get(term), terms.get(term)
        if then == now:
            continue
        if term == "cloud_init_sha256":
            changes.append("the cloud-init file is not the one shown")
        else:
            changes.append(f"{term} was {plan_word(then)} and is now {plan_word(now)}")
    return changes


def plan_word(value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value) if value not in (None, "") else "(empty)"


def cmd_plan(args, state):
    name, size, region, access = need(state, "name", "size", "region", "access")
    codex = answers(state).get("codex") == "yes"
    # Where ssh will really send the name, rehearsed before any price is shown: a config that
    # would move it gets no quote, so nothing can be bought on it, and an older quote is gone.
    if state.pop("quote", None) is not None:
        save_state(state)
    rehearse(name, key_paths(state)[0])
    price, source, note = machines.live_price(size)
    cloud, terms = plan_terms(state)
    commands = [shlex.join(argv) for argv in machines.plan_commands(name, size, region)]
    row = machines.read_registry().get(name)
    found, error = machines.matching_droplets(name) if shutil.which("doctl") else (None, "")
    listed = host_presets.size("do-droplet", size)
    answer = {"name": name, "size": size, "size_label": listed["label"], "region": region,
              "access": access, "codex": codex, "price_usd": price, "price_source": source,
              "price_note": note, "farm_tag": machines.farm_tag(), "commands": commands,
              "cloud_init": cloud}
    if row and machines.live_row({name: row}, name):
        answer["said"] = (f"{name} already has a row ({row.get('state')}); `apply` resumes it "
                          "and buys nothing")
        answer["buys"] = False
        return DONE, answer
    if found:
        # A quote from an earlier plan is dropped: with a droplet already there, no price
        # typed back may buy another one.
        state.pop("quote", None)
        save_state(state)
        answer["buys"] = False
        if len(found) > 1:
            answer["adopts"] = False
            answer["said"] = (f"{len(found)} droplets named {name} are already on this farm's "
                              f"tag ({machines.listed(found)}); nothing is bought or adopted "
                              "until only one is left, so `apply` stops")
            return DONE, answer
        answer["adopts"] = True
        answer["said"] = (f"a droplet named {name} is already on this farm's tag "
                          f"({machines.listed(found)}); `apply` adopts it with no price and no "
                          "quote, buys nothing, and resumes the flow")
        answer["next"] = "apply"
        return DONE, answer
    quote = secrets.token_hex(4)
    state["quote"] = dict(terms, id=quote, price_usd=price)
    save_state(state)
    answer.update({
        "buys": True, "quote": quote,
        "sentence": f"Create {name}, ${price:g} a month until you destroy it",
        "said": (f"Create {name}, ${price:g} a month until you destroy it ({note}). Nothing is "
                 f"created until the price is typed back: apply --confirm-usd {price:g} "
                 f"--quote {quote}"),
    })
    if source != "live":
        answer["said"] += ("; this is not a live price, and `apply` refuses to buy on it: log "
                           "doctl in first")
    if error:
        answer["said"] += f" (this farm's droplets could not be listed: {error})"
    return DONE, answer


# ---------------------------------------------------------------------------------- apply

def boot_wait(name, budget):
    """Step the row towards needs-login, one machines.py step at a time, within the budget."""
    machines.ensure_machines_key()
    stop_at = time.time() + budget
    while True:
        row = machines.read_registry().get(name) or {}
        if row.get("state") in (machines.NEEDS_LOGIN, machines.READY):
            return row
        if row.get("state") in (machines.DESTROYED, machines.FAILED, "") or not row:
            raise Stop(f"{name} is {row.get('state') or 'gone'}: {row.get('detail', '')}")
        change = machines.step_one_machine(name, row)
        if change:
            row = machines.apply_step(name, row.get("state") or "", change) or row
        if row.get("state") in (machines.NEEDS_LOGIN, machines.READY):
            return row
        if time.time() >= stop_at:
            return row
        time.sleep(POLL)


def cmd_apply(args, state):
    name, size, region, access = need(state, "name", "size", "region", "access")
    codex = answers(state).get("codex") == "yes"
    rows = machines.read_registry()
    row = rows.get(name)
    started = time.time()

    if not (row and machines.live_row(rows, name)):
        # The reconcile comes before any price: a droplet this farm already made (its registry
        # row lost) is adopted with no price and no quote, since nothing is bought.
        try:
            row = machines.adopt_existing(name, size, region)
        except machines.Refused as error:
            raise Stop(str(error))
        if row:
            state.pop("quote", None)
            state["farm"] = {"name": name, "outcome": "adopted"}
            save_state(state)

    if not (row and machines.live_row({name: row}, name)):
        if args.confirm_usd is None:
            raise Stop("nothing is bought without the price typed back: run `plan`, show the "
                       "person its sentence, and pass the number they type as --confirm-usd, "
                       "with the plan's --quote")
        quote = state.get("quote") or {}
        if not args.quote or args.quote != quote.get("id"):
            raise Stop("this price was not confirmed against the current plan: a typed price "
                       "buys one attempt only. Run `plan` again and have the person type its "
                       "price back")
        # The quote binds the whole plan the person saw, not its price alone: an answer changed
        # since (a region, Codex, the access, the head office) would buy or build something
        # else. The price itself is bound below, typed against quoted and quoted against live.
        changes = plan_changes(quote, plan_terms(state)[1])
        if changes:
            state.pop("quote", None)
            save_state(state)
            raise Stop("the plan changed since its quote (" + "; ".join(changes) + "). Nothing "
                       "was bought; run `plan` again, show the person the new plan and have "
                       "them type its price back")
        # The config may have changed since the plan: rehearsed again, just before the create.
        # A refusal spends the quote, as every other refusal here does.
        try:
            rehearse(name, key_paths(state)[0])
        except Stop:
            state.pop("quote", None)
            save_state(state)
            raise
        # Both prices are parsed as finite numbers above zero before they are compared: every
        # comparison with nan is false, so `--confirm-usd nan` would otherwise match any quote.
        typed, quoted = machines.usd(args.confirm_usd), machines.usd(quote.get("price_usd"))
        if typed is None or quoted is None:
            state.pop("quote", None)
            save_state(state)
            what = (f"`{args.confirm_usd}` is not a price" if typed is None else
                    "this plan's quote carries no usable price")
            raise Stop(f"{what}: a price is a finite number of dollars above zero. Nothing was "
                       "bought; run `plan` again and have the person type its price back")
        # The typed price must be the price the quote showed: a quote seen at $48 never
        # authorizes a purchase at any other number. create_droplet then compares it with the
        # live price it reads just before the create, so all three agree or nothing is bought.
        if abs(typed - quoted) > 0.005:
            state.pop("quote", None)
            save_state(state)
            raise Stop(f"the price moved: this plan's quote showed ${quoted:g} a month and "
                       f"${typed:g} was typed. Nothing was bought; run `plan` "
                       "again and have the person type its price back")
        if not state.get("preflight_ok"):
            raise Stop("the preflight has not passed; run `preflight` first")
        key, pub = key_paths(state)
        works, _how = key_works_without_a_terminal(key, pub)
        if not works:
            raise Stop("the ssh key cannot be used without a terminal any more (see "
                       "`preflight`); nothing was bought", code=WAITING)
        # The quote is spent before the provider is asked: whatever happens next, a second
        # attempt needs the price typed again.
        state.pop("quote", None)
        save_state(state)
        try:
            outcome, row = machines.create_droplet(name, size, region, person_key(state),
                                                   typed,
                                                   tailscale=access == "tailscale", node=codex)
        except machines.Refused as error:
            raise Stop(str(error))
        state["farm"] = {"name": name, "outcome": outcome}
        save_state(state)

    if row and machines.pending(row):
        budget = max(0.0, args.wait - (time.time() - started))
        try:
            row = machines.wait_pending(name, budget=budget)
        except machines.Refused as error:
            raise Stop(str(error))
        if row and machines.pending(row):
            late = machines.seconds_since(row.get("created_at")) >= machines.PENDING_WINDOW
            raise Stop(row.get("detail") or machines.PENDING_NOTE, code=WAITING,
                       next="forget-attempt" if late else "apply")

    budget = max(0.0, args.wait - (time.time() - started))
    row = boot_wait(name, budget)
    farm = state.setdefault("farm", {})
    farm.update({"name": name, "address": row.get("address") or "",
                 "provider_id": row.get("provider_id") or "", "state": row.get("state")})
    save_state(state)
    if row.get("state") not in (machines.NEEDS_LOGIN, machines.READY):
        raise Stop(f"{name} is {row.get('state')}: {row.get('detail')}; run `apply` again to "
                   "keep waiting (nothing is bought again)", code=WAITING, next="apply")
    return DONE, {"said": f"{name} is up at {row['address']} and its first boot has finished; "
                          f"{machines.price_sentence(row)}",
                  "address": row["address"], "state": row["state"], "next": "ssh-config"}


# ------------------------------------------------------------------------------ ssh-config

def pinned_key(address):
    """The host key lines known_hosts holds for this address; empty when it holds none."""
    code, out, _err = run(["ssh-keygen", "-F", address, "-f", KNOWN], timeout=20)
    return out.strip() if code == 0 else ""


def record_pin(state, address, droplet):
    """Say in farm.json which droplet, at which address, the pinned key belongs to."""
    state.setdefault("farm", {}).update({"address": address, "pinned": True,
                                         "pinned_for": droplet, "pinned_address": address})
    save_state(state)


def cmd_ssh_config(args, state):
    ensure_murmur_dir()
    name = need(state, "name")[0]
    row = machines.read_registry().get(name) or {}
    address = row.get("address") or ""
    if not address or row.get("state") not in (machines.NEEDS_LOGIN, machines.READY):
        raise Stop(f"{name} has no finished first boot yet; run `apply` first", code=WAITING)
    key, _pub = key_paths(state)
    write_ssh_block(name, address, key)
    check_resolution(name, address, key)

    farm = state.setdefault("farm", {})
    droplet = str(row.get("provider_id") or "")
    held = pinned_key(address)
    pinned_for = str(farm.get("pinned_for") or "")
    pinned_at = str(farm.get("pinned_address") or address)
    if held and not pinned_for:
        # The pin in known_hosts is authoritative. A key held for this address with no record
        # of whom it was pinned for is the first probe of a run that stopped before it saved:
        # it is adopted as it is, and a farm that now shows another key is refused below.
        record_pin(state, address, droplet)
    elif held and (pinned_for != droplet or pinned_at != address):
        # DigitalOcean reuses addresses: a key pinned for an earlier droplet would refuse this
        # one, so it goes, and only when the droplet itself changed (another id or address
        # than the one pinned). The same droplet's pin is never removed.
        run(["ssh-keygen", "-R", address, "-f", KNOWN], timeout=20)
        farm["pinned"] = False
    code, out, err = run(ssh_words(name) + ["true"], timeout=30)
    if code != 0:
        said = machines.one_line(err or out) or f"exit {code}"
        if "identification has changed" in (err or out).lower() or \
                "host key verification failed" in (err or out).lower():
            raise Stop(f"{name} at {address} shows a host key other than the one pinned in "
                       f"{KNOWN}, so nothing runs on it. If you destroyed and remade the farm "
                       "yourself, remove the old key with `ssh-keygen -R "
                       f"{address} -f {KNOWN}` and run ssh-config again; otherwise treat it "
                       f"as an attack: {said}")
        raise Stop(f"the first ssh to {name} failed, so nothing runs on it: {said}")
    if not pinned_key(address):
        raise Stop(f"the first ssh to {name} passed without pinning its host key in {KNOWN}, "
                   "so it proves nothing; check that no config sets UserKnownHostsFile "
                   "/dev/null for this host")
    # Recorded with the first probe, before any later step, so a rerun knows whose pin it is.
    record_pin(state, address, droplet)
    return DONE, {"said": f"`ssh {name}` reaches the farm as farm@{address}, and its host key "
                          f"is pinned in {KNOWN}", "ssh_config": SSH_CONFIG, "next": "finish"}


# ---------------------------------------------------------------------------------- finish

# The env file holds FLEET_DASH_TOKEN, so every rewrite keeps it 0600: the temporary file is
# made 0600 (O_EXCL, after any stale one is removed) before a byte is written, then renamed
# over the old one. A umask or an earlier file's mode never widens it.
ENV_WRITER = """import os, sys
path = sys.argv[1]
pairs = [arg.split("=", 1) for arg in sys.argv[2:]]
os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
try:
    lines = open(path).read().splitlines()
except FileNotFoundError:
    lines = []
keys = set(key for key, _ in pairs)
kept = [line for line in lines if line.split("=", 1)[0] not in keys]
kept += [key + "=" + value for key, value in pairs]
temporary = path + ".murmur"
try:
    os.unlink(temporary)
except FileNotFoundError:
    pass
handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.fchmod(handle, 0o600)
with os.fdopen(handle, "w") as out:
    out.write("\\n".join(kept) + "\\n")
os.replace(temporary, path)
"""


def set_remote_env(name, **pairs):
    """Write KEY=VALUE lines into the farm's fleet env file, replacing any earlier line."""
    words = ["python3", "-c", ENV_WRITER, REMOTE_ENV] + [f"{k}={v}" for k, v in pairs.items()]
    code, out, err = on_farm(name, words, timeout=60)
    if code != 0:
        raise Stop(f"could not write {REMOTE_ENV} on the farm: "
                   f"{machines.one_line(err or out)}")


def install_job(hq_repo):
    """The clone and the installer, detached on the box so no ssh has to stay open for it, and
    under a lock so a second `finish` never starts a second install."""
    clone = (f"if test -d {REMOTE_REPO}/.git; then git -C {REMOTE_REPO} pull -q --ff-only; "
             f"else gh repo clone {REPO} {REMOTE_REPO} -- -q; fi")
    install = ["bash", f"{REMOTE_REPO}/farm/install.sh", "--remote", "--yes"]
    if hq_repo:
        install += ["--hq-repo", hq_repo]
    job = (f"rm -f {REMOTE_CACHE}/install.done {REMOTE_CACHE}/install.failed; "
           f"if ( cd {FARM_HOME} && {clone} && {shlex.join(install)} ) "
           f"> {REMOTE_CACHE}/install.log 2>&1; then touch {REMOTE_CACHE}/install.done; "
           f"else touch {REMOTE_CACHE}/install.failed; fi")
    launch = (f"mkdir -p {REMOTE_CACHE} && setsid -f flock -n {REMOTE_CACHE}/install.lock "
              f"bash -c {shlex.quote(job)} < /dev/null > /dev/null 2>&1")
    return ["bash", "-c", launch]


def install_state(name):
    probe = (f"if test -e {REMOTE_CACHE}/install.done; then echo done; "
             f"elif test -e {REMOTE_CACHE}/install.failed; then echo failed; "
             f"tail -n 5 {REMOTE_CACHE}/install.log; "
             f"elif flock -n {REMOTE_CACHE}/install.lock true 2>/dev/null; then echo idle; "
             f"else echo running; fi")
    code, out, err = on_farm(name, ["bash", "-c", probe], timeout=60)
    if code != 0:
        raise Stop(f"could not ask the farm how its install is going: "
                   f"{machines.one_line(err or out)}")
    first, _, rest = out.strip().partition("\n")
    return first.strip(), rest


def cmd_finish(args, state):
    name, address = remote_ready(state)
    access = need(state, "access")[0]
    code, _out, _err = on_farm(name, ["gh", "auth", "status"], timeout=60)
    if code != 0:
        raise Stop("the farm needs its own GitHub login first. Run this in your own terminal, "
                   "choose GitHub.com and HTTPS, then run `finish` again",
                   code=WAITING, commands=[printed(name, ["gh", "auth", "login"])])

    set_remote_env(name, FLEET_DASH_BIND="tailscale" if access == "tailscale" else "127.0.0.1",
                   FLEET_FARM_ALIAS=name)
    stop_at = time.time() + args.wait
    status, tail = install_state(name)
    if status == "done" and args.reinstall:
        status = "idle"
    if status == "idle" or (status == "failed" and args.reinstall):
        code, out, err = on_farm(name, install_job(answers(state).get("hq_repo") or ""),
                                 timeout=60)
        if code != 0:
            raise Stop(f"the install could not be started: {machines.one_line(err or out)}")
        status = "running"
    while status == "running" and time.time() < stop_at:
        time.sleep(POLL)
        status, tail = install_state(name)
    if status == "running":
        raise Stop("the install is still running on the farm; run `finish` again to keep "
                   "waiting (it is never started twice)", code=WAITING, next="finish")
    if status == "failed":
        raise Stop("the install failed on the farm; its last lines: "
                   + machines.one_line(tail, 400) + f". The log is {REMOTE_CACHE}/install.log; "
                   "fix the cause, then run `finish --reinstall`")
    if status != "done":
        raise Stop(f"the farm answered something unexpected about its install: {status}")

    code, out, err = on_farm(name, [FLEET_BIN, "capacity"], timeout=60)
    if code != 0:
        raise Stop(f"the install finished but `fleet capacity` does not answer: "
                   f"{machines.one_line(err or out)}")
    _code, active, _err = on_farm(name, ["systemctl", "--user", "is-active", UNIT], timeout=30)
    state.setdefault("farm", {})["finished"] = True
    save_state(state)
    step = next_for(state)
    said = f"the fleet is installed on {name}; the dashboard service is {active.strip() or '?'}"
    if step == "tailscale":
        said += "; next, `tailscale` joins the farm to your tailnet"
    return DONE, {"said": said, "next": step}


# ------------------------------------------------------------------------------- tailscale

def page_answers(url, seconds):
    """True when GET <url>/api/version answers 200 within the time given."""
    parsed = urllib.parse.urlparse(url)
    stop_at = time.time() + seconds
    while True:
        try:
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
            connection.request("GET", "/api/version")
            status = connection.getresponse().status
            connection.close()
            if status == 200:
                return True
        except (OSError, http.client.HTTPException):
            pass
        if time.time() >= stop_at:
            return False
        time.sleep(0.5)


def remote_listens(name):
    probe = f"ss -ltnH 'sport = :{REMOTE_DASH_PORT}'"
    code, out, _err = on_farm(name, ["bash", "-c", probe], timeout=30)
    return [line.split()[3] for line in out.splitlines() if len(line.split()) > 3] \
        if code == 0 else []


def fall_back_to_tunnel(name, state, reason):
    """Loopback first, the service restarted, the listener checked, and only then the tunnel:
    a tunnel to loopback while the page listens on the tailnet alone would be refused."""
    set_remote_env(name, FLEET_DASH_BIND="127.0.0.1")
    code, out, err = on_farm(name, ["systemctl", "--user", "restart", UNIT], timeout=60)
    if code != 0:
        raise Stop(f"the fallback to the tunnel could not restart the dashboard: "
                   f"{machines.one_line(err or out)}")
    wanted = f"127.0.0.1:{REMOTE_DASH_PORT}"
    stop_at = time.time() + REACH_SECONDS
    while wanted not in remote_listens(name):
        if time.time() >= stop_at:
            raise Stop(f"after the fallback the dashboard does not listen on {wanted}; see "
                       f"`journalctl --user -u {UNIT}` on the farm")
        time.sleep(1)
    answers(state)["access"] = "tunnel"
    state.setdefault("farm", {})["fallback"] = reason
    save_state(state)
    return DONE, {"said": f"the page is reached through the ssh tunnel instead: {reason}",
                  "access": "tunnel", "next": next_for(state)}


def cmd_tailscale(args, state):
    name, _address = remote_ready(state)
    if need(state, "access")[0] != "tailscale":
        return DONE, {"said": "this farm is reached through the tunnel; nothing to do",
                      "next": next_for(state)}
    usable, reason = tailscale_on_laptop()
    if not usable:
        return fall_back_to_tunnel(name, state, reason)

    code, out, _err = on_farm(name, ["tailscale", "ip", "-4"], timeout=30)
    tailnet = out.strip().splitlines()[0].strip() if code == 0 and out.strip() else ""
    if not tailnet:
        try:
            mode = os.stat(TS_KEY).st_mode & 0o777
        except FileNotFoundError:
            raise Stop(f"make a one-off auth key in your Tailscale admin page and save it, in "
                       f"your own terminal, as {TS_KEY} with mode 600; it never goes through "
                       "this chat. Then run `tailscale` again", code=WAITING,
                       commands=[f"umask 077 && cat > {shlex.quote(TS_KEY)}"])
        if mode & 0o077:
            raise Stop(f"{TS_KEY} can be read by others (mode {mode:o}); run "
                       f"`chmod 600 {TS_KEY}` and try again")
        with open(TS_KEY, encoding="utf-8") as handle:
            key = handle.read().strip()
        # The key travels on ssh's stdin to the root helper, never on an argv.
        code, out, err = on_farm(name, ["sudo", "-n", TAILSCALE_HELPER], timeout=120,
                                 stdin_text=key + "\n")
        key = ""
        if code != 0:
            return fall_back_to_tunnel(name, state, "the farm could not join the tailnet: "
                                       + machines.one_line(err or out))
        code, out, _err = on_farm(name, ["tailscale", "ip", "-4"], timeout=30)
        tailnet = out.strip().splitlines()[0].strip() if code == 0 and out.strip() else ""
        if not tailnet:
            return fall_back_to_tunnel(name, state, "the farm joined but has no tailnet address")
    on_farm(name, ["systemctl", "--user", "restart", UNIT], timeout=60)
    url = f"http://{tailnet}:{REMOTE_DASH_PORT}"
    if not page_answers(url, REACH_SECONDS):
        return fall_back_to_tunnel(
            name, state, f"this laptop cannot reach {url} (a key from another tailnet, or an "
                         "ACL that does not let this laptop in)")
    state.setdefault("farm", {})["tailnet"] = tailnet
    save_state(state)
    return DONE, {"said": f"the farm is on your tailnet at {tailnet}; the page answers at {url}",
                  "url": url, "next": next_for(state)}


# ------------------------------------------------------------------------------------ open

def sock_path(name):
    return os.path.join(MURMUR, f"{name}.sock")


def port_path(name):
    return os.path.join(MURMUR, f"{name}.tunnel")


def tunnel_alive(name):
    if not os.path.exists(sock_path(name)):
        return False
    code, _out, _err = run(ssh_words(name, batch=False, extra=["-S", sock_path(name),
                                                                "-O", "check"]), timeout=20)
    return code == 0


def stop_tunnel(name):
    if os.path.exists(sock_path(name)):
        run(ssh_words(name, batch=False, extra=["-S", sock_path(name), "-O", "exit"]),
            timeout=20)
    for path in (sock_path(name), port_path(name)):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def port_is_free(port):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def listeners(port):
    """Every address something listens on for this port, as `address:port` strings."""
    code, out, _err = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], timeout=20)
    if code != 127:                                     # lsof says 1 when nothing listens
        return [word for line in out.splitlines()[1:] for word in line.split()
                if word.endswith(f":{port}")]
    code, out, _err = run(["ss", "-ltnH", f"sport = :{port}"], timeout=20)
    if code == 0:
        return [line.split()[3] for line in out.splitlines() if len(line.split()) > 3]
    return None


def start_tunnel(name):
    stop_tunnel(name)
    port = DASH_PORT if port_is_free(DASH_PORT) else free_port()
    argv = ssh_words(name, extra=["-f", "-N", "-M", "-S", sock_path(name),
                                  "-o", "ExitOnForwardFailure=yes",
                                  "-o", "ServerAliveInterval=30",
                                  "-L", f"127.0.0.1:{port}:127.0.0.1:{REMOTE_DASH_PORT}"])
    # -f leaves ssh running in the background, still holding whatever it was given as stdout
    # and stderr, so those go to a file and never to a pipe this script would wait on.
    err_path = os.path.join(MURMUR, f"{name}.tunnel-err")
    with open(err_path, "w", encoding="utf-8") as err:
        try:
            done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=err, timeout=60)
            code = done.returncode
        except subprocess.TimeoutExpired:
            code = 124
    with open(err_path, encoding="utf-8") as handle:
        said = machines.one_line(handle.read())
    os.unlink(err_path)
    if code != 0:
        stop_tunnel(name)
        raise Stop(f"the tunnel did not start on 127.0.0.1:{port}: {said or f'exit {code}'}")
    found = listeners(port)
    if found is None:
        stop_tunnel(name)
        raise Stop("neither lsof nor ss is here to check that the tunnel listens on this "
                   "laptop only, so it was closed")
    wide = [entry for entry in found if not entry.startswith("127.0.0.1:")]
    if wide or not found:
        stop_tunnel(name)
        raise Stop(f"the tunnel listened on {', '.join(wide) or 'nothing'} instead of "
                   f"127.0.0.1:{port} only (a GatewayPorts line in your ssh config?), so it "
                   "was closed: it would hand this laptop's network the page's reads")
    with open(port_path(name), "w", encoding="utf-8") as handle:
        handle.write(f"{port}\n")
    return port


def read_port(name):
    try:
        with open(port_path(name), encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return 0


def opener():
    if os.environ.get("MURMUR_OPEN"):
        return os.environ["MURMUR_OPEN"]
    if platform_name() == "Darwin":
        return "open"
    if is_wsl() and shutil.which("wslview"):
        return "wslview"
    return "xdg-open"


def hand_token_to_browser(name, base):
    """Read the token over ssh into memory, write a one-shot 0600 page that sends the browser
    to the dashboard with the token in the fragment, open that page's path, and delete it."""
    code, out, err = on_farm(name, [FLEET_BIN, "dashboard", "token"], timeout=60)
    token = out.strip().splitlines()[0].strip() if code == 0 and out.strip() else ""
    if not TOKEN_RE.match(token):
        raise Stop("the farm did not give its dashboard token (`fleet dashboard token` on the "
                   f"farm): {machines.one_line(err) or 'no answer'}")
    target = base + "/#token=" + urllib.parse.quote(token, safe="")
    page = ("<!doctype html><meta charset=\"utf-8\"><meta name=\"referrer\" "
            "content=\"no-referrer\"><title>murmur</title><script>location.replace("
            + json.dumps(target) + ")</script>\n")
    token = target = ""
    for stale in os.listdir(MURMUR):
        if stale.startswith("open-") and stale.endswith(".html"):
            try:
                os.unlink(os.path.join(MURMUR, stale))
            except OSError:
                pass
    path = os.path.join(MURMUR, f"open-{secrets.token_hex(6)}.html")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(page)
    page = ""
    code, out, err = run([opener(), path], timeout=30)
    # The page is deleted once the browser has had time to load it, by a child that outlives
    # this script, so `open` returns at once.
    if os.fork() == 0:
        try:
            os.setsid()
            quiet = os.open(os.devnull, os.O_RDWR)       # let go of the caller's pipes
            for fd in (0, 1, 2):
                os.dup2(quiet, fd)
            time.sleep(OPEN_LINGER)
            os.unlink(path)
        except OSError:
            pass
        finally:
            os._exit(0)
    if code != 0:
        raise Stop(f"the browser could not be opened ({machines.one_line(err or out)}); open "
                   f"{base} and paste the token `fleet dashboard token` prints on the farm")


def cmd_open(args, state):
    name, _address = remote_ready(state)
    ensure_murmur_dir()
    if args.stop:
        stop_tunnel(name)
        return DONE, {"said": f"the tunnel to {name} is closed"}
    tailnet = (state.get("farm") or {}).get("tailnet")
    if need(state, "access")[0] == "tailscale" and not tailnet:
        raise Stop("the farm is not on your tailnet yet; run `tailscale` first", code=WAITING)
    if tailnet and answers(state).get("access") == "tailscale":
        base = f"http://{tailnet}:{REMOTE_DASH_PORT}"
        if not page_answers(base, REACH_SECONDS):
            raise Stop(f"the page does not answer at {base}; run `tailscale` again, which falls "
                       "back to the tunnel if this laptop cannot reach the farm")
        reused = False
    else:
        port = read_port(name)
        reused = tunnel_alive(name) and port and page_answers(f"http://127.0.0.1:{port}", 5)
        if not reused:
            port = start_tunnel(name)
        base = f"http://127.0.0.1:{port}"
        if not page_answers(base, REACH_SECONDS):
            raise Stop(f"the tunnel is up but the page does not answer at {base}; run "
                       f"`ssh {name} {FLEET_BIN} dashboard status`")
    if not args.no_browser:
        hand_token_to_browser(name, base)
    return DONE, {"said": (f"the dashboard is open at {base}"
                           + (" (the tunnel that was already up)" if reused else "")),
                  "url": base}


# ---------------------------------------------------------------------------------- logins

def accounts_rows(name):
    code, out, err = on_farm(name, [FLEET_BIN, "accounts", "list", "--json"], timeout=60)
    if code != 0:
        raise Stop(f"`fleet accounts list --json` failed on the farm: "
                   f"{machines.one_line(err or out)}")
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        raise Stop("`fleet accounts list --json` answered something that is not JSON")
    return {row.get("name"): row for row in rows if isinstance(row, dict)}


def cmd_logins(args, state):
    name, _address = remote_ready(state)
    wanted = [a for a in (answers(state).get("accounts") or "").split(",") if a]
    codex = answers(state).get("codex") == "yes"
    rows = accounts_rows(name)
    for account in wanted:
        if account not in rows:
            code, out, err = on_farm(name, [FLEET_BIN, "accounts", "add", account], timeout=60)
            if code != 0:
                raise Stop(f"`fleet accounts add {account}` failed on the farm: "
                           f"{machines.one_line(err or out)}")
    rows = accounts_rows(name)

    commands, waiting, problems = [], [], []
    expected = ["default"] + wanted
    for account in expected:
        row = rows.get(account)
        if row is None:
            problems.append(f"the farm has no account row for {account}")
            continue
        if not row.get("logged_in"):
            words = [CLAUDE_BIN] if account == "default" else \
                ["env", f"CLAUDE_CONFIG_DIR={ACCOUNTS_DIR}/{account}", CLAUDE_BIN]
            commands.append(printed(name, words) + "   then type /login")
            waiting.append(account)
    emails = {}
    for account in expected:
        email = (rows.get(account) or {}).get("email") or ""
        if email:
            emails.setdefault(email.lower(), []).append(account)
    for email, owners in emails.items():
        if len(owners) > 1:
            problems.append(f"{' and '.join(owners)} are signed in as the same email ({email}); "
                            "log each one in to its own subscription")
    if problems:
        raise Stop("; ".join(problems) + ". No lane should move to this farm yet",
                   commands=commands)

    if codex:
        codex_commands, codex_waiting = codex_step(name, args)
        commands += codex_commands
        waiting += codex_waiting
    if waiting:
        raise Stop("log these in from your own terminal, one at a time, then run `logins` "
                   f"again: {', '.join(waiting)}", code=WAITING, commands=commands)
    state.setdefault("farm", {})["logins"] = True
    save_state(state)
    said = (f"{len(expected)} Claude "
            f"{'subscription is' if len(expected) == 1 else 'subscriptions are'} logged in, "
            "each as its own email")
    if codex:
        said += "; Codex is installed and logged in"
    return DONE, {"said": said, "accounts": [rows[a] for a in expected], "next": next_for(state)}


def codex_step(name, args):
    """Codex in a prefix the farm user owns, its binary in the env file, its login, the skill
    link once ~/.codex exists, and one real lane when a project is named."""
    code, _out, _err = on_farm(name, ["test", "-x", CODEX_BIN], timeout=30)
    if code != 0:
        code, out, err = on_farm(name, ["npm", "install", "--prefix", FARM_HOME + "/.local",
                                        "-g", "@openai/codex"], timeout=900)
        if code != 0:
            raise Stop(f"Codex did not install on the farm: {machines.one_line(err or out)}")
    set_remote_env(name, FLEET_CODEX_BIN=CODEX_BIN)
    code, _out, _err = on_farm(name, [CODEX_BIN, "login", "status"], timeout=60)
    if code != 0:
        return ([printed(name, [CODEX_BIN, "login"], extra=["-L", "1455:localhost:1455"])],
                ["codex"])
    # The fleet's installer links its skill into ~/.codex/skills only once ~/.codex exists,
    # which the login has just made.
    on_farm(name, ["bash", f"{REMOTE_REPO}/fleet/install.sh"], timeout=300)
    code, _out, _err = on_farm(name, ["test", "-L", FARM_HOME + "/.codex/skills/fleet"],
                               timeout=30)
    if code != 0:
        raise Stop("Codex is logged in but the fleet skill is not linked into "
                   f"{FARM_HOME}/.codex/skills; run `bash {REMOTE_REPO}/fleet/install.sh` on "
                   "the farm and look at what it says")
    if args.codex_lane:
        return codex_lane(name, args)
    return [], []


def codex_lane(name, args):
    if not args.by:
        raise Stop("the Codex lane needs --by <your code name>")
    lane = "codex-check"
    code, out, err = on_farm(name, [FLEET_BIN, "spawn", "--project", args.codex_lane,
                                    "--lane", lane, "--engine", "codex", "--by", args.by,
                                    "--task", "Reply with the single word ready, and stop."],
                             timeout=120)
    if code != 0 and "already" not in (out + err):
        raise Stop(f"the Codex lane did not spawn: {machines.one_line(err or out)}")
    stop_at = time.time() + args.wait
    while True:
        code, out, _err = on_farm(name, [FLEET_BIN, "status", "--json"], timeout=60)
        try:
            lanes = (json.loads(out or "{}") or {}).get("agents") or []
        except ValueError:
            lanes = []
        mine = [row for row in lanes if lane in str(row.get("slug") or row.get("lane") or "")]
        status = str((mine[-1] if mine else {}).get("status") or "")
        if status in ("done", "done_no_pr", "ended", "pr_open"):
            return [], []
        if status in ("failed", "killed", "gave_up", "state_unreadable"):
            raise Stop(f"the Codex lane ended {status}; `ssh {name} {FLEET_BIN} logs` says why")
        if time.time() >= stop_at:
            raise Stop("the Codex lane is still running; run `logins` again to keep waiting",
                       code=WAITING)
        time.sleep(POLL)


# ---------------------------------------------------------------------- forget-attempt, status

def cmd_forget_attempt(args, state):
    name = need(state, "name")[0]
    try:
        outcome, row = machines.forget_attempt(name)
    except machines.Refused as error:
        raise Stop(str(error))
    state.pop("quote", None)
    save_state(state)
    if outcome == "adopted":
        return DONE, {"said": f"the droplet appeared after all (id {row['provider_id']}); it is "
                              "adopted, not bought again. Run `apply` to wait for its boot",
                      "next": "apply"}
    return DONE, {"said": "the lost attempt is forgotten. A new droplet needs the price typed "
                          "again: run `plan`, and have the person type its price back",
                  "next": "plan"}


def next_step(state, row):
    unanswered = [q["id"] for q in questions(state) if q["id"] not in answers(state)]
    farm = state.get("farm") or {}
    if not state.get("preflight_ok"):
        return "preflight"
    if unanswered:
        return "questions"
    if not row or not machines.live_row({row["name"]: row}, row["name"]):
        return "plan"
    if machines.pending(row):
        late = machines.seconds_since(row.get("created_at")) >= machines.PENDING_WINDOW
        return "forget-attempt" if late else "apply"
    if row.get("state") not in (machines.NEEDS_LOGIN, machines.READY):
        return "apply"
    if not farm.get("pinned"):
        return "ssh-config"
    if not farm.get("finished"):
        return "finish"
    if answers(state).get("access") == "tailscale" and not farm.get("tailnet"):
        return "tailscale"
    if not farm.get("logins"):
        return "logins"
    return "open"


def next_for(state):
    """The step `status` would name next, for a step that has just done its part."""
    name = answers(state).get("name")
    return next_step(state, machines.read_registry().get(name) if name else None)


def cmd_status(args, state):
    name = answers(state).get("name")
    row = machines.read_registry().get(name) if name else None
    shown = machines.presented(row) if row else None
    farm = state.get("farm") or {}
    return DONE, {"answers": answers(state), "machine": shown, "farm": farm,
                  "tunnel": bool(name and os.path.exists(sock_path(name))),
                  "next": next_step(state, row),
                  "said": (f"{name}: {shown['state']}, {shown['detail']}" if shown
                           else "no farm bought yet")}


# ------------------------------------------------------------------------------------ argv

def parser():
    ap = argparse.ArgumentParser(prog="murmur_farm.py", description=__doc__.splitlines()[0])
    subs = ap.add_subparsers(dest="command", required=True)
    pre = subs.add_parser("preflight")
    pre.add_argument("--install-doctl", action="store_true")
    pre.add_argument("--make-key", action="store_true")
    pre.set_defaults(run=cmd_preflight)
    ask = subs.add_parser("questions")
    ask.add_argument("--all", action="store_true")
    ask.set_defaults(run=cmd_questions)
    store = subs.add_parser("answer")
    store.add_argument("--id", required=True)
    store.add_argument("--value", default="")
    store.set_defaults(run=cmd_answer)
    subs.add_parser("plan").set_defaults(run=cmd_plan)
    apply = subs.add_parser("apply")
    # A string, parsed by machines.usd: float() would take nan and inf without a word.
    apply.add_argument("--confirm-usd")
    apply.add_argument("--quote")
    apply.add_argument("--wait", type=float, default=480)
    apply.set_defaults(run=cmd_apply)
    subs.add_parser("ssh-config").set_defaults(run=cmd_ssh_config)
    finish = subs.add_parser("finish")
    finish.add_argument("--wait", type=float, default=480)
    finish.add_argument("--reinstall", action="store_true")
    finish.set_defaults(run=cmd_finish)
    subs.add_parser("tailscale").set_defaults(run=cmd_tailscale)
    opening = subs.add_parser("open")
    opening.add_argument("--stop", action="store_true")
    opening.add_argument("--no-browser", action="store_true")
    opening.set_defaults(run=cmd_open)
    logins = subs.add_parser("logins")
    logins.add_argument("--codex-lane", metavar="PROJECT",
                        help="also spawn one Codex lane on this registered project")
    logins.add_argument("--by", help="your code name, for the Codex lane")
    logins.add_argument("--wait", type=float, default=480)
    logins.set_defaults(run=cmd_logins)
    subs.add_parser("forget-attempt").set_defaults(run=cmd_forget_attempt)
    subs.add_parser("status").set_defaults(run=cmd_status)
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    state = load_state()
    try:
        code, answer = args.run(args, state)
    except Stop as stop:
        code = stop.code
        answer = {"said": stop.said, "run_in_your_terminal": stop.commands}
        answer.update(stop.extra)
    except machines.Refused as error:
        code, answer = REFUSED, {"said": str(error)}
    answer.setdefault("run_in_your_terminal", [])
    answer["ok"] = code == DONE
    answer["step"] = args.command
    print(json.dumps(answer, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
