#!/usr/bin/env python3
"""Serve the real dashboard against fixtures, in each of the four states a panel can be in.

The page under test is the one next to this file: a hardcoded checkout path silently serves a
DIFFERENT tree than the worktree you are testing, which is exactly how a green reading gets
produced for code nobody ran.

The state is picked, in order, from the `state` query parameter, from the `state` parameter of
the page that made the request, and from STUB_STATE. So a browser opened on
`http://127.0.0.1:PORT/?state=empty` sees the empty dataset everywhere without the page
knowing anything about this file.

    ready    a farm with agents, a queue, mail, accounts and a healthy machine
    empty    a farm that has just been installed: nothing registered, nothing run
    error    gh missing, hq missing, no graphics card, and a queue that will not answer
    loading  every route answers slowly, so the skeletons are what you see
    quiet    a busy farm whose queue has only finished runs, whose lane names are too long
             for a card, and whose office holds two inbox issues under one name
"""
import http.server
import json
import os
import pathlib
import socketserver
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "index.html"
STATIC = HERE / "static"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7901
LOADING_DELAY = float(os.environ.get("STUB_LOADING_DELAY", "60"))
NOW = time.time()

STATES = ("ready", "empty", "error", "loading", "quiet")

# Routes served from a background snapshot. In the loading state they answer at once and say
# the first pass has not happened, which is a different thing from a slow request.
SNAPSHOT_ROUTES = ("/api/config", "/api/health", "/api/mail/")


def ago(seconds):
    return NOW - seconds


