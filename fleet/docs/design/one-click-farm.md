# One-click farm

Status: design, for review before code. Owner ask of 2026-09-24: "a farm in the cloud in one click",
and move the owner's own farm onto the result so it is tested for real.

## In short

A person with a laptop, Claude Code and a DigitalOcean account types `/murmur:farm`, answers a
few questions, types back one price, and a few minutes later has a working farm: a droplet with
murmur installed, the dashboard running as a service, and the dashboard open in their browser
through a private tunnel. Nothing listens on the internet but ssh. The same command then moves
the owner's farm off the home PC.

`fleet/docs/design/hosting.md` section 6 already specifies `/murmur:farm` (questions, `plan`,
`apply` with the typed price, the ssh config block, the finish command, reuse of
`fleet/lib/machines.py` through `plugin/lib` symlinks). None of it was built. This record adds
what that design leaves manual, and changes nothing it decided.

## What exists and what is missing

| Piece | Exists | Missing for one click |
|---|---|---|
| Droplet, firewall, cloud-init | `fleet/lib/machines.py` create (:885), `cloud_init()` (:448), ssh-only firewall (:513) | runs from a farm today; untested on macOS |
| Install on the box | `farm/install.sh --remote` | asks questions; needs `gh` login first |
| Finish | `finish_command` (:606), copied by hand | a person pastes it and answers prompts |
| Dashboard | `fleet dashboard start` in tmux (`run.sh` :118) | no systemd unit in the repo, dies on reboot |
| Private access | `tunnel_command` (:613) | nothing opens it; token read by hand |
| Laptop entry | none | `/murmur:farm` (hosting.md section 6) |
| doctl, ssh key | preset links to docs | nothing installs doctl or makes a key |

## The flow

One skill, one script (`plugin/scripts/murmur_farm.py`), the steps in order. Every step is
idempotent, so a person who stops can run `/murmur:farm` again and it resumes. Two rules hold
across all of them:

- **Nothing interactive runs inside the skill.** Claude Code's tools have no terminal, so every
  login (doctl, GitHub on the box, Claude, Codex) is a command the person runs in their own
  terminal; the script prints it, then verifies the result without a terminal and waits.
- **A purchase is never repeated.** The laptop has one farm id, the creator's own
  (`$FLEET_CONFIG/farm-id`, by default `~/.config/fleet/farm-id`, `machines.py` :61): the script
  keeps no id of its own and asks `machines.py` for it, so plan, create and resume all use the
  same per-farm tag `murmur-by-<farm id>` (`machines.py` :267, :540). Before any create, the script reconciles by that tag and the name:
  exactly one match is adopted, never bought again; more than one stops with the list. A create
  whose answer was lost (a timeout, a non-zero exit) is not failed but **unknown**: the row stays
  pending, the script polls the tagged list for up to ten minutes, and adopts the droplet if it
  appears. If it never appears, no new create runs on its own: the person runs
  `/murmur:farm forget-attempt` and types the price again. A typed price is good for one create
  attempt only.

1. **Preflight on the laptop.**
   - `doctl` present, else on macOS `brew install doctl` (asked first), else the install link.
   - A doctl context named `murmur` answers `doctl account get --context murmur`. If not, the
     skill prints `doctl auth init --context murmur` for the person to run in their own
     terminal and waits; the token never passes through the chat. The skill never switches the
     person's current doctl context (the owner keeps his company account as the default).
   - An ssh key: `~/.ssh/id_ed25519.pub`, else offer `ssh-keygen -t ed25519` (asked first).
     The skill's ssh runs have no terminal, so the key must work without one: either it has no
     passphrase (`ssh-keygen -y -P '' -f <key>` succeeds; its output, the public key, is
     discarded) or the agent holds it (`ssh-add -L` lists that public key). If neither, the skill
     prints `ssh-add --apple-use-keychain <key>` on macOS or `ssh-add <key>` elsewhere for the
     person's own terminal, and waits; the passphrase never reaches the chat, an argv or a log.
     This is checked before any purchase, and again after boot: `ssh -o BatchMode=yes <name>
     true` must succeed before any remote step runs.
   - `gh auth status` on the laptop (the box will need its own login; this one only checks the
     person has GitHub at all).
