#!/usr/bin/env python3
"""Fleet dashboard, a stdlib-only HTTP server. Serves the single-page UI plus
   /api/fleet (agent state) and /api/metrics (farm health).

   Binding and write access are configuration, not a constant. FLEET_DASH_BIND
   defaults to 127.0.0.1: reaching the page from another machine (a tailnet, a
   LAN) is a deliberate act.

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
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET_HOME = os.path.dirname(HERE)          # the checkout this file lives in, never a fixed path
sys.path.insert(0, os.path.join(FLEET_HOME, "lib"))
import ci as CI  # noqa: E402
import metrics as M  # noqa: E402
import identity as ID  # noqa: E402
import claude_accounts as CA  # noqa: E402
import codex_usage as CX  # noqa: E402
import mode as MODE  # noqa: E402
import models as MODELS  # noqa: E402

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
CI_LOG_TAIL_BYTES = 256 * 1024
MAX_BODY_BYTES = 256 * 1024
CI_DAEMON_UNIT = "fleet-ci.service"
SWEEP_TIMER_UNIT = "fleet-sweep.timer"
DEFAULT_TITLE = "murmur"
DEFAULT_HQ_AGENT = "dashboard"
# A tool that does not answer must not hold a page open. Three seconds is longer than any of
# these take when the machine is well, and short enough that a hung one reads as a failed check.
TOOL_TIMEOUT = 3


def run_tool(args, timeout=TOOL_TIMEOUT, env=None):
    """(returncode, stdout, stderr) from a command line tool. Never raises: a missing binary, a
    hung one and a failing one are all answers this page has to draw, not crashes."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return done.returncode, done.stdout or "", done.stderr or ""
    except FileNotFoundError:
        return 127, "", f"{args[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{args[0]} did not answer within {timeout}s"
    except OSError as exc:
        return 1, "", str(exc)


def unit_loaded(unit):
    """Whether the user manager knows this unit at all."""
    rc, out, _ = run_tool(["systemctl", "--user", "show", unit, "-p", "LoadState", "--value"])
    return rc == 0 and out.strip() == "loaded"


def hq_binary():
    return shutil.which("hq") or ""


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
            "forge": "github" if shutil.which("gh") else "unknown"}


def measured_features():
    """The features that have to ask the user manager. Only the refresher calls this: this
    route is open, so anyone who can reach the port could otherwise spend two process spawns
    per request, with no token and nothing to rate limit them."""
    return {"slice": unit_loaded(MODE.SLICE), "ci_daemon": unit_loaded(CI_DAEMON_UNIT)}


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
            "ci_daemon": bool(units.get("ci_daemon")),
            "forge": free["forge"],
        },
        "hq_agent": dash_hq_agent(),
        # True until the refresher's first pass: the two unit facts above are not known yet and
        # are reported as absent, which is the safe way round for a page deciding what to draw.
        "pending": not snapshot.get("tried"),
    }

# branch -> {"backend":"pass|fail|pend", ...}, filled by a 60s poller so the per-3s
# dashboard tick never hammers the GitHub API.
CI_CACHE = {}
_UNREADABLE_REPORTED = set()


_CI_REFRESH_TTL = 2.0
_ci_refresh_cache = {"at": 0.0, "value": None, "stamp": None}
_ci_refresh_lock = threading.Lock()



def _ci_state_stamp(payload):
    """What the observations actually depend on: which candidates exist, and their states."""
    if not isinstance(payload, dict):
        return None
    rows = []
    for bucket in ("running", "queued", "recent"):
        for item in payload.get(bucket) or []:
            if isinstance(item, dict):
                rows.append((bucket, item.get("id"), item.get("state")))
    return tuple(rows)


def _ci_refresher(interval=15.0):
    """Keep the observation snapshot warm off the request path.

    A failure here must leave the previous snapshot alone rather than blank the pane: "the forge is
    unreachable" and "there is nothing to show" look identical once the value is gone, and only one
    of them is true.
    """
    while True:
        try:
            refreshed = CI.read_state(refresh=True)
            if isinstance(refreshed, dict):
                stamp = _ci_state_stamp(refreshed)
                with _ci_refresh_lock:
                    _ci_refresh_cache["value"] = refreshed
                    _ci_refresh_cache["at"] = time.time()
                    _ci_refresh_cache["stamp"] = stamp
        except Exception:
            pass
        time.sleep(interval)


