# Operating a farm

How to set up a machine that runs headless coding agents (a **farm**), and how to run it once it
is up. Everything here is generic: substitute your own values for `<FARM_HOST>`, `<PROJECT>`,
`<OWNER>/<REPO>` and `<LANE>`.

The shape of the thing:

```
  your laptop (cockpit, thin)              the farm (a spare Linux box)
  ┌────────────────────────┐               ┌──────────────────────────────────┐
  │ an orchestrator session│   ssh/git     │  fleet CLI                        │
  │ a browser on the board │◄─────────────►│  one agent per lane, each in its  │
  │ `fleet` ssh shim       │               │  own git worktree                 │
  └────────────────────────┘               │  dashboard, sweep timer, daemon   │
                                            └──────────────────────────────────┘
```

Past roughly four or five parallel agents a laptop runs out of RAM and thermal headroom. The farm
does the work; finished branches come back over git. Nothing but git and ssh crosses between the
two machines.

---

## 1. Prerequisites

On the farm:

| Need | Why | Check |
|---|---|---|
| Linux with **systemd** and a running **user manager** | the sweep timer, the supervisor daemon and the CI queue are `systemctl --user` units | `systemctl --user is-system-running` |
| a **delegated cgroup** for the user manager | power modes cap `fleet.slice` live, without root | `cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/cgroup.controllers` lists `cpu` and `memory` |
| **linger enabled** for your user | units must survive with nobody logged in | `loginctl enable-linger $USER` |
| **python 3.11 or newer** | the config registry is parsed with `tomllib` | `python3 -V` |
| **git** | worktrees are the isolation mechanism | `git --version` |
| **gh**, logged in | agents open pull requests; the sweep asks GitHub whether a branch merged | `gh auth status` |
| **claude** and/or **codex**, logged in on a subscription | the engines the lanes run on | `claude --version`, `codex --version` |
| **tmux** | the dashboard runs in a detached session | `tmux -V` |

Two things about the agent logins:

- Log in **on a subscription**, not an API key. The fleet unsets `ANTHROPIC_API_KEY` when it
  spawns, so a lane can never quietly bill an API account. The real constraint is the
  subscription's own usage windows, shared with your interactive sessions.
- The login is interactive, so do it once over an ssh session with a terminal:
  `ssh -t <FARM_HOST> claude` then `/login`. For codex, tunnel the OAuth callback back to your
  machine: `ssh -L 1455:localhost:1455 -t <FARM_HOST> codex login`.

Optional but worth it: a private network (a tailnet or a VPN) between your machine and the farm, so
the dashboard port and ssh are not exposed to the internet. A single-machine setup needs none of
this, see `--local` below.

---

## 2. Install

```bash
git clone <REPO_URL> ~/work/fleet
cd ~/work/fleet
./install.sh
```

That links `~/.local/bin/fleet`, links the orchestrator skill into `~/.claude/skills`, copies the
two example configs into `~/.config/fleet/` if they are not there yet, and enables the sweep timer.
It prints what it did. Flags:

| Flag | Effect |
|---|---|
| `--prefix DIR` | link the launcher under `DIR/bin` instead of `~/.local/bin` |
| `--no-autosweep` | leave the 10-minute sweep timer alone |
| `--no-skills` | do not link agent skills into `~/.claude/skills` or `~/.codex/skills` |
| `--with-paper` | also install the optional Paper subsystem, see `contrib/paper/README.md` |
| `--local` | single machine: no ssh shim advice, and `FLEET_DASH_BIND=127.0.0.1` is recorded in the env file that `fleet dashboard` reads |

Operator overrides live in one file, `~/.config/fleet/env`, which the `fleet` command reads on
every run (FLEET_* keys only, and an explicit export wins), and so does `fleet dashboard` (`FLEET_HOME`, `FLEET_DASH_BIND`, `FLEET_DASH_TOKEN`, any unit
tuning; the full list is in section 9). Every install writes `FLEET_HOME` there, so the units
always resolve their scripts against the clone you installed from. Limits live in
`~/.config/fleet/policy.toml`.

