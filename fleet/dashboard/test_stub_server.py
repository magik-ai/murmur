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
import re
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
SNAPSHOT_ROUTES = ("/api/config", "/api/health", "/api/mail/", "/api/services",
                   "/api/accounts/login-state", "/api/hosts", "/api/machines")


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

# Only the dev server base is a project's own. The api and end-to-end bases are the same
# numbers for every project on a farm, which is why a page that took the highest of all three
# suggested a block far above the one the farm would actually hand out.
PROJECTS = [
    {"name": "demo", "repo": "your-org/demo", "path": "/home/farm/work/demo",
     "base_branch": "main", "ports": {"web": 5200, "api": 8100, "e2e": 9100},
     "lanes_open": 3, "last_activity": ago(40)},
    {"name": "storefront", "repo": "your-org/storefront", "path": "/home/farm/work/storefront",
     "base_branch": "main", "ports": {"web": 5210, "api": 8100, "e2e": 9100},
     "lanes_open": 2, "last_activity": ago(5400)},
    {"name": "sandbox", "repo": "your-org/sandbox", "path": "/home/farm/work/sandbox",
     "base_branch": "main", "ports": {"web": 5220, "api": 8100, "e2e": 9100},
     "lanes_open": 0, "last_activity": ago(86000)},
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
        "failed_tests": [
            {"tier": "end to end", "test": "orders.spec.ts > an empty basket says so",
             "log": f"/home/farm/.fleet/ci/logs/ci-{1000 + index}-0000/end-to-end.log"},
        ] if state == "failed" else [],
        "base_branch": "main", "head_sha": f"{index:07x}9ab",
        "enqueued": started - 30,
        "farm_verdict": state if state in ("passed", "failed") else None,
        "hosted_verdict": state if state in ("passed", "failed") else None,
        "divergent": False,
    }


# A farm that has been up for a day holds dozens of finished runs, and the table has to stay
# readable with all of them in it. These carry the shape the detail panel reads: five stages,
# failed tests with their names, the gates this queue does not cover, and the two verdicts.
DEEP_STAGES = ["changed files", "unit tests", "browser", "container image", "documents"]
DEEP_STATES = ["passed", "failed", "passed_partial", "passed", "cancelled", "passed"]


def deep_record(index):
    state = DEEP_STATES[index % len(DEEP_STATES)]
    started = ago(7200 + index * 300)
    project = "demo" if index % 2 else "storefront"
    stages = []
    at = started
    for position, name in enumerate(DEEP_STAGES):
        span = 40 + position * 45
        stage_state = "passed"
        if state == "failed" and name == "browser":
            stage_state = "failed"
        elif state == "failed" and position > 2:
            stage_state = "skipped"
        elif state == "cancelled" and position > 1:
            stage_state = "cancelled"
        elif state == "passed_partial" and name == "container image":
            stage_state = "skipped"
        stages.append({
            "name": name, "state": stage_state, "started": at, "ended": at + span,
            "detail": "one case failed on the orders screen" if stage_state == "failed" else "",
            "log": f"{name.replace(' ', '-')}.log",
        })
        at += span
    # One run where the two verdicts disagree. It has to be a failed one, or "they disagree"
    # would be a sentence over two identical words.
    divergent = state == "failed" and index == 7
    return {
        "id": f"ci-{2000 + index}-0000", "project": project, "repo": f"your-org/{project}",
        "pr": 300 + index, "branch": f"{project}/change-{index}", "state": state,
        "reason": {"passed_partial": "verified with the hosted browser check left out",
                   "cancelled": "a person cancelled this run"}.get(state, ""),
        "started": started, "ended": at, "enqueued": started - 45, "position": None,
        "base_branch": "main", "head_sha": f"{index:07x}c1d",
        "tiers": stages,
        "uncovered": ["hosted browser check", "licence scan", "publish the image"]
                     if state == "passed_partial" else [],
        "failed_tests": [
            {"tier": "browser", "test": "orders.spec.ts > an empty basket says so",
             "log": f"/home/farm/.fleet/ci/logs/ci-{2000 + index}-0000/browser.log"},
            {"tier": "browser", "test": "orders.spec.ts > a declined card is explained",
             "log": f"/home/farm/.fleet/ci/logs/ci-{2000 + index}-0000/browser.log"},
        ] if state == "failed" else [],
        "farm_verdict": "failed" if state == "failed" else "passed",
        "hosted_verdict": "passed" if divergent or state != "failed" else "failed",
        "divergent": divergent,
    }


QUEUE = {
    "updated": NOW, "daemon_alive": True, "refresh_age": 4,
    "running": [queue_record(0, "running", "running")],
    "queued": [queue_record(1, "queued", "queued"), queue_record(2, "queued", "queued")],
    "recent": [queue_record(index + 3, state, "recent") for index, state in enumerate(QUEUE_STATES)]
              + [deep_record(index) for index in range(40 - len(QUEUE_STATES))],
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
        {"name": "farm-three", "label": "farm three", "engine": "claude", "session": None,
         "weekly": None, "session_resets": None, "weekly_resets": None, "read_at": None,
         "scoped": []},
        {"name": "farm-four", "label": "farm four", "engine": "claude", "session": 18,
         "weekly": 34, "session_resets": NOW + 3000, "weekly_resets": NOW + 250000,
         "read_at": ago(120), "scoped": [],
         "stale_error": "the vendor answered 429, so these numbers stopped refreshing"},
        # The fifth state: a credentials file that is there and cannot be read. The page must
        # not draw it as an account that was never set up, which is the one state that sends a
        # person off to log in again over a credential that was fine.
        {"name": "farm-unread", "label": "farm unread", "engine": "claude", "session": None,
         "weekly": None, "session_resets": None, "weekly_resets": None, "read_at": ago(300),
         "scoped": []},
    ],
    "errors": {},
}

# The models, as GET /api/engines answers them: the catalog row plus whether the command is
# on this machine (`installed` and `path`), what to run if it is not (`install_hint`), how the
# model is paid for (`access`), the one word the table draws as a pill (`status`), whether the
# operator added the entry or it shipped with the farm (`source`), and the variant it runs.
#
# There are five rows here on purpose, one per status, because the table draws a different set
# of actions for each. The fields are the ones GET /api/engines really carries: `health` is the
# state of the last test (ok | fail | unchecked) and `health_prompt` is the tiny prompt a test
# sends, which is how lib/models.py names them; no row carries `docs`, because nothing on the
# server writes one into a catalog; and the two rows this farm added carry no role, quality or
# caps note, because the add route writes none.
MODELS = [
    {"id": "claude", "label": "Claude Code", "glyph": "C", "color": "#D97757", "enabled": True,
     "engine": "claude", "source": "shipped", "preset": "", "status": "on", "variant": "opus",
     "access": "Your Claude subscription.",
     "role": "the workhorse: most lanes, most of the time",
     "quality": "frontier", "caps": "Two windows, session and weekly.",
     "tos": "First-party CLI on the Anthropic subscription, made for headless runs.",
     "run": "claude -p {task}", "auth_env": "",
     "health": "ok", "health_prompt": "What is 17 plus 25? Reply with the number only.", "health_detail": "",
     "routable": True,
     "models": "opus, sonnet, haiku", "limits": "two windows, session and weekly",
     "command": "claude",
     "installed": True, "path": "/home/farm/.local/bin/claude", "last_test": ago(1800),
     "install_hint": "npm install -g @anthropic-ai/claude-code"},
    # Installed, keyed, switched on, and the last health call did not come back. The table draws
    # Failing and puts the server's own detail under the pill.
    {"id": "codex", "label": "Codex", "glyph": "X", "color": "#10A37F", "enabled": True,
     "engine": "codex", "source": "shipped", "preset": "", "status": "failing",
     "variant": "gpt-5-codex",
     "access": "Your ChatGPT subscription.",
     "role": "frontier tier: architecture, security, migrations",
     "quality": "frontier, Opus-class on agentic work", "caps": "One five hour window.",
     "tos": "First-party CLI on the ChatGPT subscription.",
     "run": "codex exec {task}", "auth_env": "",
     "health": "fail", "health_prompt": "What is 17 plus 25? Reply with the number only.",
     "health_detail": "the last health call timed out", "routable": False,
     "models": "gpt-5-codex", "limits": "five hour window", "command": "codex",
     "installed": True, "path": "/usr/bin/codex", "last_test": ago(600),
     "install_hint": "npm install -g @openai/codex"},
    # Added by the operator, installed, keyed, and switched off. This is the only row that can
    # be switched on, and one of the two that can be removed. It carries no role, quality or
    # caps note: those are catalog fields a person writes, and lib/model_presets.py does not
    # write them, so a row this farm added through the dialog has none.
    {"id": "qwen", "label": "Qwen Code", "color": "#7C5CFC", "enabled": False,
     "engine": "generic", "source": "added", "preset": "qwen", "status": "off",
     "variant": "qwen3-coder-plus",
     "access": "An API key, held on the farm.",
     "tos": "LOW: a documented headless mode, and the plan is sold for agentic use.",
     "run": "{bin} -p {task} --output-format stream-json", "auth_env": "QWEN_CODE_API_KEY",
     "health": "ok", "health_prompt": "What is 17 plus 25? Reply with the number only.", "health_detail": "",
     "routable": False, "limits": "", "command": "qwen",
     "installed": True, "path": "/home/farm/.local/bin/qwen", "last_test": ago(7200),
     "install_hint": "npm install -g @qwen-code/qwen-code"},
    # Added, installed, and no key was ever pasted. It cannot be switched on: a model with no
    # credential spawns a lane that cannot answer. Test is offered, because a key is pasted in a
    # terminal and this page cannot see it land.
    {"id": "kimi", "label": "Kimi Code", "color": "#6D5AE6", "enabled": False,
     "engine": "generic", "source": "added", "preset": "kimi", "status": "needs_key",
     "variant": "",
     "access": "An API key, held on the farm.",
     "tos": "HIGH: the subscription is sold for interactive use only, so a headless farm "
            "risks suspension.",
     "run": "{bin} -p {task} --output-format stream-json", "auth_env": "KIMI_API_KEY",
     "health": "unchecked", "health_prompt": "What is 17 plus 25? Reply with the number only.", "health_detail": "",
     "routable": False, "limits": "", "command": "kimi",
     "installed": True, "path": "/home/farm/.local/bin/kimi", "last_test": None,
     "install_hint": "npm install -g @moonshot/kimi-code"},
    # The one this machine cannot run. It carries enabled true on purpose: a model left switched
    # on in the registry and then uninstalled is exactly the row that must not offer a switch,
    # because pressing it spawns a lane that cannot start.
    {"id": "local", "label": "Local model", "color": "#8b949e", "enabled": True,
     "engine": "generic", "source": "shipped", "preset": "", "status": "not_installed",
     "variant": "",
     "access": "Runs on this machine. Nothing is paid.",
     "role": "offline experiments", "quality": "well under the frontier tier",
     "caps": "Whatever this machine can hold.",
     "tos": "Local weights on your own machine, so no service terms apply.",
     "run": "{bin} run {variant} {task}", "auth_env": "",
     "health": "unchecked", "health_prompt": "What is 17 plus 25? Reply with the number only.", "health_detail": "",
     "routable": False, "limits": "", "command": "llama",
     "installed": False, "path": "", "last_test": None,
     "install_hint": "curl -fsSL https://example.invalid/local/install.sh | sh"}
]

