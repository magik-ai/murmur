#!/usr/bin/env python3
"""The model catalog a person can write from the dashboard: the presets, the guarded writer that
adds an entry to a farm's own models.toml, and the status one row shows.

Everything here runs against a throwaway FLEET_CONFIG and FLEET_STATE. A test that touched the
real ~/.config/fleet/models.toml would rewrite the catalog of the farm it is running on.
"""
import atexit
import contextlib
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

LIB = pathlib.Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
# Point the library at a throwaway farm BEFORE importing it: its catalog and state paths are
# read from the environment once, at import.
_SANDBOX = tempfile.mkdtemp(prefix="fleet-models-test-")
os.environ["FLEET_CONFIG"] = os.path.join(_SANDBOX, "config")
os.environ["FLEET_STATE"] = os.path.join(_SANDBOX, "state")
import model_presets as P  # noqa: E402
import models as M  # noqa: E402

atexit.register(lambda: shutil.rmtree(_SANDBOX, ignore_errors=True))

ok = True


def check(name, cond, detail=""):
    global ok
    print(("  PASS " if cond else "  FAIL ") + name
          + (f": {detail}" if detail and not cond else ""))
    ok = ok and cond


print("presets")

_ids = [p["id"] for p in P.PRESETS]
check("every service the dialog offers has a preset",
      _ids == ["claude", "codex", "gemini", "qwen", "kimi", "opencode", "aider", "ollama",
               "custom"], str(_ids))

_fields = ("id", "label", "color", "kind", "engine", "bin", "install_hint", "pull_hint",
           "auth_env", "run", "health", "tos", "access", "variants", "docs")
check("every preset carries every field, so no card has to guess",
      all(set(_fields) <= set(p) for p in P.PRESETS),
      str([p["id"] for p in P.PRESETS if not set(_fields) <= set(p)]))
check("every preset says in one line how it is paid for",
      all(p["access"].strip() for p in P.PRESETS))
check("every preset says whether running it headless is permitted",
      all(p["tos"].strip() for p in P.PRESETS))
check("kind is one of the three a person can arrange",
      all(p["kind"] in ("subscription", "key", "local") for p in P.PRESETS))
check("engine is generic unless it is one of our two native launchers",
      all((p["engine"] == "generic") != (p["id"] in ("claude", "codex")) for p in P.PRESETS))
check("nothing in the presets is dated",
      not any(w in (p["tos"] + p["access"] + p["label"]).lower()
              for p in P.PRESETS
              for w in ("today", "2025", "2026", "prepared, do not enable")))

_by = {p["id"]: p for p in P.PRESETS}
check("Gemini CLI runs the command its own docs give, with the chosen model named in it",
      _by["gemini"]["run"] == "{bin} -m {variant} -p {task} --output-format json"
      and _by["gemini"]["install_hint"] == "npm install -g @google/gemini-cli"
      and _by["gemini"]["auth_env"] == "GEMINI_API_KEY")
check("Qwen Code keeps the invocation the shipped catalog used",
      _by["qwen"]["run"] == "{bin} -p {task} --output-format stream-json"
      and _by["qwen"]["install_hint"] == "npm install -g @qwen-code/qwen-code"
      and _by["qwen"]["auth_env"] == "QWEN_CODE_API_KEY")
check("Kimi Code names the key plan as the permitted path, not the subscription",
      "forbid non-interactive use" in _by["kimi"]["tos"]
      and "api key" in _by["kimi"]["access"].lower()
      and _by["kimi"]["auth_env"] == "KIMI_API_KEY")
check("OpenCode runs `opencode run` and installs from its own script",
      _by["opencode"]["run"] == "{bin} run {task}"
      and _by["opencode"]["install_hint"] == "curl -fsSL https://opencode.ai/install | bash"
      and "ANTHROPIC_API_KEY" in _by["opencode"]["access"])
check("Aider runs one message and answers its own prompts",
      _by["aider"]["run"] == "{bin} --message {task} --yes"
      and _by["aider"]["install_hint"] == "pip install aider-chat")