If the farm is a separate machine, do not install the tool twice. Put a shim on your own machine so
`fleet ...` runs over ssh:

```bash
printf '#!/usr/bin/env bash\nargs=(); for a in "$@"; do args+=("$(printf %%q "$a")"); done\nexec ssh <FARM_HOST> "$HOME/.local/bin/fleet ${args[*]}"\n' > ~/.local/bin/fleet
chmod +x ~/.local/bin/fleet
```

`<FARM_HOST>` is an ssh host alias for the farm. The shim quotes every argument, which matters:
briefs contain quotes and newlines.

---

## 3. Register a project

```bash
fleet add-project --name <PROJECT> --repo <OWNER>/<REPO>       # clones to ~/work/<PROJECT>
fleet add-project --name <PROJECT> --repo <OWNER>/<REPO> \
                  --path /srv/checkouts/<PROJECT> --branch main --port-base 5200
fleet projects                                                  # what is registered
```

The registry is `~/.config/fleet/projects.toml`. Registering the same name twice with different
settings is refused rather than appended, so the file cannot grow two tables for one project.

`port_base` is the start of the block of ports the project's lanes get handed (dev server, API,
end-to-end runner). Give each project its own block so lanes from different projects cannot collide.

The tool is project-agnostic: a worker grounds itself in the target repo's own `CLAUDE.md`, so the
conventions it follows are the project's, not the fleet's.

---

## 4. First spawn

```bash
fleet capacity                       # will the box take another agent?
fleet spawn --project <PROJECT> --lane <LANE> --model sonnet \
      --by <CODENAME> --icon 🕷 --color '#a371f7' \
      --task "Implement X. Acceptance: ..."
fleet status                         # lanes plus farm health
fleet tail <slug>                    # one lane, human-readable
fleet logs <slug>                    # its raw stream
fleet events --follow                # the append-only event stream
```

A spawn takes a capacity check, cuts a fresh worktree off the project's base branch, hands the lane
deterministic ports, and launches the engine headless in a detached tmux session. The stream is
parsed into `~/.fleet/state/<slug>.json`, which is what `fleet status` and the dashboard read.

Briefs come in three shapes: `--issue N` (the worker reads the GitHub issue), `--task "..."`
(inline) or `--brief-file <path>` (a file on the farm). Use `--brief-file` for anything long or
full of punctuation, see [`sharp-edges.md`](sharp-edges.md).

`--by <CODENAME>` tags who spawned the lane, and the dashboard groups by it. One code name has one
emoji and colour: the first spawn registers the mark and the registry wins afterwards, so every
agent of one orchestrator looks alike. `fleet identity` shows and sets the marks.

Engines and tiers:

- `--engine claude` (the default) dials capability by `--model opus|sonnet|haiku`.
- `--engine codex` dials it by `--effort low|medium|high|xhigh`.
- A model the box cannot route is refused at spawn, not minutes later inside the lane.

**The dashboard** starts on the first spawn, or with `fleet dashboard start`, on port 7878. It is a
shared, long-lived service: health strip, subscription tiles, one card per lane with status, PR
link, live activity and cost. Stop it with `fleet dashboard stop`, never with a pattern kill, see
[`sharp-edges.md`](sharp-edges.md).

### What the dashboard serves

Reads are open when the dashboard is bound to this machine only, and need the bearer token once
the bind is wide. Writes always need it, and a request whose `Origin` or `Sec-Fetch-Site` says it
came from another site is refused whatever token it carries. The page and its own files are open
either way, or the page could never be opened to hand over the token in the first place.

