#!/usr/bin/env python3
"""Fleet model catalog: which coding models exist, their routing role, and per-model runtime state
(enabled/disabled + last health check + measured limits). The catalog (config/models.toml) is
declarative; the toggles and health live in ~/.fleet/models-state.json, so activating a model
never rewrites its description.

Health check on enable: a model is only spawnable when it is BOTH enabled AND last-health-ok, so
flipping a switch back on fires a real test request (does the CLI run, does the sub authenticate,
what do the limits look like) before any lane is routed to it."""
import json
import os
import shutil
import subprocess
import time

# The checkout this file belongs to, so a clone anywhere works without being told where it is.
# FLEET_HOME still wins, which is how `bin/fleet` passes its own resolved home down.
FLEET_HOME = os.environ.get("FLEET_HOME") or os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))
CONFIG = os.path.expanduser(os.path.join(os.environ.get("FLEET_CONFIG", "~/.config/fleet"),
                                         "models.toml"))
EXAMPLE = os.path.join(FLEET_HOME, "config", "models.example.toml")
STATE = os.path.join(os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet")),
                     "models-state.json")


def _load_toml(path):
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def catalog():
    """The declarative catalog. Prefer the user's config, fall back to the shipped example."""
    for p in (CONFIG, EXAMPLE):
        if os.path.exists(p):
            d = _load_toml(p)
            if d:
                return d
    return {}


def _state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def _save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, STATE)


def effective(mid, cat=None, st=None):
    """Catalog entry merged with runtime state → the full picture for one model."""
    cat = cat if cat is not None else catalog()
    st = st if st is not None else _state()
    if mid not in cat:
        return None
    m = dict(cat[mid])
    m["id"] = mid
    srec = st.get(mid, {})
    m["enabled"] = srec.get("enabled", bool(m.get("default_on", False)))
    m["health"] = srec.get("health", "unchecked")      # ok | fail | unchecked
    m["health_detail"] = srec.get("health_detail", "")
    m["limits"] = srec.get("limits", "")
    m["checked_at"] = srec.get("checked_at", 0)
    # a model is routable only if switched on AND its last health test passed (native engines,
    # which ride our own subs, are healthy as long as their binary + auth exist)
    if m.get("engine") in ("codex", "claude"):
        m["routable"] = m["enabled"] and m["health"] != "fail"
    else:
        m["routable"] = m["enabled"] and m["health"] == "ok"
    return m


def listing():
    cat, st = catalog(), _state()
    return [effective(mid, cat, st) for mid in cat]


def health_check(mid):
    """Fire a real test request. Returns (health, detail, limits). Never raises."""
    m = effective(mid)
    if not m:
        return "fail", "no such model", ""
    eng = m.get("engine")
    if eng == "codex":
        binp = os.environ.get("CODEX_BIN", "/usr/bin/codex")
        if not (os.path.exists(binp) or shutil.which("codex")):
            return "fail", "codex binary not found", ""
        auth = os.path.exists(os.path.expanduser("~/.codex/auth.json"))
        return ("ok", "codex CLI + ChatGPT auth present", "subscription") if auth \
            else ("fail", "no ~/.codex/auth.json", "")
    if eng == "claude":
        binp = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
        if not (os.path.exists(binp) or shutil.which("claude")):
            return "fail", "claude binary not found", ""
        return "ok", "claude CLI present", "subscription"
    # generic: actually run the CLI on a tiny prompt
    binp = m.get("bin", mid)
    if not shutil.which(binp):
        return "fail", f"{binp} not installed on the farm", ""
    auth_env = m.get("auth_env", "")
    if auth_env and not os.environ.get(auth_env) and not _model_secret(mid):
        return "fail", f"no credential: set {auth_env} (fleet models auth {mid})", ""
    prompt = m.get("health", "Reply with exactly: OK")
    run = m.get("run", "{bin} -p {task}")
    cmd = run.replace("{bin}", binp).replace("{task}", _shquote(prompt))
    env = dict(os.environ)
    sec = _model_secret(mid)
    if auth_env and sec:
        env[auth_env] = sec
    try:
        r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True,
                           timeout=90, env=env)
        out = (r.stdout or "") + " " + (r.stderr or "")
        if "OK" in (r.stdout or "").upper():
            limits = _sniff_limits(out)
            return "ok", "test request succeeded", limits
        low = out.lower()
        if any(w in low for w in ("rate limit", "quota", "429", "exceeded", "insufficient")):
            return "fail", "reachable but rate-limited/quota: " + out.strip()[:120], _sniff_limits(out)
        if any(w in low for w in ("unauthor", "401", "403", "invalid", "forbidden")):
            return "fail", "auth rejected: " + out.strip()[:120], ""
        return "fail", "no OK in response: " + (r.stdout or r.stderr or "").strip()[:120], ""
    except subprocess.TimeoutExpired:
        return "fail", "test request timed out (90s)", ""
    except Exception as e:
        return "fail", f"error: {e}", ""