2. **Questions with defaults** (hosting.md section 6): where (DigitalOcean), name (`farm`),
   size (the preset's live sizes, default 4 vCPU 8 GB; 2 vCPU 4 GB is offered with the warning
   that it runs one or two agents at a time), region (nearest by the laptop's
   timezone, else fra1), and access (ssh tunnel, or Tailscale, see below).
3. **Plan.** Print the doctl commands, the cloud-init file and the price in words: "Create farm,
   $48 a month until you destroy it". Nothing is created.
4. **Apply** only with the price typed back (the existing `--confirm-usd` rule), after the
   reconcile above. The firewall is checked, not trusted by name: `murmur-ssh-only` must allow
   inbound tcp 22 only and carry the `murmur-farm` tag; a firewall by that name with any other
   rule or without the tag is corrected, and if it cannot be, nothing is created
   (`ensure_firewall` today returns on the name alone, `machines.py` :501). Then wait for the
   droplet to be active and cloud-init to finish (`machines.py` list states).
5. **ssh config.** A `Host <name>` block inside a marked section of `~/.ssh/config` that the
   script owns (hosting.md section 6), user `farm`, the key from step 1. The droplet is new, so
   its host key is unknown to the laptop, and a batch probe cannot answer the trust question
   ssh asks by default. So every ssh the script runs or prints for this farm carries
   `-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=<laptop home>/.config/murmur/known_hosts`
   on its command line, written out in full, where it wins over any config file, including
   an earlier `Host *` that says `StrictHostKeyChecking no` (the block repeats the two lines for
   the person's own use, but nothing relies on it). The first connection, minutes after the
   script itself created that address, records the key, and any later change of key is
   refused. Before the first remote command, `ssh -G` with those same options must report
   `accept-new` and that file. The script creates `~/.config/murmur` with mode 0700 at the
   preflight, before any probe (ssh creates only `~/.ssh` on its own, and a known-hosts file it
   cannot open is a warning, not an error; the control socket of step 8 lives there too). After
   the first probe, `ssh-keygen -F <address> -f <that file>` must find the droplet's key, or
   the run stops: a probe that passed without pinning a key proves nothing. The creator's own
   readiness check keeps its separate known-hosts file (`machines.py` :389), so the script
   primes this one with its own first probe. ssh takes the first
   value it meets, so a name the person's config already answers would send the login and the
   install to the old machine, or take the old name over while that machine still works. So
   the name is checked at the questions (step 2): `ssh -G <name>` must resolve to the bare name
   with no host of its own, or to this script's own section; any other answer asks for a
   different name. After writing the block, `ssh -G <name>` must resolve to the droplet's
   address and user `farm` before any remote command runs.
6. **Finish in two sessions.** First the person runs `ssh -t <name> gh auth login` in their
   own terminal (the script prints it; it cannot run it: no terminal, and the helper sends
   stdin to /dev/null, `machines.py` :343). The script verifies with `ssh <name> gh auth status`
   and only then runs the clone and `install.sh --remote --yes` in a second, non-interactive
   session. `--yes` must stop asking: the head office repo (or `--hq-repo`), the codename and
   the alias take defaults, the single-machine question is skipped under `--remote`.
7. **Dashboard as a service.** The installer installs and enables a user unit
   `fleet-dashboard.service` (new, in `fleet/systemd/`), with linger already on from cloud-init.
   Like the other farm units it has `Restart=always` and `RestartSec=5` (`fleet-daemon.service`),
   plus `StartLimitIntervalSec=0` so retries never run out: after a reboot the user manager can
   start it before Tailscale has an address, the server refuses and exits, and systemd tries
   again every five seconds until the address is there. `fleet dashboard start` keeps working
   and starts the unit.
8. **Open it.** Tunnel mode: ssh itself is the supervisor, through its control socket, so the
   skill can return while the tunnel lives on. `/murmur:farm open` runs
   `ssh -f -N -M -S ~/.config/murmur/<name>.sock -o ExitOnForwardFailure=yes
   -o ServerAliveInterval=30 -L 127.0.0.1:<port>:127.0.0.1:7878 <name>`, the laptop end bound to
   loopback by name, because a `GatewayPorts yes` in the person's ssh config would otherwise
   listen on every interface and hand the laptop's network the page's tokenless reads
   (`server.py` :4181). After start, the listener is checked to be on `127.0.0.1` only
   (`lsof -iTCP:<port> -sTCP:LISTEN`), and the tunnel is closed if it is not. `-f` goes to the background only
   after the forward is bound, so a port that cannot bind is a clear error, not a silent tunnel.
   The port (7878, or a free one if that is taken) is written next to the socket in
   `~/.config/murmur/<name>.tunnel`, then a health check asks the page. Before starting,
   `ssh -S <sock> -O check <name>` says whether a tunnel already lives: if it does and the page
   answers, `open` only opens the browser; if it is dead (a sleep, a dropped network), the stale
   socket is removed and a fresh tunnel starts. `/murmur:farm open --stop` runs
   `ssh -S <sock> -O exit <name>` and removes both files. Tailscale mode: no tunnel, the page is at `http://<tailnet address>:7878`. Either way the token reaches the
   browser without an argv or a log: the script reads it over ssh into memory, writes a
   one-shot local file (mode 0600, deleted after the browser loads it) that navigates to the
   page with the token in the fragment (`#token=`), and opens that file's path. The page
   accepts `#token=` as it accepts `?token=` today and strips it at once (`api.js` :14); a
   fragment never reaches the server, and the server stops writing query strings into its
   failure log (`server.py` :4212 logs `self.path`). `/murmur:farm open` reopens it later.
9. **The logins only the person can do**, each printed as a command for their own terminal and
   then verified by the script without a terminal. Two rules for every remote command, printed
   or run: ssh runs it with `bash -c`, which on Ubuntu returns from `.bashrc` before the line that
   adds `~/.local/bin` (`farm/install.sh` :135), so programs installed there are named by absolute
   path
   (`/home/farm/.local/bin/claude`, `/home/farm/.local/bin/fleet`, the user is always `farm`), or
   the command runs under `bash -lc` as the creator's own check does (`machines.py` :715); and
   no `~` or `$` is left for the laptop's shell to expand: remote paths are written out in full
   and the command is built with `shlex.join`, so a person's copy-paste reaches the farm as
   printed.
   - Claude, first subscription: `ssh -t <name> /home/farm/.local/bin/claude`, then `/login`
     (the default `~/.claude`).
   - Each further subscription is its own account directory (`fleet/lib/claude_accounts.py`,
     OPERATIONS.md section 7): the script asks for a short name per subscription, runs
     `ssh <name> /home/farm/.local/bin/fleet accounts add <acct>`, and prints
     `ssh -t <name> env CLAUDE_CONFIG_DIR=/home/farm/.fleet/claude-accounts/<acct>
     /home/farm/.local/bin/claude` then `/login`.
     Verified by `ssh <name> /home/farm/.local/bin/fleet accounts list --json` (new: today `list` prints text only,
     `claude_accounts.py` :502; the JSON is the account name, whether its credentials file
     exists, and its email, `account_email` :58): one row per subscription, each logged in, no
     two with the same email.
   - Codex, if they use it (`--with-codex`), since the bootstrap installs only Claude today
     (`farm/install.sh` :148). Cloud-init, which runs as root, installs Node and npm from the
     distribution packages. The `farm` user then installs Codex into a prefix it owns, because a
     global npm install writes under root-owned `/usr` and fails with EACCES:
     `npm install --prefix /home/farm/.local -g @openai/codex`, which puts the binary at
     `/home/farm/.local/bin/codex`. The script writes
     `FLEET_CODEX_BIN=/home/farm/.local/bin/codex` into `~/.config/fleet/env`, the setting that
     exists for exactly this (`fleet/bin/fleet` :44, default `/usr/bin/codex`); a user-owned
     install also updates without root. The login forwards the OAuth callback, as OPERATIONS.md
     section 1 documents: `ssh -L 1455:localhost:1455 -t <name> /home/farm/.local/bin/codex
     login`. Verified by `ssh <name> /home/farm/.local/bin/codex login status`, then by one real
     lane: `fleet spawn --engine codex` with a one-line brief that must finish. Then the script
     reruns the skills step of `fleet/install.sh`, which links the fleet skill into
     `~/.codex/skills` only once `~/.codex` exists (:84).

## Access: tunnel by default, Tailscale on request

Owner decision 2026-09-24: the tunnel is the default because it needs nothing installed.

**Tailscale** is offered as the alternative, and only on a laptop that is itself on a tailnet.
The skill runs where the browser runs, on the person's laptop; its checks are only true there.
Under WSL (`/proc/version` names Microsoft) the Linux side and the Windows browser are two
network environments and Tailscale belongs to the Windows host, so there the skill offers the
tunnel only, which WSL forwards to Windows' localhost. Elsewhere the preflight runs the
laptop's `tailscale status` and, if there is no client or it is logged
out, says so and offers the tunnel instead. After enrolment the script checks that the laptop
reaches the farm's tailnet address (the page answers); if it does not (a key from another
tailnet, an ACL), it says why and falls back to the tunnel, so provisioning never ends at a
page the person cannot open. The fallback first switches the bind back to loopback
(`FLEET_DASH_BIND=127.0.0.1`, the single line below), restarts the dashboard service and checks
it listens on `127.0.0.1:7878` over ssh, and only then opens the tunnel: a tunnel to loopback
while the page listens on the tailnet address alone would connect and then be refused.

