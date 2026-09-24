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
import contextlib
import fcntl
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
import model_discovery as DISCOVERY  # noqa: E402

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
    # Every model is asked the sum and must answer 42, so a row's own prompt (the legacy sentence
    # or a hand-written one) is not asked: its answer would not be 42.
    m["health_prompt"] = PRESETS.HEALTH
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
    m["models_on"] = models_on(m)
    m["default_model"] = default_model(m)
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
        binp = (os.environ.get("CODEX_BIN") or os.environ.get("FLEET_CODEX_BIN")
                or "/usr/bin/codex")
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
    prompt = m.get("health_prompt") or PRESETS.HEALTH
    run = m.get("run", "{bin} -p {task}")
    cmd = _fill(run, binp, _shquote(prompt), m.get("variant", ""))
    env = dict(os.environ)
    sec = _model_secret(mid)
    if auth_env and sec:
        env[auth_env] = sec

    def said(text, cap=120):
        # Redacted before it is cut, so a cut can never keep the first half of a secret.
        return redact(text, auth_env, env, secrets=(sec,))[:cap]
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
        if r.returncode != 0:
            # A CLI that failed says so in its exit code, and nothing it printed on the way out
            # (a token count, a request id) can outvote that.
            return ("fail", f"CLI exited with code {r.returncode}{_kind(out)}: "
                    + said(_error_line(r.stdout, r.stderr)), "")
        if answered(r.stdout or ""):
            return "ok", "test request succeeded", said(_sniff_limits(out))
        low = out.lower()
        if any(w in low for w in ("rate limit", "quota", "429", "exceeded", "insufficient")):
            return ("fail", "reachable but rate-limited/quota: " + said(out.strip()),
                    said(_sniff_limits(out)))
        if any(w in low for w in ("unauthor", "401", "403", "invalid", "forbidden")):
            return "fail", "auth rejected: " + said(out.strip()), ""
        return "fail", "no 42 in response: " + said((r.stdout or r.stderr or "").strip()), ""
    except subprocess.TimeoutExpired:
        return "fail", "test request timed out (90s)", ""
    except Exception as e:
        return "fail", f"error: {e}", ""


# What a CLI prints can hold a credential (a failing CLI echoing its key, a debug line with an
# Authorization header), and the Test keeps what it printed in models-state.json and shows it on
# the page. Every such fragment goes through redact() before it is kept.
REDACTED = "[redacted]"
REDACT_CAP = 200
_SECRET_NAME_RE = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD)$", re.I)
_SECRET_PAIR_RE = re.compile(
    r"([A-Za-z0-9_.-]*(?:key|token|secret|password|credential|authorization)[A-Za-z0-9_.-]*"
    r"[\"']?\s*[=:]\s*)"
    r"((?:bearer|basic|token)\s+\S+|\"[^\"]*\"|'[^']*'|[^\s,;&]+)", re.I)


def redact(text, auth_env="", env=None, cap=REDACT_CAP, secrets=()):
    """`text` with every secret it can recognise replaced by [redacted], cut to `cap` characters.

    A secret is the value of the row's auth variables and the row's stored `secrets`, at any
    length; the value of any other variable whose name ends in KEY, TOKEN, SECRET or PASSWORD,
    at eight characters or more; and the value in any key=value or key: value whose key names a
    credential."""
    text = str(text or "")
    env = os.environ if env is None else env
    names = {n for n in re.split(r"[\s,]+", auth_env or "") if n}
    # The row's own credential is known to be one, and `fleet models auth` accepts a short one,
    # so it has no floor. A stranger variable only looks like a credential by its name, and a
    # value like "1" there must not blank out the reply.
    own = {str(env.get(n) or "") for n in names} | {str(s or "") for s in secrets}
    values = {v for v in own if v}
    values |= {str(v or "") for n, v in env.items()
               if _SECRET_NAME_RE.search(n) and len(str(v or "")) >= 8}
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, REDACTED)
    text = _SECRET_PAIR_RE.sub(lambda m: m.group(1) + REDACTED, text)
    return text[:cap]


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_JSON_ESCAPE_RE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])')
_QUOTES = "\"'\u2018\u2019\u201c\u201d`"


def _unescape(m):
    try:
        return json.loads('"' + m.group(0) + '"')
    except ValueError:
        return m.group(0)


