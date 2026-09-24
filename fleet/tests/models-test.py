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
      _ids == ["claude", "codex", "gemini", "qwen", "kimi", "grok", "opencode", "aider", "ollama",
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
check("Qwen Code names the model it runs with --model",
      _by["qwen"]["run"] == "{bin} --model {variant} -p {task} --output-format stream-json"
      and _by["qwen"]["install_hint"] == "npm install -g @qwen-code/qwen-code"
      and _by["qwen"]["auth_env"] == "QWEN_CODE_API_KEY")
check("Kimi Code names the key plan as the permitted path, not the subscription",
      "forbid non-interactive use" in _by["kimi"]["tos"]
      and "api key" in _by["kimi"]["access"].lower()
      and _by["kimi"]["auth_env"] == "KIMI_API_KEY")
check("Grok Build is xAI's own CLI, headless on the API key, with the model on the command line",
      _by["grok"]["install_hint"] == "curl -fsSL https://x.ai/cli/install.sh | bash"
      and _by["grok"]["run"] == ("{bin} --no-auto-update --always-approve -p {task} -m {variant} "
                                 "--output-format streaming-json")
      and _by["grok"]["auth_env"] == "XAI_API_KEY"
      and _by["grok"]["variants"])
check("OpenCode runs `opencode run -m` and installs from its own script",
      _by["opencode"]["run"] == "{bin} run -m {variant} {task}"
      and _by["opencode"]["install_hint"] == "curl -fsSL https://opencode.ai/install | bash"
      and "ANTHROPIC_API_KEY" in _by["opencode"]["access"])
check("Aider runs one message on the chosen model and answers its own prompts",
      _by["aider"]["run"] == "{bin} --model {variant} --message {task} --yes"
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

_entry, _err = P.entry_from("custom", {"bin": "mycli", "run": "{bin} -p {task}",
                                       "variant": "qwen3-coder"})
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
      _live["health_prompt"] == P.HEALTH, _live["health_prompt"])
check("the prompt does not hold its own answer",
      P.HEALTH_ANSWER not in P.HEALTH and not M.answered(P.HEALTH), P.HEALTH)

def fake_model(room, name, script, health=None):
    """A generic row whose CLI is `script`, first in its own bin directory. `health` is the
    prompt the row was written with; None leaves it out, as a hand-written row may."""
    binp = room / "bin"
    binp.mkdir(exist_ok=True)
    tool = binp / name
    tool.write_text("#!/bin/sh\n" + script)
    tool.chmod(0o755)
    pathlib.Path(M.CONFIG).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(M.CONFIG).write_text(
        '[%s]\nlabel = "%s"\nengine = "generic"\nbin = "%s"\nrun = "{bin} -p {task}"\n'
        % (name, name, tool)
        + ('' if health is None else 'health = "%s"\n' % health)
        + 'source = "added"\n')
    return M.health_check(name)


# A CLI that only says back what it was sent: with a bad key some do exactly that, or quote the
# prompt in their error. "Reply with exactly: OK" held its own pass word, so this passed.
with farm() as room:
    _health, _detail, _limits = fake_model(room, "echoback", 'echo "$@"\n', P.HEALTH)
check("a CLI that only echoes the prompt fails the Test",
      _health == "fail", f"{_health}: {_detail}")

with farm() as room:
    _health, _detail, _limits = fake_model(room, "echoold", 'echo "$@"\n', P.LEGACY_HEALTH)
check("a row still written with the old prompt is asked the new one, so an echo fails it too",
      _health == "fail", f"{_health}: {_detail}")

# The echo above fails whichever prompt it is sent, so it cannot tell whether the row was moved to
# the new one. This CLI answers each question truthfully: it passes only if it is asked the sum.
with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "oldrow", 'case "$*" in *"17 plus 25"*) echo 42;; *"exactly: OK"*) echo OK;;\n'
        '*) echo "$@";; esac\n', P.LEGACY_HEALTH)
check("a row still written with the old prompt passes because it is asked the sum",
      _health == "ok", f"{_health}: {_detail}")

# A hand-written row with a prompt of its own: its answer is not 42, and the Test asks every model
# the same question, so the row is asked the sum too.
with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "customrow", 'case "$*" in *"17 plus 25"*) echo 42;; *) echo OK;; esac\n',
        "Confirm you can respond to a request.")
check("a row with a custom prompt passes because it is asked the sum",
      _health == "ok", f"{_health}: {_detail}")

with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "sums", 'case "$*" in *"17 plus 25"*) echo 42;; *) echo "$@";; esac\n', P.HEALTH)
check("a test request carries the catalog's prompt, not the state's word",
      _health == "ok", f"{_health}: {_detail}")

with farm() as room:
    _bin = room / "bin"
    _bin.mkdir()
    _grok = _bin / "grokfail"
    # What Grok Build prints for a key or model it cannot use: its own name, "grok models",
    # carries the letters OK, and a Test that matched letters passed it.
    _grok.write_text("#!/bin/sh\n"
                     "echo '{\"type\":\"error\",\"message\":\"Could not set model grok-4.7: "
                     "unknown model id. Run grok models to see available models.\"}'\n"
                     "exit 1\n")
    _grok.chmod(0o755)
    pathlib.Path(M.CONFIG).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(M.CONFIG).write_text(
        '[grokfail]\nlabel = "Grok"\nengine = "generic"\nbin = "%s"\n'
        'run = "{bin} -p {task}"\nhealth = "%s"\nsource = "added"\n'
        % (_grok, P.HEALTH))
    _health, _detail, _limits = M.health_check("grokfail")
check("a failing CLI whose error mentions grok or tokens does not pass the Test",
      _health == "fail", f"{_health}: {_detail}")

print()
print("what a real CLI prints around the answer")

# The reply is read as a person would read it: what a terminal or a JSON stream wraps around the
# number is taken off, and anything that makes it a different number is not.
check("a colour code around the answer passes", M.answered("\x1b[1;32m42\x1b[0m\n"))
check("an escaped newline right before the answer in JSON passes",
      M.answered('{"type":"result","result":"Sure.\\n42"}'))
check("escaped curly quotes around the answer in JSON pass",
      M.answered('{"text":"\\u201c42\\u201d"}'))
check("straight quotes around the answer pass", M.answered("'42'") and M.answered('"42"'))
check("curly quotes around the answer pass", M.answered("\u201c42\u201d"))
check("the Test asks for the number alone, so a sentence that ends on it does not pass",
      not M.answered("The answer is 42."))
check("the answer with one trailing period passes", M.answered("42.\n"))
check("a coloured answer in quotes with a trailing period passes",
      M.answered("\x1b[32m\u201c42\u201d.\x1b[0m\n") and M.answered("`42`\n"))
check("-42 does not pass", not M.answered("-42"))
check("42 with two trailing periods does not pass", not M.answered("42..\n"))
check("420 does not pass", not M.answered("420"))
check("4.2 does not pass", not M.answered("4.2"))
check("an id that holds the digits does not pass", not M.answered("request req_a42f failed"))
check("an HTTP 429 does not pass", not M.answered("HTTP 429 Too Many Requests"))

# Only what the model said counts. A JSON line's usage, ids and error fields are not its reply,
# and a CLI that exited non-zero failed whatever else it printed.
_BADKEY = '{"type":"error","message":"invalid API key","usage":{"input_tokens":42}}'
check("42 in a token count does not pass",
      not M.answered('{"type":"result","result":"done","usage":{"output_tokens":42}}'))
check("42 as an id does not pass", not M.answered('{"id":"42","text":"no idea"}'))
check("42 in an error event's metadata does not pass", not M.answered(_BADKEY))
check("the answer in a stream-json message passes",
      M.answered('{"type":"assistant","message":{"content":[{"type":"text","text":"42"}]}}'))
check("the answer in a codex item passes",
      M.answered('{"type":"item.completed","item":{"type":"agent_message","text":"42"}}'))

# Gemini's --output-format json writes one object across many lines (JSON.stringify(o, null, 2)),
# so no line parses alone and a line reader took its stats for words.
_GEMINI = ('{\n  "response": "%s",\n  "stats": {\n    "models": {\n      "gemini-2.5-pro": {\n'
           '        "tokens": {\n          "input": 42\n        }\n      }\n    }\n  }\n}\n')
