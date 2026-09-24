#!/usr/bin/env python3
"""Fleet dashboard, a stdlib-only HTTP server. Serves the single-page UI plus
   /api/fleet (agent state) and /api/metrics (farm health).

   Binding and write access are configuration, not a constant. FLEET_DASH_BIND
   defaults to 127.0.0.1: reaching the page from another machine (a tailnet, a
   LAN) is a deliberate act. FLEET_DASH_BIND=tailscale binds this machine's
   Tailscale address, resolved at start, and refuses to start without one.

   Writing is gated by a bearer token, ALWAYS, loopback or not. "Loopback is
   trusted" was never true of a browser: any web page the operator happens to
   open can POST to 127.0.0.1, and so can anything else sharing the machine, and
   this page can stop an account or flip a model. The token is FLEET_DASH_TOKEN,
   or one minted into $FLEET_CONFIG/dash-token (mode 600) on first start;
   `fleet dashboard token` prints it. A request whose Origin or Sec-Fetch-Site
   says it came from another site is refused whatever token it carries, because a
   token a page can guess or replay is not a permission.

   Reads are open on a loopback bind and need the same token once the bind is
   wide: /api/agent hands out a lane's whole brief and its result."""
import datetime
import glob
import hmac
import http.server
import ipaddress
import json
import shutil
import os
import re
import secrets
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET_HOME = os.path.dirname(HERE)          # the checkout this file lives in, never a fixed path
sys.path.insert(0, os.path.join(FLEET_HOME, "lib"))
import metrics as M  # noqa: E402
import identity as ID  # noqa: E402
import claude_accounts as CA  # noqa: E402
import codex_usage as CX  # noqa: E402
import mode as MODE  # noqa: E402
import models as MODELS  # noqa: E402
import model_presets as MODEL_PRESETS  # noqa: E402
import model_discovery as MODEL_DISCOVERY  # noqa: E402
import scrub as SCRUB  # noqa: E402
sys.path.insert(0, HERE)                    # github_access sits next to this file
import github_access as GH  # noqa: E402

STATE = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))
CONFIG = os.path.expanduser(os.environ.get("FLEET_CONFIG", "~/.config/fleet"))
PORT = int(os.environ.get("FLEET_DASH_PORT", "7878"))
BIND = os.environ.get("FLEET_DASH_BIND", "127.0.0.1").strip() or "127.0.0.1"
TOKEN_FILE = os.path.join(CONFIG, "dash-token")
INDEX = os.path.join(HERE, "index.html")
STATIC = os.path.join(HERE, "static")

# What the browser is told a file is. A stylesheet or a module served as text/plain is simply
# ignored, with no error anywhere, so the map is written out rather than left to `mimetypes`,
# whose answer depends on the machine's own /etc/mime.types.
STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".mjs": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
}


def stored_token():
    """The token minted by an earlier start, or "" when there is none yet."""
    try:
        with open(TOKEN_FILE) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def ensure_token():
    """The write token, minting one on first start. Called from __main__ only: importing this
    module (the tests do) must not create files, and a read-only $FLEET_CONFIG must not stop the
    dashboard from serving, it only leaves writing closed until the operator sets one by hand."""
    token = os.environ.get("FLEET_DASH_TOKEN", "").strip() or stored_token()
    if token:
        return token
    token = secrets.token_urlsafe(32)
    try:
        os.makedirs(CONFIG, exist_ok=True)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(token + "\n")
        os.chmod(TOKEN_FILE, 0o600)
    except OSError as exc:
        print(f"fleet dashboard: cannot write {TOKEN_FILE} ({exc}); set FLEET_DASH_TOKEN "
              "yourself or the page stays read-only", file=sys.stderr)
        return ""
    return token


TOKEN = os.environ.get("FLEET_DASH_TOKEN", "").strip() or stored_token()
MAX_BODY_BYTES = 256 * 1024
DAEMON_UNIT = "fleet-daemon.service"
SWEEP_TIMER_UNIT = "fleet-sweep.timer"
# The tmux session `dashboard/run.sh` starts this server in. The variable exists so a suite can
# drive a dashboard of its own without reading the farm's.
DASH_SESSION = os.environ.get("FLEET_DASH_SESSION", "").strip() or "fleet-dashboard"
DEFAULT_TITLE = "murmur"
DEFAULT_HQ_AGENT = "dashboard"
# A tool that does not answer must not hold a page open. Three seconds is longer than any of
# these take when the machine is well, and short enough that a hung one reads as a failed check.
TOOL_TIMEOUT = 3


def run_tool(args, timeout=TOOL_TIMEOUT, env=None):
    """(returncode, stdout, stderr) from a command line tool. Never raises: a missing binary, a
    hung one and a failing one are all answers this page has to draw, not crashes.
    """
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return done.returncode, done.stdout or "", done.stderr or ""
    except FileNotFoundError:
        return 127, "", f"{args[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{args[0]} did not answer within {timeout}s"
    except OSError as exc:
        return 1, "", str(exc)


def tool_message(rc, out, err, what):
    """The one line a page can show when a tool refused: its last word, never a traceback and
    never the whole stream. Every write route answers with this."""
    lines = [line for line in ((err or "") + "\n" + (out or "")).splitlines() if line.strip()]
    return (lines[-1].strip() if lines else f"{what} exited {rc}")[:400]


def unit_loaded(unit):
    """Whether the user manager knows this unit at all."""
    rc, out, _ = run_tool(["systemctl", "--user", "show", unit, "-p", "LoadState", "--value"])
    return rc == 0 and out.strip() == "loaded"


def hq_binary():
    """The hq command, from PATH or from the user's own bin directory.

    A dashboard started by a service unit carries a short PATH that rarely includes
    ~/.local/bin, where `hq install` links the CLI. Without the fallback the mail tab on such a
    farm said "no head office is installed" while hq sat one directory away; bin/fleet looks in
    the same place for the same reason."""
    found = shutil.which("hq")
    if found:
        return found
    local = os.path.join(os.path.expanduser("~"), ".local", "bin", "hq")
    return local if os.access(local, os.X_OK) else ""


def hq_office():
    """The head office repository hq is pointed at, or "" when it is not configured.

    Resolved the way hq resolves it: the config file first, the environment last, so a farm that
    points one lane elsewhere with HQ_REPO and this dashboard agree about which office is meant.
    """
    override = os.environ.get("HQ_REPO")
    if override is not None:
        return override.strip()
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    try:
        import tomllib
        with open(os.path.join(base, "hq", "config.toml"), "rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return ""
    table = data.get("hq") if isinstance(data.get("hq"), dict) else {}
    return str(table.get("repo") or data.get("repo") or "").strip()


def dash_hq_agent():
    """The name this dashboard signs mail with. Never a name taken from a request."""
    return os.environ.get("FLEET_DASH_HQ_AGENT", "").strip() or DEFAULT_HQ_AGENT


def page_build():
    """The newest file the page is made of, as a number that changes on every deploy. The page's
    shell alone was the old answer, and a deploy that changed only a script left it the same, so
    a tab opened before the deploy never learned that it was running old code."""
    newest = 0.0
    for path in [INDEX] + [os.path.join(root, name) for root, _dirs, names in os.walk(STATIC) for name in names]:
        try:
            newest = max(newest, os.path.getmtime(path))
        except OSError:
            pass
    return str(int(newest))


_version_cache = {"value": None}


def version():
    """A build name for the page: this checkout's short commit, or "unknown" outside git."""
    if _version_cache["value"] is None:
        rc, out, _ = run_tool(["git", "-C", FLEET_HOME, "rev-parse", "--short", "HEAD"])
        _version_cache["value"] = out.strip() if rc == 0 and out.strip() else "unknown"
    return _version_cache["value"]


def free_features():
    """The features that cost nothing to answer: a lookup on PATH, a small file, two settings.

    These stay live rather than cached, so installing the head office tool or pointing it at a
    repository changes the page on its next tick instead of within a cadence.
    """
    return {"hq": bool(hq_binary() and hq_office()),
            "gpu": bool(M.NVIDIA),
            "cpu_temp": bool(M.LHM_URL),
            "forge": "github" if shutil.which("gh") else "unknown",
            "health_panel": health_panel_on()}


def health_panel_on():
    """Whether the Machine tab draws its Health section. Off unless this farm asks for it with
    FLEET_DASH_HEALTH=on: its hardware tiles read sensors (a graphics card, a hardware monitor
    endpoint) that most machines do not have, so a fresh farm would open on a wall of
    "not configured". The setup checklist on the Board does not depend on it."""
    return os.environ.get("FLEET_DASH_HEALTH", "").strip().lower() in ("1", "on", "true", "yes")


def measured_features():
    """The features that have to ask the user manager. Only the refresher calls this: this
    route is open, so anyone who can reach the port could otherwise spend two process spawns
    per request, with no token and nothing to rate limit them."""
    return {"slice": unit_loaded(MODE.SLICE)}


def config_refresh():
    with _snapshot_lock:
        _snapshot_succeeded(_config_snapshot,
                            {"units": measured_features(), "version": version()})


def config_payload():
    """What the page needs before it can decide what to draw: its name, and which of the
    optional parts of a farm this one actually has. A feature that is absent is drawn as absent,
    with the command that would add it, instead of as a panel that silently never fills."""
    snapshot = _copy_snapshot(_config_snapshot)
    units = snapshot.get("units") or {}
    free = free_features()
    return {
        "title": os.environ.get("FLEET_DASH_TITLE", "").strip() or DEFAULT_TITLE,
        "version": snapshot.get("version") or "unknown",
        "features": {
            "hq": free["hq"],
            "slice": bool(units.get("slice")),
            "gpu": free["gpu"],
            "cpu_temp": free["cpu_temp"],
            "forge": free["forge"],
            "health_panel": free["health_panel"],
        },
        "hq_agent": dash_hq_agent(),
        # Whether this farm has any hosting to draw at all, from the hosting snapshot and never
        # from a tool: this route is open and is asked on every page load.
        "hosting": hosting_counts(),
        # The name a person types after `ssh -t` to reach this farm, for every command the page
        # hands them to run elsewhere. Never a secret: it is the alias in their own ssh config.
        "farm_alias": CA.FARM_ALIAS,
        # True until the refresher's first pass: the unit fact above is not known yet and is
        # reported as absent, which is the safe way round for a page deciding what to draw.
        "pending": not snapshot.get("tried"),
    }

# branch -> {"backend":"pass|fail|pend", ...}, filled by a 60s poller so the per-3s
# dashboard tick never hammers the GitHub API.
CI_CACHE = {}
_UNREADABLE_REPORTED = set()


ACCOUNTS_REFRESH_SECONDS = 600  # owner's cadence: each refresh is one API call per account
# "Refresh now" on the page. One press is one request per account to the vendor, so a second
# press inside a minute is refused rather than queued: an account that is being throttled is
# made worse by asking again.
ACCOUNTS_WAKE_COOLDOWN = 60
_accounts_wake = threading.Event()
_accounts_wake_at = {"at": 0.0}
_accounts_lock = threading.Lock()
_accounts_snapshot = {"at": None, "accounts": [], "errors": {}}


# What a card says when the reader cannot be told anything more useful than "it did not work".
ACCOUNT_TROUBLE_UNKNOWN = "The farm could not read this account's numbers."


def account_trouble_kind(raw):
    """Which trouble a reader's message is, as a word this file can steer off: "", no_login,
    expired, rate_limited, unreachable or unknown.

    Read while the text is still the READER'S own words. Once account_trouble has turned it into
    copy for a person, classifying it again ties this farm's states to its wording: the login
    table's rate_limited state survived only because `account_trouble`'s sentence happens to
    carry the words "slow down", and a rewrite of that sentence would have moved every throttled
    account to "unknown" with no test failing.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    low = text.lower()
    if "filenotfounderror" in low or "no such file" in low or "never read" in low:
        return "no_login"
    if ("401" in low or "403" in low or "expired" in low
            or "unauthorized" in low or "forbidden" in low):
        return "expired"
    if "429" in low or "rate-limited" in low or "rate limited" in low:
        return "rate_limited"
    if any(word in low for word in ("urlerror", "timeout", "timed out", "connection", "refused",
                                    "unreachable", "gaierror", "socket", "ssl", "http 5")):
        return "unreachable"
    return "unknown"


def account_trouble(raw):
    """One sentence a person can act on, whatever the reader threw.

    What must never reach a card: an exception class, a traceback, a file path. "FileNotFoundError:
    [Errno 2] No such file or directory: '/private/tmp/...'" tells the reader nothing about what
    to do, and here there are only ever three things to do: log in once, log in again, or wait.
    """
    kind = account_trouble_kind(raw)
    if not kind:
        return ""
    if kind == "no_login":
        return ("This account has no login on the farm yet. Log in once: "
                f"ssh -t {CA.FARM_ALIAS} claude")
    return {"expired": "The login on this account has expired. Log in again.",
            "rate_limited": "The vendor asked the farm to slow down. These numbers refresh by "
                            "themselves.",
            "unreachable": "The vendor did not answer the last time the farm asked.",
            "unknown": ACCOUNT_TROUBLE_UNKNOWN}[kind]


def plain_account_trouble(rows, errors):
    """The same rows and errors, with every reason written for a person instead of for a log.

    The kind is kept next to the sentence, under `trouble`: it is a word, never the reader's
    text, so nothing that could carry a path or a class name is published, and the states this
    page draws are decided by what happened rather than by how it was worded.
    """
    for row in rows:
        if row.get("stale_error"):
            row["trouble"] = account_trouble_kind(row["stale_error"])
            row["stale_error"] = account_trouble(row["stale_error"])
    return rows, {name: account_trouble(text) for name, text in (errors or {}).items()}


# Which engine spends a subscription. Every account this reader publishes is a claude account:
# the codex row is appended below by its own module, which names itself. Without this the page's
# Engine column read "unknown" on every claude row, which is every row but one.
CLAUDE_ENGINE = "claude"


def _accounts_refresher():
    """Keep the account-limit snapshot warm off the request path.

    A failure leaves the previous snapshot in place rather than blanking it: "Anthropic was
    unreachable" and "there are no accounts" look identical once the data is gone, and only one
    of them is true.
    """
    while True:
        # Cleared before the pass, never after it: a request that arrives while this one runs is
        # asking for numbers this pass may already have missed.
        _accounts_wake.clear()
        try:
            summaries, errors = CA.collect()
            with _accounts_lock:
                previous = {row["name"]: row for row in _accounts_snapshot["accounts"]}
            rows = []
            for name in CA.account_dirs():
                if name in summaries:
                    s = summaries[name]
                    rows.append({"name": name, "label": CA.display(name), "email": CA.account_email(name),
                                 "engine": CLAUDE_ENGINE,
                                 "session": s["session"], "weekly": s["weekly"],
                                 "session_resets": s.get("session_resets"),
                                 "weekly_resets": s.get("weekly_resets"),
                                 "read_at": time.time(),
                                 "scoped": [
                                     {"label": label, "percent": pct, "active": active,
                                      "resets": resets}
                                     for label, pct, active, resets in s["scoped"]
                                 ]})
                elif name in previous:
                    # A failed read (429, timeout) keeps the last good numbers, marked stale.
                    # Dropping the row made "the vendor throttled us" render exactly like "the
                    # account was deleted" - the same defect the CI pane once had.
                    row = dict(previous[name])
                    row["engine"] = CLAUDE_ENGINE
                    err = errors.get(name, "unreadable")
                    exp = CA.token_expiry(CA.account_dirs().get(name, ""))
                    if "429" in err and exp is not None and exp <= time.time():
                        row["stale_error"] = "token expired"
                    else:
                        row["stale_error"] = err
                    rows.append(row)
                else:
                    rows.append({"name": name, "label": CA.display(name), "email": CA.account_email(name),
                                 "engine": CLAUDE_ENGINE,
                                 "session": None, "weekly": None,
                                 "session_resets": None, "weekly_resets": None,
                                 "read_at": None, "scoped": [],
                                 "stale_error": errors.get(name, "never read")})
            # codex, with the same last-good merge the claude tiles get (transient 403 must not
            # blank the tile to "unreadable"): CX.merge_row holds the previous good numbers.
            try:
                rows.append(CX.merge_row(CX.snapshot_row(), previous))
            except Exception:
                pass  # codex is best-effort; its absence must not blank the claude tiles
            rows, errors = plain_account_trouble(rows, errors)
            with _accounts_lock:
                _accounts_snapshot["at"] = time.time()
                _accounts_snapshot["accounts"] = rows
                _accounts_snapshot["errors"] = errors
            CA.write_cache(rows)  # let balance() and the CLI steer off this, not their own burst
        except Exception:
            pass
        # A wait rather than a sleep: "Refresh now" on the page is this event, not a second
        # reader of the vendor's endpoint.
        _accounts_wake.wait(ACCOUNTS_REFRESH_SECONDS)


def accounts_snapshot() -> dict:
    with _accounts_lock:
        return json.loads(json.dumps(_accounts_snapshot))


# ---------------------------------------------------------------- who is logged in
#
# One row per subscription account: logged in, waiting for its first login, expired, or
# rate-limited so this farm cannot tell. Read from the credentials file on disk and from the last
# usage snapshot, NEVER by asking the vendor: this row is drawn on every tick of the machine tab,
# and an account the vendor is already throttling is made worse by asking it again.

LOGIN_STATES = ("logged_in", "waiting_for_login", "expired", "rate_limited", "unknown")


def _first_login_sentence(name, config_dir):
    """How to log this account in, as the CLI itself words it."""
    if name == "default":
        return ("This account has no login on the farm yet. Log in once: "
                f"ssh -t {CA.FARM_ALIAS} claude, then /login")
    return ("This account has no login on the farm yet. Log in once: "
            f"ssh -t {CA.FARM_ALIAS} env CLAUDE_CONFIG_DIR={config_dir} claude, then /login")


# What the CLI writes an account's login into, and the only file this row is read from.
CREDENTIALS_FILE = ".credentials.json"


def credentials_state(config_dir):
    """Which of four things this account's credentials file is.

    `CA.token_expiry` answers None for all four of them, and only one of them means the account
    was never logged in. Drawing a working account as one that was never set up sends the
    operator to ssh in and run /login, which does not help and may replace a good credential.
    """
    path = os.path.join(config_dir or "", CREDENTIALS_FILE)
    if not os.path.exists(path):
        return "absent"
    try:
        with open(path) as handle:
            stored = json.load(handle)
    except (OSError, ValueError, UnicodeError):
        return "unreadable"                      # torn mid-write, or not ours to read
    if not isinstance(stored, dict):
        return "unreadable"
    oauth = stored.get("claudeAiOauth")
    if not isinstance(oauth, dict) or not isinstance(oauth.get("expiresAt"), (int, float)):
        return "incomplete"                      # a schema this farm does not know
    return "readable"


def _claude_login_row(name, config_dir, row, now):
    expiry = CA.token_expiry(config_dir)
    trouble = str((row or {}).get("stale_error") or "")
    # The kind the refresher recorded, never the sentence it published. A row that never went
    # through the refresher (a test, a snapshot written by an older build) is classified from
    # whatever text it does carry, which is then still the reader's own.
    throttled = ((row or {}).get("trouble") or account_trouble_kind(trouble)) == "rate_limited"
    if expiry is None:
        stored = credentials_state(config_dir)
        if stored == "absent":
            state, sentence = "waiting_for_login", _first_login_sentence(name, config_dir)
        elif stored == "incomplete":
            state = "unknown"
            sentence = (f"This account's {CREDENTIALS_FILE} carries no login token this farm "
                        "recognises, so it cannot tell whether the account is logged in.")
        else:
            state = "unknown"
            sentence = (f"This farm could not read this account's {CREDENTIALS_FILE}, so it "
                        "cannot tell whether the account is logged in. It is there; nothing "
                        "here says it is wrong.")
    elif expiry <= now:
        # A 429 masks an expired token, which is why the expiry is read first: the CLI's own list
        # makes the same correction.
        state = "expired"
        sentence = ("The login on this account has expired. The keepalive timer usually "
                    "refreshes it; log in again if it does not.")
    elif throttled:
        state = "rate_limited"
        sentence = ("The vendor asked the farm to slow down, so it cannot tell how much room is "
                    "left. These numbers refresh by themselves.")
    elif trouble:
        state = "unknown"
        sentence = "The farm could not read this account's numbers the last time it asked."
    else:
        state = "logged_in"
        sentence = "Logged in. Lanes can be spawned on this account."
    return {"name": name, "label": CA.display(name), "email": CA.account_email(name), "engine": "claude", "state": state,
            "sentence": sentence, "expires_at": _iso(expiry) if expiry else None}


def _codex_login_row(row, now):
    expiry = CX.token_expiry()
    if expiry is None:
        state = "waiting_for_login"
        sentence = ("This farm is not logged in to codex yet. Log in once: "
                    f"ssh -L 1455:localhost:1455 -t {CA.FARM_ALIAS} codex login")
    elif expiry <= now:
        state = "expired"
        sentence = ("The codex login has expired. The keepalive timer usually refreshes it; log "
                    "in again if it does not.")
    elif str((row or {}).get("stale_error") or ""):
        state = "unknown"
        sentence = "The farm could not read codex's numbers the last time it asked."
    else:
        state = "logged_in"
        sentence = "Logged in. Lanes can be spawned on codex."
    return {"name": "codex", "label": "codex", "engine": "codex", "state": state,
            "sentence": sentence, "expires_at": _iso(expiry) if expiry else None}


def accounts_login_state(now=None):
    """Every account's login, as files on this machine say it is. No vendor call, ever."""
    now = time.time() if now is None else now
    snapshot = accounts_snapshot()
    rows = {str(row.get("name")): row for row in snapshot.get("accounts") or []}
    out = []
    for name, config_dir in CA.account_dirs().items():
        row = rows.get(name) or {}
        answer = _claude_login_row(name, config_dir, row, now)
        answer["read_at"] = _iso(row["read_at"]) if row.get("read_at") else None
        out.append(answer)
    codex = _codex_login_row(rows.get("codex"), now)
    codex["read_at"] = _iso(rows["codex"]["read_at"]) if (rows.get("codex") or {}).get("read_at") \
        else None
    out.append(codex)
    return {"accounts": out, "at": _iso(snapshot["at"]) if snapshot.get("at") else None,
            "pending": snapshot.get("at") is None,
            "cooldown_seconds": ACCOUNTS_WAKE_COOLDOWN}


def accounts_refresh_request(now=None):
    """(status, payload) for POST /api/accounts/refresh: wake the reader, or say when it may be
    woken again."""
    now = time.time() if now is None else now
    since = now - (_accounts_wake_at["at"] or 0)
    if since < ACCOUNTS_WAKE_COOLDOWN:
        wait = max(1, int(round(ACCOUNTS_WAKE_COOLDOWN - since)))
        return 429, {"error": f"These numbers were asked for {int(since)} seconds ago. Each "
                              "refresh is one request per account to the vendor, so this can be "
                              f"asked again in {wait} seconds.",
                     "retry_after": wait}
    _accounts_wake_at["at"] = now
    _accounts_wake.set()
    return 200, {"ok": True, "retry_after": ACCOUNTS_WAKE_COOLDOWN,
                 "detail": "The farm is reading the accounts now; the numbers arrive in a few "
                           "seconds."}


def static_file(name):
    """(status, body, content type) for one file under `dashboard/static`.

    The front end is a directory an operator can add to, so the name comes from the request.
    Confinement is decided on the RESOLVED path, never by spotting "..": a symlink inside the
    directory pointing out of it is the same escape with none of the punctuation, and a browser
    is not the only thing that can call this.
    """
    name = unquote(name or "")
    if not name or name.startswith("/") or "\x00" in name:
        return 404, b"not found", "text/plain; charset=utf-8"
    root = os.path.realpath(STATIC)
    resolved = os.path.realpath(os.path.join(root, name))
    try:
        inside = resolved == root or os.path.commonpath([root, resolved]) == root
    except ValueError:
        inside = False
    if not inside:
        return 403, b"that path is outside the dashboard's static directory", \
            "text/plain; charset=utf-8"
    if not os.path.isfile(resolved):
        return 404, b"not found", "text/plain; charset=utf-8"
    ctype = STATIC_TYPES.get(os.path.splitext(resolved)[1].lower(), "application/octet-stream")
    try:
        with open(resolved, "rb") as handle:
            return 200, handle.read(), ctype
    except OSError:
        return 500, b"that file could not be read", "text/plain; charset=utf-8"


# ---------------------------------------------------------------- health checks
#
# One row per prerequisite, in the order a person would fix them. Four states and no more:
#   ok      the thing is there and answers
#   missing the thing is needed and is not installed
#   off     the thing is deliberately absent, and the farm works without it
#   error   the thing is there and did not answer; `detail` says what it said
#
# A check never raises: `health()` turns an exception into an error row with the message, because
# a page that shows a traceback has told the operator nothing they can act on.


def _which(name, env_var=""):
    """A tool's path, honouring the environment variable that points at it when it lives
    somewhere PATH does not reach."""
    override = (os.environ.get(env_var) or "").strip() if env_var else ""
    if override:
        return override if os.path.exists(override) else ""
    return shutil.which(name) or ""


def _check_gh():
    path = _which("gh")
    if path:
        return "ok", path, ""
    return "missing", "pull request checks and the head office both read through gh", \
        "install the GitHub CLI: https://cli.github.com"


def _check_tmux():
    path = _which("tmux")
    if path:
        return "ok", path, ""
    return "missing", "the dashboard and every lane run inside a detached tmux session", \
        "install tmux with this machine's package manager"


def _check_systemd_user():
    rc, out, err = run_tool(["systemctl", "--user", "is-system-running"])
    word = (out or err).strip().splitlines()[0] if (out or err).strip() else ""
    if rc == 127:
        # Lanes themselves run in tmux, so this is not what stops work. What needs a user
        # manager is the CPU cap behind the power modes, the sweep timer and the dashboard's
        # own unit.
        return "off", ("no user manager here, so the power modes and the sweep timer are "
                       "unavailable; lanes themselves run in tmux and are fine"), \
            "run this farm on a machine with a systemd user manager to get those"
    if word in ("running", "degraded", "starting", "maintenance"):
        return "ok", f"user manager is {word}", ""
    return "error", word or "the user manager did not answer", \
        "start it: `systemctl --user daemon-reload`, and check `loginctl show-user $USER`"


def _login_name():
    """The user this server runs as. USER and LOGNAME are unset in some containers and service
    managers; the account database still knows who this process is."""
    name = os.environ.get("USER") or os.environ.get("LOGNAME")
    if name:
        return name
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError, OSError):
        return ""