def iso(when=None):
    """Times in a snapshot envelope are ISO 8601 in UTC, so no reader has to guess a unit."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW if when is None else when))

# --------------------------------------------------------------------- fixtures

IDENTITIES = {
    "winston": {"icon": "\U0001f98a", "color": "#5b8def"},
    "rubicon": {"icon": "\U0001f989", "color": "#3fb950"},
    "dali": {"icon": "\U0001f419", "color": "#d29922"},
    "euler": {"icon": "\U0001f422", "color": "#a371f7"},
}

AGENTS = [
    {
        "slug": "demo-api-3f2a", "project": "demo", "lane": "api", "engine": "claude",
        "model": "opus", "effort": "high", "status": "running", "outcome": "unknown",
        "started_at": ago(2400), "updated_at": ago(40), "spawned_by": "winston",
        "branch": "demo/api-pagination", "cost_usd": 1.82, "tokens_in": 184000,
        "tokens_out": 24500,
        "task": "Add pagination to the catalogue endpoint and cover it with a service test.",
    },
    {
        "slug": "demo-web-91bd", "project": "demo", "lane": "web", "engine": "claude",
        "model": "sonnet", "status": "pr_open", "outcome": "met",
        "started_at": ago(9400), "updated_at": ago(900), "spawned_by": "winston",
        "branch": "demo/web-empty-states", "pr_url": "https://example.invalid/demo/pull/412",
        "cost_usd": 3.4, "tokens_in": 402000, "tokens_out": 61000,
        "ci": {"unit tests": "pass", "typecheck": "pass", "container image": "pend",
               "end to end": "fail", "docs": "pass", "licence scan": "pass"},
        "task": "Give every panel on the orders screen an empty state and a loading state.",
    },
    {
        "slug": "storefront-checkout-77c1", "project": "storefront", "lane": "checkout",
        "engine": "codex", "effort": "xhigh", "status": "failed", "outcome": "unmet",
        "started_at": ago(18000), "updated_at": ago(5400), "spawned_by": "rubicon",
        "branch": "storefront/checkout-retry", "cost_usd": 0.94, "tokens_in": 96000,
        "tokens_out": 8100,
        "scope": {"delivered": [1841], "dropped": [1842, 1843]},
        "task": "Retry a failed card charge once, then hand the customer a plain explanation.",
    },
    {
        "slug": "storefront-search-04ef", "project": "storefront", "lane": "search",
        "engine": "claude", "model": "sonnet", "status": "done", "outcome": "met",
        "started_at": ago(26000), "updated_at": ago(7200), "spawned_by": "dali",
        "branch": "storefront/search-typos", "pr_url": "https://example.invalid/storefront/pull/88",
        "cost_usd": 2.1, "tokens_in": 233000, "tokens_out": 30200,
        "ci": {"unit tests": "pass", "typecheck": "pass", "container image": "pass"},
        "task": "Forgive one typo in a product search without slowing the query down.",
    },
    {
        "slug": "demo-docs-5a10", "project": "demo", "lane": "docs", "engine": "claude",
        "model": "haiku", "status": "done_no_pr", "outcome": "unknown",
        "started_at": ago(4000), "updated_at": ago(600), "spawned_by": "euler",
        "cost_usd": 0.22, "tokens_in": 41000, "tokens_out": 5200,
        "task": "Write the page that explains how a reader installs this on their own machine.",
    },
    {
        "slug": "demo-sweep-1a77", "project": "demo", "lane": "sweep", "engine": "claude",
        "status": "state_unreadable", "outcome": "unknown", "started_at": ago(60000),
        "updated_at": ago(60000), "spawned_by": "winston",
        "state_error": "the state record could not be read twice in a row",
    },
]

# Real farms name a lane after the ticket and the branch, which is far wider than a card. The
# name is the part that may be cut; the word in the status pill is not.
LONG_AGENTS = [
    {
        "slug": "storefront-checkout-retry-a-declined-card-once-then-explain-7c41",
        "project": "storefront", "lane": "checkout-retry-a-declined-card-once-then-explain",
        "engine": "claude", "model": "opus", "status": "done", "outcome": "met",
        "started_at": ago(88000), "updated_at": ago(30000), "spawned_by": "winston",
        "branch": "storefront/checkout-retry-a-declined-card-once-then-explain",
        "cost_usd": 5.12, "tokens_in": 512000, "tokens_out": 71000,
        "task": "Retry a declined card once, then explain the refusal in the customer's own words.",
    },
    {
        "slug": "demo-catalogue-pagination-and-the-empty-search-result-4b19",
        "project": "demo", "lane": "catalogue-pagination-and-the-empty-search-result",
        "engine": "codex", "effort": "xhigh", "status": "failed", "outcome": "unmet",
        "started_at": ago(70000), "updated_at": ago(26000), "spawned_by": "rubicon",
        "branch": "demo/catalogue-pagination-and-the-empty-search-result",
        "cost_usd": 1.44, "tokens_in": 132000, "tokens_out": 9900,
        "task": "Page the catalogue, and say something useful when a search finds nothing.",
    },
    {
        "slug": "demo-workspace-sticky-after-publish-and-the-avatar-bundle-1f90",
        "project": "demo", "lane": "workspace-sticky-after-publish-and-the-avatar-bundle",
        "engine": "claude", "model": "sonnet", "status": "pr_open", "outcome": "unknown",
        "started_at": ago(64000), "updated_at": ago(3400), "spawned_by": "dali",
        "branch": "demo/workspace-sticky-after-publish-and-the-avatar-bundle",
        "pr_url": "https://example.invalid/demo/pull/515",
        "cost_usd": 3.02, "tokens_in": 288000, "tokens_out": 40100,
        "task": "Keep the reader in the workspace they published from, and bake the avatar after.",
    },
]

RESULTS = {
    "demo-web-91bd": "Every panel now has the four states. The end to end check is red on one "
                     "case that was already red on the base branch.",
    "storefront-search-04ef": "Search forgives one typo. Measured on the sample catalogue: "
                              "no change in query time worth reporting.",
}

PROJECTS = [
    {"name": "demo", "repo": "your-org/demo", "path": "/home/farm/work/demo",
     "base_branch": "main", "ports": {"web": 5200, "api": 5201, "e2e": 5202},
     "lanes_open": 3, "last_activity": ago(40)},
    {"name": "storefront", "repo": "your-org/storefront", "path": "/home/farm/work/storefront",
     "base_branch": "main", "ports": {"web": 5210, "api": 5211, "e2e": 5212},
     "lanes_open": 2, "last_activity": ago(5400)},
]

QUEUE_STATES = ["passed", "passed_partial", "failed", "conflict", "ejected", "cancelled", "blocked"]


def queue_record(index, state, kind):
    started = ago(3600 - index * 120)
    return {
        "id": f"ci-{1000 + index}-0000", "project": "demo" if index % 2 else "storefront",
        "repo": "your-org/demo", "pr": 400 + index, "branch": f"demo/change-{index}",
        "state": state, "reason": {
            "passed_partial": "verified with the hosted browser check left out",
            "conflict": "the change no longer applies to the current main branch",
            "blocked": "waiting for a person to release the hold",
        }.get(state, ""),
        "started": started, "ended": None if kind == "running" else started + 700,
        "position": index + 1 if kind == "queued" else None,
        "tiers": [
            {"name": "changed files", "state": "passed", "started": started, "ended": started + 4},
            {"name": "unit tests", "state": "passed", "started": started + 4, "ended": started + 300},
            {"name": "end to end", "state": "running" if kind == "running" else state,
             "started": started + 300, "ended": None if kind == "running" else started + 700,
             "detail": "" if state != "failed" else "one case failed on the orders screen"},
        ],
        "uncovered": ["hosted browser check"] if state == "passed_partial" else [],
    }


QUEUE = {
    "updated": NOW, "daemon_alive": True, "refresh_age": 4,
    "running": [queue_record(0, "running", "running")],
    "queued": [queue_record(1, "queued", "queued"), queue_record(2, "queued", "queued")],
    "recent": [queue_record(index + 3, state, "recent") for index, state in enumerate(QUEUE_STATES)],
}

ACCOUNTS = {
    "at": NOW,
    "accounts": [
        {"name": "farm-one", "label": "farm one", "engine": "claude", "session": 42,
         "weekly": 71, "session_resets": NOW + 5400, "weekly_resets": NOW + 300000,
         "read_at": NOW, "scoped": [{"label": "long context", "percent": 12, "active": True,
                                     "resets": NOW + 5400}]},
        {"name": "farm-two", "label": "farm two", "engine": "codex", "session": 96,
         "weekly": 88, "session_resets": NOW + 900, "weekly_resets": NOW + 120000,
         "read_at": ago(900), "scoped": [], "stale_error": "the vendor answered 429"},
    ],
    "errors": {},
}

MODELS = [
    {"id": "claude", "label": "Claude", "glyph": "C", "color": "#d29922", "enabled": True,
     "role": "builds the change", "models": "opus, sonnet, haiku", "health": "ok",
     "limits": "two windows, session and weekly"},
    {"id": "codex", "label": "Codex", "glyph": "X", "color": "#3fb950", "enabled": True,
     "role": "reviews the change", "models": "gpt-5-codex", "health": "fail",
     "health_detail": "the last health call timed out", "limits": "five hour window"},
    {"id": "local", "label": "Local model", "enabled": False, "role": "offline experiments",
     "health": "unchecked"},
]

MAIL_BOXES = [
    {"name": "all", "number": 1, "updated_at": ago(600), "count_24h": 9, "last_at": ago(600)},
    {"name": "winston", "number": 12, "updated_at": ago(900), "count_24h": 4, "last_at": ago(900)},
    {"name": "rubicon", "number": 13, "updated_at": ago(4200), "count_24h": 2, "last_at": ago(4200)},
    {"name": "dali", "number": 14, "updated_at": ago(20000), "count_24h": 1, "last_at": ago(20000)},
]

# One office, two inbox issues under one name. It happens when a name is registered twice, and
# the page used to show that name twice with half its thread in each row.
MAIL_BOXES_DOUBLED = MAIL_BOXES + [
    {"name": "winston", "number": 4, "updated_at": ago(50000), "count_24h": 1, "last_at": ago(50000)},
]


def message(sender, seconds_ago, text):
    """A message carries the time twice: as the office wrote it, and as a number to count from."""
    return {"sender": sender, "at": f"{seconds_ago // 60}m ago" if seconds_ago < 3600
            else f"{seconds_ago // 3600}h ago", "created_at": ago(seconds_ago),
            "text": text}


MAIL_THREADS = {
    "all": [
        message("winston", 7200, "The orders screen is claimed on demo/web-empty-states. Nobody else touch it."),
        message("rubicon", 3600, "Checkout retry is red on the base branch too. I am not chasing it tonight."),
        message("dali", 600, "Search typo tolerance is merged. The catalogue query time did not move."),
    ],
    "winston": [
        message("dashboard", 5400, "Your lane has a change open, checks are still running."),
        message("winston", 900, "Seen. I will wait for the container image check."),
    ],
    "rubicon": [
        message("rubicon", 4200, "Taking the checkout lane until it merges."),
    ],
    "dali": [
        message("dali", 20000, "Handing the search lane back, it is done."),
    ],
}

def event(seconds_ago, kind, text, label=None):
    """An event carries the office's own words for when it happened, and the time behind them."""
    return {"at": iso(ago(seconds_ago)), "at_label": label, "kind": kind, "text": text}


