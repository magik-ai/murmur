"""Where hq is pointed, and by whom.

Everything that used to be a constant naming one person's organisation lives
here: the head office repo, the owner who may override a claim, the author of
claims commits, where state is cached, how the repo is cloned. A stranger
configures hq with `hq init`; nobody has to edit the source.

Precedence is file, then environment: the file is the durable setup, the
environment is how a spawner configures one lane or one command inline.

The file is TOML, read by the standard library's `tomllib`, which is why hq
requires python 3.11. hq used to carry a hand-written fallback parser for 3.9
and 3.10, and the two disagreed about five malformed inputs: the same config
file then failed open on one python and blocked pushes on another. One parser
is worth more than two supported versions.
"""

import os
import sys
import tomllib
from pathlib import Path

DEFAULTS = {
    "repo": "",                  # owner/name of the head office repo. No default.
    "owner": "",                 # the sovereign; empty means nobody is sovereign.
    "bot_name": "hq",            # author name on claims commits
    "bot_email": "hq@users.noreply.github.com",
    "home": "",                  # state dir; empty means ~/.agent-hq
    "bin_dir": "",               # where `hq install` links; empty means ~/.local/bin
    "clone_url_template": "https://github.com/{repo}.git",
}

# Environment overrides the file, for spawners that configure a lane inline.
ENV_OVERRIDES = {
    "repo": "HQ_REPO",
    "owner": "HQ_OWNER",
    "bot_name": "HQ_BOT_NAME",
    "bot_email": "HQ_BOT_EMAIL",
    "home": "HQ_HOME",
}


def config_path():
    """${XDG_CONFIG_HOME:-~/.config}/hq/config.toml"""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "hq" / "config.toml"


class ConfigError(Exception):
    """The config file is there but hq cannot use it: unreadable, or not TOML.

    An exception rather than `sys.exit`, because one caller must survive it.
    `hq check-push` is a push gate, and a gate that dies on a stray character in
    a config file blocks every push on the machine - a far worse failure than
    the one it guards against. Everything else turns this into one line and
    stops, in `load_config`.
    """


def toml_string(value):
    """`value` as a TOML basic string, escapes and all.

    The config file is written from user input (`hq init --owner 'al"ice'`, a
    Windows-style `--home`), and interpolating that input straight into
    `key = "..."` produced a file hq itself could not parse - while `hq init`
    still exited 0, so the damage only surfaced at the next command.
    """
    out = ['"']
    for character in str(value):
        if character in ('"', "\\"):
            out.append("\\" + character)
        elif character == "\n":
            out.append("\\n")
        elif character == "\r":
            out.append("\\r")
        elif character == "\t":
            out.append("\\t")
        elif ord(character) < 0x20 or ord(character) == 0x7F:
            out.append("\\u%04X" % ord(character))
        else:
            out.append(character)
    out.append('"')
    return "".join(out)


def read_config_file(path):
    """The config file as a flat dict, or {} when it does not exist.

    Keys may sit at the top level or inside a `[hq]` table; the table wins.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise ConfigError(f"cannot read the config file {path} ({error})")
    try:
        # Decoded explicitly, because `read_text` raises UnicodeDecodeError -
        # a ValueError, not an OSError - and that escaped every caller that
        # catches ConfigError, the push gate included. One accented name saved
        # by an editor in latin-1 then froze every push on the machine.
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError(f"cannot read the config file {path} (not UTF-8: {error})")
    try:
        data = tomllib.loads(text)
    except Exception as error:
        raise ConfigError(f"cannot parse the config file {path} ({error})")
    flat = {k: v for k, v in data.items() if not isinstance(v, dict)}
    flat.update(data.get("hq", {}) if isinstance(data.get("hq"), dict) else {})
    return flat


class Config:
    """Resolved settings, plus every path derived from them."""

    def __init__(self, values, error=None):
        # The config file problem this Config was built in spite of, or None.
        # Only `check-push` reads it: it warns and lets the push through instead
        # of failing closed.
        self.error = error
        self.repo = str(values.get("repo") or "")
        self.owner = str(values.get("owner") or "")
        self.bot_name = str(values.get("bot_name") or DEFAULTS["bot_name"])
        self.bot_email = str(values.get("bot_email") or DEFAULTS["bot_email"])
        self.clone_url_template = str(
            values.get("clone_url_template") or DEFAULTS["clone_url_template"])
        home = str(values.get("home") or "")
        self.state = Path(home).expanduser() if home else Path.home() / ".agent-hq"
        bin_dir = str(values.get("bin_dir") or "")
        self.bin_dir = Path(bin_dir).expanduser() if bin_dir else Path.home() / ".local/bin"

    @property
    def cache(self):
        return self.state / "repo"

    @property
    def identity_file(self):
        return self.state / "identity"

    @property
    def identity_owner_file(self):
        """Which session last wrote identity_file. Without it the shared file is
        a guess; with it, a second session on the machine can tell the file is
        not about itself."""
        return self.state / "identity.session"

    @property
    def session_dir(self):
        """One file per session, so two agents on one machine stop overwriting
        each other."""
        return self.state / "identity.d"

    @property
    def lastread_file(self):
        return self.state / "lastread"

    @property
    def presence_dir(self):
        """One stamp per name: when this machine last heartbeated for it."""
        return self.state / "presence.d"

    @property
    def claims_index(self):
        return self.state / "claims.index"

    def clone_url(self):
        return self.clone_url_template.format(repo=self.repo)


def load_config(strict=True):
    """File first, environment last. Read fresh every time: a spawner may set
    HQ_REPO for one command, and tests swap HQ_HOME between cases.

    `strict=False` is for the push gate alone: a broken config file comes back
    as `cfg.error` instead of stopping the process, so the gate can warn and
    fail OPEN. Every other command wants the one-line exit.
    """
    values = dict(DEFAULTS)
    error = None
    try:
        values.update(read_config_file(config_path()))
    except ConfigError as problem:
        if strict:
            sys.exit(f"hq: {problem}")
        error = problem
    for key, variable in ENV_OVERRIDES.items():
        value = os.environ.get(variable)
        if value is not None:
            values[key] = value
    return Config(values, error)


def require_repo(cfg=None):
    """The head office repo, or one line telling the user how to get one."""
    cfg = cfg or load_config()
    if not cfg.repo:
        sys.exit(
            "hq: no head office repo configured - run `hq init --repo owner/name` "
            f"(or set HQ_REPO); config file: {config_path()}"
        )
    return cfg.repo