def _check_linger():
    user = _login_name()
    rc, out, err = run_tool(["loginctl", "show-user", user, "-p", "Linger", "--value"])
    if rc == 127:
        return "off", "no user manager here, so nothing keeps units alive after a logout", \
            "run this farm on a machine with a systemd user manager"
    answer = out.strip()
    if answer == "yes":
        return "ok", "units keep running after you log out", ""
    if answer == "no":
        return "off", "lanes and the dashboard stop when the last login session ends", \
            f"sudo loginctl enable-linger {user or '$USER'}"
    return "error", (err or "loginctl gave no answer").strip()[:200], \
        f"check `loginctl show-user {user or '$USER'}`"


def _check_hq():
    if not hq_binary():
        return "missing", "no hq on PATH, so the mail tab has nothing to read", \
            "install it from the hq directory of this checkout: uv tool install --from . hq-cli"
    office = hq_office()
    if not office:
        return "off", "hq is installed but points at no head office", \
            "hq init --repo <owner>/<office>"
    return "ok", f"head office {office}", ""


def _engine_row(name, env_var, label_fix, other_present):
    path = _which(name, env_var)
    if path:
        return "ok", path, ""
    if other_present:
        # A farm normally runs one engine. Calling the other one missing would paint a healthy
        # machine red, so an absent second engine is a choice until BOTH are gone.
        return "off", f"not installed; lanes cannot ask for {name}", label_fix
    return "missing", "no coding engine is installed, so no lane can run", label_fix


def _check_claude():
    return _engine_row("claude", "CLAUDE_BIN",
                       "install Claude Code: https://claude.com/claude-code",
                       bool(_which("codex", "CODEX_BIN")))


def _check_codex():
    return _engine_row("codex", "CODEX_BIN",
                       "install the Codex CLI: https://developers.openai.com/codex",
                       bool(_which("claude", "CLAUDE_BIN")))


def _check_gpu_sensor():
    if M.NVIDIA and os.path.exists(M.NVIDIA):
        return "ok", M.NVIDIA, ""
    return "off", "no GPU sensor, so power mode has no signal and stays on full", \
        "set FLEET_NVIDIA_SMI to the sensor's path if this machine has one"


def _check_cpu_temp_sensor():
    if M.LHM_URL:
        return "ok", M.LHM_URL, ""
    return "off", "CPU temperature is unknown, which warns but never blocks a spawn", \
        "set FLEET_LHM_URL to a hardware monitor endpoint if this machine has one"


def _check_sweep_timer():
    state = sweep_status()
    if state.get("enabled"):
        left = state.get("secs_left")
        when = f"next pass in {int(left // 60)} min" if left is not None else "enabled"
        return "ok", when, ""
    return "off", "nothing buries dead worktrees or stale cards on this machine", \
        f"systemctl --user enable --now {SWEEP_TIMER_UNIT}"


def _check_office_reachable():
    office = hq_office()
    if not office:
        return "off", "no head office configured", "hq init --repo <owner>/<office>"
    if not _which("gh"):
        return "missing", "the office is read through gh, which is not installed", \
            "install the GitHub CLI: https://cli.github.com"
    rc, out, err = run_tool(["gh", "repo", "view", office, "--json", "nameWithOwner"])
    if rc == 0:
        return "ok", f"{office} answers", ""
    return "error", (err or out or "gh gave no answer").strip().splitlines()[0][:200], \
        f"check `gh auth status` and that {office} exists and you can read it"


HEALTH_CHECKS = (
    ("gh", "GitHub CLI", _check_gh),
    ("tmux", "tmux", _check_tmux),
    ("systemd_user", "systemd user manager", _check_systemd_user),
    ("linger", "linger", _check_linger),
    ("hq", "head office", _check_hq),
    ("claude", "Claude Code engine", _check_claude),
    ("codex", "Codex engine", _check_codex),
    ("gpu_sensor", "GPU sensor", _check_gpu_sensor),
    ("cpu_temp_sensor", "CPU temperature sensor", _check_cpu_temp_sensor),
    ("sweep_timer", "sweep timer", _check_sweep_timer),
    ("office", "head office reachable", _check_office_reachable),
)


def run_health_checks():
    """The whole table, as rows. Runs tools, so only the refresher thread calls it."""
    rows = []
    for identifier, label, check in HEALTH_CHECKS:
        try:
            state, detail, fix = check()
        except Exception as exc:
            # A broken check is a fact about this machine, not a reason to lose the other
            # rows, and never a traceback on a page.
            state, detail, fix = "error", f"{type(exc).__name__}: {exc}"[:200], ""
        rows.append({"id": identifier, "label": label, "state": state,
                     "detail": detail, "fix": fix})
    return rows


# ------------------------------------------------------------ snapshots off the request path
#
# Everything a tick of the page draws is READ FROM MEMORY. Not one GET may run a tool, reach the
# network or write to disk: the page redraws every few seconds, so a single tool call on a read
# path is a tool call a few thousand times an hour, against a budget every agent on the machine
# shares. One thread refreshes all of it on a fixed cadence, and a request that arrives before
# the first pass gets an honest "not yet" rather than a blank panel or a wait.

REFRESH_SECONDS = 45
_snapshot_lock = threading.Lock()
# Set by a request that wants a snapshot nobody has asked for yet, so the refresher can pick it
# up in a moment instead of at the end of its next sleep.
_refresh_wake = threading.Event()


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _blank_snapshot(**payload):
    """`tried` is kept apart from `at`: an office that has never answered must not put a fetch
    back on the request path, and "never asked" must not read as "asked and got nothing"."""
    snapshot = {"at": None, "tried": False, "stale_since": None, "error": None}
    snapshot.update(payload)
    return snapshot


def _snapshot_succeeded(snapshot, payload):
    snapshot.update(payload)
    snapshot.update({"at": _now_iso(), "tried": True, "stale_since": None, "error": None})


def _snapshot_failed(snapshot, message):
    """Keep the last good values and say when they were true. "The forge is unreachable" and
    "there is nothing here" look identical once the data is gone, and only one of them is
    worth acting on."""
    snapshot["tried"] = True
    snapshot["error"] = message
    snapshot["stale_since"] = snapshot["at"]


def _envelope(snapshot, payload):
    """Every snapshot-backed answer says when it was true, when it went stale, and whether the
    first pass has happened at all."""
    answer = {"at": snapshot.get("at"), "stale_since": snapshot.get("stale_since"),
              "error": snapshot.get("error"), "pending": not snapshot.get("tried")}
    answer.update(payload)
    return answer


def _copy_snapshot(snapshot):
    with _snapshot_lock:
        return json.loads(json.dumps(snapshot))


_health_snapshot = _blank_snapshot(checks=[])
_config_snapshot = _blank_snapshot(units={}, version=None)


def health_refresh():
    rows = run_health_checks()
    with _snapshot_lock:
        _snapshot_succeeded(_health_snapshot, {"checks": rows})


def health():
    snapshot = _copy_snapshot(_health_snapshot)
    return _envelope(snapshot, {"checks": snapshot.get("checks") or []})


# ---------------------------------------------------------------- engines
#
# An engine is the command an agent runs. The catalog says which engines this farm knows about;
# whether the command is on this machine is a fact about the machine, and the page needs it to
# decide whether a switch belongs on the row at all. Offering On and Off for an engine that is
# not installed is offering to spawn a lane that cannot start.
#
# The check is `shutil.which` and a file test, never a process: this route is read on every tick
# of the machine tab, and a GET that ran each engine's CLI would be a health check nobody asked
# for, on every tick, for every engine. Running the engine is what Test is for.

# The variable each native engine's launcher reads instead of the bare command.
ENGINE_BIN_ENV = {"claude": "CLAUDE_BIN", "codex": "CODEX_BIN"}


def engine_command(model):
    """The command one catalog row runs. A native engine is named by its engine, a generic one
    carries its own `bin`."""
    engine = str((model or {}).get("engine") or "").strip()
    if engine in ENGINE_BIN_ENV:
        return engine
    return str((model or {}).get("bin") or (model or {}).get("id") or "").strip()


def engine_binary(model):
    """(installed, path) for one engine, read from this machine without starting anything."""
    command = engine_command(model)
    if not command:
        return False, ""
    override = os.environ.get(ENGINE_BIN_ENV.get(str((model or {}).get("engine") or ""), ""), "")
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        # The launcher runs this file and nothing else, so this is the path that counts.
        return True, override
    found = shutil.which(command)
    return (True, found) if found else (False, "")


# The five words a row's Status pill can say. The order below is the order they are decided in:
# a model nothing can run is "not installed" whatever else is true of it, and a model that has
# no key cannot be failing a test it never ran.
MODEL_STATUSES = ("not_installed", "needs_key", "failing", "on", "off")

# What a preset-less row says about its money, when its catalog entry never said.
NATIVE_ACCESS = {"claude": "your Claude subscription", "codex": "your ChatGPT subscription"}


def model_has_key(model):
    """Whether this farm can authenticate this model right now: the variable in the environment
    the dashboard runs in, or a key stored by `fleet models auth`. The key is never read."""
    auth_env = str((model or {}).get("auth_env") or "").strip()
    if not auth_env:
        return True
    if os.environ.get(auth_env):
        return True
    return MODELS.has_secret(str((model or {}).get("id") or ""))


def model_access(model):
    """One sentence: how this model is paid for. The catalog's own `access` line when it has
    one, otherwise a sentence built from what the entry does say."""
    access = str((model or {}).get("access") or "").strip()
    if access:
        return access
    engine = str((model or {}).get("engine") or "")
    if engine in NATIVE_ACCESS:
        return NATIVE_ACCESS[engine]
    auth_env = str((model or {}).get("auth_env") or "").strip()
    if auth_env:
        return f"an API key, held on this farm and read as {auth_env}"
    tos = str((model or {}).get("tos") or "").strip()
    return tos or "not recorded: add an access line to this model in models.toml"


def model_status(model, installed):
    """One word for the Status pill, from what the machine and the catalog know."""
    if not installed:
        return "not_installed"
    if not model_has_key(model):
        return "needs_key"
    if str((model or {}).get("health") or "") == "fail":
        return "failing"
    if (model or {}).get("enabled") and (model or {}).get("routable"):
        return "on"
    return "off"


def engine_row(model):
    """One catalog entry as the models table reads it: the entry, what this machine has, how it
    is paid for, and the one word its pill says."""
    row = dict(model)
    row["tos_kind"] = str(model.get("tos_kind") or "").strip() or MODEL_PRESETS.tos_kind(model.get("tos"))
    installed, path = engine_binary(model)
    command = engine_command(model)
    checked = model.get("checked_at") or 0
    row.update({
        "command": command,
        "installed": installed,
        "path": path,
        "install_hint": str(model.get("install_hint") or "").strip()
        or f"install {command or model.get('id')} and put it on this farm's PATH",
        "enabled": bool(model.get("enabled")),
        "last_test": _iso(checked) if checked else None,
        "access": model_access(model),
        "status": model_status(model, installed),
        "source": "added" if model.get("source") == "added" else "shipped",
        "variant": str(model.get("variant") or ""),
    })
    return row


def engines():
    """GET /api/engines: the catalog, each row saying whether its command is on this machine."""
    return [engine_row(model) for model in MODELS.listing() if model]


# ---------------------------------------------------------------- adding a model
#
# A person adds a model by picking a service, naming it and pasting one command. The services
# are lib/model_presets.py; this page turns one of them plus a few answers into a catalog entry
# and writes it. Two things it never does: run anything (the entry is data, and Test is what
# runs the CLI), and touch a credential. A key belongs on a terminal's stdin, where it is not in
# a browser's memory, a proxy's log or this server's traceback, so a body carrying one is
# refused before anything else is read.

# The words that make a field a credential. A name is lowercased and stripped of punctuation
# first, so key, apiKey, API_KEY and x-api-key are all the same field, and none of the fields
# this route actually reads (preset, id, variant, bin, run, auth_env, label) carries one.
KEY_WORDS = ("key", "secret", "token", "credential", "password")
KEY_REFUSAL = "A key never goes through this page. Run: fleet models auth {id}"
KEY_IN_COMMAND = ("A key never goes through this page: take it out of the command line and name "
                  "the variable that holds it instead. Run: fleet models auth {id}")
# A credential pasted into the command itself. That one is not harmless: it is written into
# models.toml verbatim, echoed back in the row, and re-run on every later Test. A command may of
# course READ a key, so a value that is a shell variable ($MY_API_KEY) or a {placeholder} is
# what a person is told to write instead.
KEY_FLAG = re.compile(r"--?[a-z0-9_-]*(?:key|secret|token|password)[\s=]+(\S+)", re.I)
KEY_TOKEN = re.compile(r"(?:\b(?:sk|pk|rk|ghp|gho|ghu|ghs|xox[abopsr])-[A-Za-z0-9_-]{8,}"
                       r"|\bAIza[A-Za-z0-9_-]{20,})")


def key_refusal(mid, sentence=KEY_REFUSAL):
    shown = mid if MODELS.ID_RE.match(str(mid or "")) else "<id>"
    return sentence.format(id=shown)


def key_field(body):
    """The name of a field in this body that carries a credential, or "" for none."""
    for name, value in (body or {}).items():
        if not value:
            continue
        flat = re.sub(r"[^a-z0-9]", "", str(name).lower())
        if any(word in flat for word in KEY_WORDS):
            return str(name)
    return ""


def key_in_command(value):
    """Whether a command line a person typed has a credential written into it."""
    text = str(value or "")
    if KEY_TOKEN.search(text):
        return True
    found = KEY_FLAG.search(text)
    return bool(found and not found.group(1).lstrip("\"'").startswith(("$", "{")))


def model_presets_listing():
    """GET /api/models/presets: the services, each saying whether this farm already has it."""
    catalogue = MODELS.catalog()
    taken = set(catalogue)
    for mid in catalogue:
        entry = catalogue.get(mid) or {}
        if isinstance(entry, dict) and entry.get("preset"):
            taken.add(str(entry["preset"]))
    rows = []
    for preset in MODEL_PRESETS.presets():
        preset["added"] = preset["id"] in taken
        rows.append(preset)
    return rows