**Read, from the snapshot.** Not one of these runs a tool, reaches the network or writes to disk.
Background threads read the machine instead: one every 45 seconds for the health table, the
services, the mailboxes, the office timeline and the session list; one every 45 seconds for the
two hosting listings; one every 15 seconds for the verification queue's observations; one every 5
seconds for the live machine numbers; one every 10 minutes for the subscription accounts. A page
redraws every few seconds, so a tool call on a read path is a few thousand calls an hour against
the budget every agent on this machine shares. An answer says `pending` until the first pass, and
keeps the last good values when a pass fails, with `stale_since` saying when they were still true.

| Route | Method | Answers |
|---|---|---|
| `/static/<file>` | GET | the front end's files, confined to `dashboard/static` |
| `/api/config` | GET | the page's name, this build, and which optional parts this farm has |
| `/api/health` | GET | one row per prerequisite: `ok`, `missing`, `off` or `error`, each with a fix |
| `/api/services` | GET | the agent runner, the verification runner, the sweep timer and this dashboard: state, since when, and what each one is for |
| `/api/metrics` | GET | load, memory, disk, GPU, temperature and whether this farm can spawn |
| `/api/mode` | GET | the power mode: the setting, what it resolves to, and the caps it applies |
| `/api/sweep` | GET | whether the sweep timer is enabled, and how long until the next pass |
| `/api/ci` | GET | the verification queue: running, waiting and recent, with the runner's own state |
| `/api/ci/log?id&tier` | GET | the last 256 KB of one stage's log, with `truncated` when there is more |
| `/api/projects` | GET | the registered projects, with lanes open now and last activity |
| `/api/fleet`, `/api/agent?slug` | GET | every lane, and one lane's whole record |
| `/api/agent/log?slug&tail=200` | GET | that lane's log as words, at most 2000 lines |
| `/api/accounts` | GET | each subscription's windows, with the last good numbers when a read failed |
| `/api/accounts/login-state` | GET | per account: `logged_in`, `waiting_for_login`, `expired`, `rate_limited` or `unknown`, each with a sentence and when it was last read. `waiting_for_login` means the credentials file is ABSENT; one that is there but cannot be read is `unknown`, never an invitation to log in over it |
| `/api/jobs`, `/api/jobs/<id>` | GET | the long actions in flight, and one action's record |
| `/api/engines` | GET | the model catalog as the Models table reads it: one row per model with how it is paid for (`access`), one status word (`on`, `off`, `needs_key`, `not_installed`, `failing`), whether this farm added it (`source`), the model it runs (`variant`), and whether its command is on this machine. It starts nothing: running a model is what Test is for |
| `/api/models` | GET | the catalog as the library sees it, without the machine's own facts |
| `/api/models/presets` | GET | the services "Add a model" offers (Claude Code, Codex, Gemini CLI, Qwen Code, Kimi Code, Grok Build, OpenCode, Aider, Ollama local, Custom command), each with its install hint, its key variable, its variants, how it is paid for and whether running it headless is permitted. `added` is true for a service this farm already has |
| `/api/power/preview?action=` | GET | what throttle, drain or resume will do, with the lanes a drain would stop, by name |
| `/api/mail/boxes` | GET | the head office's mailboxes, with a count for the last day |
| `/api/mail/thread?box&since` | GET | one mailbox's messages, newest last |
| `/api/mail/feed?hours=24` | GET | the whole office as one timeline, newest first, built here |
| `/api/mail/who` | GET | the live sessions, from `hq who` |
| `/api/machines` | GET | this farm, the machines it owns and what they cost a month, each with one `state` (`creating`, `preparing`, `needs-login`, `ready`, `unreachable`, `failed`, `destroyed`, `unrecorded`), the command that finishes a new one and the command that tunnels to its dashboard, and the provider's own `provider_id`. From `fleet machines list --json`, read on a thread and never on the request |
| `/api/hosts` | GET | one row per hosting provider: which job it does (`machine` or `runner`), whether its CLI is installed, `login_state` (`logged_in`, `logged_out`, `not_installed`, `no_answer`, so a slow provider is never drawn as logged out), which of its secrets are stored, the last Test, its `cli`, `color`, `engines` and `docs`, and its terms, pricing, sizes (each with `default`, true on exactly one) and regions. From `fleet hosts list --json`, passed through untouched |

