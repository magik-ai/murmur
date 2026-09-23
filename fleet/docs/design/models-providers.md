# Models: providers, and the models you switch on

Design record, 2026-09-23. The owner: "it would be good like this: you connect a provider as a
subscription, then you click it and choose in a sidebar which models you want to activate; for
that you press a button 'Request available models' and get a list where you tick what you want
to add, and the ones already added are marked."

## 1. The shape

Two levels, which today's Models table folds into one:

- **A provider** is an agent CLI and the way it is paid for: Claude Code on a Claude
  subscription, Codex on a ChatGPT plan, Gemini CLI, Qwen Code, Kimi Code, OpenCode, Aider,
  Ollama on this machine, or a custom command. You connect it once (install, log in, test), as
  the Models section already lets you.
- **A model** is one of the models that provider offers to your account (Opus, Sonnet and
  Haiku on Claude; the GPT-6 family on Codex; whatever Ollama has pulled). You switch on the
  ones agents may use. A lane names one with `fleet spawn --engine <provider> --model <model>`.

## 2. The page

The Models section becomes a table of providers, every cell one line: Provider (name, with the
command it runs in the tooltip), Access (Subscription, API key, Local), Status (the server's
own five words, one pill: Connected for what the server calls on, Off, Needs a key, Not
installed, Failing), Models ("3 on", the names in the tooltip), Last test, Actions (Test,
Switch off or on). Test is today's provider test, unchanged. "Add a provider" is today's Add a
model dialog, renamed.

**Clicking a provider opens the sidebar** (the drawer the name opens today):

1. The provider's facts: status in words, the login or key command, how it is paid for, its
   terms.
2. **One list of models.** It opens with the models that are on, each a ticked row: name, id,
   and, on the model a lane gets when `fleet spawn` names none, a "Default" pill; that row
   cannot be unticked (untick it and no bare spawn would have a model). **Request available
   models** merges what the provider offers into the same list: new rows arrive unticked, rows
   already on stay ticked and say "On", and each new row carries a source pill (From your
   account, or From the docs). An "Add by name" field under the list takes a model the list
   does not show (the only way in for a custom provider). The list ends with "Add 2 models", or
   "Save" when the change includes a removal, disabled until something changed. A request that
   fails says why in one of a fixed set of sentences and shows the docs list instead.
3. A provider whose command cannot take a model at all (section 5) shows one sentence instead
   of the list: "This provider runs the model its own settings choose; change it there."

Request, tick and Save run nothing that spends: no prompt is sent, and Save never triggers the
provider's health test.

## 3. Where a provider's model list comes from

Never by sending a prompt: every route reads metadata only, and none spends tokens. Researched
against each provider's docs and source on 2026-09-23
(`internal/research/report-model-discovery.md`):

| Provider | How the list is asked for | What it knows |
|---|---|---|
| Codex | `codex debug models`, rows with `visibility == "list"` | your account's list (the CLI marks this command experimental) |
| Ollama | `GET http://127.0.0.1:11434/api/tags` | the models pulled on this machine |
| Qwen Code | read `~/.qwen/settings.json` `modelProviders` | what your configured providers offer |
| Kimi Code | read `~/.kimi/config.toml` `[models.*]` | what its login wrote there |
| OpenCode | `opencode models` | its catalog, not a plan check |
| Claude Code | the docs list: `opus`, `sonnet`, `haiku`, `fable`, full ids such as `claude-opus-5-5` | the docs; Claude Code lists a subscription's models only inside a running session |
| Gemini CLI, Aider | the docs list (a key-based list is a follow-up: it is the only route where the server would hold a key, and those lists mix in embedding and image models) | the docs |
| Custom | none | what the person types |

**What a request keeps.** Only `id`, a label (`name` or `display_name`) and a description;
nothing else from the file, the CLI's output or the HTTP body is kept, and the answer passes
`fleet/lib/scrub.py` as well (the Qwen and Kimi files can hold API keys). A failure is one of a
fixed set of sentences ("the CLI is not installed", "it did not answer in 15 seconds", "its
output could not be read", "the file is missing"), never text from the provider.

`fleet/lib/model_discovery.py` holds one function and one docs list per preset id; the method
is chosen by the provider row's `preset`, falling back to its `engine` for the shipped Claude
and Codex rows. An answer is `{source: "account" | "docs", models: [{id, label, note}], error}`.

## 4. Cost notes

A note travels with a model whose use can cost money the subscription does not cover:

- Claude `fable`: some plans bill it to usage credits, and in headless runs it bills without
  asking.
- `claude-opus-4-6[1m]` on Pro and `claude-sonnet-4-6[1m]` on every plan need usage credits.
  (`opus` and `sonnet` are Opus 5.5 and Sonnet 5, which run 1M context on every plan and need no
  note.)

Switching a noted model on asks once more, and the server enforces it: `POST
/api/models/select` refuses a noted model unless `confirm_cost` names it. So that the confirm
means something, `fleet spawn` refuses a noted model that is not on, with the note as its
reason; every other model that is not on only warns. A retirement date is shown as a note but
asks nothing, and API key providers say "paid per token on your key" once, in the Access
column, not per model.

## 5. Data, commands and spawn

**Data.** A provider's catalog entry gains `models_on = [...]`, the ids that are on. (The
shipped example's `models = "sonnet, opus, haiku"` is a string the page reads today; it is
retired in the same change and its value becomes Claude's first `models_on`.)

**Commands.**

| Command | Does |
|---|---|
| `fleet models discover <provider> [--json]` | section 3; prints `{source, models, error}` |
| `fleet models on <provider> <model>... [--confirm-cost <model>...]` | adds ids to `models_on` |
| `fleet models off <provider> <model>...` | removes them; refuses the default model |

**A model must reach the lane.** Today a generic provider's command template fills `{variant}`
from the catalog row's single `variant`, and the Qwen, Kimi, OpenCode and Aider templates have
no `{variant}` at all, so a model chosen on the page would never run. So: the launch command
takes the lane's `--model` and fills `{variant}` with it (the row's `variant` when there is
none), shell-quoted (a `[1m]` would otherwise glob); each preset's `run` gains its model flag
(`qwen --model {variant}`, `kimi -m {variant}`, `opencode run -m {variant}`, `aider --model
{variant}`); a row whose `run` still has no `{variant}` shows the sentence of section 2 item 3,
and spawn refuses `--model` for it.