# The presets GET /api/models/presets serves: one service per card in the add dialog. A preset
# is a description, never farm state; whether the farm already carries it is the `added` flag,
# computed per request from the catalog above and whatever this stub has been asked to add.
#
# `tos_kind` is the server's own classification of its `tos` sentence, in one word: safe, check
# or blocked. The page draws it as the card's terms pill, so a sentence nobody has read is never
# called safe by a page guessing from its wording.
MODEL_PRESETS = [
    {"id": "claude", "label": "Claude Code", "color": "#D97757", "kind": "subscription", "tos_kind": "safe", "pull_hint": "",
     "engine": "claude", "bin": "claude",
     "install_hint": "npm install -g @anthropic-ai/claude-code", "auth_env": "",
     "run": "claude -p {task}", "health": "What is 17 plus 25? Reply with the number only.",
     "tos": "First-party CLI on the Anthropic subscription, made for headless runs.",
     "access": "Your Claude subscription.", "variants": ["opus", "sonnet", "haiku"],
     "docs": "https://example.invalid/docs/claude-code"},
    {"id": "codex", "label": "Codex", "color": "#10A37F", "kind": "subscription", "tos_kind": "safe", "pull_hint": "",
     "engine": "codex", "bin": "codex", "install_hint": "npm install -g @openai/codex",
     "auth_env": "", "run": "codex exec {task}", "health": "What is 17 plus 25? Reply with the number only.",
     "tos": "First-party CLI on the ChatGPT subscription.",
     "access": "Your ChatGPT subscription.", "variants": ["gpt-5-codex"],
     "docs": "https://example.invalid/docs/codex"},
    {"id": "gemini", "label": "Gemini CLI", "color": "#4285F4", "kind": "key", "tos_kind": "safe", "pull_hint": "",
     "engine": "generic", "bin": "gemini", "install_hint": "npm install -g @google/gemini-cli",
     "auth_env": "GEMINI_API_KEY", "run": "{bin} -p {task}",
     "health": "What is 17 plus 25? Reply with the number only.",
     "tos": "A documented non-interactive mode, billed against the key.",
     "access": "An API key, billed per token.",
     "variants": ["gemini-2.5-pro", "gemini-2.5-flash"],
     "docs": "https://example.invalid/docs/gemini-cli"},
    {"id": "qwen", "label": "Qwen Code", "color": "#7C5CFC", "kind": "key", "tos_kind": "safe", "pull_hint": "",
     "engine": "generic", "bin": "qwen",
     "install_hint": "npm install -g @qwen-code/qwen-code", "auth_env": "QWEN_CODE_API_KEY",
     "run": "{bin} -p {task} --output-format stream-json", "health": "What is 17 plus 25? Reply with the number only.",
     "tos": "LOW: a documented headless mode, and the plan is sold for agentic use.",
     "access": "An API key, held on the farm.",
     "variants": ["qwen3-coder-plus", "qwen3-coder-flash"],
     "docs": "https://example.invalid/docs/qwen-code"},
    {"id": "kimi", "label": "Kimi Code", "color": "#6D5AE6", "kind": "key", "tos_kind": "blocked", "pull_hint": "",
     "engine": "generic", "bin": "kimi", "install_hint": "npm install -g @moonshot/kimi-code",
     "auth_env": "KIMI_API_KEY", "run": "{bin} -p {task} --output-format stream-json",
     "health": "What is 17 plus 25? Reply with the number only.",
     "tos": "HIGH: the subscription is sold for interactive use only, so a headless farm "
            "risks suspension.",
     "access": "An API key, held on the farm.", "variants": [],
     "docs": "https://example.invalid/docs/kimi-code"},
    {"id": "opencode", "label": "OpenCode", "color": "#F5A623", "kind": "key", "tos_kind": "safe", "pull_hint": "",
     "engine": "generic", "bin": "opencode", "install_hint": "npm install -g opencode-ai",
     "auth_env": "OPENCODE_API_KEY", "run": "{bin} run {task}",
     "health": "What is 17 plus 25? Reply with the number only.",
     "tos": "Open source client, so the terms are the provider's behind the key.",
     "access": "An API key, billed per token.", "variants": [],
     "docs": "https://example.invalid/docs/opencode"},
    {"id": "aider", "label": "Aider", "color": "#14B8A6", "kind": "key", "engine": "generic", "tos_kind": "safe", "pull_hint": "",
     "bin": "aider", "install_hint": "python3 -m pip install aider-install",
     "auth_env": "OPENAI_API_KEY", "run": "{bin} --message {task} --yes",
     "health": "What is 17 plus 25? Reply with the number only.",
     "tos": "Open source client, so the terms are the provider's behind the key.",
     "access": "An API key, billed per token.", "variants": [],
     "docs": "https://example.invalid/docs/aider"},
    {"id": "ollama", "label": "Ollama local", "color": "#8b949e", "kind": "local", "tos_kind": "safe",
     "engine": "generic", "bin": "ollama",
     "install_hint": "curl -fsSL https://example.invalid/local/install.sh | sh",
     "pull_hint": "ollama pull <variant>", "auth_env": "", "run": "{bin} run {variant} {task}", "health": "What is 17 plus 25? Reply with the number only.",
     "tos": "Local weights on your own machine, so no service terms apply.",
     "access": "Runs on this machine. Nothing is paid.",
     "variants": ["qwen2.5-coder:14b", "llama3.1:8b"],
     "docs": "https://example.invalid/docs/ollama"},
    {"id": "custom", "label": "Custom command", "color": "#6e7681", "kind": "key", "tos_kind": "check", "pull_hint": "",
     "engine": "generic", "bin": "", "install_hint": "", "auth_env": "", "run": "",
     "health": "What is 17 plus 25? Reply with the number only.",
     "tos": "Whatever the terms of the service behind your command are.",
     "access": "However the command you give is paid for.", "variants": [],
     "docs": ""},
]

# The words that make a field a credential, and the two sentences the server refuses with. A
# field name is lowercased and stripped of punctuation first, so key, api_key, apiKey, API_KEY
# and x-api-key are all the same field: refusing only the exact spelling "key" made this stub
# weaker than the farm it stands in for. A command line that carries a key is refused too, and
# a command that READS one ($MY_API_KEY, {placeholder}) is what a person is told to write.
KEY_WORDS = ("key", "secret", "token", "credential", "password")
KEY_REFUSAL = "A key never goes through this page. Run: fleet models auth {id}"
KEY_IN_COMMAND = ("A key never goes through this page: take it out of the command line and name "
                  "the variable that holds it instead. Run: fleet models auth {id}")
KEY_FLAG = re.compile(r"--?[a-z0-9_-]*(?:key|secret|token|password)[\s=]+(\S+)", re.I)
KEY_TOKEN = re.compile(r"(?:\b(?:sk|pk|rk|ghp|gho|ghu|ghs|xox[abopsr])-[A-Za-z0-9_-]{8,}"
                       r"|\bAIza[A-Za-z0-9_-]{20,})")


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


# The id rule is lib/models.py's own (ID_RE), with its own sentence, so a name this stub takes
# is a name the farm takes: 2 to 31 characters, lower case, starting with a letter.
MODEL_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")
MODEL_ID_RULE = ("a model id is lower case letters, digits, - and _, starting with a letter, "
                 "2 to 31 characters")

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