**Write.** Every one of these needs the token, names its own timeout in the code, passes argv as a
list (never a shell string), and answers with one sentence a person can act on rather than with a
traceback. `--` goes before a positional only where the CLI parses options with argparse
(`hq msg`, `fleet ci cancel`); `fleet`'s own case loops refuse a bare `--` as an unknown flag, so
none is sent to them.

| Route | Body | Runs |
|---|---|---|
| `/api/services` | `{service, action}` | `fleet daemon start\|stop`, `fleet ci daemon start\|stop`, `fleet autosweep on\|off`; a restart is the stop and then the start. The dashboard's own row refuses and names `fleet dashboard restart` |
| `/api/power` | `{action}` | throttle: `fleet mode balanced`, at once. drain: `fleet game-mode on`, as a job. resume: `fleet game-mode off`, as a job |
| `/api/agents/kill` | `{slug, retire}` | `fleet kill [--retire] <slug>`; the answer carries the lane's restart policy and what the press did |
| `/api/ci/enqueue` | `{project, pr}` | `fleet ci enqueue --project <name> --pr <n>`, as a job |
| `/api/ci/cancel` | `{id}` | `fleet ci cancel -- <id>`, for a run that is running or waiting |
| `/api/projects` | `{name, repo, port_base?}` | `fleet add-project`, as a job (it clones the repository); without a port base it takes the next free block above the highest registered one, and is refused with a sentence when there is no free block left |
| `/api/projects/remove` | `{name}` | a guarded rewrite of `projects.toml` (there is no fleet verb): refused while the project has lanes open or while a project is being added, keeps a copy of the previous file, and names the dev server port block that is free again |
| `/api/accounts/add`, `/api/accounts/remove` | `{name, engine}` / `{name}` | the login command and its steps; removal moves the account to `dead-account-backups` |
| `/api/accounts/refresh` | | wakes this server's own account reader, and is refused for sixty seconds afterwards: one press is one request per account to the vendor |
| `/api/models` | `{action, id}` | enable, disable or test one model, each a real request to the provider |
| `/api/models/add` | `{preset, id, variant?, label?, bin?, run?, auth_env?}` | writes one entry into this farm's own `models.toml`, creating it from the shipped example on the first write, and answers the new row. It runs nothing. A body carrying a key is refused with `A key never goes through this page. Run: fleet models auth <id>`, whatever the field is called, and so is a key written into `bin` or `run`: a key belongs on a terminal's stdin, not in a browser, a proxy log or this server. A command that names the variable holding it (`--api-key $MY_API_KEY`) is what to write instead. `variant` is required by a service whose command line carries `{variant}`, and refused by one that does not |
| `/api/models/remove` | `{id}` | deletes one entry this farm added, with its runtime state and its stored key. `404` when there is no such model, `400` when it came with fleet (a shipped model can be switched off, not removed) |
| `/api/mode` | `{mode}` | the power mode, applied at once |
| `/api/agent/msg` | `{slug, text}` | `fleet msg`, delivered at the lane's next checkpoint |
| `/api/mail/send` | `{to, text}` | `hq msg -- <to> <text>` as this dashboard's own name, then wakes the office reader |
| `/api/machines/plan` | `{provider, name, size, region, ssh_public?}` | `fleet machines plan --provider P --name N --size S --region R [--pubkey-file F] --json`, synchronously, answering with its JSON as it printed it, unwrapped (design section 7), and its job record is under `/api/jobs`. A POST because it runs a tool that asks the provider for today's price; a read-only page never needs a plan. It buys nothing |
| `/api/machines` | `{provider: "do-droplet", name, size, region, ssh_public, confirm_usd}` | `fleet machines create ... --pubkey-file F --confirm-usd N`, as a job. It asks the provider for the droplet and returns; the progress from `creating` to `needs-login` is made by the refresher's `list`. Without `ssh_public` it is refused with `Your SSH public key is how your laptop reaches the machine.`, because the finish command and the tunnel are both run from the person's laptop |
| `/api/machines` | `{provider: "ssh", name, target, port?}` | `fleet machines add --name N --target user@host [--port P]`, as a job. Nothing is bought: the machine is registered and checked |
| `/api/machines/check` | `{name}` | `fleet machines check N`, as a job |
| `/api/machines/destroy` | `{name, confirm}` | `fleet machines destroy N --confirm N`, as a job. `400` unless the confirmation repeats the machine's name: the disk goes with it, and this is the only thing that stops the billing |
| `/api/machines/adopt` | `{name}` | `fleet machines adopt N`, for a droplet this farm made and lost: the row is written back from the provider's own facts |
| `/api/machines/forget` | `{name}` | `fleet machines forget N`: the row goes, the machine is not touched |
| `/api/hosts/check` | `{provider}` | `fleet hosts check <provider>`, as a job |
| `/api/hosts/test` | `{provider, project, confirm: true}` | `fleet runner test <provider> --project P`, as a job. It creates the smallest sandbox the provider sells, runs two commands in it and deletes it, so it spends a few cents: `400` without `confirm: true` |

