#!/usr/bin/env python3
"""Which models a provider offers, asked without spending anything.

One docs list per preset id, and one function for a provider that can say what it offers
(design: fleet/docs/design/models-providers.md, section 3). Every route reads metadata only: no
prompt is ever sent, so no request here costs a token. The method is chosen by the provider row's
`preset`, falling back to its `engine` for the shipped Claude and Codex rows. A contributed
preset adds its docs list to DOCS and, when its CLI can list models, a function to ROUTES.

An answer is {source: "account" | "docs", models: [{id, label, description}], error}, and
annotate() adds each model's `cost_note` and `on` (design section 6):

  source   "account" when the provider itself answered (its CLI, its local file, its port),
           "docs" when the list is the one its documentation gives
  models   only an id, a label and a description are kept from any source. A vendor's own file
           can hold API keys, a CLI can print anything, and none of that is ours to pass on.
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


# What each provider's documentation says it offers, as read on 2026-09-23. A description here
# is shown and asks nothing; only the cost rule above asks.
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
}


class Failed(Exception):
    """A discovery route that did not work, carrying one FAILURES key."""

    def __init__(self, key):
        super().__init__(key)
        self.key = key


def method(row):
    """The preset id whose route this provider row uses: its `preset`, else its `engine` (the
    shipped claude and codex rows carry no preset), else "" (no route and no list)."""
    row = row or {}
    preset = str(row.get("preset") or "").strip()
    if preset in DOCS:
        return preset
    engine = str(row.get("engine") or "").strip()
    if engine in ("claude", "codex"):
        return engine
    return ""


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
    """The codex CLI lanes run, found as bin/fleet finds it (model_presets.engine_bin)."""
    return PRESETS.engine_bin("codex")


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


# A route returns (rows, secrets): the rows through keep(), and every credential-looking value it
# read on the way (a vendor file's API key), which is added to the scrub of the answer.
ROUTES = {"codex": from_codex}


def discover(row):
    """{source, models, error} for one provider row. Never raises, never sends a prompt."""
    how = method(row)
    route = ROUTES.get(how)
    if route is None:
        listed = docs_list(row)
        # A row with neither a route nor a documented list (a hand-written command, a row whose
        # preset was removed) says so, rather than answering a press with nothing at all.
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