# The keys the lane parsers read an agent's words from (parse_generic.words_of, parse_codex's
# item.text, stream-json message content), and Gemini's response. Usage, ids and error fields are
# never among them, so a 42 in a token count or a request id is not an answer.
_REPLY_KEYS = ("response", "text", "message", "content", "delta", "data", "result", "item")
# Where a CLI keeps its bookkeeping. A reply key nested under one of these is a count or a label,
# never the model's words, so the search does not go in.
_META_KEYS = ("stats", "usage", "tokens", "id", "ids", "model", "models", "error", "errors",
              "metadata", "session_id", "request_id")


def _reply_parts(value, out, in_reply=True):
    if isinstance(value, str):
        if in_reply:
            out.append(value)
    elif isinstance(value, list):
        for v in value:
            _reply_parts(v, out, in_reply)
    elif isinstance(value, dict):
        # An error event quotes the request back and carries metadata; it is never the reply.
        if (value.get("error") or value.get("is_error")
                or "error" in str(value.get("type") or "").lower()):
            return
        for k, v in value.items():
            if k in _REPLY_KEYS:
                _reply_parts(v, out, True)
            elif str(k).lower() not in _META_KEYS:
                # A wrapper such as {"candidates": [{"content": ...}]}: its reply fields count,
                # its own strings do not.
                _reply_parts(v, out, False)


_MEMBER_RE = re.compile(r'^\s*"(?:[^"\\]|\\.)*"\s*:')


def _is_document(value):
    # A footnote such as [1] or [x, y] parses too; a list is a document only when it holds an
    # object or a list, as a CLI's array output does.
    if isinstance(value, dict):
        return True
    return isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value)


def _documents(text):
    """Every JSON document in text, at any position, in order. Decoding is tried at each brace or
    bracket that is not inside a document already found, so JSON lines, one indented document,
    and a notice before or a footer after are all read the same way."""
    dec = json.JSONDecoder()
    docs, i = [], 0
    while True:
        starts = [at for at in (text.find("{", i), text.find("[", i)) if at >= 0]
        if not starts:
            return docs
        at = min(starts)
        try:
            doc, end = dec.raw_decode(text, at)
        except ValueError:
            i = at + 1
            continue
        if _is_document(doc):
            docs.append(doc)
            i = end
        else:
            i = at + 1


def reply_text(stdout):
    """What the model said.

    If the output holds any JSON document, the reply is the reply fields of those documents and
    nothing else: a notice before, a line between or a usage footer after is the CLI talking, not
    the model, and a document's stats are not an answer. Only output with no document is read as
    plain text, and even then a line shaped like a JSON member is a fragment of bookkeeping,
    never words."""
    clean = _ANSI_RE.sub("", stdout or "")
    docs = _documents(clean)
    if docs:
        parts = []
        _reply_parts(docs, parts)
        return "\n".join(parts)
    return "\n".join(ln for ln in clean.splitlines() if not _MEMBER_RE.match(ln))


def _error_line(stdout, stderr):
    """The last thing the CLI said before it gave up: stderr first, then stdout, with a JSON
    error event reduced to its message."""
    for stream in (stderr, stdout):
        lines = [ln.strip() for ln in (stream or "").splitlines() if ln.strip()]
        if not lines:
            continue
        last = lines[-1]
        try:
            event = json.loads(last)
        except ValueError:
            return last
        if isinstance(event, dict):
            err = event.get("error")
            msg = (err.get("message") if isinstance(err, dict) else err) or event.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
        return last
    return "no output"


def _kind(out):
    low = out.lower()
    if any(w in low for w in ("rate limit", "quota", "429", "exceeded", "insufficient")):
        return ", rate-limited/quota"
    if any(w in low for w in ("unauthor", "401", "403", "invalid", "forbidden")):
        return ", auth rejected"
    return ""