def start_ci_refresher():
    thread = threading.Thread(target=_ci_refresher, name="ci-refresher", daemon=True)
    thread.start()
    return thread

ACCOUNTS_REFRESH_SECONDS = 600  # owner's cadence: each refresh is one API call per account
_accounts_lock = threading.Lock()
_accounts_snapshot = {"at": None, "accounts": [], "errors": {}}


# What a card says when the reader cannot be told anything more useful than "it did not work".
ACCOUNT_TROUBLE_UNKNOWN = "The farm could not read this account's numbers."


def account_trouble(raw):
    """One sentence a person can act on, whatever the reader threw.

    What must never reach a card: an exception class, a traceback, a file path. "FileNotFoundError:
    [Errno 2] No such file or directory: '/private/tmp/...'" tells the reader nothing about what
    to do, and here there are only ever three things to do: log in once, log in again, or wait.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    low = text.lower()
    if "filenotfounderror" in low or "no such file" in low or "never read" in low:
        return ("This account has no login on the farm yet. Log in once: "
                f"ssh -t {CA.FARM_ALIAS} claude")
    if ("401" in low or "403" in low or "expired" in low
            or "unauthorized" in low or "forbidden" in low):
        return "The login on this account has expired. Log in again."
    if "429" in low or "rate-limited" in low or "rate limited" in low:
        return "The vendor asked the farm to slow down. These numbers refresh by themselves."
    if any(word in low for word in ("urlerror", "timeout", "timed out", "connection", "refused",
                                    "unreachable", "gaierror", "socket", "ssl", "http 5")):
        return "The vendor did not answer the last time the farm asked."
    return ACCOUNT_TROUBLE_UNKNOWN


def plain_account_trouble(rows, errors):
    """The same rows and errors, with every reason written for a person instead of for a log."""
    for row in rows:
        if row.get("stale_error"):
            row["stale_error"] = account_trouble(row["stale_error"])
    return rows, {name: account_trouble(text) for name, text in (errors or {}).items()}


def _accounts_refresher():
    """Keep the account-limit snapshot warm off the request path.

    A failure leaves the previous snapshot in place rather than blanking it: "Anthropic was
    unreachable" and "there are no accounts" look identical once the data is gone, and only one
    of them is true.
    """
    while True:
        try:
            summaries, errors = CA.collect()
            with _accounts_lock:
                previous = {row["name"]: row for row in _accounts_snapshot["accounts"]}
            rows = []
            for name in CA.account_dirs():
                if name in summaries:
                    s = summaries[name]
                    rows.append({"name": name, "label": CA.display(name),
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
                    err = errors.get(name, "unreadable")
                    exp = CA.token_expiry(CA.account_dirs().get(name, ""))
                    if "429" in err and exp is not None and exp <= time.time():
                        row["stale_error"] = "token expired"
                    else:
                        row["stale_error"] = err
                    rows.append(row)
                else:
                    rows.append({"name": name, "label": CA.display(name),
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
        time.sleep(ACCOUNTS_REFRESH_SECONDS)


def accounts_snapshot() -> dict:
    with _accounts_lock:
        return json.loads(json.dumps(_accounts_snapshot))


def ci_queue(refresh=True):
    """The local-CI queue written by Fleet's CI coordinator.

    The dashboard is also useful before that coordinator has ever run, so a
    missing file is a normal empty queue rather than an error.  Validate the
    stored payload before asking the coordinator for its refreshed view: if
    refresh is temporarily unavailable, the dashboard can still render the
    same last-known queue it rendered before freshness observations existed.
    """
    # A stale `updated` is only meaningful next to "is anything still writing this?". Without it
    # the pane ages silently and reads as live data that simply has not changed.
    def _daemon_alive():
        try:
            r = subprocess.run(["systemctl", "--user", "is-active", CI_DAEMON_UNIT],
                               capture_output=True, text=True, timeout=3)
            return r.stdout.strip() == "active"
        except Exception:
            return None

    empty = {"updated": None, "running": [], "queued": [], "recent": [],
             "daemon_alive": _daemon_alive()}
    try:
        with open(os.path.join(STATE, "ci", "queue.json")) as f:
            stored = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return empty
    if not isinstance(stored, dict):
        return empty

    def shaped(payload):
        return {
            "updated": payload.get("updated"),
            "running": (
                payload.get("running")
                if isinstance(payload.get("running"), list)
                else []
            ),
            "queued": (
                payload.get("queued")
                if isinstance(payload.get("queued"), list)
                else []
            ),
            "recent": (
                payload.get("recent")
                if isinstance(payload.get("recent"), list)
                else []
            ),
            # Without this the pane cannot tell "nothing has happened" from "nothing is writing
            # this any more", and a stale timestamp reads as live data.
            "daemon_alive": _daemon_alive(),
        }

    if not refresh:
        return shaped(stored)
    # Never block a draw on the forge. The refresher thread publishes here; until it has produced
    # anything we serve the stored queue, which is what the dashboard rendered before observations
    # existed at all.
    # A snapshot built from a different queue file is not a stale view of this one, it is an
    # answer about something else. Key it on the file it was built from.
    stamp = _ci_state_stamp(stored)
    with _ci_refresh_lock:
        snapshot = _ci_refresh_cache["value"]
        produced = _ci_refresh_cache["at"]
        if _ci_refresh_cache.get("stamp") != stamp:
            snapshot = None
    if snapshot is not None:
        view = shaped(snapshot)
        view["refresh_age"] = max(0, int(time.time() - produced))
        return view
    # Nothing published yet - the very first draw after a restart. Pay for one refresh inline so the
    # pane never opens on observations it does not have, then the thread owns it from here.
    try:
        refreshed = CI.read_state(refresh=True)
    except Exception:
        return shaped(stored)
    if not isinstance(refreshed, dict):
        return shaped(stored)
    with _ci_refresh_lock:
        _ci_refresh_cache["value"] = refreshed
        _ci_refresh_cache["at"] = time.time()
        _ci_refresh_cache["stamp"] = _ci_state_stamp(refreshed)
    return shaped(refreshed)
    # Several panes poll, and each stage-log open asks again; one refresh per couple of seconds is
    # as fresh as a human can perceive and keeps a busy run from serialising the whole dashboard.
    if not isinstance(refreshed, dict):
        return shaped(stored)
    return shaped(refreshed)


def ci_log_tail(candidate_id, tier_name):
    """Return a bounded log tail for one stage of one known CI record.

    Callers identify the record and stage, never a filesystem path. The path is
    taken from that stage's queue record and must still resolve beneath the
    record's canonical log directory; this also rejects a symlink escaping it.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", candidate_id or ""):
        return 400, {"error": "invalid CI run id"}
    if not tier_name:
        return 400, {"error": "CI stage is required"}

    state = ci_queue(refresh=False)
    record = next(
        (
            item
            for bucket in ("running", "queued", "recent")
            for item in state.get(bucket, [])
            if isinstance(item, dict)
            if item.get("id") == candidate_id
        ),
        None,
    )
    if record is None:
        return 404, {"error": "CI run not found"}
    tier = next(
        (
            item
            for item in (
                record.get("tiers", [])
                if isinstance(record.get("tiers"), list)
                else []
            )
            if isinstance(item, dict)
            if item.get("name") == tier_name
        ),
        None,
    )
    if tier is None:
        return 404, {"error": "CI stage not found"}

    response = {"id": candidate_id, "tier": tier_name}
    stored_path = tier.get("log")
    if not stored_path:
        return 200, {
            **response,
            "content": "",
            "missing": True,
            "message": "No action log was recorded for this stage.",
            "truncated": False,
        }

    run_root = os.path.realpath(
        os.path.join(STATE, "ci", "logs", candidate_id)
    )
    requested = os.path.expanduser(str(stored_path))
    if not os.path.isabs(requested):
        requested = os.path.join(run_root, requested)
    resolved = os.path.realpath(requested)
    try:
        inside_run = os.path.commonpath([run_root, resolved]) == run_root
    except ValueError:
        inside_run = False
    if not inside_run:
        return 403, {"error": "CI log path is outside this run's log directory"}
    if not os.path.isfile(resolved):
        return 200, {
            **response,
            "content": "",
            "missing": True,
            "message": "The action log is not available yet.",
            "truncated": False,
        }

    try:
        size = os.path.getsize(resolved)
        start = max(0, size - CI_LOG_TAIL_BYTES)
        with open(resolved, "rb") as handle:
            handle.seek(start)
            content = handle.read(CI_LOG_TAIL_BYTES).decode(
                "utf-8", errors="replace"
            )
    except OSError:
        return 500, {"error": "The action log could not be read."}
    return 200, {
        **response,
        "content": content,
        "missing": False,
        "truncated": start > 0,
    }


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
        # manager is the CPU cap behind the power modes, the CI daemon, the sweep timer and
        # the dashboard's own unit.
        return "off", ("no user manager here, so the power modes, the CI daemon and the sweep "
                       "timer are unavailable; lanes themselves run in tmux and are fine"), \
            "run this farm on a machine with a systemd user manager to get those"
    if word in ("running", "degraded", "starting", "maintenance"):
        return "ok", f"user manager is {word}", ""
    return "error", word or "the user manager did not answer", \
        "start it: `systemctl --user daemon-reload`, and check `loginctl show-user $USER`"


