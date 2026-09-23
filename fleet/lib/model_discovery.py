#!/usr/bin/env python3
"""Which models a provider offers, asked without spending anything.

One function and one docs list per preset id (design: fleet/docs/design/models-providers.md,
section 3). Every route reads metadata only: no prompt is ever sent, so no request here costs a
token. The method is chosen by the provider row's `preset`, falling back to its `engine` for the
shipped Claude and Codex rows.

An answer is {source: "account" | "docs", models: [{id, label, description}], error}, and
annotate() adds each model's `cost_note` and `on` (the conductor's amendment to section 6):

  source   "account" when the provider itself answered (its CLI, its local file, its port),
           "docs" when the list is the one its documentation gives
  models   only an id, a label and a description are kept from any source. The Qwen and Kimi
           files hold API keys, a CLI can print anything, and none of that is ours to pass on.
           A description is free text and never asks anything; `cost_note` is the server's,
           decided by rule (cost_note() below), and is the only thing that asks
  error    "" or one of FAILURES: a fixed sentence, never text from the provider

A failed request answers the docs list with the sentence, so the page still has something to
offer. The whole answer passes lib/scrub.py on its way out, with every credential-looking value
the provider's own file held added to the scrub list.

Run:  python3 lib/model_discovery.py discover <provider> [--json]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_presets as PRESETS  # noqa: E402
import scrub as SCRUB  # noqa: E402

TIMEOUT = 15

# The fixed set of sentences a failed request can say. Nothing a provider printed is ever one.
FAILURES = {
    "not_installed": "the CLI is not installed",
    "timeout": f"it did not answer in {TIMEOUT} seconds",
    "unreadable": "its output could not be read",
    "missing": "the file is missing",
    "failed": "the CLI exited with an error",
    "unreachable": "nothing answered on its port",
    "empty": "it listed no models",
    "no_list": "this provider has no list to offer here; add a model by its name",
}

LABEL_MAX = 80
DESCRIPTION_MAX = 200

FABLE_NOTE = ("some plans bill Fable to usage credits, and a headless run bills it without "
              "asking")
OPUS_46_1M_NOTE = "needs usage credits on Pro"
SONNET_46_1M_NOTE = "needs usage credits on every plan"

# A note that is about money the subscription does not cover. Switching one of these on asks
# once more (POST /api/models/select wants it in confirm_cost, `fleet models on` wants
# --confirm-cost), and `fleet spawn` refuses one that is not on. Decided by rule on the model's
# family, never by an exact lookup, so every id that names a noted model carries the note: a
# `[1m]` suffix and a dated snapshot (`-YYYYMMDD`) are taken off before the family is read.
_ONE_M = "[1m]"
_DATED = re.compile(r"-\d{8}$")


def _family(model):
    """(the id with its `[1m]` and its snapshot date taken off, whether it asked for 1M)."""
    base = str(model or "").strip().lower()
    one_m = False
    while True:
        if base.endswith(_ONE_M):
            base, one_m = base[:-len(_ONE_M)], True
        elif _DATED.search(base):
            base = _DATED.sub("", base)
        else:
            return base, one_m


def _named(base, family):
    return base == family or base.startswith(family + "-")


def claude_cost_note(model):
    base, one_m = _family(model)
    if _named(base, "fable") or _named(base, "claude-fable"):
        return FABLE_NOTE
    if one_m and _named(base, "claude-opus-4-6"):
        return OPUS_46_1M_NOTE
    if one_m and _named(base, "claude-sonnet-4-6"):
        return SONNET_46_1M_NOTE
    return ""


COST_RULES = {"claude": claude_cost_note}


def _docs(*rows):
    return [{"id": mid, "label": label, "description": said} for mid, label, said in rows]


# What each provider's documentation says it offers (checked 2026-09-23, see
# internal/research/report-model-discovery.md). A description here is shown and asks nothing;
# only the cost rule above asks.
DOCS = {
    "claude": _docs(
        ("sonnet", "Sonnet 5", ""),
        ("opus", "Opus 5.5", ""),
        ("haiku", "Haiku 4.5", ""),
        ("fable", "Fable 5.1", ""),
        ("opus[1m]", "Opus 5.5, 1M context", ""),
        ("sonnet[1m]", "Sonnet 5, 1M context", ""),
        ("claude-opus-5-5", "Opus 5.5 (full id)", ""),
        ("claude-sonnet-5", "Sonnet 5 (full id)", ""),
        ("claude-haiku-4-5-20251001", "Haiku 4.5 (full id)", ""),
        ("claude-opus-4-6[1m]", "Opus 4.6, 1M context", ""),
        ("claude-sonnet-4-6[1m]", "Sonnet 4.6, 1M context", ""),
    ),
    "codex": _docs(
        ("gpt-6-sol", "GPT-6 Sol", "the docs' pick for Plus, Pro, Business, Enterprise and Edu"),
        ("gpt-6-luna", "GPT-6 Luna", "the docs' pick for Free and Go"),
        ("gpt-6-astra", "GPT-6 Astra", ""),
        ("gpt-5.6-sol", "GPT-5.6 Sol", ""),
        ("gpt-5.5", "GPT-5.5", "retires 2026-10-14"),
    ),
    "gemini": _docs(
        ("auto", "Auto", ""),
        ("pro", "Pro", ""),
        ("flash", "Flash", ""),
        ("flash-lite", "Flash-Lite", ""),
        ("gemini-2.5-pro", "Gemini 2.5 Pro", ""),
        ("gemini-2.5-flash", "Gemini 2.5 Flash", ""),
        ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", ""),
        ("gemini-3-pro-preview", "Gemini 3 Pro Preview", ""),
        ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview", ""),
    ),
    "qwen": _docs(
        ("qwen3-coder-plus", "Qwen3 Coder Plus", ""),
        ("qwen3-coder-next", "Qwen3 Coder Next", ""),
        ("qwen3.7-plus", "Qwen3.7 Plus", ""),
        ("qwen3.6-plus", "Qwen3.6 Plus", ""),
        ("qwen3.5-plus", "Qwen3.5 Plus", ""),
        ("qwen3-max-2026-01-23", "Qwen3 Max", ""),
        ("glm-5", "GLM-5", ""),
        ("glm-4.7", "GLM-4.7", ""),
        ("kimi-k2.5", "Kimi K2.5", ""),
        ("MiniMax-M2.5", "MiniMax M2.5", ""),
    ),
    "kimi": _docs(("kimi-code/kimi-for-coding", "Kimi for Coding", "")),
    "grok": _docs(
        ("grok-4.7", "Grok 4.7", "xAI's pick for code"),
        ("grok-build-0.1", "Grok Build 0.1", "the model behind Grok Build's own agent loop"),
    ),
    "opencode": _docs(
        ("openai/gpt-6-sol", "GPT-6 Sol through OpenAI", ""),
        ("anthropic/claude-sonnet-5", "Sonnet 5 through Anthropic", ""),
    ),
    "aider": _docs(
        ("openai/gpt-6-sol", "GPT-6 Sol through OpenAI", ""),
        ("anthropic/claude-sonnet-5", "Sonnet 5 through Anthropic", ""),
    ),
    "ollama": _docs(
        ("llama3.1", "Llama 3.1", ""),
        ("qwen2.5-coder", "Qwen2.5 Coder", ""),
        ("deepseek-coder", "DeepSeek Coder", ""),
    ),
    "custom": [],
}


class Failed(Exception):
    """A discovery route that did not work, carrying one FAILURES key."""

    def __init__(self, key):
        super().__init__(key)
        self.key = key


def method(row):
    """The preset id whose route this provider row uses: its `preset`, else its `engine` (the
    shipped claude and codex rows carry no preset), else custom."""
    row = row or {}
    preset = str(row.get("preset") or "").strip()
    if preset in DOCS:
        return preset
    engine = str(row.get("engine") or "").strip()
    if engine in ("claude", "codex"):
        return engine
    return "custom"


def cost_note(engine, model):
    """The cost note for this model on this engine, or "" when it needs no second question."""
    rule = COST_RULES.get(str(engine or ""))
    return rule(model) if rule else ""


def docs_list(row):
    return [dict(item) for item in DOCS.get(method(row), [])]


# ---------------------------------------------------------------- keeping only what we may keep

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _text(value, limit):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    said = _CONTROL.sub(" ", str(value)).strip()
    return said if len(said) <= limit else said[:limit - 1].rstrip() + "…"


def keep(mid, label="", description=""):
    """One row, or None when the id is not a model name the rule lets reach a command line."""
    mid = str(mid or "").strip() if isinstance(mid, str) else ""
    if not PRESETS.MODEL_RE.match(mid):
        return None
    return {"id": mid, "label": _text(label, LABEL_MAX) or mid,
            "description": _text(description, DESCRIPTION_MAX)}


def _unique(rows):
    seen, out = set(), []
    for row in rows:
        if row and row["id"] not in seen:
            seen.add(row["id"])
            out.append(row)
    return out


_SECRET_NAME = re.compile(r"key|token|secret|password|credential|auth", re.I)


def secrets_in(value, named=False):
    """Every string in a parsed config file that sits under a credential-looking name. These are
    added to the scrub, so a key a vendor wrote into a description is taken out too."""
    found = []
    if isinstance(value, dict):
        for name, item in value.items():
            found += secrets_in(item, named or bool(_SECRET_NAME.search(str(name))))
    elif isinstance(value, list):
        for item in value:
            found += secrets_in(item, named)
    elif isinstance(value, str) and named and value.strip():
        found.append(value.strip())
    return found


# ---------------------------------------------------------------- the routes

def _run(argv):
    """stdout of a listing command. The argv is a list: nothing here goes through a shell."""
    if not (os.path.isabs(argv[0]) and os.access(argv[0], os.X_OK)) and not shutil.which(argv[0]):
        raise Failed("not_installed")
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise Failed("not_installed")
    except subprocess.TimeoutExpired:
        raise Failed("timeout")
    except OSError:
        raise Failed("failed")
    if done.returncode != 0:
        raise Failed("failed")
    return done.stdout or ""


def _bin(row, fallback):
    return str((row or {}).get("bin") or "").strip() or fallback


def codex_bin():
    """The codex lanes run: bin/fleet's CODEX_BIN, which FLEET_CODEX_BIN points elsewhere."""
    return (os.environ.get("CODEX_BIN") or os.environ.get("FLEET_CODEX_BIN")
            or ("/usr/bin/codex" if os.path.exists("/usr/bin/codex") else "codex"))