def add_model_request(body):
    """POST /api/models/add {preset, id, variant?, bin?, run?, auth_env?} -> the new row."""
    body = body or {}
    mid = str(body.get("id") or "").strip()
    if key_field(body):
        return 400, {"error": key_refusal(mid or body.get("preset"))}
    for field in ("bin", "run"):
        if key_in_command(body.get(field)):
            return 400, {"error": key_refusal(mid or body.get("preset"), KEY_IN_COMMAND)}
    preset = str(body.get("preset") or "").strip()
    if not preset:
        return 400, {"error": "pick a service first"}
    entry, problem = MODEL_PRESETS.entry_from(preset, body)
    if problem:
        return 400, {"error": problem}
    entry["id"] = mid or preset
    try:
        model, problem = MODELS.add_model(entry)
    except Exception as exc:                       # a write can fail; a traceback is not an answer
        return 400, {"error": f"the catalog could not be written: {exc.__class__.__name__}"}
    if problem:
        return 400, {"error": problem}
    return 200, {"model": engine_row(model)}


def remove_model_request(body):
    """POST /api/models/remove {id} -> {ok, removed}. Only a model this farm added."""
    mid = str((body or {}).get("id") or "").strip()
    if not mid:
        return 400, {"error": "which model?"}
    try:
        removed, problem = MODELS.remove_model(mid)
    except Exception as exc:
        return 400, {"error": f"the catalog could not be written: {exc.__class__.__name__}"}
    if problem:
        return (404 if problem.startswith("no such model") else 400), {"error": problem}
    return 200, {"ok": True, "removed": removed}


# ---------------------------------------------------------------- a provider's models
#
# Request available models and the ticks that follow (design: docs/design/models-providers.md,
# sections 3 to 6). Discovery runs `fleet models discover` through run_tool, so it uses the
# codex binary lanes use (bin/fleet's CODEX_BIN), which this server does not have in its own
# environment. Neither route sends a prompt or runs a provider's test.

DISCOVER_TIMEOUT = 20
SELECT_TIMEOUT = 10
DISCOVERING = set()
DISCOVERING_LOCK = threading.Lock()


def _provider(body):
    mid = str((body or {}).get("id") or "").strip()
    if not MODELS.ID_RE.match(mid):
        return mid, None
    return mid, MODELS.effective(mid)


def _id_list(body, name):
    value = (body or {}).get(name) or []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        return None
    return [x.strip() for x in value if x.strip()]


def discover_models_request(body):
    """POST /api/models/discover {id} -> {source, models: [{id, label, description, cost_note,
    on}], error}. The cost note is decided here, by rule, never taken from the tool's answer."""
    mid, row = _provider(body)
    if not row:
        return 404, {"error": f"no such provider: {mid[:40]}" if mid else "which provider?"}
    with DISCOVERING_LOCK:
        if mid in DISCOVERING:
            return 409, {"error": f"a request for {mid}'s models is already running"}
        DISCOVERING.add(mid)
    try:
        rc, out, _err = run_tool([fleet_bin(), "models", "discover", mid, "--json"],
                                 timeout=DISCOVER_TIMEOUT)
    finally:
        with DISCOVERING_LOCK:
            DISCOVERING.discard(mid)
    answer = None
    if rc == 0:
        try:
            answer = json.loads(out)
        except ValueError:
            answer = None
    if not isinstance(answer, dict) or not isinstance(answer.get("models"), list):
        # The tool's own words are never passed on: they could be anything a provider printed.
        failed = (MODEL_DISCOVERY.FAILURES["timeout"] if rc == 124
                  else MODEL_DISCOVERY.FAILURES["unreadable"])
        answer = {"source": "docs", "models": MODEL_DISCOVERY.docs_list(row), "error": failed}
    rows = [MODEL_DISCOVERY.keep(item.get("id"), item.get("label"), item.get("description"))
            for item in answer["models"] if isinstance(item, dict)]
    error = str(answer.get("error") or "")
    clean = {"source": "account" if answer.get("source") == "account" else "docs",
             "models": [item for item in rows if item],
             "error": error if error in MODEL_DISCOVERY.FAILURES.values() else
             (MODEL_DISCOVERY.FAILURES["unreadable"] if error else "")}
    return 200, MODEL_DISCOVERY.annotate(MODEL_DISCOVERY.scrubbed(clean), row)


def select_models_request(body):
    """POST /api/models/select {id, on, off, confirm_cost} -> the updated row, as GET
    /api/engines has it (design section 6). An unknown provider is 404, as on discover. A noted
    model not named in confirm_cost, and the default model in off, are refused here, before any
    command runs, and again by `fleet models on|off`."""
    mid, row = _provider(body)
    if not row:
        return 404, {"error": f"no such provider: {mid[:40]}" if mid else "which provider?"}
    on, off, confirm = (_id_list(body, "on"), _id_list(body, "off"),
                        _id_list(body, "confirm_cost"))
    if on is None or off is None or confirm is None:
        return 400, {"error": "on, off and confirm_cost are lists of model names"}
    if not on and not off:
        return 400, {"error": "nothing to change"}
    refusal = MODELS.select_refusal(row, on, off, confirm)
    if refusal:
        # {error}, or {error, cost_note, model} for a model that can cost money, so the page
        # can ask the question and send again with it in confirm_cost.
        return 400, refusal
    steps = []
    if on:
        steps.append(["on", mid] + on + (["--confirm-cost"] + confirm if confirm else []))
    if off:
        steps.append(["off", mid] + off)
    for step in steps:
        rc, out, err = run_tool([fleet_bin(), "models"] + step, timeout=SELECT_TIMEOUT)
        if rc != 0:
            return 400, {"error": tool_message(rc, out, err, "fleet models " + step[0])}
    return 200, engine_row(MODELS.effective(mid))


# ---------------------------------------------------------------- services
#
# Three rows in the machine's control room: the agent runner, the sweep timer, and this
# dashboard. Every fact here costs a process, so all three are read by the 45 second refresher
# and NEVER on a request: a page redrawing every few seconds would otherwise ask systemd a few
# thousand questions an hour.
#
# The dashboard's own row is read from its tmux session and its listening socket, the two things
# `dashboard/run.sh status` looks at, and it is read-only: a page that can stop itself answers the
# next request with nothing at all.

# `fix` is written out next to `start`, never derived from `verb`: `fleet autosweep` takes
# on|off|status, so a fix built as "<verb> start" told the reader to run `fleet autosweep start`,
# which falls through to status, prints "autosweep OFF" and changes nothing. A row that says the
# sweep is off and hands over a command that does nothing reads as a broken farm.
SERVICE_UNITS = (
    {"id": "agent_runner", "label": "Agent runner", "unit": DAEMON_UNIT,
     "what": "respawns a lane that carries a restart policy until it delivers",
     "stopped": "stopped, so no lane is respawned when it ends before delivering",
     "verb": "fleet daemon", "start": ["daemon", "start"], "stop": ["daemon", "stop"],
     "fix": "fleet daemon start"},
    {"id": "sweep_timer", "label": "Sweep timer", "unit": SWEEP_TIMER_UNIT,
     "what": "buries merged worktrees and resolved cards every few minutes",
     "stopped": "off, so nothing buries merged worktrees or resolved cards",
     "verb": "fleet autosweep", "start": ["autosweep", "on"], "stop": ["autosweep", "off"],
     "fix": "fleet autosweep on"},
)
SERVICE_BY_ID = {spec["id"]: spec for spec in SERVICE_UNITS}
DASHBOARD_SERVICE_ID = "dashboard"
# What a page is told when it asks this server to stop or restart itself.
DASHBOARD_SERVICE_REFUSAL = ("This dashboard cannot start, stop or restart itself: the answer to "
                             "that request would never arrive. Run `fleet dashboard restart` in a "
                             "terminal on the farm.")


def _systemd_duration(text):
    """Seconds out of a systemd duration, e.g. "19h 41min 40.045077s".

    systemd formats a property as a timespan when, and only when, its NAME carries `USec`:
    NextElapseUSecMonotonic prints as "1d 1min 17.351398s", so it is read here rather than
    divided by a million.
    """
    total = 0.0
    for number, unit in re.findall(r"([\d.]+)(us|ms|min|h|d|s)", text or ""):
        total += {"us": 1e-6, "ms": 1e-3, "s": 1, "min": 60, "h": 3600,
                  "d": 86400}[unit] * float(number)
    return total


def _systemd_monotonic(text):
    """Seconds since boot out of a monotonic timestamp property, whichever way systemd printed it.

    ActiveEnterTimestampMonotonic has no `USec` in its name, so systemd prints it as a bare count
    of microseconds ("586929396"). Reading that as a timespan found no units in it and answered
    zero, which is why every service row said it had never become active.
    """
    text = (text or "").strip()
    if re.fullmatch(r"\d+", text):
        return int(text) / 1e6
    return _systemd_duration(text)


def _unit_properties(unit, *names):
    """{property: value} for one unit, or {} when the user manager cannot answer."""
    args = ["systemctl", "--user", "show", unit]
    for name in names:
        args += ["-p", name]
    rc, out, _err = run_tool(args)
    if rc != 0:
        return {}
    facts = {}
    for line in (out or "").splitlines():
        key, _, value = line.partition("=")
        facts[key.strip()] = value.strip()
    return facts


def _unit_since(facts, now=None):
    """When this unit last became active, as an ISO stamp, or None.

    Read from the MONOTONIC property and turned into wall clock here, so the answer is on the one
    clock every other time on this page is on, without parsing systemd's own date format.
    """
    seconds = _systemd_monotonic(facts.get("ActiveEnterTimestampMonotonic"))
    if seconds <= 0:
        return None
    try:
        ago = time.clock_gettime(time.CLOCK_MONOTONIC) - seconds
    except (AttributeError, OSError):
        return None
    if ago < 0:
        return None
    return _iso((time.time() if now is None else now) - ago)


def _unit_row(spec):
    """One service's row, as the refresher reads it."""
    row = {"id": spec["id"], "label": spec["label"], "unit": spec["unit"],
           "what": spec["what"], "verb": spec["verb"], "state": "unknown", "detail": "",
           "since": None, "actions": ["start", "stop", "restart"], "read_only": False, "fix": ""}
    rc, out, err = run_tool(["systemctl", "--user", "is-active", spec["unit"]])
    word = ((out or "") + (err or "")).strip().splitlines()
    word = word[0].strip() if word else ""
    if rc == 127:
        row.update(state="absent", actions=[], read_only=True,
                   detail="there is no systemd user manager on this machine, so this service "
                          "cannot run here",
                   fix="run this farm on a machine with a systemd user manager")
        return row
    if rc == 124:
        row.update(state="unknown", detail="the user manager did not answer within "
                                           f"{TOOL_TIMEOUT}s")
        return row
    facts = _unit_properties(spec["unit"], "LoadState", "ActiveEnterTimestampMonotonic")
    if facts.get("LoadState") not in ("loaded", None, ""):
        # Never installed, or installed and then removed. Starting it is what installs it, so the
        # row keeps its actions and says what is true today.
        row.update(state="absent", detail=f"{spec['unit']} is not installed on this machine",
                   fix=spec["fix"])
        return row
    row["since"] = _unit_since(facts)
    if word == "active":
        row.update(state="active", detail=spec["what"])
    elif word == "failed":
        row.update(state="failed", detail=f"{spec['unit']} failed; it is not doing its work",
                   fix=spec["fix"])
    elif word in ("activating", "deactivating", "reloading"):
        row.update(state="changing", detail=f"{spec['unit']} is {word}")
    else:
        row.update(state="inactive", detail=spec["stopped"], fix=spec["fix"])
    return row


# Where the kernel publishes its sockets, and how many bytes an address is in each. Named so a
# test can point it at a file of its own: the format is the kernel's and does not change, but
# this machine's own sockets do, and a suite must not depend on them.
PROC_TCP_FILES = (("/proc/net/tcp", 4), ("/proc/net/tcp6", 16))


def listening_socket(port):
    """"<address>:<port>" something is LISTENing on, or "" when nothing is, read from /proc.

    A file read, not a tool call: this is asked once per refresh and the answer decides whether
    the dashboard's own row says it is up. Off Linux there is no such file, every open fails,
    and the answer is "", which the dashboard's row already words as "this machine does not say
    which socket it is listening on".
    """
    for path, size in PROC_TCP_FILES:
        try:
            with open(path) as handle:
                lines = handle.read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 4 or fields[3] != "0A":          # 0A = LISTEN
                continue
            raw, _, hexport = fields[1].partition(":")
            try:
                if int(hexport, 16) != int(port):
                    continue
                packed = b"".join(struct.pack("<I", int(raw[index:index + 8], 16))
                                  for index in range(0, len(raw), 8))
                address = ipaddress.ip_address(packed[:size])
            except (ValueError, struct.error):
                continue
            return f"[{address}]:{port}" if address.version == 6 else f"{address}:{port}"
    return ""


def _dashboard_row():
    """This server's own row, read the way `dashboard/run.sh status` reads it."""
    row = {"id": DASHBOARD_SERVICE_ID, "label": "This dashboard", "unit": None,
           "what": "serves this page", "verb": "fleet dashboard", "state": "active",
           "detail": "", "since": None, "actions": [], "read_only": True,
           "fix": "fleet dashboard restart", "refusal": DASHBOARD_SERVICE_REFUSAL}
    socket_address = listening_socket(PORT)
    rc, _out, _err = run_tool(["tmux", "has-session", "-t", DASH_SESSION])
    in_tmux = rc == 0
    if in_tmux and socket_address:
        row["detail"] = f"listening on {socket_address}, in the tmux session {DASH_SESSION}"
    elif in_tmux:
        row.update(state="failed",
                   detail=f"the tmux session {DASH_SESSION} is up but nothing is listening on "
                          f"port {PORT}")
    elif socket_address:
        row["detail"] = (f"listening on {socket_address}, started outside the tmux session "
                         f"{DASH_SESSION}, so `fleet dashboard restart` will not find it")
    else:
        row["detail"] = ("serving this page; this machine does not say which socket it is "
                         "listening on")
    return row


_services_snapshot = _blank_snapshot(services=[])


def services_refresh():
    rows = []
    for spec in SERVICE_UNITS:
        try:
            rows.append(_unit_row(spec))
        except Exception as exc:
            # One row that will not read is a fact about that unit, not a reason to lose the
            # others, and never a traceback on a page.
            rows.append({"id": spec["id"], "label": spec["label"], "unit": spec["unit"],
                         "what": spec["what"], "verb": spec["verb"], "state": "unknown",
                         "detail": f"this farm could not read {spec['unit']}"
                                   f" ({type(exc).__name__})",
                         "since": None, "actions": [], "read_only": False, "fix": ""})
    try:
        rows.append(_dashboard_row())
    except Exception:
        rows.append({"id": DASHBOARD_SERVICE_ID, "label": "This dashboard", "unit": None,
                     "what": "serves this page", "verb": "fleet dashboard", "state": "active",
                     "detail": "serving this page", "since": None, "actions": [],
                     "read_only": True, "fix": "fleet dashboard restart",
                     "refusal": DASHBOARD_SERVICE_REFUSAL})
    with _snapshot_lock:
        _snapshot_succeeded(_services_snapshot, {"services": rows})


def services():
    snapshot = _copy_snapshot(_services_snapshot)
    return _envelope(snapshot, {"services": snapshot.get("services") or []})


def service_row(identifier):
    """One row out of the last snapshot, or None when the first pass has not run."""
    for row in _copy_snapshot(_services_snapshot).get("services") or []:
        if row.get("id") == identifier:
            return row
    return None


# `fleet autosweep on` writes two unit files and reloads the user manager; the others enable a
# unit and wait for it. A minute is longer than any of them takes and short enough that a wedged
# user manager reads as a failed action rather than as a page that never answers.
SERVICE_ACTION_TIMEOUT = 60
SERVICE_ACTIONS = ("start", "stop", "restart")


def service_action(body):
    """(status, payload) for POST /api/services.

    `fleet` has no restart verb for any of these, so a restart is the stop and then the start, in
    that order, stopping at the first step that refuses.
    """
    identifier = str(body.get("service") or "").strip()
    action = str(body.get("action") or "").strip().lower()
    if identifier == DASHBOARD_SERVICE_ID:
        return 400, {"error": DASHBOARD_SERVICE_REFUSAL, "fix": "fleet dashboard restart"}
    spec = SERVICE_BY_ID.get(identifier)
    if spec is None:
        return 400, {"error": f"'{identifier}' is not a service on this farm",
                     "services": [item["id"] for item in SERVICE_UNITS] + [DASHBOARD_SERVICE_ID]}
    if action not in SERVICE_ACTIONS:
        return 400, {"error": "an action is start, stop or restart"}
    steps = {"start": [spec["start"]], "stop": [spec["stop"]],
             "restart": [spec["stop"], spec["start"]]}[action]
    said = []
    for step in steps:
        # No `--` here, deliberately: fleet parses with a hand written case loop, which never
        # reads a leading dash as an option and refuses a bare `--` as an unknown flag. Every
        # word below is this server's own, never the request's.
        rc, out, err = run_tool([fleet_bin()] + step, timeout=SERVICE_ACTION_TIMEOUT)
        if rc != 0:
            return 400, {"error": tool_message(rc, out, err, "fleet " + " ".join(step)),
                         "service": identifier, "action": action}
        said.append((out or "").strip().splitlines()[-1] if (out or "").strip() else "")
    # The row a page draws next must be the new one, not the one from before the press.
    _refresh_wake.set()
    return 200, {"ok": True, "service": identifier, "action": action,
                 "detail": " ".join(word for word in said if word)[:400],
                 "verb": spec["verb"]}


# ------------------------------------------------------------ the machine's live numbers
#
# Load, memory, GPU, the power mode and the sweep countdown. Each of these asks the machine
# something (a sensor, the user manager), so they are read on their own short cadence and
# served from memory. Five seconds is faster than a person perceives and is a fixed cost, where a
# read path was a cost per open page per tick.

MACHINE_REFRESH_SECONDS = 5
_machine_snapshot = _blank_snapshot(metrics={}, mode={}, sweep={})


# What each reader is called on the page, so a failure is a sentence and never a class name.
MACHINE_PARTS = {"metrics": "live numbers", "mode": "power mode", "sweep": "sweep countdown"}


def machine_refresh():
    """One pass over the machine's readers.

    A reader that threw keeps its last good value, and the pass is a FAILURE: republishing an
    hour-old load with `at` set to now and no error is the very thing the envelope was added to
    prevent, and the strip would say "now" over numbers nobody can vouch for.
    """
    parts, failed = {}, []
    for key, reader in (("metrics", M.collect), ("mode", MODE.status),
                        ("sweep", sweep_status)):
        try:
            value = reader()
        except Exception:
            # One sensor that will not answer must not cost the strip the other two.
            with _snapshot_lock:
                value = _machine_snapshot.get(key) or {}
            failed.append(MACHINE_PARTS[key])
        parts[key] = value
    with _snapshot_lock:
        if failed:
            _machine_snapshot.update(parts)
            _snapshot_failed(_machine_snapshot,
                             "this farm could not read its " + " and ".join(failed))
        else:
            _snapshot_succeeded(_machine_snapshot, parts)


def _machine_part(key):
    snapshot = _copy_snapshot(_machine_snapshot)
    payload = snapshot.get(key) or {}
    if not isinstance(payload, dict):
        payload = {}
    return _envelope(snapshot, payload)


def _machine_refresher(interval=MACHINE_REFRESH_SECONDS):
    while True:
        try:
            machine_refresh()
        except Exception:
            pass
        time.sleep(interval)