check("an indented JSON reply whose only 42 is a token count does not pass",
      not M.answered(_GEMINI % "I cannot answer"))
check("an indented JSON reply that says 42 passes", M.answered(_GEMINI % "42"))

with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "geminiwrong", "cat <<'JSON'\n%sJSON\n" % (_GEMINI % "I cannot answer"), P.HEALTH)
check("a Gemini-shaped CLI that answers wrong fails the Test even with 42 in its stats",
      _health == "fail", f"{_health}: {_detail}")

with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "geminiright", "cat <<'JSON'\n%sJSON\n" % (_GEMINI % "42"), P.HEALTH)
check("a Gemini-shaped CLI whose response is 42 passes the Test",
      _health == "ok", f"{_health}: {_detail}")

# A notice before the document (a cached-settings line, an update hint) made the whole stdout
# unparseable, and the line reader then took the document's stats for words. Once any JSON
# document parses, only its reply fields count and nothing printed around it does.
_NOTICE = "Notice: using cached settings\n" + _GEMINI
check("a notice before an indented JSON reply whose only 42 is a token count does not pass",
      not M.answered(_NOTICE % "I cannot answer"))
check("a notice before an indented JSON reply that says 42 passes",
      M.answered(_NOTICE % "42"))

with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "noticewrong", "cat <<'JSON'\n%sJSON\n" % (_NOTICE % "I cannot answer"), P.HEALTH)
check("a CLI that prints a notice, then JSON with 42 only in its stats, fails the Test",
      _health == "fail", f"{_health}: {_detail}")

with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "noticeright", "cat <<'JSON'\n%sJSON\n" % (_NOTICE % "42"), P.HEALTH)
check("a CLI that prints a notice, then JSON whose response is 42, passes the Test",
      _health == "ok", f"{_health}: {_detail}")

# With no document to parse, the plain reading applies, but a line shaped like a JSON member is a
# fragment of bookkeeping, never the model's words.
check("a JSON member line in otherwise plain output does not pass",
      not M.answered('I cannot answer that.\n  "input_tokens": 42,\nDone.\n'))
check("the Test asks for the number alone, so plain output with 42 in a sentence does not pass",
      not M.answered("Thinking...\nThe answer is 42\n"))
check("plain output with 42 alone on a line passes", M.answered("Thinking...\n  42  \n"))

# The Test asks for the number only, so the answer is a line that is the number and nothing else.
# A count in a footer is on a line of its own words, and a sign makes it a different number.
check("I cannot answer, then a usage footer with 42, does not pass",
      not M.answered("I cannot answer\nUsage: 42 tokens consumed\n"))
with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "plainfooter", "printf 'I cannot answer\\nUsage: 42 tokens consumed\\n'\n", P.HEALTH)
check("a plain-text CLI that cannot answer, then a 42 usage footer, fails the Test",
      _health == "fail", f"{_health}: {_detail}")
with farm() as room:
    _health, _detail, _limits = fake_model(room, "minus", "echo -42\n", P.HEALTH)
check("a plain-text CLI that says -42 fails the Test", _health == "fail", f"{_health}: {_detail}")

# A JSON-lines stream is a run of documents: the reply in an early event counts, and the usage in
# the closing one does not, whatever notice came first.
check("a notice, then a codex event stream whose message is 42, passes",
      M.answered('Reading config\n'
                 '{"type":"item.completed","item":{"type":"agent_message","text":"42"}}\n'
                 '{"type":"turn.completed","usage":{"input_tokens":7}}\n'))
check("a notice, then a codex event stream whose only 42 is usage, does not pass",
      not M.answered('Reading config\n'
                     '{"type":"item.completed","item":{"type":"agent_message","text":"no"}}\n'
                     '{"type":"turn.completed","usage":{"input_tokens":42}}\n'))

# A footer after the document (a usage line) made the whole stdout unparseable, and the plain
# reading then took the footer's 42 for words. Wherever documents sit in the output, text outside
# them is never the model.
_FOOTER = '{"response":"%s"}\nUsage: 42 tokens consumed\n'
check("JSON that cannot answer, then a usage footer with 42, does not pass",
      not M.answered(_FOOTER % "I cannot answer"))
check("JSON whose response is 42, then the same footer, passes", M.answered(_FOOTER % "42"))

with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "footerwrong", "cat <<'JSON'\n%sJSON\n" % (_FOOTER % "I cannot answer"), P.HEALTH)
check("a CLI that prints JSON that cannot answer, then a 42 usage footer, fails the Test",
      _health == "fail", f"{_health}: {_detail}")

with farm() as room:
    _health, _detail, _limits = fake_model(
        room, "footerright", "cat <<'JSON'\n%sJSON\n" % (_FOOTER % "42"), P.HEALTH)
check("a CLI that prints JSON whose response is 42, then a usage footer, passes the Test",
      _health == "ok", f"{_health}: {_detail}")

_SANDWICH = ('Notice: using cached settings\n'
             '{"type":"item.completed","item":{"type":"agent_message","text":"%s"}}\n'
             '{"type":"turn.completed","usage":{"input_tokens":7}}\n'
             'Done in 42 ms\n')
check("a notice, JSON lines that cannot answer, and a 42 footer do not pass",
      not M.answered(_SANDWICH % "no idea"))
check("a notice, JSON lines whose message is 42, and a footer pass",
      M.answered(_SANDWICH % "42"))

# Plain text that happens to hold brackets is still plain text, and still answers.
check("the Test asks for the number alone, so a sentence with a footnote does not pass",
      not M.answered("The answer is 42 [1]\n[1] arithmetic\n"))
check("plain output that is 42, then a footnote in brackets, passes",
      M.answered("42\n[1] arithmetic\n"))

with farm() as room:
    _health, _detail, _limits = fake_model(room, "badkey", "echo '%s'\nexit 1\n" % _BADKEY,
                                           P.HEALTH)
check("a CLI that exits 1 with 42 only in its error metadata fails the Test",
      _health == "fail", f"{_health}: {_detail}")
check("and the reason names the exit code and the error line",
      "code 1" in _detail and "invalid API key" in _detail, _detail)

with farm() as room:
    _health, _detail, _limits = fake_model(room, "saysthenfails", "echo 42\nexit 2\n", P.HEALTH)
check("a CLI that says 42 and exits 2 still fails the Test",
      _health == "fail" and "code 2" in _detail, f"{_health}: {_detail}")

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
                     "touch fleet-test-request-was-here\necho 42\n")
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
                     "echo 42\n")
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
print("the one model rule")

# One rule for every model name that reaches a command line (design section 5). A letter or a
# digit first, so no name can ever be read as an option by the CLI it is handed to.

for _name in ("sonnet", "opus[1m]", "sonnet[1m]", "claude-opus-4-6[1m]", "gpt-6-sol",
              "kimi-code/kimi-for-coding", "qwen2.5-coder:7b", "MiniMax-M2.5"):
    check(f"the rule takes {_name}", bool(P.MODEL_RE.match(_name)))
for _name in ("-rf", "--model", "", "a b", "x;rm", "$(id)", "'q'", "a" * 81, "[1m]"):
    check(f"the rule refuses {_name[:20]!r}", not P.MODEL_RE.match(_name))
check("VARIANT_RE is gone: one rule, not two", not hasattr(P, "VARIANT_RE"))
check("every preset whose command takes a model offers a docs list for the Add dialog",
      all(p["variants"] for p in P.PRESETS if "{variant}" in p["run"]),
      str([p["id"] for p in P.PRESETS if "{variant}" in p["run"] and not p["variants"]]))
check("every generic preset except Custom now carries {variant} in its run",
      all("{variant}" in p["run"] for p in P.PRESETS
          if p["engine"] == "generic" and p["id"] != "custom"))
check("the model flags are the ones each CLI documents",
      "--model {variant}" in _by["qwen"]["run"] and "-m {variant}" in _by["kimi"]["run"]
      and "run -m {variant}" in _by["opencode"]["run"]
      and "--model {variant}" in _by["aider"]["run"])


# ---------------------------------------------------------------- a sandbox for the rest
#
# Every check below runs in a throwaway world: its own FLEET_CONFIG, FLEET_STATE and HOME, and a
# PATH whose first directory holds fake `codex`, `opencode` and `claude` executables that write
# down their argv and never reach a provider. The Qwen and Kimi files hold a planted fake key.