# Newest first, the order the route sends and the page draws.
MAIL_FEED = [
    event(600, "mail", "dali to all: search typo tolerance is merged", "10m ago"),
    event(1800, "note", "the office snapshot was refreshed"),
    event(4200, "claim", "rubicon claimed storefront/checkout-retry"),
    event(7200, "claim", "winston claimed demo/web-empty-states", "2h ago"),
    event(20000, "session", "dali said hello and took the search lane", "5h ago"),
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
     "fix": "fleet ci daemon start"},
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
# `removed` holds the ids a person has taken out of the catalog in this run, fixture rows
# included: a farm can remove anything it added, and two of the five fixtures are rows this farm
# added. Without it the first Remove anyone tried by hand answered "no such model".
SENT = {"messages": [], "mail": [], "projects": [], "models": [], "removed": [],
        "machines": []}


def models_now():
    """The catalog as it stands: the fixtures plus what this run added, less what it removed."""
    return [row for row in MODELS + SENT["models"] if row["id"] not in SENT["removed"]]


# A stage log the server had to cut. The page must say so and name the command that shows the
# whole thing, which it cannot be trusted to do until a fixture is actually 256 KB long.
TRUNCATED_LOG = "\n".join(
    f"[12:{index // 60 % 60:02d}:{index % 60:02d}] step {index}: "
    "compiled one module and wrote its output to the work tree" for index in range(4000)
)[-256 * 1024:]

# The five login states the account reader can report, each under the key the server sends it
# in. The sentence is `sentence`, not `detail`: a page reading the wrong one drew five empty
# tooltips and told nobody what to do about an account that is not logged in.
LOGIN_STATES = [
    {"name": "farm-one", "engine": "claude", "state": "logged_in", "read_at": ago(240),
     "sentence": "Logged in. Lanes can be spawned on this account."},
    {"name": "farm-two", "engine": "codex", "state": "expired", "read_at": ago(900),
     "sentence": "The login on this account has expired. The keepalive timer usually refreshes "
                 "it; log in again if it does not."},
    {"name": "farm-three", "engine": "claude", "state": "waiting_for_login", "read_at": None,
     "sentence": "This account has no login on the farm yet. Log in once: ssh -t farm claude, "
                 "then /login"},
    {"name": "farm-four", "engine": "claude", "state": "rate_limited", "read_at": ago(120),
     "sentence": "The vendor asked the farm to slow down, so it cannot tell how much room is "
                 "left. These numbers refresh by themselves."},
    {"name": "farm-unread", "engine": "claude", "state": "unknown", "read_at": ago(300),
     "sentence": "This farm could not read this account's credentials file, so it cannot tell "
                 "whether the account is logged in."},
]

# An account added through the page is waiting for its first login until the fixture clock says
# the person has finished, which is how the step panel can be seen flipping by itself.
ADD_LOGIN_SECONDS = float(os.environ.get("STUB_ADD_LOGIN_SECONDS", "4"))
ADDED_ACCOUNTS = {}

# The keys are the server's own: `what` the service does, `since` it last became active, and
# `fix`, the command that puts it right from a terminal. A stub that answered `note`, `command`
# and `changed_at` let the page read three keys nothing on a real farm sends.
SERVICE_ROWS = [
    {"id": "agent_runner", "label": "agent runner", "unit": "fleet-daemon.service",
     "actions": ["start", "stop", "restart"], "verb": "fleet daemon", "fix": "fleet daemon start",
     "what": "respawns a lane that carries a restart policy until it delivers"},
    {"id": "ci_runner", "label": "verification runner", "unit": "fleet-ci.service",
     "actions": ["start", "stop", "restart"], "verb": "fleet ci daemon",
     "fix": "fleet ci daemon start",
     "what": "verifies one queued change at a time against main"},
    {"id": "sweep_timer", "label": "sweep timer", "unit": "fleet-sweep.timer",
     "actions": ["start", "stop"], "verb": "fleet autosweep", "fix": "fleet autosweep on",
     "what": "buries merged worktrees and resolved cards every few minutes"},
    {"id": "dashboard", "label": "This dashboard", "unit": "tmux session and a listening socket",
     "actions": [], "verb": "fleet dashboard", "fix": "fleet dashboard restart",
     "read_only": True, "what": "serves this page"},
]


def services_for(state):
    """systemctl --user is-active, as the 45 second refresher last read it."""
    rows = []
    for index, row in enumerate(SERVICE_ROWS):
        if state == "empty":
            live, detail = "inactive", "never started on this machine"
        elif state == "error" and row["id"] in ("ci_runner", "sweep_timer"):
            live = "failed" if row["id"] == "ci_runner" else "inactive"
            detail = ("the unit exited with status 1" if live == "failed"
                      else "not enabled on this machine")
        else:
            live, detail = "active", "running"
        if row["id"] == "dashboard":
            live, detail = "active", "answering on 127.0.0.1"
        rows.append({**row, "state": live, "detail": detail,
                     "since": ago(600 + index * 120)})
    return rows


JOB_SECONDS = float(os.environ.get("STUB_JOB_SECONDS", "2"))
JOBS = {}


def job_new(action, detail, fails=False, seconds=None, started=None):
    ident = "job-%04d" % (len(JOBS) + 1)
    JOBS[ident] = {"id": ident, "action": action, "detail": detail, "fails": fails,
                   "started": time.time() if started is None else started,
                   "seconds": JOB_SECONDS if seconds is None else seconds}
    return job_view(JOBS[ident])


def job_view(job):
    """A job is running until its own span is up, then it is done or it has failed."""
    elapsed = time.time() - job["started"]
    running = elapsed < job["seconds"]
    state = "running" if running else ("failed" if job["fails"] else "done")
    return {"id": job["id"], "action": job["action"], "detail": job["detail"], "state": state,
            "started": job["started"], "ended": None if running else job["started"] + job["seconds"],
            "error": "" if state != "failed" else "the runner refused this request, its log says why"}


# One job still running and one that finished, so the list has both without a press.
job_new("add project", "registering sandbox-two", seconds=3600)
job_new("drain", "salvaged and stopped 3 lanes", seconds=12, started=ago(400))


def power_preview(action):
    """What an action is about to do.

    The server works the numbers out of this farm's own power profile and writes them into one
    finished sentence, with the rest as warnings. It does not send a `caps` object, so neither
    does this stub: a page that builds its own sentence out of one reads every number as none.
    """
    lanes = [{"slug": row["slug"], "project": row["project"],
              "restart": "until-pr" if index % 2 else "",
              "has_pr": bool(row.get("pr_url"))}
             for index, row in enumerate(AGENTS) if row["status"] in ("running", "pr_open")]
    if action == "throttle":
        payload = {
            "label": "Throttle the farm and stop new agents",
            "sentence": "Every agent already running keeps running. This caps every agent "
                        "already running at 40% of the CPU (about 5.6 of 14 cores) and 40% of "
                        "this machine's memory, stops any new agent from being spawned, and "
                        "releases the verification database.",
            "warnings": ["Nothing is lost, and nothing is stopped."],
            "lanes": [],
        }
    elif action == "drain":
        payload = {
            "label": "Drain the farm",
            "sentence": f"This salvages and then stops the {len(lanes)} lane(s) below, stops "
                        "the agent runner so nothing is respawned, and stops the verification "
                        "database.",
            "warnings": ["A verification in flight loses its verdict.",
                         "A lane with no restart policy loses whatever salvage could not push.",
                         "This dashboard keeps running through all of it."],
            "lanes": lanes,
        }
    elif action == "resume":
        payload = {
            "label": "Resume the farm",
            "sentence": "This starts the agent runner again, and it will respawn every until-pr "
                        "and until-merged lane from its brief, which spends subscription.",
            "warnings": ["The verification database starts again at the next run."],
            "lanes": [row for row in lanes if row["restart"]],
        }
    else:
        return None
    payload.update({"action": action, "lane_count": len(payload["lanes"]), "running_job": None})
    return payload


# ------------------------------------------------------------------- hosting