The person creates a one-off auth key in their
Tailscale admin page and puts it in a local file (`~/.config/murmur/tailscale.key`, mode 0600);
it never passes through the chat and never goes into user data (which the provider stores).
Cloud-init installs the Tailscale package only, and a root-owned helper,
`/usr/local/sbin/murmur-tailscale-up`, that reads a key on stdin into a 0600 file under `/run`,
runs `tailscale up --authkey file:<it>` and deletes it. Cloud-init allows the `farm` user to run
exactly that helper with `sudo -n` and nothing else. After boot the script runs
`ssh <name> sudo -n /usr/local/sbin/murmur-tailscale-up < ~/.config/murmur/tailscale.key`: the
key travels on ssh's stdin, not on an argv.

**The dashboard listens on the Tailscale address only**, never `0.0.0.0`. Today
`install.sh` writes `FLEET_DASH_BIND=0.0.0.0` when Tailscale is chosen (:249), which on a
droplet with a public address and no firewall would publish the page to the internet behind
its token. New: `FLEET_DASH_BIND=tailscale` means the server resolves `tailscale ip -4` at start
and binds to it, and refuses to start (with the reason) if Tailscale has no address. The
installer writes that value instead of `0.0.0.0`.

**The bind is chosen explicitly, once.** Cloud-init writes a loopback `FLEET_DASH_BIND`
(`machines.py` :470) and the installer's write is conditional (`install.sh` :249), and
`--remote` skips the Tailscale branch entirely. So the script itself writes the one value in
`~/.config/fleet/env` before it starts the service: `127.0.0.1` in tunnel mode, `tailscale` in
Tailscale mode, replacing any earlier line. The ssh-only firewall stays in either case, and
`run.sh` keeps loopback as its own default (:25).