check("Ollama is local: a variant in the command, an install and a pull",
      _by["ollama"]["kind"] == "local"
      and _by["ollama"]["run"] == "{bin} run {variant} {task}"
      and _by["ollama"]["variants"] == ["llama3.1", "qwen2.5-coder", "deepseek-coder"]
      and _by["ollama"]["pull_hint"] == "ollama pull <variant>"
      and _by["ollama"]["install_hint"] == "curl -fsSL https://ollama.com/install.sh | sh")
check("Ollama needs no key at all", _by["ollama"]["auth_env"] == "")
check("a preset that offers a choice of models puts {variant} in the command it runs: a choice "
      "the command line has no room for would never reach the model",
      all("{variant}" in p["run"] for p in P.PRESETS if p["variants"]),
      str([p["id"] for p in P.PRESETS if p["variants"] and "{variant}" not in p["run"]]))
check("a native engine offers no choice here: its lane picks the model, not this catalog row",
      _by["claude"]["variants"] == [] and _by["codex"]["variants"] == [],
      str(_by["claude"]["variants"]))
check("Custom command ships no defaults: the operator names the command",
      _by["custom"]["bin"] == "" and _by["custom"]["run"] == "")
check("a subscription preset holds no key variable",
      all(_by[p]["auth_env"] == "" for p in ("claude", "codex")))
check("every preset that is not Custom points at the vendor's docs",
      all(p["docs"].startswith("https://") for p in P.PRESETS if p["id"] != "custom"))
check("the shipped list is copied out, so a caller cannot edit it",
      (lambda rows: (rows[0].__setitem__("label", "scribbled"),
                     P.PRESETS[0]["label"] == "Claude Code")[1])(P.presets()))

print()
print("building a catalog entry from a preset")

_entry, _err = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
check("a preset plus a variant is a complete entry",
      _err == "" and _entry["bin"] == "gemini" and _entry["engine"] == "generic"
      and _entry["variant"] == "gemini-2.5-pro" and _entry["preset"] == "gemini"
      and _entry["access"].startswith("an API key"), str(_err))
check("the entry carries no kind, variants or docs: those describe the service, not the row",
      not ({"kind", "variants", "docs"} & set(_entry)))

_entry, _err = P.entry_from("ollama", {"variant": "qwen2.5-coder"})
check("a local runner keeps {variant} in its command for the launcher to fill",
      _err == "" and _entry["run"] == "{bin} run {variant} {task}"
      and _entry["variant"] == "qwen2.5-coder", str(_err))

_entry, _err = P.entry_from("ollama", {})
check("a command that needs a model refuses without one, and names the choices",
      _entry is None and "llama3.1" in _err, str(_err))

_entry, _err = P.entry_from("custom", {"bin": "mycli", "run": "{bin} --do {task}"})
check("Custom command takes the operator's own bin and run",
      _err == "" and _entry["bin"] == "mycli" and _entry["run"] == "{bin} --do {task}", str(_err))

check("a custom command carries no label of its own: the name is the operator's",
      _entry.get("label", "") == "", str(_entry.get("label")))

_entry, _err = P.entry_from("custom", {"bin": "mycli", "run": "{bin} --do {task}",
                                       "label": "Nightly release notes"})
check("and a name a person gives is the one kept",
      _err == "" and _entry["label"] == "Nightly release notes", str(_err))

_entry, _err = P.entry_from("custom", {"bin": "mycli", "run": "{bin} --do {task}",
                                       "label": "x" * 200})
check("a name too long for a table is refused, not truncated in silence",
      _entry is None and "name" in _err, str(_err))

_entry, _err = P.entry_from("custom", {"run": "{bin} --do {task}"})
check("Custom command without a bin is refused", _entry is None and "bin" in _err, str(_err))

_entry, _err = P.entry_from("custom", {"bin": "mycli"})
check("Custom command without a command line is refused",
      _entry is None and "run" in _err, str(_err))