# The providers as fleet/lib/host_presets.py serves them (design section 2), with the facts of
# the research pass of 2026-09-23: sizes, prices, stages and what each one is honest about.
# Nothing in this file talks to a provider, and no secret value is ever held here.
HOST_PRESETS = [
    {"id": "ssh", "label": "Your own machine", "color": "#7A8699", "job": "machine", "cli": "ssh",
     "stage": "ga", "install": "", "login": "", "docs": "https://man.openbsd.org/ssh",
     "engines": ["claude", "codex"],
     "terms": "Any Linux box you already reach over SSH: a spare PC, WSL2, a company VM.",
     "pricing": "Whatever you already pay for it.", "secrets": [], "sizes": [], "regions": []},
    {"id": "do-droplet", "label": "DigitalOcean Droplet", "color": "#0069FF", "job": "machine",
     "cli": "doctl", "stage": "ga", "install": "sudo snap install doctl",
     "login": "doctl auth init --context murmur",
     "docs": "https://docs.digitalocean.com/reference/doctl/", "engines": ["claude", "codex"],
     "terms": "A droplet is billed per second until it is destroyed. Powering it off does not "
              "stop the bill.",
     "pricing": "From $24 a month, list price on 2026-09-23.",
     "secrets": [],
     "sizes": [
         {"slug": "s-2vcpu-4gb", "label": "Small", "vcpu": 2, "ram_gb": 4, "disk_gb": 80,
          "monthly_usd": 24, "default": False},
         {"slug": "s-4vcpu-8gb", "label": "Standard", "vcpu": 4, "ram_gb": 8, "disk_gb": 160,
          "monthly_usd": 48, "default": True},
         {"slug": "s-8vcpu-16gb", "label": "Large", "vcpu": 8, "ram_gb": 16, "disk_gb": 320,
          "monthly_usd": 96, "default": False},
     ],
     "regions": [{"slug": "fra1", "label": "Frankfurt"}, {"slug": "ams3", "label": "Amsterdam"},
                 {"slug": "nyc3", "label": "New York"}]},
    {"id": "do-agents", "label": "DigitalOcean Managed Agents", "color": "#0069FF",
     "job": "runner", "cli": "doctl", "stage": "preview", "install": "sudo snap install doctl",
     "login": "doctl auth init --context murmur",
     "docs": "https://docs.digitalocean.com/products/managed-agents/", "engines": ["claude"],
     "terms": "Region RIC1 only, and a prepaid balance: a session pauses at zero. A session "
              "pauses after 15 idle minutes.",
     "pricing": "About $0.25 an hour for 4 vCPU and 8 GB, billed by DigitalOcean.",
     "secrets": ["CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN"], "sizes": [], "regions": ["ric1"]},
    {"id": "railway", "label": "Railway sandboxes", "color": "#8A63D2", "job": "runner",
     "cli": "railway", "stage": "early access", "install": "npm install -g @railway/cli",
     "login": "railway login --browserless", "docs": "https://docs.railway.com/cli/sandbox",
     "engines": ["claude"],
     "terms": "A sandbox stops itself after 30 idle minutes, which is Railway's own backstop.",
     "pricing": "$50 per vCPU-month and $50 per GB-month, while it runs.",
     "secrets": ["CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN"], "sizes": [], "regions": []},
    {"id": "vercel", "label": "Vercel Sandbox", "color": "#000000", "job": "runner",
     "cli": "sandbox", "stage": "ga", "install": "npm install -g sandbox", "login": "sandbox login",
     "docs": "https://vercel.com/docs/sandbox/cli-reference", "engines": ["claude"],
     "terms": "Up to 24 hours a session on Pro, 45 minutes on Hobby. UNVERIFIED: live streaming "
              "out of exec is not documented.",
     "pricing": "About $0.13 an hour of active CPU, plus memory.",
     "secrets": ["CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN"], "sizes": [], "regions": []},
]

# What this farm knows about each provider. `secrets` maps a stored name to the account label
# it was stored with; a name that is not in it is not stored. The four login states are spread
# across the states of this stub, because a page that only ever sees "logged in" draws the
# other three by guesswork.
HOST_FARM = {
    "ssh": {"cli_installed": True, "login_state": "logged_in", "account": "this farm's own key",
            "detail": "", "checked_at": ago(120), "secrets": {}, "tested": None},
    "do-droplet": {"cli_installed": True, "login_state": "logged_in",
                   "account": "owner@example.invalid", "detail": "", "checked_at": ago(90),
                   "secrets": {}, "tested": None},
    "do-agents": {"cli_installed": False, "login_state": "not_installed", "account": "",
                  "detail": "this doctl build has no harness-runtime commands",
                  "checked_at": ago(220), "secrets": {}, "tested": None},
    "railway": {"cli_installed": True, "login_state": "logged_in", "account": "murmur-workspace",
                "detail": "", "checked_at": ago(70),
                "secrets": {"CLAUDE_CODE_OAUTH_TOKEN": "work subscription", "GITHUB_TOKEN": ""},
                "tested": {"ok": True, "at": ago(5400), "seconds": 54,
                           "detail": "a sandbox started, claude answered and it was deleted"}},
    "vercel": {"cli_installed": True, "login_state": "logged_out", "account": "",
               "detail": "sandbox list came back with no session", "checked_at": ago(140),
               "secrets": {"GITHUB_TOKEN": ""},
               "tested": {"ok": False, "at": ago(9000), "seconds": 12,
                          "detail": "the sandbox was created and exec never streamed"}},
}

FRESH_FARM = {"cli_installed": False, "login_state": "not_installed", "account": "",
              "detail": "", "checked_at": None, "secrets": {}, "tested": None}

# A Test asked for through the page. It is answered the way a job is: not before its seconds
# are up, so the page can be watched flipping the pill by itself.
TESTS = {}


def host_rows(state):
    """The providers, in the shape of design section 7 as amended (cli, color, engines and docs
    on every row; default on every size): one preset plus this farm's reading, and no field
    the contract does not name, so a page that leans on one is caught here."""
    rows = []
    for preset in HOST_PRESETS:
        farm = dict(FRESH_FARM if state == "empty" else HOST_FARM[preset["id"]])
        stored = dict(farm["secrets"])
        tested = farm["tested"]
        asked = TESTS.get(preset["id"])
        if asked and time.time() - asked["at"] >= JOB_SECONDS:
            tested = {"ok": True, "at": asked["at"] + JOB_SECONDS, "seconds": 57,
                      "detail": f"a sandbox ran claude --version and git ls-remote for "
                                f"{asked['project']}, then was deleted"}
        rows.append({
            "id": preset["id"], "label": preset["label"], "color": preset["color"],
            "job": preset["job"], "stage": preset["stage"], "cli": preset["cli"],
            "docs": preset["docs"], "engines": list(preset["engines"]),
            "cli_installed": farm["cli_installed"], "login_state": farm["login_state"],
            "account": farm["account"], "detail": farm["detail"],
            "checked_at": farm["checked_at"],
            "secrets": [{"name": name, "stored": name in stored,
                         "account": stored.get(name, "")} for name in preset["secrets"]],
            "tested": tested,
            "login": preset["login"], "install": preset["install"], "terms": preset["terms"],
            "pricing": preset["pricing"], "sizes": preset["sizes"], "regions": preset["regions"],
        })
    return rows


THIS_FARM = {"name": "quartz", "address": "127.0.0.1"}

FINISH_TEMPLATE = ("ssh -t farm@{address} 'gh auth login && gh repo clone magik-ai/murmur "
                   "~/work/murmur -- -q && bash ~/work/murmur/farm/install.sh --remote'")
TUNNEL_TEMPLATE = "ssh -N -L 7878:127.0.0.1:7878 farm@{address}"

# One machine per state, because each one offers a different set of actions and a different
# sentence about money, and a table with only ready rows in it proves none of them.
MACHINES = [
    {"name": "athens", "provider": "do-droplet", "user": "farm", "address": "203.0.113.10",
     "size": "s-4vcpu-8gb", "monthly_usd": 48, "region": "fra1", "state": "ready",
     "detail": "fleet capacity answered", "checked_at": ago(180), "provider_id": 4001,
     "finish_command": "", "tunnel_command": TUNNEL_TEMPLATE.format(address="203.0.113.10")},
    {"name": "brussels", "provider": "do-droplet", "user": "farm", "address": "203.0.113.11",
     "size": "s-2vcpu-4gb", "monthly_usd": 24, "region": "ams3", "state": "needs-login",
     "detail": "first boot finished, your two logins are left", "checked_at": ago(300),
     "provider_id": 4002, "finish_command": FINISH_TEMPLATE.format(address="203.0.113.11"),
     "tunnel_command": ""},
    {"name": "cairo", "provider": "do-droplet", "user": "farm", "address": "",
     "size": "s-8vcpu-16gb", "monthly_usd": 96, "region": "nyc3", "state": "creating",
     "detail": "the provider is building it", "checked_at": ago(20), "provider_id": None,
     "finish_command": "", "tunnel_command": ""},
    {"name": "delhi", "provider": "do-droplet", "user": "farm", "address": "203.0.113.13",
     "size": "s-4vcpu-8gb", "monthly_usd": 48, "region": "fra1", "state": "preparing",
     "detail": "cloud-init is installing packages", "checked_at": ago(45), "provider_id": 4004,
     "finish_command": "", "tunnel_command": ""},
    {"name": "edinburgh", "provider": "do-droplet", "user": "farm", "address": "203.0.113.14",
     "size": "s-2vcpu-4gb", "monthly_usd": 24, "region": "ams3", "state": "unreachable",
     "detail": "ssh timed out after 5 seconds", "checked_at": ago(900), "provider_id": 4005,
     "finish_command": "", "tunnel_command": ""},
    {"name": "faro", "provider": "do-droplet", "user": "farm", "address": "",
     "size": "s-4vcpu-8gb", "monthly_usd": 48, "region": "fra1", "state": "failed",
     "detail": "doctl refused: this account has no payment method on file",
     "checked_at": ago(1200), "provider_id": None, "finish_command": "", "tunnel_command": ""},
    {"name": "genoa", "provider": "do-droplet", "user": "farm", "address": "",
     "size": "s-4vcpu-8gb", "monthly_usd": 48, "region": "nyc3", "state": "destroyed",
     "detail": "destroyed on 2026-09-20; nothing is billed for it",
     "checked_at": ago(36000), "provider_id": 4007, "finish_command": "", "tunnel_command": ""},
    {"name": "haifa", "provider": "do-droplet", "user": "farm", "address": "203.0.113.17",
     "size": "s-2vcpu-4gb", "monthly_usd": 24, "region": "fra1", "state": "unrecorded",
     "detail": "tagged murmur-by-quartz at the provider and not in this registry",
     "checked_at": ago(120), "provider_id": 4008, "finish_command": "", "tunnel_command": ""},
    {"name": "ithaca", "provider": "ssh", "user": "dev", "address": "192.168.1.40",
     "size": "", "monthly_usd": 0, "region": "", "state": "ready",
     "detail": "fleet capacity answered", "checked_at": ago(600), "provider_id": None,
     "finish_command": "", "tunnel_command": TUNNEL_TEMPLATE.format(address="192.168.1.40")},
]