## Security

- Open to the internet: ssh with a key, nothing else (the `murmur-ssh-only` firewall).
- The DigitalOcean token stays on the laptop in the person's doctl config; the farm never
  receives it. A farm that later creates machines itself logs in on its own.
- The dashboard token is read into memory for the browser and never printed, logged or put on
  an argv of a long-lived process (the tunnel does not carry it).
- The Tailscale key file is 0600 on the laptop and deleted from the box after `tailscale up`.

## The repository is private

`magik-ai/murmur` is private today, so `gh repo clone` on the box works only for accounts with
access, and the landing's `curl | bash` works for nobody outside. The owner makes the
repository public before launch (decision 2026-09-24); until then the flow is tested with the
owner's own GitHub login, which has access.

## Moving the owner's farm

The owner's farm is a Windows PC under WSL (12 cores, 17 GB, load around 2, four lanes running
at a time, about 100 GB of real working data; its RTX 5070 belongs to Windows and no agent uses
it). The move is the live test.

1. Run `/murmur:farm` against the owner's personal DigitalOcean account (doctl context `murmur`,
   verified 2026-09-24: a gmail account, "My Team", no droplets). Size proposed: 8 vCPU, 16 GB,
   the live price confirmed by the owner before apply. Access: Tailscale, bound to its address.
   The skill runs on the owner's Mac, which is on the owner's tailnet today (the old farm's
   dashboard is reached at its tailnet address), not on the WSL farm. The new farm takes a new
   ssh name; the old farm keeps its own until step 7.