_entry, _err = P.entry_from("custom", {"bin": "mycli", "run": "{bin} --do"})
check("a command line that never mentions the task is refused",
      _entry is None and "{task}" in _err, str(_err))

_entry, _err = P.entry_from("nope", {})
check("a preset nobody ships is refused by name",
      _entry is None and "nope" in _err, str(_err))

_entry, _err = P.entry_from("gemini", {"variant": "pro; rm -rf /"})
check("a variant that is not a model name never reaches a command line",
      _entry is None and "model name" in _err, str(_err))

_entry, _err = P.entry_from("qwen", {"variant": "qwen3-coder"})
check("a model name a command line has nowhere to put is refused, not quietly dropped",
      _entry is None and "{variant}" in _err, str(_err))

_entry, _err = P.entry_from("gemini", {"auth_env": "my key"})
check("a key variable that is not a variable name is refused",
      _entry is None and "environment variable" in _err, str(_err))


@contextlib.contextmanager
def farm():
    """A farm with no catalog of its own yet: the library reads the shipped example until
    something is added, and writes only inside this temporary directory."""
    with tempfile.TemporaryDirectory() as room:
        config = os.path.join(room, "config", "models.toml")
        state = os.path.join(room, "state", "models-state.json")
        old = (M.CONFIG, M.STATE, os.environ.get("FLEET_STATE"))
        M.CONFIG, M.STATE = config, state
        os.environ["FLEET_STATE"] = os.path.join(room, "state")
        try:
            yield pathlib.Path(room)
        finally:
            M.CONFIG, M.STATE, _state = old
            if _state is None:
                os.environ.pop("FLEET_STATE", None)
            else:
                os.environ["FLEET_STATE"] = _state


def toml_of(path):
    import tomllib
    with open(path, "rb") as handle:
        return tomllib.load(handle)


print()
print("writing this farm's own catalog")

with farm() as room:
    entry, err = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
    entry["id"] = "gemini"
    model, err = M.add_model(entry)
    check("adding a model answers the new row", err == "" and model["id"] == "gemini", str(err))
    check("the row is marked as one this farm added", model["source"] == "added")
    check("the row carries how it is paid for, and which model it runs",
          model["access"].startswith("an API key") and model["variant"] == "gemini-2.5-pro")
    check("the catalog is created from the shipped example on the first write, keeping both "
          "models fleet ships",
          set(toml_of(M.CONFIG)) == {"claude", "codex", "gemini"}, str(set(toml_of(M.CONFIG))))
    check("a shipped row stays shipped", M.effective("claude")["source"] == "shipped")
    check("the new model is in the listing once, not twice",
          [m["id"] for m in M.listing()].count("gemini") == 1)

with farm():
    entry, _ = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
    M.add_model(dict(entry, id="gemini"))
    model, err = M.add_model(dict(entry, id="gemini"))
    check("the same id is refused the second time",
          model is None and "already" in err, str(err))
    model, err = M.add_model(dict(entry, id="claude"))
    check("an id a shipped model already holds is refused",
          model is None and "already" in err, str(err))

with farm():
    entry, _ = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
    for bad in ("Gemini", "2fast", "a", "gem ini", "gem/ini", "x" * 32, ""):
        model, err = M.add_model(dict(entry, id=bad))
        check(f"an id a table name cannot hold is refused: {bad!r}",
              model is None and "model id" in err, str(err))
    check("a refused add leaves no catalog behind", not os.path.exists(M.CONFIG))

