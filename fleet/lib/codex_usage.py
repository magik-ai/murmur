#!/usr/bin/env python3
"""Read the ChatGPT/codex subscription limits the farm spawns against.

Codex exposes its usage through an undocumented endpoint, shaped differently from Anthropic's:
`https://chatgpt.com/backend-api/codex/usage` with the CLI's own access token returns a
`rate_limit` block with a primary and a secondary window. Each window gives its length in
`limit_window_seconds`: 5 hours (18000 s) for the session window, 7 days (604800 s) for the
weekly one. Which of the two is primary is not fixed, so the windows are told apart by their
length, never by their position. Either can be null. Codex is a single subscription under
`~/.codex/auth.json`, with no per-account files like Claude's.

The token never leaves this process; only percentages and reset times are surfaced.
"""
import base64
import json
import os
import time
import urllib.request
import urllib.error

AUTH = os.path.expanduser(os.environ.get("CODEX_AUTH", "~/.codex/auth.json"))
USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"


def _access_token_and_account():
    with open(AUTH) as handle:
        auth = json.load(handle)
    tokens = auth.get("tokens") or {}
    return tokens.get("access_token"), tokens.get("account_id", "")


def token_expiry():
    """Unix seconds when the codex access token expires, or None."""
    try:
        access, _ = _access_token_and_account()
        mid = access.split(".")[1]
        mid += "=" * (-len(mid) % 4)
        return json.loads(base64.urlsafe_b64decode(mid)).get("exp")
    except Exception:
        return None


def read_usage():
    """The raw usage payload from the codex backend, or raise with a short reason."""
    access, account = _access_token_and_account()
    if not access:
        raise RuntimeError("no access token in ~/.codex/auth.json")
    request = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {access}",
        "chatgpt-account-id": account,
        "User-Agent": "codex-cli",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())


def _window(win):
    if not win:
        return None
    pct = win.get("used_percent")
    reset_at = win.get("reset_at")
    return {
        "percent": round(pct) if isinstance(pct, (int, float)) else None,
        # codex gives reset_at as a unix second; normalise to the ISO the dashboard countdown wants
        "resets": (time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(reset_at))
                   if isinstance(reset_at, (int, float)) else None),
    }


# A window of at most a day is the session window (5 hours today); a longer one is the weekly one.
SESSION_MAX_SECONDS = 24 * 3600


def _slot(win, guess):
    """"session" or "weekly" for one window, by its limit_window_seconds.

    A window that does not give its length keeps the slot its position suggests (`guess`)."""
    seconds = win.get("limit_window_seconds")
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0:
        return "session" if seconds <= SESSION_MAX_SECONDS else "weekly"
    return guess


def summarize(usage=None):
    """{plan, session, weekly, limit_reached} out of the payload, shaped for a tile.

    session is the 5-hour window and weekly the 7-day one, each None when the payload has no
    such window.
    """
    usage = usage if usage is not None else read_usage()
    rl = usage.get("rate_limit") or {}
    placed = {"session": None, "weekly": None}
    for key, guess in (("primary_window", "weekly"), ("secondary_window", "session")):
        win = rl.get(key)
        if isinstance(win, dict):
            slot = _slot(win, guess)
            if placed[slot] is None:
                placed[slot] = _window(win)
    return {
        "plan": usage.get("plan_type"),
        "session": placed["session"],
        "weekly": placed["weekly"],
        "limit_reached": bool(rl.get("limit_reached")),
    }


def merge_row(fresh: dict, previous: dict) -> dict:
    """Hold last-good codex numbers on a transient error rather than blanking the tile.

    A single 403 from chatgpt.com (anti-bot / momentary) otherwise renders identically to
    "the account is gone". Mirrors the last-good merge the claude tiles already do.
    """
    if fresh.get("stale_error") and previous and "codex" in previous:
        held = dict(previous["codex"])
        held["stale_error"] = fresh["stale_error"]
        return held
    return fresh


def snapshot_row():
    """One dashboard row for codex, matching the account-tile contract, or an error row."""
    try:
        s = summarize()
    except urllib.error.HTTPError as exc:
        return {"name": "codex", "label": "codex", "engine": "codex",
                "stale_error": f"HTTP {exc.code}", "read_at": None,
                "session": None, "weekly": None}
    except Exception as exc:
        return {"name": "codex", "label": "codex", "engine": "codex",
                "stale_error": f"{type(exc).__name__}", "read_at": None,
                "session": None, "weekly": None}
    session, weekly = s["session"] or {}, s["weekly"] or {}
    return {
        "name": "codex", "label": "codex", "engine": "codex", "read_at": time.time(),
        # the same keys the Claude tiles use, so the page draws both in one row
        "session": session.get("percent"), "session_resets": session.get("resets"),
        "weekly": weekly.get("percent"), "weekly_resets": weekly.get("resets"),
        "plan": s["plan"], "limit_reached": s["limit_reached"],
    }


REFRESH_MARGIN_SECONDS = 6 * 3600  # codex token lives ~50h; warn well before it lapses


def keepalive(now=None):
    """Report codex token health. Never auto-exec: a proactive exec against a shaky token can
    trigger a login flow that, if it does not complete, wipes the auth entirely (learned the hard
    way). A codex lane spawning through this account refreshes the token on its own; if none has,
    the fix is an interactive `codex login --device-auth`.
    """
    import time as _t
    now = now if now is not None else _t.time()
    exp = token_expiry()
    if exp is None:
        return "codex: not logged in — run `codex login --device-auth`"
    left = (exp - now) / 3600
    if left <= 0:
        return "codex: token EXPIRED — run `codex login --device-auth`"
    if left <= REFRESH_MARGIN_SECONDS / 3600:
        return f"codex: token low ({left:.1f}h) — spawn a codex lane to refresh, or re-login"
    return f"codex: fresh ({left:.1f}h left)"


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["json"]:
        print(json.dumps(snapshot_row(), indent=2))
    else:
        s = summarize()
        weekly, session = s["weekly"] or {}, s["session"] or {}
        print(f"  codex ({s['plan']}): weekly {weekly.get('percent')}%  "
              f"5h {session.get('percent') if session else '—'}%"
              + ("  LIMIT REACHED" if s["limit_reached"] else ""))