# A lane name on a real farm is longer than a card, and so is a machine name a person gave a
# ticket number. The quiet state carries one of each, so the ellipsis rule is measured.
LONG_MACHINES = [
    {"name": "the-second-farm-for-the-checkout-rewrite-and-its-nightly-lanes",
     "provider": "do-droplet", "user": "farm", "address": "203.0.113.200",
     "size": "s-8vcpu-16gb", "monthly_usd": 96, "region": "fra1", "state": "ready",
     "detail": "fleet capacity answered with fourteen cores free, which is more than this farm "
               "has, and the whole sentence belongs on the title rather than in the cell",
     "checked_at": ago(60), "provider_id": 4100, "finish_command": "",
     "tunnel_command": TUNNEL_TEMPLATE.format(address="203.0.113.200")},
]

MACHINE_STEP_SECONDS = float(os.environ.get("STUB_MACHINE_SECONDS", "3"))
MACHINE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
MACHINE_NAME_RULE = ("a machine name is lower case letters, digits and dashes, starting with a "
                     "letter, 2 to 31 characters")
TARGET_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.:_-]+$")
PUBLIC_KEY_RE = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9-]+)\s+[A-Za-z0-9+/=]+"
                           r"(\s+\S.*)?$")
# The four exact token shapes scrub.py knows. A value that matches one is refused, and the
# refusal never repeats the value: a sentence that echoes a token has leaked it.
TOKEN_SHAPES = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{36,}"
                          r"|github_pat_[A-Za-z0-9_]{50,}|dop_v1_[a-f0-9]{64}")
SECRET_REFUSAL = ("a secret never goes through this page: store it in a terminal with "
                  "fleet hosts secret <provider> <NAME>")


def advance(row):
    """A machine created through the page moves on by itself, as the farm's refresher moves it.

    The page must never do this arithmetic: the row is the farm's, and this stub stands in for
    a refresher that carries one step per pass."""
    born = row.get("created_at")
    if not born or row["state"] not in ("creating", "preparing", "needs-login"):
        return row
    elapsed = time.time() - born
    if row["provider"] == "ssh":
        return row
    if elapsed < MACHINE_STEP_SECONDS:
        row["state"] = "creating"
    elif elapsed < MACHINE_STEP_SECONDS * 2:
        row["state"] = "preparing"
        row["address"] = row["address"] or "203.0.113.50"
        row["provider_id"] = row["provider_id"] or 4200
    else:
        row["state"] = "needs-login"
        row["address"] = row["address"] or "203.0.113.50"
        row["provider_id"] = row["provider_id"] or 4200
        row["finish_command"] = FINISH_TEMPLATE.format(address=row["address"])
    row["checked_at"] = time.time()
    return row


def machines_for(state):
    rows = [] if state == "empty" else MACHINES
    if state == "quiet":
        rows = MACHINES + LONG_MACHINES
    return [advance(row) for row in rows + SENT["machines"]]


# The fields of a machine row in design section 7, as amended (provider_id). The stub keeps a
# little bookkeeping of its own on a row (created_at), and none of it is ever sent.
MACHINE_FIELDS = ("name", "provider", "user", "address", "size", "monthly_usd", "region",
                  "state", "detail", "checked_at", "provider_id", "finish_command",
                  "tunnel_command")


def machines_payload(state, **extra):
    rows = machines_for(state)
    # As the farm counts it: a destroyed droplet, and a failed row the provider never made a
    # droplet for, cost nothing, and neither does a machine of your own.
    total = sum(row["monthly_usd"] or 0 for row in rows
                if row["state"] != "destroyed" and row["provider"] != "ssh"
                and not (row["state"] == "failed" and not row["provider_id"]))
    return envelope(this=dict(THIS_FARM), total_monthly_usd=total,
                    machines=[{field: row.get(field) for field in MACHINE_FIELDS}
                              for row in rows], **extra)


def machine_named(name):
    return next((row for row in machines_for("ready") if row["name"] == name), None)


def size_named(slug):
    droplet = next(row for row in HOST_PRESETS if row["id"] == "do-droplet")
    return next((size for size in droplet["sizes"] if size["slug"] == slug), None)


def machine_plan(body):
    """What `fleet machines plan --json` prints: the commands, the file, and the live price."""
    name = str(body.get("name") or "")
    size = size_named(str(body.get("size") or ""))
    region = str(body.get("region") or "")
    if not MACHINE_NAME_RE.match(name):
        return 400, {"error": MACHINE_NAME_RULE}
    if size is None:
        return 400, {"error": "that is not a size this provider sells"}
    # As `fleet machines plan --json` prints them: each command its argument list, not a string.
    commands = [
        ["doctl", "compute", "ssh-key", "import", "murmur-quartz", "--public-key-file",
         "/tmp/xxxx.pub", "--context", "murmur"],
        # Inbound SSH only, and every outbound rule: a DigitalOcean firewall denies whatever it
        # does not list, outbound included, so one without these would cut the farm off from
        # GitHub and the model providers (internal/research/report-hosting.md, "Firewall").
        ["doctl", "compute", "firewall", "create", "--name", "murmur-ssh-only", "--tag-names",
         "murmur-farm", "--inbound-rules",
         "protocol:tcp,ports:22,address:0.0.0.0/0 protocol:tcp,ports:22,address:::/0",
         "--outbound-rules",
         "protocol:tcp,ports:0,address:0.0.0.0/0 protocol:udp,ports:0,address:0.0.0.0/0 "
         "protocol:icmp,address:0.0.0.0/0 protocol:tcp,ports:0,address:::/0 "
         "protocol:udp,ports:0,address:::/0", "--context", "murmur"],
        ["doctl", "compute", "droplet", "create", name, "--size", size["slug"], "--region", region,
         "--image", "ubuntu-24-04-x64", "--tag-names", "murmur,murmur-farm,murmur-by-quartz",
         "--user-data-file", "/tmp/xxxx.yaml", "-o", "json", "--context", "murmur"],
    ]
    cloud_init = "\n".join([
        "#cloud-config",
        "users:",
        "  - name: farm",
        "    shell: /bin/bash",
        "    ssh_authorized_keys:",
        "      - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... farm@quartz",
        "      - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... you@laptop",
        "packages: [git, tmux, python3, curl, ca-certificates]",
        "runcmd:",
        "  - runuser -u farm -- sh -c 'mkdir -p ~/.config/fleet && echo "
        "FLEET_DASH_BIND=127.0.0.1 >> ~/.config/fleet/env'",
        "  - loginctl enable-linger farm",
    ])
    return 200, {"ok": True, "provider": "do-droplet", "name": name, "size": size["slug"],
                 "region": region, "monthly_usd": size["monthly_usd"],
                 "price_source": "live, doctl compute size list",
                 "commands": commands, "cloud_init": cloud_init}


# ------------------------------------------------------------------- the server

