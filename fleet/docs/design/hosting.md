# Hosting: where a farm runs

This design record explains where a murmur farm can run, and why that part of murmur works the
way it does. A farm is an always-on Linux machine that runs your agents: it holds their git
worktrees, their processes and the dashboard. The code is `fleet/lib/host_presets.py`,
`fleet/lib/machines.py`, `fleet/lib/hosts.py`, the hosting routes of
`fleet/dashboard/server.py`, and the Hosting section of the dashboard's Machine tab
(`fleet/dashboard/static/views/hosting.js`). The flow that creates your first farm from your
laptop has its own record: [one-click-farm.md](one-click-farm.md).

## 1. Two kinds of machine

A farm needs systemd user services, tmux, git worktrees, the dashboard and the installer, as
they are. So a place to run a farm must be a whole Linux machine. murmur calls it a machine and
supports two kinds:

- **Your own machine**: any Linux box you already reach over SSH, such as a spare PC, WSL2, a
  rented server or a company VM. murmur registers it and checks it. It buys nothing.
- **A DigitalOcean Droplet**: a cloud server that murmur creates, prices and destroys with
  DigitalOcean's command-line tool, `doctl`.

Each farm keeps its own dashboard. The Hosting section shows the other machines this farm owns
and what they cost. It is not a console for many farms.

Other providers can be added as a contribution: see [CONTRIBUTING.md](../../../CONTRIBUTING.md).

## 2. Providers (presets)

Each kind of machine is one preset: one dict in `fleet/lib/host_presets.py`, the same pattern as
the model presets. Every preset carries every field, so no reader has to guess:

| Field | What it holds |
|---|---|
| `id` | the preset's name, and the provider name on every command line |
| `label`, `summary` | the name and the one-line description the page shows |
| `color` | the provider's colour |
| `job` | `machine`: a whole farm |
| `cli`, `install` | the command-line tool this farm calls, and how to install it |
| `login` | the login command you run in your own terminal |
| `whoami` | the read-only login check, as an argument list |
| `docs`, `terms` | where the vendor documents the tool, and one sentence on what you agree to |
| `stage` | `ga`, `preview` or `early access` |
| `pricing` | one sentence you can read before you spend |
| `sizes`, `regions` | what can be bought, and where; the first region is the default |
| `engines` | the agent engines the machine can run |

The two presets:

| `id` | Label | Tool | Login | Login check |
|---|---|---|---|---|
| `ssh` | Your own machine | `ssh` | none: there is no account to log in to | none: `fleet hosts` only checks that `ssh` is installed, and `fleet machines check` checks each machine |
| `do-droplet` | DigitalOcean Droplet | `doctl` | `doctl auth init --context murmur` | `doctl account get -o json --context murmur` |

Both are at stage `ga`, and both run the `claude` and `codex` engines.

**The doctl context.** doctl keeps each login in a named context. Every doctl call this farm
makes names the `murmur` context, the one the login command creates. A farm that keeps its
DigitalOcean login in another context sets `FLEET_DOCTL_CONTEXT`; an empty value means doctl's
default context. The reason: a call that creates something must land in the account you logged
in with. A firewall made in another account would leave the new droplet without one.

**Droplet sizes.** The default size is `s-4vcpu-8gb`.

| Size | vCPU | Memory | Disk | List price |
|---|---|---|---|---|
| `s-2vcpu-4gb` | 2 | 4 GB | 80 GB | $24 a month |
| `s-4vcpu-8gb` | 4 | 8 GB | 160 GB | $48 a month |
| `s-8vcpu-16gb` | 8 | 16 GB | 320 GB | $96 a month |

These are DigitalOcean's list prices on 2026-09-23, the date that `PRICED_ON` in
`host_presets.py` records. Prices change, so murmur buys only at the live price (section 4).

**Regions.** `fra1` (the default), `ams3`, `lon1`, `nyc3`, `sfo3`, `sgp1`, `tor1`, `blr1` and
`syd1`. DigitalOcean has more. A region that is not on this list is refused, not passed on
unchecked. Every droplet runs Ubuntu 24.04 (the image `ubuntu-24-04-x64`).

**What the preset tells you before you spend.** The `pricing` sentence says that a droplet is
billed until you destroy it, and that powering it off does not stop the bill. The `install`
field sends you to DigitalOcean's install page for doctl, rather than naming a package that may
be wrong on your system.