def _check_linger():
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
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


def _check_ci_daemon():
    rc, out, err = run_tool(["systemctl", "--user", "is-active", CI_DAEMON_UNIT])
    answer = (out or "").strip()
    if answer == "active":
        return "ok", "verifying candidates before merge", ""
    if rc == 127:
        return "off", "no user manager here, so there is no CI daemon to run", \
            "run this farm on a machine with a systemd user manager"
    if answer in ("inactive", "failed", "unknown", "activating", "deactivating", ""):
        detail = ("the queue is not being worked" if answer != "failed"
                  else "the unit failed; the queue is not being worked")
        return "off", detail, "fleet ci daemon start"
    return "error", (err or answer).strip()[:200], "fleet ci daemon start"


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
    ("ci_daemon", "farm CI daemon", _check_ci_daemon),
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
            # eleven rows, and never a traceback on a page.
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


def add_project(body):
    """(status, payload) for POST /api/projects. Registering is `fleet add-project`'s job,
    never a second writer of the same file: a page that edited projects.toml itself would be a
    second implementation of the one thing that knows how to refuse a duplicate."""
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
    if port_base not in (None, ""):
        try:
            port_base = int(port_base)
        except (TypeError, ValueError):
            return 400, {"error": "port_base must be a whole number"}
        if not PORT_BASE_MIN <= port_base <= PORT_BASE_MAX:
            return 400, {"error": f"port_base must be between {PORT_BASE_MIN} and "
                                  f"{PORT_BASE_MAX}"}
        args += ["--port-base", str(port_base)]
    rc, out, err = run_tool(args, timeout=PROJECT_ADD_TIMEOUT)
    if rc != 0:
        lines = [line for line in ((err or "") + "\n" + (out or "")).splitlines() if line.strip()]
        return 400, {"error": (lines[-1].strip() if lines else
                               f"fleet add-project exited {rc}")[:400]}
    row = next((item for item in projects() if item["name"] == name), None)
    if row is None:
        return 400, {"error": f"fleet add-project reported success but '{name}' is not in the "
                              "registry"}
    return 200, row


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
    rows = _gh_json(["issue", "list", "--repo", office, "--state", "all", "--label", "inbox",
                     "--limit", "100", "--json", "number,title,updatedAt"])
    boxes = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "")
        boxes.append({"name": title.removeprefix("inbox: ").strip() or title,
                      "number": row.get("number"),
                      "updated_at": row.get("updatedAt")})
    return boxes


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