def answered(stdout):
    """Whether a test reply is the answer: some line of the reply that is 42 and nothing else.

    The Test asks for the number only, so 42 inside a sentence or a footer (Usage: 42 tokens
    consumed) is not the answer, and neither are -42, 420 or 4.2. Real CLIs still wrap a correct
    reply: a colour code, a JSON string with escaped quotes or an escaped newline, quotes of any
    kind around it, surrounding spaces and one full stop after it. Those are taken off each line
    first, so a working model is not failed on its packaging."""
    text = _ANSI_RE.sub("", reply_text(stdout))
    text = _JSON_ESCAPE_RE.sub(_unescape, text)
    for line in text.splitlines():
        line = line.strip().strip(_QUOTES).strip()
        if line.endswith("."):
            line = line[:-1].strip(_QUOTES).strip()
        if line == PRESETS.HEALTH_ANSWER:
            return True
    return False


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
    """One invocation template with this farm's answers in it. {variant} is the model the command
    runs (`ollama run llama3.1 ...`, `qwen --model qwen3-coder-plus ...`); it is substituted
    here, shell-quoted, never left to bash: `opus[1m]` unquoted is a glob."""
    return (str(template).replace("{bin}", binp)
            .replace("{variant}", _shquote(str(variant or "")))
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


# ---------------------------------------------------------------- the models a provider has on
#
# A provider row is an agent CLI and the way it is paid for; `models_on` is the list of that
# provider's models agents may use, and a lane names one with `fleet spawn --model`. Nothing
# here runs the provider: switching a model on or off only rewrites the list.

CLAUDE_DEFAULT_MODEL = "sonnet"
CODEX_FALLBACK_MODEL = "gpt-5.6-sol"
NO_MODEL_CHOICE = "This provider runs the model its own settings choose; change it there."


def _env_file_value(key):
    """A FLEET_* value from $FLEET_CONFIG/env, read the way bin/fleet's _load_env_file reads it."""
    path = os.path.join(os.path.expanduser(os.environ.get("FLEET_CONFIG", "~/.config/fleet")),
                        "env")
    try:
        with open(path) as handle:
            lines = handle.read().splitlines()
    except OSError:
        return ""
    for line in lines:
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name != key:
            continue
        for quote in ('"', "'"):
            if len(value) >= 2 and value.startswith(quote) and value.endswith(quote):
                value = value[1:-1]
        return value
    return ""


def codex_default_model():
    """The model a codex lane runs when spawn names none, resolved as bin/fleet resolves it."""
    return (os.environ.get("CODEX_DEFAULT_MODEL") or os.environ.get("FLEET_CODEX_MODEL")
            or _env_file_value("FLEET_CODEX_MODEL") or CODEX_FALLBACK_MODEL)


def default_model(m):
    """The model a lane on this provider gets when `fleet spawn` names none."""
    engine = str((m or {}).get("engine") or "")
    if engine == "claude":
        return CLAUDE_DEFAULT_MODEL
    if engine == "codex":
        return codex_default_model()
    return str((m or {}).get("variant") or "")


def takes_model(m):
    """Whether this provider's command can be told which model to run at all."""
    if str((m or {}).get("engine") or "") in ("claude", "codex"):
        return True
    return "{variant}" in str((m or {}).get("run") or "")


def models_on(m):
    """The ids switched on for this provider. A catalog that still carries the retired
    `models = "sonnet, opus"` string is read as the first models_on until something is saved."""
    listed = (m or {}).get("models_on")
    if isinstance(listed, list):
        return [str(x) for x in listed if isinstance(x, str) and x]
    old = (m or {}).get("models")
    if isinstance(old, str) and old.strip():
        return [x.strip() for x in old.split(",") if x.strip()]
    return []


def _table_bounds(lines, mid):
    header = re.compile(r"^\s*\[\s*\"?" + re.escape(mid) + r"\"?\s*\]\s*(#.*)?$")
    any_header = re.compile(r"^\s*\[")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if any_header.match(lines[i]):
            end = i
            break
    return start, end


def _open_brackets(text, depth=0):
    """How many `[` are still open after this TOML value text. A bracket inside a quoted string
    (`"opus[1m]"`) or a comment is not one, so a model id never closes a list early."""
    quote, i = "", 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "#":
            break
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        i += 1
    return max(depth, 0)


def _same_but_models(before, after, mid):
    """Whether two parsed catalogs differ only in this table's models_on and models."""
    def rest(cat):
        cat = dict(cat)
        cat[mid] = {k: v for k, v in dict(cat.get(mid) or {}).items()
                    if k not in ("models_on", "models")}
        return cat
    return rest(before) == rest(after)


def _with_models_on(text, mid, ids):
    """The catalog text with this table's models_on set, the retired `models` string taken out,
    and every other line as it was."""
    lines = text.splitlines(True)
    start, end = _table_bounds(lines, mid)
    if start is None:
        return text, False
    key = re.compile(r"^\s*(models_on|models)\s*=")
    body, first, depth = [], None, 0
    for line in lines[start + 1:end]:
        if depth > 0:                               # the rest of a hand-written multi-line list
            depth = _open_brackets(line, depth)
            continue
        if key.match(line):
            first = len(body) if first is None else first
            depth = _open_brackets(line.split("=", 1)[1])
            continue
        body.append(line)
    at = first
    if at is None:
        # after the table's last key, above the blank lines and comments that open the next one
        at = len(body)
        while at > 0 and (not body[at - 1].strip() or body[at - 1].lstrip().startswith("#")):
            at -= 1
    body.insert(at, f"{'models_on':<10} = {_toml_value(list(ids))}\n")
    head = lines[start] if lines[start].endswith("\n") else lines[start] + "\n"
    return "".join(lines[:start] + [head] + body + lines[end:]), True


def select_refusal(m, on=(), off=(), confirm_cost=()):
    """{error} that refuses this change, or {} when it may go on. Shared by `fleet models on|off`
    and POST /api/models/select, so the page and the terminal refuse the same things. A model
    that can cost money the subscription does not cover, not on yet and not named in
    confirm_cost, is refused as {error, cost_note, model}, so the page can ask and send again."""
    if not m:
        return {"error": "no such provider"}
    if (on or off) and not takes_model(m):
        return {"error": NO_MODEL_CHOICE}
    for mid in list(on) + list(off):
        if not PRESETS.MODEL_RE.match(str(mid or "")):
            return {"error": f"{str(mid)[:80]!r} is not a model name: {PRESETS.MODEL_RULE}"}
    confirmed = set(confirm_cost or ())
    already = set(m.get("models_on") or [])
    for mid in on:
        note = DISCOVERY.cost_note(m.get("engine"), mid)
        if note and mid not in already and mid not in confirmed:
            return {"error": (f"{mid} can cost money your subscription does not cover: {note}. "
                              f"Confirm it: fleet models on {m['id']} {mid} --confirm-cost {mid}"),
                    "cost_note": note, "model": mid}
    default = m.get("default_model") or ""
    if default and default in off:
        return {"error": (f"{default} is the model a lane gets when fleet spawn names none, so it "
                          "stays on")}
    return {}


def select_problem(m, on=(), off=(), confirm_cost=()):
    """The one sentence that refuses this change, or ""."""
    return select_refusal(m, on, off, confirm_cost).get("error", "")


@contextlib.contextmanager
def _catalog_lock():
    """One writer of models_on at a time: two saves at once (the page and `fleet models on`)
    would otherwise both read the old list and the second would undo the first. The lock is a
    sidecar file beside the catalog, since the catalog itself is replaced by rename."""
    folder = os.path.dirname(CONFIG) or "."
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "." + os.path.basename(CONFIG) + ".lock"), "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def set_models(mid, on=(), off=(), confirm_cost=()):
    """(the provider as effective() sees it, an error sentence). Adds `on` to the provider's
    models_on and takes `off` out, in this farm's own catalog. It runs nothing."""
    try:
        with _catalog_lock():
            return _set_models(mid, on, off, confirm_cost)
    except OSError as exc:
        return None, f"could not lock {CONFIG}: {exc}"


