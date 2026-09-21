#!/usr/bin/env python3
"""Pin codex usage parsing on fixtures — the real endpoint shapes, both windows and the null case."""
import os, sys, pathlib
# FLEET_HOME, else the checkout this file lives in (see tests/salvage-test.py).
FLEET_HOME = pathlib.Path(os.environ.get("FLEET_HOME") or pathlib.Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(FLEET_HOME / "lib"))
import codex_usage as cx

ok = True
def check(n, c):
    global ok
    print(("  PASS " if c else "  FAIL ") + n); ok = ok and c

# the exact shape the live endpoint returned
payload = {
    "plan_type": "team",
    "rate_limit": {
        "allowed": True, "limit_reached": False,
        "primary_window": {"used_percent": 12, "reset_at": 1787038998},
        "secondary_window": {"used_percent": 40, "reset_at": 1786450000},
    },
}
s = cx.summarize(payload)
check("plan parsed", s["plan"] == "team")
check("primary (weekly) percent parsed", s["primary"]["percent"] == 12)
check("secondary (5h) percent parsed", s["secondary"]["percent"] == 40)
check("reset_at unix -> ISO string", s["primary"]["resets"].startswith("2026-"))

# the common case: secondary window null until the burst window is in use
payload2 = {"plan_type": "team", "rate_limit": {"limit_reached": False,
            "primary_window": {"used_percent": 0, "reset_at": 1787038998},
            "secondary_window": None}}
s2 = cx.summarize(payload2)
check("a null secondary window is tolerated, not crashed", s2["secondary"] is None)
check("limit_reached surfaces", cx.summarize({"rate_limit": {"limit_reached": True}})["limit_reached"] is True)



# A transient 403 must hold the last-good tile, not blank it to unreadable (the CI-pane defect).
_prev = {"codex": {"name": "codex", "engine": "codex", "read_at": 111, "weekly": 0, "session": None}}
_err = {"name": "codex", "engine": "codex", "read_at": None, "session": None, "weekly": None,
        "stale_error": "HTTP 403"}
_held = cx.merge_row(_err, _prev)
check("a transient codex error holds last-good numbers, marked stale",
      _held["weekly"] == 0 and _held["read_at"] == 111 and _held["stale_error"] == "HTTP 403")
check("a codex error with no prior passes through (no phantom good data)",
      cx.merge_row(_err, {}).get("read_at") is None)
check("a clean codex read is returned unchanged",
      cx.merge_row({"weekly": 5, "read_at": 9}, _prev)["weekly"] == 5)

print("\nRESULT: " + ("ALL PASS" if ok else "FAILURES"))
sys.exit(0 if ok else 1)
