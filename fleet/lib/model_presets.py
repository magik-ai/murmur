#!/usr/bin/env python3
"""The engines a person can add as a model, one dict each.

murmur ships presets for two engines, Claude Code and Codex, and the shipped catalog
(config/models.example.toml) already carries both. CONTRIBUTING.md says how to add another.

The list is still the mechanism an engine is added by: a preset is a description complete enough
that adding it is picking a card, naming it, and pasting one command. The dashboard's Add a model
dialog reads this list, POST /api/models/add turns one preset plus a few answers into a catalog
entry (entry_from below), and a catalog entry whose engine is "generic" is launched by
bin/fleet from its `bin`, `run` and `auth_env` (models.py launchcmd, parse_generic.py). So a
contributor adds an engine by adding one dict here; CONTRIBUTING.md says which fields and which
test to extend.

Fields, all present on every preset so a reader never has to guess:

  id            the preset's own name, and the default catalog id
  label         the human name, as the vendor writes it
  color         the provider's glyph colour on the models table
  kind          subscription | key | local: what the operator has to arrange. A key engine is
                given `fleet models auth <id>` in the dialog, a local one its pull_hint
  engine        the launcher path: "claude", "codex", or "generic" (a CLI template)
  bin           the command, as it must appear on this farm's PATH
  install_hint  the one command that puts that binary there
  pull_hint     for a local runner, how a variant is fetched ("" for the rest)
  auth_env      the env var the headless CLI reads for its credential ("" for a subscription)
  run           the non-interactive invocation; {bin}, {task} and {variant} are substituted
  health        the tiny prompt a test request sends
  tos           whether running it headless is permitted, and how sure we are of that
  access        one sentence: how this is paid for
  variants      the model names this service offers, may be empty. A preset that lists any
                MUST carry {variant} in its run, or the model a person picks in step 2 would
                never reach the command line
  docs          where the vendor documents the CLI

Accuracy: every install command and run flag below is the one the tool's own documentation
gives. Where a vendor's packaging could not be confirmed from this machine, the preset says so
in its own `tos` sentence rather than inventing a package name, and the operator is sent to
`docs`. Nothing here is dated: a plan that is out of room today is a fact about a farm, not
about a service, and belongs in that farm's own models.toml.
"""
import copy
import re

# The answer is not in the question: a CLI that echoes the prompt, or quotes it back in an error
# about a bad key, must not pass the Test. models.health_check passes only a reply line that is 42 alone.
HEALTH = "What is 17 plus 25? Reply with the number only."
HEALTH_ANSWER = "42"
# What every added row was written with before, and what those farms' models.toml still say.
# Its answer is in its own text, so a row that carries it is asked the new question instead.
LEGACY_HEALTH = "Reply with exactly: OK"

PRESETS = [
    {
        "id": "claude",
        "label": "Claude Code",
        "color": "#D97757",
        "kind": "subscription",
        "engine": "claude",
        "bin": "claude",
        "install_hint": "npm install -g @anthropic-ai/claude-code",
        "pull_hint": "",
        "auth_env": "",
        "run": "{bin} -p {task}",
        "health": HEALTH,
        "tos": "first-party CLI on the Anthropic OAuth subscription; headless use is what it is for",
        "access": "your Claude subscription, shared with your own interactive sessions",
        # No choice of model here: the claude engine is launched by bin/fleet with the model the
        # lane was spawned with, so a name recorded on this row would never reach the command.
        "variants": [],
        "docs": "https://docs.claude.com/en/docs/claude-code/overview",
    },
    {
        "id": "codex",
        "label": "Codex",
        "color": "#10A37F",
        "kind": "subscription",
        "engine": "codex",
        "bin": "codex",
        "install_hint": "npm install -g @openai/codex",
        "pull_hint": "",
        "auth_env": "",
        "run": "{bin} exec {task}",
        "health": HEALTH,
        "tos": "first-party CLI on the ChatGPT subscription (auth_mode chatgpt)",
        "access": "your ChatGPT subscription",
        "variants": [],
        "docs": "https://developers.openai.com/codex/cli",
    },
]

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")
# The one model rule: every model name that reaches a command line passes it, whichever engine
# runs it and whether it came from a person, a provider's list or `fleet spawn --model`. A letter
# or digit first, so no model name can ever read as an option to the CLI it is handed to. The
# page mirrors it for "Add by name". The provider id rule above is a different thing.
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,79}$")
MODEL_RULE = ("a model name is letters, digits and . _ : / [ ] -, starting with a letter or "
              "digit, at most 80 characters")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,60}$")