MAIL_FEED = [
    event(20000, "session", "dali said hello and took the search lane", "5h ago"),
    event(7200, "claim", "winston claimed demo/web-empty-states", "2h ago"),
    event(4200, "claim", "rubicon claimed storefront/checkout-retry"),
    event(1800, "note", "the office snapshot was refreshed"),
    event(600, "mail", "dali to all: search typo tolerance is merged", "10m ago"),
]

MAIL_WHO = [
    {"name": "winston", "state": "live", "age_hours": 2.6, "since": None,
     "task": "finishing the empty states on the orders screen"},
    {"name": "rubicon", "state": "stale", "age_hours": 5.0, "since": None,
     "task": "checkout retry"},
]

HEALTH_READY = [
    {"id": "gh", "label": "gh", "state": "ok", "detail": "version 2.61.0", "fix": ""},
    {"id": "tmux", "label": "tmux", "state": "ok", "detail": "version 3.4", "fix": ""},
    {"id": "systemd_user", "label": "systemd user manager", "state": "ok", "detail": "running", "fix": ""},
    {"id": "linger", "label": "linger", "state": "ok", "detail": "on for this user", "fix": ""},
    {"id": "hq", "label": "hq", "state": "ok", "detail": "head office reachable", "fix": ""},
    {"id": "claude", "label": "claude", "state": "ok", "detail": "on the path", "fix": ""},
    {"id": "codex", "label": "codex", "state": "off", "detail": "switched off in the policy file", "fix": ""},
    {"id": "gpu_sensor", "label": "nvidia-smi", "state": "ok", "detail": "one card reporting", "fix": ""},
    {"id": "cpu_temp_sensor", "label": "temperature sensor", "state": "ok", "detail": "reading from the package sensor", "fix": ""},
    {"id": "ci_daemon", "label": "queue runner", "state": "ok", "detail": "running", "fix": ""},
    {"id": "sweep_timer", "label": "sweep timer", "state": "ok", "detail": "next run in nine minutes", "fix": ""},
    {"id": "office", "label": "head office", "state": "ok", "detail": "answered in 240 ms", "fix": ""},
]