with farm():
    entry, _ = P.entry_from("custom", {"bin": "mycli",
                                       "run": 'mycli --say "hi" --path C:\\tools {task}'})
    model, err = M.add_model(dict(entry, id="mine"))
    check("a quote and a backslash survive the write", err == "", str(err))
    check("the catalog reads back exactly what was asked for",
          toml_of(M.CONFIG)["mine"]["run"] == 'mycli --say "hi" --path C:\\tools {task}',
          repr(toml_of(M.CONFIG)["mine"].get("run")))
    check("the escaped value is written as TOML, not as a bare string",
          '\\"hi\\"' in pathlib.Path(M.CONFIG).read_text())
    model, err = M.add_model(dict(entry, id="newline",
                                  label="two\nlines", run="{bin} {task}"))
    check("a newline in a value cannot end the line it is written on",
          err == "" and toml_of(M.CONFIG)["newline"]["label"] == "two\nlines", str(err))

print()
print("what a custom command is called")

with farm():
    _mine, _ = P.entry_from("custom", {"bin": "mycli", "run": "{bin} --do {task}"})
    M.add_model(dict(_mine, id="nightly"))
    _yours, _ = P.entry_from("custom", {"bin": "othercli", "run": "{bin} {task}"})
    M.add_model(dict(_yours, id="triage"))
    _named, _ = P.entry_from("custom", {"bin": "thirdcli", "run": "{bin} {task}",
                                        "label": "Release notes"})
    M.add_model(dict(_named, id="notes"))
    check("two custom commands are two names in the table, not one name twice",
          [M.effective(mid)["label"] for mid in ("nightly", "triage")] == ["nightly", "triage"],
          str([M.effective(mid)["label"] for mid in ("nightly", "triage")]))
    check("a name the person gave is the one the row shows",
          M.effective("notes")["label"] == "Release notes", M.effective("notes")["label"])
    check("and a preset's own label is still its label",
          M.effective("claude")["label"] == "Claude Code")

print()
print("a write that does not finish")

# The catalog is a file a person edits. A write that fails halfway (a full disk, a crash, two
# adds at the same moment) must leave the one they have exactly as it was: the new text goes to
# a temp file beside it and is renamed over the top, the one step a filesystem does whole.


@contextlib.contextmanager
def replace_fails():
    """os.replace, and only os.replace, refusing the way a full disk refuses."""
    real = os.replace

    def boom(*_args, **_kw):
        raise OSError(28, "No space left on device")

    os.replace = boom
    try:
        yield
    finally:
        os.replace = real


def beside(path):
    return sorted(entry.name for entry in pathlib.Path(path).parent.iterdir())


with farm():
    _entry, _ = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
    M.add_model(dict(_entry, id="gemini"))
    _before = pathlib.Path(M.CONFIG).read_text()
    _local, _ = P.entry_from("ollama", {"variant": "llama3.1"})
    with replace_fails():
        _model, _err = M.add_model(dict(_local, id="local"))
    check("an add that cannot finish leaves the operator's catalog exactly as it was",
          pathlib.Path(M.CONFIG).read_text() == _before, "the catalog was rewritten")
    check("and says so, instead of answering with a model it did not write",
          _model is None and "could not write" in _err, str(_err))
    check("and leaves nothing half written beside it", beside(M.CONFIG) == ["models.toml"],
          str(beside(M.CONFIG)))
    with replace_fails():
        _removed, _err = M.remove_model("gemini")
    check("a remove that cannot finish leaves it as it was too",
          pathlib.Path(M.CONFIG).read_text() == _before and _removed is None
          and "could not write" in _err, str(_err))
    check("so the row is still there to try again",
          "gemini" in toml_of(M.CONFIG) and beside(M.CONFIG) == ["models.toml"],
          str(beside(M.CONFIG)))

print()
print("taking a model back out")

with farm() as room:
    entry, _ = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
    M.add_model(dict(entry, id="gemini"))
    secret = pathlib.Path(M._secret_path("gemini"))
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("sk-not-a-real-key\n")
    M.set_enabled("gemini", False)
    removed, err = M.remove_model("gemini")
    check("a model this farm added can be removed", removed == "gemini" and err == "", str(err))
    check("its table is gone from the catalog", "gemini" not in toml_of(M.CONFIG))
    check("the two shipped models are untouched", set(toml_of(M.CONFIG)) == {"claude", "codex"})
    check("its stored key is deleted with it", not secret.exists())
    check("its runtime state is deleted with it", "gemini" not in M._state())
    check("removing it twice says so, rather than failing quietly",
          M.remove_model("gemini") == (None, "no such model: gemini"))

