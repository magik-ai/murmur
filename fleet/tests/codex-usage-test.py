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

# A payload whose windows do not give their length: each keeps the slot its position suggests.
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
check("an unsized primary window reads as the weekly one", s["weekly"]["percent"] == 12)
check("an unsized secondary window reads as the session one", s["session"]["percent"] == 40)
check("reset_at unix -> ISO string", s["weekly"]["resets"].startswith("2026-"))

# the common case: secondary window null until the burst window is in use
payload2 = {"plan_type": "team", "rate_limit": {"limit_reached": False,
            "primary_window": {"used_percent": 0, "reset_at": 1787038998},
            "secondary_window": None}}
s2 = cx.summarize(payload2)
check("a null secondary window is tolerated, not crashed", s2["session"] is None)
check("limit_reached surfaces", cx.summarize({"rate_limit": {"limit_reached": True}})["limit_reached"] is True)

# The windows are told apart by limit_window_seconds, never by position: here the 5-hour window
# is the primary one and the weekly window the secondary one.
payload3 = {"plan_type": "plus", "rate_limit": {"limit_reached": False,
            "primary_window": {"used_percent": 30, "limit_window_seconds": 18000,
                               "reset_at": 1787000000},
            "secondary_window": {"used_percent": 55, "limit_window_seconds": 604800,
                                 "reset_at": 1787500000}}}
s3 = cx.summarize(payload3)
check("a 5-hour primary window is the session window",
      s3["session"]["percent"] == 30 and s3["weekly"]["percent"] == 55)
_read_usage = cx.read_usage
cx.read_usage = lambda: payload3
_row = cx.snapshot_row()
cx.read_usage = _read_usage
check("and the tile shows its percent as the session, the 7-day one as the week",
      (_row["session"], _row["weekly"]) == (30, 55)
      and _row["session_resets"].startswith("2026-") and _row["weekly_resets"].startswith("2026-"))
# A plan with only a weekly limit: one 7-day window, in the primary slot or the secondary one.
for _key in ("primary_window", "secondary_window"):
    _only = cx.summarize({"rate_limit": {_key: {"used_percent": 7, "limit_window_seconds": 604800}}})
    check(f"a lone 7-day window in {_key} is the weekly one",
          _only["weekly"]["percent"] == 7 and _only["session"] is None)



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