def from_codex(row):
    """`codex debug models`: only rows the picker lists (visibility "list"). The docs say
    choosing a model does not grant access to it, so a hidden row is not offered."""
    binary = codex_bin() if str((row or {}).get("engine")) == "codex" else _bin(row, codex_bin())
    out = _run([binary, "debug", "models"])
    try:
        data = json.loads(out)
        items = data["models"] if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise Failed("unreadable")
    rows = []
    for item in items:
        if not isinstance(item, dict) or item.get("visibility") != "list":
            continue
        rows.append(keep(item.get("slug"), item.get("display_name"), item.get("description")))
    return rows, []


def ollama_url():
    """Where Ollama listens: OLLAMA_HOST as Ollama itself reads it, else its default port."""
    host = str(os.environ.get("OLLAMA_HOST") or "").strip() or "127.0.0.1:11434"
    if "://" not in host:
        host = "http://" + host
    return host.rstrip("/") + "/api/tags"


def from_ollama(_row):
    """GET /api/tags on this machine: the models pulled here."""
    try:
        with urllib.request.urlopen(ollama_url(), timeout=TIMEOUT) as answer:
            body = answer.read(4 * 1024 * 1024)
    except (TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError):
            raise Failed("timeout")
        if isinstance(exc, urllib.error.HTTPError):
            raise Failed("unreadable")
        raise Failed("unreachable")
    try:
        items = json.loads(body.decode("utf-8"))["models"]
        if not isinstance(items, list):
            raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise Failed("unreadable")
    rows = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("name") or item.get("model")
            rows.append(keep(name, name, ""))
    return rows, []