with farm():
    entry, _ = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
    M.add_model(dict(entry, id="gemini"))
    removed, err = M.remove_model("claude")
    check("a model fleet ships cannot be removed from here",
          removed is None and "came with fleet" in err, str(err))
    check("and it is still in the catalog", "claude" in toml_of(M.CONFIG))
    removed, err = M.remove_model("nope")
    check("removing something that was never there is an answer, not a crash",
          removed is None and "no such model" in err, str(err))

with farm():
    entry, _ = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
    M.add_model(dict(entry, id="gemini"))
    M.add_model(dict((P.entry_from("ollama", {"variant": "llama3.1"})[0]), id="local"))
    pathlib.Path(M.CONFIG).write_text(
        pathlib.Path(M.CONFIG).read_text().replace("[local]", "# a note about local\n[local]"))
    M.remove_model("gemini")
    check("a comment written above the next table stays with that table",
          "# a note about local" in pathlib.Path(M.CONFIG).read_text()
          and set(toml_of(M.CONFIG)) == {"claude", "codex", "local"})

print()
print("a catalog that parses to an empty document")

# A farm that adds a row and then takes it back out is left with a models.toml holding no
# tables at all. That is a valid, empty catalog: the page must read it as "no models here yet"
# and still be able to write the next one. Only a file that is not TOML is a file to fix by hand.

with farm():
    pathlib.Path(M.CONFIG).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(M.CONFIG).write_text("# every row this farm had has been taken back out\n")
    check("a catalog of comments is an empty catalog, not the shipped example",
          M.catalog() == {}, str(M.catalog()))
    entry, _ = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
    model, err = M.add_model(dict(entry, id="gemini"))
    check("and a model can still be added to it without a hand edit",
          err == "" and model is not None, str(err))
    check("the operator's own comment is still at the top of the file",
          pathlib.Path(M.CONFIG).read_text().startswith("# every row"))

with farm():
    pathlib.Path(M.CONFIG).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(M.CONFIG).write_text("")
    check("an empty file is an empty catalog too", M.catalog() == {}, str(M.catalog()))
    entry, _ = P.entry_from("ollama", {"variant": "llama3.1"})
    model, err = M.add_model(dict(entry, id="local"))
    check("and it takes the first row like any other catalog",
          err == "" and set(toml_of(M.CONFIG)) == {"local"}, str(err))

with farm():
    pathlib.Path(M.CONFIG).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(M.CONFIG).write_text('[half\nthis is not TOML at all\n')
    entry, _ = P.entry_from("gemini", {"variant": "gemini-2.5-pro"})
    model, err = M.add_model(dict(entry, id="gemini"))
    check("a catalog that is not TOML is still sent back to the operator",
          model is None and "could not be read as TOML" in err, str(err))
    check("and it is left exactly as it was found",
          pathlib.Path(M.CONFIG).read_text() == '[half\nthis is not TOML at all\n')
    check("a broken catalog falls back to the shipped example rather than to nothing",
          set(M.catalog()) == {"claude", "codex"}, str(set(M.catalog())))

print()
print("the word one row's status pill says")

# The status rules live with the route that serves them, so they are read from there: this is
# the same function the dashboard answers /api/engines with.
_spec = importlib.util.spec_from_file_location(
    "fleet_dashboard_server",
    pathlib.Path(__file__).resolve().parent.parent / "dashboard" / "server.py")
SERVER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SERVER)