def mail_refresh():
    """One pass over the office. Called by the refresher thread, and once inline before the
    first answer, never on every request."""
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
    try:
        boxes = mail_fetch_boxes(office)
    except Exception as exc:
        with _snapshot_lock:
            _snapshot_failed(_mail_snapshot, str(exc)[:200])
        return
    threads, fresh_seen, error = {}, {}, None
    for box in boxes:
        name = box["name"]
        stamp = box.get("updated_at")
        if name in previous and stamp is not None and seen.get(name) == stamp:
            # Nothing has been written to this box since the last pass. Fetching it again would
            # spend the shared API budget to learn that.
            threads[name] = previous[name]
            fresh_seen[name] = stamp
            continue
        try:
            threads[name] = mail_fetch_thread(office, box["number"], since)
            fresh_seen[name] = stamp
        except Exception as exc:
            threads[name] = previous.get(name, [])
            error = str(exc)[:200]
    cutoff = parse_iso(since)
    for box in boxes:
        messages = threads.get(box["name"]) or []
        recent = [message for message in messages
                  if (parse_iso(message.get("created_at")) or cutoff) >= cutoff]
        box["count_24h"] = len(recent)
        # One clock. A sender's own stamp in the body is for display; a box's last activity is
        # the forge's `created_at`, which is the clock its `updated_at` is on too.
        box["last_at"] = (messages[-1]["created_at"] if messages else box.get("updated_at"))
    if error:
        with _snapshot_lock:
            _mail_snapshot["boxes"] = boxes
            _mail_snapshot["threads"] = threads
            _mail_snapshot["seen"] = fresh_seen
            _snapshot_failed(_mail_snapshot, error)
        return
    with _snapshot_lock:
        _snapshot_succeeded(_mail_snapshot,
                            {"boxes": boxes, "threads": threads, "seen": fresh_seen})