def _home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        raise Failed("missing")
    except (OSError, UnicodeError):
        raise Failed("unreadable")


def from_qwen(_row):
    """~/.qwen/settings.json modelProviders.<type>[]: exactly what Qwen Code's /model offers."""
    try:
        data = json.loads(_read(_home(".qwen", "settings.json")))
    except ValueError:
        raise Failed("unreadable")
    providers = data.get("modelProviders") if isinstance(data, dict) else None
    if not isinstance(providers, dict):
        raise Failed("unreadable")
    rows = []
    for items in providers.values():
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                rows.append(keep(item.get("id"), item.get("name"), item.get("description")))
    return rows, secrets_in(data)


def from_kimi(_row):
    """~/.kimi/config.toml [models."<alias>"]: what Kimi Code's login wrote there. The alias is
    what `kimi -m` takes."""
    import tomllib
    try:
        data = tomllib.loads(_read(_home(".kimi", "config.toml")))
    except tomllib.TOMLDecodeError:
        raise Failed("unreadable")
    models = data.get("models")
    if not isinstance(models, dict):
        raise Failed("unreadable")
    rows = []
    for alias, item in models.items():
        item = item if isinstance(item, dict) else {}
        rows.append(keep(alias, item.get("display_name") or item.get("model"),
                         item.get("description")))
    return rows, secrets_in(data)