PLANTED = "sk-planted-fake-key-0123456789abcdef"
PLANTED_TOKEN = "planted-kimi-token-9876543210"
FLEET_BIN = pathlib.Path(__file__).resolve().parent.parent / "bin" / "fleet"

CODEX_JSON = """{"models": [
 {"slug": "gpt-6-sol", "display_name": "GPT-6 Sol", "description": "the daily one",
  "visibility": "list", "supported_in_api": true, "supported_reasoning_levels": ["low"]},
 {"slug": "gpt-6-hidden", "display_name": "Hidden", "description": "not for you",
  "visibility": "hide"},
 {"slug": "gpt-6-none", "display_name": "None", "visibility": "none"},
 {"slug": "-rf", "display_name": "an option", "visibility": "list"},
 {"slug": "gpt-6-luna", "display_name": "GPT-6 Luna", "visibility": "list",
  "base_instructions": "a long prompt nobody asked for"}
]}"""

QWEN_SETTINGS = """{
  "security": {"auth": {"selectedType": "openai"}},
  "modelProviders": {
    "openai": [
      {"id": "qwen3-coder-plus", "name": "Qwen3 Coder Plus",
       "description": "coding, key %s inside", "baseUrl": "https://example.invalid/v1",
       "envKey": "QWEN_KEY", "apiKey": "%s",
       "generationConfig": {"timeout": 60000}},
      {"id": "glm-5", "name": "GLM-5"}
    ]
  },
  "env": {"QWEN_API_KEY": "%s"}
}""" % (PLANTED, PLANTED, PLANTED)

KIMI_CONFIG = """default_model = "kimi-code/kimi-for-coding"

[providers.kimi-code]
type = "kimi"
base_url = "https://example.invalid/coding/v1"
api_key = "%s"

[models."kimi-code/kimi-for-coding"]
provider = "kimi-code"
model = "kimi-for-coding"
display_name = "Kimi for Coding %s"
max_context_size = 262144
""" % (PLANTED_TOKEN, PLANTED_TOKEN)


