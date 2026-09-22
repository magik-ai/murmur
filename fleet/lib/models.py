#!/usr/bin/env python3
"""Fleet model catalog: which coding models exist, their routing role, and per-model runtime state
(enabled/disabled + last health check + measured limits). The catalog (config/models.toml) is
declarative; the toggles and health live in ~/.fleet/models-state.json, so activating a model
never rewrites its description.

Health check on enable: a model is only spawnable when it is BOTH enabled AND last-health-ok, so
flipping a switch back on fires a real test request (does the CLI run, does the sub authenticate,
what do the limits look like) before any lane is routed to it.

A farm's catalog is also written from here: add_model() turns one of lib/model_presets.py's
services into an entry in ~/.config/fleet/models.toml (creating it from the shipped example on
the first write) and remove_model() takes one back out. Only an entry this farm added carries
source = "added" and only those can be removed: what came with fleet can be switched off."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_presets as PRESETS  # noqa: E402

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
    """The parsed document, or None when the file is not TOML at all.

    An empty file and a file of nothing but comments both parse to {}, and that is a real
    answer: a farm that took its last added row back out has an empty catalog, not a broken
    one. Only None means "a person has to fix this by hand".
    """
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def catalog():
    """The declarative catalog. Prefer the user's config, fall back to the shipped example."""
    for p in (CONFIG, EXAMPLE):
        if os.path.exists(p):
            d = _load_toml(p)
            if d is not None:
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
    # The catalog's `health` is the tiny PROMPT a test request sends; the state's `health` is how
    # the last test went, and that is what every reader means by the word. The prompt gets its
    # own name here before the state overwrites it: without this the test request asked the
    # model "unchecked" and no generic model could ever pass its own health check.
    m["health_prompt"] = str(m.get("health") or "Reply with exactly: OK")
    m["enabled"] = srec.get("enabled", bool(m.get("default_on", False)))
    m["health"] = srec.get("health", "unchecked")      # ok | fail | unchecked
    m["health_detail"] = srec.get("health_detail", "")
    m["limits"] = srec.get("limits", "")
    m["checked_at"] = srec.get("checked_at", 0)
    # The fields the models table reads, always present so no reader has to guess: how this is
    # paid for, whether this farm added the row (and may remove it), and which model it runs.
    m["access"] = str(m.get("access") or "")
    m["source"] = "added" if str(m.get("source") or "") == "added" else "shipped"
    m["variant"] = str(m.get("variant") or "")
    m["preset"] = str(m.get("preset") or "")
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
    prompt = m.get("health_prompt") or "Reply with exactly: OK"
    run = m.get("run", "{bin} -p {task}")
    cmd = _fill(run, binp, _shquote(prompt), m.get("variant", ""))
    env = dict(os.environ)
    sec = _model_secret(mid)
    if auth_env and sec:
        env[auth_env] = sec
    try:
        # An empty room of its own, thrown away with the answer. A test request runs a real
        # coding agent and some of them edit and commit in the directory they start in; the
        # dashboard's own working directory is the fleet checkout, which is not a thing to hand
        # to a file-editing agent because somebody pressed Test.
        with tempfile.TemporaryDirectory(prefix="fleet-model-test-",
                                         ignore_cleanup_errors=True) as room:
            r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True,
                               timeout=90, env=env, cwd=room)
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


def _fill(template, binp, task, variant=""):
    """One invocation template with this farm's answers in it. {variant} is a local runner's
    model name (`ollama run llama3.1 ...`); it is substituted here, never left to bash."""
    return (str(template).replace("{bin}", binp)
            .replace("{variant}", str(variant or ""))
            .replace("{task}", task))


def _secret_path(mid):
    return os.path.join(os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet")),
                        "secrets", f"{mid}.key")


def _model_secret(mid):
    try:
        return open(_secret_path(mid)).read().strip()
    except Exception:
        return ""


def has_secret(mid):
    """Whether this farm holds a credential for this model. The key itself never leaves here."""
    return bool(_model_secret(mid))


# ---------------------------------------------------------------- writing the catalog
#
# The catalog is a file a person edits, so a program that writes it writes plain, quoted TOML
# and nothing else: one table per model, every string escaped, no reformatting of what is
# already there. A value never reaches a shell from here, and an id is checked against a
# pattern before it becomes a table name.

ID_RE = PRESETS.ID_RE
ID_RULE = ("a model id is lower case letters, digits, - and _, starting with a letter, "
           "2 to 31 characters")