def config_for(state):
    # health_panel is off, as on every farm that has not set FLEET_DASH_HEALTH=on.
    features = {"hq": True, "slice": True, "gpu": True, "cpu_temp": True,
                "ci_daemon": True, "forge": True, "health_panel": False}
    if state == "error":
        features.update({"hq": False, "gpu": False, "cpu_temp": True})
    return {"title": "murmur", "version": "2026.09.21-a1b2c3d", "features": features,
            "hq_agent": "dashboard", "farm_alias": "farm", "at": iso(), "stale_since": None, "error": None,
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
           "/api/mail/feed": "events", "/api/mail/who": "sessions",
           "/api/services": "services", "/api/accounts/login-state": "accounts",
           "/api/hosts": "providers", "/api/machines": "machines"}.get(path, "items")
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
    if path == "/api/hosts":
        # A provider that was slow is not a provider you are logged out of, and this is the one
        # state that produces that reading.
        rows = host_rows("ready")
        for row in rows:
            if row["id"] == "do-agents":
                row["login_state"] = "no_answer"
                row["cli_installed"] = True
                row["detail"] = ("the check did not come back within fifteen seconds, so this "
                                 "farm cannot say whether it is logged in")
        return 200, envelope(providers=rows)
    if path == "/api/machines":
        return 200, machines_payload("quiet")
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
        run_id = query.get("id", [""])[0]
        tier = query.get("tier", [""])[0]
        if state == "empty":
            return 200, {"id": run_id, "tier": tier, "content": "", "truncated": False,
                         "missing": True, "message": "No log was recorded for this stage."}
        if not run_id or not tier:
            return 400, {"error": "a log needs a run and a stage"}
        # One stage carries a log the server had to cut, so the page can be made to say so.
        if tier in ("unit tests", "browser"):
            return 200, {"id": run_id, "tier": tier, "content": TRUNCATED_LOG,
                         "truncated": True, "missing": False}
        return 200, {"id": run_id, "tier": tier, "content": "\n".join(LOG_LINES[:40]),
                     "truncated": False, "missing": False}
    if path == "/api/services":
        if state == "error":
            # A farm with no systemd user manager is a farm that cannot answer this, and it says
            # so in a sentence with the command that fixes it. A 500 here would only teach every
            # other check on this page to expect a failed request.
            return 200, {"unavailable": "This machine has no user service manager, so services "
                                        "cannot be read or switched from here.",
                         "fix": "loginctl enable-linger $USER"}
        return 200, envelope(services=services_for(state))
    if path == "/api/hosts":
        if state == "error":
            # A snapshot the farm could not refresh: the last reading, and since when it is old.
            return 200, envelope(stale_since=ago(1800),
                                 error="fleet hosts list did not answer within sixty seconds",
                                 providers=host_rows("ready"))
        return 200, envelope(providers=host_rows(state))
    if path == "/api/machines":
        if state == "error":
            # The same envelope as /api/hosts: no GET runs a tool, so a refresh that failed is a
            # stale snapshot, never a failed request. A route that fails outright is a case the
            # hostile pass asks for on its own.
            return 200, machines_payload("ready", stale_since=ago(1800),
                                         error="fleet machines list did not answer within "
                                               "sixty seconds")
        return 200, machines_payload(state)
    if path == "/api/jobs":
        return 200, {"jobs": [job_view(job) for job in JOBS.values()]}
    if path.startswith("/api/jobs/"):
        found = JOBS.get(path[len("/api/jobs/"):])
        if not found:
            return 404, {"error": "there is no job with that id"}
        return 200, job_view(found)
    if path == "/api/power/preview":
        answer = power_preview(query.get("action", [""])[0])
        if answer is None:
            return 400, {"error": "an action is one of throttle, drain, resume"}
        return 200, answer
    if path == "/api/accounts/login-state":
        if state == "empty":
            return 200, envelope(accounts=[])
        rows = [dict(row) for row in LOGIN_STATES]
        for name, at in ADDED_ACCOUNTS.items():
            waiting = time.time() - at < ADD_LOGIN_SECONDS
            rows.append({
                "name": name, "engine": "claude", "read_at": time.time(),
                "state": "waiting_for_login" if waiting else "logged_in",
                "sentence": ("This account has no login on the farm yet. Log in once: "
                             "ssh -t farm claude, then /login"
                             if waiting else "Logged in. Lanes can be spawned on this account.")})
        return 200, envelope(accounts=rows)
    if path == "/api/projects/next-port":
        # The farm's own answer, read off the dev server bases alone. The api and end-to-end
        # bases are the same numbers for every project here, so counting them in would suggest
        # a block ten above the port every project's API already listens on.
        rows = [] if state == "empty" else PROJECTS + SENT["projects"]
        highest = max([row["ports"]["web"] for row in rows] or [5190])
        return 200, {"next_port_base": highest + 10,
                     "sentence": f"The next free port block on this farm is {highest + 10}. "
                                 "Leave the field empty to take it."}
    if path == "/api/projects":
        return 200, empty_list if state == "empty" else PROJECTS + SENT["projects"]
    if path == "/api/accounts":
        if state == "empty":
            return 200, {"at": NOW, "accounts": [], "errors": {}}
        return 200, ACCOUNTS
    if path == "/api/models/presets":
        # A preset is a description of a service, the same list in every state. Only `added`
        # is farm state, and it is computed here from the catalog this state is serving.
        carried = [] if state == "empty" else [row["id"] for row in models_now()]
        return 200, [dict(row, added=row["id"] in carried) for row in MODEL_PRESETS]
    if path in ("/api/models", "/api/engines"):
        return 200, empty_list if state == "empty" else models_now()
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


# --------------------------------------------------------------------- the harness

# The Queue and Machine views live in their own files and are registered by index.html and
# app.js, which another lane owns. This page is the same shell around the same two modules, so
# the two views can be opened, measured and photographed on their own before the page that
# links them exists. It reads the same routes, on the same three second tick, through the same
# core modules: nothing about the views is stubbed here.
HARNESS = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>murmur</title>
<link rel="stylesheet" href="/static/app.css">
<link rel="stylesheet" href="/static/queue.css">
<link rel="stylesheet" href="/static/models.css">
<link rel="stylesheet" href="/static/machine.css">
<link rel="stylesheet" href="/static/hosting.css">
</head>
<body>
<div id="app">
  <aside id="sidebar" aria-label="Sections">
    <div class="side-head"><span class="mark" aria-hidden="true"></span>
      <span class="mark-name" id="sidebarTitle">murmur</span></div>
    <nav id="navlinks">
      <a class="navlink" href="#/queue"><svg viewBox="0 0 24 24" aria-hidden="true"><path
        d="M4 6h16M4 12h16M4 18h10" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round"/></svg><span class="label">Queue</span></a>
      <a class="navlink" href="#/machine"><svg viewBox="0 0 24 24" aria-hidden="true"><path
        d="M6 6h12v12H6z" fill="none" stroke="currentColor" stroke-width="2"/><path
        d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" stroke="currentColor"
        stroke-width="2"/></svg><span class="label">Machine</span></a>
    </nav>
    <div class="side-foot"><span id="versionLabel" class="muted">harness</span></div>
  </aside>
  <header id="topbar">
    <h1 id="productTitle">murmur</h1>
    <span class="crumb-sep" aria-hidden="true">/</span>
    <span id="viewTitle" class="crumb"></span>
    <div class="top-right">
      <span id="capacity" class="pill pause" title="The harness draws no capacity reading."><span
        class="dot"></span><span class="pill-text">harness</span></span>
      <label class="field"><span class="sr-only">Project filter</span>
        <select id="projectFilter"><option value="">All projects</option></select></label>
      <span id="freshness" class="freshness" aria-live="polite"></span>
    </div>
  </header>
  <main id="view" tabindex="-1"></main>
</div>
<div id="drawer" class="drawer" hidden role="dialog" aria-modal="true" aria-labelledby="drawerTitle">
  <div class="drawer-head">
    <div><h2 id="drawerTitle"></h2><p id="drawerSub" class="muted"></p></div>
    <button id="drawerClose" class="ghost-button" aria-label="Close">Close</button>
  </div>
  <div id="drawerBody" class="drawer-body"></div>
</div>
<div id="drawerScrim" class="scrim" hidden></div>
<div id="toasts" class="toasts" aria-live="polite"></div>
<script type="module">
import * as api from "/static/core/api.js";
import * as identity from "/static/core/identity.js";
import { render, paintDrawer, closeDrawer } from "/static/core/ui.js";
import queue from "/static/views/queue.js";
import machine from "/static/views/machine.js";

const VIEWS = new Map([[queue.id, queue], [machine.id, machine]]);
const ALWAYS = ["/api/config", "/api/access", "/api/identities"];
const extra = new Set();
const state = { view: "queue", params: new URLSearchParams(), project: "" };

const context = {
  get config() { return api.resource("/api/config").data || { title: "murmur", features: {} }; },
  get features() { return context.config.features || {}; },
  get access() { return api.access; },
  get project() { return state.project; },
  get params() { return state.params; },
  get view() { return state.view; },
  res: (path) => api.resource(path),
  watch(path) {
    if (!extra.has(path)) {
      extra.add(path);
      api.pull([path]).then((done) => { if (done.length) paint(); });
    }
    return api.resource(path);
  },
  drop(path) { extra.delete(path); api.forget(path); },
  go(view, params) {
    const query = params ? new URLSearchParams(params).toString() : "";
    location.hash = "#/" + view + (query ? "?" + query : "");
  },
  paint,
  identity,
  async refresh(path) { await api.refresh(path); paint(); },
};

function current() { return VIEWS.get(state.view) || queue; }

function paths() {
  const view = current();
  const needs = typeof view.needs === "function" ? view.needs(context) : view.needs || [];
  return [...ALWAYS, ...needs, ...extra];
}

function paint() {
  const view = current();
  document.getElementById("viewTitle").textContent = view.title;
  render(document.getElementById("view"), view.render(context));
  paintDrawer();
}

async function tick(force) {
  await api.pull(paths(), Boolean(force));
  const access = api.resource("/api/access").data;
  if (access) {
    api.access.writable = access.writable !== false;
    api.access.reason = access.reason || "";
    api.access.loopback = access.loopback !== false;
    api.access.checked = true;
    document.body.classList.toggle("readonly", !api.access.writable);
  }
  const ids = api.resource("/api/identities").data;
  if (ids) identity.setRegistry(ids);
  fillProjects();
  const label = document.getElementById("freshness");
  const at = api.oldestAt(paths());
  label.textContent = at == null ? "Not yet" : "Live";
  paint();
}