def _fake(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


@contextlib.contextmanager
def world(catalog=None, state=None):
    """(room, env) with the library, the environment and every subprocess pointed inside it."""
    import json
    with tempfile.TemporaryDirectory(prefix="fleet-models-world-") as raw:
        room = pathlib.Path(raw)
        home, bins, config, st = room / "home", room / "bin", room / "config", room / "state"
        for folder in (home, bins, config, st):
            folder.mkdir()
        calls = room / "calls.txt"
        calls.write_text("")
        record = f'echo "$(basename "$0") $*" >> "{calls}"\n'
        _fake(bins / "codex", record + 'if [ "$1 $2" = "debug models" ]; then\n'
              '  [ -f "$HOME/codex-mode" ] && mode="$(cat "$HOME/codex-mode")"\n'
              '  case "$mode" in\n'
              '    slow) sleep 30;;\n'
              '    garbage) echo "not json at all, and a key ' + PLANTED + '";;\n'
              '    fail) echo "error: ' + PLANTED + '" >&2; exit 3;;\n'
              '    *) cat "$HOME/codex-models.json";;\n'
              '  esac\n  exit 0\nfi\nexit 9\n')
        (home / "codex-models.json").write_text(CODEX_JSON)
        _fake(bins / "opencode", record + 'if [ "$1" = "models" ]; then\n'
              '  printf "openai/gpt-6-sol\\nanthropic/claude-sonnet-5\\n\\nopenai/gpt-6-sol\\n"\n'
              '  exit 0\nfi\nexit 9\n')
        _fake(bins / "claude", record + "exit 9\n")
        for tool in ("tmux", "systemctl", "hq", "gh"):
            _fake(bins / tool, "exit 0\n")
        _fake(bins / "systemd-run", record + "exit 0\n")
        (home / ".qwen").mkdir()
        (home / ".qwen" / "settings.json").write_text(QWEN_SETTINGS)
        (home / ".kimi").mkdir()
        (home / ".kimi" / "config.toml").write_text(KIMI_CONFIG)
        (home / ".claude").mkdir()
        (home / ".claude" / ".credentials.json").write_text("{}")
        (config / "policy.toml").write_text("[hq]\nenabled = false\n")
        if catalog is not None:
            (config / "models.toml").write_text(catalog)
        if state is not None:
            (st / "models-state.json").write_text(json.dumps(state))
        env = {"HOME": str(home), "FLEET_CONFIG": str(config), "FLEET_STATE": str(st),
               "PATH": str(bins) + ":/usr/local/bin:/usr/bin:/bin",
               "CODEX_BIN": str(bins / "codex"), "CLAUDE_BIN": str(bins / "claude"),
               "OLLAMA_HOST": "127.0.0.1:9", "FLEET_LHM_URL": "http://127.0.0.1:9"}
        names = list(env) + ["FLEET_CODEX_MODEL", "CODEX_DEFAULT_MODEL", "FLEET_CODEX_BIN"]
        kept = {name: os.environ.get(name) for name in names}
        old = (M.CONFIG, M.STATE)
        for name in ("FLEET_CODEX_MODEL", "CODEX_DEFAULT_MODEL", "FLEET_CODEX_BIN"):
            os.environ.pop(name, None)
        os.environ.update(env)
        M.CONFIG, M.STATE = str(config / "models.toml"), str(st / "models-state.json")
        try:
            yield room, calls
        finally:
            M.CONFIG, M.STATE = old
            for name, value in kept.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def fleet(*args, timeout=60):
    return subprocess.run([str(FLEET_BIN)] + list(args), capture_output=True, text=True,
                          env=dict(os.environ), timeout=timeout)


import model_discovery as D  # noqa: E402

PROVIDERS = """
[qwen]
label  = "Qwen Code"
engine = "generic"
preset = "qwen"
bin    = "qwen"
run    = "{bin} --model {variant} -p {task}"
variant = "qwen3-coder-plus"
source = "added"

[kimi]
label  = "Kimi Code"
engine = "generic"
preset = "kimi"
bin    = "kimi"
run    = "{bin} -m {variant} -p {task}"
variant = "kimi-code/kimi-for-coding"
source = "added"

[opencode]
label  = "OpenCode"
engine = "generic"
preset = "opencode"
bin    = "opencode"
run    = "{bin} run -m {variant} {task}"
variant = "openai/gpt-6-sol"
source = "added"

[ollama]
label  = "Ollama local"
engine = "generic"
preset = "ollama"
bin    = "ollama"
run    = "{bin} run {variant} {task}"
variant = "llama3.1"
source = "added"

[gemini]
label  = "Gemini CLI"
engine = "generic"
preset = "gemini"
bin    = "gemini"
run    = "{bin} -m {variant} -p {task}"
variant = "gemini-2.5-pro"
source = "added"

[oldqwen]
label  = "Qwen, added before models"
engine = "generic"
preset = "qwen"
bin    = "qwen"
run    = "{bin} -p {task}"
source = "added"

[mine]
label  = "Mine"
engine = "generic"
preset = "custom"
bin    = "mine"
run    = "{bin} --model {variant} {task}"
variant = "house-model"
source = "added"
"""


def full_catalog():
    example = (pathlib.Path(__file__).resolve().parent.parent / "config"
               / "models.example.toml").read_text()
    return example + PROVIDERS


def discover_cli(provider):
    import json
    done = fleet("models", "discover", provider, "--json")
    try:
        return json.loads(done.stdout), done
    except ValueError:
        return None, done


def leaked(*texts):
    return [t[:80] for t in texts if PLANTED in str(t) or PLANTED_TOKEN in str(t)]


print()
print("where a provider's model list comes from")

with world(full_catalog()) as (room, calls):
    _codex, _done = discover_cli("codex")
    _calls = calls.read_text()
    check("Codex is asked with `codex debug models`, the binary lanes use",
          "codex debug models" in _calls, _calls)
    check("and only its listed rows are kept",
          _codex and [m["id"] for m in _codex["models"]] == ["gpt-6-sol", "gpt-6-luna"],
          str(_codex))
    check("the answer says it came from the account",
          _codex and _codex["source"] == "account" and _codex["error"] == "", str(_codex))
    check("only id, label, description, cost_note and on are kept from anything the CLI printed",
          _codex and all(set(m) == {"id", "label", "description", "cost_note", "on"}
                         for m in _codex["models"]),
          str(_codex))
    check("a label and a description come through as label and description",
          _codex and _codex["models"][0]["label"] == "GPT-6 Sol"
          and _codex["models"][0]["description"] == "the daily one", str(_codex))
    check("and a description never asks: no Codex model carries a cost note",
          _codex and all(m["cost_note"] == "" for m in _codex["models"]), str(_codex))
    check("an id that would read as an option is dropped, not offered",
          _codex and "-rf" not in [m["id"] for m in _codex["models"]])

    _qwen, _done = discover_cli("qwen")
    check("Qwen Code is read from ~/.qwen/settings.json modelProviders",
          _qwen and [m["id"] for m in _qwen["models"]] == ["qwen3-coder-plus", "glm-5"]
          and _qwen["source"] == "account", str(_qwen))
    check("the planted key in the Qwen file is in no answer, no stdout and no stderr",
          not leaked(json_text := __import__("json").dumps(_qwen), _done.stdout, _done.stderr),
          str(leaked(json_text, _done.stdout, _done.stderr)))
    check("and a key written into a description is scrubbed out of it",
          _qwen and "[redacted]" in _qwen["models"][0]["description"], str(_qwen))
    _human = fleet("models", "discover", "qwen")
    check("the human listing leaks no key either",
          not leaked(_human.stdout, _human.stderr) and "qwen3-coder-plus" in _human.stdout,
          _human.stdout)

    _kimi, _done = discover_cli("kimi")
    check("Kimi Code is read from ~/.kimi/config.toml [models.*], keyed by the alias kimi -m takes",
          _kimi and [m["id"] for m in _kimi["models"]] == ["kimi-code/kimi-for-coding"]
          and _kimi["source"] == "account", str(_kimi))
    check("the planted token in the Kimi file is in no answer, stdout or stderr",
          not leaked(__import__("json").dumps(_kimi), _done.stdout, _done.stderr), str(_kimi))

    _open, _done = discover_cli("opencode")
    check("OpenCode is asked with `opencode models`, without --refresh",
          "opencode models" in calls.read_text() and "--refresh" not in calls.read_text())
    check("and each provider/model line is one model, once",
          _open and [m["id"] for m in _open["models"]]
          == ["openai/gpt-6-sol", "anthropic/claude-sonnet-5"], str(_open))

    _claude, _done = discover_cli("claude")
    check("Claude Code answers the docs list, and the claude binary is never run",
          _claude and _claude["source"] == "docs" and _claude["error"] == ""
          and "claude " not in calls.read_text()
          and {"sonnet", "opus", "haiku", "fable", "opus[1m]"}
          <= {m["id"] for m in _claude["models"]}, str(_claude))
    check("the models already on are marked on",
          _claude and {m["id"] for m in _claude["models"] if m["on"]}
          == {"sonnet", "opus", "haiku"}, str(_claude))
    _noted = {m["id"]: m["cost_note"] for m in (_claude or {}).get("models", []) if m["cost_note"]}
    check("the cost note is on exactly Fable and the credit-billed [1m] ids, decided by the server",
          set(_noted) == {"fable", "claude-opus-4-6[1m]", "claude-sonnet-4-6[1m]"}
          and "usage credits" in _noted["fable"], str(_noted))
    check("and the docs descriptions never carry it",
          _claude and all("usage credits" not in m["description"] for m in _claude["models"]),
          str(_claude))
    _gem, _done = discover_cli("gemini")
    check("Gemini CLI answers the docs list, holding no key and calling nothing",
          _gem and _gem["source"] == "docs" and "gemini-2.5-pro" in
          [m["id"] for m in _gem["models"]], str(_gem))
    _mine, _done = discover_cli("mine")
    check("a custom command has no list, and says so rather than answering the press with nothing",
          _mine == {"source": "docs", "models": [], "error": D.FAILURES["no_list"]}, str(_mine))
    check("every preset but Custom has a way to list its models: a route or a documented list "
          "(Grok Build arrived after the lists were written and its button did nothing)",
          all(p["id"] == "custom" or p["id"] in D.ROUTES or D.DOCS.get(p["id"])
              for p in P.PRESETS),
          str([p["id"] for p in P.PRESETS
               if p["id"] != "custom" and p["id"] not in D.ROUTES and not D.DOCS.get(p["id"])]))
    _grok = D.discover({"preset": "grok", "id": "grok"})
    check("Grok Build answers its documented models",
          [m["id"] for m in _grok["models"]] == ["grok-4.7", "grok-build-0.1"] and not _grok["error"],
          str(_grok))
    _none = fleet("models", "discover", "nosuch")
    check("an unknown provider is a sentence and a non-zero exit",
          _none.returncode != 0 and "no such provider" in _none.stderr, _none.stderr)
    check("no discovery sent a prompt: the only calls were the two listing commands",
          all(line.split()[:3] in (["codex", "debug", "models"], ["opencode", "models"])
              for line in calls.read_text().splitlines()), calls.read_text())


class _Tags(__import__("http.server").server.BaseHTTPRequestHandler):
    body = b""
    status = 200
    seen = []

    def do_GET(self):
        _Tags.seen.append(self.path)
        self.send_response(_Tags.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(_Tags.body)

    def do_POST(self):
        _Tags.seen.append("POST " + self.path)
        self.send_response(500)
        self.end_headers()

    def log_message(self, *_args):
        pass


@contextlib.contextmanager
def ollama_stub(body, status=200):
    import http.server
    import threading
    _Tags.body, _Tags.status, _Tags.seen = body, status, []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Tags)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


with world(full_catalog()) as (room, calls):
    with ollama_stub(b'{"models": [{"name": "llama3.1:latest", "size": 1, "details": {}},'
                     b' {"name": "qwen2.5-coder:7b", "digest": "abc"}]}') as where:
        os.environ["OLLAMA_HOST"] = where
        _oll, _done = discover_cli("ollama")
        _seen = list(_Tags.seen)
    check("Ollama is read from GET /api/tags on this machine",
          _seen == ["/api/tags"], str(_seen))
    check("and every pulled model is offered, name as id",
          _oll and [m["id"] for m in _oll["models"]] == ["llama3.1:latest", "qwen2.5-coder:7b"]
          and _oll["source"] == "account", str(_oll))
    with ollama_stub(b"<html>not json</html>") as where:
        os.environ["OLLAMA_HOST"] = where
        _oll, _done = discover_cli("ollama")
    check("an Ollama answer that is not JSON is its fixed sentence, with the docs list",
          _oll and _oll["error"] == D.FAILURES["unreadable"] and _oll["source"] == "docs"
          and _oll["models"], str(_oll))
    os.environ["OLLAMA_HOST"] = "127.0.0.1:9"
    _oll, _done = discover_cli("ollama")
    check("no Ollama running is its fixed sentence",
          _oll and _oll["error"] == D.FAILURES["unreachable"], str(_oll))

with world(full_catalog()) as (room, calls):
    (room / "home" / ".qwen" / "settings.json").write_text(__import__("json").dumps({
        "security": {"auth": {"selectedType": "dashscope"}},
        "modelProviders": {"dashscope": [{"id": "dashscope/qwen3-coder-plus", "name": "Plus"},
                                      {"id": "glm-5", "name": "GLM-5"}]}}))
    _qwen = D.discover(M.effective("qwen"))
    check("a row whose id the scrub changed is dropped, never offered as [redacted]/...",
          [m["id"] for m in _qwen["models"]] == ["glm-5"], str(_qwen))
    _only = D.scrubbed({"source": "account", "error": "",
                        "models": [{"id": "secretword/x", "label": "x", "description": ""}]},
                       ["secretword"])
    check("and an answer left with no row keeps no redacted id", _only["models"] == [], str(_only))
    (room / "home" / ".qwen" / "settings.json").write_text(__import__("json").dumps({
        "security": {"auth": {"selectedType": "dashscope"}},
        "modelProviders": {"dashscope": [{"id": "dashscope/qwen3-coder-plus"}]}}))
    _qwen = D.discover(M.effective("qwen"))
    check("an account list the scrub emptied is the docs list and its sentence",
          _qwen["source"] == "docs" and _qwen["error"] == D.FAILURES["empty"]
          and _qwen["models"], str(_qwen)[:200])

print()
print("every failure is a fixed sentence")

with world(full_catalog()) as (room, calls):
    home = room / "home"
    (home / "codex-mode").write_text("garbage")
    _c, _done = discover_cli("codex")
    check("codex output that is not JSON: its output could not be read",
          _c and _c["error"] == "its output could not be read" and _c["source"] == "docs"
          and [m["id"] for m in _c["models"]][:1] == ["gpt-6-sol"], str(_c))
    check("and nothing the CLI printed reaches the answer",
          not leaked(_done.stdout, _done.stderr) and "not json" not in _done.stdout)
    (home / "codex-mode").write_text("fail")
    _c, _done = discover_cli("codex")
    check("codex exiting non-zero: the CLI exited with an error, its stderr kept out",
          _c and _c["error"] == "the CLI exited with an error"
          and not leaked(_done.stdout, _done.stderr), str(_c))
    (home / "codex-models.json").write_text('{"models": [{"slug": "x", "visibility": "hide"}]}')
    (home / "codex-mode").write_text("ok")
    _c, _done = discover_cli("codex")
    check("an account with nothing listed: it listed no models",
          _c and _c["error"] == "it listed no models", str(_c))
    os.remove(room / "bin" / "codex")
    _c, _done = discover_cli("codex")
    check("codex missing: the CLI is not installed",
          _c and _c["error"] == "the CLI is not installed", str(_c))
    os.remove(home / ".qwen" / "settings.json")
    _q, _done = discover_cli("qwen")
    check("no Qwen settings file: the file is missing",
          _q and _q["error"] == "the file is missing" and _q["source"] == "docs", str(_q))
    (home / ".kimi" / "config.toml").write_text('api_key = "%s"\n[models\nbroken' % PLANTED)
    _k, _done = discover_cli("kimi")
    check("a Kimi file that is not TOML: its output could not be read, no key in it",
          _k and _k["error"] == "its output could not be read"
          and not leaked(_done.stdout, _done.stderr), str(_k))
    _old = D.TIMEOUT
    D.TIMEOUT = 1
    (home / "codex-mode").write_text("slow")
    _fake(room / "bin" / "codex", 'sleep 5\n')
    _t = D.discover(M.effective("codex"))
    D.TIMEOUT = _old
    check("a CLI that hangs: it did not answer in 15 seconds",
          _t["error"] == D.FAILURES["timeout"] and "15 seconds" in D.FAILURES["timeout"],
          str(_t))
    check("every sentence a failure can say is one of the fixed set",
          set(D.FAILURES.values()) >= {"the CLI is not installed",
                                       "it did not answer in 15 seconds",
                                       "its output could not be read", "the file is missing"})

print()
print("switching models on and off")

with world() as (room, calls):
    _cat = pathlib.Path(M.CONFIG)
    _cat.write_text((pathlib.Path(__file__).resolve().parent.parent / "config"
                     / "models.example.toml").read_text()
                    .replace('models_on  = ["sonnet", "opus", "haiku"]',
                             'models     = "sonnet, opus, haiku"'))
    check("a farm catalog that still carries the retired string reads it as models_on",
          M.effective("claude")["models_on"] == ["sonnet", "opus", "haiku"],
          str(M.effective("claude")["models_on"]))
    _on = fleet("models", "on", "claude", "claude-opus-5-5")
    _toml = toml_of(M.CONFIG)
    check("fleet models on adds an id", _on.returncode == 0
          and _toml["claude"]["models_on"] == ["sonnet", "opus", "haiku", "claude-opus-5-5"],
          _on.stdout + _on.stderr)
    check("and the retired string is gone from the file, migrated once",
          "models" not in _toml["claude"] and 'models     =' not in _cat.read_text())
    check("every other line of the file is as it was",
          "# The pool is SHARED" in _cat.read_text() and _toml["codex"]["label"] == "Codex")
    _fab = fleet("models", "on", "claude", "fable")
    check("a noted model is refused without --confirm-cost, with the note",
          _fab.returncode != 0 and "usage credits" in _fab.stderr
          and "fable" not in toml_of(M.CONFIG)["claude"]["models_on"], _fab.stderr)
    _fab = fleet("models", "on", "claude", "fable", "--confirm-cost", "fable")
    check("and switched on when the confirm names it",
          _fab.returncode == 0 and "fable" in toml_of(M.CONFIG)["claude"]["models_on"],
          _fab.stderr)
    for _id in ("claude-fable-5-1[1m]", "claude-fable-5-1-20260801", "fable[1m]",
                "claude-opus-4-6-20260101[1m]"):
        _fab = fleet("models", "on", "claude", _id)
        check(f"every id of a noted family asks too, not only the listed ones: {_id}",
              _fab.returncode != 0 and "usage credits" in _fab.stderr
              and _id not in toml_of(M.CONFIG)["claude"]["models_on"], _fab.stderr)
    check("the note is decided by rule, and names no model that costs nothing more",
          [bool(D.cost_note("claude", x)) for x in
           ("claude-fable-5-1", "CLAUDE-FABLE-5-1[1M]", "claude-sonnet-4-6[1m]", "opus[1m]",
            "claude-opus-4-6", "claude-opus-5-5[1m]", "sonnet", "fabled")]
          == [True, True, True, False, False, False, False, False]
          and D.cost_note("codex", "fable") == "")
    _off = fleet("models", "off", "claude", "sonnet")
    check("off refuses the default model",
          _off.returncode != 0 and "stays on" in _off.stderr
          and "sonnet" in toml_of(M.CONFIG)["claude"]["models_on"], _off.stderr)
    _off = fleet("models", "off", "claude", "haiku")
    check("off takes another one out",
          _off.returncode == 0 and "haiku" not in toml_of(M.CONFIG)["claude"]["models_on"],
          _off.stderr)
    _bad = fleet("models", "on", "claude", "--rf")
    check("a name the rule refuses is not written",
          _bad.returncode != 0 and "not a model name" in _bad.stderr, _bad.stderr)
    os.environ["FLEET_CODEX_MODEL"] = "gpt-6-luna"
    check("the codex default is the one spawn resolves: FLEET_CODEX_MODEL",
          M.effective("codex")["default_model"] == "gpt-6-luna")
    os.environ.pop("FLEET_CODEX_MODEL")
    (pathlib.Path(os.environ["FLEET_CONFIG"]) / "env").write_text('FLEET_CODEX_MODEL="gpt-6-astra"\n')
    check("or the env file's, as bin/fleet loads it",
          M.effective("codex")["default_model"] == "gpt-6-astra",
          M.effective("codex")["default_model"])
    _off = fleet("models", "off", "codex", "gpt-6-astra")
    check("and off refuses that default too",
          _off.returncode != 0 and "stays on" in _off.stderr, _off.stderr)
    _on = fleet("models", "on", "codex", "gpt-6-sol")
    check("a provider's first list starts with its default model",
          toml_of(M.CONFIG)["codex"]["models_on"] == ["gpt-6-astra", "gpt-6-sol"],
          str(toml_of(M.CONFIG)["codex"]))

with world() as (room, calls):
    import tomllib as _tomllib
    _cat = pathlib.Path(M.CONFIG)
    _example = (pathlib.Path(__file__).resolve().parent.parent / "config"
                / "models.example.toml").read_text()
    _multi = _example.replace('models_on  = ["sonnet", "opus", "haiku"]',
                              'models_on = [\n  "sonnet",\n  "opus[1m]",  # the 1M one\n'
                              '  "haiku",\n]')
    _cat.write_text(_multi)
    _text, _found = M._with_models_on(_multi, "claude", ["sonnet", "opus"])
    try:
        _parsed = _tomllib.loads(_text)
    except _tomllib.TOMLDecodeError as exc:
        _parsed = {"error": str(exc)}
    check("a hand-written multi-line list holding opus[1m] is replaced whole, no orphan lines",
          _found and _parsed.get("claude", {}).get("models_on") == ["sonnet", "opus"]
          and '"haiku",' not in _text, str(_parsed)[:200])
    _on = fleet("models", "on", "claude", "claude-opus-5-5")
    _toml = toml_of(M.CONFIG)
    check("and fleet models on over it leaves a catalog that parses, every table kept",
          _on.returncode == 0 and _toml["claude"]["models_on"]
          == ["sonnet", "opus[1m]", "haiku", "claude-opus-5-5"]
          and set(_toml) == set(_tomllib.loads(_multi)), _on.stdout + _on.stderr)
    _before = _cat.read_text()
    _real = M._with_models_on
    M._with_models_on = lambda text, mid, ids: (text + "\nbroken = [\n", True)
    _m, _err = M.set_models("claude", on=["claude-sonnet-5"])
    M._with_models_on = _real
    check("a rewrite that would not parse is refused, and the file is left as it was",
          _m is None and "could not be rewritten safely" in _err
          and _cat.read_text() == _before, _err)

with world() as (room, calls):
    import threading as _threading
    import time as _time
    _real = M._with_models_on

    def _slow(text, mid, ids):
        _time.sleep(0.4)                       # both saves have read the file by now, unlocked
        return _real(text, mid, ids)

    M._with_models_on = _slow
    _errs = []
    _savers = [_threading.Thread(target=lambda x=x: _errs.append(M.set_models("claude", on=[x])[1]))
               for x in ("claude-opus-5-5", "claude-sonnet-5")]
    for _t in _savers:
        _t.start()
    for _t in _savers:
        _t.join()
    M._with_models_on = _real
    _now = toml_of(M.CONFIG)["claude"]["models_on"]
    check("two saves at the same moment both land: neither undoes the other",
          _errs == ["", ""] and {"claude-opus-5-5", "claude-sonnet-5"} <= set(_now),
          str(_now) + str(_errs))

with world(full_catalog()) as (room, calls):
    _no = fleet("models", "on", "oldqwen", "glm-5")
    check("a provider whose command cannot take a model says so and writes nothing",
          _no.returncode != 0 and "its own settings choose" in _no.stderr, _no.stderr)
    check("GET /api/engines rows carry models_on and default_model",
          {r["id"]: (r["models_on"], r["default_model"]) for r in SERVER.engines()}
          .get("claude") == (["sonnet", "opus", "haiku"], "sonnet"))

print()
print("the model reaches the lane")

LANE_CATALOG = """
[fakeqwen]
label   = "Fake Qwen"
engine  = "generic"
preset  = "qwen"
bin     = "%s"
run     = "{bin} --model {variant} -p {task}"
variant = "qwen3-coder-plus"
models_on = ["qwen3-coder-plus"]
source  = "added"

[fixed]
label  = "Fixed"
engine = "generic"
bin    = "fixed"
run    = "{bin} -p {task}"
source = "added"
"""


def project(room):
    repo, origin = room / "project", room / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-q", "-u", "origin", "main"], check=True,
                   capture_output=True)
    (room / "config" / "projects.toml").write_text(
        f'[demo]\nrepo = "example/demo"\npath = "{repo}"\nbranch = "main"\n')


