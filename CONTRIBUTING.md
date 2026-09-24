# Contributing to murmur

Thank you for helping. Bug reports, fixes, documentation and new engines or
cloud providers are all welcome.

## Ways to help

- **Report a bug.** Open an issue with the bug template. Include the exact
  command you ran and the last lines of its output.
- **Suggest an improvement.** Open an issue with the feature template. Say what
  you were trying to do and what got in the way.
- **Fix something.** Small fixes (a typo, a wrong command in the docs, a clear
  bug) can go straight to a pull request. For a bigger change, open an issue
  first so we can agree on the approach before you spend time on it.
- **Report a security problem** privately, as [SECURITY.md](SECURITY.md)
  describes. Please do not use a public issue for it.

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## How the repository is laid out

| Folder | What it holds | Language |
| --- | --- | --- |
| [`plugin/`](plugin) | The Claude Code plugin: commands, skills, hooks and their scripts | Markdown, Python, Bash |
| [`fleet/`](fleet) | The farm: the `fleet` command, the dashboard and the systemd units | Bash, Python, JavaScript |
| [`hq/`](hq) | The head office command-line tool | Python |
| [`farm/`](farm) | The one-command farm installer | Bash |
| [`docs/`](docs) | The handbook | Markdown |
| [`templates/`](templates) | Files users copy into their own repositories | Markdown, Bash |
| [`design/`](design) | The design system used by the dashboard and the website | CSS, JavaScript |
| [`site/`](site) | The murmur.farm landing page | HTML, CSS |
| [`tests/`](tests) | Tests for the plugin | Python |

## Set up

You need:

- Python 3.11 or newer
- git and Bash
- Node.js 18 or newer, for the dashboard tests
- Optional: Playwright with Chromium, for the dashboard's browser tests

The Python code uses only the standard library, on purpose: the farm and the
head office must work on a machine that has little more than Python, git and
the GitHub CLI. Only the `hq` tests need an extra package (pytest).

## Run the tests

Run the tests for the part you changed before you open a pull request. CI runs
the same commands (see [`.github/workflows/`](.github/workflows)). All commands
start from the root of the repository.

The head office (`hq`) uses pytest, so install it in a virtual environment first:

```bash
cd hq
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q
```

The plugin:

```bash
python3 tests/test_plugin_installed_copy.py -v
python3 tests/test_murmur_farm.py -v
```

The farm (`fleet`), its main suites:

```bash
cd fleet
bash tests/policy-test.sh bin/fleet
python3 tests/supervisor-test.py lib/supervisor.py
python3 dashboard/test_server.py
python3 tests/hosting-test.py
```

[fleet/docs/VERIFYING.md](fleet/docs/VERIFYING.md) lists every suite, the
arguments each one takes, and how to run the dashboard's browser tests.

When you add a test, first make sure it fails without your fix. A test that
cannot fail proves nothing.

## Pull requests

- Keep each pull request to one topic. Small pull requests get reviewed faster.
- Explain what changed, why, and how you tested it.
- Update the documentation in the same pull request when behaviour changes.
- Add a line to the `Unreleased` section of [CHANGELOG.md](CHANGELOG.md) for
  anything a user would notice.
- Write everything in English: code, comments, docs and commit messages.
- Never put a real secret in a test or an example. Use fake values such as
  `ghp_` followed by `x` characters.

## Releasing (maintainers)

Claude Code sends a plugin update to users only when the plugin's version
changes. For each release:

1. Set the same new version in `.claude-plugin/marketplace.json` and
   `plugin/.claude-plugin/plugin.json`.
2. In [CHANGELOG.md](CHANGELOG.md), move the `Unreleased` entries under a
   heading with the version and the date.
3. Tag the release commit (`git tag v0.1.0`, for example) and push the tag.

By contributing, you agree that your contribution is licensed under the
[MIT License](LICENSE), like the rest of the project.

## Adding an agent engine

murmur ships two engines: **Claude Code** and **Codex**. Other engines can be
added as presets. The code that runs them already exists, so a new engine is
mostly data plus a test.

In your pull request, please tell us what you ran with it for real (for
example, a lane that opened a pull request) and whether the tool's terms allow
running it without a person at the keyboard.

**Where:** add one entry to `PRESETS` in
[`fleet/lib/model_presets.py`](fleet/lib/model_presets.py). Every field is required:

