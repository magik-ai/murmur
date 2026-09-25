# Operating a farm

This guide is for the person who runs a **farm**: an always-on Linux machine where coding agents
work headless (no chat window, nobody typing) while nobody watches. It covers setup, access,
daily running, recovery and troubleshooting. For the short path, start with
[`QUICKSTART.md`](QUICKSTART.md). Read [`sharp-edges.md`](sharp-edges.md) once, before you need
it: it describes the failure modes that can destroy work.

Words this guide uses:

- **lane**: one agent doing one task on its own branch, in its own git worktree. Each run of a
  lane has a **slug**, a unique id that `fleet spawn` prints.
- **orchestrator**: the agent (or the person) that splits the work into lanes and spawns them.
- **conductor**: the agent that takes approved pull requests through the merge queue.
- **head office**: a private GitHub repository that agents use for names, branch claims and
  messages, through the `hq` command. It is optional.
- **sweep**: the clean-up job that removes finished worktrees on a timer.
- **supervisor daemon**: the service that starts a lane again when it ends before it delivered.
  It only acts on lanes that have a restart policy. The dashboard calls it the agent runner.

The handbook's [glossary](../../docs/00-start-here.md#words-this-handbook-uses) has the rest.
Replace `<FARM_HOST>` (the farm's ssh host alias), `<PROJECT>`, `<ORG>/<REPO>`, `<LANE>` and
`<CODENAME>` with your own values.

murmur runs two engines, **Claude Code** and **Codex**. A farm is **your own Linux machine** or a
**DigitalOcean Droplet** that fleet creates for you. Adding another engine or another kind of
machine is a contribution: see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

```text
  your laptop (optional)                    the farm (an always-on Linux machine)
  ┌──────────────────────────┐              ┌─────────────────────────────────────┐
  │ an orchestrator session  │   ssh, git   │ the fleet command                   │
  │ a browser on the board   │◄────────────►│ one agent per lane, each in its own │
  │ the `fleet` ssh shim     │              │ git worktree                        │
  └──────────────────────────┘              │ dashboard, sweep timer, daemon      │
                                            └─────────────────────────────────────┘
```

A laptop runs out of memory and cooling after a few agents in parallel. The farm does the work,
and finished branches come back to you through GitHub.

Contents:

1. [What the farm needs](#1-what-the-farm-needs)
2. [Install](#2-install)
3. [Register a project](#3-register-a-project)
4. [Spawn and watch lanes](#4-spawn-and-watch-lanes)
5. [The dashboard](#5-the-dashboard)
6. [The supervisor daemon](#6-the-supervisor-daemon)
7. [Sweep, clean and salvage](#7-sweep-clean-and-salvage)
8. [Subscription accounts](#8-subscription-accounts)
9. [Power modes and capacity](#9-power-modes-and-capacity)
10. [Machines and hosting](#10-machines-and-hosting)
11. [Where state lives](#11-where-state-lives)
12. [Updating](#12-updating)
13. [Troubleshooting](#13-troubleshooting)
14. [Dashboard API reference](#14-dashboard-api-reference)

---

## 1. What the farm needs

| Need | Why | Check |
|---|---|---|
| Linux with **systemd** and a running **user manager** | lanes, the supervisor daemon, the sweep timer and the dashboard service are systemd user units | `systemctl --user is-system-running` answers `running` or `degraded` |
| **linger** on for your user | user units keep running when nobody is logged in | `loginctl show-user "$USER" -p Linger --value` prints `yes` |
| the **cpu** and **memory** controllers delegated to your user manager | the power modes cap the agents' CPU and memory without root | `cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers` lists `cpu` and `memory` |
| **Python 3.11** or newer | fleet reads its config files with `tomllib`. Ubuntu 22.04 ships 3.10: see [quickstart step 1](QUICKSTART.md#1-get-a-machine-with-systemd) | `python3 -V` |
| **git** | each lane works in its own git worktree | `git --version` |
| **gh** 2.40 or newer, logged in | lanes open pull requests, the sweep asks GitHub whether a branch merged, and the dashboard checks the login with `gh auth status --active` (install it as in [quickstart step 3](QUICKSTART.md#3-install-githubs-cli-and-log-in)) | `gh --version`, `gh auth status` |
| **claude** and/or **codex**, logged in on a subscription | the engines the lanes run | `claude --version`, `codex --version` |
| **tmux** | runs the dashboard until you install it as a user unit | `tmux -V` |

If `cpu` is missing from the controllers, everything works except the CPU cap of `fleet mode`. An
administrator can delegate it with a systemd drop-in. Reboot for it to take effect:

```bash
sudo mkdir -p /etc/systemd/system/user@.service.d
printf '[Service]\nDelegate=cpu cpuset io memory pids\n' |
  sudo tee /etc/systemd/system/user@.service.d/delegate.conf
sudo systemctl daemon-reload
```

### Logins

- Log in on a **subscription**, not an API key. fleet removes `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `CLAUDE_CODE_USE_BEDROCK`,
  `CLAUDE_CODE_USE_VERTEX` and `CLAUDE_CODE_USE_FOUNDRY` from every Claude Code and Codex lane, so
  a lane does not switch to paid API use by accident. Do not set up other API credentials on the
  farm either, such as an `apiKeyHelper` in Claude Code's settings or a Codex login made with an
  API key. The limit that matters is the subscription's own usage windows, and your interactive
  sessions share them.
- Logging in is interactive. Do it once over ssh with a terminal: `ssh -t <FARM_HOST> claude`,
  then type `/login`. For Codex, tunnel the login callback back to the farm:
  `ssh -L 1455:localhost:1455 -t <FARM_HOST> codex login`.
- fleet looks for each engine CLI in `~/.local/bin` first, where the official installers put it,
  then on `PATH`, and for Codex at `/usr/bin/codex` last. `FLEET_CLAUDE_BIN` and `FLEET_CODEX_BIN`
  name another path. Set them when the CLI is outside the services' `PATH`
  (`/usr/local/bin:/usr/bin:/bin:~/.local/bin`), as in
  [quickstart step 4](QUICKSTART.md#4-install-an-agent-cli-and-log-in-on-a-subscription). The
  dashboard checks the same file a lane runs. A lane whose engine is not there fails at once (see
  [troubleshooting](#lanes)).

### Where it runs

- Any Linux with systemd runs fleet. The one-command installer knows Ubuntu 22.04 or newer and
  Debian 12 or newer, because it installs packages with apt.
- On Windows, use WSL2 with Ubuntu, with systemd running inside it. By default, WSL stops the
  distribution soon after its last terminal closes, and systemd services do not keep it running.
  [The machine](../../docs/12-the-machine.md#what-the-machine-must-be) shows the two settings that
  keep the farm on.
- macOS cannot be a farm, because it has no systemd. Use a Mac to drive a Linux farm over ssh.
- Optional, and worth it for a remote farm: a private network between your laptop and the farm
  (a tailnet or a VPN), so the dashboard and ssh are not open to the internet.
- Lanes run with no permission prompts, because nobody is at their keyboard. Claude Code runs with
  `--dangerously-skip-permissions`, and Codex with `--dangerously-bypass-approvals-and-sandbox`,
  which switches off its approvals and its sandbox. A lane can run any command the farm's user can
  run, with that user's files and logins. Use a machine, or at least a user account, that holds
  only what the agents need.

---

## 2. Install

### The one-command installer

On Ubuntu or Debian, as an ordinary user (not root):

```bash
curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
```

It installs the system packages and `gh`, turns on linger, and installs `uv` and Claude Code. It
clones murmur to `~/work/murmur` and installs fleet and the head office CLI from that clone. It
asks a few questions: the head office repository, your code name, the farm's ssh alias, and
whether this is your only machine. When it is not, it offers Tailscale. It writes the answers into
the config and runs the dashboard as a user service. `~/work/murmur/farm/install.sh --help` lists
its flags, and [chapter 12 of the handbook](../../docs/12-the-machine.md) walks through it.

On a machine with less than 12 GB of memory, the installer also lowers `ram_min_gb` and
`warn_ram_gb` in `~/.config/fleet/policy.toml` to fit it (see [capacity](#capacity)). If
`fleet capacity` still blocks on free memory, lower them yourself.

### Installing fleet by hand

```bash
git clone https://github.com/magik-ai/murmur ~/work/murmur
cd ~/work/murmur/fleet
./install.sh
```

The installer prints what it did:

- it links `~/.local/bin/fleet` to the clone;
- it links the orchestrator skill into `~/.claude/skills/fleet`, and into `~/.codex/skills/fleet`
  when `~/.codex` exists;
- it copies `config/policy.example.toml` and `config/projects.example.toml` to
  `~/.config/fleet/policy.toml` and `projects.toml`, unless those files exist already;
- it writes `FLEET_HOME` into `~/.config/fleet/env`;
- it turns on the timer that runs `fleet sweep` every 10 minutes.

| Flag | Effect |
|---|---|
| `--prefix DIR` | link the `fleet` command into `DIR/bin` instead of `~/.local/bin` |
| `--no-autosweep` | leave the sweep timer off |
| `--no-skills` | do not link the orchestrator skill into `~/.claude/skills` or `~/.codex/skills` |
| `--local` | single machine: record `FLEET_DASH_BIND=127.0.0.1` in `~/.config/fleet/env`, and skip the laptop advice |

The supervisor daemon respawns lanes through the `bin/fleet` of its own clone, so `--prefix` needs
nothing else. `FLEET_BIN` in `~/.config/fleet/env` names another `fleet` command.

### The env file

`~/.config/fleet/env` holds your settings, one `KEY=VALUE` per line. The full list is in
[Environment](#environment).

- The `fleet` command reads the `FLEET_*` keys on every run. A variable already set in your shell
  wins over the file.
- `fleet dashboard` reads the dashboard's keys from it the same way.
- The systemd user units (the daemon, the dashboard and the sweep) load the whole file.
- Every install writes `FLEET_HOME` there, so the units use the clone you installed from.

After you change it, restart what reads it: `fleet dashboard restart` for the dashboard, and
`systemctl --user restart fleet-daemon` for the daemon.

### Driving the farm from a laptop

If the farm is a separate machine, do not install fleet on your laptop too. Put the small ssh
shim from the [fleet README](../README.md#optional-drive-the-farm-from-your-laptop) on the laptop
instead, so that `fleet ...` runs on the farm. It quotes every argument, because briefs contain
quotes and line breaks.

---

## 3. Register a project

```bash
fleet add-project --name <PROJECT> --repo <ORG>/<REPO>          # clones to ~/work/<PROJECT>
fleet add-project --name <PROJECT> --repo <ORG>/<REPO> \
                  --path /srv/checkouts/<PROJECT> --branch main --port-base 5200
fleet projects                                                   # the registered names
```

- `add-project` clones `https://github.com/<ORG>/<REPO>.git` when the path holds no checkout
  yet, then adds a table to `~/.config/fleet/projects.toml`.
- The name must be a plain name: letters, digits, `.`, `_` or `-`, starting with a letter or
  digit. `fleet spawn` refuses any other project name, so `add-project` refuses it too.
- Registering a name again with the same settings changes nothing. With different settings it is
  refused, so the file never holds two tables for one project.
- `--branch` (default `main`) is the base branch that lanes start from.
- fleet does not bring its own conventions: each lane reads the project's own `CLAUDE.md`.

**Ports.** Each lane gets three ports: one for a dev server (`vite`), one for an API (`uvicorn`)
and one for an end-to-end runner (`e2e`). The lane's instructions name them. Each port is a base
plus a slot: the lowest slot whose three ports no running lane holds, so two running lanes never
share a port, and a lane that ends frees its slot. `--port-base` (default 5200) sets the dev
server base, which `add-project` writes as `port_base`. The API and end-to-end bases default to
8100 and 6100. Set all three per project in a `[<PROJECT>.ports]` table with `vite_base`,
`api_base` and `e2e_base`; `vite_base` there wins over `port_base`. Give each project its own
bases. The dashboard's Machine tab can add a project too, and it picks the next free base, 100
above the highest one registered.

**Validation.** A `validation` key in the project's table names a command that
`fleet group assemble` runs on the integration branch before it pushes. If the command fails, no
pull request is opened. See [grouped lanes](../README.md#several-lanes-one-pull-request).

---

## 4. Spawn and watch lanes

```bash
fleet capacity                       # can the farm take another agent?
fleet spawn --project <PROJECT> --lane <LANE> --model sonnet --by <CODENAME> \
      --task "Implement X. Acceptance: ..."
```

### What a spawn does

1. It checks the names. The project, the lane, the code name and the effort may hold only
   letters, digits, `.`, `_` and `-`, and must start with a letter or digit.
2. It refuses to start if `policy.toml` does not parse.
3. It checks the engine and the model, and picks the Claude account.
4. With `--after`, it records the lane and stops there. The supervisor daemon starts it later
   (see [section 6](#6-the-supervisor-daemon)).
5. It starts the dashboard if it is not running.
6. It checks capacity and the power setting. `--force` skips both checks.
7. It fetches the base branch and creates the worktree `~/.fleet/worktrees/<PROJECT>/<slug>` on a
   new branch `fleet/<LANE>-<HHMMSS>`, from `origin/<base>`.
8. It sets the worktree's commit author and installs its pre-push hooks. With head office on, it
   also claims the branch.
9. It saves the brief, adds the lane instructions from `lib/brief_template.md`, and starts the
   engine as the systemd user unit `fleet-<slug>` in `fleet.slice`, with no permission prompts
   (see [where it runs](#where-it-runs)).

If a step fails once the worktree exists, the spawn removes everything it created.

**Briefs.** Give the task as `--task "..."` (inline), `--brief-file <path>` (a file on the farm)
or `--issue N` (the agent reads that GitHub issue). Use `--brief-file` for anything long or full
of punctuation (see [`sharp-edges.md`](sharp-edges.md)). A brief over 120,000 bytes is saved to
`~/.fleet/briefs/<slug>.prompt.md`, and the agent is told to read that file first.

**Commit author.** Each lane commits under its own name, so a reviewer can tell the agents apart.
`[identity]` in `policy.toml` sets the shape; `{agent}` stands for the `--by` code name, or the
lane name without one. The default is `{agent} (agent)` with the address `{agent}@agents.local`.

**Code names and marks.** `--by <CODENAME>` tags who spawned the lane, and the dashboard groups
lanes by it. Each code name has one mark, a glyph and a colour. The first spawn records it in
`~/.config/fleet/codenames.json`, from `--icon` and `--color`, or picked from the name without
them. After that the registry wins, whatever a spawn passes, so all of one orchestrator's lanes
look alike. `fleet identity` shows the marks, and this changes one:
`fleet identity <name> --icon <glyph> --color <hex>`.

### Engines, models and tiers

- `--engine claude` is the default. `--model` picks the tier: `opus`, `sonnet` (the default) or
  `haiku`. It also takes `fable`, `'opus[1m]'`, `'sonnet[1m]'` or a full `claude-*` id. Quote the
  `[1m]` names in a shell.
- `--engine codex` runs one model (`FLEET_CODEX_MODEL`, default `gpt-5.6-sol`), and `--effort`
  picks the tier: `low`, `medium` (the default), `high` or `xhigh`. `--model` picks another
  Codex model.
- `--effort` works on Claude lanes too, but the levels a Claude model supports depend on the
  model: not every model has every level.
- `--account NAME|auto` picks the Claude subscription (see
  [section 8](#8-subscription-accounts)). Codex refuses it.
- A model name must start with a letter or digit, contain only letters, digits and
  `. _ : / [ ] -`, and be at most 80 characters. A name fleet cannot use is refused at spawn, not
  minutes later inside the lane.
- Each provider has a list of models that are switched on (`models_on`). A model that is not on
  prints one `warning:` line, and the spawn goes ahead. A model that can cost money beyond the
  subscription is refused until you switch it on: Claude `fable` and `claude-fable-*`, and the
  `[1m]` ids of `claude-opus-4-6` and `claude-sonnet-4-6`.

### Switching models on and off

```bash
fleet models                             # every provider: on or off, health, role
fleet models discover codex              # the models a provider offers; --json for scripts
fleet models on claude claude-opus-5-5   # switch a model on
fleet models on claude fable --confirm-cost fable
fleet models off claude haiku
```

- Nothing here sends a prompt. `discover` asks Codex with `codex debug models`, and reads Claude
  Code's list from `lib/model_discovery.py`. When it fails, it falls back to the built-in list
  and gives one short reason, such as "the CLI is not installed" or "it did not answer in 15
  seconds".
- `off` refuses the provider's default model, the one a spawn gets without `--model`.
- A model with a cost note needs `--confirm-cost <model>` when you switch it on.
- `fleet models enable <id>` switches a provider on and tests it, `fleet models test <id>` tests
  it again, and `fleet models disable <id>` switches it off. For Claude Code and Codex, the test
  only checks that the CLI is installed and, for Codex, logged in (`~/.codex/auth.json` exists).
  It sends no request, so a pass does not prove that a Claude login works: `fleet accounts` shows
  that. Only an engine added as a contribution gets a real test prompt.
- `fleet models auth <id>` stores a key for an added engine that needs one, read from standard
  input, in `~/.fleet/secrets/<id>.key` (mode 600). Claude Code and Codex use their own logins
  instead.
- fleet reads the shipped `config/models.example.toml` until your first change creates
  `~/.config/fleet/models.toml`. On/off state and health go to `~/.fleet/models-state.json`.
- A table in your own `models.toml` for an engine murmur does not ship stays usable. `fleet models`
  and the dashboard mark it **not in the catalog**, and say how to remove it.

### Watching lanes

```bash
fleet status --project <PROJECT>     # a table of lanes, and the farm's load, memory and GPU
fleet status --json                  # every lane for scripts: status, outcome, pull request, scope
fleet tail <slug>                    # engine, tier, age, status, pull request, last message
fleet logs <slug>                    # the raw output stream, followed live
fleet events --follow --lane <LANE>  # also --project, --kind a,b, --since <unix time>, --json
fleet msg <slug> "..."               # add a note to the lane's inbox; no text reads the inbox
fleet kill <slug>                    # stop a lane
fleet kill --retire <slug>           # stop it, and stop the daemon from respawning it
```

- Prefer `fleet events` and `fleet status --json` to grepping log files. Events are appended to
  `~/.fleet/events.jsonl`. Their kinds include `spawned`, `status`, `delivered`, `respawned`,
  `dropped-scope`, `gate-fired` and `model-switched`.
- `fleet msg` appends to `~/.fleet/msg/<slug>.md`. The lane's instructions tell it to read that
  file at checkpoints: before a commit, when blocked, and between slices. A note reaches the lane
  there, not in the middle of a thought.
- The status of a lane is `starting`, `running`, `pr_open` (it opened a pull request and
  stopped), `done_no_pr`, `ended`, `failed`, `killed` or `gave_up`.

A lane is one pass. It ends when it opens a pull request, and it does not wait for review. To act
on a review, fix the branch yourself, or spawn a new lane with the findings in its brief; a new
lane always starts on a new branch. Lanes never merge. You decide what merges, and after your yes
the conductor (or the orchestrator, if you run no conductor) merges it.

---

## 5. The dashboard

### Start it and keep it running

```bash
fleet dashboard start      # start it; a spawn starts it too
fleet dashboard status     # running or not, and the address it really listens on
fleet dashboard token      # print the token
fleet dashboard restart    # pick up a new address, port, title or token
fleet dashboard stop
fleet dashboard enable     # install it as the user unit fleet-dashboard.service
```

Until you run `fleet dashboard enable`, the dashboard runs in a detached tmux session named
`fleet-dashboard`, and it does not come back after a reboot. `enable` installs
`fleet-dashboard.service` as a systemd user unit and starts it. From then on, `start`, `stop` and
`restart` drive the unit, and with linger on it starts at boot. `farm/install.sh` runs `enable`
for you.

Stop the dashboard with `fleet dashboard stop`, never with `pkill -f server.py`. Its process is a
plain `python3 server.py`, and `pkill -f` takes the board down while every lane keeps working.
The farm then looks dead from outside (see [`sharp-edges.md`](sharp-edges.md)).

### Reach it

| From | How |
|---|---|
| the farm itself | open `http://127.0.0.1:7878` |
| your laptop, over ssh | run `ssh -N -L 7878:127.0.0.1:7878 <FARM_HOST>`, then open `http://127.0.0.1:7878` on the laptop |
| your laptop, over Tailscale | set `FLEET_DASH_BIND=tailscale` in `~/.config/fleet/env`, run `fleet dashboard restart`, and open port 7878 on the farm's Tailscale address |
| another network | set `FLEET_DASH_BIND` to one of the farm's addresses (an IPv6 literal works too), then restart |

- `FLEET_DASH_BIND` defaults to `127.0.0.1`, so only the farm itself can connect.
- On a loopback address, the dashboard answers only requests addressed to `localhost` or to a
  loopback address such as `127.0.0.1` or `[::1]`, on any port. This stops a website that points
  a name of its own at `127.0.0.1` (DNS rebinding) from reading the board.
- `tailscale` means the farm's Tailscale IPv4 address, read when the dashboard starts. With no
  such address, the dashboard does not start at all, rather than listen more widely. As a user
  unit, it tries again every 5 seconds until the address is there.
- Do not bind `0.0.0.0` on a machine with a public address. The page would face the internet with
  only the token in front of it.
- `FLEET_DASH_PORT` changes the port (default 7878).

### The token

- Every change made through the page needs the bearer token, on every address, loopback included.
- Reading needs the token too once `FLEET_DASH_BIND` is not a loopback address, because a lane's
  brief and result are not public. The page itself and its files are always served, so you can
  load it and hand it the token.
- The dashboard creates the token on its first start, in `~/.config/fleet/dash-token` (mode 600),
  unless `FLEET_DASH_TOKEN` is set. `fleet dashboard token` prints it.
- Open the page once as `http://<address>:7878/#token=<token>`. The part after `#` never reaches
  the server or its log. `?token=<token>` works as well, but it does reach the server. The page
  keeps the token for that browser tab, and removes it from the address bar.
- A request whose `Origin` or `Sec-Fetch-Site` header says it came from another site is refused,
  whatever token it carries.
- To replace the token, delete `~/.config/fleet/dash-token` (or set a new `FLEET_DASH_TOKEN`) and
  run `fleet dashboard restart`. Then open the page again with the new token.
- If the dashboard cannot write the token file, it starts read-only and says so. Set
  `FLEET_DASH_TOKEN` in that case.

### The tabs

**Board** is the screen to keep open. From top to bottom:

- While a prerequisite is missing, a **Finish setting up** checklist, with the fix for each item.
  It has no close button: it goes away when the items are fixed.
- The machine strip: load, free memory, free disk, the graphics card and the CPU temperature.
- The accounts strip: one card per subscription with each usage window (session, weekly, and any
  model-specific one), when the next one resets, and a warning when the account is out of room.
- The lanes, with status, model, who spawned them, age, cost and tokens.
- Click a lane to open its drawer: stop this pass or retire the lane, its change and GitHub
  checks, its brief, its result, the last 200 lines of its log, and a box to message it.

On a farm where no lane has ever run, the Board shows the checklist and the commands for a first
spawn instead.

**Mail** shows the head office as conversations: the mailboxes, one conversation, and who is
online now. A reply is sent with `hq msg` under the name `FLEET_DASH_HQ_AGENT` (default
`dashboard`), never under a name taken from the browser. Mail is read through `gh` every 45
seconds, so it can be up to 45 seconds behind. Reading never marks mail as read for an agent: the
page never calls `hq inbox`, which would move the inbox cursor the agents rely on. Without `hq`,
or with no head office configured, the tab says so and shows the command that fixes it.

**Machine** holds the controls, in sections:

- **Power**: the power setting, and three actions for the whole farm: **Throttle**
  (`fleet mode balanced`), **Drain** (`fleet drain`) and **Resume** (`fleet resume`). Each one
  shows what it will do before you confirm. See [section 9](#9-power-modes-and-capacity).
- **Services**: the agent runner (the supervisor daemon, which restarts only the lanes that have
  a restart policy) and the sweep timer, with start, stop and restart. Stopping the agent runner
  stops no running lane. The dashboard's own row is read-only: restart it from a terminal.
- **Hosting**: your machines and the hosting providers (see
  [section 10](#10-machines-and-hosting)).
- **Accounts**: the subscriptions and their login state. Add and remove them, or refresh their
  usage (at most once a minute).
- **Models**: each provider and its models. Switch models on and off, discover them, and enable,
  disable, test, add or remove a provider.
- **Projects**: the registered repositories, with open lanes and last activity. Add one (after a
  check of your GitHub access) or remove one.
- **Health**: the prerequisites and the hardware tiles, shown only when `FLEET_DASH_HEALTH=on`.

**The header** is the same on every tab. It shows the page's name (`FLEET_DASH_TITLE`, default
`murmur`), a project filter, the time to the next sweep, the power setting, and a theme switch
(system, light, dark). A capacity pill appears when the farm has no room, and its tooltip gives
the reason. When something on screen is an old answer, because a request failed, the header says
`Stale since <time>`. Press Ctrl+K or Cmd+K to jump to any tab, lane, project or conversation.

### What stays at a terminal

The page can stop, retire and message lanes, send mail, change the power setting, start and stop
the daemon and the sweep timer, and add or remove accounts, models, projects and machines. These
stay at a terminal:

- spawning a lane: `fleet spawn`;
- `fleet clean` and `fleet sweep`, with or without `--force`;
- storing a provider key: `fleet models auth <id>` reads it from standard input. A page request
  that carries a key is refused;
- logging in to a subscription or a provider: the page only shows the command to run;
- stopping or restarting the dashboard itself.

---

## 6. The supervisor daemon

A lane is one pass: the engine reads its brief once and exits. If it exits before it delivered,
something has to notice and start it again. That is the supervisor daemon. The dashboard calls
it the **agent runner**. Stopping it stops no running lane: each lane is its own unit.

```bash
fleet daemon start        # install and start the user unit fleet-daemon.service
fleet daemon status       # active or not, and its last log lines
fleet daemon tick         # one pass now, in the foreground, when the daemon is not running
fleet daemon stop
```

The daemon acts only on lanes spawned with a `--restart` policy, and on lanes waiting for
`--after`. It never touches any other lane.

```bash
fleet spawn ... --restart until-merged --done-when pr-merged
fleet spawn ... --issues 1923,1809 --restart until-merged   # one lane, several issues
fleet spawn ... --after <LANE>:pr-merged                    # start when that lane delivers
```

- `--restart until-pr | until-merged | until-file:<path> | never` says when to stop respawning.
  `--done-when pr-open | pr-merged | file:<path> | issue-closed:#N` says what delivered means.
  With `--restart` alone, fleet picks the matching `--done-when`.
- A respawn is a new agent. It runs the saved brief again, under a new slug, in a new worktree on
  a new branch. It does not resume the old session, so it starts without that session's context.
- Respawns are limited: at most `FLEET_RESPAWN_MAX` per lane (default 10), and at least
  `FLEET_RESPAWN_COOLDOWN` seconds apart (default 600). After that the lane is marked `gave_up`.
- A lane with several `--issues` is not delivered while any issue is unaccounted for. The missing
  ones show in the daemon's log and in a `dropped-scope` event.
- `--after` creates nothing at spawn time: no worktree and no card. The lane waits in
  `~/.fleet/pending/<LANE>.json` until the daemon starts it.
- The daemon makes a pass every `FLEET_DAEMON_INTERVAL` seconds (default 60). `fleet daemon tick`
  does nothing while the daemon runs, because only one of them may run at a time.
- If one lane opens several near-identical pull requests, stop the daemon first, then count them
  (see [`sharp-edges.md`](sharp-edges.md)).

**Without the daemon, `--restart` and `--after` are only recorded.** Nothing warns you at spawn
time, so check `fleet daemon status` before you rely on them.

---

## 7. Sweep, clean and salvage

```bash
fleet sweep --dry-run                    # exactly what the next pass would remove
fleet sweep --project <PROJECT>          # one pass now, for one project
fleet autosweep status                   # when the timer runs next, and the last result
fleet autosweep on 15                    # run it every 15 minutes; `off` stops the timer
fleet clean --project <PROJECT> --dry-run
fleet clean --project <PROJECT>
fleet salvage <slug>                     # commit and push a lane's work before a clean
```

### The sweep

`install.sh` sets up a timer that runs `fleet sweep` every 10 minutes, always without `--force`.
In each pass, for each project, it:

1. removes the worktree, and deletes the local branch, of each fleet lane whose pull request
   GitHub reports as merged, or whose branch is already in the base branch;
2. archives the card of each finished lane whose pull request merged, that was killed, or that
   ended more than 15 minutes ago with no open pull request, and removes its worktree.

What happens to work in a worktree:

| State of the work | What the sweep does |
|---|---|
| the lane is still running | nothing |
| an open pull request | keeps the worktree and the card for as long as the pull request is open |
| uncommitted changes, including new files that git does not ignore | keeps the worktree until someone runs `fleet sweep --force` |
| commits that were never pushed | pushes them to `refs/fleet-salvage/<slug>` on `origin`, then removes the worktree; if the push fails, keeps it |
| a pushed branch | removes the local worktree; the branch stays on GitHub |
| GitHub does not answer | keeps everything, and prints `GitHub state is UNKNOWN` |

`fleet sweep --force` removes worktrees with uncommitted changes too. Before it does, it saves
`<slug>.dirt.txt` (the status and the first 200 KB of the diff) and `<slug>.untracked.tar` (the
new files) in `~/.fleet/state-archive/<YYYY-MM>/`. A later pass deletes a salvage ref once its
work is in the base branch. The full rules are in [`SWEEP.md`](SWEEP.md).

### Recovering work

- Archived cards and autopsies are in `~/.fleet/state-archive/<YYYY-MM>/`.
- Commits the sweep rescued are on `origin` under `refs/fleet-salvage/`. Fetch them with:

  ```bash
  git fetch origin '+refs/fleet-salvage/*:refs/fleet-salvage/*'
  ```

- A branch that was pushed is still on GitHub.
- Uncommitted work that was forced away survives only as the `.dirt.txt` diff and the
  `.untracked.tar` archive.

### `fleet clean`

`fleet clean` removes the worktree and the card of finished lanes: status `done`, `done_no_pr`,
`pr_open`, `failed`, `ended` or `killed`, or the supervisor daemon's `delivered`, `gave_up`,
`respawned` or `respawn_failed`. It also removes a record that still says running when
its unit has been gone for 15 minutes. An open pull request does not stop `clean`, because the
branch is on GitHub. What stops it is work that exists nowhere else:

- It keeps any worktree with uncommitted changes or unpushed commits, prints `KEEP <slug>` with
  the reason, and names `fleet salvage <slug>`.
- `--force` is refused without `--by <CODENAME>`, so a forced clean cannot reach another
  orchestrator's lanes.
- A forced clean of a worktree with unsaved work also needs `--yes`. It then saves the same
  autopsy as the sweep before it removes anything.
- Every `fleet kill` and `fleet clean` is logged to `audit.log` in the fleet directory.

### `fleet salvage`

`fleet salvage <slug>` commits any uncommitted changes as `salvage: WIP from lane <slug>` and
pushes the lane's branch to `origin`. It never removes anything. It finds the worktree on disk
even when the lane's card is unreadable.

---

## 8. Subscription accounts

A farm can hold several Claude subscriptions and spread lanes across them. An account is a Claude
Code config folder. The default one is `~/.claude`, and extra ones live in
`~/.fleet/claude-accounts/<name>`. Codex has one account, in `~/.codex`.

```bash
fleet accounts                 # session and weekly use per account; marks the best pick
fleet accounts add <name>      # create the folder and print the login command
ssh -t <FARM_HOST> env CLAUDE_CONFIG_DIR=~/.fleet/claude-accounts/<name> claude   # then /login
fleet accounts pick            # the account with the most room (exit 1 when none has room)
fleet accounts balance         # the next engine and account, taking turns over Claude and Codex
fleet accounts keepalive       # refresh any login token that is close to expiry
```

- An account name starts with a letter or digit, then letters, digits, `.`, `_` or `-`, at most
  40 characters. `auto` and `default` are taken.
- When you log in a new account, check that the browser is signed in to the right Claude account.
  Use a private window if another one is signed in. Otherwise the new folder quietly uses the same
  subscription.
- `fleet spawn` uses `--account auto` for Claude lanes unless you name one. `auto` takes turns
  across the accounts below 95% of both their session and weekly windows, and prefers those below
  80% of their session window. It takes turns rather than always choosing the emptiest account,
  so that parallel lanes spread across the accounts' session windows.
- If every account is at 95% or more, an `auto` spawn is refused. If no account's usage can be
  read at all, `auto` uses the default account.
- `fleet accounts balance` prints `claude <name>` or `codex codex`.
- A login token that is never used expires. The usage check then gets HTTP 429, which looks like
  rate limiting. `fleet accounts` tells the two apart. `fleet accounts keepalive` sends one tiny
  request for each token close to expiry. murmur ships no timer for it: run it from cron or a
  timer of your own, and log in again to any account it names.
- The dashboard reads every account's usage every 10 minutes. Its Refresh button reads them once
  more, at most once a minute.
- The subscriptions are shared with your own interactive use. When every account is out of room,
  stop spawning and wait for the reset.

---

## 9. Power modes and capacity

### Power modes

The agents run inside `fleet.slice`, a systemd user slice. fleet can cap the slice's CPU and
memory while the agents run, without root and without stopping them.

```bash
fleet mode                # the setting, what it resolves to, and the cap in force
fleet mode auto           # the default
fleet mode full|soft|balanced|hard
```

| `fleet mode` | Dashboard | CPU cap (share of the machine) | Memory share before the kernel reclaims | New spawns |
|---|---|---|---|---|
| `full` | Full | none | none | yes |
| `soft` | Shared | 50% | 60% | yes |
| `balanced` | Background | 35% | 40% | paused |
| `hard` | Paused | 20% | 25% | paused |

- `auto` switches to `soft` while the GPU is busy (25% use or more). It goes back to `full` once
  the GPU has stayed at 10% or less for 60 seconds. It never picks a harder mode by itself.
- `auto` needs a GPU sensor: `nvidia-smi` on `PATH`, or `FLEET_NVIDIA_SMI`. Without one, `auto`
  stays on `full` and says so once.
- A mode you pick by hand stays until you run `fleet mode auto`.
- Above its memory share, the kernel reclaims memory from the agents. They slow down, but they are
  not killed.
- `[mode]` and `[mode.<name>]` in `policy.toml` change the thresholds and the profiles
  (`cpu_quota_pct`, `cpu_weight`, `allow_spawn`, `mem_high_pct`). A `cpu_quota_pct` or
  `mem_high_pct` of 0 means no cap.

### Draining the farm

```bash
fleet drain               # salvage every running lane, stop the daemon, stop the lanes
fleet resume              # start the daemon again
fleet drain status        # the daemon's state, the running lanes and free memory
```

`fleet drain` frees the machine's memory, for example while you use the machine for something
else. It runs `fleet salvage` on each running lane, stops the supervisor daemon so that nothing
respawns, and then stops the lanes. `fleet resume` starts the daemon, which respawns the lanes
that have a restart policy, from their saved briefs. A lane without a restart policy stays
stopped, and any work that salvage could not push is lost.

`fleet game-mode on`, `off` and `status` are older names for the same three commands, and still
work. The dashboard's **Drain** and **Resume** run `fleet game-mode on` and `fleet game-mode off`.

### Capacity

`fleet capacity` answers `OK` or `BLOCK`, a level (`ok`, `warn` or `block`) and the reasons. Only
hardware blocks a spawn:

| Setting in `[limits]` | Default | Effect |
|---|---|---|
| `ram_min_gb` | 6 | block when free memory is below this, in GB |
| `disk_min_gb` | 20 | block when free disk, where `~/.fleet` lives, is below this, in GB |
| `gpu_temp_max` | 87 | block when the GPU is hotter than this, in degrees Celsius |
| `cpu_temp_max` | 92 | block when the CPU is hotter than this, in degrees Celsius |
| `warn_ram_gb`, `warn_disk_gb` | 8, 40 | warn below these |
| `warn_gpu_temp`, `warn_cpu_temp` | 82, 85 | warn above these |
| `warn_agents` | 24 | warn at this many running agents |

- The number of running agents never blocks a spawn. It only raises a warning.
- On a machine with less than 12 GB of memory, `farm/install.sh` sets `ram_min_gb` to about a
  quarter of the memory (at least 1) and `warn_ram_gb` to 1 more. It does this only while
  `[limits]` is still the example's, so a limit you changed stays as you set it.
- The defaults are `DEFAULT_POLICY` in `lib/metrics.py`. `[limits]` in
  `~/.config/fleet/policy.toml` overrides them (the example file sets `warn_agents = 15`).
  `fleet metrics` prints every number in force, and where it came from.
- The CPU temperature comes from the processor's Linux sensor: the `coretemp`, `k10temp`,
  `zenpower` or `cpu_thermal` driver, or the thermal zone of the processor's package. Under WSL,
  which has none, `FLEET_LHM_URL` can name a LibreHardwareMonitor web server on the Windows host;
  when it is set, it is asked first. Without a sensor the temperature is not measured, which never
  warns and never blocks. Cloud machines usually have none.
- `fleet spawn --force` skips the capacity check.

---

## 10. Machines and hosting

fleet keeps a list of the machines you run farms on, and it can buy a DigitalOcean Droplet for a
new farm.

```bash
fleet hosts list                  # the providers: your own machine over ssh, and DigitalOcean
fleet hosts check do-droplet      # is the provider's CLI installed and logged in?
fleet machines list               # your machines, their state and their monthly cost
fleet machines add --name <NAME> --target <USER>@<ADDRESS> [--port <PORT>]
fleet machines check <NAME>
```

`add` copies nothing to your machine. The farm logs in with its own key,
`~/.fleet/machines/id_ed25519`, so first add the public half,
`~/.fleet/machines/id_ed25519.pub`, to `~/.ssh/authorized_keys` on that machine. The dashboard's
Add a machine dialog shows the line to run there.

For a new Droplet:

```bash
doctl auth init --context murmur          # once, in your own terminal
fleet machines plan --provider do-droplet --name <NAME> --pubkey-file ~/.ssh/id_ed25519.pub
fleet machines create --provider do-droplet --name <NAME> \
      --pubkey-file ~/.ssh/id_ed25519.pub --confirm-usd <MONTHLY_PRICE>
fleet machines list                       # run again until it prints the finish command
fleet machines destroy <NAME> --confirm <NAME>
```

- `--size` and `--region` default to `s-4vcpu-8gb` and `fra1`. `/murmur:farm` instead suggests
  the region nearest your laptop's time zone.
- `plan` shows the commands, the cloud-init file and today's price from DigitalOcean. It buys
  nothing.
- `create` buys the Droplet only when `--confirm-usd` matches the live monthly price. If the price
  moved, it refuses and asks you to run `plan` again.
- `list` moves a new machine through `creating`, `preparing` and `needs-login` to `ready`. At
  `needs-login`, it prints the command that finishes the install from your laptop (it runs
  `farm/install.sh --remote` on the Droplet), and the ssh tunnel to its dashboard.
- `destroy` deletes the Droplet and its disk. It is the only thing that stops the billing, so it
  needs the machine's name twice.
- `adopt <NAME>` writes back the record of a Droplet this farm created and then lost.
  `forget <NAME>` drops a record and leaves the machine alone.
- `forget-attempt <NAME>` is for a create whose answer from DigitalOcean was lost. Once the wait
  for its Droplet is over, it drops the attempt, or adopts the Droplet if one did appear. A new
  create then needs the price confirmed again.
- fleet uses the `doctl` login context `murmur`. `FLEET_DOCTL_CONTEXT` names another one.
- The `/murmur:farm` command of the murmur Claude Code plugin runs the same steps from your laptop.

---

## 11. Where state lives

| What | Where |
|---|---|
| the tool | the clone you installed from. `<prefix>/bin/fleet` links to it, and `FLEET_HOME` names it |
| lane records, one card per lane | `~/.fleet/state/<slug>.json` |
| lane output | `~/.fleet/logs/<slug>.jsonl` (the raw stream) and `<slug>.err` (errors) |
| worktrees | `~/.fleet/worktrees/<PROJECT>/<slug>` |
| briefs | `~/.fleet/briefs/`, kept so that a respawn runs the same brief |
| lane inboxes | `~/.fleet/msg/<slug>.md`, written by `fleet msg` |
| deferred lanes | `~/.fleet/pending/<LANE>.json`, waiting for an `--after` condition |
| pre-push hooks | `~/.fleet/hooks/<slug>/` |
| groups | `~/.fleet/groups/` |
| the event stream | `~/.fleet/events.jsonl` |
| archived cards and autopsies | `~/.fleet/state-archive/<YYYY-MM>/` |
| dashboard jobs | `~/.fleet/jobs/<id>.json` |
| extra Claude accounts | `~/.fleet/claude-accounts/<name>/` |
| model on/off state and health | `~/.fleet/models-state.json` |
| settings | `~/.config/fleet/`: `policy.toml`, `projects.toml`, `env`, `dash-token`, `codenames.json`, `machines.toml`, and `models.toml` after your first model change |
| user units | `~/.config/systemd/user/`: `fleet-daemon.service`, `fleet-dashboard.service`, `fleet-sweep.service`, `fleet-sweep.timer` |
| running lanes | transient user units named `fleet-<slug>`, in `fleet.slice` |
| project checkouts | wherever `add-project` put them; `~/work/<PROJECT>` by default |
| the kill and clean log | `audit.log` in the clone's `fleet/` directory, which git ignores |

Apart from `audit.log`, nothing fleet writes at runtime lives inside the clone, so `git pull` is
always safe.

### Environment

Every setting below is optional and has a working default. Put it in `~/.config/fleet/env`.

| Variable | Default | What it decides |
|---|---|---|
| `FLEET_HOME` | the clone `install.sh` ran from | which clone the units and helpers use |
| `FLEET_STATE` | `~/.fleet` | runtime state, logs, worktrees, briefs and inboxes |
| `FLEET_CONFIG` | `~/.config/fleet` | where the settings files live |
| `FLEET_DASH_BIND` | `127.0.0.1` | the dashboard's address. `tailscale` means the farm's Tailscale IPv4 address; an IPv6 literal works too |
| `FLEET_DASH_PORT` | `7878` | the dashboard's port |
| `FLEET_DASH_TOKEN` | a token created in `~/.config/fleet/dash-token` | the bearer token for every write, and for every read once the address is not loopback |
| `FLEET_DASH_TITLE` | `murmur` | the page's name, in the browser tab and in the header |
| `FLEET_DASH_HQ_AGENT` | `dashboard` | the name the page signs head office mail with. It is never a name taken from a request, so a message from the page is always from the page |
| `FLEET_DASH_HEALTH` | off | `on` adds the Health section to the Machine tab: hardware tiles and the prerequisites table |
| `FLEET_FARM_ALIAS` | the machine's hostname | the ssh host name in account login commands. Set it to the name you actually reach the farm by |
| `FLEET_NVIDIA_SMI` | `nvidia-smi` on `PATH` | the GPU sensor that `fleet mode auto` and the capacity check read |
| `FLEET_LHM_URL` | unset | a LibreHardwareMonitor web server for the CPU temperature, asked before the Linux sensors. For WSL, which has none |
| `FLEET_CLAUDE_BIN` | `~/.local/bin/claude`, else `claude` on `PATH` | the Claude Code CLI that lanes run. Set it when Claude Code is outside the services' `PATH` |
| `FLEET_CODEX_BIN` | `~/.local/bin/codex`, else `codex` on `PATH`, else `/usr/bin/codex` | the Codex CLI that lanes run. Set it when Codex is outside the services' `PATH`. A newer CLI unlocks newer models |
| `FLEET_CODEX_MODEL` | `gpt-5.6-sol` | the model a Codex lane runs when `fleet spawn` gets no `--model` |
| `FLEET_DAEMON_INTERVAL` | `60` | seconds between two passes of the supervisor daemon |
| `FLEET_RESPAWN_MAX` | `10` | the most respawns per lane before it is marked `gave_up` |
| `FLEET_RESPAWN_COOLDOWN` | `600` | the fewest seconds between two respawns of one lane |
| `FLEET_BIN` | `bin/fleet` in the daemon's own clone | the `fleet` command the supervisor daemon respawns lanes with |
| `FLEET_DOCTL_CONTEXT` | `murmur` | the `doctl` login context used for DigitalOcean |

`CLAUDE_BIN` and `CODEX_BIN` in your shell's environment win over both settings. In this file,
use the `FLEET_` names: the `fleet` command reads only the `FLEET_` keys from it.

---

## 12. Updating

```bash
cd ~/work/murmur
fleet status                              # see what is running first
git pull
cd fleet && ./install.sh                  # with the same flags as the first time
systemctl --user restart fleet-daemon     # if you run the daemon, so it loads the new code
fleet dashboard restart                   # so the dashboard loads the new code
```

- Restarting the daemon or the dashboard stops no lane: each lane is its own unit.
- `install.sh` is safe to run again. It relinks, keeps your `policy.toml` and `projects.toml`, and
  updates keys in `~/.config/fleet/env` in place rather than adding a second copy.
- The sweep runs the new code on its next pass.
- A clone made by `farm/install.sh` updates the same way. `git -C ~/work/murmur pull` updates
  fleet and the head office CLI together, because both run from that clone.

Before you trust a change to fleet itself, run the checks in [`VERIFYING.md`](VERIFYING.md).

---

## 13. Troubleshooting

Each entry starts with what you see, then says what to do.

### Setup and access

**`fleet: command not found` over ssh.** A non-interactive ssh session usually has no
`~/.local/bin` on its `PATH`. Call `~/.local/bin/fleet` by its full path, as the shim does. fleet
then adds `~/.local/bin` to its own `PATH`, so it still finds `hq` and the engine CLIs there.

**The sweep, the daemon or the lanes stop when you log out.** Linger is off. Run
`loginctl enable-linger "$USER"` (with `sudo` if it asks), then check it with
`loginctl show-user "$USER" -p Linger --value`. On WSL2, WSL also stops the distribution soon
after its last terminal closes: set the two idle settings in
[the machine](../../docs/12-the-machine.md#what-the-machine-must-be).

**`install.sh` says autosweep "could not enable".** No systemd user manager answered. Check
`systemctl --user is-system-running`. On WSL2, make sure systemd is running inside the
distribution. Until then, run `fleet sweep` yourself.

### Spawning

**`REFUSING to spawn: invalid policy file ...`.** `~/.config/fleet/policy.toml` does not parse. Fix
the TOML error it names. fleet refuses rather than guess at your limits.

**`CAPACITY BLOCK: ...`.** A hardware limit: free memory, free disk or a temperature (see
[capacity](#capacity)). Wait, stop a lane, or change `[limits]`. `--force` spawns anyway.

**`MODE BLOCK: power mode '...' pauses new spawns`.** The power setting is `balanced` or `hard`.
`fleet mode auto` releases it. `--force` spawns anyway.

**`no account has headroom`.** Every Claude account is at 95% or more of its session or weekly
window. Wait for the reset, or spawn with `--engine codex`.

**`unknown claude model '...'`.** Use `sonnet`, `opus`, `haiku`, `fable`, `opus[1m]`,
`sonnet[1m]` or a full `claude-*` id.

**`... is not on for claude, and it can cost money the subscription does not cover`.** Switch the
model on first: `fleet models on claude <model> --confirm-cost <model>`.

**`engine '...' is not in murmur's catalog`.** murmur ships the `claude` and `codex` engines.
`fleet models` lists the engines this farm has.

**`project '...' not registered or missing (fleet add-project)`.** Register it, or check that its
`path` in `projects.toml` holds a git checkout.

**`project '...' is already registered with different settings`.** Edit that project's table in
`projects.toml`, or register the new one under another name.

**`hq: the hq CLI is on PATH and ... has no [hq] table`.** Head office stays on for this lane. Add
an `[hq]` table with `enabled = true` or `enabled = false` to `policy.toml` (see the
[quickstart](QUICKSTART.md#head-office-is-optional)).

### Lanes

**A lane is `failed` seconds after it started, with "exited before its first turn - the lane never
started".** Read `~/.fleet/logs/<slug>.err`. Usually fleet did not find the engine CLI, or the
CLI is not logged in. See [logins](#logins).

**`fleet status` shows `running?` and "dead?".** The card says running, but the lane's unit has
been gone for over 15 minutes, usually after a reboot. The lane is gone; its worktree is not.
Push its work with `fleet salvage <slug>`. `fleet clean` and the sweep treat such a card as
finished.

**Lanes stall for half an hour.** Usually they are fighting over something shared, not failing at
their code: one shared test database, or two lanes on one port. Give each lane its own database,
and each project its own port bases.

**A lane never delivered, and nothing respawned it.** Run `fleet daemon status`: `--restart` does
nothing without the daemon. A lane marked `gave_up` used up `FLEET_RESPAWN_MAX`.

**One lane opened several near-identical pull requests.** Run `fleet daemon stop` first, then
close the duplicates.

**A note sent with `fleet msg` had no effect.** A lane reads its inbox only at checkpoints. Check
that the note arrived with `fleet msg <slug>`, which prints the inbox.

### Sweep and clean

**The sweep prints `ABORT ... unreadable state record(s)`.** This is normal while a lane is writing
its card. The sweep then removes nothing in that project, because it cannot tell whether the lane
is live. A card that stays unreadable for 15 minutes is moved to
`~/.fleet/state-archive/<YYYY-MM>/<name>.json.corrupt`, and the next pass runs normally. If the
abort goes on longer, check that `~/.fleet/state` is writable.

**`fleet clean` prints `KEEP <slug>`.** The worktree holds uncommitted changes or unpushed
commits. Run `fleet salvage <slug>`, then clean again.

**The sweep keeps a merged lane's worktree.** It has uncommitted changes (the sweep prints `KEEP`
and the number of changes), or GitHub did not answer (`GitHub state is UNKNOWN`). Salvage or
inspect the worktree. `fleet sweep --force` removes it after saving an autopsy.

**Work is missing after a sweep.** See [recovering work](#recovering-work).

### Dashboard

**The page does not load.** Run `fleet dashboard status`. If it is stopped, run
`fleet dashboard start`. If the status says something else is listening on the port, another
process holds it.

**`dashboard did NOT come up on <address>:<port>`.** `FLEET_DASH_BIND` is not an address this
machine has, or the port is taken.

**With `FLEET_DASH_BIND=tailscale`, nothing listens.** Tailscale has no IPv4 address on the farm
yet. Run `sudo tailscale up`, and check with `tailscale ip -4`. As a user unit, the dashboard
tries again every 5 seconds; `journalctl --user -u fleet-dashboard.service` says why it stopped.

**Buttons are greyed out, or a change fails with `a bearer token is required`.** Open the page
again with `/#token=` and the output of `fleet dashboard token`. A new browser tab needs the token
again.

**`this dashboard is bound to ..., so reading needs the bearer token too`.** The address is not
loopback, so every read needs the token. Open the page with the token.

**`cross-site request refused` or `cross-origin request refused`.** The request came from another
site, or its `Origin` does not match its `Host`. Use the page itself. A proxy that rewrites the
`Host` header causes this too.

**The dashboard log says `READ-ONLY: no write token could be stored`.** `~/.config/fleet` is not
writable. Make it writable, or set `FLEET_DASH_TOKEN` yourself, then run `fleet dashboard restart`.

**The board is down, but the lanes are working.** Someone probably stopped the dashboard with
`pkill -f`. Run `fleet dashboard start`.

**The Mail tab says `hq` is missing, or points at no head office.** Install the head office CLI
(see [`hq/`](../../hq)), or point it at an office with `hq init --repo <ORG>/<OFFICE>`.

**The header says `Stale since <time>`.** A request from the page is failing, or a background read
failed, so a panel shows its last good answer. Hover over the label to see which one.

### Accounts

**`fleet accounts` shows an account as `UNAVAILABLE` with a 429.** If the token expired, it says
so: run `fleet accounts keepalive`, and log in again if that does not refresh it. Otherwise the
account is being rate-limited. fleet tries again on the next refresh, and logging in again would
not help.

**An account has no credentials.** `fleet accounts` prints the login command:
`ssh -t <FARM_HOST> env CLAUDE_CONFIG_DIR=<folder> claude`, then `/login`. If the host name in it
is wrong, set `FLEET_FARM_ALIAS`.

**Every account is out of room.** The usage windows are spent. Wait for the reset rather than
look for a way around it.

### Power

**`fleet mode auto` never throttles.** There is no GPU sensor, and fleet says `auto` is inert. Set
`FLEET_NVIDIA_SMI`, or pick a mode by hand.

**A mode is set, but the agents' CPU is not capped.** Check that the `cpu` controller is
delegated (see [section 1](#1-what-the-farm-needs)).

For the failure modes that destroy work, rather than annoy you, read
[`sharp-edges.md`](sharp-edges.md).

---

## 14. Dashboard API reference

The page uses these routes itself. They are listed here for scripts and for anyone who changes
the dashboard.

### Access

- These are open without a token, on any address: `/`, `/index.html`, `/static/<file>`,
  `/api/access`, `/api/version` and `/api/config`.
- Every other `GET` needs the token once the address is not loopback. Every `POST` always needs
  it, and is refused when `Origin` or `Sec-Fetch-Site` says another site sent it.
- On a loopback address, every route answers 403 when the `Host` header is not `localhost` or a
  loopback address.
- Send the token as `Authorization: Bearer <token>`, or as `?token=<token>`.
- A request body is a JSON object of at most 256 KB. An error answers `{"error": "<a sentence>"}`.
- Every time in an answer is an ISO 8601 stamp in UTC.

### Reads

**Read, from the snapshot.** No `GET` runs a tool, reaches the network or writes to disk.
Background threads read the machine instead: every 5 seconds for the live numbers, the power
mode and the sweep countdown; every 45 seconds for the health checks, the services, the mail and
who is online; every 45 seconds for the machines and hosting providers; every 5 minutes for
GitHub; every 10 minutes for the subscriptions. Until the first pass, an answer says `pending`.
When a pass fails, the answer keeps the last good values, and `stale_since` says when they were
true.

| Route | Answers |
|---|---|
| `/api/config` | the page's name, its build, and which optional parts this farm has |
| `/api/access` | whether this request may write, and why not |
| `/api/version` | the page's build |
| `/api/identities` | each code name's mark |
| `/api/health` | one row per prerequisite: `ok`, `missing`, `off` or `error`, each with a fix |
| `/api/services` | the agent runner, the sweep timer and the dashboard: state, since when, and what each does |
| `/api/metrics` | load, memory, disk, GPU, temperatures and the capacity verdict |
| `/api/mode` | the power setting, what it resolves to, and its caps |
| `/api/sweep` | whether the sweep timer is on, the seconds to its next pass, and the last result |
| `/api/fleet` | every lane |
| `/api/agent?slug=<slug>` | one lane's whole record |
| `/api/agent/log?slug=<slug>&tail=200` | the end of the lane's log as text; `tail` is 1 to 2000 lines |
| `/api/accounts` | each subscription's usage windows, with the last good numbers when a read failed |
| `/api/accounts/login-state` | per account: `logged_in`, `waiting_for_login`, `expired`, `rate_limited` or `unknown`, with a sentence |
| `/api/engines` | the model catalog with this machine's facts: one status per provider (`on`, `off`, `needs_key`, `not_installed` or `failing`), the models switched on, the default model, and whether the command is installed |
| `/api/models` | the model catalog without the machine's facts |
| `/api/models/presets` | the providers that "Add a model" offers (Claude Code and Codex) |
| `/api/projects` | the registered projects, with open lanes, last activity and GitHub access |
| `/api/projects/next-port` | the port base the next project would get |
| `/api/github` | the farm's GitHub connection from the last check: `login_state` (`connected`, `not_connected`, `no_gh` or `no_answer`), the login, its scopes and the API calls left |
| `/api/machines` | this farm's machines and their monthly cost, from `fleet machines list --json`. Each has one `state`: `creating`, `preparing`, `needs-login`, `ready`, `unreachable`, `failed`, `destroyed` or `unrecorded` |
| `/api/hosts` | the hosting providers, from `fleet hosts list --json`, each with a `login_state`: `logged_in`, `logged_out`, `not_installed` or `no_answer` (a slow provider is `no_answer`, never `logged_out`) |
| `/api/mail/boxes` | the head office mailboxes, with a count for the last day |
| `/api/mail/thread?box=<name>&since=<stamp>` | one mailbox's messages, newest last |
| `/api/mail/feed?hours=24` | the whole office as one timeline, newest first; `hours` is rounded up to 1, 3, 6, 12, 24, 48, 168 or 720 |
| `/api/mail/who` | who is online, from `hq who` |
| `/api/power/preview?action=<action>` | what throttle, drain or resume would do, with the lanes a drain would stop |
| `/api/jobs`, `/api/jobs/<id>` | the long actions in flight, and one action's record |

**Secrets are scrubbed from lane text.** A lane's brief, result and last activity on `/api/fleet`
and `/api/agent`, and every line of `/api/agent/log`, are scrubbed before they are served, like the
output of a job. Every key stored under `~/.fleet/secrets`, and anything shaped like an Anthropic,
GitHub or DigitalOcean token, becomes `[redacted]`.

The mail routes read through `gh`, never through `hq inbox`. A plain inbox read moves a cursor
that every process signing as one name shares, so a page that polled it would eat an agent's
mail.

### Writes

Every write is a `POST`. It has its own timeout and runs its command without a shell. A failure
answers with one sentence a person can act on, never a traceback.

| Route | Body | Does |
|---|---|---|
| `/api/agents/kill` | `{slug, retire}` | `fleet kill [--retire] <slug>` |
| `/api/agent/msg` | `{slug, text}` | `fleet msg`: read at the lane's next checkpoint |
| `/api/mail/send` | `{to, text}` | `hq msg`, signed as `FLEET_DASH_HQ_AGENT` |
| `/api/mode` | `{mode}` | sets the power setting, at once |
| `/api/power` | `{action}` | `throttle`: `fleet mode balanced`, at once. `drain`: `fleet game-mode on`, as a job. `resume`: `fleet game-mode off`, as a job |
| `/api/services` | `{service, action}` | `start`, `stop` or `restart` for `agent_runner` (`fleet daemon`) or `sweep_timer` (`fleet autosweep`). A restart is a stop, then a start. The `dashboard` row refuses |
| `/api/projects` | `{name, repo, branch?, port_base?}` | `fleet add-project`, as a job. Without a port base, it takes the next free one |
| `/api/projects/remove` | `{name}` | removes the project from `projects.toml` and keeps a copy of the old file. Refused while the project has lanes open |
| `/api/accounts/add` | `{name, engine}` | creates the account folder, and answers the login command and its steps |
| `/api/accounts/remove` | `{name}` | moves the account folder to `~/.fleet/dead-account-backups/` |
| `/api/accounts/refresh` | | reads every account's usage now; refused within 60 seconds of the last refresh |
| `/api/models` | `{action, id}` | `enable`, `disable` or `test` one provider. Enable and test run the check described in [switching models on and off](#switching-models-on-and-off) |
| `/api/models/add` | `{preset, id, variant?, label?, bin?, run?, auth_env?}` | writes one provider into `~/.config/fleet/models.toml`. It runs nothing |
| `/api/models/remove` | `{id}` | removes a provider this farm added. A shipped one can only be switched off |
| `/api/models/discover` | `{id}` | `fleet models discover <id> --json`, one at a time per provider. Answers `{source, models, error}`, where `source` is `account` or `docs` |
| `/api/models/select` | `{id, on, off, confirm_cost}` | `fleet models on` and `off`. A model with a cost note must be named in `confirm_cost` |
| `/api/github/check` | | one GitHub check now, in the background. One at a time, and at most once a minute |
| `/api/github/repos` | `{owner?, q?}` | the repositories from the last check, filtered. It runs nothing |
| `/api/github/branches` | `{repo}` | the repository's default branch and its protected branches |
| `/api/github/access` | `{repo, branch, name}` | the checks before a project is added: login, role, reachability, base branch, existing checkout |
| `/api/machines/plan` | `{provider, name, size, region, ssh_public?}` | `fleet machines plan ... --json`. It buys nothing |
| `/api/machines` | `{provider: "do-droplet", name, size, region, ssh_public, confirm_usd}` | `fleet machines create`, as a job |
| `/api/machines` | `{provider: "ssh", name, target, port?}` | `fleet machines add`, as a job |
| `/api/machines/check` | `{name}` | `fleet machines check`, as a job |
| `/api/machines/destroy` | `{name, confirm}` | `fleet machines destroy`, as a job. `confirm` must repeat the name |
| `/api/machines/adopt` | `{name}` | `fleet machines adopt`, as a job |
| `/api/machines/forget` | `{name}` | `fleet machines forget`, as a job. The machine itself is not touched |
| `/api/hosts/check` | `{provider}` | `fleet hosts check`, as a job |

**Keys and tokens never go through the page.** `/api/models/add` and the hosting routes refuse a
field whose name says key, secret, token, credential or password. `/api/models/add` also refuses
a key written into `bin` or `run`. A model's key belongs on the standard input of
`fleet models auth <id>`, and a provider login belongs in a terminal on the farm. A person's SSH
public key is not a secret and may be sent as `ssh_public`. It is written to a temporary file with
mode 600, passed as `--pubkey-file`, and deleted when the job ends.

### Long actions are jobs

Draining, resuming, adding a project and the hosting actions can take longer than a request.
They answer `202` at once, with a job record:

```json
{"job": {"id": "drain-1790000000-a1b2c3", "action": "drain", "key": "power",
         "label": "Drain the farm", "command": "fleet game-mode on", "state": "running",
         "started_at": "2026-09-22T08:00:00Z", "ended_at": null, "output": "", "pid": 4242}}
```

- The record is a file, `~/.fleet/jobs/<id>.json`, so a reloaded page can still read how the job
  ended: `GET /api/jobs/<id>` for one, `GET /api/jobs` for those in flight.
- A job ends `done` or `failed`, with `exit_code`, the end of the tool's output and, on a failure,
  an `error` sentence. A job whose dashboard stopped reads as `failed`. Finished records are
  deleted after a day.
- Each job holds a key for what it changes: `power` for throttle, drain and resume; `projects` for
  adding and removing a project; `machine:<name>` for one machine; `host:<provider>` for a
  provider check. A second job with a key that is in use is refused with `409` and the record of
  the running one, so pressing Drain twice drains once.