CATALOG = """
[gone]
label  = "Gone"
engine = "generic"
bin    = "gone"
run    = "{bin} -p {task}"
source = "added"

[keyless]
label    = "Keyless"
engine   = "generic"
bin      = "keyless"
run      = "{bin} -p {task}"
auth_env = "KEYLESS_API_KEY"
source   = "added"

[broken]
label  = "Broken"
engine = "generic"
bin    = "broken"
run    = "{bin} -p {task}"
source = "added"

[live]
label   = "Live"
engine  = "generic"
bin     = "live"
run     = "{bin} run {variant} {task}"
variant = "llama3.1"
source  = "added"

[resting]
label  = "Resting"
engine = "generic"
bin    = "resting"
run    = "{bin} -p {task}"
source = "added"
"""

RUNTIME = {"broken": {"enabled": True, "health": "fail", "health_detail": "auth rejected"},
           "live": {"enabled": True, "health": "ok"},
           "resting": {"enabled": False, "health": "ok"}}


@contextlib.contextmanager
def machine(installed, env=None):
    """A farm holding exactly these commands, and nothing else on its PATH: a status must not
    come out different on a machine that happens to have gemini installed."""
    import json
    with farm() as room:
        pathlib.Path(M.CONFIG).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(M.CONFIG).write_text(CATALOG)
        pathlib.Path(M.STATE).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(M.STATE).write_text(json.dumps(RUNTIME))
        binaries = room / "bin"
        binaries.mkdir(exist_ok=True)
        for name in installed:
            tool = binaries / name
            tool.write_text("#!/bin/sh\nexit 0\n")
            tool.chmod(0o755)
        kept = {name: os.environ.get(name) for name in ("PATH", "KEYLESS_API_KEY")}
        os.environ["PATH"] = str(binaries)
        os.environ.pop("KEYLESS_API_KEY", None)
        os.environ.update(env or {})
        try:
            yield room
        finally:
            for name, value in kept.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            for name in (env or {}):
                if name not in kept:
                    os.environ.pop(name, None)


def statuses(installed, env=None):
    with machine(installed, env):
        return {row["id"]: row for row in SERVER.engines()}


_rows = statuses(["keyless", "broken", "live", "resting"])
check("a model whose command is not on this machine is not installed",
      _rows["gone"]["status"] == "not_installed", _rows["gone"]["status"])
check("a model with a key variable and no key anywhere needs a key",
      _rows["keyless"]["status"] == "needs_key", _rows["keyless"]["status"])
check("a model whose last test failed is failing",
      _rows["broken"]["status"] == "failing", _rows["broken"]["status"])
check("a model switched on whose test passed is on",
      _rows["live"]["status"] == "on", _rows["live"]["status"])
check("a model nobody switched on is off",
      _rows["resting"]["status"] == "off", _rows["resting"]["status"])
check("every status is one of the five the pill can say",
      all(row["status"] in SERVER.MODEL_STATUSES for row in _rows.values()))

_rows = statuses([])
check("a missing command outranks every other answer",
      [_rows[m]["status"] for m in ("gone", "keyless", "broken", "live", "resting")]
      == ["not_installed"] * 5)

_rows = statuses(["keyless"], env={"KEYLESS_API_KEY": "sk-not-a-real-key"})
check("a key in the environment answers the key question",
      _rows["keyless"]["status"] == "off", _rows["keyless"]["status"])

with machine(["keyless"]):
    _secret = pathlib.Path(M._secret_path("keyless"))
    _secret.parent.mkdir(parents=True, exist_ok=True)
    _secret.write_text("sk-not-a-real-key\n")
    _rows = {row["id"]: row for row in SERVER.engines()}
check("a key stored by `fleet models auth` answers it too",
      _rows["keyless"]["status"] == "off", _rows["keyless"]["status"])

_rows = statuses(["live"])
check("a row that never said how it is paid for is still given a sentence",
      "KEYLESS_API_KEY" in _rows["keyless"]["access"] and _rows["gone"]["access"].strip())
check("a row this farm added says so, and says which model it runs",
      _rows["live"]["source"] == "added" and _rows["live"]["variant"] == "llama3.1")

print()
print("the prompt a test request sends")

