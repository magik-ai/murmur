# Hosting: machines and runners

Design record, 2026-09-23. The owner: "add the ability to connect different hostings for the
machine, so the connectors are there from the start: DigitalOcean (with its new Managed Agents),
Railway, Vercel; think through the setup, write skills, make onboarding easy through the
interface." This record is the answer, built on a research pass over each provider's own
documentation (murmur plan, `internal/research/report-hosting.md`).

## 1. The finding that shapes everything

The three providers do not offer the same thing, and a page that drew them as three
interchangeable "hosts" would lie. There are two jobs:

| Job | What it is | Who can do it today |
|---|---|---|
| **Machine** | a whole farm: systemd user services, tmux, worktrees, the dashboard, the installer runs as is | DigitalOcean Droplet; any Linux machine you reach over SSH (your own PC, WSL2, Hetzner, a company VM) |
| **Runner** | one lane at a time, in a remote sandbox, started and watched by a farm | DigitalOcean Managed Agents (Harness Runtime); Railway sandboxes; Vercel Sandbox |

Not a fit, said on screen with the reason: a farm inside a Railway container (no systemd; the
farm would need its own process supervisor, a later change), and the dashboard on Vercel
(stateless functions cannot read a farm's disk).

A farm is still the brain: it holds the worktrees, the claims, the queue, the dashboard. A runner
only moves the heavy part, the agent's own process, off the farm's CPU.

## 2. Providers (presets)

Served by `fleet/lib/host_presets.py`, one dict per preset, the same pattern as model presets:
`id, label, color, job (machine | runner), cli (the binary), install (the command that installs
the CLI), login (the command a person runs), whoami (the read-only check, argv), docs, terms (one
sentence), stage (ga | preview | early access), pricing (one sentence), sizes (list of {slug,
label, vcpu, ram_gb, disk_gb, monthly_usd or hourly_usd}), regions (list, first is the default),
secrets (env names the runner needs), engines (which fleet engines it can run)`.

| id | label | job | cli | login | whoami | stage |
|---|---|---|---|---|---|---|
| `ssh` | Your own machine | machine | ssh | none (your key) | `ssh -o BatchMode=yes <target> true` | ga |
| `do-droplet` | DigitalOcean Droplet | machine | doctl | `doctl auth init --context murmur` | `doctl account get -o json --context murmur` | ga |
| `do-agents` | DigitalOcean Managed Agents | runner | doctl | same context | `doctl harness-runtime list -o json --context murmur` | preview |
| `railway` | Railway sandboxes | runner | railway | `railway login --browserless` | `railway whoami --json` | early access |
| `vercel` | Vercel Sandbox | runner | sandbox | `sandbox login` | `sandbox list` | ga |

Facts carried by the presets (research dated 2026-09-23, `internal/research/report-hosting.md`):

- Droplet sizes `s-2vcpu-4gb` $24, `s-4vcpu-8gb` $48 (the default), `s-8vcpu-16gb` $96 a month;
  billed per second up to that cap; a powered-off droplet is still billed, only Destroy stops it.
- DO Managed Agents: region RIC1 only, prepaid balance required (sessions pause at zero), sessions
  pause after 15 idle minutes, about $0.25 an hour for 4 vCPU and 8 GB at full allocation.
- Railway sandboxes: $50 per vCPU-month and $50 per GB-month, idle timeout 30 minutes by default.
- Vercel Sandbox: up to 24 hours per session on Pro (45 minutes on Hobby), 2 GB per vCPU,
  processes do not survive a stop, about $0.13 an hour of active CPU plus memory.

Exact runner CLI shapes that the provider docs do not show are marked UNVERIFIED in the preset's
`terms` and in the adapter, never guessed silently.

## 3. Credentials: never through the page

Same law as model keys, and the fleet's standing rule that a lane never bills an API key:

- **Provider logins** are made by the provider's own CLI, in a terminal on the farm. The page
  hands the command (`ssh -t <farm> doctl auth init --context murmur`) and then watches the
  whoami check flip from "not logged in" to "logged in as <account>" by itself.
- **Runner secrets** are two: `CLAUDE_CODE_OAUTH_TOKEN` (the one-year subscription token that
  `claude setup-token` prints; the agent runs on the person's subscription, never on an API key)
  and `GITHUB_TOKEN`, **read-only** (a fine-grained token limited to the project's repository
  with contents: read; the remote agent clones with it and cannot push, so the farm's claims
  guard stays the only road to the branch). Stored by `fleet hosts secret <provider> <NAME>
  [--account <label>]` with the value on stdin, in `$FLEET_STATE/secrets/hosts/<provider>/<NAME>`,
  mode 600; the optional label records which Claude subscription the token belongs to. Handed to
  the provider only through its own secret mechanism, a 0600 file or the remote process's stdin,
  never on an argv.
- **Redaction is a mechanism, not a promise.** A remote agent can print its environment. So
  every line `run_remote.py` passes on, and the provider CLI's stderr, is first scrubbed by
  `fleet/lib/scrub.py` (one module, owned by the core lane): every stored secret value, plus the
  exact token shapes `sk-ant-[A-Za-z0-9_-]{20,}`, `gh[pousr]_[A-Za-z0-9]{36,}`,
  `github_pat_[A-Za-z0-9_]{50,}` and `dop_v1_[a-f0-9]{64}` (never a generic "long run of
  characters" rule, which would eat every commit SHA). The bootstrap never uses `set -x`. The
  dashboard scrubs `out` and `err` at the top of `_finish_job` and in `run_job_now`, so the
  `error` sentence and the synchronous answers are clean too. Acceptance greps the lane logs,
  `$log.err` and the job records, not only the fakes' argv.
- **A person's SSH public key** is not a secret and may be typed into the page (it lets the
  person reach a new machine from their laptop). Its field is `ssh_public`, because the models
  routes' classifier refuses any field whose name contains "key"; the value must parse as one
  line of `ssh-ed25519`, `ssh-rsa` or `ecdsa-sha2-*`.
- Every other field that looks like a credential is refused by that same classifier.

## 4. Machines

**Registry.** `~/.config/fleet/machines.toml`, one table per machine: `name, provider, user,
address, size, monthly_usd, region, provider_id, created_at, state, detail`. This farm is always
shown first and is not in the file. Written by `machines.py`'s own small atomic writer (the file must run alone
inside the plugin, so it does not import `models.py`; ten lines of visible duplication are
cheaper than a shared module the plugin would also have to carry).

**States.** `creating` (the provider is building it), `preparing` (first boot is installing
packages), `needs-login` (prepared; the person's two logins and the installer are left),
`ready` (the farm answers `fleet capacity` over SSH), `unreachable`, `failed`, `destroyed`, and
`unrecorded` (a droplet tagged `murmur-by-<farm id>` that the provider lists and the registry
does not: created by this farm and lost between the provider's answer and the registry write).
The farm id is a random word written once to `~/.config/fleet/farm-id`, so two farms on one
DigitalOcean account never claim each other's droplets. An `unrecorded` row offers Adopt (write
the row from the provider's facts) and Destroy, never Forget. Every
state of a droplet except `destroyed` still costs money, and its pill sentence says so with the
price; the section head carries the total ("You pay $96 a month for 2 machines").

**No droplet can cost money invisibly.** The order is: refuse a name that already has a live
row (a retry after a timeout must never buy a second droplet), write the row as `creating` with
the exact name, then call the provider, then record its id. `fleet machines list` (which the
dashboard's refresher runs every 45 seconds) reconciles the registry with `doctl compute droplet
list --tag-name murmur-by-<farm id> -o json`: a droplet without a row appears as `unrecorded`; a
`creating` row with no id picks its id up by name; a row whose id the provider no longer lists
becomes `destroyed`.

**One writer at a time.** The refresher's `list` and the per-machine jobs all read, change and
rewrite `machines.toml`, so every read-modify-write holds an `flock` on
`machines.toml.lock`, and no provider call or SSH is made while the lock is held.

**Nothing waits inside a request.** `create` only writes the row, imports the key, ensures the
firewall and asks the provider for the droplet; it returns in seconds. The progress from
`creating` to `preparing` to `needs-login` is made by `list`, one short step per machine per
pass (`doctl compute droplet get` for the address, then `cloud-init status` over SSH without
`--wait`), so a dashboard restart, a timed-out `doctl` or a dropped connection loses nothing:
the next pass carries on from the row. `list` never SSHes into a `ready` machine (Check does);
its SSH uses `ConnectTimeout=5`.

**The price is live.** `plan` reads `doctl compute size list -o json` (`price_monthly`) when
doctl is logged in; the preset's number is the fallback, labelled "list price on 2026-09-23".
`create` refuses when the live price differs from the price the person confirmed.

**What a new droplet gets.** A cloud-init file rendered by `fleet/lib/machines.py` (the only
place it is written; it stays well under the 64 KiB limit because it embeds nothing large):

- a user `farm` with no sudo, its SSH keys = this farm's own machines key (a fleet-owned key at
  `$FLEET_STATE/machines/id_ed25519`, made once; the person's `~/.ssh` is never touched) plus the
  person's public key, which is required when a droplet is created from the page (without it
  the finish command and the tunnel, both run from the laptop, cannot log in; the `/murmur:farm`
  skill reads the laptop's own key); root keeps key-only SSH for administration;
- packages `git tmux python3 curl ca-certificates`, and `gh` from GitHub's own apt repository
  exactly as `farm/install.sh` adds it (so the installer's system step finds everything and
  never reaches for sudo, which this user does not have);
- `FLEET_DASH_BIND=127.0.0.1` written into the farm user's `~/.config/fleet/env` before the
  installer ever runs, by a `runcmd` line run as that user (`runuser -u farm -- sh -c 'mkdir -p
  ~/.config/fleet && echo FLEET_DASH_BIND=127.0.0.1 >> ~/.config/fleet/env'`), never by
  `write_files`, which runs before the user exists and would leave root owning its home (the
  installer only adds that line when it is absent);
- `loginctl enable-linger farm`, so the farm's services outlive a login;
- a cloud firewall `murmur-ssh-only` attached by tag `murmur-farm`: inbound SSH only, outbound
  open (a DO firewall that only lists inbound rules also blocks the farm from GitHub and the
  model providers; the research found this trap). The dashboard stays on loopback, so the new
  farm is reachable by nobody but the keys it was given.

The installer is not run by cloud-init: it needs the person's GitHub login to clone murmur and
their Claude login to run agents, and both are logins only the person can do. After `preparing`
the machine row shows one command, copyable, run from the person's laptop:

```
ssh -t farm@<address> 'gh auth login && gh repo clone magik-ai/murmur ~/work/murmur -- -q && bash ~/work/murmur/farm/install.sh --remote'
```

(once the repository is public this becomes the one-line `curl ... | bash -s -- --remote`).
`--remote` is a new installer flag: this box is driven from a laptop, so the dashboard stays on
loopback, Tailscale is not offered, and the last lines print the tunnel
(`ssh -N -L 7878:127.0.0.1:7878 farm@<address>`). The installer also gains a preflight: when a
package is missing and `sudo -n true` fails, it names every missing package in one sentence and
stops before changing anything. Check then flips the row to `ready`.

**Adding a machine from the dashboard** (Machine tab, Hosting, "Add a machine"), a dialog with
numbered steps, in the pattern of the add-account and add-model dialogs:

1. Where: provider cards for "Your own machine" and "DigitalOcean Droplet", each with its price
   line and stage. Runner providers are not offered here.
2. For a droplet: name, size (radio cards with vCPU, RAM, disk and the monthly price), region,
   and your SSH public key (required: it is how your laptop reaches the machine). For your own machine: user, address, port.
3. Log in: if `doctl` is missing or not logged in on this farm, the install or login command
   and a state that flips by itself.
4. Review: the exact commands that will run and the cloud-init file, read-only and copyable.
5. Create: the button names the price ("Create, $48 a month until you destroy it"); the
   confirmation repeats it. The server runs `fleet machines create ... --confirm-usd 48` as a
   job; the dialog shows the job's steps; the row appears at once in `creating` and moves on
   by itself. For your own machine step 5 is "Add and check": it registers the machine and
   checks SSH; nothing is bought.

A machine row: Name, Provider, Address, Size and price, State (one pill), Last check, Actions:
Copy the finish command (in `needs-login`), Check, Destroy (droplets only: the confirmation
names the droplet, says the disk is deleted and billing stops, and must be answered by typing
the name), Adopt (`unrecorded`), Forget (a destroyed row, a failed row with no id, an own
machine).

This does not make the dashboard a multi-farm console: each farm keeps its own dashboard. The
list is where a person sees what they own and what it costs.

**Commands** (`fleet machines ...`, the page and the skill run the same code):

| Command | Does |
|---|---|
| `fleet machines list [--json]` | the registry, reconciled with the provider and advanced one step per machine |
| `fleet machines plan --provider do-droplet --name N --size S --region R [--pubkey-file F] [--json]` | prints the commands, the cloud-init and the live price; buys nothing |
| `fleet machines create ... --confirm-usd <price>` | refuses unless the price matches the live plan; writes the `creating` row; ensures this farm's key (creates one if missing) and imports it; ensures the firewall; creates the droplet without waiting; records its id; returns |
| `fleet machines add --name N --target user@host [--port P]` | an own machine: register and check |
| `fleet machines check N` | SSH, `cloud-init status`, then `fleet capacity`; updates state |
| `fleet machines destroy N --confirm N` | `doctl compute droplet delete <id> --force`; state `destroyed` |
| `fleet machines adopt N` | an `unrecorded` droplet becomes a row, from the provider's facts |
| `fleet machines forget N` | drops a `destroyed` row, a `failed` row with no id, or an own machine |

SSH from the farm to a machine always uses the machines key, `BatchMode=yes`, a connect timeout,
and a known-hosts file of the fleet's own (`$FLEET_STATE/machines/known_hosts`, `accept-new`),
so a check never hangs on a prompt and never edits the person's `~/.ssh`. When an address is
recorded, `ssh-keygen -R <address> -f <that file>` runs first, because DigitalOcean reuses
addresses and `accept-new` refuses a changed host key.

## 5. Runners

**What a runner does.** `fleet spawn --runner <provider>` keeps everything a lane is today (the
state record, the claimed branch, the worktree on the farm, the transient unit in
`fleet.slice`, the log, the parser, kill, sweep, salvage) and changes one thing: the unit's
`run.sh` does not start the engine on the farm, it runs `lib/runners/run_remote.py`, whose
stdout is the remote agent's output, scrubbed (section 3), so the same `tee` and parser read it.
It:

1. pushes the lane's branch from the worktree (the farm's claims guard runs) and keeps that
   commit's SHA as `base`;
2. writes a handle file `$FLEET_STATE/runners/<slug>.json` (provider, sandbox name, base,
   created_at) BEFORE it asks the provider for anything, then creates one sandbox and records
   its id there;
3. runs the bootstrap inside it, sent on stdin or copied as a file, never argv: install Claude
   Code if the image lacks it; a git credential helper that reads the read-only `GITHUB_TOKEN`
   from the environment (the token never enters a URL or a process list); a partial clone of the
   branch (`--filter=blob:none`, so a branch ahead of main can still merge main); `user.name` and
   `user.email` set to the lane's own identity; then `claude -p` with the brief and the system
   prompt (sent as files), with `CLAUDE_CODE_OAUTH_TOKEN` in its environment, `ANTHROPIC_API_KEY`
   unset, and without `--include-partial-messages` (a token cannot be split across two delta
   lines and slip past the scrub). For DO, whose `prompt` runs DO's own adapter, the same
   bootstrap minus the `claude` line runs first through one buffered `doctl harness-runtime
   exec`, then `prompt` starts the agent in that checkout;
4. **the brief is rendered for a sandbox.** A runner lane's brief carries the sandbox clone path
   instead of the farm worktree, and one runner paragraph replaces the template's push and pull
   request lines: "You run in a remote sandbox. hq and fleet are not available. Commit your work;
   do not push and do not run gh. When you are done, write the pull request title on the first
   line and its body after it into /tmp/fleet-pr.md, outside the repository. The farm pushes your
   branch and opens the pull request.";
5. streams the scrubbed remote output to stdout, and scrubs the provider CLI's own stderr before
   it reaches `$log.err`;
6. brings the work home every five minutes when `git rev-parse HEAD` inside the sandbox has
   moved, and at the end: at the end it first commits a dirty tree ("wip: uncommitted work at
   exit"); an empty `base..HEAD` means nothing new (no bundle is made); otherwise `git bundle
   create - base..HEAD` comes back base64-encoded on every provider (DO: written to a file and
   fetched with `download`), and the farm runs `git -C <wt> fetch <bundle>`, `git -C <wt> merge
   --ff-only FETCH_HEAD` (a non-fast-forward is left alone and said in the log) and `git -C <wt>
   push origin HEAD:<branch>`, where the claims guard runs. So the worktree always holds the
   latest committed work, and `fleet salvage` and the sweep protect it as they protect a local
   lane;
7. at the end, reads `/tmp/fleet-pr.md` from the sandbox and, when the branch has commits and no
   pull request exists, runs `gh pr create --head <branch>` with that title and body from the
   farm (a missing file gives a draft with the branch name as title). So `--done-when pr-open`
   and `--restart until-pr` finish as they do for a local lane;
8. on exit, on an exception, and on SIGTERM or SIGINT (a handler, not only `finally`), brings the
   work home one last time, opens the pull request, deletes the sandbox and removes the handle
   file. A closed stdout is not fatal to the handler: it still deletes.

**Stopping a runner lane.** In a runner lane's `run.sh`, `tee` and the parser start under
`trap '' TERM`, so they keep draining until `run_remote.py` closes its stdout. The unit gets
`TimeoutStopSec=120`. `fleet kill` on a runner lane marks the record `killed` first, then runs
`systemctl --user stop --no-block`, so the dashboard's kill (which waits 60 seconds) never
reports a failure for a stop that is still bringing work home.

**The reaper.** A hard kill (out of memory, a reboot) can skip the handler, so `fleet runner
reap` handles every handle file whose unit is not loaded or whose `ActiveState` is `inactive` or
`failed` (never `deactivating`, which is a stop in progress): it brings the work home, then
deletes the sandbox and the file. The sweep runs it every ten minutes (`fleet sweep --dry-run`
only lists). `--runner` is refused when the sweep timer is off, because then nothing would reap.

**Whose subscription.** A runner lane spends the subscription its `CLAUDE_CODE_OAUTH_TOKEN`
belongs to, which the Accounts windows on this farm do not see. So `--runner` is checked before
the account default is resolved: an explicit `--account` with `--runner` is refused with a
sentence (the token decides), and the account resolution is skipped. The runner row names the
account label stored with the secret, and the gap is said on the page: "Usage by cloud agents is
not in the Accounts windows yet."

Only the `claude` engine runs remotely in this version. Codex needs its login file copied into
the sandbox, which is a follow-up.

**Adapters** in `lib/runners/`: `base.py` (the interface: `create(spec) -> handle`,
`run(handle) -> iterator of output lines`, `fetch_bundle(handle, base) -> path`,
`delete(handle)`, and `output` = `stream-json` or `text`, which picks the parser in `run.sh`),
then one file per provider. A bundle always leaves the sandbox base64-encoded (DO: written to a
file, then `harness-runtime download`). Each builds argv lists
from the provider's documented CLI (`internal/research/report-hosting-cli.md`); every step the
docs do not show is marked UNVERIFIED in a comment and in the preset's terms.

| Provider | Create | Secrets | Run and stream | Delete |
|---|---|---|---|---|
| Railway | `railway sandbox create --json --env-file <0600 file>` (the default 30 minute idle stop stays: it is Railway's own backstop for a leaked sandbox, and an exec in progress defers it) | the env file, deleted after create | `railway sandbox exec --id ID -- bash -s` with the bootstrap on stdin; streams live (documented) | `railway sandbox destroy ID` |
| Vercel | `sandbox create --name N --vcpus 4 --timeout <lane budget> --non-persistent` | `sandbox copy <0600 file> N:/tmp/agent.env`, sourced and deleted by the bootstrap | `sandbox exec N -- sh -c '...'` (live streaming UNVERIFIED) | `sandbox remove N` |
| DO Managed Agents | `doctl harness-runtime create <spec.yaml> --name N` with `agent: claude-code` | `--secret NAME=@<0600 file>` for both | `doctl harness-runtime prompt N - --on-hitl approve < brief`; output is the adapter's text, so `output = text` and `parse_generic.py` reads it | `doctl harness-runtime remove N` |

Railway is the reference adapter: the only one whose live stream and stdin forwarding are both
documented. DO's `harness-runtime` commands merged into doctl on 2026-09-22 and may be missing
from a released build; `available()` checks `doctl harness-runtime --help` and says so. Whether
DO's `claude-code` adapter accepts `CLAUDE_CODE_OAUTH_TOKEN` instead of an API key is not
documented, so the DO row says it may need DigitalOcean's own inference (billed by DO), and the
page shows that sentence next to its Test.

**Honesty.** Adapters are tested against fake CLIs that mirror the documented shapes. None has
run against a live account. Every runner row carries "not yet run live on this farm" until the
person's first successful Test on that farm clears it; the first live run is an owner ask.

**Runner Test** from the page: creates the smallest sandbox, runs `claude --version` and
`git ls-remote` of the project inside it with the stored secrets, deletes it, reports the
seconds it took. The button says it spends a few cents; the body must carry `confirm: true`.

**Spawning stays a command.** The page shows the `fleet spawn ... --runner <id>` line for a
connected runner; the page does not spawn.

## 6. Skills

Two plugin skills, because the first farm has no dashboard to onboard from:

- **`/murmur:farm`** (`plugin/skills/farm/SKILL.md`, command `plugin/commands/farm.md`, script
  `plugin/scripts/murmur_farm.py`): from a person's laptop, get their first farm. Questions with
  defaults (where: DigitalOcean or a machine you already have; size; region; name), then `plan`
  prints the commands and the cloud-init file, `apply` runs them only when called with the price
  the person typed back, then waits for first boot, adds a `Host <name>` block to the laptop's
  `~/.ssh/config` inside a marked section it owns, and prints the one finish command. The
  provider login is the person's own terminal (`doctl auth init`), never the chat; the skill
  checks it with `doctl account get`.
- **`/murmur:runner`** (`plugin/skills/runner/SKILL.md`, command `plugin/commands/runner.md`):
  connect a runner provider to an existing farm over SSH: install the CLI on the farm, the login
  command, the two secrets with `fleet hosts secret` (the person types them into their own
  terminal; the skill never sees them), the Test, the spawn line.

**One implementation.** `murmur_farm.py` does not render its own cloud-init: it runs the same
`fleet/lib/machines.py` (stdlib only, runnable on its own) through symlinks inside the plugin
directory (`plugin/lib/machines.py`, `plugin/lib/host_presets.py`, `plugin/lib/scrub.py` if
needed), the way PR 36 made `plugin/templates` reach the installed copy. The skills lane extends
`tests/test_plugin_installed_copy.py` so the installed copy runs `murmur_farm.py plan`.

Both skills follow the init skill's rules: never invent an answer, never write a file the
script should write, never take a secret through the conversation, never spend money without the
price typed back.

## 7. Routes

Read, from a snapshot refreshed on its own thread every 45 seconds (no GET runs a tool). The
refresher runs `fleet machines list --json` and `fleet hosts list --json`, each with a 60 second
timeout; a provider check inside them has its own 15 second timeout:

| Route | Answer |
|---|---|
| `GET /api/hosts` | `{at, stale_since, error, pending, providers: [{id, label, job, stage, cli_installed, login_state, account, detail, checked_at, secrets: [{name, stored, account}], tested: {ok, at, seconds, detail} or null, login, install, terms, pricing, sizes, regions}]}` |
| `GET /api/machines` | `{at, stale_since, error, pending, this: {name, address}, total_monthly_usd, machines: [{name, provider, user, address, size, monthly_usd, region, state, detail, checked_at, finish_command, tunnel_command}]}` |

`login_state` is `logged_in`, `logged_out`, `not_installed` or `no_answer`; a slow provider is
never drawn as logged out. `finish_command` is set in `needs-login`, `tunnel_command` in `ready`.

Write, behind the token and the cross-site refusal, each one a `fleet` command run as a job
keyed by its own resource (`machine:<name>` for everything about one machine, so adding a second
machine while the first boots is not refused; `host:<provider>` for a provider):

| Route | Runs |
|---|---|
| `POST /api/machines/plan {provider, name, size, region, ssh_public?}` | `fleet machines plan ... --json`, synchronously; a POST because it asks the provider for the live price, and only a page that can create needs a plan |
| `POST /api/machines {provider: "do-droplet", name, size, region, ssh_public, confirm_usd}` | `fleet machines create ... --confirm-usd N` |
| `POST /api/machines {provider: "ssh", name, target, port?}` | `fleet machines add ...` |
| `POST /api/machines/check {name}` | `fleet machines check N` |
| `POST /api/machines/destroy {name, confirm}` | `fleet machines destroy N --confirm N` (400 unless confirm equals name) |
| `POST /api/machines/adopt {name}` | `fleet machines adopt N` |
| `POST /api/machines/forget {name}` | `fleet machines forget N` |
| `POST /api/hosts/check {provider}` | `fleet hosts check <provider>` |
| `POST /api/hosts/test {provider, project, confirm: true}` | `fleet runner test <provider> --project P` (400 without confirm) |

Every name, size, region, target and port is validated against a strict pattern before any argv
is built; `ssh_public` is written to a 0600 temporary file passed as `--pubkey-file` and deleted
after. Refusals are 400 with a sentence; a second press of a running job is 409 as today. After
any of these jobs ends, the snapshot refreshes at once. Job records are scrubbed (section 3).

## 8. The page

Machine tab gains a **Hosting** section after Services, two tables and two buttons, every cell
one line (the owner's one-line rule):

- **Machines**: Name, Provider, Address, Size and price, State (one pill), Last check, Actions.
  "Add a machine" opens the dialog of section 4. The head says the monthly total. Size and price
  read "4 vCPU, 8 GB, $48 a month", cut with an ellipsis and a title when narrow.
- **Runners**: Provider, CLI (Installed, or a Copy install command button), Login (pill: Logged in,
  Not logged in, Not installed), Secrets ("2 of 2"), Test (pill: Passed, Not tested, Failed;
  "not run live" while untested), Actions (Check, Test, Copy spawn line). "Connect a runner"
  opens a dialog: pick a provider card (terms, stage, price), install the CLI (command), log in
  (command, state flips by itself), store the secrets (one `fleet hosts secret` command per
  name, a state per name), Test (with the cost sentence), the spawn line.

Every control is disabled with the access sentence in read-only; loading, empty, error and ready
states; no em-dash; no emoji.

## 9. Delivery

Five lanes on the farm, disjoint paths, the JSON of section 7 and the commands of sections 4
and 5 as their contract. Four start at once; the skills lane starts when core has merged,
because its script runs core's `machines.py`.

- **hosting-core** (library and CLI): `fleet/lib/host_presets.py`, `fleet/lib/machines.py`, `fleet/lib/scrub.py`,
  `fleet/lib/hosts.py`, `fleet/bin/fleet` (the `machines` and `hosts` subcommands only),
  `farm/install.sh` (`--remote` and the sudo preflight), `fleet/tests/hosting-test.py`,
  `fleet/tests/fakes/core/`, and `.github/workflows/fleet-tests.yml`, where it replaces the
  one-by-one list of python tests with a loop over `fleet/tests/*-test.py`, so the other lanes'
  tests run without touching the workflow.
- **hosting-runners**: `fleet/lib/runners/**`, `fleet/lib/brief_template.md` (the runner paragraph), `fleet/bin/fleet` (cmd_spawn's `--runner`, cmd_kill's runner branch, a new
  `runner` subcommand with `test` and `reap`, and the one line in the sweep that calls reap),
  `fleet/tests/runners-test.py`, `fleet/tests/fakes/runners/`.
- **hosting-server**: `fleet/dashboard/server.py` (snapshot, routes, the job-record scrub),
  `fleet/dashboard/test_server.py`, `fleet/docs/OPERATIONS.md` (routes). Tests use a fake
  `fleet` that prints the section 7 shapes.
- **hosting-ui**: `fleet/dashboard/static/views/hosting.js` (new; `machine.js` gains `export`
  on the helpers it shares, one import, the endpoints in `needs`, and one section call),
  `fleet/dashboard/static/hosting.css`, `fleet/dashboard/index.html` (the stylesheet link),
  `fleet/dashboard/test_stub_server.py`, `fleet/dashboard/test_hostile_hosting.mjs`,
  `fleet/dashboard/test_screens_hosting.mjs`.
- **hosting-skills** (after core): `plugin/skills/farm/**`, `plugin/skills/runner/**`,
  `plugin/commands/farm.md`, `plugin/commands/runner.md`, `plugin/scripts/murmur_farm.py`,
  `plugin/lib/` (symlinks to core's two files), `tests/test_plugin_installed_copy.py`,
  `docs/12-the-machine.md`, `fleet/docs/QUICKSTART.md`, `fleet/docs/sharp-edges.md`,
  `plugin/README.md`.

The conductor writes the one CHANGELOG bullet at assembly.

Acceptance, run end to end by the conductor with fake provider CLIs on a scratch farm (no money
is spent by the build):

1. A person with a DigitalOcean login and no farm runs `/murmur:farm`, answers four questions,
   types the price, and gets a `needs-login` machine and its finish command.
2. On a farm, Machine tab, "Add a machine", a droplet: the row goes creating, preparing,
   needs-login by itself; Check after the finish command turns it ready; Destroy asks for the
   name and the row turns destroyed.
3. "Connect a runner", Vercel: the rows flip by themselves as the fake CLI logs in and the
   secrets are stored; Test passes; the spawn line runs a lane whose log streams from the fake
   sandbox and whose kill deletes it.
4. Nothing asks for a secret on the page or in a chat; no secret appears in a job record, a lane
   log or an argv (tests grep the fakes' recorded argv, `$FLEET_STATE/logs/*` and
   `$FLEET_STATE/jobs/*` for the secret values).
5. Every paid action names its price before it runs and refuses without it.
6. A killed runner lane leaves no sandbox behind: SIGTERM deletes it, and `fleet runner reap`
   deletes one whose lane died hard.

## 10. Out of scope, said once

A farm inside a Railway container (needs a supervisor mode in fleet); the dashboard on Vercel;
a multi-farm console (each machine keeps its own dashboard); spawning from the page; Codex as a
remote engine; Railway cloud agents (they carry subscription logins, which is attractive, but
they are early access, sized by plan and have no idle stop; a follow-up once sandboxes work);
Hetzner and other providers (the `ssh` preset covers any machine you already rent).

## 11. Plan review (PR 35), and what changed

An independent reviewer read this record against the code and returned RED with twenty
findings. Each one and its outcome:

| # | Finding | Outcome |
|---|---|---|
| 1 | a remote agent can print its tokens into the lane log the page serves | accepted: scrub in `run_remote.py`, no `set -x`, acceptance greps logs (sections 3, 9) |
| 2 | `fleet kill` SIGKILLs before cleanup, a sandbox keeps billing | accepted: handle file first, SIGTERM handler, `TimeoutStopSec=120`, `fleet runner reap` on the sweep (section 5) |
| 3 | a droplet can exist with no row | accepted: row before the provider call, reconcile by tag, `unrecorded` state (section 4) |
| 4 | the installer could bind the dashboard to every interface | accepted: cloud-init writes the loopback bind, `--remote` flag, tunnel line (section 4) |
| 5 | a no-sudo user breaks the installer halfway | accepted: `gh` from GitHub's repository in cloud-init, sudo preflight in the installer (section 4) |
| 6 | DO Managed Agents has no documented stream-json | accepted: `prompt` streams text into `parse_generic.py`, said on the row (section 5) |
| 7 | the key classifier refuses a field called `pubkey` | accepted: the field is `ssh_public` (section 3) |
| 8 | a stale preset price would still pass the confirm | accepted: live price from `doctl compute size list`, refuse on mismatch (section 4) |
| 9 | fetching into a checked-out branch is refused | accepted: fetch then `merge --ff-only` (section 5) |
| 10 | remote commits are unattributed and bypass the claims guard | accepted: identity set in the sandbox, read-only token, the farm pushes (sections 3, 5) |
| 11 | salvage protects an empty worktree | accepted: the work comes home as a bundle on every result (section 5) |
| 12 | the plugin's copy may not follow symlinks | rejected with evidence: installing murmur into a scratch Claude Code config from a git clone produced a real `templates` directory in the cache, and PR 36 now tests that shape on every change |
| 13 | ship Railway cloud agents first, they carry the subscription | rejected: `CLAUDE_CODE_OAUTH_TOKEN` is Claude Code's own documented headless login, so the Railway and Vercel sandboxes carry the subscription too; only DO's adapter is unverified, and the page says so. Cloud agents stay a follow-up (no idle stop, early access) |
| 14 | remote usage is invisible to the Accounts windows | accepted: `--runner` with `--account` refused, account label on the secret, the gap said on the page (section 5) |
| 15 | job records can keep a token from a CLI's error | accepted: job output scrubbed (section 7) |
| 16 | the atomic writer is private to `models.py` | accepted differently: `machines.py` carries its own ten lines, because it must run alone in the plugin (section 4) |
| 17 | the workflow, the fakes and the changelog have no owner | accepted: core owns the workflow and turns it into a glob; fakes split per lane; the conductor writes the changelog (section 9) |
| 18 | a slow provider would read as logged out | accepted: `login_state` with `no_answer`, 15 second check timeout (section 7) |
| 19 | one job key for all machines refuses a second machine | accepted: keyed by machine name (section 7) |
| 20 | cut two adapters, the plan route and forget; add an install button and a total | partly: the owner named all three providers, so three adapters stay; plan stays as a POST because it reads the live price; forget stays for own machines and `unrecorded` rows; the total and the billing sentence on every pill are added; the install button is not, because installing a provider CLI needs sudo or npm on most farms, and a copied command with a state that flips is the pattern of the rest of the tab |

**Second round.** A second reviewer read the rewrite and returned RED with twelve more. All
accepted, and folded into sections 3 to 9 above: the farm opens the pull request from
`/tmp/fleet-pr.md` (1); work comes home every five minutes when HEAD moves, dirty trees are
committed at exit, empty ranges are skipped, bundles travel base64, the clone is partial (2);
`tee` and the parser ignore TERM, a closed stdout does not stop the delete, kill marks first and
stops without blocking (3); the reaper skips a stop in progress, brings work home first, and
`--runner` needs the sweep on (4); Railway keeps its idle stop (5); exact token patterns in one
core-owned `scrub.py`, stderr scrubbed, no partial messages, the server scrubs errors too (6);
the loopback line is written as the user, not by `write_files` (7); `flock` on the registry,
vanished droplets become destroyed, a live name is refused, no SSH to ready machines, stale host
keys removed, a fleet-owned machines key (8); a per-farm tag, Adopt instead of Forget on
`unrecorded` (9); the person's public key is required from the page (10); DO runs the bootstrap
through `exec` before `prompt` (11); the account check comes before the account default, and
the stale text is gone (12).