def _refresh_once():
    """One pass over everything a read route serves. Each part is on its own: a head office
    that is down must not cost the page its health table."""
    for refresh in (config_refresh, health_refresh, mail_refresh, who_refresh, feed_refresh):
        try:
            refresh()
        except Exception:
            pass


def _refresher(interval=REFRESH_SECONDS):
    while True:
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
# `hq feed` fetches the claims branch and makes several forge calls, so it is slower than a
# single read and, far more to the point, it writes to disk. It belongs on the thread.
MAIL_FEED_TIMEOUT = 60


def _first_line(text, fallback):
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[0].strip()[:200] if lines else fallback


FEED_STAMP = "%d %b %H:%M"


def feed_iso(label, now=None):
    """hq prints a feed line's time as a local label with no year and no zone, which cannot be
    sorted against the stamps every other answer here carries. Rebuild it as UTC: this year in
    this machine's zone, or last year when that would put the event in the future. The month
    name is read in the locale hq wrote it in, which is this machine's."""
    try:
        parsed = time.strptime(label, FEED_STAMP)
    except (TypeError, ValueError):
        return None
    now = time.time() if now is None else now

    def stamp_for(year):
        # mktime with tm_isdst = -1 asks the system which side of a daylight change this is.
        return time.mktime((year, parsed.tm_mon, parsed.tm_mday, parsed.tm_hour,
                            parsed.tm_min, 0, 0, 1, -1))

    stamp = stamp_for(time.localtime(now).tm_year)
    if stamp > now + 86400:
        stamp = stamp_for(time.localtime(now).tm_year - 1)
    return _iso(stamp)


def _parse_feed(out, now=None):
    events = []
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        match = FEED_LINE.match(line)
        if match:
            label = match.group("at").strip()
            events.append({"at": feed_iso(label, now), "at_label": label,
                           "kind": match.group("kind"), "text": match.group("text").strip()})
        else:
            # "office quiet for the last 24h" and anything else hq chooses to say.
            events.append({"at": None, "at_label": None, "kind": "note", "text": line.strip()})
    return events


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
        else:
            _snapshot_succeeded(_who_snapshot, {"sessions": _parse_who(out)})


def feed_refresh():
    if mail_unavailable():
        return
    with _snapshot_lock:
        windows = list(_feed_windows)
    for window in windows:
        rc, out, err = run_tool([hq_binary(), "feed", "--hours", _feed_key(window)],
                                timeout=MAIL_FEED_TIMEOUT)
        with _snapshot_lock:
            entry = _feed_snapshots.setdefault(
                _feed_key(window), _blank_snapshot(events=[], hours=window))
            if rc != 0:
                _snapshot_failed(entry, _first_line(err or out, f"hq feed exited {rc}"))
            else:
                _snapshot_succeeded(entry, {"events": _parse_feed(out), "hours": window})


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
    return 200, {"ok": True, "to": target, "from": agent, "detail": (out or "").strip()[:200]}



