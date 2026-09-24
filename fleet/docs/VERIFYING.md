# Running the tests

This page lists every test suite in this repository: the command that runs it, what it covers and
what it needs. Run the suites for the part you changed before you open a pull request.
[CONTRIBUTING.md](../../CONTRIBUTING.md) has the short version.

| Part | Tests | Runner |
|---|---|---|
| The farm runner (`fleet`) | `fleet/tests/` | Python and Bash scripts |
| The dashboard | `fleet/dashboard/test_*` | Python, Node.js and a browser |
| The head office CLI (`hq`) | `hq/tests/` | pytest |
| The Claude Code plugin | `tests/` | Python |

A farm is the always-on Linux machine that runs the agents, and `fleet` is the command that runs
it. A lane is one agent doing one task on its own branch.

## Before you start

You need Python 3.11 or newer, git and Bash. The dashboard tests also need Node.js 18 or newer, and
the browser tests need Playwright with Chromium (see
[What the browser tests need](#what-the-browser-tests-need)). Only the `hq` tests need an extra
Python package, pytest.

Every suite sets up its own throwaway world: temporary state and config directories, local git
repositories and fake command-line tools. No suite changes a live farm, and none reaches GitHub or
a cloud provider. There is one small exception: `stale-status-test.sh` starts a short-lived
systemd user unit.

Run the tests as an ordinary user. The farm installer refuses to run as root, so its tests skip
under root. A few other cases skip, and say why, on a machine without IPv6 or without a systemd
user manager.

## The farm runner

Run these from the `fleet/` directory:

```bash
cd fleet
```

### Suites that take a path

Six suites test the file you name on the command line:

```bash
python3 tests/supervisor-test.py lib/supervisor.py   # the daemon: respawns, cooldown, attempt cap
python3 tests/train-test.py      lib/supervisor.py   # --after: a gated lane waits for its dependency
python3 tests/blind-test.py      lib/supervisor.py   # GitHub unreachable: no respawn
python3 tests/scope-test.py      lib/supervisor.py   # --issues: no delivery while an issue is dropped
python3 tests/group-test.py      bin/fleet           # fleet group; spawn rollback; hard briefs
bash    tests/salvage-test.sh    bin/fleet           # fleet clean, salvage and sweep
```

Without the argument each suite tests the file in its own checkout. Pass a path to test another
one. The Python suites refuse the wrong kind of file: give a supervisor suite `bin/fleet` and it
stops with a message instead of a false result.

`group-test.py` also covers what spawn does with a difficult brief: quotes, a trailing backslash,
and a prompt over the size limit. `salvage-test.sh` covers what the destructive commands keep,
what they remove and what they save first.

### The other suites

```bash
bash    tests/policy-test.sh bin/fleet   # policy.toml and projects.toml at spawn time
python3 tests/events-test.py             # the event journal and the filters of `fleet events`
python3 tests/salvage-test.py            # rescue refs for commits that were never pushed
bash    tests/silent-start-test.sh       # an engine that dies before its first turn is `failed`
bash    tests/stale-status-test.sh       # `fleet status` flags a lane whose unit is gone
python3 tests/model-switch-test.py       # a lane that changes model mid-run is recorded once
python3 tests/accounts-test.py           # which Claude account a lane takes
python3 tests/codex-usage-test.py        # reading Codex usage windows
python3 tests/sensors-test.py            # optional GPU and CPU sensors, and `fleet mode auto`
python3 tests/models-test.py             # the model catalog, its presets, the models.toml writer
python3 tests/scrub-test.py              # secrets are removed from text the dashboard shows
python3 tests/hosting-test.py            # hosting presets, the machine registry, the installer
python3 tests/one-click-farm-test.py     # the one-click farm: machines, installer, dashboard
```

A few details:

- `policy-test.sh` checks the head office switch, the commit identity a lane pushes under, the
  port block each project hands its lanes, a policy file that does not parse, the names a spawn
  accepts, the pending spec `fleet spawn --after` writes, the env file `~/.config/fleet/env`, and
  `fleet kill`. Its argument is optional: it defaults to the `bin/fleet` next to it.
- `stale-status-test.sh` starts a real systemd user unit to stand for a live lane. Without a
  running user manager it skips that case. It tests the `bin/fleet` next to it; set
  `FLEET=<path>` to test another one.
- The other suites load the code next to the test file. `events-test.py`, `salvage-test.py` and
  `codex-usage-test.py` also accept `FLEET_HOME=<checkout>` to test a different checkout.

## The dashboard

Run these from the `fleet/` directory too:

```bash
python3 dashboard/test_server.py          # every API route, access rules, background snapshots
python3 dashboard/test_github_access.py   # the GitHub connection behind the Projects section
node    dashboard/test_ui.mjs             # the page without a browser: modules, route shapes
node    dashboard/test_token_fragment.mjs # a token in the address is taken, then removed from it
bash    dashboard/test_browser.sh         # everything that needs a real browser
```

`test_ui.mjs` starts the stub server itself, so it reads the same fixtures as the browser tests.
`test_palette.mjs` is not a suite: it is a helper that `test_ui.mjs` imports.

### The browser tests

`test_browser.sh` runs every check that needs a real browser:

1. It starts the stub server, `test_stub_server.py`, on a free port. The stub serves the real page
   with fixed test data.
2. It runs `test_status_colours.mjs` against the stub: the five status colours on the Machine
   tab, in the light and the dark theme, must read as the status they stand for.
3. It runs `test_render_defer.mjs` against the stub. The page updates itself every three seconds,
   and it must not rebuild itself under you: a click, a half-typed message, an open drawer and the
   scroll position must all survive the update.
4. It runs every `test_hostile*.mjs` and every `test_screens*.mjs`, each with its own stub on its
   own free port. The hostile checks feed the page wrong or failing answers, or open it without
   the write token, and check that nothing throws and that the reader is told. The screens checks
   draw each tab or section in every state, at a desktop width and a phone width, and fail if
   anything throws or the page scrolls sideways.

The screens checks save their screenshots in your system's temporary directory, outside the
repository. Set `SHOT_DIR` to save them somewhere else.

To run one hostile or screens check on its own, call it with `node`. It starts its own stub:

```bash
node dashboard/test_hostile_models.mjs
PORT=7990 node dashboard/test_screens.mjs           # when the default port is taken
ONLY=token node dashboard/test_hostile.mjs          # only the cases whose name contains "token"
```

`ONLY` works in the hostile checks. `test_browser.sh` finds these files by name pattern, so a new
`test_hostile_<area>.mjs` or `test_screens_<area>.mjs` runs without any change to the script.

To look at the page yourself, start the stub and open it in a browser:

```bash
python3 dashboard/test_stub_server.py 7901
```

Then open `http://127.0.0.1:7901/?state=empty`. The states are `ready` (a busy farm), `empty` (a
farm that was just installed), `error` (`gh` and `hq` missing, no graphics card), `loading` (every
route answers slowly) and `quiet` (lane names too long for a card, and one name with two
mailboxes).

### What the browser tests need

- **Node.js 18 or newer.**
- **Playwright with its Chromium.** The quickest way to get both:

  ```bash
  npx playwright install chromium
  ```

  The checks look for Playwright in this order, and use the first copy whose Chromium is
  downloaded:

  1. `FLEET_PLAYWRIGHT`: a path to Playwright's `index.mjs`, or any module name Node can import;
  2. a `playwright` or `playwright-core` package that Node finds from `fleet/dashboard/`;
  3. a copy that npx has unpacked in its cache, `~/.npm/_npx/`, for example with the command
     above.

  If Playwright is installed globally, point at it:

  ```bash
  FLEET_PLAYWRIGHT="$(npm root -g)/playwright/index.mjs" bash dashboard/test_browser.sh
  ```

  When no copy has a Chromium, the checks stop with
  `playwright has no chromium. Run: npx playwright install chromium`.
- **Chromium's system libraries.** If Chromium does not start because a library such as
  `libnspr4.so` is missing, install them with `npx playwright install-deps chromium` (this needs
  root). On a machine where you have no root, you can unpack them under
  `~/.local/pwdeps/root/usr/lib/x86_64-linux-gnu`: `test_browser.sh` adds that directory to
  `LD_LIBRARY_PATH`.

## The head office (`hq`)

The head office is a private GitHub repository that agents use for names, branch claims and
messages. `hq` is its command-line tool. Its tests use pytest, so install it in a virtual
environment first:

```bash
cd hq
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q
```

The tests cover names and sessions, branch claims and the pre-push check, mail, presence, the
config file and `hq install`. They need no network.

## The plugin

Run these from the root of the repository:

```bash
python3 tests/test_plugin_installed_copy.py -v   # the plugin works from Claude Code's cache copy
python3 tests/test_murmur_farm.py -v             # /murmur:farm step by step, against fakes
```

`test_plugin_installed_copy.py` copies the plugin the way Claude Code installs it, with nothing
outside its own directory, and checks that it still works. `test_murmur_farm.py` plays
DigitalOcean, the Droplet, ssh and the tailnet with fake tools, so it makes no cloud call.

## What CI runs

GitHub Actions runs three workflows from [`.github/workflows/`](../../.github/workflows). Each one
runs on a push to `main` and on a pull request, but only when the paths it watches change (and
when its own workflow file changes):

- **fleet tests** (`fleet-tests.yml`), when `fleet/` or `farm/` changes. It checks the Bash
  syntax of `bin/fleet`, `install.sh` and `dashboard/run.sh`. Then it runs `policy-test.sh`,
  `sensors-test.py`, `supervisor-test.py`, `model-switch-test.py`, `silent-start-test.sh`,
  `test_server.py`, `test_github_access.py`, `test_token_fragment.mjs`, `models-test.py`,
  `scrub-test.py`, `hosting-test.py` and `one-click-farm-test.py`.
- **hq tests** (`hq-tests.yml`), when `hq/` changes. It runs `pytest -q` on Python 3.11 and 3.12,
  then checks that `hq --help` and `python bin/hq --help` run.
- **plugin tests** (`plugin-tests.yml`), when `plugin/`, `templates/` or `tests/` changes, or one
  of the fleet files the plugin uses: `fleet/lib/machines.py`, `fleet/lib/host_presets.py`,
  `fleet/lib/scrub.py` and `fleet/tests/fakes/core/`. It runs `test_plugin_installed_copy.py` and
  `test_murmur_farm.py` on Python 3.11.

CI does not run the browser tests, `test_ui.mjs`, or these fleet suites: `train-test.py`,
`blind-test.py`, `scope-test.py`, `group-test.py`, `salvage-test.sh`, `salvage-test.py`,
`events-test.py`, `stale-status-test.sh`, `accounts-test.py` and `codex-usage-test.py`. If you
change what they cover, run them yourself.

## Writing a new check

- **Make a new check fail first.** Break the code it guards, run the check and watch it fail.
  Then restore the code and watch it pass. A check that cannot fail looks exactly like a check
  that passes.
- **Test both directions.** Check that the bad case is caught and that the good case is left
  alone. A check that flags everything passes the first half.
- **Build a throwaway world.** Give the suite its own `FLEET_STATE` and `FLEET_CONFIG` in a
  temporary directory, and put fake tools first on `PATH`, as the suites above do. Never point a
  test at a real farm's state.
- **Test the code in your checkout.** Load the code relative to the test file, or take its path as
  an argument. Never read it from a fixed path such as `~/work/fleet`.