| Field | What it holds |
| --- | --- |
| `id` | The preset's name and default catalog id: lower case, digits, `-` and `_` |
| `label` | The vendor's name for the tool |
| `color` | A `#RRGGBB` colour for the models table |
| `kind` | `subscription`, `key` or `local`: what the user has to set up |
| `engine` | `"generic"` for any tool other than Claude Code and Codex |
| `bin` | The command, as it appears on the farm's `PATH` |
| `install_hint` | The one command that installs it |
| `pull_hint` | For a `local` engine, how to download a model (`<variant>` is filled in); `""` otherwise |
| `auth_env` | The environment variable the tool reads its key from; `""` for a subscription |
| `run` | The non-interactive command line. `{bin}` and `{task}` are required; `{variant}` goes where the model name goes |
| `health` | Use `HEALTH`. The test asks for 17 plus 25 and passes only on a reply of `42` |
| `tos` | One sentence: is running it unattended allowed, and how sure are we |
| `access` | One sentence: how it is paid for |
| `variants` | The model names it offers. If you list any, `run` must contain `{variant}` |
| `docs` | Where the vendor documents the tool |

**How it runs:** the dashboard's "Add a model" dialog and `POST /api/models/add`
turn the preset into a catalog entry. `fleet/bin/fleet` launches a `generic`
entry from its `bin`, `run` and `auth_env`, and
[`fleet/lib/parse_generic.py`](fleet/lib/parse_generic.py) turns its output into
the agent's card. `fleet models auth <id>` stores a key, and
`fleet models test <id>` runs the health check.

**Optional, model lists:** in
[`fleet/lib/model_discovery.py`](fleet/lib/model_discovery.py), add the
documented model names to `DOCS` under your preset's id. If the tool can list
its models without sending a prompt, also add a function to `ROUTES`.

**Tests to extend:** `fleet/tests/models-test.py` (it asserts the list of
presets, today `["claude", "codex"]`), and, if the dialog should show something
new, `MODEL_PRESETS` in `fleet/dashboard/test_stub_server.py` together with
`fleet/dashboard/test_hostile_models.mjs`. Then run:

```bash
cd fleet
python3 tests/models-test.py
python3 dashboard/test_server.py
```

## Adding a machine provider

murmur can run a farm on **a Linux machine you reach over SSH** or on a
**DigitalOcean Droplet**. Another provider is a preset plus, if it creates
machines, the code that creates them.

**Where:** add one entry to `PRESETS` in
[`fleet/lib/host_presets.py`](fleet/lib/host_presets.py), with `job = "machine"`.
Every field is required:

| Field | What it holds |
| --- | --- |
| `id` | The provider name used on every command line |
| `label`, `summary` | The vendor's name, and two short lines for its card (90 characters at most) |
| `color` | A `#RRGGBB` colour |
| `job` | `machine` |
| `cli`, `install`, `login` | The command the farm calls, the command that installs it, and the login a person runs in their own terminal (never in the dashboard) |
| `whoami` | A read-only login check, as a list of arguments. `{target}` in it means the check is for one machine |
| `docs`, `terms`, `stage`, `pricing` | Where the tool is documented; what you agree to and what is not verified; `ga`, `preview` or `early access`; one sentence on price, with the date you read it |
| `sizes` | `[{slug, label, vcpu, ram_gb, disk_gb, monthly_usd, default}]` with exactly one `default: true`, or `[]` |
| `regions` | The regions offered, the first one is the default, or `[]` |
| `engines` | The engines it can run: `["claude", "codex"]` |

Then add the id to `HOSTING_PROVIDERS` in
[`fleet/dashboard/server.py`](fleet/dashboard/server.py). The dashboard uses
that list to keep unknown words out of commands, and `HostingProvidersTest`
fails if the two lists differ.

A machine you reach over SSH needs nothing more: `fleet machines add` registers
it and `fleet machines check` walks it to ready. A provider that **creates**
machines also needs create, list and destroy code in
[`fleet/lib/machines.py`](fleet/lib/machines.py), which today talks only to
DigitalOcean (`doctl`). Follow the `do-droplet` code paths there and keep their
rules: the record is written before the provider is called, the price is
confirmed before anything is bought, and destroying a machine needs its name
typed back.

**Tests to extend:** `fleet/tests/hosting-test.py` (the preset list in
`test_murmur_ships_your_own_machine_and_a_droplet_and_nothing_else`, plus a fake
of the provider's command-line tool under `fleet/tests/fakes/core/` that records
every call, so no test spends money), `HostingProvidersTest` in
`fleet/dashboard/test_server.py`, and `fleet/dashboard/test_hostile_hosting.mjs`
if the "Add a machine" dialog changes. Then run:

```bash
cd fleet
python3 tests/hosting-test.py
python3 dashboard/test_server.py
```