with world() as (room, calls):
    _argv = room / "argv.txt"
    _tool = room / "bin" / "fakeqwen"
    _fake(_tool, ': > "%s"\nfor a in "$@"; do echo "$a" >> "%s"; done\n' % (_argv, _argv))
    pathlib.Path(M.CONFIG).write_text(
        (pathlib.Path(__file__).resolve().parent.parent / "config" / "models.example.toml")
        .read_text() + LANE_CATALOG % _tool)
    (room / "state" / "models-state.json").write_text(
        '{"fakeqwen": {"enabled": true, "health": "ok"}, "fixed": {"enabled": true, "health": "ok"}}')
    project(room)
    _plain = fleet("spawn", "--project", "demo", "--lane", "gp", "--engine", "fakeqwen",
                   "--task", "t", "--force")
    _plain_first = (_plain.stdout.splitlines() or [""])[0]
    _spawn = fleet("spawn", "--project", "demo", "--lane", "gq", "--engine", "fakeqwen",
                   "--model", "opus[1m]", "--task", "t", "--force")
    _first = (_spawn.stdout.splitlines() or [""])[0]
    check("a spawn with a model that is not on goes ahead",
          _spawn.returncode == 0 and "\nspawned  gq-" in "\n" + _spawn.stdout,
          _spawn.stdout + _spawn.stderr)
    check("and warns once on stderr, keeping stdout's first line the spawn result",
          "warning: opus[1m] is not on for fakeqwen" in _spawn.stderr
          and "warning" not in _spawn.stdout and "warning" not in _first
          and _first == _plain_first, _spawn.stderr)
    _runs = list((room / "state" / "logs").glob("gq-*.run.sh"))
    _run = _runs[0].read_text() if _runs else ""
    check("the generic lane's run.sh carries the chosen model, shell-quoted",
          "--model 'opus[1m]' -p" in _run, _run[-400:])
    # The same line, run by bash in a directory where `opus[1m]` would glob to a file.
    _here = room / "globroom"
    _here.mkdir()
    (_here / "opus1").write_text("")
    (_here / "task").write_text("do it")
    _line = launchcmd(room, "fakeqwen", str(_here / "task"))
    _mline = subprocess.run([sys.executable, str(LIB / "models.py"), "launchcmd", "fakeqwen",
                             str(_here / "task"), "opus[1m]"], capture_output=True, text=True,
                            env=dict(os.environ)).stdout.strip()
    subprocess.run(["bash", "-c", _mline], cwd=_here, env=dict(os.environ))
    _got = _argv.read_text().split("\n") if _argv.exists() else []
    check("run by bash beside a file named opus1, opus[1m] does not glob",
          _got[:3] == ["--model", "opus[1m]", "-p"], str(_got))
    check("without a --model the row's own variant fills {variant}",
          "--model 'qwen3-coder-plus'" in _line, _line)
    _bad = subprocess.run([sys.executable, str(LIB / "models.py"), "launchcmd", "fakeqwen",
                           "/tmp/t", "-x"], capture_output=True, text=True, env=dict(os.environ))
    check("launchcmd refuses a model the rule refuses", _bad.returncode != 0 and not _bad.stdout)

    check("a spawn of the model that is on says nothing on stderr about it",
          _plain.returncode == 0 and "warning" not in _plain.stderr
          and "model=qwen3-coder-plus" in _plain.stdout, _plain.stdout + _plain.stderr)
    _fixed = fleet("spawn", "--project", "demo", "--lane", "gf", "--engine", "fixed",
                   "--model", "anything", "--task", "t", "--force")
    check("a row with no {variant} refuses --model",
          _fixed.returncode != 0 and "its own settings choose" in _fixed.stdout,
          _fixed.stdout + _fixed.stderr)
    _dash = fleet("spawn", "--project", "demo", "--lane", "gd", "--engine", "fakeqwen",
                  "--model", "-rf", "--task", "t", "--force")
    check("the model rule refuses a leading -",
          _dash.returncode != 0 and "not a model name" in _dash.stdout, _dash.stdout)

    _fable = fleet("spawn", "--project", "demo", "--lane", "cf", "--engine", "claude",
                   "--account", "default", "--model", "fable", "--task", "t", "--force")
    check("spawn refuses a noted model that is off, with its note",
          _fable.returncode != 0 and "usage credits" in _fable.stdout
          and not list((room / "state" / "logs").glob("cf-*.run.sh")),
          _fable.stdout + _fable.stderr)
    _fable = fleet("spawn", "--project", "demo", "--lane", "cg", "--engine", "claude",
                   "--account", "default", "--model", "claude-fable-5-1[1m]", "--task", "t",
                   "--force")
    check("and refuses a full Fable id with [1m] the same way, not only with a warning",
          _fable.returncode != 0 and "usage credits" in _fable.stdout
          and not list((room / "state" / "logs").glob("cg-*.run.sh")),
          _fable.stdout + _fable.stderr)
    _one = fleet("spawn", "--project", "demo", "--lane", "c1", "--engine", "claude",
                 "--account", "default", "--model", "opus[1m]", "--task", "t", "--force")
    _runs = list((room / "state" / "logs").glob("c1-*.run.sh"))
    check("claude accepts opus[1m], and its run.sh quotes it",
          _one.returncode == 0 and _runs and '--model "opus[1m]"' in _runs[0].read_text(),
          _one.stdout + _one.stderr)
    _son = fleet("spawn", "--project", "demo", "--lane", "c2", "--engine", "claude",
                 "--account", "default", "--model", "sonnet[1m]", "--task", "t", "--force")
    check("and sonnet[1m], warning because it is not on",
          _son.returncode == 0 and "not on for claude" in _son.stderr, _son.stderr)
    check("no spawn ran claude or codex itself",
          not any(line.split()[0] in ("claude", "codex")
                  for line in calls.read_text().splitlines()), calls.read_text())