### Long actions are jobs

Draining the farm, resuming it, queueing a verification and adding a project can outlast a
request, so they answer `202` at once with a job record instead of holding the connection open:

```json
{"job": {"id": "drain-1790000000-a1b2c3", "action": "drain", "key": "power",
         "label": "Drain the farm", "command": "fleet game-mode on", "state": "running",
         "started_at": "2026-09-22T08:00:00Z", "ended_at": null, "output": ""}}
```

The record is a file under `$FLEET_STATE/jobs/<id>.json`, so a page that was reloaded, or a second
page, can still read how it ended: `GET /api/jobs/<id>` for one, `GET /api/jobs` for the ones in
flight. A job ends `done` or `failed`, with the exit code, the tail of what the tool said and, on
a failure, one sentence naming it. A job whose dashboard is gone reads as `failed` rather than as
running for ever, and a finished record is forgotten after a day, by the 45 second refresher and
not only by the next job to start.

Hosting jobs take a key of their own: `machine:<name>` for everything about one machine, so a
second machine can be ordered while the first one is still booting, and `host:<provider>` for a
provider's check and test. When one of them ends, the hosting snapshot is asked to look again at
once, rather than at the end of its 45 second sleep. A token never goes through any of these
routes: a body with a field whose name carries key, secret, token, credential or password is
refused with `A token never goes through this page. Run the login command in a terminal on this
farm.`, and the refusal repeats neither the value nor the field's name. A person's SSH public key
is not a credential and may be typed in, under the field name `ssh_public`; it is written to a
0600 temporary file, passed as `--pubkey-file`, and deleted the moment the job ends.

A runner test holds a paid sandbox while it runs. Past its 600 second timeout it is sent SIGTERM,
to its whole process group, and given 60 seconds to delete the sandbox before it is killed; the
grace only helps a `fleet runner test` that turns SIGTERM into its own delete. The grace is not
what owns a leak. The contract is that `fleet runner test` writes its handle,
`$FLEET_STATE/runners/<slug>.json`, before it asks the provider for anything, exactly as a runner
lane does (design section 5), so a test that is killed anyway leaves a sandbox `fleet runner reap`
finds and deletes on the next sweep.