# What a catalog entry may carry out of a preset. `kind` and `variants` and `docs` describe the
# service, not this farm's row, so they stay here and are read back through by_id().
ENTRY_FIELDS = ("color", "label", "engine", "bin", "install_hint", "auth_env", "run", "health", "tos_kind",
                "tos", "access")


def presets():
    """The list, copied, so a caller that annotates a row cannot edit the shipped description.
    Every row carries `tos_kind`, the one word the page colours its terms pill with."""
    rows = copy.deepcopy(PRESETS)
    for row in rows:
        row["tos_kind"] = tos_kind(row.get("tos"))
    return rows


def by_id(pid):
    for preset in PRESETS:
        if preset["id"] == str(pid or ""):
            return copy.deepcopy(preset)
    return None


def entry_from(preset_id, overrides=None):
    """(catalog entry, error sentence). The entry is the preset plus this farm's answers, ready
    for models.add_model(); the id is the caller's to set."""
    preset = by_id(preset_id)
    if not preset:
        return None, f"no such preset: {preset_id}"
    given = dict(overrides or {})
    entry = {field: preset.get(field, "") for field in ENTRY_FIELDS}
    entry["tos_kind"] = tos_kind(preset.get("tos"))
    entry["preset"] = preset["id"]

    for field in ("bin", "run", "auth_env"):
        value = str(given.get(field) or "").strip()
        if value:
            entry[field] = value

    # What the row is called. A name given here wins over the preset's own label.
    label = str(given.get("label") or "").strip()
    if len(label) > 60:
        return None, "a name longer than 60 characters is not a name a table row can show"
    if label:
        entry["label"] = label
    if entry["auth_env"] and not ENV_RE.match(entry["auth_env"]):
        return None, (f"{entry['auth_env']} is not an environment variable name: capitals, "
                      "digits and underscores")

    variant = str(given.get("variant") or "").strip()
    if variant and not MODEL_RE.match(variant):
        return None, f"{variant} is not a model name this page will write into a command"
    if "{variant}" in entry["run"] and not variant:
        choices = ", ".join(preset["variants"]) or "one the service offers"
        return None, f"{preset['label']} needs a model: {choices}"
    if variant and "{variant}" not in entry["run"]:
        # Recording a model name that the command line has no room for is how a person ends up
        # reading one model in the table and paying for another.
        return None, (f"{preset['label']} runs one model: put {{variant}} in the command line "
                      "if it should be told which one")
    if variant:
        entry["variant"] = variant

    if not entry["bin"]:
        return None, f"{preset['label']} needs the command to run (bin)"
    if not entry["run"]:
        return None, f"{preset['label']} needs the non-interactive command line (run)"
    if "{task}" not in entry["run"]:
        return None, "the command line must say where the task goes: use {task}"
    return entry, ""


def _human(preset):
    return (f"{preset['id']:<10} {preset['label']:<16} {preset['kind']:<13} {preset['access']}")


if __name__ == "__main__":
    import json
    import sys
    if sys.argv[1:2] == ["json"]:
        print(json.dumps(presets(), indent=2))
    else:
        for row in PRESETS:
            print(_human(row))


# The terms of a service as one word the page can colour: safe, check or blocked. The sentence
# is the operator's to read; the word is what the pill says before they have.
_TOS_BLOCKED = re.compile(r"\b(forbid|forbids|forbidden|blocked|not permitted|interactive use only)\b", re.I)
_TOS_CHECK = re.compile(r"\b(high|risk|risks|suspension|check|unknown|could not be confirmed|nobody here has read)\b", re.I)
_TOS_SAFE = re.compile(r"\b(documented|first-party|open source|no service terms|on this machine|own hardware)\b", re.I)


def tos_kind(text):
    """safe, check or blocked, from a terms sentence. Unknown terms are a thing to read."""
    said = str(text or "")
    if _TOS_BLOCKED.search(said):
        return "blocked"
    if _TOS_CHECK.search(said):
        return "check"
    return "safe" if _TOS_SAFE.search(said) else "check"
