# Models: providers, and the models you switch on

This design record explains the Models section of the dashboard's Machine tab: how you connect a
provider, and how you choose which of its models your agents may use. murmur ships two
providers, Claude Code and Codex. The code is `fleet/lib/models.py`, `fleet/lib/model_presets.py`,
`fleet/lib/model_discovery.py`, the model routes of `fleet/dashboard/server.py`, and the page
`fleet/dashboard/static/views/models.js`. A lane, in what follows, is one agent doing one task on
its own branch; `fleet spawn` starts one.

## 1. The shape

There are two levels:

- **A provider** is an agent CLI and the way it is paid for: Claude Code on a Claude
  subscription, or Codex on a ChatGPT subscription. You connect it once: install it, log in,
  test it.
- **A model** is one of the models a provider offers, such as Opus, Sonnet, Haiku or Fable on
  Claude Code, or the GPT models Codex lists. You switch on the ones agents may use. A lane
  names one with `fleet spawn --engine <provider> --model <model>`.

The reason for two levels: you log in and pay once per provider, but you choose a model per lane.

Each provider is one table in the farm's catalog, `$FLEET_CONFIG/models.toml`. Until the farm
writes its own, the shipped `fleet/config/models.example.toml` is read, and it carries both
providers. A provider is added from a preset in `model_presets.py`; murmur ships presets for
Claude Code and Codex only, and another engine is a contribution (see
[CONTRIBUTING.md](../../../CONTRIBUTING.md)). A table whose preset or engine murmur does not ship
stays in the catalog as it is. The page marks it "Not in the catalog", with one sentence on how
to take it out.

## 2. The page

The Models section shows the two levels: a table with one row per provider, and a sidebar with
one list of models per provider.

**The table.** Every cell is one line:

| Column | Shows |
|---|---|
| Provider | the name, with the command it runs in the tooltip |
| Access | Subscription, API key or Local, with the catalog's sentence in the tooltip |
| Status | one pill with the server's own status: Connected (the server's `on`), Off, Needs a key, Needs a login (Claude Code or Codex installed, with no login on the farm), Not installed, or Failing |
| Models | for example "3 on", with the names in the tooltip; the default model is counted |
| Last test | when the provider was last tested |
| Actions | Switch on or Switch off, and Test; Key (it copies `fleet models auth <id>`) when a key is missing; Remove for a row this farm added |

Test runs the provider's health check, as `fleet models test <id>` does. "Add a provider" opens
the dialog that writes a preset's entry into this farm's catalog. When every shipped preset is
already there, the dialog says so and points to CONTRIBUTING.md.

**The sidebar.** Clicking a provider's name opens its sidebar:

1. The provider's facts: its status in words, how it is paid for, its terms, and the login or key
   command, which you run in a terminal.
2. **One list of models.** It opens with the models that are on, ticked. The model a lane gets
   when `fleet spawn` names none carries a "Default" pill and cannot be unticked, because a bare
   spawn must always have a model. **Request available models** merges what the provider offers
   into the same list. New rows arrive unticked, with a source pill: From your account, or From
   the docs. Rows that are already on stay ticked and say "On". An "Add by name" field takes a
   model the list does not show. The button reads "Add 2 models", or "Save" when the change
   includes a removal, and it stays off until something changed. A request that fails says why in
   one fixed sentence (section 3), and shows the docs list instead.
3. A provider whose command cannot take a model at all shows one sentence instead of the list:
   "This provider runs the model its own settings choose; change it there." Claude Code and Codex
   always take a model. The sentence is for a `generic` row whose `run` line has no `{variant}`
   (section 5).

Request, tick and Save spend nothing: no prompt is sent, and Save never runs the health check.

## 3. Where a provider's model list comes from

A request must cost nothing. So no route ever sends a prompt: each one reads metadata only.

| Provider | How the list is read | What it knows |
|---|---|---|
| Codex | `codex debug models`, keeping only the rows whose `visibility` is `"list"` | what the Codex CLI on this farm lists; the page calls it From your account |
| Claude Code | the documented list kept in `model_discovery.py`: the aliases `sonnet`, `opus`, `haiku`, `fable`, `opus[1m]` and `sonnet[1m]`, and full ids such as `claude-opus-5-5` | the docs; murmur does not ask the Claude Code CLI |

**What a request keeps.** Only each model's `id`, a label (Codex's `display_name`) and a
description. Nothing else from the CLI's output is kept. The id must pass the model rule
(section 5), and the whole answer passes `fleet/lib/scrub.py`; a row whose id the scrub changed
is dropped. A failed request answers with the docs list and one of a fixed set of sentences
(`FAILURES` in `model_discovery.py`), never text from the provider. For example: "the CLI is not
installed", "it did not answer in 15 seconds", "its output could not be read", "the CLI exited
with an error" or "it listed no models". A provider with neither a route nor a docs list says
"this provider has no list to offer here; add a model by its name".

**Where it lives.** `fleet/lib/model_discovery.py` holds one docs list per preset id (`DOCS`), and
one function per provider that can list its own models (`ROUTES`; today that is Codex). The
method is chosen by the provider row's `preset`, falling back to its `engine` for the shipped
Claude Code and Codex rows. An answer is `{source: "account" | "docs", models: [{id, label,
description}], error}`. The CLI and the route then add each model's `cost_note` and `on`
(section 4).

