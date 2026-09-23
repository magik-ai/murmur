"""The two model routes of design section 6, as the browser checks' stub answers them.

POST /api/models/discover {id} answers {source, models: [{id, label, description, cost_note, on}],
error}, and POST /api/models/select {id, on, off, confirm_cost} writes `models_on` on the stub's
own catalog row and answers it. `description` is free text and never asks anything; `cost_note`
is set by rule, and only for a model that can cost money the subscription does not cover. Nothing here runs a CLI, reads a provider's file or opens a socket: the lists
are written below, in the shape the server's `fleet models discover --json` gives, so a browser
check can never reach a provider or the live farm.

test_stub_server.py hands every POST to these two paths here, in one line, with the catalog rows
as they stand. The rows are the stub's own dicts, so a save is seen by the next GET /api/engines.
"""
import re

# The one model rule (design section 5), the same as lib/model_presets.py and the page.
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,79}$")

FABLE_NOTE = "Some plans bill Fable to usage credits, and a headless run bills without asking."

# The cost rule of section 4, decided by pattern and never by a lookup of a few strings, so a
# full id (claude-fable-5-1) or a dated one asks the same question as its alias. Only a Claude
# provider bills this way. Switching a noted model on asks once more, and the route refuses it
# unless confirm_cost names it.
COST_RULES = (
    (re.compile(r"^(claude-)?fable(-[0-9][0-9a-z.-]*)?(\[1m\])?$", re.I), FABLE_NOTE),
    (re.compile(r"^(claude-)?opus-4-6(-[0-9]+)?\[1m\]$", re.I), "Needs usage credits on Pro."),
    (re.compile(r"^(claude-)?sonnet-4-6(-[0-9]+)?\[1m\]$", re.I), "Needs usage credits on every plan."),
)


def cost_note(row, mid):
    """The cost note for this model on this provider, or "" when it needs no second question."""
    if str(row.get("engine") or row.get("id") or "") != "claude":
        return ""
    return next((note for pattern, note in COST_RULES if pattern.match(str(mid))), "")


# What a request answers per provider: id, label and description. A description is text from the
# provider or the docs, a retirement date or a plan's pick among them, and it asks nothing.
LISTS = {
    "claude": ("docs", "", [
        ("opus", "Opus 5.5", ""),
        ("sonnet", "Sonnet 5", ""),
        ("haiku", "Haiku 4.5", ""),
        ("fable", "Fable 5.1", "The largest model."),
        ("claude-opus-5-5", "Opus 5.5, by its full id", ""),
        ("claude-sonnet-4-6[1m]", "Sonnet 4.6 with 1M context", ""),
    ]),
    "codex": ("account", "", [
        ("gpt-6-astra", "GPT-6 Astra", "Costs more per task than Sol, and is billed to the plan."),
        ("gpt-6-sol", "GPT-6 Sol", "The docs' pick for Plus, Pro, Business, Enterprise and Edu."),
        ("gpt-6-luna", "GPT-6 Luna", ""),
        ("gpt-5.5", "GPT-5.5", "Retires on 2026-10-14."),
    ]),
    "qwen": ("account", "", [
        ("qwen3-coder-plus", "Qwen3 Coder Plus", ""),
        ("qwen3.7-plus", "Qwen3.7 Plus", ""),
    ]),
    # The file its login writes is not there, so the answer is the docs list and the reason.
    "kimi": ("docs", "the file is missing", [
        ("kimi-code/kimi-for-coding", "Kimi for Coding", ""),
    ]),
    "local": ("docs", "the CLI is not installed", []),
}


def on_list(row):
    """The ids that are on: the row's `models_on`, or the old string a fixture still carries."""
    if isinstance(row.get("models_on"), list):
        return [str(item) for item in row["models_on"] if item]
    return [part.strip() for part in str(row.get("models") or "").split(",") if part.strip()]


def default_of(row):
    said = row.get("default_model")
    return str(said if said is not None else row.get("variant") or "")


def discover(row):
    source, error, models = LISTS.get(row["id"], ("docs", "", []))
    on = set(on_list(row))
    return 200, {"source": source, "error": error or None,
                 "models": [{"id": mid, "label": label, "description": text,
                             "cost_note": cost_note(row, mid), "on": mid in on}
                            for mid, label, text in models]}


def select(row, body):
    wanted_on = [str(item) for item in body.get("on") or []]
    wanted_off = [str(item) for item in body.get("off") or []]
    confirmed = {str(item) for item in body.get("confirm_cost") or []}
    for mid in wanted_on + wanted_off:
        if not MODEL_RE.match(mid):
            return 400, {"error": f"{mid[:40]} is not a model name"}
    if default_of(row) and default_of(row) in wanted_off:
        return 400, {"error": f"{default_of(row)} is the default model, so it stays on"}
    for mid in wanted_on:
        if cost_note(row, mid) and mid not in confirmed:
            return 400, {"error": cost_note(row, mid), "cost_note": cost_note(row, mid), "model": mid}
    now = [mid for mid in on_list(row) if mid not in wanted_off]
    now += [mid for mid in wanted_on if mid not in now]
    row["models_on"] = now
    return 200, {"model": row}


def post(path, body, rows):
    """(code, payload) for one of the two routes."""
    wanted = str(body.get("id") or "").strip()
    row = next((item for item in rows if item.get("id") == wanted), None)
    if row is None:
        return 404, {"error": f"no such provider: {wanted[:40]}"}
    if path == "/api/models/discover":
        return discover(row)
    return select(row, body)
