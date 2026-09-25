#!/usr/bin/env python3
"""Claude subscription accounts for the farm: list them, read their live limits, pick one.

Why this exists: Claude agents run on a human's Max subscription, and that pool is shared with
that human's own interactive sessions. When codex (a separate pool) ran out, Claude became the
workhorse, so the farm must be able to SEE how much subscription is left, and to spread lanes
across more than one account once a second is added. Guessing at limits is how an orchestrator
silently eats someone's own working quota.

An "account" is a Claude Code config directory:

    default  ->  ~/.claude                      (the one `claude` uses with no env)
    <name>   ->  ~/.fleet/claude-accounts/<name>  (used via CLAUDE_CONFIG_DIR)

Each holds its own .credentials.json after one interactive login. Limits come from the same
endpoint the CLI itself uses for its warnings; the access token never leaves this process and is
never printed.

CLI:
    list          every account with session/weekly utilization and token state
    list --json   every account as {name, logged_in, email}, read from disk only
    pick          print the name of the account with the most headroom (exit 1 if none)
    dir NAME      print the account's CLAUDE_CONFIG_DIR (NAME may be `auto`)
    add NAME      create the directory and print the one-line login instruction
    balance       print the next engine and account with headroom, round-robin over claude
                  and codex: `claude <name>` or `codex codex` (exit 1 if none)
    keepalive     refresh any token near expiry
"""

import json
import os
import re
import socket
import time
import subprocess
import sys
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
# Logging an account in is interactive, and it has to happen ON the farm. The instructions the CLI
# prints therefore name the farm, and how you address it is local knowledge: an ssh host alias, a
# hostname, whatever your config calls it. FLEET_FARM_ALIAS is that name; the machine's own
# hostname is the honest default, and is right whenever you are already on the box.
FARM_ALIAS = os.environ.get("FLEET_FARM_ALIAS", "").strip() or socket.gethostname()
EXTRA_DIR = os.path.join(HOME, ".fleet", "claude-accounts")
# The name of an added account, which is also its folder in EXTRA_DIR: a letter or digit first,
# then letters, digits, '.', '_' or '-', at most 40 characters. The first character rules out '.'
# and '..', which name EXTRA_DIR itself and its parent, and anything that reads as an option.
ACCOUNT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# An account at or past this share of a window is not a candidate: a lane spawned into it would
# finish (or die) against someone else's remaining sliver, most likely yours.
FULL = 95
# A lane runs for tens of minutes. An account already deep into its session window hits the
# session cap mid-run and dies with its work half done, so spawns prefer accounts under this
# ceiling and fall back to anything under FULL only when none is.
SPAWN_SESSION_CEILING = 80

# ~/.claude cannot be renamed - it is what the CLI uses with no env at all - so the default
# account carries a display name instead. Both forms are accepted wherever a name is, and a
# deployment that wants the account shown under its real login adds it here.
DISPLAY_NAMES = {}


def account_email(name: str) -> str:
    """The login this account's folder is signed in as, read from the config file Claude Code
    keeps beside it (no network). `default` is the CLI's own config, which lives in the home
    directory, not inside ~/.claude. Empty when the file is missing or unreadable."""
    folder = account_dirs().get(name)
    if not folder:
        return ""
    path = (os.path.join(HOME, ".claude.json") if name == "default"
            else os.path.join(folder, ".claude.json"))
    try:
        with open(path, encoding="utf-8") as handle:
            account = (json.load(handle) or {}).get("oauthAccount") or {}
    except (OSError, ValueError, AttributeError):
        return ""
    email = account.get("emailAddress")
    return email.strip() if isinstance(email, str) else ""


def display(name: str) -> str:
    """What a person reads for an account: a name set in DISPLAY_NAMES, else the part of its
    login before the @, else the folder name. The folder `default` is ~/.claude, which says
    nothing about whose subscription it is."""
    if name in DISPLAY_NAMES:
        return DISPLAY_NAMES[name]
    login = _login(name)
    if not login:
        return name
    # Two folders signed in to one login would read the same; the folder tells them apart, so a
    # typed name can never land on a subscription the person did not mean.
    twins = [other for other in account_dirs() if other != name and _login(other) == login]
    return f"{login} ({name})" if twins else login