def start_machine_refresher():
    thread = threading.Thread(target=_machine_refresher, name="machine-refresher", daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------- long actions, as jobs
#
# A write that can outlast a request (draining the farm, resuming it, adding a project)
# answers at once with a job id and runs on a thread of its own. The record is a file under
# $FLEET_STATE/jobs, so a page that was reloaded, or a second page, can still read what happened;
# and a second press of a running action is refused rather than quietly run twice.

JOB_OUTPUT_TAIL = 4000        # what a person reads of a job that went wrong, not the whole log
JOB_KEEP_SECONDS = 24 * 3600  # a finished job is kept for a day, then it is nobody's business
JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_jobs_lock = threading.Lock()


def jobs_dir():
    return os.path.join(STATE, "jobs")


def _job_path(job_id):
    return os.path.join(jobs_dir(), job_id + ".json")


def _write_job(record):
    """One record, written whole. A half written job is a job a page reads as broken."""
    os.makedirs(jobs_dir(), exist_ok=True)
    path = _job_path(record["id"])
    temporary = path + ".writing"
    with open(temporary, "w") as handle:
        json.dump(record, handle)
    os.replace(temporary, path)


def _process_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _job_as_read(record):
    """A job whose dashboard is gone is not running, whatever its file says. Without this a
    restart mid-drain would leave the control disabled for ever, waiting on nothing."""
    if record.get("state") != "running" or record.get("pid") == os.getpid():
        return record
    if _process_alive(record.get("pid")):
        return record
    return dict(record, state="failed", ended_at=record.get("ended_at") or _now_iso(),
                error="the dashboard stopped while this was running, so how it ended is unknown")


def read_job(job_id):
    """(status, payload) for GET /api/jobs/<id>."""
    job_id = (job_id or "").strip()
    if not job_id or not JOB_ID.fullmatch(job_id):
        return 400, {"error": "invalid job id"}
    try:
        with open(_job_path(job_id)) as handle:
            record = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return 404, {"error": f"there is no job '{job_id}' on this farm"}
    if not isinstance(record, dict):
        return 404, {"error": f"there is no job '{job_id}' on this farm"}
    return 200, _job_as_read(record)


def _all_jobs():
    records = []
    for path in glob.glob(os.path.join(jobs_dir(), "*.json")):
        try:
            with open(path) as handle:
                record = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
        if isinstance(record, dict) and record.get("id"):
            records.append(_job_as_read(record))
    records.sort(key=lambda record: str(record.get("started_at") or ""), reverse=True)
    return records


def running_jobs():
    """What is in flight right now, newest first: the list every control consults before it
    lets itself be pressed."""
    return [record for record in _all_jobs() if record.get("state") == "running"]


def _forget_old_jobs(now=None):
    """Finished records older than a day. A page only ever asks about what it started."""
    now = time.time() if now is None else now
    for path in glob.glob(os.path.join(jobs_dir(), "*.json")):
        try:
            if os.path.getmtime(path) > now - JOB_KEEP_SECONDS:
                continue
            with open(path) as handle:
                record = json.load(handle)
            if isinstance(record, dict) and _job_as_read(record).get("state") == "running":
                continue
            os.remove(path)
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue


def _job_output(out, err):
    text = ((out or "") + ("\n" if out and err else "") + (err or "")).strip()
    return text[-JOB_OUTPUT_TAIL:]


def _new_job_id(action):
    return f"{action}-{int(time.time())}-{secrets.token_hex(3)}"


def _job_secrets():
    """Every secret this farm stores, for the scrub below. A directory that cannot be read is an
    empty list and not an exception: the token shapes in scrub.py still catch what looks like a
    token, and a job must end even when the secrets directory is missing."""
    try:
        return SCRUB.stored_secrets(STATE)
    except Exception:
        return []


def _finish_job(record, rc, out, err):
    """The record as it ends, written whole. Returned as well, so a synchronous write can hand
    its own outcome straight back to the page.

    The scrub is here, at the top, rather than at each caller: a provider CLI that prints a
    token into its own error message would otherwise leave it in this file, in the `error`
    sentence `tool_message` builds from it, and in every later GET /api/jobs/<id>.
    """
    known = _job_secrets()
    out, err = SCRUB.scrub(out, known), SCRUB.scrub(err, known)
    finished = dict(record, state="done" if rc == 0 else "failed", ended_at=_now_iso(),
                    exit_code=rc, output=_job_output(out, err))
    if rc != 0:
        finished["error"] = tool_message(rc, out, err, record["command"])
    try:
        _write_job(finished)
    except OSError as exc:
        print(f"fleet dashboard: job {record['id']} could not be recorded: {exc}",
              file=sys.stderr)
    return finished


def _run_job(record, args, timeout, after=None):
    try:
        rc, out, err = run_tool(args, timeout=timeout)
        _finish_job(record, rc, out, err)
    finally:
        # Whatever the tool did, the caller's own tidying runs: a temporary file to delete, a
        # snapshot to wake. An exception here must not cost the job its record.
        if after is not None:
            try:
                after()
            except Exception:
                pass


def claim_job(action, args=None, label=None, key=None, command=None):
    """(202, record) when this farm is free to run it, (409, payload) when it is not.

    The interlock is the RESOURCE, not the verb. Drain and resume are `fleet game-mode on` and
    `fleet game-mode off`, two names for the one power state this farm has, so a check that only
    compared verbs let both run at once and left the operator drained or resumed by whichever
    call happened to land last. Actions that share a resource share a key; the label stays per
    press, so the refusal still names what is actually running.

    `command` is for a write this server performs itself instead of by running a tool: the
    registry rewrite is one, and it shares its resource with `fleet add-project`.
    """
    label = label or action
    key = key or action
    with _jobs_lock:
        already = next((record for record in running_jobs()
                        if (record.get("key") or record.get("action")) == key), None)
        if already is not None:
            # Its own label, not this press's: the page is being told about the job in flight.
            return 409, {"error": f"{already.get('label') or label} is already running on this "
                                  "farm",
                         "job": already}
        _forget_old_jobs()
        record = {"id": _new_job_id(action), "action": action, "key": key, "label": label,
                  "command": (command or
                              " ".join([os.path.basename(args[0])] + list(args[1:])))[:400],
                  "state": "running", "started_at": _now_iso(), "ended_at": None,
                  "output": "", "pid": os.getpid()}
        try:
            _write_job(record)
        except OSError as exc:
            return 500, {"error": f"this farm's job directory could not be written ({exc})"}
    return 202, record


def start_job(action, args, timeout, label=None, key=None, after=None):
    """(status, payload) for a write that runs on a thread.

    202 and the record when it started, 409 and the record of the one already holding this
    resource: pressing Drain twice must not drain twice, and pressing Resume during a drain must
    not undo it halfway.

    `after` runs on that thread once the job has ended, however it ended. A caller that started
    the job with a temporary file, or that wants a snapshot refreshed the moment the work is
    done, hangs it here rather than polling the record.
    """
    code, payload = claim_job(action, args, label=label, key=key)
    if code != 202:
        return code, payload
    threading.Thread(target=_run_job, args=(payload, list(args), timeout),
                     kwargs={"after": after},
                     name="job-" + payload["id"], daemon=True).start()
    return 202, {"job": payload}


def run_job_now(action, args, timeout, label=None, key=None):
    """(status, payload, rc, out, err) for a short write that answers with its own result.

    It still takes the resource while it runs, so it cannot overlap a job that holds the same
    one, and it leaves the same finished record behind for a page that was reloaded.
    """
    code, payload = claim_job(action, args, label=label, key=key)
    if code != 202:
        return code, payload, None, "", ""
    rc, out, err = run_tool(args, timeout=timeout)
    # Scrubbed here too, and not only inside _finish_job: `out` and `err` go back to the caller,
    # which answers the page with them synchronously.
    known = _job_secrets()
    out, err = SCRUB.scrub(out, known), SCRUB.scrub(err, known)
    return 200, {"job": _finish_job(payload, rc, out, err)}, rc, out, err


# ---------------------------------------------------------------- projects
#
# Which repositories this farm serves. The registry is `projects.toml`, written by
# `fleet add-project`; this route reads it and adds the two live facts a person wants next to it:
# how many lanes of that project are open now, and when it last did anything.

PROJECT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
# Each side starts with a letter or a digit, so "../.." and "-x/-y" are refused here rather
# than further down, where they would become part of a clone URL or a command line.
PROJECT_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
# A port block a lane can actually be handed: above the privileged range, below the ephemeral
# one, and with room for the three ports a lane is given.
PORT_BASE_MIN = 1024
PORT_BASE_MAX = 60000
# The ports fleet hands a lane when the project's own table says nothing, which is what it used
# when these numbers were hardcoded.
DEFAULT_PORTS = {"web": 5200, "api": 8100, "e2e": 6100}
# A lane stops counting as open when it has stopped for good. A lane still thinking, and a lane
# whose pull request is waiting on a person, are both work this project has in flight.
CLOSED_LANE_STATUSES = {"aborted", "cancelled", "done", "done_no_pr", "ended", "failed",
                        "killed", "merged", "stopped"}
# add-project may clone a repository, which is the one thing here that is allowed to take a while.
PROJECT_ADD_TIMEOUT = 300
# The registry is one file, so the writes to it take one key and wait for each other.
PROJECT_WRITE_KEY = "projects"
# How far apart two projects' port bases are put. A lane is handed base+slot for its dev server,
# so a block is as many ports as a project could ever have lanes, with room to spare.
PORT_BLOCK_SIZE = 100


def fleet_bin():
    """The fleet CLI this dashboard drives. The checkout this file lives in wins over PATH: on a
    machine with two clones the page must not drive the other one."""
    local = os.path.join(FLEET_HOME, "bin", "fleet")
    if os.access(local, os.X_OK):
        return local
    return shutil.which("fleet") or "fleet"


def _projects_registry():
    """The `projects.toml` tables, or {} when there is no registry or it cannot be parsed.

    An unparseable registry is reported once on stderr rather than turned into a broken page:
    the tab then says "no projects yet", which is also what the log line is about.
    """
    path = os.path.join(CONFIG, "projects.toml")
    try:
        import tomllib
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        if path not in _UNREADABLE_REPORTED:
            print(f"fleet dashboard: unreadable project registry {path}: {exc}", file=sys.stderr)
            _UNREADABLE_REPORTED.add(path)
        return {}
    _UNREADABLE_REPORTED.discard(path)
    return {name: table for name, table in data.items() if isinstance(table, dict)}


def _lane_activity():
    """project -> (lanes open now, newest record's modification time)."""
    open_lanes, last_seen = {}, {}
    for path in glob.glob(os.path.join(STATE, "state", "*.json")):
        try:
            with open(path) as handle:
                record = json.load(handle)
            stamp = int(os.path.getmtime(path))
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        name = str(record.get("project") or "")
        if not name:
            continue
        last_seen[name] = max(last_seen.get(name, 0), stamp)
        if str(record.get("status") or "").lower() not in CLOSED_LANE_STATUSES:
            open_lanes[name] = open_lanes.get(name, 0) + 1
    return open_lanes, last_seen


def _port(value, fallback, default):
    for candidate in (value, fallback, default):
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return default


def projects():
    registry = _projects_registry()
    open_lanes, last_seen = _lane_activity()
    rows = []
    for name in sorted(registry):
        table = registry[name]
        ports = table.get("ports") if isinstance(table.get("ports"), dict) else {}
        base = table.get("port_base")
        rows.append({
            "name": name,
            "repo": str(table.get("repo") or ""),
            "path": os.path.expanduser(str(table.get("path") or "")),
            "base_branch": str(table.get("branch") or "main"),
            "ports": {
                "web": _port(ports.get("vite_base"), base, DEFAULT_PORTS["web"]),
                "api": _port(ports.get("api_base"), None, DEFAULT_PORTS["api"]),
                "e2e": _port(ports.get("e2e_base"), None, DEFAULT_PORTS["e2e"]),
            },
            "lanes_open": open_lanes.get(name, 0),
            "last_activity": last_seen.get(name),
        })
    return rows


def _registered_port_base(table):
    """One project's port base, in either spelling, or None."""
    ports = table.get("ports") if isinstance(table.get("ports"), dict) else {}
    for candidate in (ports.get("vite_base"), table.get("port_base")):
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def next_port_base():
    """The next free block above the highest one registered, or None when there is no room left.

    None rather than the ceiling: clamping handed the same numbers to the project at the top and
    to the one after it, which is the one thing this function exists to prevent. A farm that has
    run out of blocks is a sentence for a person, not a silent collision.
    """
    highest = None
    for table in _projects_registry().values():
        base = _registered_port_base(table)
        if base is not None and (highest is None or base > highest):
            highest = base
    if highest is None:
        return DEFAULT_PORTS["web"]
    following = highest + PORT_BLOCK_SIZE
    return following if following <= PORT_BASE_MAX else None


def next_port_answer():
    """GET /api/projects/next-port: the block this farm would hand the next project.

    The page needs this before the form is filled in, and it is the farm's answer rather than
    the page's arithmetic: a page taking the highest of every port in the table counted the api
    and end-to-end bases too, which are the same numbers for every project here, and suggested a
    block ten above the one every project's API already listens on.
    """
    base = next_port_base()
    if base is None:
        return {"next_port_base": None,
                "sentence": f"The highest port block on this farm is already at {PORT_BASE_MAX}, "
                            "so there is no free block above it. Remove a project, or give the "
                            f"next one a block of its own between {PORT_BASE_MIN} and "
                            f"{PORT_BASE_MAX}."}
    return {"next_port_base": base,
            "sentence": f"The next free port block on this farm is {base}. Leave the field "
                        "empty to take it."}


def add_project(body):
    """(status, payload) for POST /api/projects. Registering is `fleet add-project`'s job,
    never a second writer of the same file: a page that edited projects.toml itself would be a
    second implementation of the one thing that knows how to refuse a duplicate.

    It answers 202 and a job id, like drain and resume: `fleet add-project` clones the
    repository, so holding the connection open for it meant a browser waiting up to five
    minutes, an outcome lost on a reload, and a second press starting a second clone because
    nothing was there to refuse it.
    """
    name = str(body.get("name") or "").strip()
    repo = str(body.get("repo") or "").strip()
    if not PROJECT_NAME.fullmatch(name):
        return 400, {"error": "a project name is letters, digits, dot, dash or underscore, "
                              "up to 40 characters"}
    if not PROJECT_REPO.fullmatch(repo):
        return 400, {"error": "a repository is owner/name"}
    # Values travel behind their own option, and fleet's case loop takes the next word
    # literally whatever it starts with, so no separator is needed or wanted.
    args = [fleet_bin(), "add-project", "--name", name, "--repo", repo]
    port_base = body.get("port_base")
    if port_base in (None, ""):
        # Not the CLI's own default, which is the same 5200 for every project: the next free
        # block above the highest registered one, so the second project does not land on the
        # first one's ports.
        port_base = next_port_base()
        if port_base is None:
            return 400, {"error": f"the highest port block on this farm is already at "
                                  f"{PORT_BASE_MAX}, so there is no free block above it. Remove "
                                  "a project, or give this one a port base of its own between "
                                  f"{PORT_BASE_MIN} and {PORT_BASE_MAX}."}
    else:
        try:
            port_base = int(port_base)
        except (TypeError, ValueError):
            return 400, {"error": "port_base must be a whole number"}
        if not PORT_BASE_MIN <= port_base <= PORT_BASE_MAX:
            return 400, {"error": f"port_base must be between {PORT_BASE_MIN} and "
                                  f"{PORT_BASE_MAX}"}
    args += ["--port-base", str(port_base)]
    branch = str(body.get("branch") or "").strip()
    if branch:
        problem = GH.branch_problem(branch)
        if problem:
            return 400, {"error": problem}
        # One git call, no API call: a base branch that does not exist fails every lane.
        if GH._ls_remote(repo, f"refs/heads/{branch}") != 0:
            return 400, {"error": f"there is no branch {branch} in {repo}, or git on this farm "
                                  "cannot read the repository"}
        args += ["--branch", branch]
    code, payload = start_job("add_project", args, PROJECT_ADD_TIMEOUT,
                              label=f"Adding {name}", key=PROJECT_WRITE_KEY)
    payload.update({"name": name, "repo": repo, "port_base": port_base,
                    "sentence": f"{name} is being registered and its repository cloned. The "
                                "project appears in this list when that is done."})
    return code, payload


TABLE_HEADER = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]")


def _table_owner(line):
    """Which project a `[table]` line belongs to, or None when the line is not a header.

    `fleet add-project` writes the name quoted, an operator writes it bare, and a sub-table is
    `[<name>.ports]` in either spelling. All four forms name the same project.
    """
    match = TABLE_HEADER.match(line)
    if not match:
        return None
    return match.group(1).replace('"', "").replace("'", "").split(".")[0].strip()


def _registry_without(text, name):
    """The registry text with one project's tables removed and everything else left alone.

    Line based on purpose: this file is the operator's, with their comments and their order in
    it, and a rewrite through a TOML writer would hand it back without either.
    """
    kept, dropping = [], False
    for line in text.splitlines(keepends=True):
        owner = _table_owner(line)
        if owner is not None:
            dropping = owner == name
        if not dropping:
            kept.append(line)
    return "".join(kept)


def remove_project(body):
    """(status, payload) for POST /api/projects/remove.

    The registry only. Worktrees, checkouts and lane records are not this route's business, and
    a project with work in flight is not removed at all.

    The rewrite runs under the same key as `fleet add-project`. Both write `projects.toml`, the
    server is threaded, and add-project runs for up to five minutes next to this: a remove whose
    read landed before an add's append and whose replace landed after it dropped the new
    project, and the guard below could not see it, because it only compares against the text
    this reader read.
    """
    name = str(body.get("name") or "").strip()
    if not PROJECT_NAME.fullmatch(name):
        return 400, {"error": "a project name is letters, digits, dot, dash or underscore, "
                              "up to 40 characters"}
    row = next((item for item in projects() if item["name"] == name), None)
    if row is None:
        return 404, {"error": f"'{name}' is not a project registered on this farm"}
    if row["lanes_open"] > 0:
        count = row["lanes_open"]
        return 409, {"error": f"{name} has {count} lane(s) open. Stop or retire them first, "
                              "then remove the project.",
                     "lanes_open": count}
    code, claim = claim_job("remove_project", label=f"Removing {name}", key=PROJECT_WRITE_KEY,
                            command=f"remove {name} from projects.toml")
    if code != 202:
        return code, claim
    try:
        status, payload = _registry_without_project(name, row)
    except Exception:
        _finish_job(claim, 1, "", f"removing {name} did not complete")
        raise
    _finish_job(claim, 0 if status == 200 else 1, payload.get("sentence") or "",
                payload.get("error") or "")
    return status, payload


def _registry_without_project(name, row):
    """The rewrite itself, under the registry key its caller took."""
    path = os.path.join(CONFIG, "projects.toml")
    try:
        with open(path) as handle:
            before = handle.read()
    except OSError as exc:
        return 400, {"error": f"this farm's project registry could not be read ({exc})"}
    after = _registry_without(before, name)
    # The guard: what comes out must parse, must have lost this project, and must have kept
    # every other one exactly. A registry is the farm's map of itself; a bad rewrite of it is
    # worse than a project that will not go away.
    try:
        import tomllib
        parsed = tomllib.loads(after)
        original = tomllib.loads(before)
    except Exception as exc:
        return 400, {"error": f"removing '{name}' would leave a registry this farm cannot read "
                              f"({exc}); edit {path} by hand"}
    if name in parsed or any(parsed.get(other) != table for other, table in original.items()
                             if other != name):
        return 400, {"error": f"removing '{name}' would change another project's settings; "
                              f"edit {path} by hand"}
    backup = path + "." + name + "-removed-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:
        with open(backup, "w") as handle:
            handle.write(before)
        fd, temporary = tempfile.mkstemp(prefix="projects.toml.", dir=os.path.dirname(path))
        with os.fdopen(fd, "w") as handle:
            handle.write(after)
        os.replace(temporary, path)
    except OSError as exc:
        return 400, {"error": f"this farm's project registry could not be written ({exc})"}
    ports = row["ports"]
    block = f"{ports['web']} to {ports['web'] + PORT_BLOCK_SIZE - 1}"
    # The dev server block, and only that: `fleet add-project` writes port_base alone, so the
    # api and end-to-end bases are the same numbers for every project on this farm and are not
    # this project's to free.
    return 200, {"ok": True, "name": name, "ports": ports, "port_base": ports["web"],
                 "freed": block, "backup": backup,
                 "sentence": f"{name} is no longer registered. Its dev server port block, "
                             f"{block}, is free for the next project. Its checkout and its "
                             "worktrees are untouched."}


def _is_phantom(record):
    """A record with neither a project nor an engine was never a lane.

    `fleet spawn` writes the record before those fields are known, so anything that fails early
    leaves one behind. Rendering it as an agent - with a defaulted engine - puts agents on the
    dashboard that never existed, and the operator cannot tell them from real ones.
    """
    return not record.get("project") and not record.get("engine")