HEALTH_ERROR = [
    {"id": "gh", "label": "gh", "state": "missing", "detail": "gh is not installed, so checks on a change cannot be read.",
     "fix": "sudo apt install gh"},
    {"id": "tmux", "label": "tmux", "state": "ok", "detail": "version 3.4", "fix": ""},
    {"id": "systemd_user", "label": "systemd user manager", "state": "ok", "detail": "running", "fix": ""},
    {"id": "linger", "label": "linger", "state": "missing",
     "detail": "Agents stop when you log out, because linger is off.", "fix": "loginctl enable-linger $USER"},
    {"id": "hq", "label": "hq", "state": "missing", "detail": "No head office is configured, so there is no mail.",
     "fix": "hq init --repo <owner>/<office>"},
    {"id": "claude", "label": "claude", "state": "ok", "detail": "on the path", "fix": ""},
    {"id": "codex", "label": "codex", "state": "off", "detail": "switched off in the policy file", "fix": ""},
    {"id": "gpu_sensor", "label": "nvidia-smi", "state": "missing",
     "detail": "No graphics card sensor, so power mode has no signal and stays on full.",
     "fix": "set FLEET_NVIDIA_SMI to the path of nvidia-smi"},
    {"id": "cpu_temp_sensor", "label": "temperature sensor", "state": "error",
     "detail": "The sensor package is installed but returned nothing.", "fix": "sudo sensors-detect"},
    {"id": "ci_daemon", "label": "queue runner", "state": "error", "detail": "The runner is not answering.",
     "fix": "fleet daemon start"},
    {"id": "sweep_timer", "label": "sweep timer", "state": "off", "detail": "not enabled on this machine",
     "fix": "fleet autosweep --enable"},
    {"id": "office", "label": "head office", "state": "missing", "detail": "no office to reach",
     "fix": "hq init --repo <owner>/<office>"},
]