**Spawn.** `fleet spawn --engine <e> --model <m>` keeps working as today, with three changes: the
Claude names accept `'opus[1m]'` and `'sonnet[1m]'` (quoted in the case pattern); every engine
checks `--model` against the one model rule below; and when the provider has a `models_on` list
and the model the lane will actually run (after the defaults resolve: `sonnet` for Claude,
`FLEET_CODEX_MODEL` for Codex, the row's `variant` otherwise) is not in it, spawn prints one
warning line on stderr (the supervisor reports stdout's first line, which must stay the spawn
result), or refuses when the model has a cost note (section 4).

**The one model rule** replaces `VARIANT_RE` in `model_presets.py` and is mirrored by the page
for "Add by name": `^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,79}$` (a letter or digit first, so no
model name can become an option). The provider id rule (`^[a-z][a-z0-9_-]{1,30}$`) is a
different thing and stays.

## 6. Routes

| Route | Answer or effect |
|---|---|
| `GET /api/engines` | each row gains `models_on: [id...]` and `default_model` |
| `POST /api/models/discover {id}` | runs `fleet models discover <id> --json` through `run_tool` (so the server uses the same codex binary lanes use, which it does not have in its own environment); 20 second timeout; one at a time per provider; `{source, models: [{id, label, note, on}], error}` |
| `POST /api/models/select {id, on: [...], off: [...], confirm_cost: [...]}` | runs `fleet models on` and `off`; answers the updated row; 400 with the note for a noted model not in `confirm_cost`, and for the default model in `off` |

The two new routes sit above the `startswith("/api/models")` catch-all in the POST chain, beside
`/api/models/remove`. Both are behind the token and the cross-site refusal.

## 7. Delivery

Two lanes. Other lanes are editing `server.py`, `machine.js`, `cmd_spawn` and the stub right now,
so each keeps its code in files of its own:

- **models-discovery** (library, CLI, server): `fleet/lib/model_discovery.py` (new),
  `fleet/lib/model_presets.py` (the model rule, the `run` model flags), `fleet/lib/models.py`
  (`models_on`, on, off, the quoted `{variant}`), `fleet/config/models.example.toml` (the string
  retired), `fleet/bin/fleet` (`models discover|on|off` inside `cmd_models`; in `cmd_spawn` only
  the Claude names and one call after the engine blocks that asks `models.py` whether to warn
  or refuse), `fleet/dashboard/server.py` (the two routes and the two fields, a few lines each),
  `fleet/tests/models-test.py` (new cases go here: CI already runs this file), and
  `fleet/docs/OPERATIONS.md`.
- **models-ui**: only the models functions move from `machine.js` to
  `fleet/dashboard/static/views/models.js` (new). The helpers other dialogs share (`stepHead`,
  `commandRow`, `detailRow`, `copyCommand`) stay in `machine.js` with `export`; the render line
  stays `modelsSection(context)`, imported under that name; `needs` and `machine.css` are not
  touched. Also `fleet/dashboard/static/models.css`, `fleet/dashboard/index.html` (the link),
  `fleet/dashboard/stub_models.py` (new; one dispatch line in the stub),
  `fleet/dashboard/test_hostile_models.mjs`, `fleet/dashboard/test_screens_models.mjs`, and the
  models checks inside `test_hostile_queue_machine.mjs` and `test_screens_queue_machine.mjs`,
  which move to the new files.

Out of scope: a per-model test run; per-project model lists; usage and cost per model; key-based
lists for Gemini and Aider.

## 8. Review

An independent reviewer returned RED with twelve findings, all folded in above: the lane's
model now reaches generic providers (it never did); `models_on`, since `models` is already a
string; the Claude `[1m]` names spawn accepts; no per-model test (it was either empty or costly,
and could block a provider); the cost confirm enforced by spawn and the server, and asked only
where money is at stake; only ids, labels and descriptions kept from files that hold keys, with
Gemini and Aider on the docs list; discovery run through `fleet` so it uses the lanes' codex; the
default model marked and kept; one model rule with a letter or digit first; the routes placed
above the catch-all; the move limited to the models functions; one list in the drawer with an
"Add by name" field, and the server's own status words.
