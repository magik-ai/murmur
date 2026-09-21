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
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
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
            r = subprocess.run(["systemctl", "--user", "is-active", "fleet-ci.service"],
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


def agents():
    out = []
    for fp in sorted(glob.glob(os.path.join(STATE, "state", "*.json"))):
        s = _read_agent_record(fp)
        if s is None:
            continue
        if s.get("status") == "state_unreadable":
            out.append(s)
            continue
        br = s.get("branch") or ""
        if s.get("pr_url") and br in CI_CACHE:
            s["ci"] = CI_CACHE[br]
        if _is_phantom(s):
            continue
        out.append(s)
    return out


def agent_detail(slug):
    """One agent's full record for the detail modal. The state file keeps task/result
    truncated (to stay small and light in the list); the FULL text lives in the agent's
    log files, so read those here — this works for agents spawned before this endpoint too."""
    if not slug or not re.fullmatch(r"[A-Za-z0-9._-]+", slug):
        return {"error": "bad slug"}
    path = os.path.join(STATE, "state", slug + ".json")
    s = _read_agent_record(path)
    if s is None:
        return {"error": "not found"}
    if s.get("status") == "state_unreadable":
        return s
    br = s.get("branch") or ""
    if s.get("pr_url") and br in CI_CACHE:
        s["ci"] = CI_CACHE[br]
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
        # "19h 41min 40.045077s" — not raw microseconds. Parse it to seconds.
        total = 0.0
        for num, u in re.findall(r"([\d.]+)(us|ms|min|h|d|s)", s or ""):
            total += {"us": 1e-6, "ms": 1e-3, "s": 1, "min": 60, "h": 3600, "d": 86400}[u] * float(num)
        return total

    t = props("fleet-sweep.timer", "UnitFileState", "NextElapseUSecMonotonic")
    enabled = t.get("UnitFileState") in ("enabled", "enabled-runtime")
    secs = None
    if enabled:
        nxt = dur(t.get("NextElapseUSecMonotonic"))     # next fire, as monotonic seconds
        if nxt > 0:
            secs = max(0.0, nxt - time.clock_gettime(time.CLOCK_MONOTONIC))
    return {"enabled": enabled, "secs_left": secs,
            "result": (props("fleet-sweep.service", "Result").get("Result") or None)}


def _ci_parse(rollup):
    """A PR's statusCheckRollup -> {backend/frontend/docker: pass|fail|pend}. Matches the
    three required CI jobs by name; anything not yet concluded reads as pending."""
    out = {}
    for c in rollup or []:
        name = (c.get("name") or c.get("context") or "").lower()
        concl = (c.get("conclusion") or "").upper()
        state = (c.get("state") or "").upper()          # StatusContext (non-Actions checks)
        for job in ("backend", "frontend", "docker"):
            if job in name:
                if concl == "SUCCESS" or state == "SUCCESS":
                    out[job] = "pass"
                elif concl in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED",
                               "STARTUP_FAILURE") or state in ("FAILURE", "ERROR"):
                    out[job] = "fail"
                else:
                    out[job] = "pend"
    return out


def _ci_refresh():
    """Poll GitHub once per PR for its check states — every 60s, not every tick."""
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
            fresh[br] = _ci_parse(json.loads(r.stdout or "{}").get("statusCheckRollup"))
        except Exception:
            fresh[br] = CI_CACHE.get(br, {})            # keep last-known on a transient error
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

    # The shell and the two routes that only describe access: served without a token, on any
    # bind, or a wide-bound dashboard could not be opened at all (the token arrives in the URL of
    # this very page). They expose no lane data.
    OPEN_PATHS = ("/", "/index.html", "/api/access", "/api/version")

    def _query_token(self):
        return parse_qs(urlparse(self.path).query).get("token", [""])[0]

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path not in self.OPEN_PATHS:
                readable, why = may_read(self.headers, self._query_token())
                if not readable:
                    self._send(403, json.dumps({"error": why}))
                    return
            if path.startswith("/api/access"):
                # The page asks this on load so it can grey out what it cannot do, instead of
                # letting a click fail with a 403 the user never sees.
                writable, why = may_mutate(self.headers, self._query_token())
                self._send(200, json.dumps({"writable": writable, "reason": why,
                                            "token_required": True,
                                            "loopback": bind_is_loopback()}))
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
            elif path.startswith("/api/sweep"):
                self._send(200, json.dumps(sweep_status()))
            elif path.startswith("/api/metrics"):
                self._send(200, json.dumps(M.collect()))
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

    def do_POST(self):
        try:
            writable, why = may_mutate(self.headers, self._query_token())
            if not writable:
                self._send(403, json.dumps({"error": why}))
                return
            if self.path.startswith("/api/models"):
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
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
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                try:
                    MODE.set_setting(body.get("mode", ""))
                except ValueError as e:
                    self._send(400, json.dumps({"error": str(e)}))
                    return
                self._send(200, json.dumps(MODE.tick(force=True)))  # apply now
            elif self.path.startswith("/api/accounts/add"):
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                engine = (body.get("engine") or "claude").strip()
                if engine == "codex":
                    # codex is a single shared account (~/.codex, Team plan) — no dir-per-name; this
                    # just re-logs it in through the SSH-tunnelled OAuth callback.
                    self._send(200, json.dumps({
                        "name": "codex", "engine": "codex",
                        "command": ("ssh -L 1455:localhost:1455 -t %s codex login"
                                    % CA.FARM_ALIAS),
                        "steps": ["codex is one shared account — this RE-LOGS it in (not a new account)",
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
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
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
    Server((BIND, PORT), Handler).serve_forever()