def _read_agent_record(path):
    """Retry a transient torn read; return an explicit placeholder for a persistent one."""
    state = None
    last = None
    for attempt in range(2):
        try:
            with open(path) as handle:
                state = json.load(handle)
            if not isinstance(state, dict):
                raise ValueError("state record is not a JSON object")
            _UNREADABLE_REPORTED.discard(path)
            return state
        except Exception as exc:
            last = exc
            if attempt == 0:
                time.sleep(0.01)
    if not os.path.exists(path):
        _UNREADABLE_REPORTED.discard(path)
        return None
    if path not in _UNREADABLE_REPORTED:
        print(f"fleet dashboard: unreadable state record {path}: {last}",
              file=sys.stderr)
        _UNREADABLE_REPORTED.add(path)
    return {
        "slug": os.path.basename(path)[:-5],
        "project": None,
        "lane": None,
        "engine": None,
        "status": "state_unreadable",
        "outcome": "unknown",
        "state_path": path,
        "state_error": str(last)[:200],
    }


def _apply_polled_checks(record):
    """Put the last poll's checks on a lane, when the poll actually read some.

    An empty poll is "nothing was read", never "the checks went away": overwriting the lane's
    own recorded checks with it is how a drawer ended up saying no check had reported while
    the record on disk held three.
    """
    branch = record.get("branch") or ""
    polled = CI_CACHE.get(branch)
    if record.get("pr_url") and polled:
        record["ci"] = polled
    return record


def agents():
    out = []
    for fp in sorted(glob.glob(os.path.join(STATE, "state", "*.json"))):
        s = _read_agent_record(fp)
        if s is None:
            continue
        if s.get("status") == "state_unreadable":
            out.append(s)
            continue
        _apply_polled_checks(s)
        if _is_phantom(s):
            continue
        out.append(s)
    return out


def agent_detail(slug):
    """One agent's full record for the detail modal. The state file keeps task/result
    truncated (to stay small and light in the list); the FULL text lives in the agent's
    log files, so read those here: this works for agents spawned before this endpoint too."""
    if not slug or not re.fullmatch(r"[A-Za-z0-9._-]+", slug):
        return {"error": "bad slug"}
    path = os.path.join(STATE, "state", slug + ".json")
    s = _read_agent_record(path)
    if s is None:
        return {"error": "not found"}
    if s.get("status") == "state_unreadable":
        return s
    _apply_polled_checks(s)
    logs = os.path.join(STATE, "logs")

    def read(ext, cap=40000):
        try:
            return open(os.path.join(logs, slug + ext)).read()[:cap]
        except Exception:
            return None

    task = read(".task")
    if task:
        s["task"] = task
    last = read(".last")
    if last:
        s["result_text"] = last
    return s


# ---------------------------------------------------------------- one lane's log
#
# `fleet spawn` writes the engine's raw stream to $FLEET_STATE/logs/<slug>.jsonl (with .log as
# the plain-text form some engines produce). The stream is machine shaped, so this route turns
# each event into the one line a person would have seen in a terminal, and falls back to the raw
# line whenever it cannot.

AGENT_LOG_DEFAULT_TAIL = 200
AGENT_LOG_MAX_TAIL = 2000
# How much of the file's end is read before the tail is cut out of it. A busy lane writes tens of
# megabytes; a megabyte holds far more than the maximum tail of any real stream.
AGENT_LOG_TAIL_BYTES = 1024 * 1024
SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _stream_text(event):
    """The human text in one stream event, or a short note naming what it was."""
    if not isinstance(event, dict):
        return None
    kind = event.get("type")
    if kind == "system":
        model = event.get("model") or ""
        return f"session started{(' on ' + model) if model else ''}"
    if kind == "result":
        text = (event.get("result") or "").strip()
        return text or "run finished"
    if kind == "error":
        said = event.get("message") or event.get("error") or ""
        if isinstance(said, dict):
            said = said.get("message") or ""
        if isinstance(said, str) and said.strip():
            return "error: " + said.strip()
    # A generic engine's own words (a streaming-json CLI may keep them under "data").
    for key in ("data", "text"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    inner = event.get("event") if isinstance(event.get("event"), dict) else {}
    if inner.get("type") == "content_block_start":
        block = inner.get("content_block") or {}
        if block.get("type") == "tool_use":
            return "tool: " + str(block.get("name") or "?")
    if inner.get("type") == "content_block_delta":
        delta = inner.get("delta") or {}
        if delta.get("type") == "text_delta" and (delta.get("text") or "").strip():
            return delta["text"].strip()
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    parts = []
    for block in message.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            parts.append("tool: " + str(block.get("name") or "?"))
        elif block.get("type") == "text" and (block.get("text") or "").strip():
            parts.append(block["text"].strip())
        elif block.get("type") == "tool_result":
            parts.append("tool result")
    if parts:
        return "\n".join(parts)
    return f"[{kind}]" if kind else None


def _log_lines(path, tail):
    """The last `tail` readable lines of one log file, and whether anything was left out."""
    try:
        size = os.path.getsize(path)
        start = max(0, size - AGENT_LOG_TAIL_BYTES)
        with open(path, "rb") as handle:
            handle.seek(start)
            raw = handle.read()
    except OSError:
        return None, False
    text = raw.decode("utf-8", errors="replace")
    if start > 0:
        text = text.partition("\n")[2]        # the first line of a mid-file read is half a line
    rows = [line for line in text.splitlines() if line.strip()]
    lines = []
    for line in rows:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeError):
            lines.append(line.rstrip())
            continue
        rendered = _stream_text(event)
        lines.append(rendered if rendered is not None else line.rstrip())
    truncated = start > 0 or len(lines) > tail
    return lines[-tail:], truncated


def agent_log(slug, tail=None):
    """(status, payload) for /api/agent/log.

    The slug names a lane, never a path: it is matched against the shape of a slug, joined to the
    log directory, and the result must still resolve inside it, which also refuses a symlink
    pointing out.
    """
    if not slug or not SLUG.fullmatch(slug):
        return 400, {"error": "invalid lane name"}
    try:
        wanted = int(tail) if str(tail or "").strip() else AGENT_LOG_DEFAULT_TAIL
    except (TypeError, ValueError):
        wanted = AGENT_LOG_DEFAULT_TAIL
    wanted = max(1, min(AGENT_LOG_MAX_TAIL, wanted))
    root = os.path.realpath(os.path.join(STATE, "logs"))
    for suffix in (".jsonl", ".log"):
        candidate = os.path.realpath(os.path.join(root, slug + suffix))
        try:
            inside = os.path.commonpath([root, candidate]) == root
        except ValueError:
            inside = False
        if not inside:
            return 403, {"error": "that log is outside the lane log directory"}
        if not os.path.isfile(candidate):
            continue
        lines, truncated = _log_lines(candidate, wanted)
        if lines is None:
            return 500, {"error": "that log could not be read"}
        return 200, {"slug": slug, "file": os.path.basename(candidate), "lines": lines,
                     "truncated": truncated, "missing": False}
    return 200, {"slug": slug, "file": None, "lines": [], "truncated": False, "missing": True,
                 "message": "This lane has written no log yet."}


# A lane's mid-run inbox, delivered at its next checkpoint by `fleet msg`. The dashboard writes
# nothing itself: the CLI owns that file, and a second writer of it would be a second answer to
# the question of what an inbox looks like.
AGENT_MSG_TIMEOUT = 15
AGENT_MSG_MAX_BYTES = 8000


def agent_msg(body):
    """(status, payload) for POST /api/agent/msg."""
    slug = str(body.get("slug") or "").strip()
    text = str(body.get("text") or "").strip()
    if not slug or not SLUG.fullmatch(slug):
        return 400, {"error": "invalid lane name"}
    # A name that is merely well shaped is not a lane. Without this the route would create an
    # inbox file for anything the page happened to send, and nothing would ever read it.
    if not os.path.isfile(os.path.join(STATE, "state", slug + ".json")):
        return 400, {"error": f"there is no lane named '{slug}' on this farm"}
    if not text:
        return 400, {"error": "a message needs some text"}
    if len(text.encode()) > AGENT_MSG_MAX_BYTES:
        return 400, {"error": f"a message is at most {AGENT_MSG_MAX_BYTES} bytes"}
    # No `--` here, deliberately: fleet parses with a hand written case loop, so it never reads
    # a leading dash as an option, and a separator would be taken as the lane's name.
    rc, out, err = run_tool([fleet_bin(), "msg", slug, text], timeout=AGENT_MSG_TIMEOUT)
    if rc != 0:
        lines = [line for line in ((err or "") + "\n" + (out or "")).splitlines() if line.strip()]
        return 400, {"error": (lines[-1].strip() if lines else f"fleet msg exited {rc}")[:400]}
    return 200, {"ok": True, "slug": slug, "detail": (out or "").strip()[:200]}


# ---------------------------------------------------------------- stopping a lane
#
# `fleet kill` stops the lane's unit and marks its record killed. `--retire` also writes the
# lane-scoped marker the supervisor honours, so the runner never respawns it and any sibling the
# storm already spawned is stopped too. Which of the two a page should offer is decided by the
# lane's restart policy, and that policy travels back with the answer so the page can say what
# the press actually did.
AGENT_KILL_TIMEOUT = 60


def agent_kill(body):
    """(status, payload) for POST /api/agents/kill."""
    slug = str(body.get("slug") or "").strip()
    retire = bool(body.get("retire"))
    if not slug or not SLUG.fullmatch(slug):
        return 400, {"error": "invalid lane name"}
    # A name that is merely well shaped is not a lane: the slug is matched against the records
    # this farm actually holds before it becomes a word on a command line.
    record = _read_agent_record(os.path.join(STATE, "state", slug + ".json"))
    if record is None:
        return 404, {"error": f"there is no lane named '{slug}' on this farm"}
    restart = str(record.get("restart") or "").strip() or None
    # No `--` here, deliberately: cmd_kill parses with a case loop whose only flag is --retire,
    # and it refuses a bare `--` as an unknown one. A slug cannot start with a dash anyway, SLUG
    # requires a letter or a digit first.
    args = [fleet_bin(), "kill"] + (["--retire"] if retire else []) + [slug]
    rc, out, err = run_tool(args, timeout=AGENT_KILL_TIMEOUT)
    if rc != 0:
        return 400, {"error": tool_message(rc, out, err, "fleet kill"), "slug": slug}
    if retire:
        sentence = "This lane is stopped and retired. Nothing will respawn it."
    elif restart:
        sentence = ("This pass is stopped. The runner will respawn this lane under a new name, "
                    f"because its policy is {restart}.")
    else:
        sentence = "This lane is stopped. It carries no restart policy, so nothing respawns it."
    return 200, {"ok": True, "slug": slug, "retired": retire, "restart": restart,
                 "lane": record.get("lane"), "project": record.get("project"),
                 "sentence": sentence, "detail": (out or "").strip()[:200]}


# ---------------------------------------------------------------- power
#
# Three actions, labelled as what they do. There is no spawn-only pause verb on this farm, so the
# control that stops new agents is `fleet mode balanced`, which also caps the CPU and memory of
# every agent already running. Draining is `fleet game-mode on`: it salvages and kills every live
# lane and stops the agent runner. Resuming is `fleet game-mode off`, and the runner it starts
# respawns every until-pr and until-merged lane, which spends subscription.

POWER_THROTTLE_TIMEOUT = 30    # writes a cgroup and answers
POWER_DRAIN_TIMEOUT = 900      # salvage pushes one lane at a time, over the network
POWER_RESUME_TIMEOUT = 300
THROTTLE_MODE = "balanced"
# All three power actions take this one key, because this farm has one power state and not
# three. Throttle, drain and resume are opposites of each other in pairs: two of them running at
# once leaves the farm in whichever state the last call happened to reach, at random.
POWER_JOB_KEY = "power"
# The two statuses `fleet game-mode` counts as RAM holders, and so the lanes a drain stops.
LIVE_LANE_STATUSES = ("running", "starting")


def live_lanes():
    """The lanes a drain would salvage and stop, by name."""
    rows = []
    for record in agents():
        if str(record.get("status") or "").lower() not in LIVE_LANE_STATUSES:
            continue
        rows.append({"slug": record.get("slug"), "project": record.get("project"),
                     "lane": record.get("lane"), "by": record.get("by"),
                     "restart": str(record.get("restart") or "").strip() or None,
                     "pr_url": record.get("pr_url")})
    rows.sort(key=lambda row: str(row.get("slug") or ""))
    return rows


def _throttle_caps():
    """What `fleet mode balanced` will actually do to a machine, in one phrase.

    Read from the mode policy rather than written down here: a farm that edited its profiles must
    not be promised this farm's numbers.
    """
    try:
        profiles, _auto = MODE._policy()
        profile = profiles[THROTTLE_MODE]
    except Exception:
        return "caps the CPU and memory of every agent"
    cores = os.cpu_count() or 1
    quota = profile.get("cpu_quota_pct")
    memory = profile.get("mem_high_pct")
    parts = []
    if quota is not None:
        parts.append(f"{quota}% of the CPU (about {round(quota / 100 * cores, 1)} of {cores} "
                     "cores)")
    if memory is not None:
        parts.append(f"{memory}% of this machine's memory")
    return ("caps every agent already running at " + " and ".join(parts)) if parts else \
        "caps the CPU and memory of every agent"


def power_preview(action):
    """(status, payload) for GET /api/power/preview: what the press will do, before it is
    pressed. Reads state files only, so it costs a page nothing to ask first."""
    action = (action or "").strip().lower()
    if action not in ("throttle", "drain", "resume"):
        return 400, {"error": "an action is throttle, drain or resume"}
    lanes = live_lanes() if action == "drain" else []
    # Any power job, not just this verb's: a page asking about resume while a drain runs is
    # asking about the one thing that is in flight.
    running = next((record for record in running_jobs()
                    if (record.get("key") or record.get("action")) == POWER_JOB_KEY), None)
    if action == "throttle":
        payload = {
            "label": "Throttle the farm and stop new agents",
            "sentence": f"Every agent already running keeps running. This {_throttle_caps()} "
                        "and stops any new agent from being spawned.",
            "warnings": ["Nothing is lost, and nothing is stopped."],
        }
    elif action == "drain":
        payload = {
            "label": "Drain the farm",
            "sentence": f"This salvages and then stops the {len(lanes)} lane(s) below, and stops "
                        "the agent runner so nothing is respawned.",
            "warnings": ["A lane with no restart policy loses whatever salvage could not push.",
                         "This dashboard keeps running through all of it."],
        }
    else:
        payload = {
            "label": "Resume the farm",
            "sentence": "This starts the agent runner again, and it will respawn every until-pr "
                        "and until-merged lane from its brief, which spends subscription.",
            "warnings": [],
        }
    payload.update({"action": action, "lanes": lanes, "lane_count": len(lanes),
                    "running_job": running})
    return 200, payload


def power_action(body):
    """(status, payload) for POST /api/power."""
    action = str(body.get("action") or "").strip().lower()
    code, preview = power_preview(action)
    if code != 200:
        return code, preview
    if action == "throttle":
        # Synchronous: it writes a cgroup and answers, and a page that had to poll a job for that
        # would be slower than the thing it is watching. It takes the power key all the same, so
        # it can neither start during a drain nor let one start under it.
        code, payload, rc, out, err = run_job_now(
            action, [fleet_bin(), "mode", THROTTLE_MODE], POWER_THROTTLE_TIMEOUT,
            label=preview["label"], key=POWER_JOB_KEY)
        if code != 200:
            payload.update({"action": action})
            return code, payload
        if rc != 0:
            return 400, {"error": tool_message(rc, out, err, "fleet mode"), "action": action}
        try:
            setting = MODE.get_setting()          # a one word file, never a tool
        except Exception:
            setting = THROTTLE_MODE
        return 200, {"ok": True, "action": action, "mode": setting,
                     "sentence": preview["sentence"], "detail": (out or "").strip()[:400]}
    verb = ["game-mode", "on" if action == "drain" else "off"]
    timeout = POWER_DRAIN_TIMEOUT if action == "drain" else POWER_RESUME_TIMEOUT
    code, payload = start_job(action, [fleet_bin()] + verb, timeout, label=preview["label"],
                              key=POWER_JOB_KEY)
    payload.update({"action": action, "lanes": preview["lanes"],
                    "lane_count": preview["lane_count"], "sentence": preview["sentence"]})
    return code, payload


# ---------------------------------------------------------------- hosting: machines
#
# A farm can own other machines: your own box over SSH, or a DigitalOcean Droplet. Two tools say
# where that stands: `fleet machines list --json` reconciles this farm's registry with the
# provider and advances each row one step, and `fleet hosts list --json` says which provider
# CLIs are installed and logged in.
#
# Both reach the network, so neither may ever run on a request. They are read by a thread of
# their own on the 45 second cadence, exactly as the machine strip is, and the two answers are
# kept apart, each with its own `at`, `stale_since` and `error`: a provider whose login expired
# must not cost the page its machine table, and a provider that is merely slow must never be
# drawn as logged out.
#
# This server never imports the hosting library and never runs a provider CLI. Its whole contract
# is the JSON those two commands print.

HOSTING_REFRESH_SECONDS = 45
# The listings ask a provider, so they get far longer than a local tool does. Nothing waits for
# them: they run on the refresher's thread and publish into a snapshot.
HOSTING_LIST_TIMEOUT = 60

# What each write is allowed to take. `create` only asks the provider for the droplet and
# returns; everything that happens after that is made by the refresher's `list`, one step per
# pass, so a create that took two minutes is a failure and not a page holding its breath.
HOSTING_PLAN_TIMEOUT = 60          # it reads the provider's live size list for the price
HOSTING_CREATE_TIMEOUT = 120
HOSTING_ADD_TIMEOUT = 60           # register a machine of your own, and check it over SSH
HOSTING_CHECK_TIMEOUT = 120        # SSH, cloud-init status, then `fleet capacity`
HOSTING_DESTROY_TIMEOUT = 120
HOSTING_REGISTRY_TIMEOUT = 60      # adopt and forget: the registry, and one read of the provider
HOSTING_HOSTS_CHECK_TIMEOUT = 60

# Every value below becomes part of an argv, so each is checked against a pattern first and a
# body that does not match never reaches a command line at all.
# A machine name is also a host name and a registry table name: lower case, no dots, 2 to 40.
MACHINE_NAME = re.compile(r"[a-z][a-z0-9-]{1,39}")
# A provider's size slug and region slug: 2 to 32 of lower case, digits and hyphens. The CLI
# checks them against the preset; this only keeps a shell-shaped or path-shaped string out of
# the argument list. A hyphen may not come first, which the bare character class would have
# allowed: `--force` is two to thirty-two of those characters, and a value that reads as an
# option is the one thing a validated field must never become.
SIZE_OR_REGION = re.compile(r"[a-z0-9][a-z0-9-]{1,31}")
# A confirmed monthly price: plain digits, and cents if any. No sign, exponent, underscore or
# `inf`, each of which float() accepts and none of which the CLI's own comparison expects.
CONFIRM_USD = re.compile(r"[0-9]{1,5}(?:\.[0-9]{1,4})?")
# user@host, each side starting with a letter or a digit for the same reason: `-lroot@10.0.0.4`
# would otherwise reach `--target` reading as an ssh option.
SSH_TARGET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9.-]*")
# One line of an OpenSSH public key: the type, the base64 body, and the optional comment. Not a
# secret, which is why it may be typed into the page at all, but still checked to the character.
SSH_PUBLIC = re.compile(r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) "
                        r"[A-Za-z0-9+/=]+(?: [^\n]{0,100})?")

# The provider ids of the design record, with the job each one can do. The catalog itself is
# `fleet/lib/host_presets.py`, which this server does not import: the CLI owns it, and a
# dashboard that carried its own copy would drift from it. This map is only the guard that keeps
# an unknown word out of an argv, and a provider the snapshot reports is accepted as well, so a
# preset added to the library needs no change here.
# The same ids as `fleet/lib/host_presets.py`. HostingProvidersTest compares the two, so a
# renamed id fails a test instead of refusing a real provider until the first listing.
HOSTING_PROVIDERS = {"ssh": "machine", "do-droplet": "machine"}

HOSTING_KEY_REFUSAL = ("A token never goes through this page. Run the login command in a "
                       "terminal on this farm.")
PUBKEY_REQUIRED = "Your SSH public key is how your laptop reaches the machine."

_hosting_machines_snapshot = _blank_snapshot(this={}, total_monthly_usd=0, machines=[])
_hosting_hosts_snapshot = _blank_snapshot(providers=[])
# Set by a write whose job has just ended, so the next pass happens in a moment rather than at
# the end of the current sleep: a row that went `creating` must not sit there for 45 seconds.
_hosting_wake = threading.Event()