The refusal is about the RESOURCE, not the verb. A job holds a `key`, and starting anything that
holds the same key is refused with `409` and the record of the one in flight, because pressing
Drain twice must not drain twice. Throttle, drain and resume all hold `power`, since this farm has
one power state and `fleet game-mode on` and `fleet game-mode off` are opposites: without that,
Drain and Resume ran at once and whichever call landed last decided where the farm ended up.
Adding a project and removing one both hold `projects`, the registry being one file: a second
press cannot start a second clone, and a removal cannot rewrite the file underneath a clone that
is about to append to it.

Every time in any of these answers is an ISO 8601 stamp in UTC, so two of them can be merged and
sorted: the moment an answer was true, a message's own stamp, a session's last sign of life, when
a service last became active. A branch claim is the one line with no moment of its own: it is a
fact about now, so it leads the timeline and says "held now" where the others say how long ago
they happened.

The mail routes read through `gh` and never through `hq inbox`, because a plain inbox read moves a
cursor shared by every process signing as one name on one machine, so a page polling it would
quietly consume an agent's mail. With no `hq` installed, or none pointed at an office, every mail
route answers with one sentence and the command that fixes it.

A lane ends by opening a pull request and stopping. Merging is a human decision.

---

## 5. The supervisor daemon

A lane is one pass. If it exits before delivering, something has to notice. That is the daemon:

```bash
fleet daemon start        # systemd --user unit, one instance, survives a reboot
fleet daemon status       # up, plus the last heartbeats
fleet daemon tick         # a single reconcile pass, for a dry look
fleet daemon stop
```

It only ever acts on lanes spawned with a `--restart` policy; every other lane is invisible to it.

```bash
fleet spawn ... --restart until-merged --done-when pr-merged
fleet spawn ... --issues 1923,1809 --restart until-merged   # no silent scope drop
fleet spawn ... --after <LANE>:pr-merged                    # defer until that lane lands
```

- `--restart until-pr | until-merged | until-file:<path> | never` and
  `--done-when pr-open | pr-merged | file:<path> | issue-closed:#N`. Set `--restart` alone and the
  contract is inferred.
- Respawns are bounded (`FLEET_RESPAWN_MAX`, default 10, `FLEET_RESPAWN_COOLDOWN`, default 600s),
  then the lane is marked `gave_up`. No storms.
- A multi-issue lane is not delivered while any issue is unaccounted for. The leftover shows in the
  heartbeat and emits a `dropped-scope` event.
- `--after` creates nothing at spawn time: no worktree, no card. The daemon fires the lane when the
  dependency delivers.

**Without the daemon running, `--restart` and `--after` are recorded metadata and nothing more.**

---

## 6. Sweep, and not losing work

`fleet sweep` is the janitor: it removes worktrees whose branch GitHub reports as merged, and reaps
dashboard cards that are resolved. `install.sh` puts it on a 10-minute timer
(`fleet autosweep on|off|status [minutes]`).

```bash
fleet sweep --dry-run       # exactly what the next pass would take
fleet clean --project <PROJECT> --dry-run
fleet salvage <slug>        # commit and push a lane's work before cleaning it
```

The survival rules, in one line each: running lanes are never touched; an open PR protects a
worktree and its card indefinitely; tracked-but-uncommitted changes are kept until someone sweeps
with `--force`; untracked scratch protects nothing; committed-but-unpushed commits are pushed to
`refs/fleet-salvage/<slug>` before a burial. Full contract in [`SWEEP.md`](SWEEP.md), and the ways it bites in
[`sharp-edges.md`](sharp-edges.md).

---

## 7. Accounts

A farm can hold several subscriptions and spread lanes across them. An account is a CLI config
directory: the default one is `~/.claude`, extra ones live in `~/.fleet/claude-accounts/<name>`.

```bash
fleet accounts                 # session / weekly percentages per account, with reset countdowns
fleet accounts add <name>      # create the config dir
ssh -t <FARM_HOST> env CLAUDE_CONFIG_DIR=~/.fleet/claude-accounts/<name> claude   # then /login
fleet accounts pick            # the account with the most headroom
fleet accounts balance         # round-robin across every engine and account with headroom
fleet accounts keepalive       # refresh any token near expiry
```