def _login(name: str) -> str:
    email = account_email(name)
    return email.split("@", 1)[0] if email else ""


def canonical(name: str) -> str:
    """The folder name for whatever a person typed: the folder itself, or its display name. A
    name two folders share matches neither, so it is refused downstream as unknown."""
    dirs = account_dirs()
    if name in dirs:
        return name
    matches = [canon for canon in dirs if display(canon) == name]
    return matches[0] if len(matches) == 1 else name


def account_dirs() -> dict:
    dirs = {"default": os.path.join(HOME, ".claude")}
    if os.path.isdir(EXTRA_DIR):
        for name in sorted(os.listdir(EXTRA_DIR)):
            path = os.path.join(EXTRA_DIR, name)
            if os.path.isdir(path):
                dirs[name] = path
    return dirs


# The CLI refreshes a token proactively while >=2h remain (measured), so pinging inside this
# margin keeps it fresh with no expiry gap. Slightly above the observed threshold for safety.
REFRESH_MARGIN_SECONDS = 3 * 3600
KEEPALIVE_MODEL = "haiku"  # cheapest; never fable, which burns its own scoped window


def token_expiry(config_dir: str) -> float | None:
    """Unix seconds when this account's access token expires, or None if unreadable."""
    try:
        with open(os.path.join(config_dir, ".credentials.json")) as handle:
            creds = json.load(handle)
    except (OSError, ValueError):
        return None
    oauth = creds.get("claudeAiOauth") or {}
    ms = oauth.get("expiresAt")
    return ms / 1000 if isinstance(ms, (int, float)) else None