def _hosting_list(snapshot, args, what, keys):
    """One listing into its snapshot. A failed run keeps the last good answer, says when it was
    true and carries one sentence: an empty table and an unreachable provider look identical
    once the rows are gone, and only one of them is worth acting on."""
    rc, out, err = run_tool([fleet_bin()] + list(args), timeout=HOSTING_LIST_TIMEOUT)
    known = _job_secrets()
    out, err = SCRUB.scrub(out, known), SCRUB.scrub(err, known)
    if rc != 0:
        with _snapshot_lock:
            _snapshot_failed(snapshot, tool_message(rc, out, err, what))
        return
    try:
        payload = json.loads(out or "")
    except (json.JSONDecodeError, UnicodeError):
        with _snapshot_lock:
            _snapshot_failed(snapshot, f"{what} did not answer with JSON")
        return
    if not isinstance(payload, dict):
        with _snapshot_lock:
            _snapshot_failed(snapshot, f"{what} did not answer with a JSON object")
        return
    with _snapshot_lock:
        _snapshot_succeeded(snapshot, {key: payload.get(key, blank)
                                       for key, blank in keys.items()})


def hosting_refresh():
    """One pass over both listings. They are separate calls into separate snapshots, so one
    failing tool leaves the other table alone."""
    _hosting_list(_hosting_machines_snapshot, ["machines", "list", "--json"],
                  "fleet machines list",
                  {"this": {}, "total_monthly_usd": 0, "machines": []})
    _hosting_list(_hosting_hosts_snapshot, ["hosts", "list", "--json"], "fleet hosts list",
                  {"providers": []})


def _hosting_refresher(interval=HOSTING_REFRESH_SECONDS, stop=None):
    """`stop` exists for the suite: a refresher left running past the test that started it goes
    on spawning tools into every test that follows."""
    while stop is None or not stop.is_set():
        _hosting_wake.clear()
        try:
            hosting_refresh()
        except Exception:
            pass
        _hosting_wake.wait(interval)


def start_hosting_refresher():
    thread = threading.Thread(target=_hosting_refresher, name="hosting-refresher", daemon=True)
    thread.start()
    return thread


def hosting_machines():
    """GET /api/machines. From memory, always: this route runs nothing."""
    snapshot = _copy_snapshot(_hosting_machines_snapshot)
    machines = snapshot.get("machines")
    this = snapshot.get("this")
    return _envelope(snapshot, {
        "this": this if isinstance(this, dict) else {},
        "total_monthly_usd": snapshot.get("total_monthly_usd") or 0,
        "machines": machines if isinstance(machines, list) else []})


def hosting_hosts():
    """GET /api/hosts. From memory, always: this route runs nothing."""
    snapshot = _copy_snapshot(_hosting_hosts_snapshot)
    providers = snapshot.get("providers")
    return _envelope(snapshot, {"providers": providers if isinstance(providers, list) else []})


def hosting_counts():
    """The number /api/config carries, so the page knows whether this farm has any hosting at
    all before it draws the section. Read from the snapshot, never from a tool."""
    machines = _copy_snapshot(_hosting_machines_snapshot).get("machines")
    return {"machines": len(machines) if isinstance(machines, list) else 0}


# ---- the writes
#
# Each one is a `fleet` command, run as a job keyed by the resource it touches: `machine:<name>`,
# so a second machine can be added while the first one boots, and `host:<provider>`. Every field
# is validated before a word of it is put in a list, the list is never a shell string, and when
# the job ends the snapshot is asked to look again.


def hosting_key_refusal(body):
    """The sentence for a body carrying something that looks like a credential, or "".

    The models routes' classifier, unchanged, which is also why the public key field is called
    `ssh_public`: a field named `pubkey` carries the word "key" and is refused here, as it
    should be. The refusal repeats neither the field nor its value; a sentence that echoed
    either would put the thing straight back into a log, a proxy and this page's own history.
    """
    return HOSTING_KEY_REFUSAL if key_field(body) else ""


def _known_providers():
    """id -> job, the design record's list plus whatever this farm's own CLI reported."""
    known = dict(HOSTING_PROVIDERS)
    providers = _copy_snapshot(_hosting_hosts_snapshot).get("providers")
    for row in providers if isinstance(providers, list) else []:
        if isinstance(row, dict) and row.get("id"):
            known.setdefault(str(row["id"]), str(row.get("job") or ""))
    return known


def _echo(value):
    """What a person typed, fit to be quoted back in a refusal. The key classifier reads field
    names only, so a token pasted into the wrong box reaches these sentences; it is scrubbed
    before it is cut, so a cut can never leave a token too short for the scrub to recognise."""
    return SCRUB.scrub(str(value), _job_secrets())[:40]


def _provider_field(body, want_job=""):
    """(the provider id, a sentence). `want_job` keeps a provider of another job out."""
    provider = str((body or {}).get("provider") or "").strip()
    known = _known_providers()
    if provider not in known:
        return "", (f"'{_echo(provider)}' is not a hosting provider this farm knows"
                    if provider else "which hosting provider?")
    job = known[provider]
    # An empty job is a mismatch, not a pass: a listed row that names no job is a provider this
    # farm cannot say is a machine, so it reaches no machine route.
    if want_job and job != want_job:
        if not job:
            return "", f"{provider} does not say whether it is a machine provider"
        return "", f"{provider} is a {job} provider, and this asks for a {want_job}"
    return provider, ""


def _name_field(body):
    name = str((body or {}).get("name") or "").strip()
    if not MACHINE_NAME.fullmatch(name):
        return "", ("a machine name is 2 to 40 characters: lower case letters, digits and "
                    "hyphens, starting with a letter")
    return name, ""


def _slug_field(body, field, what):
    value = str((body or {}).get(field) or "").strip()
    if not SIZE_OR_REGION.fullmatch(value):
        return "", f"'{_echo(value)}' is not a {what} this farm can pass on"
    return value, ""


def _confirm_usd(value):
    """The price the person typed back, as the CLI wants to read it. The CLI is what refuses a
    price that no longer matches the live one; this only keeps the field a number."""
    text = "" if isinstance(value, bool) or value is None else str(value).strip()
    if not CONFIRM_USD.fullmatch(text) or not 0 < float(text) < 100000:
        return "", "a price is a number of dollars a month, for example 48"
    if len(text) > 1 and text[0] == "0" and text[1].isdigit():
        # The CLI compares the string, so 048 would be refused there with no reason given.
        plain = text.lstrip("0")
        return "", f"write the price without leading zeros, as {'0' * plain.startswith('.')}{plain}"
    # The string as the person sent it, never reformatted: the CLI compares it with the live
    # price, and `%g` would have turned a correct 12345.67 into a refused 12345.7.
    return text, ""


def _remove_quietly(path):
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _pubkey_file(value, required):
    """(a 0600 file holding the person's public key, a sentence).

    Not a credential, so the page may take it; still theirs, so it is never left in a world
    readable file, is passed as `--pubkey-file` and not on the command line, and is deleted the
    moment the job that used it ends.
    """
    text = str((value if value is not None else "") or "").strip()
    if not text:
        return "", (PUBKEY_REQUIRED if required else "")
    if not SSH_PUBLIC.fullmatch(text):
        return "", ("that does not read as one line of an SSH public key (ssh-ed25519, ssh-rsa "
                    "or ecdsa-sha2-nistp256/384/521, then the key body)")
    handle, path = tempfile.mkstemp(prefix="fleet-pubkey-", suffix=".pub")
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w") as opened:
            opened.write(text + "\n")
    except OSError as exc:
        _remove_quietly(path)
        return "", f"this farm could not write the key to a file ({exc.__class__.__name__})"
    return path, ""


def _hosting_job(action, args, timeout, label, key, cleanup=""):
    """One hosting write as a job. However it ends, the temporary file it was handed is gone and
    the snapshot has been asked to look again."""
    def after():
        _remove_quietly(cleanup)
        _hosting_wake.set()

    code, payload = start_job(action, args, timeout, label=label, key=key, after=after)
    if code != 202:
        # Nothing started, so nothing will clean up after it.
        _remove_quietly(cleanup)
    return code, payload


def machines_plan(body):
    """POST /api/machines/plan {provider, name, size, region, ssh_public?} -> the plan's JSON,
    unwrapped.

    A POST because it runs a tool that asks the provider for today's price: a read-only page
    never needs a plan, and a GET that reached a provider would be a GET that costs a request
    per tick.
    """
    body = body or {}
    refusal = hosting_key_refusal(body)
    if refusal:
        return 400, {"error": refusal}
    provider, problem = _provider_field(body, want_job="machine")
    if problem:
        return 400, {"error": problem}
    name, problem = _name_field(body)
    if problem:
        return 400, {"error": problem}
    size, problem = _slug_field(body, "size", "size")
    if problem:
        return 400, {"error": problem}
    region, problem = _slug_field(body, "region", "region")
    if problem:
        return 400, {"error": problem}
    pubkey, problem = _pubkey_file(body.get("ssh_public"), required=False)
    if problem:
        return 400, {"error": problem}
    args = [fleet_bin(), "machines", "plan", "--provider", provider, "--name", name,
            "--size", size, "--region", region]
    if pubkey:
        args += ["--pubkey-file", pubkey]
    args.append("--json")
    try:
        code, payload, rc, out, err = run_job_now(
            "machines_plan", args, HOSTING_PLAN_TIMEOUT, label=f"Planning machine {name}",
            key="machine:" + name)
    finally:
        _remove_quietly(pubkey)
    _hosting_wake.set()
    if code != 200:
        return code, payload
    job = payload.get("job")
    if rc != 0:
        return 400, {"error": tool_message(rc, out, err, "fleet machines plan"), "job": job}
    try:
        plan = json.loads(out or "")
    except (json.JSONDecodeError, UnicodeError):
        plan = None
    if not isinstance(plan, dict):
        return 400, {"error": "fleet machines plan did not answer with JSON", "job": job}
    # The CLI's JSON as it printed it, with nothing wrapped around it: design section 7 says
    # this route "returns its JSON", and the page reads the plan's fields at the top level. The
    # job record is still on disk for a page that was reloaded, under GET /api/jobs.
    return 200, plan


def machines_create(body):
    """POST /api/machines. A droplet is bought; a machine of your own is only registered."""
    body = body or {}
    refusal = hosting_key_refusal(body)
    if refusal:
        return 400, {"error": refusal}
    provider, problem = _provider_field(body, want_job="machine")
    if problem:
        return 400, {"error": problem}
    name, problem = _name_field(body)
    if problem:
        return 400, {"error": problem}
    if provider == "ssh":
        return _machines_add_own(body, name)
    return _machines_create_droplet(body, provider, name)


def _machines_create_droplet(body, provider, name):
    size, problem = _slug_field(body, "size", "size")
    if problem:
        return 400, {"error": problem}
    region, problem = _slug_field(body, "region", "region")
    if problem:
        return 400, {"error": problem}
    price, problem = _confirm_usd(body.get("confirm_usd"))
    if problem:
        return 400, {"error": problem}
    # Required from the page, and only from the page: the finish command and the tunnel are both
    # run from the person's laptop, and without their key neither can log in.
    pubkey, problem = _pubkey_file(body.get("ssh_public"), required=True)
    if problem:
        return 400, {"error": problem}
    args = [fleet_bin(), "machines", "create", "--provider", provider, "--name", name,
            "--size", size, "--region", region, "--pubkey-file", pubkey,
            "--confirm-usd", price]
    code, payload = _hosting_job("machines_create", args, HOSTING_CREATE_TIMEOUT,
                                 f"Creating machine {name}", "machine:" + name, cleanup=pubkey)
    if code == 202:
        payload.update({"name": name, "provider": provider})
    return code, payload


def _machines_add_own(body, name):
    target = str(body.get("target") or "").strip()
    if not SSH_TARGET.fullmatch(target):
        return 400, {"error": "a machine of your own is named user@host, for example "
                              "farm@10.0.0.4"}
    args = [fleet_bin(), "machines", "add", "--name", name, "--target", target]
    raw = body.get("port")
    if raw not in (None, ""):
        try:
            port = int(str(raw).strip())
        except (TypeError, ValueError):
            port = 0
        if not 0 < port < 65536:
            return 400, {"error": "a port is a whole number from 1 to 65535"}
        args += ["--port", str(port)]
    code, payload = _hosting_job("machines_add", args, HOSTING_ADD_TIMEOUT,
                                 f"Adding machine {name}", "machine:" + name)
    if code == 202:
        payload.update({"name": name, "provider": "ssh"})
    return code, payload


def _machines_verb(body, verb, action, label, timeout, extra=()):
    """The four writes that are one verb and one machine name."""
    body = body or {}
    refusal = hosting_key_refusal(body)
    if refusal:
        return 400, {"error": refusal}
    name, problem = _name_field(body)
    if problem:
        return 400, {"error": problem}
    # No `--` separator: fleet's own case loops read a bare one as an unknown flag, and the name
    # pattern above has already refused anything that could read as an option.
    args = [fleet_bin(), "machines", verb, name] + list(extra)
    code, payload = _hosting_job(action, args, timeout, f"{label} {name}", "machine:" + name)
    if code == 202:
        payload["name"] = name
    return code, payload


def machines_check(body):
    """POST /api/machines/check {name}."""
    return _machines_verb(body, "check", "machines_check", "Checking machine",
                          HOSTING_CHECK_TIMEOUT)


def machines_destroy(body):
    """POST /api/machines/destroy {name, confirm}. The confirmation is the name itself, typed
    back: every state of a droplet but `destroyed` costs money, and destroying is the only
    thing that stops it, so it is also the only thing that cannot be undone."""
    body = body or {}
    # The classifier first, as on every other hosting route: a body carrying a token is refused
    # for that, whatever else is wrong with it.
    refusal = hosting_key_refusal(body)
    if refusal:
        return 400, {"error": refusal}
    name = str(body.get("name") or "").strip()
    if str(body.get("confirm") or "").strip() != name or not name:
        return 400, {"error": "type the machine's name to confirm: this deletes its disk"}
    return _machines_verb(body, "destroy", "machines_destroy", "Destroying machine",
                          HOSTING_DESTROY_TIMEOUT, extra=["--confirm", name])


def machines_adopt(body):
    """POST /api/machines/adopt {name}: a droplet this farm made and lost gets its row back."""
    return _machines_verb(body, "adopt", "machines_adopt", "Adopting machine",
                          HOSTING_REGISTRY_TIMEOUT)


def machines_forget(body):
    """POST /api/machines/forget {name}: the row goes, the machine is not touched."""
    return _machines_verb(body, "forget", "machines_forget", "Forgetting machine",
                          HOSTING_REGISTRY_TIMEOUT)


def hosts_check(body):
    """POST /api/hosts/check {provider}: is its CLI installed, and is this farm logged in."""
    body = body or {}
    refusal = hosting_key_refusal(body)
    if refusal:
        return 400, {"error": refusal}
    provider, problem = _provider_field(body)
    if problem:
        return 400, {"error": problem}
    args = [fleet_bin(), "hosts", "check", provider]
    code, payload = _hosting_job("hosts_check", args, HOSTING_HOSTS_CHECK_TIMEOUT,
                                 f"Checking the {provider} login", "host:" + provider)
    if code == 202:
        payload["provider"] = provider
    return code, payload


# ---------------------------------------------------------------- the head office's mail
#
# The agents talk to each other through a head office: one issue per mailbox, one comment per
# message. The dashboard READS that through gh directly and never through `hq inbox`, because a
# plain inbox read MOVES a cursor that is shared by every process signing as one name on one
# machine: a page polling it would silently eat an agent's mail.
#
# Reading happens on a background thread every 45 seconds, never on the request path, and a
# failed pass leaves the last good answer in place with `stale_since` saying when it was true.
# "GitHub did not answer" and "the office is quiet" look identical once the data is gone, and
# only one of them is worth acting on.

MAIL_REFRESH_SECONDS = 45
MAIL_WINDOW_HOURS = 24
MAIL_GH_TIMEOUT = 20          # off the request path, so it may take longer than a health check
MAIL_SEND_TIMEOUT = 30
MAIL_MAX_BYTES = 8000
# The shape hq writes a message in, and reads it back with, in registry.py's feed.
MAIL_FROM = re.compile(r"\*\*from ([^*]+)\*\* \(([^)]*)\):\n?")
FEED_LINE = re.compile(r"^(?P<at>.+?)\s\s+\[(?P<kind>[a-z]+)\]\s*(?P<text>.*)$")
WHO_LINE = re.compile(r"^(?P<name>\S+)\s+(?P<state>live|STALE)\s+updated\s+"
                      r"(?P<age>[\d.]+)h ago\s*(?P<task>.*)$")

_mail_snapshot = _blank_snapshot(boxes=[], threads={}, seen={})



def mail_unavailable():
    """(sentence, command) when there is no office to read, or None when there is.

    Every mail route answers with this, at status 200: a farm with no head office is a normal
    farm, and the tab says so in one sentence instead of showing an error.
    """
    if not hq_binary():
        return ("No head office is installed, so there is no agent mail to show.",
                "Install hq, then run: hq init --repo <owner>/<office>")
    if not hq_office():
        return ("No head office configured, so there is no agent mail to show.",
                "hq init --repo <owner>/<office>")
    if not shutil.which("gh"):
        return ("The head office is read through gh, which is not installed.",
                "Install the GitHub CLI: https://cli.github.com")
    return None


def _iso(when):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when))


def parse_iso(value):
    """One timestamp as an aware datetime, or None when it is not ISO 8601.

    Both forms this server meets are taken: the trailing Z the forge writes, and an offset. A
    stamp with no zone is read as UTC, which is what every producer here means by one. Comparing
    these as strings worked by accident for the Z form and silently answered "nothing" for
    everything else, which is worse than refusing the value.
    """
    text = (value or "").strip()
    if not text:
        return None
    try:
        when = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _gh_json(args, timeout=MAIL_GH_TIMEOUT):
    rc, out, err = run_tool(["gh"] + args, timeout=timeout)
    if rc != 0:
        message = (err or out or f"gh exited {rc}").strip()
        raise RuntimeError(message.splitlines()[0][:200] if message else f"gh exited {rc}")
    try:
        return json.loads(out or "null")
    except (json.JSONDecodeError, UnicodeError):
        raise RuntimeError("gh answered something that is not JSON")


def mail_fetch_boxes(office):
    """The office's inbox issues, one box per NAME.

    An office can hold two issues titled `inbox: winston`; it happens when a name is registered
    twice. They are one mailbox to everybody who uses them, and the dashboard used to draw that
    name twice with half the thread behind each row. The newest issue is the box people write
    to, every issue under the name is read for the thread, and the box is as fresh as the
    freshest of them.
    """
    rows = _gh_json(["issue", "list", "--repo", office, "--state", "all", "--label", "inbox",
                     "--limit", "100", "--json", "number,title,updatedAt"])
    boxes = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "")
        name = title.removeprefix("inbox: ").strip() or title
        number = row.get("number")
        stamp = row.get("updatedAt")
        box = boxes.get(name)
        if box is None:
            boxes[name] = {"name": name, "number": number, "updated_at": stamp,
                           "numbers": [number] if number is not None else []}
            continue
        if number is not None:
            box["numbers"].append(number)
            if box["number"] is None or number > box["number"]:
                box["number"] = number
        if stamp and (not box["updated_at"] or str(stamp) > str(box["updated_at"])):
            box["updated_at"] = stamp
    for box in boxes.values():
        box["numbers"] = sorted(set(box["numbers"]), reverse=True)
    return list(boxes.values())


def mail_fetch_box_thread(office, box, since):
    """One mailbox's thread, read from every inbox issue that carries its name."""
    numbers = box.get("numbers") or ([box["number"]] if box.get("number") is not None else [])
    if len(numbers) == 1:
        return mail_fetch_thread(office, numbers[0], since)
    messages = []
    for number in numbers:
        messages.extend(mail_fetch_thread(office, number, since))
    messages.sort(key=lambda message: message["created_at"])
    return messages


def mail_box_order(boxes):
    """Newest first, with "all" pinned to the top: it is the box everybody reads, and a farm
    with twenty five code names is otherwise a list in whatever order the forge answered."""
    def freshness(box):
        return str(box.get("last_at") or box.get("updated_at") or "")

    pinned = [box for box in boxes if box.get("name") == "all"]
    rest = [box for box in boxes if box.get("name") != "all"]
    rest.sort(key=freshness, reverse=True)
    return pinned + rest