# The catalog calls the test prompt `health` and the runtime state calls the result `health`.
# The prompt has to survive the merge, or the test request asks the model "unchecked" and no
# generic model can ever pass a health check.
with machine(["live"]):
    _live = M.effective("live")
check("the last test's result is still the word everyone reads",
      _live["health"] == "ok", _live["health"])
check("and the prompt is kept under its own name",
      _live["health_prompt"] == "Reply with exactly: OK", _live["health_prompt"])

with farm() as room:
    _bin = room / "bin"
    _bin.mkdir()
    _echo = _bin / "echoback"
    _echo.write_text('#!/bin/sh\necho "$@"\n')
    _echo.chmod(0o755)
    pathlib.Path(M.CONFIG).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(M.CONFIG).write_text(
        '[echoback]\nlabel = "Echo"\nengine = "generic"\nbin = "%s"\n'
        'run = "{bin} -p {task}"\nhealth = "Reply with exactly: OK"\nsource = "added"\n'
        % _echo)
    _health, _detail, _limits = M.health_check("echoback")
check("a test request carries the catalog's prompt, not the state's word",
      _health == "ok", f"{_health}: {_detail}")

print()
print("a key never goes through this page")

# The route refuses a credential before it reads anything else. The check is on the field's
# name, so the casing a client happens to use cannot walk one past it, and on the command line
# itself, because a key pasted in there was written into models.toml verbatim.

with farm():
    _refused = []
    for _field in ("key", "apiKey", "API_KEY", "x-api-key", "Token", "Secret", "credential"):
        _status, _payload = SERVER.add_model_request(
            {"preset": "gemini", "id": "g1", "variant": "gemini-2.5-pro",
             _field: "sk-live-not-a-real-key"})
        _refused.append((_field, _status, "never goes through this page"
                         in str(_payload.get("error", ""))))
    check("a credential is refused whatever the field is called",
          all(status == 400 and said for _f, status, said in _refused), str(_refused))
    _status, _payload = SERVER.add_model_request(
        {"preset": "custom", "id": "c1", "bin": "echo",
         "run": "{bin} --api-key sk-live-not-a-real-key -p {task}"})
    check("a key pasted into the command line never reaches the catalog",
          _status == 400 and not os.path.exists(M.CONFIG), str(_payload))
    _status, _payload = SERVER.add_model_request(
        {"preset": "custom", "id": "mine", "bin": "mycli",
         "run": "{bin} --api-key $MY_API_KEY -p {task}", "auth_env": "MY_API_KEY"})
    check("a command that reads its key from the environment is still written",
          _status == 200, str(_payload))

print()
print("where a test request runs")

# Pressing Test runs a real coding agent, and some of them (aider says so in its own tos line)
# edit and commit in the directory they are started in. The dashboard's working directory is the
# fleet checkout, so the command gets an empty room of its own instead.

with farm() as room:
    _bin = room / "bin"
    _bin.mkdir(exist_ok=True)
    _where = room / "where.txt"
    _tool = _bin / "pwdback"
    _tool.write_text("#!/bin/sh\npwd > '" + str(_where) + "'\n"
                     "touch fleet-test-request-was-here\necho OK\n")
    _tool.chmod(0o755)
    pathlib.Path(M.CONFIG).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(M.CONFIG).write_text(
        '[pwdback]\nlabel = "Pwd"\nengine = "generic"\nbin = "' + str(_tool) + '"\n'
        'run = "{bin} -p {task}"\nsource = "added"\n')
    _health, _detail, _limits = M.health_check("pwdback")
    _ran_in = _where.read_text().strip() if _where.exists() else ""
_litter = pathlib.Path.cwd() / "fleet-test-request-was-here"
check("a test request runs somewhere other than the directory the dashboard was started in",
      _ran_in and _ran_in != str(pathlib.Path.cwd()), f"ran in {_ran_in!r}")
check("and that room is thrown away with the answer",
      _ran_in and not os.path.exists(_ran_in), f"{_ran_in!r} is still there")