## 4. Cost notes

Some models can cost money that the subscription does not cover. Such a model carries a note.
The note is decided by a rule on the model's family (`cost_note()` in `model_discovery.py`), and
never taken from the provider's answer. A `[1m]` suffix and a dated snapshot suffix are taken off
before the family is read. Today the rule notes three Claude models:

- `fable`: "some plans bill Fable to usage credits, and a headless run bills it without asking";
- `claude-opus-4-6[1m]`: "needs usage credits on Pro";
- `claude-sonnet-4-6[1m]`: "needs usage credits on every plan".

No Codex model carries a note.

Switching a noted model on asks once more, and the server enforces it. `POST /api/models/select`
refuses a noted model that is not on yet, unless `confirm_cost` names it, and `fleet models on`
wants `--confirm-cost <model>`. So that the confirmation means something, `fleet spawn` refuses a
noted model that is not on, with the note as its reason. Any other model that is not on only
gets a warning (section 5).

A description, such as the docs list saying that a model retires on a certain date, is shown in
the same Note column but asks nothing. A provider paid with an API key says "paid per token on
your key" once, in the Access column, not once per model.

## 5. Data, commands and spawn

**Data.** A provider's table carries `models_on = [...]`, the ids that are on. The shipped
example switches on `sonnet`, `opus` and `haiku` for Claude Code. A catalog that still has an
older `models = "sonnet, opus"` string is read as the first `models_on`, and the first save
replaces it. A provider's first saved list starts with its default model, so switching one more
model on never turns every default lane into a warning.

For Claude Code the default model is `FLEET_CLAUDE_MODEL` (from the environment or
`$FLEET_CONFIG/env`), else `opus`. For Codex it is `FLEET_CODEX_MODEL`, read the same way, else
`gpt-6-sol`. For a `generic` row it is the row's
`variant`.

**Commands.**

| Command | Does |
|---|---|
| `fleet models discover <provider> [--json]` | section 3; prints `{source, models, error}`, each model with its `cost_note` and `on` |
| `fleet models on <provider> <model>... [--confirm-cost <model>...]` | adds ids to `models_on`; runs nothing else |
| `fleet models off <provider> <model>...` | takes ids out; refuses the default model |

`on` and `off` rewrite only that provider's `models_on` line, under a lock. Before the new file is
written, it must parse, and it must differ from the old one only in that list.

**A model must reach the lane.** Claude Code and Codex take the lane's model through their own
launch code in `fleet/bin/fleet`. A `generic` row, from a contributed preset or a table you wrote
yourself, is launched from its `run` template by `models.py launchcmd`. It fills `{variant}` with
the lane's `--model`, or with the row's own `variant` when there is none. The value is
shell-quoted, because a name such as `opus[1m]` would otherwise be read as a glob. A row whose
`run` has no `{variant}` cannot take a model: the page shows the sentence of section 2, item 3,
and `fleet spawn` refuses `--model` for it.

**Spawn.** `fleet spawn --engine <e> --model <m>`:

- For Claude Code, the model is `sonnet`, `opus`, `haiku`, `fable`, `opus[1m]`, `sonnet[1m]`, or
  a full `claude-*` id.
- Every engine checks `--model` against the one model rule below.
- The provider may have a `models_on` list, and the model the lane will run (after the defaults
  above) may not be in it. Then spawn prints one warning line on stderr, or refuses when the
  model has a cost note (section 4). The warning goes to stderr so that the first line of stdout
  stays the spawn's result.
- A `generic` row whose `run` needs a model, and gets none, is refused.

**The one model rule** is `MODEL_RE` in `model_presets.py`, and the page mirrors it for "Add by
name": `^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,79}$`. A letter or a digit comes first, so no model
name can be read as an option by the CLI it is handed to. The provider id rule
(`^[a-z][a-z0-9_-]{1,30}$`) is a different rule.

## 6. Routes

| Route | Answer or effect |
|---|---|
| `GET /api/engines` | the catalog; each row carries `models_on: [id...]` and `default_model`, and `in_catalog` with `catalog_note` |
| `POST /api/models/discover {id}` | runs `fleet models discover <id> --json` through `run_tool`, so it uses the same codex binary lanes use, which the server does not have in its own environment; 20-second timeout; one request at a time per provider (a second gets a 409); answers `{source, models: [{id, label, description, cost_note, on}], error}` |
| `POST /api/models/select {id, on: [...], off: [...], confirm_cost: [...]}` | runs `fleet models on` and `fleet models off`; answers the updated row as `GET /api/engines` has it; 400 with `{error, cost_note, model}` for a noted model not in `confirm_cost`, and 400 for the default model in `off` |

The discover route keeps only `id`, `label` and `description` from the tool's answer, passes on
only the fixed failure sentences, scrubs the answer, and adds `cost_note` by rule. The tool's own
words never reach the page. An unknown provider is a 404 on both routes. Both routes are exact
paths above the `/api/models` prefix route in the server, and both need the write token and pass
the cross-site check.

## 7. Out of scope

- A test per model: the health check belongs to the provider.
- A model list per project.
- Usage and cost per model.