## 3. Credentials never go through the page

The dashboard is a web page. A token typed into it would pass through the browser, perhaps a
proxy, the server's memory and its logs. So no credential goes through the page, and text that a
tool prints is cleaned before anyone reads it. `fleet/lib/hosts.py` follows the same rule: it
only looks, and it never logs in.

- **You log in to a provider with the provider's own tool, in a terminal.** For a droplet, the
  page shows `ssh -t <farm> doctl auth init --context murmur`. Then it watches the login state
  flip from "Not logged in" to "Logged in" by itself. The dialog asks the farm every three
  seconds, and the farm checks the provider every 45 seconds.
- **A slow provider is not a logged-out provider.** A check that does not answer within 15
  seconds is `no_answer`, never `logged_out`. A person told "not logged in" logs in again, and may
  end up pasting a token where it does not belong. A provider tool too old to know the check's
  command is `not_installed`, with a sentence that says so.
- **Your SSH public key is not a secret**, so the page may take it: it is how your laptop reaches
  a new droplet. Its field is called `ssh_public`, because the server refuses any field whose name
  contains "key", "secret", "token", "credential" or "password". The value must be one line of an
  OpenSSH public key: `ssh-ed25519`, `ssh-rsa`, or `ecdsa-sha2-nistp256`, `-nistp384` or
  `-nistp521`. The page refuses a value shaped like a token before it sends anything.
- **Any other field that looks like a credential is refused** with one sentence: "A token never
  goes through this page. Run the login command in a terminal on this farm." The refusal repeats
  neither the field's name nor its value.
- **Printed text is scrubbed.** `fleet/lib/scrub.py` replaces the exact token shapes of Anthropic
  keys (`sk-ant-...`), GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`) and
  DigitalOcean tokens (`dop_v1_...`). It has no rule for "long random strings", because such a
  rule would also remove every commit SHA. The sentences `hosts.py` and `machines.py` keep from a
  provider tool's output pass through it. So do the listings the dashboard reads, and every job
  record the dashboard writes.

## 4. Machines

**The registry.** This farm's machines are listed in `$FLEET_CONFIG/machines.toml` (by default
`~/.config/fleet/machines.toml`), one table per machine. The fields are `name`, `provider`,
`user`, `address`, `port`, `size`, `monthly_usd`, `region`, `provider_id`, `created_at`, `state`,
`detail` and `checked_at`. The farm you run the command on is always shown first, and it is not
in the file. Each write replaces the whole file in one step, with mode 0600, so a write that does
not finish leaves the old file whole. `machines.py` has its own small TOML writer instead of
importing `models.py`, because it must also run alone inside the plugin (section 6).

**States.**

| State | Meaning |
|---|---|
| `creating` | DigitalOcean is building the droplet |
| `preparing` | the first boot (cloud-init) is installing packages |
| `needs-login` | prepared; your logins and the installer are left (see the finish command below) |
| `ready` | the farm answers `fleet capacity` over SSH |
| `unreachable` | SSH did not answer |
| `failed` | a step before the purchase failed, so no droplet was asked for |
| `destroyed` | the droplet is deleted and its billing has stopped |
| `unrecorded` | DigitalOcean lists a droplet with this farm's tag, and the registry has no row for it |

A droplet costs money in every state except `destroyed`, and except a `failed` row that never
got a droplet id. Each such row says so on its state pill, with the price. The section head gives
the total, for example "You pay $96 a month for 2 machines."

**The farm id.** Each farm makes an id once and keeps it in `$FLEET_CONFIG/farm-id`: a word and
four hex digits, such as `heron-3fa2`. Every droplet the farm creates carries the tag
`murmur-by-<farm id>`, and the farm reconciles only droplets with that tag. So two farms on one
DigitalOcean account never adopt or destroy each other's droplets.

**No droplet costs money unseen.** `fleet machines create` works in this order:

1. It refuses unless the price you confirmed equals DigitalOcean's live price. With no live price
   (doctl not logged in, or no answer), it buys nothing.
2. It refuses a name that already has a live row. So a retry after a timeout never buys a second
   droplet.
3. It looks for a droplet with this name on this farm's tag. Exactly one is adopted, not bought
   again. More than one, or a listing that fails, stops the run.
4. Under the registry lock, it writes the row as `creating`, with the exact name.
5. It imports this farm's machines key and checks the firewall (below). If either step fails, the
   row becomes `failed`, and no droplet was asked for.
6. It asks DigitalOcean for the droplet, without waiting for it to be built, and records its id.

The create call has no `--wait`:

```text
doctl compute droplet create <name> --image ubuntu-24-04-x64 --size <size> --region <region>
  --tag-names murmur-farm,murmur-by-<farm id> --ssh-keys <key id>
  --user-data-file <cloud-init file> -o json --context murmur