def mail_fetch_thread(office, number, since):
    comments = _gh_json(["api", f"repos/{office}/issues/{number}/comments"
                                f"?since={since}&per_page=100"])
    messages = []
    for comment in comments or []:
        if not isinstance(comment, dict):
            continue
        body = str(comment.get("body") or "")
        match = MAIL_FROM.match(body)
        created = str(comment.get("created_at") or "")
        messages.append({
            "sender": match.group(1).strip() if match else "?",
            "at": (match.group(2).strip() if match else "") or created,
            "text": (body[match.end():] if match else body).strip(),
            "created_at": created,
        })
    messages.sort(key=lambda message: message["created_at"])
    return messages


def _decorate_box(box, messages, cutoff):
    """The two facts a mailbox row shows, counted once when its thread arrives rather than on
    every publish: a pass over an office of a hundred names publishes a hundred times."""
    recent = [message for message in messages
              if (parse_iso(message.get("created_at")) or cutoff) >= cutoff]
    box["count_24h"] = len(recent)
    # One clock. A sender's own stamp in the body is for display; a box's last activity is
    # the forge's `created_at`, which is the clock its `updated_at` is on too.
    box["last_at"] = (messages[-1]["created_at"] if messages else box.get("updated_at"))


def _publish_mail(boxes, threads, seen, error=None):
    """The office as it is known SO FAR. Called after the box list and again as each thread
    lands, so a page opened on a big office fills in front of the reader instead of showing
    nothing until the last mailbox has been read.

    Everything published is copied: the caller keeps filling its own dictionaries, and a
    reader copying the snapshot under the lock must not meet one of them mid write.
    """
    rows = mail_box_order([dict(box) for box in boxes])
    with _snapshot_lock:
        if error:
            _mail_snapshot["boxes"] = rows
            _mail_snapshot["threads"] = dict(threads)
            _mail_snapshot["seen"] = dict(seen)
            _snapshot_failed(_mail_snapshot, error)
        else:
            _snapshot_succeeded(_mail_snapshot, {"boxes": rows, "threads": dict(threads),
                                                 "seen": dict(seen)})


def mail_refresh():
    """One pass over the office. Called by the refresher thread, and once inline before the
    first answer, never on every request.

    The box list is one call and the threads are one call each, so the first pass on an office
    of a hundred mailboxes is a hundred calls. They are published as they arrive, and a box
    whose `updated_at` has not moved since the last pass is not read again at all.
    """
    if mail_unavailable():
        return                       # nothing to read; the routes say so themselves
    with _snapshot_lock:
        # "A pass has happened" is tracked apart from "a pass succeeded": an office that is
        # unreachable never sets `at`, and a page ticking every few seconds would then put a
        # fetch on every single request, which is the one thing the refresher exists to prevent.
        _mail_snapshot["tried"] = True
        previous = dict(_mail_snapshot["threads"])
        seen = dict(_mail_snapshot["seen"])
    office = hq_office()
    since = _iso(time.time() - MAIL_WINDOW_HOURS * 3600)
    cutoff = parse_iso(since)
    try:
        boxes = mail_fetch_boxes(office)
    except Exception as exc:
        with _snapshot_lock:
            _snapshot_failed(_mail_snapshot, str(exc)[:200])
        return
    # Every box starts from the thread already held, so the list of mailboxes is on screen
    # before the first thread is asked for.
    threads = {box["name"]: previous.get(box["name"], []) for box in boxes}
    fresh_seen, error = {}, None
    for box in boxes:
        _decorate_box(box, threads[box["name"]], cutoff)
    _publish_mail(boxes, threads, fresh_seen)
    for box in boxes:
        name = box["name"]
        stamp = box.get("updated_at")
        if name in previous and stamp is not None and seen.get(name) == stamp:
            # Nothing has been written to this box since the last pass. Fetching it again would
            # spend the shared API budget to learn that.
            fresh_seen[name] = stamp
            continue
        try:
            threads[name] = mail_fetch_box_thread(office, box, since)
            fresh_seen[name] = stamp
            _decorate_box(box, threads[name], cutoff)
        except Exception as exc:
            error = str(exc)[:200]
        _publish_mail(boxes, threads, fresh_seen, error)


def _refresh_once():
    """One pass over everything a read route serves. Each part is on its own: a head office
    that is down must not cost the page its health table.

    Forgetting old job records rides along here rather than only inside start_job: on a farm
    whose last action was a drain, nothing else would ever start, and the record would sit in
    $FLEET_STATE/jobs for ever against a document that says it is kept for a day.
    """
    for refresh in (config_refresh, services_refresh, health_refresh, mail_refresh, who_refresh,
                    feed_refresh, _forget_old_jobs):
        try:
            refresh()
        except Exception:
            pass


def _refresher(interval=REFRESH_SECONDS, stop=None):
    """The 45 second pass. `stop` exists for the suite: a refresher left running past the test
    that started it goes on spawning tools into every test that follows."""
    while stop is None or not stop.is_set():
        _refresh_wake.clear()
        _refresh_once()
        # A wait rather than a sleep, so a request for something nobody has asked for yet is
        # answered in a moment instead of at the end of this sleep.
        _refresh_wake.wait(interval)


def start_refresher():
    thread = threading.Thread(target=_refresher, name="refresher", daemon=True)
    thread.start()
    return thread


def mail_snapshot():
    """A deep copy of the last office snapshot the refresher produced. A handler that mutates
    its answer must not poison the shared one, and no handler ever fills it: a read that pays
    for a fetch is a read that blocks on GitHub."""
    return _copy_snapshot(_mail_snapshot)


def mail_boxes():
    unavailable = mail_unavailable()
    if unavailable:
        return {"unavailable": unavailable[0], "fix": unavailable[1]}
    snapshot = mail_snapshot()
    return _envelope(snapshot, {"boxes": snapshot.get("boxes") or []})


def mail_thread(box, since=""):
    unavailable = mail_unavailable()
    if unavailable:
        return 200, {"unavailable": unavailable[0], "fix": unavailable[1]}
    box = (box or "").strip()
    if not box:
        return 400, {"error": "a mailbox name is required"}
    snapshot = mail_snapshot()
    threads = snapshot.get("threads") or {}
    if box not in threads:
        if snapshot.get("at") is None:
            # The office has never answered, so this dashboard does not know which mailboxes
            # exist. Saying one is missing would turn an outage into "your mailbox is gone".
            return 200, _envelope(snapshot, {"box": box, "messages": [],
                                             "window_hours": MAIL_WINDOW_HOURS})
        return 404, {"error": f"there is no mailbox named '{box}' in this office",
                     "boxes": sorted(threads)}
    since = (since or "").strip()
    cutoff = parse_iso(since) if since else None
    if since and cutoff is None:
        return 400, {"error": "since must be an ISO 8601 timestamp, for example "
                              "2026-09-21T08:00:00Z"}
    messages = []
    for message in threads[box]:
        stamp = parse_iso(message.get("created_at")) if cutoff is not None else None
        # A message whose own stamp cannot be read is shown rather than hidden: losing mail is
        # the worse failure of the two.
        if stamp is not None and stamp <= cutoff:
            continue
        messages.append(message)
    return 200, _envelope(snapshot, {"box": box, "messages": messages,
                                     "window_hours": MAIL_WINDOW_HOURS})


_who_snapshot = _blank_snapshot(sessions=[])
# One feed per window asked for, the default always among them. A window nobody has asked for is
# registered on the first request and filled by the next pass, which the request wakes.
_feed_snapshots = {}
_feed_windows = [float(MAIL_WINDOW_HOURS)]
FEED_WINDOWS_TRACKED = 8
# The timeline is ASSEMBLED HERE, never by running `hq feed`. That command re-reads every
# mailbox in the office for itself: on the farm with ninety nine of them it takes eighty seven
# seconds, which is past any timeout a page can wait behind, so the route answered an error and
# the Overview said the agents had been silent all day. Everything the timeline shows is
# already held: the threads this server reads for the Mail tab, the sessions `hq who` reports
# in 0.7s, and the live branch claims.
FEED_TEXT_LIMIT = 200
# A day of a busy office is thousands of messages, and no reader scrolls past the newest few
# hundred. The cut keeps the newest, which is the end a timeline is read from.
FEED_MAX_EVENTS = 200
# `hq claims` reads one git branch. It is the one part of the timeline this server cannot
# assemble from what it already holds, so it is guarded like every other tool call and the
# timeline simply loses its claim lines when it does not answer.
CLAIM_LINE = re.compile(r"^(?P<repo>\S+)\s+(?P<branch>\S+)\s+(?P<owner>\S+)\s+until\s+"
                        r"(?P<until>\S+)\s*(?P<note>.*)$")


def _first_line(text, fallback):
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[0].strip()[:200] if lines else fallback


def _feed_text(value):
    """One line, cut to what a timeline row can show. A message that arrives as five paragraphs
    is a message this list would otherwise be nothing but."""
    return " ".join(str(value or "").split())[:FEED_TEXT_LIMIT]


def _feed_seconds(event):
    when = parse_iso(event.get("at"))
    return when.timestamp() if when else None


def _mail_events(threads):
    """Every message in every mailbox, as one line each. The threads are the ones the Mail tab
    already reads, so the timeline costs this server nothing it was not already paying."""
    events = []
    for name, messages in (threads or {}).items():
        for message in messages or []:
            events.append({
                "at": message.get("created_at") or None,
                "at_label": None,
                "kind": "mail",
                "text": _feed_text(f"{message.get('sender') or '?'} to {name}: "
                                   f"{message.get('text') or ''}"),
            })
    return events


def _session_events(sessions):
    """Who said hello, and when. The session list is `hq who`, which answers in under a second
    and is read once a pass for the Mail tab's own panel."""
    events = []
    for session in sessions or []:
        task = _feed_text(session.get("task"))
        state = "active" if session.get("state") == "live" else "quiet"
        name = session.get("name") or "?"
        events.append({"at": session.get("since"), "at_label": None, "kind": "session",
                       "text": _feed_text(f"{name} {state}" + (f": {task}" if task else ""))})
    return events


def _parse_claims(out):
    """The live branch claims, one line each.

    A claim has no moment: it is a fact about now, and the only time it carries is when it runs
    out. So it gets no stamp to be sorted by and says "held now" where the others say how long
    ago they happened, and the assembly puts these at the top of the list.
    """
    events = []
    for line in (out or "").splitlines():
        match = CLAIM_LINE.match(line.strip())
        if not match:
            continue                 # "no active claims", and anything else hq chooses to say
        events.append({"at": None, "at_label": "held now", "kind": "claim",
                       "text": _feed_text(f"{match.group('owner')} holds {match.group('repo')}"
                                          f"#{match.group('branch')} "
                                          f"until {match.group('until')}")})
    return events


def read_claims():
    """The claim lines, or none of them. A slow or failing `hq claims` costs the timeline its
    claims and nothing else: the messages and the sessions are the substance."""
    rc, out, _err = run_tool([hq_binary(), "claims"], timeout=MAIL_GH_TIMEOUT)
    return _parse_claims(out) if rc == 0 else []


def assemble_feed(threads, sessions, claims):
    """One office timeline, newest first. Claims lead it: they are what is true now, not what
    happened at some point in the day."""
    timed = _mail_events(threads) + _session_events(sessions)
    # A message whose stamp cannot be read is shown rather than hidden, at the end of the list:
    # losing mail is the worse failure of the two.
    timed.sort(key=lambda event: (_feed_seconds(event) is not None, _feed_seconds(event) or 0),
               reverse=True)
    return list(claims) + timed


def feed_in_window(events, hours, now=None):
    now = time.time() if now is None else now
    cutoff = now - hours * 3600
    kept = [event for event in events
            if _feed_seconds(event) is None or _feed_seconds(event) >= cutoff]
    return kept[:FEED_MAX_EVENTS]


def _parse_who(out, now=None):
    now = time.time() if now is None else now
    sessions = []
    for line in (out or "").splitlines():
        match = WHO_LINE.match(line.strip())
        if not match:
            continue
        age = float(match.group("age"))
        sessions.append({"name": match.group("name"),
                         "state": "live" if match.group("state") == "live" else "stale",
                         "age_hours": age,
                         # hq reports an age to a tenth of an hour, so this stamp is good to a
                         # few minutes. It is here because a time can be sorted and compared
                         # against every other answer on this page, and an age cannot.
                         "since": _iso(now - age * 3600),
                         "task": match.group("task").strip()})
    return sessions


def _feed_window(hours):
    try:
        window = float(hours) if str(hours or "").strip() else float(MAIL_WINDOW_HOURS)
    except (TypeError, ValueError):
        window = float(MAIL_WINDOW_HOURS)
    return max(0.1, min(720.0, window))


def _feed_key(window):
    return f"{window:g}"


def who_refresh():
    if mail_unavailable():
        return
    rc, out, err = run_tool([hq_binary(), "who"], timeout=MAIL_GH_TIMEOUT)
    with _snapshot_lock:
        if rc != 0:
            _snapshot_failed(_who_snapshot, _first_line(err or out, f"hq who exited {rc}"))
            return
        previous = {session["name"]: session for session in _who_snapshot["sessions"]}
        sessions = _parse_who(out)
        for session in sessions:
            older = previous.get(session["name"])
            # The same reading implies the same moment. hq reports an AGE, so deriving a stamp
            # from it again a second later moves it a second, and every row that carries it
            # redraws, and nothing that holds two of these snapshots can compare them.
            if older and older.get("age_hours") == session["age_hours"]:
                session["since"] = older["since"]
        _snapshot_succeeded(_who_snapshot, {"sessions": sessions})


def feed_refresh():
    """The timeline for every window asked for, built from the office this server already
    holds. It runs after the mail and session passes, so what it assembles is this pass's
    answer, and it is exactly as fresh, or as stale, as the office read that produced it."""
    if mail_unavailable():
        return
    with _snapshot_lock:
        windows = list(_feed_windows)
        tried = _mail_snapshot["tried"]
        threads = dict(_mail_snapshot["threads"])
        error = _mail_snapshot["error"]
        stale_since = _mail_snapshot["stale_since"] or _mail_snapshot["at"]
        sessions = list(_who_snapshot["sessions"])
    if not tried:
        return                       # the office has not been read yet; a timeline now is a guess
    events = assemble_feed(threads, sessions, read_claims())
    for window in windows:
        kept = feed_in_window(events, window)
        with _snapshot_lock:
            entry = _feed_snapshots.setdefault(
                _feed_key(window), _blank_snapshot(events=[], hours=window))
            if error:
                # The office could not be read. The timeline still shows what was held, and
                # says so: "the forge is unreachable" and "nobody said anything" look identical
                # once the words are gone, and only one of them is worth acting on.
                entry.update({"events": kept, "hours": window, "tried": True,
                              "error": error, "stale_since": stale_since})
            else:
                _snapshot_succeeded(entry, {"events": kept, "hours": window})


def mail_feed(hours=None):
    unavailable = mail_unavailable()
    if unavailable:
        return {"unavailable": unavailable[0], "fix": unavailable[1]}
    window = _feed_window(hours)
    key = _feed_key(window)
    with _snapshot_lock:
        entry = _feed_snapshots.get(key)
        if entry is None:
            entry = _blank_snapshot(events=[], hours=window)
            _feed_snapshots[key] = entry
            _feed_windows.append(window)
            while len(_feed_windows) > FEED_WINDOWS_TRACKED:
                for candidate in _feed_windows:
                    if candidate != float(MAIL_WINDOW_HOURS):
                        _feed_windows.remove(candidate)
                        _feed_snapshots.pop(_feed_key(candidate), None)
                        break
                else:
                    break
        copy = json.loads(json.dumps(entry))
    if not copy["tried"]:
        _refresh_wake.set()
    return _envelope(copy, {"events": copy.get("events") or [], "hours": window})


def mail_who():
    unavailable = mail_unavailable()
    if unavailable:
        return {"unavailable": unavailable[0], "fix": unavailable[1]}
    snapshot = _copy_snapshot(_who_snapshot)
    if not snapshot["tried"]:
        _refresh_wake.set()
    return _envelope(snapshot, {"sessions": snapshot.get("sessions") or []})


def mail_send(body):
    """(status, payload) for POST /api/mail/send.

    The dashboard signs as its own identity, FLEET_DASH_HQ_AGENT, never as a name taken from the
    request: mail that can claim any sender is not mail anyone can act on.
    """
    unavailable = mail_unavailable()
    if unavailable:
        return 200, {"unavailable": unavailable[0], "fix": unavailable[1]}
    target = str(body.get("to") or "").strip()
    text = str(body.get("text") or "").strip()
    snapshot = mail_snapshot()
    if snapshot.get("at") is None:
        # Sending to a name that is not a mailbox CREATES one, so a typo would leave a ghost
        # nobody reads. Without a box list this dashboard cannot tell the two apart, and the
        # honest answer is to come back in a moment rather than to guess.
        return 503, {"error": "the head office has not been read yet, so this dashboard cannot "
                              "tell whether that is a mailbox",
                     "fix": "try again in a moment"}
    known = {box["name"] for box in (snapshot.get("boxes") or [])} | {"all"}
    if target not in known:
        return 400, {"error": f"'{target}' is not a mailbox in this office",
                     "boxes": sorted(known)}
    if not text:
        return 400, {"error": "a message needs some text"}
    if len(text.encode()) > MAIL_MAX_BYTES:
        return 400, {"error": f"a message is at most {MAIL_MAX_BYTES} bytes"}
    agent = dash_hq_agent()
    environment = dict(os.environ)
    environment["HQ_AGENT"] = agent
    # `--` first: hq parses its two positionals with argparse, which reads a leading dash as
    # an option. Without the separator a message of "-h" printed the subcommand's help, exited
    # 0, and this route answered "sent" for a message nobody received.
    rc, out, err = run_tool([hq_binary(), "msg", "--", target, text], timeout=MAIL_SEND_TIMEOUT,
                            env=environment)
    if rc != 0:
        lines = [line for line in ((err or "") + "\n" + (out or "")).splitlines() if line.strip()]
        return 400, {"error": (lines[-1].strip() if lines else f"hq msg exited {rc}")[:400]}
    # The message is in the office now, but this dashboard reads the office on a cadence, so
    # without this wake a sender watches their own message take up to forty five seconds to
    # appear in the thread they just sent it to.
    _refresh_wake.set()
    return 200, {"ok": True, "to": target, "from": agent, "detail": (out or "").strip()[:200],
                 "refreshing": True}



def sweep_status():
    """State of the autosweep systemd --user timer, for the header countdown. Uses the
    MONOTONIC next-elapse (OnUnitActiveSec is monotonic) and the same clock in Python, so
    'seconds until the next sweep' needs no wall-clock/date parsing.

    Runs two processes, so only the machine refresher calls it; /api/sweep serves what it left."""
    timer = _unit_properties(SWEEP_TIMER_UNIT, "UnitFileState", "NextElapseUSecMonotonic")
    enabled = timer.get("UnitFileState") in ("enabled", "enabled-runtime")
    secs = None
    if enabled:
        nxt = _systemd_duration(timer.get("NextElapseUSecMonotonic"))   # monotonic seconds
        if nxt > 0:
            secs = max(0.0, nxt - time.clock_gettime(time.CLOCK_MONOTONIC))
    service = _unit_properties(SWEEP_TIMER_UNIT.replace(".timer", ".service"), "Result")
    return {"enabled": enabled, "secs_left": secs, "result": service.get("Result") or None}


# What a forge calls a check that did not pass, mapped onto the five words this page draws.
CI_FAILED = ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE")
CI_PENDING = ("QUEUED", "IN_PROGRESS", "WAITING", "PENDING", "REQUESTED", "EXPECTED")


def _check_state(check):
    """One check's state: pass, fail, pending, skipped or unknown.

    A check carries either a conclusion (an Actions run) or a state (an older status context),
    so both are read and the first that says something wins.
    """
    concl = str(check.get("conclusion") or "").upper()
    state = str(check.get("state") or "").upper()
    status = str(check.get("status") or "").upper()
    if concl in ("SUCCESS", "NEUTRAL") or state == "SUCCESS":
        return "pass"
    if concl in CI_FAILED or state in ("FAILURE", "ERROR"):
        return "fail"
    if concl == "SKIPPED" or state == "SKIPPED":
        return "skipped"
    if status in CI_PENDING or state in CI_PENDING:
        return "pending"
    return "unknown"