2. The owner logs in GitHub, the three Claude subscriptions (three account rows, step 9) and
   Codex on the new box. No lane moves until `fleet accounts` shows the three subscriptions
   logged in with three different emails.
3. **Point at the same head office.** The installer runs with `--hq-repo` set to the owner's
   existing head office repository (not a new default one, `install.sh` :200), and before any
   lane spawns the new farm proves it sees the same claims and mail: `hq whoami`, `hq claims`,
   `hq inbox --peek` answer with what the old farm sees.
4. **Re-register, do not copy, what holds paths.** `policy.toml` and `models.toml` are copied.
   `projects.toml` stores absolute checkout paths from the WSL home (`fleet/bin/fleet` :173), so
   projects are cloned fresh and registered again with `fleet add-project`, and each registered
   path is checked with `git -C <path> rev-parse --git-dir`. The dashboard token is minted fresh.
5. **Move CI deliberately.** The check queue is farm-local (`$FLEET_STATE/ci/queue.json`,
   `fleet/lib/ci.py` :69), and its tiers need tools a fresh droplet does not have: `bwrap` for
   every tier (`ci.py` :3830), Docker for the Postgres tier, `npm` and `npx` for the frontend
   tier, `terraform` and `helm` for the infra tier (`ci.py` :2134, :2589). So:
   - provision every tier the owner uses (Docker with the `farm` user in its group, a
     root-equivalent right accepted on a dedicated farm; bubblewrap; Node; terraform; helm);
   - recreate `$FLEET_STATE/ci/env` (overrides and credentials, `ci.py` :3991): copied from the
     old farm to the new one over ssh stdin into a 0600 file, never printed or put on an argv;
   - start the CI service and run one real candidate per tier the owner uses to green;
   - let the old queue drain (`fleet ci status` shows nothing running or queued: the `running` and `queued` lists in `queue.json` are empty, while its record of finished checks stays) or requeue its items on
     the new farm, and only then stop the old CI.
   `--hq-repo` (step 3) is a new installer flag; it lands with this flow.
6. **Lanes.** Announce a window in `hq`; new lanes spawn on the new farm, lanes on the old farm
   finish there. The sweep moves last.
7. The old PC stays until the owner decides; nothing is deleted there.

## Out of scope

Other providers than DigitalOcean for the one-click path, GPU machines, a hosted dashboard run
by anyone but the person, and the runner skill (`/murmur:runner`, hosting.md section 6).

## Tests

- `murmur_farm.py` with fake `doctl`, `ssh`, `ssh-keygen`, `gh` and `brew` first on PATH
  (the pattern of `fleet/tests/fakes/core/doctl`): every step, resume after a stop at each
  step, the price refusal, the ssh config section rewritten in place, the token never on stdout.
- The lost create: a fake doctl that creates the droplet and then times out; the rerun adopts
  it and never calls create again, and a new purchase asks for the price again.
- The slow create: the first create times out, the next list is empty, the droplet appears a
  minute later; the rerun waits on the pending attempt and never starts a second create.
- Another farm's droplet: a list with `farm` tagged for another farm id is never adopted; two
  candidates with this farm's tag stop the run.
- Tailscale without a laptop client, or with a tailnet that cannot reach the farm, ends in the
  tunnel with the reason said, and the fallback rewrites the bind to loopback and restarts the
  service before the tunnel opens (a fake page that listens only where it is bound).