```

DigitalOcean's answer to step 6 can be lost (a timeout or an error), and the droplet may exist
anyway. So such a row stays `creating` with no id, which means pending, never failed.
`fleet machines list` adopts the droplet when it appears on the tag. After ten minutes without
it, the row says so, and nothing is bought again on its own: `fleet machines forget-attempt
<name>` drops the row, and a new create needs the price confirmed again. `forget-attempt` is
refused inside those ten minutes, and it adopts the droplet instead if it did appear.

**Reconciling with DigitalOcean.** `fleet machines list` reads `doctl compute droplet list
--tag-name murmur-by-<farm id> -o json`. It does so when doctl is installed and this farm has a
farm id or a droplet row. A droplet on the tag with no row is shown as `unrecorded`, with Adopt
and Destroy. A row with no droplet id picks its id up by name. A row whose droplet DigitalOcean
no longer lists becomes `destroyed`.

**One writer at a time.** The dashboard's refresher and the per-machine jobs all read, change
and rewrite `machines.toml`. So every read-modify-write holds an `flock` on
`machines.toml.lock`, and no provider call or SSH runs while the lock is held. A step's answer is
written only if the row is still in the state the step started from. So a Destroy during a slow
SSH check is never undone.

**Nothing waits inside a request.** `create` returns once DigitalOcean has the order. Then
`fleet machines list` moves each row one short step per pass:

1. `creating` to `preparing`: `doctl compute droplet get` finds the address.
2. `preparing` to `needs-login`: `cloud-init status` over SSH, without `--wait`, says `done`.
3. `needs-login` to `ready`: `bash -lc 'fleet capacity'` over SSH answers.

Machines are stepped in parallel, and each answer is written as soon as it comes. So a dashboard
restart, a timed-out `doctl` or a dropped connection loses nothing: the next pass carries on
from the row. `list` never connects to a `ready` machine; Check does.

**The price is live.** `fleet machines plan` reads `price_monthly` from `doctl compute size list
-o json` when doctl answers. Otherwise it shows the preset's price, labelled "list price on
2026-09-23". `create` never buys on a list price. The reason: a stale number is how a person
confirms $48 and pays $52.

**What a new droplet gets.** `cloud_init()` in `machines.py` writes the droplet's whole first
boot, and nothing else writes it:

- A user `farm` without sudo, so nothing that runs as that user can change the system. Its SSH
  keys are this farm's machines key and your public key. The machines key belongs to the
  fleet, at `$FLEET_STATE/machines/id_ed25519`, and is made once; your `~/.ssh` is never touched.
  Your public key is required to create a droplet, because the finish command and the tunnel
  both run from your laptop.
- SSH for root with a key only, for administration. No password opens the box.
- The packages `git`, `tmux`, `python3`, `curl` and `ca-certificates`, and `gh` from GitHub's own
  apt repository, added the same way `farm/install.sh` adds it. So the installer finds everything
  it needs and never asks for sudo.
- `FLEET_DASH_BIND=127.0.0.1` in the farm user's `~/.config/fleet/env`, written before the
  installer runs, so the dashboard listens on loopback only. A `runcmd` line writes it as that
  user. `write_files` would not do: it runs before the user exists, and it would leave root
  owning the user's home.
- `loginctl enable-linger farm`, so the farm's services keep running after you log out.
- Two tags and no others: `murmur-farm`, which the firewall attaches by, and
  `murmur-by-<farm id>`. Any other tag would be one more way for a firewall this farm does not
  own to cover the droplet.

`/murmur:farm` can add two things to the first boot: the Tailscale package with one root helper,
and Node.js with npm for Codex. See [one-click-farm.md](one-click-farm.md).

**The firewall.** Every droplet sits behind the firewall `murmur-ssh-only`, attached by the tag
`murmur-farm`:

- Inbound: tcp 22 from `0.0.0.0/0` and `::/0`, and nothing else. Your laptop's address is not
  known and it changes, so SSH must come in from anywhere. Your key keeps everyone else out.
- Outbound: tcp and udp on every port, and icmp, to `0.0.0.0/0` and `::/0`. A DigitalOcean
  firewall lets nothing out that no outbound rule allows, and a farm must reach packages, GitHub,
  Tailscale and the model providers.

The firewall is checked, never trusted by its name. Before every create:

1. The `murmur-farm` tag is created first, because the firewall commands accept only tags that
   exist.
2. Every firewall in the account is listed. The create stops, and names them, when another
   firewall would also cover the new droplet (by one of its two tags, or by naming this farm's
   droplets by id), or when two firewalls are called `murmur-ssh-only`. DigitalOcean adds up the
   allow rules of every firewall over a droplet, so `murmur-ssh-only` alone would not decide what
   reaches the farm. murmur never edits or detaches a firewall it does not own: you decide.
3. A `murmur-ssh-only` that differs from the rules above in any way is rewritten to them: another
   inbound rule, SSH from narrower sources, missing or narrower outbound rules, a deny rule,
   another tag, or no tag. Then it is read back until DigitalOcean reports its status as
   `succeeded` (up to six reads, five seconds apart). If it is still wrong, nothing is created.

The dashboard stays on loopback. So a new farm is reachable only with the SSH keys it was given.

**Finishing a droplet.** cloud-init does not run the installer. The installer needs your GitHub
login: the farm clones murmur with it, and later opens pull requests with it. After the install
you also log in to Claude. Only you can make those logins. So in `needs-login` the machine row
shows one command to run from your laptop:

```bash
ssh -t farm@<address> 'gh auth login && gh repo clone magik-ai/murmur ~/work/murmur -- -q && bash ~/work/murmur/farm/install.sh --remote'
```

`--remote` tells the installer that this box is driven from a laptop. It leaves the dashboard
bind as it is (loopback), does not offer Tailscale, and ends by printing the SSH tunnel to the
dashboard. The installer also stops before it changes anything on a box where it cannot install
packages: it names every missing package and the command an administrator runs. Then Check, or
the next `fleet machines list`, turns the row `ready`, and the row shows the tunnel:

```bash
ssh -N -L 7878:127.0.0.1:7878 farm@<address>
```

**Your own machine.** `fleet machines add --name <name> --target user@host [--port <port>]`
registers the machine and checks it over SSH. Nothing is bought, and nothing is copied to the
machine, so it must already accept this farm's machines key. If SSH works and the fleet is not
installed yet, the row is `needs-login` and shows the finish command. With `--port`, the finish
and tunnel commands carry `-p <port>`. Forget drops the row. Destroy is refused, because this farm
did not buy the machine.

**Commands.** The page, the skill and the terminal run the same code:

| Command | Does |
|---|---|
| `fleet machines list [--json]` | the registry, reconciled with DigitalOcean, each row moved one step |
| `fleet machines plan --provider do-droplet --name N [--size S] [--region R] [--pubkey-file F] [--json]` | prints the commands, the cloud-init file and the live price; buys nothing |
| `fleet machines create --provider do-droplet --name N [--size S] [--region R] --pubkey-file F --confirm-usd <price> [--wait-pending <seconds>]` | buys a droplet in the order above, or adopts the one already on the tag; exits 3 when DigitalOcean's answer was lost and the row is pending |
| `fleet machines add --name N --target user@host [--port P]` | registers a machine of your own and checks it |
| `fleet machines check N` | SSH; `cloud-init status` for a droplet still in its first boot; then `fleet capacity`; updates the state |
| `fleet machines adopt N` | writes the row of an `unrecorded` droplet from DigitalOcean's own facts |
| `fleet machines destroy N --confirm N` | `doctl compute droplet delete <id> --force`; the row becomes `destroyed` |
| `fleet machines forget N` | drops a `destroyed` row, a `failed` row with no droplet id, or a machine of your own; destroys nothing |
| `fleet machines forget-attempt N` | drops a pending create whose droplet never appeared |

The size defaults to `s-4vcpu-8gb` and the region to `fra1`.

**SSH from this farm.** Every SSH that `machines.py` makes uses the machines key, `BatchMode=yes`,
`ConnectTimeout=5`, and `StrictHostKeyChecking=accept-new` with a known-hosts file of the fleet's
own (`$FLEET_STATE/machines/known_hosts`). The port is always on the command line: 22 when the
row names none. The whole call is cut off after 15 seconds. So a check never hangs on a prompt,
and it never edits your `~/.ssh`. When an address is recorded, `ssh-keygen -R <address>` runs on
that file first: DigitalOcean reuses addresses, and `accept-new` refuses a host key that changed.

## 5. The page

The Machine tab has a **Hosting** section after Services. Its head says "Where farms run: your
own machine over SSH, or a DigitalOcean Droplet.", shows the monthly total, and has an "Add a
machine" button. Under it is the Machines table.

**The Machines table** has seven columns, one line per cell: Name, Provider, Address, Size and
price, State, Last check, and Actions. This farm is always the first row, marked "This farm" and
"Not billed here". Size and price reads like "4 vCPU, 8 GB, $48 a month". The state is one pill.
Its tooltip gives the row's detail and, for a droplet that bills, "Still billed: $48 a month. You
are billed until you destroy it. Powering it off does not stop the bill."

The actions depend on the state:

- **Finish** (`needs-login`) copies the finish command.
- **Tunnel** (`ready`) copies the tunnel command.
- **Check** (every state but `destroyed` and `unrecorded`) runs `fleet machines check`.
- **Adopt** (`unrecorded`) writes the row.
- **Forget** appears only where there is nothing left to destroy: a destroyed droplet, a machine
  of your own, or a failed row with no droplet id.
- **Destroy** (every droplet not yet destroyed, `unrecorded` included) opens a confirmation. It
  names the droplet, says that the disk is deleted and the bill stops, and stays off until you
  type the name.

**The total** reads "You pay $96 a month for 2 machines." and counts only the rows that bill.
With none, it reads "Nothing on this list is billed." It appears only after the farm has
answered, and it adds "Not refreshed since ..." when the list is old. A head that said "nothing
is billed" over a list it could not read would be the one sentence on this page that costs you
money.

**Add a machine** opens a dialog of five numbered steps:

1. **Where it runs**: a card for each provider, with its summary. Its price line and terms show
   once you pick it.
2. **What it is**. For a droplet: a name, a size (a card each, with vCPU, memory, disk and the
   monthly price), a region, and your SSH public key. For your own machine: a name, `user@host`
   and a port.
3. **Log in**. For a droplet: where to get doctl if it is missing, and the login command, with a
   state that flips by itself. Your own machine needs no provider login.
4. **Review**. For a droplet, "Show me" asks for a plan: the exact commands, the cloud-init file
   and the live price, read-only and copyable. For your own machine, it shows the one
   `fleet machines add` command. Nothing is bought.
5. **Create it**. The button names the price: "Create, $48 a month until you destroy it". A
   confirmation asks again, and "Create, $48 a month" runs `fleet machines create ...
   --confirm-usd 48` as a job. The row appears in `creating`, the dialog closes when the job
   ends, and the table takes over. For your own machine this step is **Add and check**.

In a read-only dashboard every control is off, and says why.

## 6. From a laptop: `/murmur:farm`

Your first farm has no dashboard to add a machine from. So the plugin has a skill,
`/murmur:farm`, that creates a droplet from your laptop, installs murmur on it and opens its
dashboard. It is `plugin/skills/farm/SKILL.md`, with the command `plugin/commands/farm.md` and
the script `plugin/scripts/murmur_farm.py`. Its design is in
[one-click-farm.md](one-click-farm.md).

There is one implementation. The script does not write its own cloud-init or keep its own
registry: it runs `fleet/lib/machines.py` through the symlinks in `plugin/lib/` (`machines.py`,
`host_presets.py` and `scrub.py`). `machines.py` imports nothing of the fleet but
`host_presets.py`, and it uses `scrub.py` only when it is there.
`tests/test_plugin_installed_copy.py` checks that an installed copy of the plugin runs
`murmur_farm.py plan`.

## 7. Routes

**Reads** come from memory. A thread refreshes two snapshots every 45 seconds, and no GET runs a
tool: both listings reach DigitalOcean or SSH, and the page redraws every few seconds. The thread
runs `fleet machines list --json` and `fleet hosts list --json`, each with a 60-second timeout.
Inside `hosts list`, each provider check has 15 seconds of its own (`FLEET_WHOAMI_TIMEOUT`
changes it), and the providers are checked in parallel. The two answers are kept apart, each with
its own `at`, `stale_since` and `error`. A failed listing keeps its last good answer and says
since when it is old. So an expired login never costs the page its machine table.

| Route | Answer |
|---|---|
| `GET /api/machines` | `{at, stale_since, error, pending, this: {name, address}, total_monthly_usd, machines: [...], provider_error}` |
| `GET /api/hosts` | `{at, stale_since, error, pending, providers: [...]}` |

`pending` is true until the first pass has run. `error` is the refresher's sentence when a
listing failed.

A machine row carries `name`, `provider`, `user`, `address`, `size`, `monthly_usd`, `region`,
`provider_id`, `state`, `detail`, `checked_at`, `finish_command` and `tunnel_command`: the fields
the page reads. `machines.py` also passes on the registry's `port` and `created_at`.
`finish_command` is set only in `needs-login`, and `tunnel_command` only in `ready`. On every row
that bills, `detail` ends with the price sentence.

`fleet machines list --json` itself prints `{this, total_monthly_usd, machines, error}`. There,
`error` says that DigitalOcean was not asked or did not answer, so the rows are the registry's
word alone. The dashboard passes it on as `provider_error` (its own `error` is the refresher's),
and the machines card says it above the rows.

A provider row carries `id`, `label`, `summary`, `color`, `job`, `stage`, `cli`,
`cli_installed`, `login_state`, `account`, `detail`, `checked_at`, `login`, `install`, `terms`,
`pricing`, `sizes`, `regions`, `engines` and `docs`. Each size carries `slug`, `label`, `vcpu`,
`ram_gb`, `disk_gb`, `monthly_usd` and `default`, which is true on exactly one size.
`login_state` is `logged_in`, `logged_out`, `not_installed` or `no_answer`.

**Writes** need the write token and pass the cross-site check. Each one runs one `fleet` command
as a job, keyed by the resource it touches: `machine:<name>` for everything about one machine,
and `host:<provider>` for a provider. So you can add a second machine while the first one boots,
but a second press on the same machine while its job runs gets a 409. When a job ends, the
snapshots refresh at once.

| Route | Runs |
|---|---|
| `POST /api/machines/plan {provider, name, size, region, ssh_public?}` | `fleet machines plan ... --json` at once, and returns its JSON as the CLI printed it. It is a POST because it asks DigitalOcean for the live price. |
| `POST /api/machines {provider: "do-droplet", name, size, region, ssh_public, confirm_usd}` | `fleet machines create ... --pubkey-file <file> --confirm-usd <price>` |
| `POST /api/machines {provider: "ssh", name, target, port?}` | `fleet machines add ...` |
| `POST /api/machines/check {name}` | `fleet machines check <name>` |
| `POST /api/machines/destroy {name, confirm}` | `fleet machines destroy <name> --confirm <name>`; 400 unless `confirm` equals `name` |
| `POST /api/machines/adopt {name}` | `fleet machines adopt <name>` |
| `POST /api/machines/forget {name}` | `fleet machines forget <name>` |
| `POST /api/hosts/check {provider}` | `fleet hosts check <provider>` |

Every provider, name, size, region, target, port and price is checked against a strict pattern
before any argument list is built, and none may start with `-`. A provider must be `ssh`,
`do-droplet`, or one the last `fleet hosts list` reported, and a machine route also needs its job
to be `machine`. `ssh_public` is written to a temporary file with mode 0600, passed as
`--pubkey-file`, and deleted when the job ends. A refusal is a 400 with one sentence. Job records
are scrubbed (section 3).

## 8. Out of scope

- A console for many farms: each farm keeps its own dashboard.
- Spawning agents from the Hosting section.
- Installing a provider's tool from the page. The page says how to install it and watches the
  state flip, as the rest of the Machine tab does.