def _set_models(mid, on, off, confirm_cost):
    m = effective(mid)
    problem = select_problem(m, on, off, confirm_cost)
    if problem:
        return None, problem
    ids = list(m["models_on"])
    if not ids and m["default_model"]:
        # A provider's first list starts with the model a bare spawn runs, so switching one
        # more on never turns every default lane into a warning.
        ids.append(m["default_model"])
    ids = [x for x in ids if x not in set(off)]
    for x in on:
        if x not in ids:
            ids.append(x)
    path, err = _own_catalog()
    if err:
        return None, err
    try:
        with open(path) as handle:
            text = handle.read()
        changed, found = _with_models_on(text, mid, ids)
        if not found:
            return None, f"{mid} is not a table in {path}"
        # The rewrite is checked before it lands: a file that no longer parses, or that changed
        # anything but this list, would quietly drop every provider the farm added.
        import tomllib
        try:
            after = tomllib.loads(changed)
            ok = (after.get(mid, {}).get("models_on") == ids
                  and _same_but_models(tomllib.loads(text), after, mid))
        except tomllib.TOMLDecodeError:
            ok = False
        if not ok:
            return None, (f"{path} could not be rewritten safely, so it was left as it was; "
                          f"set models_on for [{mid}] by hand")
        _write_atomic(path, changed)
    except OSError as exc:
        return None, f"could not write {path}: {exc}"
    return effective(mid), ""