print()
print("a generic lane settles on its engine's exit code")

# A bad key or an unknown model, as most CLIs report it: one plain line on stdout, then exit 1.
# The stream alone cannot tell that from a plain-text engine that worked and said one line, so
# the lane's own run.sh writes down the exit code and the parser settles on it. The run.sh is
# the one `fleet spawn` wrote, run by bash, with the fake engine first on PATH.
SETTLE_CATALOG = """
[fakecli]
label  = "Fake CLI"
engine = "generic"
bin    = "fakecli"
run    = "{bin} -p {task}"
source = "added"

[fakeexec]
label  = "Fake CLI by exec"
engine = "generic"
bin    = "fakecli"
run    = "exec {bin} -p {task}"
source = "added"
"""


def settle(room, lane, body, engine="fakecli"):
    """The status and reason a generic lane settles on when its engine runs `body`."""
    import json
    _fake(room / "bin" / "fakecli", body)
    done = fleet("spawn", "--project", "demo", "--lane", lane, "--engine", engine,
                 "--task", "t", "--force")
    runs = list((room / "state" / "logs").glob(lane + "-*.run.sh"))
    if done.returncode != 0 or not runs:
        return "no spawn", done.stdout + done.stderr
    subprocess.run(["bash", str(runs[0])], env=dict(os.environ), capture_output=True,
                   timeout=60)
    slug = runs[0].name[:-len(".run.sh")]
    rec = json.loads((room / "state" / "state" / (slug + ".json")).read_text())
    return rec.get("status"), rec.get("result_text") or ""