BARE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _toml_string(value):
    """One TOML basic string: every quote, backslash and control character escaped."""
    out = []
    for ch in str(value):
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append("\\u%04X" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return _toml_string(value)


def _toml_table(mid, entry):
    """One catalog entry as text, ready to append to a catalog."""
    name = mid if BARE_KEY.match(mid) else _toml_string(mid)
    lines = ["[" + name + "]"]
    for key in sorted(entry):
        if entry[key] is None or entry[key] == "":
            continue
        shown = key if BARE_KEY.match(key) else _toml_string(key)
        lines.append(f"{shown:<10} = {_toml_value(entry[key])}")
    return "\n".join(lines) + "\n"


def _write_atomic(path, text):
    """Replace a file's whole contents in one step.

    The catalog belongs to the operator, so a write that does not finish (a full disk, a crash,
    two adds at the same moment) has to leave the file they have exactly as it was. Truncating
    it and then writing into it loses it for good on any of those; the new text goes to a temp
    file in the same directory and is renamed over the top instead, which is the one operation
    the filesystem does whole. The state file next door is written the same way.
    """
    folder = os.path.dirname(path) or "."
    mode = 0o644
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        pass                                        # a file that is not there yet keeps 0644
    handle, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(path) + ".",
                                   suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _own_catalog():
    """(path, error): this farm's own catalog, created from the shipped example on first write.

    Until somebody adds a model there is no ~/.config/fleet/models.toml at all and the farm runs
    on the example. The first write copies the example across, so adding a model never costs the
    operator the two shipped entries.
    """
    if os.path.exists(CONFIG):
        if _load_toml(CONFIG) is None:
            return "", (f"{CONFIG} could not be read as TOML: fix it by hand before adding "
                        "a model here")
        return CONFIG, ""
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(EXAMPLE) as src:
            text = src.read()
        _write_atomic(CONFIG, text)
    except OSError as exc:
        return "", f"could not create {CONFIG}: {exc}"
    return CONFIG, ""


def add_model(spec):
    """(the new model as effective() sees it, an error sentence).

    `spec` is a catalog entry plus its id: model_presets.entry_from() builds one from a preset.
    The entry is appended to this farm's own catalog, marked as added, which is the only thing
    that lets it be removed again.
    """
    fields = dict(spec or {})
    mid = str(fields.pop("id", "") or "").strip()
    if not ID_RE.match(mid):
        return None, f"{ID_RULE}: {mid!r} is not one" if mid else ID_RULE
    if mid in catalog():
        return None, f"{mid} is already in this farm's catalog"
    entry = {k: v for k, v in fields.items() if v not in (None, "")}
    entry.setdefault("engine", "generic")
    entry.setdefault("label", mid)
    entry["source"] = "added"
    if entry["engine"] == "generic":
        if not entry.get("bin"):
            return None, "a model needs the command to run (bin)"
        if not entry.get("run"):
            return None, "a model needs the non-interactive command line (run)"
    path, err = _own_catalog()
    if err:
        return None, err
    try:
        with open(path) as f:
            text = f.read()
        block = _toml_table(mid, entry)
        _write_atomic(path, text + ("" if text.endswith("\n\n") or not text else "\n") + block)
    except OSError as exc:
        return None, f"could not write {path}: {exc}"
    model = effective(mid)
    if not model:
        return None, f"{mid} was written to {path} but the catalog would not read it back"
    return model, ""


def _without_table(text, mid):
    """The catalog text with one model's table taken out, and nothing else touched."""
    header = re.compile(r"^\s*\[\s*\"?" + re.escape(mid) + r"\"?\s*\]\s*$")
    any_header = re.compile(r"^\s*\[")
    lines = text.splitlines(True)
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return text, False
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if any_header.match(lines[i]):
            end = i
            break
    # Comments and blank lines directly above the next table belong to that table, not to this
    # one: a person's note about codex must not disappear with the row above it.
    while end - 1 > start and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    return "".join(lines[:start] + lines[end:]), True


def remove_model(mid):
    """(the id removed, an error sentence). Only an entry this farm added can be removed: a
    shipped model can be switched off, and taking it out of the example would be editing the
    checkout. The model's runtime state and its stored key go with it."""
    mid = str(mid or "").strip()
    model = effective(mid)
    if not model:
        return None, f"no such model: {mid}"
    if model.get("source") != "added":
        return None, (f"{mid} came with fleet: switch it off here, or edit this farm's "
                      "models.toml by hand")
    if not os.path.exists(CONFIG):
        return None, f"{mid} is not in this farm's own catalog ({CONFIG})"
    try:
        with open(CONFIG) as f:
            text = f.read()
        trimmed, found = _without_table(text, mid)
        if not found:
            return None, f"{mid} is not a table in {CONFIG}"
        _write_atomic(CONFIG, trimmed)
    except OSError as exc:
        return None, f"could not write {CONFIG}: {exc}"
    st = _state()
    if st.pop(mid, None) is not None:
        _save_state(st)
    try:
        os.remove(_secret_path(mid))
    except OSError:
        pass
    return mid, ""


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
            cmd = _fill(run, binp, '"$(cat ' + _shquote(taskfile) + ')"', m.get("variant", ""))
            print(cmd)
