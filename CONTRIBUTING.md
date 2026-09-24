# Contributing

During the pilot: open an issue with the `pilot-feedback` template. Pull requests welcome for docs and templates. Code changes to `hq/` and `fleet/` need a short design note in the PR body until the public release.

Everything in this repository is English.

## Adding an engine or a place to run agents

murmur ships only what we have run for real: the **Claude Code** and **Codex** engines, on **your own machine** (any Linux box reached over SSH) or on a **DigitalOcean Droplet**. The other engine presets (Gemini CLI, Qwen Code, Kimi Code, Grok Build, OpenCode, Aider, Ollama, a free-form Custom command) and the remote runners (DigitalOcean Managed Agents, Railway, Vercel) were removed on 2026-09-24 by the owner's decision. Adding one back is a contribution, and the machinery that runs it is still in place, so a contribution is mostly data plus a test.

In the pull request, say what you ran for real with it: a lane spawned on it that opened a pull request, and where its terms say headless use is permitted. A preset nobody has run is exactly what was taken out.

### An engine preset

**The file:** `fleet/lib/model_presets.py`. Add one dict to `PRESETS`. Every field is required, so no reader has to guess:

| Field | What it holds |
|---|---|
| `id` | the preset's own name and the default catalog id: lower case, digits, `-` and `_` |
| `label` | the vendor's own name for it |
| `color` | a `#RRGGBB` glyph colour for the models table |
| `kind` | `subscription`, `key` or `local`: what the operator has to arrange. The add dialog gives a `key` engine `fleet models auth <id>` and a `local` one its `pull_hint` |
| `engine` | `"generic"` for any CLI other than Claude Code and Codex |
| `bin` | the command as it appears on the farm's `PATH` |
| `install_hint` | the one command that installs it |
| `pull_hint` | for a `local` engine, how a model is fetched (`<variant>` is filled in); `""` otherwise |
| `auth_env` | the variable the headless CLI reads its key from; `""` for a subscription |
| `run` | the non-interactive command line: `{bin}` and `{task}` are required, `{variant}` wherever the model goes |
| `health` | `HEALTH`: the test request asks for 17 plus 25, and only a reply line of `42` passes |
| `tos` | one sentence: whether running it headless is permitted, and how sure we are |
| `access` | one sentence: how it is paid for |
| `variants` | the model names it offers; a preset that lists any must carry `{variant}` in `run` |
| `docs` | where the vendor documents its CLI |

**Why no other code is needed.** A catalog entry with `engine = "generic"` is the mechanism, and it stays: `POST /api/models/add` and the Add a model dialog turn the preset into an entry with `model_presets.entry_from()`, `bin/fleet` launches it from `bin`, `run` and `auth_env` (`lib/models.py launchcmd`), `lib/parse_generic.py` reads its output into the lane's card, `fleet models auth <id>` stores its key on stdin, and `fleet models test <id>` runs the health request.

**Optional, model discovery:** `fleet/lib/model_discovery.py`. Add the documented model list to `DOCS` under the preset id, and, when the CLI can list models without sending a prompt, a function to `ROUTES` that returns `(rows, secrets)`: rows through `keep()`, and any credential it read on the way, so the answer is scrubbed of it.

**The tests to extend:** `fleet/tests/models-test.py` (the preset list assertion, now `["claude", "codex"]`, and a check of your preset's `run`, `install_hint` and `auth_env`), and `fleet/dashboard/test_stub_server.py` `MODEL_PRESETS` with `fleet/dashboard/test_hostile_models.mjs` when the dialog should show something new. Run:

```bash
cd fleet
python3 tests/models-test.py
python3 dashboard/test_server.py
```

### A machine preset

**The file:** `fleet/lib/host_presets.py`. Add one dict to `PRESETS` with `job = "machine"`. Every field is required:

| Field | What it holds |
|---|---|
| `id` | the provider name on every command line |
| `label`, `summary` | the vendor's name, and two short lines for its card (90 characters at most) |
| `color` | a `#RRGGBB` glyph colour |
| `job` | `machine`: a whole farm, with systemd user services, tmux, worktrees, the dashboard and the installer |
| `cli`, `install`, `login` | the binary the farm calls, the command that installs it, and the login a person runs in their own terminal (never the page) |
| `whoami` | the read-only login check, as an argv list; `{target}` in it means the check belongs to one machine |
| `docs`, `terms`, `stage`, `pricing` | where the CLI is documented, what you agree to and what is UNVERIFIED, `ga`, `preview` or `early access`, and one sentence on price with the day it was read |
| `sizes` | `[{slug, label, vcpu, ram_gb, disk_gb, monthly_usd, default}]`, exactly one `default: true`, or `[]` |
| `regions` | the regions offered, the first is the default, or `[]` |
| `engines` | the fleet engines it can run: `["claude", "codex"]` |

Then add the id to `HOSTING_PROVIDERS` in `fleet/dashboard/server.py`: the dashboard keeps unknown words out of an argv with it, and `HostingProvidersTest` fails when the two differ.

A box you reach over SSH needs nothing more: `fleet machines add` registers it and `fleet machines check` walks it to ready. A provider that **creates** machines also needs its create, list and destroy in `fleet/lib/machines.py`, which today speaks to DigitalOcean only (`doctl`): follow the `do-droplet` paths there, and keep its rules (the row is written before the provider is called, a price is confirmed before anything is bought, destroy needs the name typed back).

**The tests to extend:** `fleet/tests/hosting-test.py` (the preset list in `test_murmur_ships_your_own_machine_and_a_droplet_and_nothing_else`, and a fake of the provider's CLI under `fleet/tests/fakes/core/` that records every call, so no test spends money), `HostingProvidersTest` in `fleet/dashboard/test_server.py`, and `fleet/dashboard/test_hostile_hosting.mjs` when the Add a machine dialog changes. Run:

```bash
cd fleet
python3 tests/hosting-test.py
python3 dashboard/test_server.py
```