HEALTH_EMPTY = [dict(check) for check in HEALTH_READY]

METRICS_READY = {
    "ts": NOW, "agents": 4, "can_spawn": True, "level": "ok", "reasons": [],
    "block_reasons": [], "warnings": [],
    "load": {"load1": 3.4, "load5": 4.1, "load15": 3.9, "cores": 14},
    "mem": {"ram_total_gb": 64.0, "ram_avail_gb": 28.4, "ram_used_gb": 35.6,
            "swap_total_gb": 8.0, "swap_used_gb": 0.2, "swap_churn_kbps": 0},
    "disk": {"path": "/", "total_gb": 1000.0, "used_gb": 612.0, "free_gb": 388.0},
    "gpu": {"name": "generic card", "temp_c": 54, "util_pct": 22, "mem_used_mb": 3100, "mem_total_mb": 16000},
    "cpu_temp_c": 48, "cpu_temp_source": "package sensor", "sensors_unavailable": False,
}

METRICS_ERROR = {
    "ts": NOW, "agents": 0, "can_spawn": False, "level": "block",
    "reasons": ["free memory is under the floor"],
    "block_reasons": ["free memory is under the floor"],
    "warnings": ["the disk is nearly full"],
    "load": {"load1": 12.8, "load5": 11.2, "load15": 9.7, "cores": 14},
    "mem": {"ram_total_gb": 64.0, "ram_avail_gb": 1.2, "ram_used_gb": 62.8,
            "swap_total_gb": 8.0, "swap_used_gb": 6.4, "swap_churn_kbps": 900},
    "disk": {"path": "/", "total_gb": 1000.0, "used_gb": 968.0, "free_gb": 32.0},
    "gpu": None, "cpu_temp_c": None, "cpu_temp_source": None, "sensors_unavailable": True,
}

METRICS_EMPTY = dict(METRICS_READY, agents=0)

MAIL_UNAVAILABLE = {
    "unavailable": "No head office is configured, so there is no mail to show.",
    "fix": "hq init --repo <owner>/<office>",
}

LOG_LINES = [f"[{time.strftime('%H:%M:%S', time.localtime(ago(1200 - index * 6)))}] "
             f"step {index + 1}: reading the files this change touches"
             for index in range(200)]

# Written by the POST routes, so the browser check can prove a form does something.
SENT = {"messages": [], "mail": [], "projects": []}


# ------------------------------------------------------------------- the server

def config_for(state):
    features = {"hq": True, "slice": True, "gpu": True, "cpu_temp": True,
                "ci_daemon": True, "forge": True}
    if state == "error":
        features.update({"hq": False, "gpu": False, "cpu_temp": True})
    return {"title": "murmur", "version": "2026.09.21-a1b2c3d", "features": features,
            "hq_agent": "dashboard", "at": iso(), "stale_since": None, "error": None,
            "pending": None}


def envelope(stale_since=None, error=None, pending=None, **payload):
    """Every snapshot route answers the same shape: when it was read, whether the reading is
    old, what went wrong, whether the first pass has happened at all, and the list by name."""
    return {"at": iso(), "stale_since": iso(stale_since) if stale_since else None,
            "error": error, "pending": pending, **payload}


def is_snapshot(path):
    return any(path == route or path.startswith(route) for route in SNAPSHOT_ROUTES)


def pending_payload(path):
    """What a snapshot route says before its first pass has run."""
    if path == "/api/config":
        answer = config_for("ready")
        answer["features"]["slice"] = False
        answer["features"]["ci_daemon"] = False
        answer["pending"] = iso()
        return answer
    key = {"/api/health": "checks", "/api/mail/boxes": "boxes", "/api/mail/thread": "messages",
           "/api/mail/feed": "events", "/api/mail/who": "sessions"}.get(path, "items")
    return envelope(pending=iso(), **{key: []})


