#!/usr/bin/env python3
"""The services a person can add as a model, one dict each.

The shipped catalog (config/models.example.toml) carries the two models a farm starts with,
claude and codex. Everything else a person might run is a PRESET here: a description complete
enough that adding it is picking a card, naming it, and pasting one command. `fleet models add`
and the dashboard's Add a model dialog both read this list, and POST /api/models/add turns one
preset plus a few answers into a catalog entry.

Fields, all present on every preset so a reader never has to guess:

  id            the preset's own name, and the default catalog id
  label         the human name, as the vendor writes it
  color         the provider's glyph colour on the models table
  kind          subscription | key | local: what the operator has to arrange
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
    {
        "id": "gemini",
        "label": "Gemini CLI",
        "color": "#4285F4",
        "kind": "key",
        "engine": "generic",
        "bin": "gemini",
        "install_hint": "npm install -g @google/gemini-cli",
        "pull_hint": "",
        "auth_env": "GEMINI_API_KEY",
        "run": "{bin} -m {variant} -p {task} --output-format json",
        "health": HEALTH,
        "tos": "a documented non-interactive mode (-p with --output-format json); the free "
               "Google-login tier is interactive sign-in on one machine, so a farm wants the key",
        "access": "an API key in GEMINI_API_KEY, or a Google login on its free tier",
        "variants": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "docs": "https://github.com/google-gemini/gemini-cli",
    },
    {
        "id": "qwen",
        "label": "Qwen Code",
        "color": "#7C5CFC",
        "kind": "key",
        "engine": "generic",
        "bin": "qwen",
        "install_hint": "npm install -g @qwen-code/qwen-code",
        "pull_hint": "",
        "auth_env": "QWEN_CODE_API_KEY",
        "run": "{bin} --model {variant} -p {task} --output-format stream-json",
        "health": HEALTH,
        "tos": "LOW: a documented headless mode, and the plan is sold for agentic use",
        "access": "an API key in QWEN_CODE_API_KEY; a flat request quota, no per-token billing",
        "variants": ["qwen3-coder-plus", "qwen3-coder-next", "qwen3.7-plus"],
        "docs": "https://github.com/QwenLM/qwen-code",
    },
    {
        "id": "kimi",
        "label": "Kimi Code",
        "color": "#6D5AE6",
        "kind": "key",
        "engine": "generic",
        "bin": "kimi",
        "install_hint": "install the vendor's Kimi CLI so that `kimi` is on this farm's PATH "
                        "(the package name is the vendor's to give: see docs)",
        "pull_hint": "",
        "auth_env": "KIMI_API_KEY",
        "run": "{bin} -m {variant} -p {task} --output-format stream-json",
        "health": HEALTH,
        "tos": "its subscription terms forbid non-interactive use, an API key plan is the "
               "permitted path. The install command and the exact headless flags could not be "
               "confirmed here: check both against the vendor's docs before enabling",
        "access": "an API key in KIMI_API_KEY, billed per token. Not the subscription: that one "
                  "is for interactive use only",
        "variants": ["kimi-code/kimi-for-coding"],
        "docs": "https://platform.moonshot.ai/docs",
    },
    {
        "id": "grok",
        "label": "Grok Build",
        "color": "#8A8F98",
        "kind": "key",
        "engine": "generic",
        "bin": "grok",
        "install_hint": "curl -fsSL https://x.ai/cli/install.sh | bash",
        "pull_hint": "",
        "auth_env": "XAI_API_KEY",
        "run": "{bin} --no-auto-update --always-approve -p {task} -m {variant} "
               "--output-format streaming-json",
        "health": HEALTH,
        "tos": "xAI's own CLI with a documented headless mode (-p, --no-auto-update for "
               "scripts). Headless it asks before every edit and command and nobody answers, so "
               "the lane runs with --always-approve, as xAI's own automation examples do; its "
               "output is one event per line (streaming-json), which the farm reads as it comes. "
               "A farm wants the API key: the plan sign-in needs `grok login --device-auth` once "
               "by hand. A community grok-cli also installs a `grok` binary: this preset is xAI's",
        "access": "an API key in XAI_API_KEY, billed per token",
        "variants": ["grok-4.7", "grok-build-0.1"],
        "docs": "https://docs.x.ai/build/cli/headless-scripting",
    },
    {
        "id": "opencode",
        "label": "OpenCode",
        "color": "#4C8DF6",
        "kind": "key",
        "engine": "generic",
        "bin": "opencode",
        "install_hint": "curl -fsSL https://opencode.ai/install | bash",
        "pull_hint": "",
        "auth_env": "OPENAI_API_KEY",
        "run": "{bin} run -m {variant} {task}",
        "health": HEALTH,
        "tos": "open source, and `opencode run` is its own documented non-interactive command",
        "access": "an API key, billed per token: OPENAI_API_KEY, or ANTHROPIC_API_KEY when you "
                  "point it at a Claude model (set the one your model needs)",
        "variants": ["openai/gpt-6-sol", "anthropic/claude-sonnet-5"],
        "docs": "https://opencode.ai/docs/cli",
    },
    {
        "id": "aider",
        "label": "Aider",
        "color": "#4FA07A",
        "kind": "key",
        "engine": "generic",
        "bin": "aider",
        "install_hint": "pip install aider-chat",
        "pull_hint": "",
        "auth_env": "OPENAI_API_KEY",
        "run": "{bin} --model {variant} --message {task} --yes",
        "health": HEALTH,
        "tos": "open source; --message runs one instruction and exits, --yes answers its "
               "confirmations. It edits and commits in the working tree it is started in",
        "access": "an API key, billed per token: OPENAI_API_KEY (or the provider variable the "
                  "model you choose needs)",
        "variants": ["openai/gpt-6-sol", "anthropic/claude-sonnet-5"],
        "docs": "https://aider.chat/docs/usage.html",
    },
    {
        "id": "ollama",
        "label": "Ollama local",
        "color": "#8A8F98",
        "kind": "local",
        "engine": "generic",
        "bin": "ollama",
        "install_hint": "curl -fsSL https://ollama.com/install.sh | sh",
        "pull_hint": "ollama pull <variant>",
        "auth_env": "",
        "run": "{bin} run {variant} {task}",
        "health": HEALTH,
        "tos": "runs on this machine, so there are no service terms to keep and no key to hold. "
               "The cost is the farm's own GPU and memory",
        "access": "nothing: it runs on this farm's own hardware",
        "variants": ["llama3.1", "qwen2.5-coder", "deepseek-coder"],
        "docs": "https://github.com/ollama/ollama",
    },
    {
        "id": "custom",
        "label": "Custom command",
        "color": "#8A8F98",
        "kind": "key",
        "engine": "generic",
        "bin": "",
        "install_hint": "",
        "pull_hint": "",
        "auth_env": "",
        "run": "",
        "health": HEALTH,
        "tos": "whatever the command you name allows: nobody here has read its terms for you",
        "access": "however the command you name is paid for",
        "variants": [],
        "docs": "",
    },
]

# The preset that is never "already added": a farm can carry any number of custom commands.
CUSTOM = "custom"

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

    # What the row is called. "Custom command" is the name of the CARD, not of a farm's own
    # command: three of them would be three identical rows, separable only by the mono id under
    # them, so the custom preset hands the naming over. A name given here wins for any preset,
    # and models.add_model() falls back to the id when there is none.
    label = str(given.get("label") or "").strip()
    if len(label) > 60:
        return None, "a name longer than 60 characters is not a name a table row can show"
    if label or preset["id"] == CUSTOM:
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