def spawn_check(engine, model):
    """(the model the lane will run, a warning, a refusal) for `fleet spawn --engine E --model M`,
    after bin/fleet has applied its own defaults. The refusal is "" when the spawn may go on."""
    model = str(model or "")
    if model and not PRESETS.MODEL_RE.match(model):
        return model, "", f"--model {model!r} is not a model name: {PRESETS.MODEL_RULE}"
    m = effective(engine)
    if not m:
        return model, "", ""
    if model and not takes_model(m):
        return model, "", f"--model: {engine} cannot take one. {NO_MODEL_CHOICE}"
    resolved = model or m["default_model"]
    if not resolved and "{variant}" in str(m.get("run") or ""):
        return "", "", (f"{engine} needs a model: fleet spawn --engine {engine} --model <name> "
                        f"(see fleet models discover {engine})")
    listed = m["models_on"]
    if not resolved or not listed or resolved in listed:
        return resolved, "", ""
    note = DISCOVERY.cost_note(m.get("engine"), resolved)
    if note:
        return resolved, "", (f"{resolved} is not on for {engine}, and it can cost money the "
                              f"subscription does not cover: {note}. Switch it on first: "
                              f"fleet models on {engine} {resolved} --confirm-cost {resolved}")
    return resolved, (f"warning: {resolved} is not on for {engine} (on: {', '.join(listed)}); "
                      f"fleet models on {engine} {resolved}"), ""


def _selection_args(args):
    """(provider, models, confirm_cost) from `on|off <provider> <model>... [--confirm-cost m...]`."""
    provider, models, confirm, into = "", [], [], None
    for arg in args:
        if arg == "--confirm-cost":
            into = confirm
        elif not provider:
            provider = arg
        else:
            (into if into is not None else models).append(arg)
    return provider, models, confirm


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
        # read the lane's task file. Substitution happens HERE (robust) not in bash. The third
        # argument is the lane's --model, which fills {variant} ahead of the row's own.
        m = effective(a[1])
        taskfile = a[2] if len(a) > 2 else ""
        chosen = a[3] if len(a) > 3 else ""
        if m and chosen and not PRESETS.MODEL_RE.match(chosen):
            print(f"--model {chosen!r} is not a model name: {PRESETS.MODEL_RULE}", file=sys.stderr)
            sys.exit(1)
        if m:
            binp = m.get("bin", a[1])
            run = m.get("run", "{bin} -p {task}")
            cmd = _fill(run, binp, '"$(cat ' + _shquote(taskfile) + ')"',
                        chosen or m.get("variant", ""))
            print(cmd)
    elif a[0] == "spawncheck":
        # bin/fleet cmd_spawn: prints the model the lane will run. A warning goes to stderr
        # (stdout's first line is the spawn's own result); a refusal is printed and exits 1.
        resolved, warning, refusal = spawn_check(a[1] if len(a) > 1 else "",
                                                 a[2] if len(a) > 2 else "")
        if refusal:
            print(refusal)
            sys.exit(1)
        if warning:
            print(warning, file=sys.stderr)
        print(resolved)
    elif a[0] in ("on", "off"):
        provider, chosen, confirm = _selection_args(a[1:])
        if not provider or not chosen:
            print(f"usage: fleet models {a[0]} <provider> <model>..."
                  + (" [--confirm-cost <model>...]" if a[0] == "on" else ""), file=sys.stderr)
            sys.exit(2)
        if a[0] == "on":
            m, err = set_models(provider, on=chosen, confirm_cost=confirm)
        else:
            m, err = set_models(provider, off=chosen)
        if err:
            print(err, file=sys.stderr)
            sys.exit(1)
        print(f"{provider}: on {', '.join(m['models_on']) or 'none'}"
              + (f" (default {m['default_model']})" if m.get("default_model") else ""))