def quiet_payload(path, query):
    """The three things the live farm showed that no other state here produces: a queue with
    nothing running and nothing waiting, lane names too long for a card, and an office holding
    two inbox issues under one name. Everything else in this state is the ready farm."""
    if path == "/api/fleet":
        return 200, AGENTS + LONG_AGENTS
    if path == "/api/ci":
        return 200, {"updated": NOW, "daemon_alive": True, "refresh_age": 2,
                     "running": [], "queued": [], "recent": QUEUE["recent"]}
    if path == "/api/mail/boxes":
        return 200, envelope(boxes=MAIL_BOXES_DOUBLED)
    if path == "/api/agent":
        slug = query.get("slug", [""])[0]
        for agent in LONG_AGENTS:
            if agent["slug"] == slug:
                return 200, dict(agent)
    return None


def payload_for(state, path, query):
    """One place that knows what each route answers in each state."""
    empty_list = []
    if state == "quiet":
        answer = quiet_payload(path, query)
        if answer is not None:
            return answer
        state = "ready"
    if state == "loading" and is_snapshot(path):
        return 200, pending_payload(path)
    if path == "/api/config":
        return 200, config_for(state)
    if path == "/api/version":
        return 200, {"v": "2026.09.21-a1b2c3d"}
    if path == "/api/access":
        return 200, {"writable": state != "error", "reason":
                     "" if state != "error" else "This page was opened without the dashboard token.",
                     "token_required": True, "loopback": True}
    if path == "/api/identities":
        return 200, {} if state == "empty" else IDENTITIES
    if path == "/api/health":
        checks = {"ready": HEALTH_READY, "empty": HEALTH_EMPTY, "error": HEALTH_ERROR}[state]
        return 200, envelope(checks=checks)
    if path == "/api/metrics":
        return 200, {"ready": METRICS_READY, "empty": METRICS_EMPTY, "error": METRICS_ERROR}[state]
    if path == "/api/mode":
        return 200, {"setting": "auto", "effective": "full", "gpu_util": 22, "allow_spawn": True,
                     "cpu_quota_pct": None, "cpu_cores": None, "cores_total": 14,
                     "mem_high_pct": None, "mem_high_gb": None, "ram_total_gb": 64.0,
                     "ram_free_gb": 28.4, "ci_ram_released": True}
    if path == "/api/sweep":
        if state == "error":
            return 200, {"enabled": False, "secs_left": None, "result": None}
        return 200, {"enabled": True, "secs_left": 540, "result": "success"}
    if path == "/api/fleet":
        return 200, empty_list if state == "empty" else AGENTS
    if path == "/api/agent":
        slug = query.get("slug", [""])[0]
        for agent in AGENTS:
            if agent["slug"] == slug:
                record = dict(agent)
                if slug in RESULTS:
                    record["result_text"] = RESULTS[slug]
                return 200, record
        return 200, {"error": "not found"}
    if path == "/api/agent/log":
        slug = query.get("slug", [""])[0]
        if state == "empty":
            return 200, {"slug": slug, "file": None, "lines": [], "truncated": False,
                         "missing": True, "message": "This lane has no log file yet."}
        tail = int(query.get("tail", ["200"])[0] or 200)
        return 200, {"slug": slug, "file": f"/home/farm/.fleet/logs/{slug}.log",
                     "lines": LOG_LINES[-tail:], "truncated": tail < len(LOG_LINES),
                     "missing": False}
    if path == "/api/ci":
        if state == "empty":
            return 200, {"updated": NOW, "daemon_alive": True, "refresh_age": 1,
                         "running": [], "queued": [], "recent": []}
        if state == "error":
            return 500, {"error": "the queue runner is not answering"}
        return 200, QUEUE
    if path == "/api/ci/log":
        if state == "empty":
            return 200, {"id": query.get("id", [""])[0], "tier": query.get("tier", [""])[0], "content": ""}
        return 200, {"id": query.get("id", [""])[0], "tier": query.get("tier", [""])[0],
                     "content": "\n".join(LOG_LINES[:40])}
    if path == "/api/projects":
        return 200, empty_list if state == "empty" else PROJECTS + SENT["projects"]
    if path == "/api/accounts":
        if state == "empty":
            return 200, {"at": NOW, "accounts": [], "errors": {}}
        return 200, ACCOUNTS
    if path == "/api/models":
        return 200, empty_list if state == "empty" else MODELS
    if path.startswith("/api/mail/"):
        if state == "error":
            return 200, MAIL_UNAVAILABLE
        empty = state == "empty"
        if path == "/api/mail/boxes":
            return 200, envelope(boxes=[] if empty else MAIL_BOXES)
        if path == "/api/mail/thread":
            box = query.get("box", [""])[0]
            since = query.get("since", [""])[0]
            if not box:
                return 400, {"error": "a thread needs the name of a mailbox"}
            if since and _epoch(since) <= 0:
                return 400, {"error": f"{since} is not a time this server can read"}
            known = [row["name"] for row in MAIL_BOXES]
            if not empty and box not in known:
                return 404, {"error": f"there is no mailbox called {box}",
                             "boxes": MAIL_BOXES}
            thread = [] if empty else (MAIL_THREADS.get(box, [])
                                       + [row for row in SENT["mail"] if row["box"] == box])
            if since:
                edge = _epoch(since)
                thread = [row for row in thread if row["created_at"] > edge]
            return 200, envelope(box=box, window_hours=72, messages=[
                {"sender": row["sender"], "at": row["at"], "created_at": row["created_at"],
                 "text": row["text"]} for row in thread])
        if path == "/api/mail/feed":
            hours = int(query.get("hours", ["24"])[0] or 24)
            return 200, envelope(hours=hours, events=[] if empty else MAIL_FEED)
        if path == "/api/mail/who":
            if empty:
                return 200, envelope(sessions=[])
            # A stale snapshot is a state the page has to say out loud, so one route shows it.
            return 200, envelope(sessions=MAIL_WHO, stale_since=ago(300))
    return 404, {"error": f"the stub does not serve {path}"}