- One farm id: plan, create and resume read the same `$FLEET_CONFIG/farm-id` and produce the
  same tag; the script writes no id file of its own.
- The tunnel: a fake `ssh` that binds and stays alive; `open` returns, `-O check` finds it, a
  second `open` reuses it, `open --stop` ends it and removes the socket and port files; a dead
  socket is replaced; a forward that cannot bind is an error.
- The logins: three subscriptions make three `fleet accounts add` calls and three distinct
  printed commands; a fake `fleet accounts list --json` with two rows, or two with one email, stops
  the move. `--with-codex` installs the CLI, and the skills step links `~/.codex/skills/fleet`
  only after `~/.codex` exists.
- The dashboard unit: `systemd-analyze --user verify` passes, and with a fake `tailscale` that
  first answers nothing and then an address, the server exits non-zero, then starts on the
  retry (the unit's restart settings are read from the file and asserted).
- The laptop listener: with a config carrying `GatewayPorts yes`, the tunnel's command still
  binds `127.0.0.1:<port>`, and a fake listener on a wider address closes the tunnel.
- The host key: with an empty `~/.config/murmur/known_hosts`, the first `BatchMode=yes` probe
  records the key and passes; a fake host that then presents a different key is refused.
- The host key on a fresh laptop: with no `~/.config/murmur` at all, the preflight creates it
  0700, the first probe records the key (checked with `ssh-keygen -F`), and a changed key is
  then refused; a probe that records nothing stops the run.
- The host key under a hostile config: with an earlier `Host *` carrying
  `StrictHostKeyChecking no` and `UserKnownHostsFile /dev/null`, every command the script builds
  still resolves (`ssh -G`) to `accept-new` and the murmur file.
- The key: a passphrase key not in the agent stops at preflight with the `ssh-add` line and no
  purchase; after boot, a failing `BatchMode=yes` probe stops before any remote step.
- A taken ssh name: a config whose earlier `Host farm` points elsewhere makes the questions ask
  for another name, and a written block that `ssh -G` does not resolve to the droplet stops the
  run before any remote command.
- WSL: a fake `/proc/version` naming Microsoft offers the tunnel only.
- Remote commands: every command the script runs or prints over ssh names its program by
  absolute path when it lives in `~/.local/bin` (system ones such as `gh` sit in `/usr/bin`) or
  runs under `bash -lc`, and none carries a `~` or `$` the laptop would expand
  (a Bash client with `HOME=/home/laptop` prints the command and it still says `/home/farm`).
- Codex: `--with-codex` installs with a `/home/farm/.local` prefix, `FLEET_CODEX_BIN` is written,
  and the one-line Codex lane runs on the fake engine.
- The firewall: a fake list with the right name but a wide rule or no tag is corrected, and a
  correction that fails creates nothing.
- The token: the browser handoff file is 0600 and gone after use, the token is on no argv
  (the fake `open` records its argv), the page takes `#token=`, and a GET that raises with
  `?token=CANARY` leaves no canary in the log.
- The Tailscale key: it reaches the fake helper on stdin, never on an argv or in user data.
- The bind: tunnel mode writes loopback and Tailscale mode writes `tailscale`, replacing
  cloud-init's line.
- The installed copy runs `murmur_farm.py plan` (`tests/test_plugin_installed_copy.py`).
- `FLEET_DASH_BIND=tailscale`: resolves, refuses without an address, never binds `0.0.0.0`.
- The unit file: `systemd-analyze --user verify` in CI where available.
- One live run: the owner's farm move above, the owner's approval given 2026-09-24.

## Decided after review (2026-09-24)

1. Two sessions: the person's own terminal for `gh auth login`, then a non-interactive session
   for clone and install, after `gh auth status` answers.
2. `/murmur:farm open` starts a background tunnel held by an ssh control socket (step 8): it
   returns only after the forward is bound and the page answers, `open` again reuses or replaces
   it after a sleep, and `open --stop` closes that same control master. A launchd agent can
   follow if people reopen it often.
3. Default 4 vCPU, 8 GB; 2 vCPU, 4 GB offered as the cheaper choice with a sentence that it runs
   few agents at once (`host_presets.py` :60).