with world(SETTLE_CATALOG, {"fakecli": {"enabled": True, "health": "ok"},
                            "fakeexec": {"enabled": True, "health": "ok"}}) as (room, calls):
    project(room)
    _status, _why = settle(room, "sx", 'echo "Error: invalid API key"\nexit 1\n')
    check("a launch that prints one plain line and exits 1 is failed, not ended",
          _status == "failed", f"{_status}: {_why}")
    check("and the line it printed is the reason",
          "invalid API key" in _why and "code 1" in _why, _why)
    _status, _why = settle(room, "sz", 'echo "Applied the edit."\nexit 0\n')
    check("the same line with exit 0 still ends the lane as it did",
          _status == "ended", f"{_status}: {_why}")
    # A row may start its CLI with exec; that must replace only the engine's own subshell, or
    # the exit code is never written and the failed launch reads as one that ended.
    _status, _why = settle(room, "se", 'echo "Error: invalid API key"\nexit 1\n', "fakeexec")
    check("a row that runs its CLI by exec and exits 1 is failed with code 1",
          _status == "failed" and "code 1" in _why, f"{_status}: {_why}")

print()
print("the two routes, behind the token")

with world(full_catalog()) as (room, calls):
    import json as _json
    import threading as _threading
    import urllib.error as _uerr
    import urllib.request as _ureq
    _old_token = SERVER.TOKEN
    SERVER.TOKEN = "test-token-not-a-secret"
    server = SERVER.Server(("127.0.0.1", 0), SERVER.Handler)
    _thread = _threading.Thread(target=server.serve_forever, daemon=True)
    _thread.start()
    _base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, body, token="test-token-not-a-secret", headers=None):
        request = _ureq.Request(_base + path, data=_json.dumps(body).encode(), method="POST",
                                headers=dict({"Content-Type": "application/json"},
                                             **({"Authorization": "Bearer " + token}
                                                if token else {}), **(headers or {})))
        try:
            with _ureq.urlopen(request, timeout=40) as answer:
                return answer.status, _json.loads(answer.read())
        except _uerr.HTTPError as err:
            return err.code, _json.loads(err.read() or b"{}")

    try:
        _s, _p = post("/api/models/discover", {"id": "codex"}, token="")
        check("discover without the token is refused", _s == 403, str(_s))
        _s, _p = post("/api/models/select", {"id": "claude", "on": ["opus[1m]"]}, token="wrong")
        check("select with a wrong token is refused", _s == 403, str(_s))
        _s, _p = post("/api/models/select", {"id": "claude", "on": ["opus[1m]"]},
                      headers={"Sec-Fetch-Site": "cross-site"})
        check("a cross-site select is refused", _s == 403, str(_p))
        check("and nothing was written", not os.path.exists(M.CONFIG)
              or "opus[1m]" not in pathlib.Path(M.CONFIG).read_text())

        _s, _p = post("/api/models/discover", {"id": "codex"})
        check("discover runs fleet models discover and answers the account's list",
              _s == 200 and [m["id"] for m in _p["models"]] == ["gpt-6-sol", "gpt-6-luna"]
              and _p["source"] == "account", str(_p))
        check("each row says whether it is on",
              all("on" in m for m in _p["models"]), str(_p))
        _s, _p = post("/api/models/discover", {"id": "qwen"})
        check("the Qwen answer through the route leaks no key",
              _s == 200 and not leaked(_json.dumps(_p)), str(_p))
        _s, _p = post("/api/models/discover", {"id": "kimi"})
        check("nor does the Kimi one",
              _s == 200 and not leaked(_json.dumps(_p)), str(_p))
        _s, _p = post("/api/models/discover", {"id": "claude"})
        check("the route's rows are {id, label, description, cost_note, on}, the note by rule",
              _s == 200 and all(set(m) == {"id", "label", "description", "cost_note", "on"}
                                for m in _p["models"])
              and {m["id"] for m in _p["models"] if m["cost_note"]}
              == {"fable", "claude-opus-4-6[1m]", "claude-sonnet-4-6[1m]"}, str(_p)[:300])
        _s, _p = post("/api/models/discover", {"id": "nosuch"})
        check("an unknown provider is 404", _s == 404, str(_s))
        SERVER.DISCOVERING.add("codex")
        _s, _p = post("/api/models/discover", {"id": "codex"})
        SERVER.DISCOVERING.discard("codex")
        check("one request at a time per provider", _s == 409, str(_s))

        # The server's own check must refuse before anything runs: the CLI refusing as well
        # would otherwise hide a server that forgot to check.
        _ran, _real_run_tool = [], SERVER.run_tool
        SERVER.run_tool = lambda argv, **_kw: (_ran.append(argv), (1, "", "ran"))[1]
        try:
            _s, _p = post("/api/models/select", {"id": "claude", "on": ["fable"]})
            _s2, _p2 = post("/api/models/select", {"id": "claude", "off": ["sonnet"]})
        finally:
            SERVER.run_tool = _real_run_tool
        check("select refuses a noted model not in confirm_cost, with the note, server side",
              _s == 400 and "usage credits" in _p["error"], str(_p))
        check("the refusal is {error, cost_note, model}, so the page can ask and send again",
              _s == 400 and set(_p) == {"error", "cost_note", "model"}
              and _p["model"] == "fable" and _p["cost_note"] == D.FABLE_NOTE, str(_p))
        check("and a refusal that is not about money is {error} alone",
              _s2 == 400 and set(_p2) == {"error"}, str(_p2))
        check("and the default model in off, server side too",
              _s2 == 400 and "stays on" in _p2["error"], str(_p2))
        check("both refused before any command ran", _ran == [], str(_ran))
        check("and wrote nothing", "fable" not in M.effective("claude")["models_on"])
        _s, _p = post("/api/models/select", {"id": "claude", "on": ["claude-fable-5-1[1m]"]})
        check("select refuses a full Fable id with [1m] too, naming it",
              _s == 400 and "usage credits" in _p["error"]
              and _p.get("model") == "claude-fable-5-1[1m]" and _p.get("cost_note")
              and "claude-fable-5-1[1m]" not in M.effective("claude")["models_on"], str(_p))
        _s, _p = post("/api/models/select",
                      {"id": "claude", "on": ["fable", "opus[1m]"], "confirm_cost": ["fable"]})
        check("with the confirm it switches both on and answers the updated row",
              _s == 200 and _p.get("id") == "claude"
              and {"fable", "opus[1m]"} <= set(_p.get("models_on") or [])
              and _p.get("default_model") == "sonnet", str(_p))
        check("the answer is the row itself, the same shape GET /api/engines rows have",
              _s == 200 and set(_p) == set(next(r for r in SERVER.engines()
                                                if r["id"] == "claude")), str(sorted(_p)))
        _s, _p = post("/api/models/select", {"id": "claude", "off": ["sonnet"]})
        check("select refuses the default model in off", _s == 400 and "stays on" in _p["error"],
              str(_p))
        _s, _p = post("/api/models/select", {"id": "claude", "off": ["haiku"]})
        check("and takes another one off",
              _s == 200 and "haiku" not in _p.get("models_on", ["haiku"]), str(_p))
        _s, _p = post("/api/models/select", {"id": "claude", "on": ["-rf"]})
        check("select refuses a name the rule refuses", _s == 400, str(_p))
        _s, _p = post("/api/models/select", {"id": "claude", "on": "opus"})
        check("select refuses a body whose lists are not lists", _s == 400, str(_p))
        _s, _p = post("/api/models/select", {"id": "oldqwen", "on": ["glm-5"]})
        check("select on a provider that cannot take a model says the sentence",
              _s == 400 and "its own settings choose" in _p["error"], str(_p))
        check("no route ran a provider's test or sent a prompt",
              all(line.split()[:3] in (["codex", "debug", "models"],)
                  for line in calls.read_text().splitlines()), calls.read_text())
    finally:
        server.shutdown()
        server.server_close()
        SERVER.TOKEN = _old_token