check("so a model that writes files leaves nothing in the checkout",
      not _litter.exists(), str(_litter))
if _litter.exists():
    _litter.unlink()

print()
print("the model a person picks reaches the command")

# Step 2 of the dialog offers a choice of models. It is only a choice if the name lands on the
# command line: both the test request and the command the launcher runs are checked here, on a
# fake binary that writes down its own argv.


def launchcmd(room, mid, taskfile="/tmp/no-such-task"):
    """What `models.py launchcmd` prints: the line bin/fleet's generic engine runs."""
    env = dict(os.environ)
    env["FLEET_CONFIG"] = str(room / "config")
    env["FLEET_STATE"] = str(room / "state")
    done = subprocess.run([sys.executable, str(LIB / "models.py"), "launchcmd", mid, taskfile],
                          capture_output=True, text=True, env=env)
    return done.stdout.strip()


with farm() as room:
    _bin = room / "bin"
    _bin.mkdir(exist_ok=True)
    _argv = room / "argv.txt"
    _tool = _bin / "argvback"
    _tool.write_text("#!/bin/sh\n: > '" + str(_argv) + "'\n"
                     'for a in "$@"; do echo "$a" >> ' + "'" + str(_argv) + "'; done\n"
                     "echo OK\n")
    _tool.chmod(0o755)
    _secret = pathlib.Path(M._secret_path("g2"))
    _secret.parent.mkdir(parents=True, exist_ok=True)
    _secret.write_text("not-a-real-key\n")
    _entry, _err = P.entry_from("gemini", {"variant": "gemini-2.5-flash", "bin": str(_tool)})
    _model, _err = M.add_model(dict(_entry, id="g2"))
    _health, _detail, _limits = M.health_check("g2")
    _seen = _argv.read_text().split() if _argv.exists() else []
    _cmd = launchcmd(room, "g2")
check("a test request runs the model the person picked, not the CLI's default",
      "gemini-2.5-flash" in _seen, str(_seen))
check("and the test request still passes on a CLI that answers", _health == "ok",
      f"{_health}: {_detail}")
check("the line the launcher runs carries the model too",
      "gemini-2.5-flash" in _cmd and "$(cat " in _cmd, _cmd)

print()
print("where this suite runs")

# A suite nobody runs is a suite that goes green on a change it should have caught, so the
# workflow is read for the line that runs this file.

WORKFLOW = (pathlib.Path(__file__).resolve().parents[2]
            / ".github" / "workflows" / "fleet-tests.yml")
_workflow = WORKFLOW.read_text() if WORKFLOW.exists() else ""
check("this suite is named in the workflow, so a catalog change is checked on every pull request",
      "tests/models-test.py" in _workflow, str(WORKFLOW))
check("and the dashboard's own suite is too",
      "dashboard/test_server.py" in _workflow, str(WORKFLOW))

print()
print("house style")

# English, and no em-dash anywhere: a repository rule, and one a reader of a FAIL line meets
# first. The files this page is made of are read for one, so the next one is caught here rather
# than in review.

FILES = [LIB / "models.py", LIB / "model_presets.py",
         pathlib.Path(__file__).resolve(),
         pathlib.Path(__file__).resolve().parent.parent / "dashboard" / "server.py",
         pathlib.Path(__file__).resolve().parent.parent / "dashboard" / "test_server.py",
         pathlib.Path(__file__).resolve().parent.parent / "config" / "models.example.toml",
         pathlib.Path(__file__).resolve().parent.parent / "docs" / "OPERATIONS.md"]
_dashed = [f"{path.name}:{number}"
           for path in FILES if path.exists()
           for number, line in enumerate(path.read_text().splitlines(), 1)
           if "\u2014" in line]
check("no em-dash in the files the models page is made of", _dashed == [], str(_dashed))

print()
print("RESULT: " + ("ALL PASS" if ok else "FAILURES"))
sys.exit(0 if ok else 1)