def _epoch(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return time.mktime(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return 0.0


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def state(self):
        query = parse_qs(urlparse(self.path).query)
        if query.get("state", [""])[0] in STATES:
            return query["state"][0]
        referer = self.headers.get("Referer") or ""
        from_page = parse_qs(urlparse(referer).query).get("state", [""])[0]
        if from_page in STATES:
            return from_page
        chosen = os.environ.get("STUB_STATE", "ready")
        return chosen if chosen in STATES else "ready"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            state = self.state()
            if state == "loading" and not is_snapshot(path):
                time.sleep(LOADING_DELAY)
            code, payload = payload_for(state, path, parse_qs(parsed.query))
            return self._json(code, payload)
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path in ("/", "/index.html"):
            return self._file(PAGE, "text/html; charset=utf-8")
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        if parsed.path == "/api/agent/msg":
            if not body.get("slug") or not body.get("text"):
                return self._json(400, {"error": "a message needs a lane and some text"})
            SENT["messages"].append(body)
            return self._json(200, {"ok": True, "slug": body["slug"],
                                    "detail": f"queued for {body['slug']}"})
        if parsed.path == "/api/mail/send":
            if self.state() == "empty":
                return self._json(503, {"error": "the office has not been read yet"})
            to = body.get("to", "all")
            if not body.get("text"):
                return self._json(400, {"error": "a message needs some text"})
            SENT["mail"].append({"box": to, "sender": "dashboard", "at": "just now",
                                 "created_at": time.time(), "text": body["text"]})
            return self._json(200, {"ok": True, "to": to, "from": "dashboard",
                                    "detail": f"sent to {to} as dashboard"})
        if parsed.path == "/api/projects":
            if not body.get("name") or not body.get("repo"):
                return self._json(200, {"error": "a project needs a name and a repository"})
            row = {"name": body["name"], "repo": body["repo"], "path": f"/home/farm/work/{body['name']}",
                   "base_branch": "main", "ports": {"web": body.get("port_base", 5300),
                                                    "api": body.get("port_base", 5300) + 1,
                                                    "e2e": body.get("port_base", 5300) + 2},
                   "lanes_open": 0, "last_activity": time.time()}
            SENT["projects"].append(row)
            return self._json(200, row)
        if parsed.path in ("/api/mode", "/api/models"):
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})

    # ------------------------------------------------------------- plumbing

    def _static(self, relative):
        target = (STATIC / relative).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            return self._json(404, {"error": "not found"})
        kinds = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".json": "application/json", ".svg": "image/svg+xml"}
        return self._file(target, kinds.get(target.suffix, "application/octet-stream"))

    def _file(self, path, content_type):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("127.0.0.1", PORT), Handler) as server:
        threading.current_thread().name = "stub"
        server.serve_forever()