def keepalive(now: float = None) -> list:
    """Refresh any token near expiry with one cheap CLI call. Returns per-account outcome lines.

    Runs a real inference only when a token is inside REFRESH_MARGIN; a healthy token costs nothing
    but a file read. A ping that leaves the token still expired means the refresh token is gone and
    the account needs an interactive /login.
    """
    from model_presets import engine_bin
    now = now if now is not None else time.time()
    binp = engine_bin("claude")
    out = []
    for name, path in account_dirs().items():
        exp = token_expiry(path)
        if exp is None:
            out.append(f"{display(name)}: no credentials — needs /login")
            continue
        remaining = exp - now
        if remaining > REFRESH_MARGIN_SECONDS:
            out.append(f"{display(name)}: fresh ({remaining/3600:.1f}h left) — skipped")
            continue
        env = dict(os.environ, CLAUDE_CONFIG_DIR=path)
        env.pop("ANTHROPIC_API_KEY", None)
        try:
            subprocess.run([binp, "-p", "ok", "--model", KEEPALIVE_MODEL],
                           env=env, capture_output=True, timeout=90, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            out.append(f"{display(name)}: ping failed ({type(exc).__name__})")
            continue
        after = token_expiry(path)
        if after and after - now > REFRESH_MARGIN_SECONDS:
            out.append(f"{display(name)}: refreshed ({(after-now)/3600:.1f}h left)")
        else:
            out.append(f"{display(name)}: ping did not refresh — refresh token gone, needs /login")
    return out


def read_usage(config_dir: str) -> dict:
    """The `limits` array from the OAuth usage endpoint, or raise with a short reason."""
    creds_path = os.path.join(config_dir, ".credentials.json")
    with open(creds_path) as handle:
        creds = json.load(handle)
    token = (creds.get("claudeAiOauth") or {}).get("accessToken") or creds.get("accessToken")
    if not token:
        raise RuntimeError("no access token in .credentials.json")
    request = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            ra = exc.headers.get("retry-after")
            secs = int(ra) if ra and ra.isdigit() else 900
            err = RuntimeError(f"429 rate-limited, retry in {secs//60}m")
            err.retry_after = secs
            raise err from exc
        raise


def summarize(usage: dict) -> dict:
    """{session, weekly, scoped: [(label, percent, active)]} out of the endpoint payload."""
    out = {"session": None, "weekly": None, "session_resets": None, "weekly_resets": None,
           "scoped": []}
    for entry in usage.get("limits") or []:
        kind = entry.get("kind")
        percent = entry.get("percent")
        if kind == "session":
            out["session"] = percent
            out["session_resets"] = entry.get("resets_at")
        elif kind == "weekly_all":
            out["weekly"] = percent
            out["weekly_resets"] = entry.get("resets_at")
        elif kind == "weekly_scoped":
            scope = ((entry.get("scope") or {}).get("model") or {}).get("display_name") or "?"
            out["scoped"].append((scope, percent, bool(entry.get("is_active")),
                                  entry.get("resets_at")))
    return out


def pick_from(summaries: dict) -> str | None:
    """The account with the most weekly headroom, skipping any that is effectively full.

    `summaries` maps name -> summarize() output (accounts whose usage could not be read are
    simply absent). Scoped limits (one model's promo window) do not disqualify an account —
    lanes can run other models — only the session and the all-model weekly do.
    """
    candidates = []
    for name, s in summaries.items():
        session = s["session"] if s["session"] is not None else 0
        weekly = s["weekly"] if s["weekly"] is not None else 0
        if session >= FULL or weekly >= FULL:
            continue
        candidates.append((weekly, session, name))
    if not candidates:
        return None
    preferred = [c for c in candidates if c[1] < SPAWN_SESSION_CEILING]
    return min(preferred or candidates)[2]


ROTATION_STATE = os.path.join(EXTRA_DIR, ".last-pick")


def eligible(summaries: dict) -> list:
    """Accounts fit to take a lane, in stable name order.

    Accounts under SPAWN_SESSION_CEILING first; only when none is, anything under FULL.
    """
    fit, near = [], []
    for name in sorted(summaries):
        s = summaries[name]
        session = s["session"] if s["session"] is not None else 0
        weekly = s["weekly"] if s["weekly"] is not None else 0
        if session < FULL and weekly < FULL:
            (fit if session < SPAWN_SESSION_CEILING else near).append(name)
    return fit or near


BALANCE_STATE = os.path.join(EXTRA_DIR, ".last-balance")
# The refresher writes this; balance() reads it. One slow writer touches the usage endpoint,
# every reader takes the cache — reading three tokens in a burst per balance() call is exactly
# what provokes the endpoint's frequency 429 (cure a rate limit by NOT calling).
ACCOUNTS_CACHE = os.path.join(HOME, ".fleet", "accounts-cache.json")
# Past this the snapshot is too stale to steer a spawn; fall back to one live read.
CACHE_MAX_AGE = 1800


def _codex_candidate():
    """(engine, name, load_percent) for codex, or None if it cannot take a lane right now."""
    try:
        import codex_usage as cx
        s = cx.summarize()
    except Exception:
        return None
    prim = (s.get("primary") or {}).get("percent") or 0
    sec = (s.get("secondary") or {}).get("percent") or 0
    if s.get("limit_reached") or prim >= FULL or sec >= FULL:
        return None
    return ("codex", "codex", max(prim, sec))


def write_cache(rows: list, cache_path: str = None) -> None:
    """Persist the refresher's account rows so balance() never has to hit the network itself."""
    path = cache_path or ACCOUNTS_CACHE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            json.dump({"at": time.time(), "accounts": rows}, handle)
    except OSError:
        pass


def _wheel_from_cache(cache_path: str = None):
    """(engine, account) candidates with headroom from the cached snapshot, or None if the cache
    is missing or too old to trust. No network. A stale_error row (throttled/expired) is skipped."""
    path = cache_path or ACCOUNTS_CACHE
    try:
        with open(path) as handle:
            blob = json.load(handle)
    except (OSError, ValueError):
        return None
    if time.time() - (blob.get("at") or 0) > CACHE_MAX_AGE:
        return None
    wheel = []
    for row in blob.get("accounts", []):
        if row.get("stale_error"):
            continue
        sess = row.get("session") or 0
        weekly = row.get("weekly") or 0
        if row.get("engine") == "codex":
            if row.get("limit_reached") or sess >= FULL or weekly >= FULL:
                continue
            wheel.append(("codex", "codex"))
        elif sess < FULL and weekly < FULL:
            wheel.append(("claude", row.get("name")))
    wheel.sort()  # deterministic order so the round-robin pointer is stable across calls
    return wheel


def balance(state_path: str = None, cache_path: str = None):
    """Next (engine, account) across all subscriptions with headroom, round-robin. None if all full.

    account is the Claude account name for engine=claude, or "codex" for engine=codex.
    """
    state_path = state_path or str(BALANCE_STATE)
    wheel = _wheel_from_cache(cache_path)
    if wheel is None:
        # Cold cache (dashboard not up yet): one live read to bootstrap, then the cache warms it.
        summaries, _ = collect()
        wheel = [("claude", n) for n in eligible(summaries)]
        cand = _codex_candidate()
        if cand:
            wheel.append((cand[0], cand[1]))
        wheel.sort()
    if not wheel:
        return None
    keys = [f"{e}:{n}" for e, n in wheel]
    last = None
    try:
        with open(state_path) as handle:
            last = handle.read().strip()
    except OSError:
        pass
    idx = (keys.index(last) + 1) % len(keys) if last in keys else 0
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as handle:
            handle.write(keys[idx])
    except OSError:
        pass
    return wheel[idx]


def rotate_pick(summaries: dict, state_path: str = None) -> str | None:
    """The next account in the rotation, or None when nothing has headroom.

    Plain round-robin over the eligible set. Deliberately no headroom weighting: weighting
    re-concentrates a batch on one account, and spreading parallel lanes across per-account
    session windows is the entire point.
    """
    state_path = state_path or ROTATION_STATE
    names = eligible(summaries)
    if not names:
        return None
    last = None
    try:
        with open(state_path) as handle:
            last = handle.read().strip()
    except OSError:
        pass
    if last in names:
        pick = names[(names.index(last) + 1) % len(names)]
    else:
        pick = names[0]
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as handle:
            handle.write(pick)
    except OSError:
        pass  # a failed remember costs one repeat, not a wrong account
    return pick


# Per-account "do not call before" wall-clock, set from a 429's retry-after. Calling a throttled
# account only pushes its backoff further out, so the refresher must wait it out, not hammer it.
_cooldown_until: dict = {}


def collect() -> tuple[dict, dict]:
    """(summaries, errors) for every account, skipping any still inside its 429 cooldown."""
    summaries, errors = {}, {}
    now = time.time()
    for name, path in account_dirs().items():
        until = _cooldown_until.get(name, 0)
        if now < until:
            errors[name] = f"429 rate-limited, {int(until - now)//60}m to retry"
            continue
        try:
            summaries[name] = summarize(read_usage(path))
            _cooldown_until.pop(name, None)
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {str(exc)[:80]}"
            ra = getattr(exc, "retry_after", None)
            if ra:
                # a little past the window, so we do not race the reset and re-arm it
                _cooldown_until[name] = time.time() + ra + 15
    return summaries, errors


def list_rows() -> list:
    """Every account as a row a program reads: its name, whether its credentials file exists,
    and the email it is signed in as. No network, and never a token."""
    return [{"name": name,
             "logged_in": os.path.exists(os.path.join(path, ".credentials.json")),
             "email": account_email(name)}
            for name, path in account_dirs().items()]


def cmd_list(as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(list_rows(), indent=2))
        return 0
    summaries, errors = collect()
    best = pick_from(summaries)
    for name, path in account_dirs().items():
        if name in summaries:
            s = summaries[name]
            scoped = " ".join(
                f"[{label} {pct}%{'!' if active else ''}]"
                for label, pct, active, _resets in s["scoped"]
            )
            mark = " <- pick" if name == best else ""
            print(f"  {display(name):<16} session {s['session']:>3}%  weekly {s['weekly']:>3}%  "
                  f"{scoped}{mark}")
        else:
            print(f"  {display(name):<16} UNAVAILABLE — {errors[name]}")
            if "429" in errors[name]:
                exp = token_expiry(account_dirs()[name])
                if exp is not None and exp <= time.time():
                    print("               token EXPIRED (429 masks it); the keepalive timer "
                          "refreshes it — or /login if that account's refresh token is gone")
                else:
                    print("               rate-limited by Anthropic; retries on the next "
                          "refresh — logging in again would not help")
            else:
                print(f"               fix: ssh -t {FARM_ALIAS} env "
                      f"CLAUDE_CONFIG_DIR={account_dirs()[name]} claude   then /login")
    return 0


def cmd_pick() -> int:
    summaries, errors = collect()
    for name, why in errors.items():
        print(f"fleet accounts: {name} unavailable ({why})", file=sys.stderr)
    best = pick_from(summaries)
    if best is None:
        print("fleet accounts: no account has headroom — every one is at "
              f">={FULL}% of its session or weekly window", file=sys.stderr)
        return 1
    print(best)
    return 0


def resolve_auto(summaries: dict, state_path: str = None) -> str | None:
    """The account an `auto` spawn takes: round-robin over those with headroom.

    `fleet spawn` without `--account` resolves here, so lanes spread evenly across every
    subscription instead of silently draining the default one, which is the pool shared with
    your own sessions. Two empty outcomes mean opposite things and are kept apart. Usage
    that was READ and is full everywhere returns None: refuse the spawn, because a lane on a full
    account dies on its first step. Usage that could not be read at all (the endpoint down, every
    account inside its 429 cooldown) falls back to "default" rather than blocking every spawn on
    a telemetry outage.
    """
    if not summaries:
        return "default"
    return rotate_pick(summaries, state_path)


def cmd_dir(name: str) -> int:
    name = canonical(name)
    if name == "auto":
        summaries, _ = collect()
        picked = resolve_auto(summaries)
        if picked is None:
            print("fleet accounts: no account has headroom; every one is at "
                  f">={FULL}% of its session or weekly window. Hold the spawn.", file=sys.stderr)
            return 1
        if picked == "default" and not summaries:
            print("fleet accounts: usage unreadable for every account; using the default one",
                  file=sys.stderr)
        name = picked
    dirs = account_dirs()
    if name not in dirs:
        print(f"fleet accounts: unknown account '{name}' — have: {', '.join(dirs)}",
              file=sys.stderr)
        return 1
    if not os.path.exists(os.path.join(dirs[name], ".credentials.json")):
        print(f"fleet accounts: '{name}' has no credentials — "
              f"ssh -t {FARM_ALIAS} env CLAUDE_CONFIG_DIR={dirs[name]} claude   then /login",
              file=sys.stderr)
        return 1
    print(dirs[name])
    return 0


def cmd_add(name: str) -> int:
    # `default` is ~/.claude, and a folder of that name would take its place in account_dirs().
    if not ACCOUNT_NAME.fullmatch(name or "") or name in ("auto", "default"):
        print("fleet accounts: pick a plain name: a letter or digit first, then letters, digits, "
              "'.', '_' or '-', at most 40 characters, and not 'auto' or 'default'",
              file=sys.stderr)
        return 1
    path = os.path.join(EXTRA_DIR, name)
    os.makedirs(path, exist_ok=True)
    print(f"created {path}")
    print(f"log it in once:  ssh -t {FARM_ALIAS} env CLAUDE_CONFIG_DIR={path} claude   "
          f"then /login   (set FLEET_FARM_ALIAS if that is not how you reach this machine)")
    print(f"then spawn with: fleet spawn ... --account {name}   (or --account auto)")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        return cmd_list(as_json="--json" in argv[1:])
    if cmd == "pick":
        return cmd_pick()
    if cmd == "dir" and len(argv) > 1:
        return cmd_dir(argv[1])
    if cmd == "add" and len(argv) > 1:
        return cmd_add(argv[1])
    if cmd == "balance":
        pick = balance()
        if pick is None:
            print("no subscription has headroom right now", file=sys.stderr)
            return 1
        engine, account = pick
        # machine-readable for spawn wrappers: "claude <account>" or "codex codex"
        print(f"{engine} {account}")
        return 0
    if cmd == "keepalive":
        for line in keepalive():
            print(f"  {line}")
        try:
            import codex_usage as _cx
            print(f"  {_cx.keepalive()}")
        except Exception as _e:
            print(f"  codex: {type(_e).__name__}")
        return 0
    print(__doc__.split("CLI:")[1])
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
