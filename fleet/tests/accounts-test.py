#!/usr/bin/env python3
"""Pin the account-picking rules on fixture payloads.

The picker decides which subscription a lane burns, and the pool it must never silently drain is
the owner's own working session. So both directions are pinned: a full account must not be picked,
and a picker too eager to skip would strand lanes with headroom available.

Fixtures mirror the real /api/oauth/usage `limits` array — the same shapes the endpoint returned
when this was built, including the scoped-promo case (one model at 96% while the account is fine).
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "lib"))
import claude_accounts as ca  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("  PASS " if cond else "  FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))
    ok = ok and cond


def payload(session, weekly, scoped=()):
    limits = [
        {"kind": "session", "group": "session", "percent": session, "is_active": False,
         "resets_at": "2026-08-10T17:50:00+00:00"},
        {"kind": "weekly_all", "group": "weekly", "percent": weekly, "is_active": False,
         "resets_at": "2026-08-11T22:00:00+00:00"},
    ]
    for label, pct, active in scoped:
        limits.append({"kind": "weekly_scoped", "group": "weekly", "percent": pct,
                       "is_active": active,
                       "scope": {"model": {"display_name": label}, "surface": None}})
    return {"limits": limits}


# 1. lowest weekly headroom wins
s = {"a": ca.summarize(payload(10, 70)), "b": ca.summarize(payload(10, 20))}
check("the account with the most weekly headroom wins", ca.pick_from(s) == "b")

# 2. a full weekly window disqualifies, even at zero session
s = {"full": ca.summarize(payload(0, 97)), "half": ca.summarize(payload(50, 50))}
check("an account at >=95% weekly is never picked", ca.pick_from(s) == "half")

# 3. a full session window disqualifies, even with weekly headroom
s = {"burst": ca.summarize(payload(96, 10)), "calm": ca.summarize(payload(30, 60))}
check("an account at >=95% session is never picked", ca.pick_from(s) == "calm")

# 4. a scoped promo limit (one model critical) does NOT disqualify the whole account
s = {"promo": ca.summarize(payload(0, 51, scoped=[("Fable", 96, True)]))}
check("a critical scoped limit alone does not sink the account", ca.pick_from(s) == "promo")

# 5. nothing has headroom -> nothing is picked, loudly None
s = {"a": ca.summarize(payload(96, 10)), "b": ca.summarize(payload(10, 96))}
check("no headroom anywhere yields None, not a bad pick", ca.pick_from(s) is None)

# 6a. reset times ride along with the percents - the tiles answer "how long until this
# number stops mattering", and a summary that drops them cannot
s = ca.summarize(payload(10, 70))
check("reset times survive summarize",
      s["session_resets"] == "2026-08-10T17:50:00+00:00"
      and s["weekly_resets"] == "2026-08-11T22:00:00+00:00")

# 6. an unreadable account is simply absent (collect() drops it) - picker works with the rest
s = {"alive": ca.summarize(payload(20, 30))}
check("picking works when other accounts failed to read", ca.pick_from(s) == "alive")

# 7. rotation: a batch spreads across every account with headroom instead of piling on one
import tempfile, os
state = os.path.join(tempfile.mkdtemp(), "last")
s3 = {"a": ca.summarize(payload(10, 30)), "b": ca.summarize(payload(10, 60)),
      "c": ca.summarize(payload(10, 10))}
seq = [ca.rotate_pick(s3, state) for _ in range(6)]
check("auto rotates through every eligible account", seq == ["a","b","c","a","b","c"], str(seq))

# 8. a full account drops out of the rotation and the rest keep cycling
s4 = {"a": ca.summarize(payload(10, 96)), "b": ca.summarize(payload(10, 60)),
      "c": ca.summarize(payload(10, 10))}
state2 = os.path.join(tempfile.mkdtemp(), "last")
seq = [ca.rotate_pick(s4, state2) for _ in range(4)]
check("a full account is skipped by the rotation", seq == ["b","c","b","c"], str(seq))

# 9. one account left -> rotation degenerates to it, not to None
s5 = {"a": ca.summarize(payload(10, 96)), "b": ca.summarize(payload(97, 10)),
      "c": ca.summarize(payload(10, 10))}
state3 = os.path.join(tempfile.mkdtemp(), "last")
seq = [ca.rotate_pick(s5, state3) for _ in range(3)]
check("a single survivor takes every spawn", seq == ["c","c","c"], str(seq))


# 10. keepalive decides to ping ONLY inside the refresh margin — a healthy token costs nothing,
# an expired one gets refreshed. Both directions, because a keepalive that always pings would burn
# quota and one that never pings would let tokens die (which is the bug it exists to prevent).
import tempfile, os, json, time
d = tempfile.mkdtemp()
def acct(name, hours):
    a = os.path.join(d, name); os.makedirs(a)
    json.dump({"claudeAiOauth": {"expiresAt": int((time.time()+hours*3600)*1000),
                                  "accessToken": "x"}},
              open(os.path.join(a, ".credentials.json"), "w"))
    return a
fresh = acct("fresh", 7); near = acct("near", 1); dead = acct("dead", -2)
check("token_expiry reads a fresh token as hours away",
      ca.token_expiry(fresh) - time.time() > 6*3600)
check("a token well inside its life is not pinged",
      (ca.token_expiry(fresh) - time.time()) > ca.REFRESH_MARGIN_SECONDS)
check("a token near expiry IS pinged",
      (ca.token_expiry(near) - time.time()) <= ca.REFRESH_MARGIN_SECONDS)
check("an expired token IS pinged",
      (ca.token_expiry(dead) - time.time()) <= ca.REFRESH_MARGIN_SECONDS)
check("keepalive never pings with fable — it burns its own scoped window",
      ca.KEEPALIVE_MODEL != "fable")


# 11. balance() spreads a batch across all four subscriptions (3 claude + codex), round-robin,
# skipping any that is full or unavailable. The engine is returned with the account because the
# two engines are not interchangeable per lane.
import tempfile as _tf, os as _os
_bs = _os.path.join(_tf.mkdtemp(), "bal")
# stub the collect + codex candidate the balancer reads
_orig_collect = ca.collect
_orig_codex = ca._codex_candidate
ca.collect = lambda: ({"a": ca.summarize(payload(10, 20)), "b": ca.summarize(payload(10, 30))}, {})
ca._codex_candidate = lambda: ("codex", "codex", 5)
_nocache = _os.path.join(_tf.mkdtemp(), "none.json")  # forces the cold-cache live fallback
seq = [ca.balance(_bs, _nocache) for _ in range(6)]
check("balance round-robins claude accounts AND codex",
      seq == [("claude","a"),("claude","b"),("codex","codex"),
              ("claude","a"),("claude","b"),("codex","codex")], str(seq))
# codex at its limit drops out; the claude accounts keep cycling
ca._codex_candidate = lambda: None
_bs2 = _os.path.join(_tf.mkdtemp(), "bal2")
seq = [ca.balance(_bs2, _nocache) for _ in range(4)]
check("a maxed/unavailable codex is skipped, claude keeps balancing",
      seq == [("claude","a"),("claude","b"),("claude","a"),("claude","b")], str(seq))
ca.collect = _orig_collect; ca._codex_candidate = _orig_codex


# 12. cache-backed balance: with a warm cache, balance() must NOT touch the network — reading three
# tokens per call in a burst is what trips the endpoint's frequency 429. Sabotage collect() so any
# live read blows up; a green run proves balance stayed offline.
import json as _json, time as _time
_cdir = _tf.mkdtemp()
_cache = _os.path.join(_cdir, "cache.json"); _cst = _os.path.join(_cdir, "st")
def _wc(rows): _json.dump({"at": _time.time(), "accounts": rows}, open(_cache, "w"))
_boom = _orig_collect
ca.collect = lambda: (_ for _ in ()).throw(AssertionError("balance hit the network"))
_wc([{"name":"default","session":2,"weekly":57},
     {"name":"spare-one","session":0,"weekly":53},
     {"name":"spare-two","session":72,"weekly":53},
     {"name":"codex","engine":"codex","session":None,"weekly":0,"limit_reached":False}])
_p = [ca.balance(_cst, _cache) for _ in range(8)]
check("cache-backed balance round-robins all four with zero network",
      len(set(_p)) == 4 and ("codex","codex") in set(_p) and _p[:4] == _p[4:8], str(_p))
_wc([{"name":"default","session":2,"weekly":57},
     {"name":"spare-two","session":72,"weekly":53,"stale_error":"429 rate-limited"},
     {"name":"codex","engine":"codex","session":None,"weekly":0}])
_os.remove(_cst)
_p = set(ca.balance(_cst, _cache) for _ in range(6))
check("cache-backed balance skips a throttled/expired row",
      _p == {("claude","default"),("codex","codex")}, str(_p))
_stale = _os.path.join(_cdir, "stale.json")
_json.dump({"at": _time.time()-4000, "accounts":[{"name":"default","session":1,"weekly":1}]}, open(_stale,"w"))
check("a stale cache is refused so balance falls back to a live read",
      ca._wheel_from_cache(_stale) is None)
check("a missing cache is refused (cold start)",
      ca._wheel_from_cache(_os.path.join(_cdir,"nope.json")) is None)
ca.collect = _boom

# resolve_auto: what `fleet spawn` without --account takes
import tempfile as _tf, os as _os2
_rs = _os2.path.join(_tf.mkdtemp(), ".last-pick")
_s = {n: ca.summarize(payload(10, 20)) for n in ("a", "b")}
check("no --account round-robins instead of taking the default account",
      [ca.resolve_auto(_s, _rs) for _ in range(4)] == ["a", "b", "a", "b"])
_full = {"a": ca.summarize(payload(10, 99)), "b": ca.summarize(payload(99, 10))}
check("every readable account full refuses the spawn (None), never a dead account",
      ca.resolve_auto(_full, _rs) is None)
check("usage unreadable everywhere falls back to default instead of blocking all spawns",
      ca.resolve_auto({}, _rs) == "default")
_one = {"a": ca.summarize(payload(99, 10)), "b": ca.summarize(payload(10, 10))}
check("a full account is skipped by auto", ca.resolve_auto(_one, _rs) == "b")

# session ceiling: a long lane must not land on an account about to hit its session cap
import tempfile as _tf3, os as _os3
_rs3 = _os3.path.join(_tf3.mkdtemp(), ".last-pick")
_deep = {"busy": ca.summarize(payload(92, 30)), "fresh": ca.summarize(payload(9, 40))}
check("rotation skips a 92%-session account while another is under the ceiling",
      [ca.rotate_pick(_deep, _rs3) for _ in range(3)] == ["fresh", "fresh", "fresh"])
_allnear = {"a": ca.summarize(payload(85, 10)), "b": ca.summarize(payload(90, 10))}
check("when every account is past the ceiling but under FULL, rotation still picks",
      ca.rotate_pick(_allnear, _rs3) in ("a", "b"))
check("the displayed pick prefers session headroom over weekly headroom",
      ca.pick_from(_deep) == "fresh")

print()
print("RESULT: " + ("ALL PASS" if ok else "FAILURES"))
sys.exit(0 if ok else 1)