def from_opencode(row):
    """`opencode models`: one provider/model a line. Its catalog, not a plan check."""
    out = _run([_bin(row, "opencode"), "models"])
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if " " in line:
            raise Failed("unreadable")
        rows.append(keep(line, line, ""))
    return rows, []


ROUTES = {"codex": from_codex, "ollama": from_ollama, "qwen": from_qwen, "kimi": from_kimi,
          "opencode": from_opencode}


def discover(row):
    """{source, models, error} for one provider row. Never raises, never sends a prompt."""
    how = method(row)
    route = ROUTES.get(how)
    if route is None:
        listed = docs_list(row)
        # A row with neither a route nor a documented list (a hand-written command, a preset
        # added after this list) says so, rather than answering a press with nothing at all.
        return {"source": "docs", "models": listed, "error": "" if listed else FAILURES["no_list"]}
    secrets = []
    try:
        rows, secrets = route(row)
        rows = _unique(rows)
        if not rows:
            raise Failed("empty")
        answer = {"source": "account", "models": rows, "error": ""}
    except Failed as failed:
        answer = {"source": "docs", "models": docs_list(row),
                  "error": FAILURES.get(failed.key, FAILURES["unreadable"])}
    except Exception:                              # a route that broke is a sentence, not a trace
        answer = {"source": "docs", "models": docs_list(row), "error": FAILURES["unreadable"]}
    answer = scrubbed(answer, secrets)
    if answer["source"] == "account" and not answer["models"]:
        answer = scrubbed({"source": "docs", "models": docs_list(row),
                           "error": FAILURES["empty"]}, secrets)
    return answer


def scrubbed(answer, secrets=()):
    """The answer with every known secret and token shape taken out of every string in it. A row
    whose id the scrub changed is dropped, not offered: `[redacted]/x` passes the model rule, and
    it is not a model anyone has."""
    state = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))
    known = list(secrets) + SCRUB.stored_secrets(state)
    clean = json.loads(SCRUB.scrub(json.dumps(answer), [json.dumps(s)[1:-1] for s in known]))
    before = [item.get("id") if isinstance(item, dict) else None
              for item in answer.get("models") or []]
    after = clean.get("models") or []
    if len(before) == len(after):
        clean["models"] = [item for was, item in zip(before, after)
                           if isinstance(item, dict) and item.get("id") == was]
    return clean


def annotate(answer, row):
    """Each model given its `cost_note` ("" unless the rule names it) and marked `on` when this
    provider has it switched on: {id, label, description, cost_note, on}."""
    on = set((row or {}).get("models_on") or [])
    engine = str((row or {}).get("engine") or "")
    for model in answer.get("models") or []:
        model["cost_note"] = cost_note(engine, model["id"])
        model["on"] = model["id"] in on
    return answer


def _human(provider, answer):
    lines = []
    if answer["error"] == FAILURES["no_list"]:
        lines.append(f"{provider}: {answer['error']}")
    elif answer["error"]:
        lines.append(f"{provider}: {answer['error']}; the docs list instead")
    where = "from your account" if answer["source"] == "account" else "from the docs"
    count = len(answer["models"])
    lines.append(f"{provider}: {count} model{'' if count == 1 else 's'} {where}")
    for model in answer["models"]:
        mark = "on " if model.get("on") else "   "
        said = "; ".join(x for x in (model.get("description"), model.get("cost_note")) if x)
        lines.append(f"  {mark} {model['id']:<28} {model['label']}"
                     + (f"  ({said})" if said else ""))
    return "\n".join(lines)


def main(argv):
    if len(argv) < 2 or argv[0] != "discover":
        print("usage: fleet models discover <provider> [--json]", file=sys.stderr)
        return 2
    provider = argv[1]
    as_json = "--json" in argv[2:]
    import models as MODELS
    row = MODELS.effective(provider)
    if not row:
        print(f"no such provider: {provider}", file=sys.stderr)
        return 1
    answer = annotate(discover(row), row)
    print(json.dumps(answer) if as_json else _human(provider, answer))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