def sweep_status():
    """State of the autosweep systemd --user timer, for the header countdown. Uses the
    MONOTONIC next-elapse (OnUnitActiveSec is monotonic) and the same clock in Python, so
    'seconds until the next sweep' needs no wall-clock/date parsing."""
    def props(unit, *names):
        try:
            args = ["systemctl", "--user", "show", unit]
            for n in names:
                args += ["-p", n]
            r = subprocess.run(args, capture_output=True, text=True, timeout=5)
            d = {}
            for line in r.stdout.splitlines():
                k, _, v = line.partition("=")
                d[k] = v
            return d
        except Exception:
            return {}

    def dur(s):
        # systemd prints a monotonic USec property as a duration since boot, e.g.
        # "19h 41min 40.045077s": not raw microseconds. Parse it to seconds.
        total = 0.0
        for num, u in re.findall(r"([\d.]+)(us|ms|min|h|d|s)", s or ""):
            total += {"us": 1e-6, "ms": 1e-3, "s": 1, "min": 60, "h": 3600, "d": 86400}[u] * float(num)
        return total

    t = props(SWEEP_TIMER_UNIT, "UnitFileState", "NextElapseUSecMonotonic")
    enabled = t.get("UnitFileState") in ("enabled", "enabled-runtime")
    secs = None
    if enabled:
        nxt = dur(t.get("NextElapseUSecMonotonic"))     # next fire, as monotonic seconds
        if nxt > 0:
            secs = max(0.0, nxt - time.clock_gettime(time.CLOCK_MONOTONIC))
    return {"enabled": enabled, "secs_left": secs,
            "result": (props(SWEEP_TIMER_UNIT.replace(".timer", ".service"),
                             "Result").get("Result") or None)}


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
            if path.startswith("/static/"):
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
                try:
                    v = str(int(os.path.getmtime(INDEX)))
                except Exception:
                    v = "0"
                self._send(200, json.dumps({"v": v}))
            elif path.startswith("/api/identities"):
                # one code name -> one mark; the card reads its emoji/colour from here,
                # not from the per-agent field, so an initiator is never scattered.
                self._send(200, json.dumps(ID.load()))
            # Keep the exact CI route above the prefix-matched mode/model routes. A
            # prior /api/models vs /api/mode collision proved route order observable.
            elif path == "/api/ci/log":
                query = parse_qs(urlparse(self.path).query)
                code, payload = ci_log_tail(
                    query.get("id", [""])[0],
                    query.get("tier", [""])[0],
                )
                self._send(code, json.dumps(payload))
            elif path == "/api/ci":
                self._send(200, json.dumps(ci_queue()))
            elif path.startswith("/api/accounts"):
                self._send(200, json.dumps(accounts_snapshot()))
            elif path.startswith("/api/models"):
                self._send(200, json.dumps(MODELS.listing()))
            elif path.startswith("/api/mode"):
                self._send(200, json.dumps(MODE.status()))
            elif path == "/api/projects":
                self._send(200, json.dumps(projects()))
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
                self._send(200, json.dumps(sweep_status()))
            elif path.startswith("/api/metrics"):
                self._send(200, json.dumps(M.collect()))
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
            if path == "/api/projects":
                code, payload = add_project(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/mail/send":
                code, payload = mail_send(body)
                self._send(code, json.dumps(payload))
            elif path == "/api/agent/msg":
                code, payload = agent_msg(body)
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
        print(f"fleet dashboard: {method} {self.path} failed: {type(exc).__name__}: {exc}",
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
    TOKEN = ensure_token()
    reach = "this machine only" if bind_is_loopback() else f"anything that can reach {BIND}"
    print(f"fleet dashboard on {BIND}:{PORT} ({reach})", flush=True)
    if TOKEN:
        print("  writing needs the bearer token; read it with: fleet dashboard token", flush=True)
        if not bind_is_loopback():
            print("  bound wide, so reading needs it too", flush=True)
    else:
        print("  READ-ONLY: no write token could be stored; set FLEET_DASH_TOKEN", flush=True)
    threading.Thread(target=_mode_loop, daemon=True).start()
    threading.Thread(target=_ci_loop, daemon=True).start()
    threading.Thread(target=_accounts_refresher, name="accounts-refresher", daemon=True).start()
    start_refresher()
    Server((BIND, PORT), Handler).serve_forever()