function route() {
  const raw = (location.hash || "#/queue").replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const id = path.split("/")[0] || "queue";
  if (!VIEWS.has(id)) return;
  if (id !== state.view) { extra.clear(); closeDrawer(); }
  state.view = id;
  state.params = new URLSearchParams(query);
  for (const link of document.querySelectorAll(".navlink")) {
    if (link.getAttribute("href") === "#/" + id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  paint();
  tick(true);
}

/* The real shell fills this select from the project registry and narrows the page to the one
   picked. The harness does the same, so a view can be measured with the header set. */
const projectFilter = document.getElementById("projectFilter");
projectFilter.addEventListener("change", () => { state.project = projectFilter.value; paint(); });

function fillProjects() {
  const data = api.resource("/api/projects").data;
  const names = (Array.isArray(data) ? data : []).map((row) => row && row.name).filter(Boolean);
  if (projectFilter.dataset.names === names.join("|")) return;
  projectFilter.dataset.names = names.join("|");
  projectFilter.replaceChildren();
  for (const [value, label] of [["", "All projects"], ...names.map((name) => [name, name])]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    projectFilter.append(option);
  }
  projectFilter.value = state.project;
}

document.getElementById("drawerClose").addEventListener("click", () => { closeDrawer(); paint(); });
document.getElementById("drawerScrim").addEventListener("click", () => { closeDrawer(); paint(); });
window.addEventListener("hashchange", route);
route();
setInterval(tick, 3000);
</script>
</body>
</html>
"""


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
        if path == "/harness":
            body = HARNESS.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
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
            # A body with no port block is a person leaving the field empty, and the farm
            # hands out the next free one itself. The real server does the same, which is why
            # the page must send nothing rather than a number of its own.
            base = body.get("port_base")
            if base in (None, ""):
                base = max([row["ports"]["web"]
                            for row in PROJECTS + SENT["projects"]] or [5190]) + 10
            base = int(base)
            row = {"name": body["name"], "repo": body["repo"], "path": f"/home/farm/work/{body['name']}",
                   "base_branch": "main", "ports": {"web": base, "api": 8100, "e2e": 9100},
                   "lanes_open": 0, "last_activity": time.time()}
            SENT["projects"].append(row)
            # The real server clones the repository, so it answers with a job (amendment 7).
            job = job_new("add_project", f"registering {body['name']}", seconds=2)
            return self._json(202, {"job": job})
        if parsed.path in ("/api/models/discover", "/api/models/select"):  # stub_models.py
            return self._json(*__import__("stub_models").post(parsed.path, body, models_now()))
        if parsed.path == "/api/models/add":
            return self._json(*self._model_add(body))
        if parsed.path == "/api/models/remove":
            wanted = str(body.get("id") or "").strip()
            row = next((item for item in models_now() if item["id"] == wanted), None)
            if row is None:
                return self._json(404, {"error": f"no such model: {wanted}"})
            # Any row this farm added, fixture or not, and never one that came with fleet: the
            # two sentences are lib/models.py's own.
            if row.get("source") != "added":
                return self._json(400, {"error": f"{wanted} came with fleet: switch it off here, "
                                                 "or edit this farm's models.toml by hand"})
            if row in SENT["models"]:
                SENT["models"].remove(row)
            SENT["removed"].append(wanted)
            return self._json(200, {"ok": True, "removed": wanted})
        if parsed.path in ("/api/mode", "/api/models"):
            # Only a model this run added is mutated here. The five fixture rows are one per
            # status on purpose, and a check that pressed a switch must not rewrite the table
            # every later check reads.
            mine = next((item for item in SENT["models"]
                         if item["id"] == str(body.get("id") or "")), None)
            action = str(body.get("action") or "")
            if mine is not None and action in ("enable", "disable", "test"):
                if action == "test":
                    mine["last_test"] = time.time()
                    mine["health"] = "ok"
                    mine["health_detail"] = ""
                    if mine["status"] == "failing":
                        mine["status"] = "on" if mine["enabled"] else "off"
                elif mine["status"] in ("on", "off"):
                    mine["enabled"] = action == "enable"
                    mine["status"] = "on" if mine["enabled"] else "off"
            return self._json(200, {"ok": True})
        if parsed.path == "/api/services":
            service = body.get("service", "")
            action = body.get("action", "")
            row = next((item for item in SERVICE_ROWS if item["id"] == service), None)
            if row is None:
                return self._json(404, {"error": f"there is no service called {service or 'that'}"})
            if row.get("read_only"):
                return self._json(403, {"error": "the dashboard does not stop or restart itself "
                                                 "from this page"})
            if action not in row["actions"]:
                return self._json(400, {"error": f"{service} takes one of "
                                                 f"{', '.join(row['actions'])}"})
            return self._json(200, {"ok": True, "service": service, "action": action,
                                    "state": "inactive" if action == "stop" else "active"})
        if parsed.path == "/api/agents/kill":
            slug = body.get("slug", "")
            if not any(row["slug"] == slug for row in AGENTS + LONG_AGENTS):
                return self._json(404, {"error": "there is no lane with that name"})
            return self._json(200, {"ok": True, "slug": slug, "retire": bool(body.get("retire"))})
        if parsed.path == "/api/power":
            action = body.get("action", "")
            if action not in ("throttle", "drain", "resume"):
                return self._json(400, {"error": "an action is one of throttle, drain, resume"})
            detail = {"throttle": "capping the farm and stopping new agents",
                      "drain": "salvaging and stopping every lane",
                      "resume": "starting the agent runner again"}[action]
            return self._json(200, {"ok": True,
                                    "job": job_new(action, detail, fails=self.state() == "error")})
        if parsed.path == "/api/ci/enqueue":
            project = str(body.get("project", "")).strip()
            number = body.get("pr")
            try:
                number = int(number)
            except (TypeError, ValueError):
                number = 0
            if not project or number <= 0:
                return self._json(400, {"error": "a verification needs a project and the number "
                                                 "of a change"})
            # One number the runner always refuses, so a failed job can be seen on purpose.
            fails = number == 999
            return self._json(200, {"ok": True, "job": job_new(
                "verify a change", f"{project} #{number}", fails=fails)})
        if parsed.path == "/api/ci/cancel":
            wanted = str(body.get("id", ""))
            known = [row["id"] for bucket in ("running", "queued", "recent")
                     for row in QUEUE[bucket]]
            if wanted not in known:
                return self._json(404, {"error": "there is no run with that id"})
            return self._json(200, {"ok": True, "id": wanted})
        if parsed.path == "/api/accounts/add":
            engine = (body.get("engine") or "claude").strip()
            if engine == "codex":
                return self._json(200, {
                    "name": "codex", "engine": "codex",
                    "command": "ssh -L 1455:localhost:1455 -t farm codex login",
                    "steps": ["codex is one shared account: this logs it in again",
                              "Run the command from wherever you reach this farm",
                              "A browser opens, authorize with your account",
                              "Wait for the words Successfully logged in",
                              "Come back here"]})
            name = (body.get("name") or "").strip()
            if not name or not all(part.isalnum() or part in "._-" for part in name):
                return self._json(400, {"error": "an account name is letters, digits, a dot, "
                                                 "a dash or an underscore"})
            ADDED_ACCOUNTS[name] = time.time()
            return self._json(200, {
                "name": name, "engine": engine,
                "command": f"ssh -t farm 'CLAUDE_CONFIG_DIR=$HOME/.fleet/claude-accounts/{name} claude'",
                "steps": ["Run the command from wherever you reach this farm",
                          "In the engine's window type /login",
                          "Choose the account with a subscription",
                          "Open the address, authorize, paste the code back",
                          "Type /exit"]})
        if parsed.path == "/api/accounts/remove":
            name = (body.get("name") or "").strip()
            known = [row["name"] for row in ACCOUNTS["accounts"]] + list(ADDED_ACCOUNTS)
            if name not in known:
                return self._json(404, {"error": "there is no account with that name"})
            ADDED_ACCOUNTS.pop(name, None)
            return self._json(200, {"ok": True, "name": name,
                                    "backup": f"/home/farm/.fleet/dead-account-backups/{name}.wiped"})
        if parsed.path == "/api/accounts/refresh":
            return self._json(200, {"ok": True, "at": iso(),
                                    "accounts": len(ACCOUNTS["accounts"])})
        if parsed.path == "/api/projects/remove":
            name = (body.get("name") or "").strip()
            row = next((item for item in PROJECTS + SENT["projects"] if item["name"] == name), None)
            if row is None:
                return self._json(404, {"error": "there is no project with that name"})
            if row.get("lanes_open"):
                return self._json(409, {"error": f"{name} has {row['lanes_open']} open lanes. "
                                                 "Stop them first, then remove the project."})
            # The dev server block alone, under the server's own key. api and e2e are shared
            # across every project here and are not this one's to free.
            web = (row.get("ports") or {}).get("web")
            freed = f"{web} to {web + 99}" if web else ""
            return self._json(200, {"ok": True, "name": name, "freed": freed,
                                    "port_base": web,
                                    "sentence": f"{name} is no longer registered. Its dev "
                                                f"server port block, {freed}, is free for the "
                                                "next project."})
        if parsed.path.startswith("/api/machines") or parsed.path.startswith("/api/hosts"):
            return self._json(*self._hosting(parsed.path, body))
        return self._json(404, {"error": "not found"})

    def _hosting(self, path, body):
        """The writes of design section 7, with the refusals the real server makes.

        Every one of them answers 202 with a job, except plan, which is read-only and answers
        at once. A body carrying a credential by any name is refused before anything else, so a
        page that started asking for one fails here rather than on a farm."""
        named = key_field(body)
        if named:
            return 400, {"error": f"{named}: {SECRET_REFUSAL}"}
        # Every string in the body, before any other refusal and before a plan is drawn from it:
        # a token pasted into the wrong field is refused without being repeated anywhere.
        if any(isinstance(value, str) and TOKEN_SHAPES.search(value) for value in body.values()):
            return 400, {"error": f"that value looks like a token: {SECRET_REFUSAL}"}
        if path == "/api/machines/plan":
            return machine_plan(body)
        if path == "/api/machines":
            return self._machine_create(body)
        name = str(body.get("name") or "").strip()
        if path in ("/api/machines/check", "/api/machines/destroy", "/api/machines/adopt",
                    "/api/machines/forget"):
            row = machine_named(name)
            if row is None:
                return 404, {"error": f"there is no machine called {name or 'that'}"}
            if path == "/api/machines/destroy":
                if str(body.get("confirm") or "") != name:
                    return 400, {"error": "a destroy is confirmed by typing the machine's name"}
                if row["provider"] == "ssh":
                    return 400, {"error": "a machine of your own is forgotten, never destroyed"}
                row["state"] = "destroyed"
                row["detail"] = "destroyed from the dashboard; nothing is billed for it"
                row["checked_at"] = time.time()
                return 202, {"job": job_new("destroy machine", f"deleting {name}")}
            if path == "/api/machines/adopt":
                if row["state"] != "unrecorded":
                    return 400, {"error": "only a droplet this farm does not have a row for is "
                                          "adopted"}
                row["state"] = "needs-login"
                row["detail"] = "adopted from the provider's own facts"
                row["finish_command"] = FINISH_TEMPLATE.format(address=row["address"])
                row["checked_at"] = time.time()
                return 202, {"job": job_new("adopt machine", f"writing the row for {name}")}
            if path == "/api/machines/forget":
                forgettable = (row["state"] == "destroyed" or row["provider"] == "ssh"
                               or (row["state"] == "failed" and not row["provider_id"]))
                if not forgettable:
                    return 400, {"error": f"{name} still exists at the provider: destroy it "
                                          "rather than forgetting it"}
                if row in MACHINES:
                    MACHINES.remove(row)
                if row in SENT["machines"]:
                    SENT["machines"].remove(row)
                return 202, {"job": job_new("forget machine", f"dropping the row for {name}")}
            row["checked_at"] = time.time()
            if row["state"] == "unreachable":
                row["state"] = "ready"
                row["detail"] = "fleet capacity answered"
            return 202, {"job": job_new("check machine", f"ssh to {name}")}
        provider = str(body.get("provider") or "").strip()
        preset = next((row for row in HOST_PRESETS if row["id"] == provider), None)
        if preset is None:
            return 404, {"error": f"there is no provider called {provider or 'that'}"}
        if path == "/api/hosts/check":
            return 202, {"job": job_new("check host", f"asking {provider} who this farm is")}
        if path == "/api/hosts/test":
            if body.get("confirm") is not True:
                return 400, {"error": "a test starts a real sandbox and costs money: it needs "
                                      "confirm"}
            project = str(body.get("project") or "").strip()
            if not project:
                return 400, {"error": "a test needs the project whose repository it clones"}
            TESTS[provider] = {"at": time.time(), "project": project}
            return 202, {"job": job_new("test runner", f"starting a {provider} sandbox")}
        return 404, {"error": f"the stub does not serve {path}"}

    def _machine_create(self, body):
        """POST /api/machines: the row is written before the provider is called, so a droplet
        can never exist without one (design section 4)."""
        provider = str(body.get("provider") or "").strip()
        name = str(body.get("name") or "").strip()
        if provider not in ("do-droplet", "ssh"):
            return 400, {"error": "a machine runs on do-droplet or on ssh"}
        # The rule, never the rejected value: a refusal is printed on the page, and the value may
        # be a token pasted into the wrong field.
        if not MACHINE_NAME_RE.match(name):
            return 400, {"error": MACHINE_NAME_RULE}
        live = machine_named(name)
        if live is not None and live["state"] != "destroyed":
            return 400, {"error": f"there is already a machine called {name}"}
        if provider == "ssh":
            target = str(body.get("target") or "").strip()
            if not TARGET_RE.match(target):
                return 400, {"error": "a target reads user@host"}
            port = body.get("port")
            if port not in (None, "") and not str(port).isdigit():
                return 400, {"error": "a port is a whole number"}
            user, _, address = target.partition("@")
            row = {"name": name, "provider": "ssh", "user": user, "address": address,
                   "size": "", "monthly_usd": 0, "region": "", "state": "ready",
                   "detail": "registered from the dashboard", "checked_at": time.time(),
                   "provider_id": None, "finish_command": "",
                   "tunnel_command": TUNNEL_TEMPLATE.format(address=address),
                   "created_at": time.time()}
            SENT["machines"].append(row)
            return 202, {"job": job_new("add machine", f"checking ssh to {target}")}
        size = size_named(str(body.get("size") or ""))
        if size is None:
            return 400, {"error": "that is not a size this provider sells"}
        if not str(body.get("region") or "").strip():
            return 400, {"error": "a droplet needs a region"}
        public = str(body.get("ssh_public") or "").strip()
        # The refusal never repeats the value: a sentence that echoes a token has leaked it.
        if TOKEN_SHAPES.search(public):
            return 400, {"error": f"that value looks like a token, not a public key: "
                                  f"{SECRET_REFUSAL}"}
        if not PUBLIC_KEY_RE.match(public):
            return 400, {"error": "a public key is one line of ssh-ed25519, ssh-rsa or "
                                  "ecdsa-sha2"}
        if float(body.get("confirm_usd") or 0) != float(size["monthly_usd"]):
            return 400, {"error": f"the price you confirmed is not the live price, which is "
                                  f"${size['monthly_usd']} a month"}
        row = {"name": name, "provider": "do-droplet", "user": "farm", "address": "",
               "size": size["slug"], "monthly_usd": size["monthly_usd"],
               "region": str(body.get("region")), "state": "creating",
               "detail": "the row is written; the provider has not answered yet",
               "checked_at": time.time(), "provider_id": None, "finish_command": "",
               "tunnel_command": "", "created_at": time.time()}
        SENT["machines"].append(row)
        return 202, {"job": job_new("create machine", f"asking DigitalOcean for {name}")}

    def _model_add(self, body):
        """POST /api/models/add: the farm's catalog gains one entry, written from a preset.

        A key never arrives here. The dialog sends the name of the environment variable and
        nothing else, and a body carrying a key is refused with that sentence, so a page that
        started asking for one would fail this stub before it reached a farm."""
        mid = str(body.get("id") or "").strip()
        shown = mid if MODEL_ID_RE.match(mid) else "<id>"
        if key_field(body):
            return 400, {"error": KEY_REFUSAL.format(id=shown)}
        for field in ("bin", "run"):
            if key_in_command(body.get(field)):
                return 400, {"error": KEY_IN_COMMAND.format(id=shown)}
        presets = {row["id"]: row for row in MODEL_PRESETS}
        preset = str(body.get("preset") or "").strip()
        if preset not in presets:
            return 400, {"error": f"there is no preset called {preset or 'that'}"}
        base = presets[preset]
        if not MODEL_ID_RE.match(mid):
            # The farm's own rule and the farm's own sentence: a stub that took a name the
            # server refuses lets a page ship a rule nothing behind it keeps.
            return 400, {"error": f"{MODEL_ID_RULE}: {mid!r} is not one" if mid else MODEL_ID_RULE}
        if any(row["id"] == mid for row in models_now()):
            return 400, {"error": f"{mid} is already in this farm's catalog"}
        run = str(body.get("run") or base["run"]).strip()
        binary = str(body.get("bin") or base["bin"]).strip()
        if preset == "custom" and (not binary or not run):
            return 400, {"error": "a custom command needs the command and the line that runs it"}
        # A custom command is called what the person called it. "Custom command" is the name of
        # the CARD, not of a farm's own command: two of them would be two identical rows,
        # separable only by the mono id under the name. model_presets.entry_from() hands the
        # naming over for that preset and models.add_model() falls back to the id.
        label = str(body.get("label") or "").strip()
        if not label:
            label = mid if preset == "custom" else base["label"]
        variant = str(body.get("variant") or "").strip()
        if base["variants"] and variant not in base["variants"]:
            variant = base["variants"][0]
        # A key preset with no key pasted yet is exactly that, and says so in the table.
        status = "needs_key" if base["kind"] == "key" and preset != "custom" else "off"
        # Exactly the fields model_presets.ENTRY_FIELDS carries into a catalog entry, plus what
        # engine_row() adds on top. No role, quality, caps or docs: the add route writes none of
        # them, so a page that leaned on any of them would be leaning on this stub alone.
        row = {
            "id": mid, "label": label, "color": base["color"],
            "engine": base["engine"], "bin": binary, "run": run,
            "install_hint": base["install_hint"] or f"install {binary}",
            "auth_env": str(body.get("auth_env") or base["auth_env"]),
            "tos": base["tos"], "access": base["access"],
            "preset": preset, "source": "added", "variant": variant,
            "health": "unchecked", "health_prompt": base["health"], "health_detail": "",
            "limits": "", "enabled": False, "routable": False, "status": status,
            "command": binary, "installed": True,
            "path": f"/home/farm/.local/bin/{binary or mid}", "last_test": None,
        }
        SENT["models"].append(row)
        # The envelope the server uses: {"model": row}, so the page reads the answer the farm
        # gives it and not a shape only this stub ever had.
        return 200, {"model": row}

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


__import__("stub_github").install(globals())  # the GitHub routes: stub_github.py


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("127.0.0.1", PORT), Handler) as server:
        threading.current_thread().name = "stub"
        server.serve_forever()
