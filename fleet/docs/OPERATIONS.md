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
the bind is wide. Writes always need it. The page and its own files are open either way, or the
page could never be opened to hand over the token in the first place.

| Route | Method | Answers |
|---|---|---|
| `/static/<file>` | GET | the front end's files, confined to `dashboard/static` |
| `/api/config` | GET | the page's name, this build, and which optional parts this farm has |
| `/api/health` | GET | one row per prerequisite: `ok`, `missing`, `off` or `error`, each with a fix |
| `/api/projects` | GET | the registered projects, with lanes open now and last activity |
| `/api/projects` | POST | registers one, by running `fleet add-project` |
| `/api/agent/log?slug&tail=200` | GET | that lane's log as words, at most 2000 lines |
| `/api/agent/msg` | POST | `{slug, text}`, delivered by `fleet msg` at the lane's next checkpoint |
| `/api/mail/boxes` | GET | the head office's mailboxes, with a count for the last day |
| `/api/mail/thread?box&since` | GET | one mailbox's messages, newest last |
| `/api/mail/feed?hours=24` | GET | the whole office as one timeline, newest first, built here |
| `/api/mail/who` | GET | the live sessions, from `hq who` |

Every time in these answers is an ISO 8601 stamp in UTC, so two of them can be merged and
sorted: the moment an answer was true, a message's own stamp, a session's last sign of life.
A branch claim is the one line with no moment of its own: it is a fact about now, so it leads
the timeline and says "held now" where the others say how long ago they happened.
| `/api/mail/send` | POST | `{to, text}`, sent through `hq msg` as this dashboard's own name |

One background thread refreshes the health table, the mailboxes, the office timeline and the
session list every 45 seconds. No GET runs a tool, reaches the network or writes to disk: the
page redraws every few seconds, and a tool call on a read path is a few thousand calls an hour
against the API budget every agent on the machine shares. An answer says `pending` until that
thread's first pass, and keeps the last good values when a pass fails, with `stale_since` saying
when they were still true. They read through `gh` and never through `hq inbox`, because a plain
inbox read moves a cursor shared by every process signing as one name on one machine, so a page
polling it would quietly consume an agent's mail. With no `hq` installed, or none pointed at an
office, every mail route answers with one sentence and the command that fixes it.

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