def _ci_parse(rollup):
    """A PR's statusCheckRollup -> [{"name": ..., "state": ...}], in the order the forge gave.

    EVERY check is kept, under the name the forge reported it by. This used to keep only names
    containing backend, frontend or docker, which is one farm's job names baked into the tool:
    a farm whose jobs are called anything else read as "nothing has reported yet", forever.
    """
    out = []
    for check in rollup or []:
        if not isinstance(check, dict):
            continue
        name = str(check.get("name") or check.get("context") or "").strip()
        if not name:
            continue
        out.append({"name": name, "state": _check_state(check)})
    return out


def _ci_refresh():
    """Poll GitHub once per PR for its check states: every 60s, not every tick."""
    try:
        import tomllib
        cfg = tomllib.load(open(os.path.join(CONFIG, "projects.toml"), "rb"))
    except Exception:
        cfg = {}
    fresh = {}
    for s in agents():
        br = s.get("branch") or ""
        if not s.get("pr_url") or not br or br in fresh:
            continue
        path = (cfg.get(s.get("project") or "") or {}).get("path", "")
        path = os.path.expanduser(path) if path else ""
        if not path:
            continue
        try:
            r = subprocess.run(["gh", "pr", "view", br, "--json", "statusCheckRollup"],
                               cwd=path, capture_output=True, text=True, timeout=25)
            read = _ci_parse(json.loads(r.stdout or "{}").get("statusCheckRollup"))
            # An empty reading means nothing was read, not "this change has no checks", so it
            # must never become the answer: the lane's own record is better than nothing.
            if read:
                fresh[br] = read
            elif CI_CACHE.get(br):
                fresh[br] = CI_CACHE[br]
        except Exception:
            keep = CI_CACHE.get(br)                     # keep last-known on a transient error
            if keep:
                fresh[br] = keep
    CI_CACHE.clear()
    CI_CACHE.update(fresh)


def _ci_loop():
    while True:
        try:
            _ci_refresh()
        except Exception:
            pass
        time.sleep(60)


def resolve_bind(value):
    """(the address to bind, a refusal sentence). Only `tailscale` needs resolving.

    FLEET_DASH_BIND=tailscale means this machine's Tailscale IPv4 address, asked of `tailscale
    ip -4` at start. Without one the server refuses to start rather than bind anything wider:
    under systemd it exits, and the unit tries again until the tailnet is up.
    """
    if (value or "").strip().lower() != "tailscale":
        return value, ""
    try:
        done = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True,
                              timeout=10, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return "", ("FLEET_DASH_BIND=tailscale, and tailscale is not installed on this machine; "
                    "install it, or set FLEET_DASH_BIND=127.0.0.1 and reach the page over ssh")
    except (subprocess.TimeoutExpired, OSError):
        return "", "FLEET_DASH_BIND=tailscale, and `tailscale ip -4` did not answer in 10 seconds"
    for line in (done.stdout or "").splitlines():
        candidate = line.strip()
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.version == 4 and not address.is_unspecified:
            return candidate, ""
    return "", ("FLEET_DASH_BIND=tailscale, and Tailscale has no IPv4 address on this machine "
                "yet (not up, or logged out), so the dashboard does not start rather than bind "
                "anything wider")


def bind_is_loopback(bind=None):
    """True when the server is reachable only from this machine. An empty bind, 0.0.0.0 or ::
    mean every interface, so they are NOT loopback."""
    value = BIND if bind is None else bind
    value = (value or "").strip()
    if not value:
        return False
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def presented_token(headers, query_token=""):
    """The bearer token on a request, or "" when there is none. The query form exists because a
    browser cannot set a header on the address bar: the page is opened once as /?token=... and
    carries the header itself from then on."""
    raw = headers.get("Authorization", "") or ""
    prefix = "bearer "
    if raw[:len(prefix)].lower() == prefix:
        return raw[len(prefix):].strip()
    return (query_token or "").strip()


def _bytes(value):
    """Compare tokens as bytes. hmac.compare_digest raises TypeError on a non-ASCII str, so a
    header of `Bearer u<umlaut>` used to kill the handler with a traceback, and a non-ASCII
    FLEET_DASH_TOKEN broke every write."""
    return (value or "").encode("utf-8", "surrogateescape")


def token_ok(headers, query_token=""):
    if not TOKEN:
        return False
    return hmac.compare_digest(_bytes(presented_token(headers, query_token)), _bytes(TOKEN))


def cross_site(headers):
    """(True, why) when the browser itself says this request came from somewhere else.

    A token is not enough on its own: the interesting attacker is a page the operator opens in
    another tab, which can POST to this server without ever reading a response. Both signals are
    set by the browser and cannot be forged by page script."""
    site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if site and site not in ("same-origin", "none"):
        return True, f"cross-site request refused (Sec-Fetch-Site: {site})"
    origin = (headers.get("Origin") or "").strip()
    if origin and origin.lower() != "null":
        host = (headers.get("Host") or "").strip()
        if urlparse(origin).netloc != host:
            return True, f"cross-origin request refused (Origin: {origin})"
    return False, ""


def may_mutate(headers, query_token=""):
    """Whether this request is allowed to change anything, and why not when it is not."""
    blocked, why = cross_site(headers)
    if blocked:
        return False, why
    if token_ok(headers, query_token):
        return True, ""
    if not TOKEN:
        return False, ("no write token is configured: set FLEET_DASH_TOKEN, or let "
                       "`fleet dashboard start` mint one and read it with `fleet dashboard token`")
    return False, "a bearer token is required (fleet dashboard token)"


def may_read(headers, query_token=""):
    """Reads are open on a loopback bind. Once the bind is wide they need the same token: a lane's
    brief, its result text and its log paths are not public just because nobody can click."""
    if bind_is_loopback():
        return True, ""
    if token_ok(headers, query_token):
        return True, ""
    return False, (f"this dashboard is bound to {BIND}, so reading needs the bearer token too "
                   "(open it once as /?token=...)")


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    # The shell, its files, and the routes that only describe this dashboard: served without a
    # token, on any bind, or a wide-bound dashboard could not be opened at all (the token arrives
    # in the URL of this very page). They expose no lane data.
    OPEN_PATHS = ("/", "/index.html", "/api/access", "/api/version", "/api/config")

    def _is_open(self, path):
        """Served without a token on any bind. The front end's own files join the shell for the
        same reason the shell is open: the token arrives in the URL of the page they build."""
        return path in self.OPEN_PATHS or path.startswith("/static/")

    def _query_token(self):
        return parse_qs(urlparse(self.path).query).get("token", [""])[0]

    def _read_body(self):
        """(the request's JSON object, an error sentence).

        A length that is not a number used to raise straight through the handler, which catches
        only a broken pipe, so the client was handed nothing at all: no status, no body, just a
        closed connection. Every way a body can be wrong is an answer instead.
        """
        raw = (self.headers.get("Content-Length") or "0").strip()
        try:
            length = int(raw)
        except ValueError:
            return {}, "Content-Length is not a number"
        if length < 0:
            return {}, "Content-Length is negative"
        if length > MAX_BODY_BYTES:
            return {}, f"a request body is at most {MAX_BODY_BYTES} bytes"
        try:
            payload = self.rfile.read(length) if length else b""
        except OSError:
            return {}, "the request body could not be read"
        if not payload.strip():
            return {}, ""
        try:
            body = json.loads(payload)
        except (json.JSONDecodeError, UnicodeError):
            return {}, "the request body is not JSON"
        if not isinstance(body, dict):
            return {}, "the request body is not a JSON object"
        return body, ""

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if not self._is_open(path):
                readable, why = may_read(self.headers, self._query_token())
                if not readable:
                    self._send(403, json.dumps({"error": why}))
                    return
            if path.startswith("/api/github"):
                code, payload = GH.get_route(path)
                self._send(code, json.dumps(payload))
            elif path.startswith("/static/"):
                code, body, ctype = static_file(path[len("/static/"):])
                self._send(code, body, ctype)
            elif path.startswith("/api/access"):
                # The page asks this on load so it can grey out what it cannot do, instead of
                # letting a click fail with a 403 the user never sees.
                writable, why = may_mutate(self.headers, self._query_token())
                self._send(200, json.dumps({"writable": writable, "reason": why,
                                            "token_required": True,
                                            "loopback": bind_is_loopback()}))
            elif path == "/api/config":
                # Open, because the page cannot decide what to draw, or even what it is called,
                # before it has this.
                self._send(200, json.dumps(config_payload()))
            elif path.startswith("/api/version"):
                self._send(200, json.dumps({"v": page_build()}))
            elif path.startswith("/api/identities"):
                # one code name -> one mark; the card reads its emoji/colour from here,
                # not from the per-agent field, so an initiator is never scattered.
                self._send(200, json.dumps(ID.load()))
            elif path == "/api/accounts/login-state":
                self._send(200, json.dumps(accounts_login_state()))
            elif path.startswith("/api/accounts"):
                self._send(200, json.dumps(accounts_snapshot()))
            elif path == "/api/models/presets":
                # Above the prefix-matched model route: the services a person can add are not
                # the models this farm has.
                self._send(200, json.dumps(model_presets_listing()))
            elif path == "/api/engines":
                # Above the prefix-matched model route, and its own name: it answers the
                # catalog plus what this machine actually has installed.
                self._send(200, json.dumps(engines()))
            elif path.startswith("/api/models"):
                self._send(200, json.dumps(MODELS.listing()))
            elif path.startswith("/api/mode"):
                self._send(200, json.dumps(_machine_part("mode")))
            elif path == "/api/projects/next-port":
                self._send(200, json.dumps(next_port_answer()))
            elif path == "/api/projects":
                self._send(200, json.dumps(GH.decorate_projects(projects())))
            elif path == "/api/machines":
                # From the hosting snapshot. Like every read here it runs nothing: listing
                # droplets is a provider request, and this page redraws every few seconds.
                self._send(200, json.dumps(hosting_machines()))
            elif path == "/api/hosts":
                self._send(200, json.dumps(hosting_hosts()))
            elif path == "/api/mail/boxes":
                self._send(200, json.dumps(mail_boxes()))
            elif path == "/api/mail/thread":
                query = parse_qs(urlparse(self.path).query)
                code, payload = mail_thread(query.get("box", [""])[0],
                                            query.get("since", [""])[0])
                self._send(code, json.dumps(payload))
            elif path == "/api/mail/feed":
                query = parse_qs(urlparse(self.path).query)
                self._send(200, json.dumps(mail_feed(query.get("hours", [""])[0])))
            elif path == "/api/mail/who":
                self._send(200, json.dumps(mail_who()))
            elif path == "/api/health":
                self._send(200, json.dumps(health()))
            elif path.startswith("/api/sweep"):
                self._send(200, json.dumps(_machine_part("sweep")))
            elif path.startswith("/api/metrics"):
                self._send(200, json.dumps(_machine_part("metrics")))
            elif path == "/api/services":
                self._send(200, json.dumps(services()))
            elif path == "/api/power/preview":
                query = parse_qs(urlparse(self.path).query)
                code, payload = power_preview(query.get("action", [""])[0])
                self._send(code, json.dumps(payload))
            elif path == "/api/jobs":
                self._send(200, json.dumps({"jobs": running_jobs()}))
            elif path.startswith("/api/jobs/"):
                code, payload = read_job(path[len("/api/jobs/"):])
                self._send(code, json.dumps(payload))
            elif path == "/api/agent/log":
                query = parse_qs(urlparse(self.path).query)
                code, payload = agent_log(query.get("slug", [""])[0],
                                          query.get("tail", [""])[0])
                self._send(code, json.dumps(payload))
            elif path.startswith("/api/agent"):
                slug = parse_qs(urlparse(self.path).query).get("slug", [""])[0]
                self._send(200, json.dumps(agent_detail(slug)))
            elif path.startswith("/api/fleet"):
                self._send(200, json.dumps(agents()))
            elif path in ("/", "/index.html"):
                self._send(200, open(INDEX, "rb").read(), "text/html; charset=utf-8")
            else:
                self._send(404, "not found", "text/plain")
        except BrokenPipeError:
            pass
        except Exception as exc:
            self._answer_failure("GET", exc)

    def do_POST(self):
        try:
            writable, why = may_mutate(self.headers, self._query_token())
            if not writable:
                self._send(403, json.dumps({"error": why}))
                return
            path = urlparse(self.path).path
            # Read once, here: every branch below used to parse the body itself, and each was
            # one more place where a malformed header dropped the connection.
            body, problem = self._read_body()
            if problem:
                self._send(400, json.dumps({"error": problem}))
                return
            if path.startswith("/api/github"):
                code, payload = GH.post_route(path, body)
                self._send(code, json.dumps(payload))
            elif path == "/api/projects":
                code, payload = add_project(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/projects/remove":
                code, payload = remove_project(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/services":
                code, payload = service_action(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/mail/send":
                code, payload = mail_send(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/agent/msg":
                code, payload = agent_msg(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/power":
                code, payload = power_action(body)
                self._send(code, json.dumps(payload))
            # Hosting. Every one of these is an exact path, and /api/machines/plan is written
            # out above /api/machines for a reader, not for the match: none of them is a prefix
            # of another.
            elif path == "/api/machines/plan":
                code, payload = machines_plan(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/machines/check":
                code, payload = machines_check(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/machines/destroy":
                code, payload = machines_destroy(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/machines/adopt":
                code, payload = machines_adopt(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/machines/forget":
                code, payload = machines_forget(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/machines":
                code, payload = machines_create(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/hosts/check":
                code, payload = hosts_check(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/agents/kill":
                code, payload = agent_kill(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/models/add":
                code, payload = add_model_request(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/models/remove":
                code, payload = remove_model_request(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/models/discover":
                code, payload = discover_models_request(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/models/select":
                code, payload = select_models_request(body)
                self._send(code, json.dumps(payload))
            elif self.path.startswith("/api/models"):
                act, mid = body.get("action", ""), body.get("id", "")
                if act == "enable":
                    m, err = MODELS.set_enabled(mid, True)
                elif act == "disable":
                    m, err = MODELS.set_enabled(mid, False)
                elif act == "test":
                    m, err = MODELS.run_test(mid)
                else:
                    err, m = "unknown action", None
                self._send(200 if not err else 400, json.dumps({"model": m, "error": err}))
            elif self.path.startswith("/api/mode"):
                try:
                    MODE.set_setting(body.get("mode", ""))
                except ValueError as e:
                    self._send(400, json.dumps({"error": str(e)}))
                    return
                self._send(200, json.dumps(MODE.tick(force=True)))  # apply now
            elif path == "/api/accounts/refresh":
                code, payload = accounts_refresh_request()
                self._send(code, json.dumps(payload))
            elif self.path.startswith("/api/accounts/add"):
                engine = (body.get("engine") or "claude").strip()
                if engine == "codex":
                    # codex is a single shared account (~/.codex, Team plan): no dir-per-name; this
                    # just re-logs it in through the SSH-tunnelled OAuth callback.
                    self._send(200, json.dumps({
                        "name": "codex", "engine": "codex",
                        "command": ("ssh -L 1455:localhost:1455 -t %s codex login"
                                    % CA.FARM_ALIAS),
                        "steps": ["codex is one shared account: this RE-LOGS it in (not a new account)",
                                  "Run the command from wherever you reach this farm (the -L tunnels the OAuth callback)",
                                  "A browser opens; authorize with your ChatGPT account",
                                  "Wait for 'Successfully logged in'",
                                  "Click Refresh here"]}))
                    return
                name = (body.get("name") or "").strip()
                if not re.match(r"^[A-Za-z0-9._-]{1,40}$", name) or name == "default":
                    self._send(400, json.dumps({"error": "invalid account name"})); return
                path = os.path.join(CA.EXTRA_DIR, name)
                if os.path.isdir(path) and os.path.exists(os.path.join(path, ".credentials.json")):
                    self._send(409, json.dumps({"error": "account already exists"})); return
                os.makedirs(path, exist_ok=True)
                # The login is interactive OAuth on the user's Mac: this command opens Claude in the
                # new account's config dir; the user runs /login inside and pastes the browser code.
                cmd = ("ssh -t %s 'CLAUDE_CONFIG_DIR=$HOME/.fleet/claude-accounts/%s claude'"
                       % (CA.FARM_ALIAS, name))
                self._send(200, json.dumps({
                    "name": name, "command": cmd,
                    "steps": ["Run the command from wherever you reach this farm",
                              "In the Claude TUI type: /login",
                              "Choose 'Claude account with subscription'",
                              "Open the URL, authorize, paste the code back",
                              "Type /exit, then click Refresh here"]}))
            elif self.path.startswith("/api/accounts/remove"):
                name = (body.get("name") or "").strip()
                if not re.match(r"^[A-Za-z0-9._-]{1,40}$", name) or name in ("default", "codex"):
                    self._send(400, json.dumps({"error": "cannot remove this account"})); return
                path = os.path.join(CA.EXTRA_DIR, name)
                if not os.path.isdir(path):
                    self._send(404, json.dumps({"error": "no such account"})); return
                backup_dir = os.path.join(os.path.dirname(CA.EXTRA_DIR), "dead-account-backups")
                os.makedirs(backup_dir, exist_ok=True)
                dest = os.path.join(backup_dir, name + ".wiped")
                if os.path.exists(dest):
                    dest = dest + "." + str(int(os.path.getmtime(path)))
                shutil.move(path, dest)
                for st in (".last-balance", ".last-pick"):
                    try: os.remove(os.path.join(CA.EXTRA_DIR, st))
                    except OSError: pass
                self._send(200, json.dumps({"ok": True, "name": name, "backup": dest}))
            else:
                self._send(404, "not found", "text/plain")
        except BrokenPipeError:
            pass
        except Exception as exc:
            self._answer_failure("POST", exc)

    def _answer_failure(self, method, exc):
        """A handler that raises must still answer. Dropping the connection hands the page no
        status and no sentence, which reads as a dead server rather than a broken request."""
        # The path only, never the query: `?token=` is how a browser first hands the token over,
        # and a log line is read by far more people than the token was meant for. A query value
        # the exception itself repeats is taken out too.
        parsed = urlparse(self.path)
        said = str(exc)
        for values in parse_qs(parsed.query).values():
            for value in values:
                if value:
                    said = said.replace(value, "<query value>")
        print(f"fleet dashboard: {method} {parsed.path} failed: {type(exc).__name__}: {said}",
              file=sys.stderr)
        try:
            self._send(500, json.dumps({"error": "this dashboard could not answer that "
                                                 "request; its log says why"}))
        except Exception:
            pass

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler, *args, **kwargs):
        # FLEET_DASH_BIND may be an IPv6 literal (`::1`, `::`). On a default AF_INET socket that
        # dies with gaierror the moment it starts, and the dashboard reads as broken rather than
        # as misconfigured, so pick the family from the address.
        try:
            if ipaddress.ip_address(server_address[0]).version == 6:
                self.address_family = socket.AF_INET6
        except ValueError:
            pass
        super().__init__(server_address, handler, *args, **kwargs)


def _mode_loop():
    # The always-on applier for `auto`: re-resolve the power mode off the GPU every few
    # seconds and keep fleet.slice's CPU cap in step. Harmless for manual modes (idempotent).
    while True:
        try:
            MODE.tick()
        except Exception:
            pass
        time.sleep(5)


if __name__ == "__main__":
    BIND, refusal = resolve_bind(BIND)
    if refusal:
        print(f"fleet dashboard: {refusal}", file=sys.stderr, flush=True)
        raise SystemExit(1)
    TOKEN = ensure_token()
    reach = "this machine only" if bind_is_loopback() else f"anything that can reach {BIND}"
    print(f"fleet dashboard on {BIND}:{PORT} ({reach})", flush=True)
    if TOKEN:
        print("  writing needs the bearer token; read it with: fleet dashboard token", flush=True)
        if not bind_is_loopback():
            print("  bound wide, so reading needs it too", flush=True)
    else:
        print("  READ-ONLY: no write token could be stored; set FLEET_DASH_TOKEN", flush=True)
    machine_refresh()          # prime it: the first page must not open on an empty strip
    start_machine_refresher()
    start_hosting_refresher()
    threading.Thread(target=_mode_loop, daemon=True).start()
    threading.Thread(target=_ci_loop, daemon=True).start()
    threading.Thread(target=_accounts_refresher, name="accounts-refresher", daemon=True).start()
    start_refresher()
    GH.start(office=hq_office, registry=_projects_registry)
    Server((BIND, PORT), Handler).serve_forever()