def _sniff_limits(text):
    import re
    for pat in (r"[0-9,]+\s*(?:requests?|prompts?|tokens?)\s*(?:remaining|left|/\s*\w+)",
                r"(?:remaining|limit)[:=]\s*[0-9,]+"):
        m = re.search(pat, text, re.I)
        if m:
            return m.group(0)[:60]
    return ""


def _shquote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _secret_path(mid):
    return os.path.join(os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet")),
                        "secrets", f"{mid}.key")


def _model_secret(mid):
    try:
        return open(_secret_path(mid)).read().strip()
    except Exception:
        return ""


def set_enabled(mid, on):
    cat = catalog()
    if mid not in cat:
        return None, "no such model"
    st = _state()
    rec = st.setdefault(mid, {})
    rec["enabled"] = bool(on)
    if on:
        h, detail, limits = health_check(mid)
        rec["health"] = h
        rec["health_detail"] = detail
        rec["limits"] = limits
        rec["checked_at"] = int(time.time())
    _save_state(st)
    return effective(mid), None


def run_test(mid):
    cat = catalog()
    if mid not in cat:
        return None, "no such model"
    h, detail, limits = health_check(mid)
    st = _state()
    rec = st.setdefault(mid, {})
    rec["health"] = h
    rec["health_detail"] = detail
    rec["limits"] = limits
    rec["checked_at"] = int(time.time())
    _save_state(st)
    return effective(mid), None


def _human(m):
    return (f"{m['id']}: {'ON' if m['enabled'] else 'off'} · health={m['health']}"
            + (f" · {m['health_detail']}" if m.get('health_detail') else "")
            + (f" · limits: {m['limits']}" if m.get('limits') else ""))


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if not a or a[0] == "list":
        print(json.dumps(listing()))          # machine-readable; the CLI/dashboard format it
    elif a[0] == "enable":
        m, err = set_enabled(a[1], True); print(err or _human(m))
    elif a[0] == "disable":
        m, err = set_enabled(a[1], False); print(err or _human(m))
    elif a[0] == "test":
        m, err = run_test(a[1]); print(err or _human(m))
    elif a[0] == "routable":
        m = effective(a[1]); print("yes" if (m and m["routable"]) else "no")
    elif a[0] == "launchspec":
        # TAB-separated bin, auth_env, run-template, secret-path, consumed by the launcher's
        # generic engine path. Only meaningful for engine=generic models.
        m = effective(a[1])
        if m:
            print("\t".join([m.get("bin", a[1]), m.get("auth_env", ""),
                             m.get("run", "{bin} -p {task}"), _secret_path(a[1])]))
    elif a[0] == "field":
        m = effective(a[1]); print(m.get(a[2], "") if m else "")
    elif a[0] == "launchcmd":
        # Final non-interactive command for a generic model, with {bin} resolved and {task} set to
        # read the lane's task file. Substitution happens HERE (robust) not in bash.
        m = effective(a[1])
        taskfile = a[2] if len(a) > 2 else ""
        if m:
            binp = m.get("bin", a[1])
            run = m.get("run", "{bin} -p {task}")
            cmd = run.replace("{bin}", binp).replace("{task}", '"$(cat ' + _shquote(taskfile) + ')"')
            print(cmd)