- Log the browser into the **right** account (use a private window if another session is open), or
  the new account is silently the same pool.
- `fleet spawn --account auto` round-robins across accounts that have headroom. It is deliberately
  unweighted: the point is to fill idle per-account session windows, not to drain the freest one.
  An account at or above 95% of a window drops out until its reset.
- `fleet accounts balance` prints `engine account` for the next lane, spreading across engines too.
- A token that is never used expires, and the usage endpoint then answers 429, which reads like
  rate limiting but is a dead token. Run `fleet accounts keepalive` on a timer of your own (this
  repo ships only the sweep timer) and re-login the accounts it names.
- The pool is shared with your own interactive use. When every account is red, stop spawning.

---

## 8. Power modes

Agents run in a `fleet.slice` user slice, so the farm's CPU and memory share can be capped live and
reversibly, with no root and without killing an agent.

```bash
fleet mode                # current mode
fleet mode auto           # the default
fleet mode full|soft|balanced|hard
```

| Mode | CPU share | New spawns |
|---|---|---|
| `full` | uncapped | yes |
| `soft` | about 50% | yes |
| `balanced` | about 35% | paused |
| `hard` | about 20% | paused |

`auto` means full while the GPU is idle and `soft` while it is busy, which is the "somebody is using
this machine" signal. It never picks a harder profile on its own: casual use of the box should make
the farm step aside, not stop. A manual pick wins until you set `fleet mode auto` again.

For a heavier need there is `fleet game-mode on|off|status`, which salvages and stops the farm, then
brings it back.

Capacity is separate from power mode. `lib/metrics.py` plus `~/.config/fleet/policy.toml` block a
spawn on hardware only: a RAM floor, a disk floor, GPU and CPU temperature ceilings. Agent count
never blocks, it only raises an advisory. Read the live numbers from `DEFAULT_POLICY` in
`lib/metrics.py` rather than from any document.

---

## 9. Where state lives

| What | Where |
|---|---|
| the tool | wherever you cloned it, linked from `<prefix>/bin/fleet`; `FLEET_HOME` points at it |
| runtime state | `~/.fleet/state/<slug>.json` (one card per lane) |
| raw logs | `~/.fleet/logs/<slug>.jsonl` and `.err` |
| worktrees | `~/.fleet/worktrees/<project>/<slug>` |
| briefs | `~/.fleet/briefs/` (saved, so a respawn re-runs the lane verbatim) |
| lane inboxes | `~/.fleet/msg/<slug>.md`, written by `fleet msg <slug> "..."` |
| deferred spawns | `~/.fleet/pending/<lane>.json`, waiting on an `--after` dependency |
| archived cards | `~/.fleet/state-archive/<YYYY-MM>/`, including `.dirt.txt` autopsies |
| config | `~/.config/fleet/{projects,policy}.toml` and `~/.config/fleet/env` |
| user units | `~/.config/systemd/user/fleet-*.{service,timer}` |
| project checkouts | wherever `add-project` put them, `~/work/<PROJECT>` by default |

Nothing the fleet writes at runtime lives inside the repo, so the checkout stays clean and
`git pull` is always safe.

### Environment

Everything below is optional, has a working default, and belongs in `~/.config/fleet/env`
(the file the user units read, and which `dashboard/run.sh` reads too).