print()
print("a credential a failing CLI prints is never kept")

# The Test keeps what a failing CLI said, in models-state.json and on the page. A CLI that prints
# its own key while it fails would put the key there, so the marker below must reach neither the
# state file nor either route that serves the rows, on stderr or stdout, bare or as key=value.
MARKER = "example_secret_marker_9876"


@contextlib.contextmanager
def leaky(script, auth_env="DEMO_TOKEN"):
    """A generic row whose CLI runs `script` with DEMO_TOKEN set to the marker, Tested through
    the Test button's route; yields (state file text, GET /api/models, GET /api/engines)."""
    import json as _json
    import threading as _threading
    import urllib.request as _ureq
    with farm() as room:
        tool = room / "probe"
        tool.write_text("#!/bin/sh\n" + script)
        tool.chmod(0o755)
        pathlib.Path(M.CONFIG).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(M.CONFIG).write_text(
            '[probe]\nlabel = "Probe"\nengine = "generic"\nbin = "%s"\nrun = "{bin} -p {task}"\n'
            'auth_env = "%s"\nsource = "added"\n' % (tool, auth_env))
        kept, old_token = os.environ.get("DEMO_TOKEN"), SERVER.TOKEN
        os.environ["DEMO_TOKEN"] = MARKER
        SERVER.TOKEN = "test-token-not-a-secret"
        server = SERVER.Server(("127.0.0.1", 0), SERVER.Handler)
        _threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        auth = {"Authorization": "Bearer test-token-not-a-secret",
                "Content-Type": "application/json"}

        def call(path, body=None):
            request = _ureq.Request(base + path, headers=auth, method="GET" if body is None
                                    else "POST", data=None if body is None
                                    else _json.dumps(body).encode())
            with _ureq.urlopen(request, timeout=60) as answer:
                return answer.read().decode()
        try:
            tested = call("/api/models", {"action": "test", "id": "probe"})
            yield (pathlib.Path(M.STATE).read_text() + tested, call("/api/models"),
                   call("/api/engines"))
        finally:
            server.shutdown()
            server.server_close()
            SERVER.TOKEN = old_token
            if kept is None:
                os.environ.pop("DEMO_TOKEN", None)
            else:
                os.environ["DEMO_TOKEN"] = kept


for _where, _script in (
        ("on stderr as credential=, stdout harmless",
         'echo starting; echo "credential=$DEMO_TOKEN" >&2; exit 1\n'),
        ("on stdout as credential=", 'echo "credential=$DEMO_TOKEN"; exit 1\n'),
        ("bare on stderr, stdout harmless", 'echo starting; echo "sent $DEMO_TOKEN" >&2; exit 1\n'),
        ("bare on stdout, exit 0", 'echo "sent $DEMO_TOKEN and no answer"\n'),
        ("on stdout as an auth failure", 'echo "401 unauthorized: token $DEMO_TOKEN"\n')):
    with leaky(_script) as (_state_text, _models, _engines):
        check(f"a credential {_where} is not in models-state.json or the Test's answer",
              MARKER not in _state_text and "probe" in _state_text, _state_text[:300])
        check(f"nor in the rows /api/models and /api/engines return ({_where})",
              MARKER not in _models and MARKER not in _engines and "probe" in _engines,
              (_models + _engines)[:300])

check("redact takes out the row's auth variable, however it is named",
      M.redact("said abcdefgh123", "WEIRD_NAME", {"WEIRD_NAME": "abcdefgh123"})
      == "said [redacted]")
check("and any variable whose name ends in KEY, TOKEN, SECRET or PASSWORD",
      M.redact("a pw1234567 b", "", {"DB_PASSWORD": "pw1234567"}) == "a [redacted] b")
check("but not a value shorter than eight characters, so a reply of 42 survives",
      M.redact("42", "", {"SOME_KEY": "42"}) == "42")
check("the row's own credential goes at any length, since `fleet models auth` takes a short one",
      M.redact("sent abc1234 and 42", "DEMO_TOKEN", {"DEMO_TOKEN": "abc1234"})
      == "sent [redacted] and 42")
check("and so does the farm's stored secret for the row, even with no auth variable named",
      M.redact("sent abc1234", "", {}, secrets=("abc1234",)) == "sent [redacted]")

# The review's case end to end: a seven-character key in the key file, echoed on stderr by a
# CLI that fails, Tested through the command a person runs.
with farm() as room:
    _tool = room / "probe"
    _tool.write_text('#!/bin/sh\necho ready; echo "sent $DEMO_TOKEN" >&2; exit 1\n')
    _tool.chmod(0o755)
    (room / "config").mkdir(parents=True, exist_ok=True)
    (room / "config" / "models.toml").write_text(
        '[probe]\nlabel = "Probe"\nengine = "generic"\nbin = "%s"\nrun = "{bin} -p {task}"\n'
        'auth_env = "DEMO_TOKEN"\nsource = "added"\n' % _tool)
    (room / "state" / "secrets").mkdir(parents=True, exist_ok=True)
    (room / "state" / "secrets" / "probe.key").write_text("abc1234\n")
    _env = {k: v for k, v in os.environ.items() if k != "DEMO_TOKEN"}
    _env["FLEET_CONFIG"] = str(room / "config")
    _env["FLEET_STATE"] = str(room / "state")
    _done = subprocess.run([sys.executable, str(LIB / "models.py"), "test", "probe"],
                           capture_output=True, text=True, env=_env, timeout=120)
    _state_file = room / "state" / "models-state.json"
    _kept = _state_file.read_text() if _state_file.exists() else ""
    check("a short stored key a failing CLI echoes is not in `models.py test`'s output",
          "abc1234" not in _done.stdout + _done.stderr and "probe" in _kept,
          "ran" if "abc1234" not in _done.stdout + _done.stderr else "leaked")
    check("nor in models-state.json", "abc1234" not in _kept and "fail" in _kept,
          "kept" if "abc1234" not in _kept else "leaked")

check("key=value and key: value pairs lose their value, a Bearer header included",
      M.redact('api_key=abc token: xyz "password": "p w" Authorization: Bearer q.r.s', "", {})
      == 'api_key=[redacted] token: [redacted] "password": [redacted] '
      'Authorization: [redacted]', M.redact('api_key=abc token: xyz "password": "p w" '
                                            'Authorization: Bearer q.r.s', "", {}))
check("what is kept is cut to 200 characters", len(M.redact("x" * 500, "", {})) == 200)

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

FILES = [LIB / "models.py", LIB / "model_presets.py", LIB / "model_discovery.py",
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