| Variable | Default | What it decides |
|---|---|---|
| `FLEET_HOME` | the checkout `install.sh` ran from | which clone the units and the spawn launcher resolve scripts against |
| `FLEET_STATE` | `~/.fleet` | runtime state, logs, worktrees, briefs, inboxes |
| `FLEET_CONFIG` | `~/.config/fleet` | `policy.toml`, `projects.toml`, `codenames.json`, `dash-token` |
| `FLEET_DASH_BIND` | `127.0.0.1` | what the dashboard binds; an IPv6 literal is served on an IPv6 socket |
| `FLEET_DASH_PORT` | `7878` | its port |
| `FLEET_DASH_TOKEN` | a minted one in `$FLEET_CONFIG/dash-token` | the bearer token every write needs, and every read once the bind is wide |
| `FLEET_DASH_TITLE` | `murmur` | what the page calls itself, in the tab and in its header |
| `FLEET_DASH_HQ_AGENT` | `dashboard` | the name the page signs head office mail with. Never a name taken from a request, so a message from the page is always attributable to the page |
| `FLEET_FARM_ALIAS` | this machine's hostname | the ssh host name printed in the account-login instructions. The hostname is almost never how you actually reach the box, and a wrong name there sends an operator to a machine that does not answer |
| `FLEET_NVIDIA_SMI` | `nvidia-smi` on PATH | the GPU sensor. Unset and absent, `fleet mode auto` is inert and says so once |
| `FLEET_LHM_URL` | unset | a LibreHardwareMonitor endpoint for CPU temperature. Unset, the temperature reads UNKNOWN and never blocks a spawn |
| `FLEET_DASH_HEALTH` | unset (off) | `on` draws the Health section on the Machine tab: the hardware tiles (graphics card, processor temperature, load, memory, disk) and the prerequisites table. Off by default because most machines have neither sensor; the Board's setup checklist does not depend on it |
| `FLEET_CODEX_BIN` | `/usr/bin/codex` | the codex CLI lanes run. Point it at a user-level install (`npm i -g --prefix ~/.local/share/codex-cli @openai/codex@latest`) when the system one needs root to update: a newer CLI is what unlocks newer models |
| `FLEET_CODEX_MODEL` | `gpt-5.6-sol` | the model a codex lane runs when `fleet spawn` gets no `--model` |

---

## 10. Updating

```bash
cd ~/work/fleet
fleet status              # are any lanes live? a restart of the units interrupts nothing, but know
git pull
./install.sh              # idempotent, re-run it with the same flags you used the first time
systemctl --user restart fleet-daemon fleet-ci 2>/dev/null || true
```

`install.sh` is safe to re-run: it relinks, it does not overwrite an existing
`policy.toml`/`projects.toml`, and it rewrites a key in `~/.config/fleet/env` in place rather than
appending a second copy. Re-running with different flags is how you change the shape of an install.

Coming from a fleet older than the configurable head office, commit identity, dashboard token and
contrib Paper, walk [`MIGRATION.md`](MIGRATION.md) once: it lists every step an existing farm needs
so that nothing it used to do changes underneath it.

Before you trust a change to the harness itself, run the checks in [`VERIFYING.md`](VERIFYING.md).

---

## 11. When something looks wrong

| Symptom | First thing to check |
|---|---|
| `fleet: command not found` over ssh | a non-interactive ssh has no `~/.local/bin` on PATH; use the full path, which is what the shim and the spawn launcher do |
| dashboard unreachable | `fleet dashboard start`; if the port answers but nothing renders, look for a second copy started by hand |
| a card says `running?` with `dead?` | the record outlived its process, usually a reboot; the lane is gone, its worktree is not |
| the sweep prints `ABORT ... unreadable state record` | normal while a lane is mid-write; one abort is expected, a repeating one clears itself within a grace window, a permanent one means the state directory is not writable |
| lanes stall for half an hour | shared-resource contention, not their code: one shared test database, or two lanes on one port. Give each lane its own |
| a lane never delivered and nothing respawned it | `fleet daemon status`; `--restart` does nothing without the daemon |
| every account shows red | the subscription windows are spent; wait for the reset rather than hunting for a workaround |

For the failure modes that destroy work rather than merely annoy you, read
[`sharp-edges.md`](sharp-edges.md) once, before you need it.
