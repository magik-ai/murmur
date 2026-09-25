# One-click farm

`/murmur:farm` gets you a farm on DigitalOcean from your laptop. A farm is an always-on Linux
machine that runs your agents. This design record explains how the flow works, and why each step
is built the way it is. The code is `plugin/scripts/murmur_farm.py`, which the skill
`plugin/skills/farm/SKILL.md` drives one step at a time. The droplet, its firewall and its
registry row come from `fleet/lib/machines.py`, described in [hosting.md](hosting.md), section 4.

## In short

You type `/murmur:farm`, answer a few questions, and type back one price. A few minutes later you
have a working farm: a DigitalOcean droplet with murmur installed, the dashboard running as a
service, and the dashboard open in your browser. You reach it through a private SSH tunnel, or
over Tailscale if you choose. A firewall lets in SSH and nothing else.

## What it builds on

| Piece | Where it comes from |
|---|---|
| The droplet, its firewall, its first boot, its registry row and the farm id | `fleet/lib/machines.py`, reached through the symlinks in `plugin/lib/` |
| The install on the farm | `farm/install.sh --remote --yes`, with `--hq-repo owner/name` to join an existing head office |
| The dashboard as a service | `fleet/systemd/fleet-dashboard.service`, installed by `fleet dashboard enable` |
| A dashboard bound to the tailnet address only | `FLEET_DASH_BIND=tailscale`, resolved by `fleet/dashboard/server.py` |
| The dashboard token handed to the browser | `#token=` in the address, read by `fleet/dashboard/static/core/api.js` |
| The check of the Claude logins | `fleet accounts list --json` (`fleet/lib/claude_accounts.py`) |

## The flow

The script has one subcommand per step, and each one prints one JSON object. Every step is safe
to run again. If you stop, run `/murmur:farm` again: `status` names the next step, and the flow
resumes there. The script keeps its state in `~/.config/murmur/farm.json`. Exit code 0 means
done, 2 means the script is waiting for you, and 1 means it refused.

Two rules hold for every step:

- **Nothing interactive runs inside the skill.** Claude Code's tools have no terminal. So every
  login (doctl, GitHub on the farm, Claude, Codex) is a command that the script prints for you to
  run in your own terminal. Then the script checks the result without a terminal, and waits.
- **A purchase is never repeated.** Before any create, the farm's own tag is reconciled: a
  droplet that is already there is adopted, never bought again. A create whose answer was lost is
  pending, never failed. A typed price is good for one attempt only (step 4).

### 1. Preflight

`preflight` checks the laptop and buys nothing:

- **doctl is installed.** If it is not, on macOS with Homebrew the script offers
  `brew install doctl`, and runs it only after you say yes (`preflight --install-doctl`).
  Elsewhere it prints DigitalOcean's install page.
- **doctl's `murmur` context is logged in**, which means `doctl account get -o json --context
  murmur` answers. If it is not, the script prints `doctl auth init --context murmur` for your
  own terminal, where you paste a DigitalOcean API token. The token never passes through the
  chat. If your laptop has `DIGITALOCEAN_*` variables set, the printed line starts with
  `env -u <variable>` for each one, because doctl would use them instead of what you paste.
- **Your current doctl context is never switched.** Every doctl call names `--context murmur`,
  and the script ignores `FLEET_DOCTL_CONTEXT` and the `DIGITALOCEAN_*` variables for its own
  calls. On a laptop, those settings may belong to another account you use for other work.
- **An SSH key**, by default `~/.ssh/id_ed25519.pub`. If there is none, the script offers to make
  one without a passphrase (`preflight --make-key`), and does so only after you say yes. If you
  want a passphrase, make the key in your own terminal and add it to the SSH agent.
- **The key works without a terminal**, because the script's SSH has none. Either the key has no
  passphrase (`ssh-keygen -y -P '' -f <key>` succeeds; its output is thrown away), or the SSH
  agent holds it (`ssh-add -L` lists it). If neither is true, the script prints
  `ssh-add --apple-use-keychain <key>` on macOS, or `ssh-add <key>` elsewhere, for your own
  terminal. The passphrase never reaches the chat, an argument list or a log. `apply` checks the
  key again just before it buys.
- **GitHub is logged in on the laptop** (`gh auth status`). The farm gets its own GitHub login
  later; this only checks that you have GitHub at all.
- **Which ways to reach the dashboard this laptop can use**: the tunnel always, and Tailscale only
  when this laptop is on a tailnet (see [Access](#access-tunnel-by-default-tailscale-on-request)).

The preflight also creates `~/.config/murmur` with mode 0700. The known-hosts file, the tunnel's
control socket and the state file live there.

### 2. Questions

`questions` lists what is still unanswered, and `answer --id <id> --value <value>` stores one
answer. An empty answer takes the default.

| Question | Default | Notes |
|---|---|---|
| `name`: the farm's SSH name on this laptop, and the droplet's name | `farm` | lower case letters, digits and `-`, starting with a letter, 2 to 31 characters; refused when your SSH config already uses it (step 5) |
| `size` | `s-4vcpu-8gb` (4 vCPU, 8 GB) | each size shows today's price when doctl answers, or else the list price with its date; the 2 vCPU size says it is cheaper and runs one or two agents at a time |
| `region` | the nearest by the laptop's time zone, else `fra1` | one of the regions in [hosting.md](hosting.md), section 2 |
| `access`: how you reach the dashboard | `tunnel` | `tailscale` is offered only when this laptop can use it |
| `codex`: also run Codex agents | `no` | |
| `accounts`: your further Claude subscriptions, after the first, as short names | empty | lower case names, not `default` or `auto`, no two alike |
| `hq_repo`: the head office repository to join, as `owner/name` | empty: a new one of your own | |

The head office is a private GitHub repository that the agents use for their names, branch
claims and messages.

The script only buys DigitalOcean droplets. For a machine you already have, the skill tells you
to run `farm/install.sh` on it.

### 3. Plan

`plan` creates nothing. First it rehearses where SSH will really send the farm's name (step 5).
A config that would send it somewhere else gets no price. Then the plan prints:

- the doctl commands the purchase will run, and the cloud-init file;
- the live price, as a sentence: "Create farm, $48 a month until you destroy it";
- a quote: a short id for this plan.

The quote binds the whole plan, not only its price: the name, size, region, image, access,
Codex, head office, and a hash of the cloud-init file. If any answer changes after `plan`,
`apply` refuses, and you run `plan` again. When the price is not live (doctl did not answer),
the plan says that `apply` will refuse to buy on it.

The plan gives no quote when nothing needs buying. If the registry already has a live row for the
name, `apply` resumes it. If one droplet with this name is already on this farm's tag (its
registry row was lost), `apply` adopts it with no price. If there are two or more, nothing is
bought or adopted until only one is left.

### 4. Apply

`apply --confirm-usd <price> --quote <quote>` buys the droplet, only with the price you typed
back:

1. The reconcile comes first. One droplet with this name on this farm's tag is adopted with no
   price, and it is never bought again. More than one stops the run.
2. The quote must be the current plan's, and the plan must not have changed since. The rehearsal
   of step 5 runs again, in case your SSH config changed.
3. The typed price must equal the quoted price. `machines.py` then compares it with the live
   price just before the create. All three must agree.
4. The quote is spent before DigitalOcean is asked. Whatever happens next, another attempt needs
   the price typed again.
5. `machines.py` buys the droplet exactly as `fleet machines create` does: the registry row
   first, then the firewall check, then the create without waiting ([hosting.md](hosting.md),
   section 4).
6. `apply` waits, up to eight minutes (`--wait`), for the droplet to get its address and for
   cloud-init to finish. It uses the same steps as `fleet machines list`.

**A lost answer.** A create whose answer was lost (a timeout or an error) is not failed: the
droplet may exist. The row stays pending, and `apply` polls the tagged list for up to ten minutes
from the attempt. It adopts the droplet if it appears. If it never appears, nothing is bought on
its own: you run `/murmur:farm forget-attempt`, then `plan`, and type the price again.

**One farm id.** The laptop has one farm id: the one `machines.py` keeps in
`$FLEET_CONFIG/farm-id`, by default `~/.config/fleet/farm-id`. The script keeps no id of its own.
So `plan`, `apply` and every resume use the same tag, `murmur-by-<farm id>`.

**The firewall.** The droplet gets the same firewall as every droplet murmur creates:
`murmur-ssh-only`, with SSH in from anywhere and everything out, and no other firewall over the
droplet. It is checked by its rules, never trusted by its name, and it is corrected or refused
before anything is bought. The full rule is in [hosting.md](hosting.md), section 4.

### 5. SSH config

After this step, `ssh <name>` must reach the new farm as the user `farm`, on port 22, with your
key. And it must trust only the host key it met first.

`ssh-config` writes a `Host <name>` block into a marked section of `~/.ssh/config`, a section the
script owns. For a farm named `farm`, it looks like this:

```text
# >>> murmur farm: written by /murmur:farm, rewritten on every run >>>
Host farm
  HostName 203.0.113.10
  Port 22
  User farm
  IdentityFile /home/you/.ssh/id_ed25519
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
  UserKnownHostsFile /home/you/.config/murmur/known_hosts
# <<< murmur farm <<<
```

The section goes before the first `Host` or `Match` line, and every run rewrites it in place. ssh
takes the first value it finds for each setting, so a `Host *` below the section cannot change
this farm's port, user or address. A section with a missing or a doubled marker is refused, and
the file is left as it was.

**The host key.** The droplet is new, so the laptop does not know its host key, and a connection
without a terminal cannot answer ssh's usual question. So every ssh the script runs or prints for
this farm carries these options on its command line:

```text
-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=<your home>/.config/murmur/known_hosts -p 22 -l farm
```

Options on the command line win over any config file, including an earlier `Host *` that says
`StrictHostKeyChecking no`. The first connection, minutes after the script created that address,
records the key. Any later change of key is refused. After that first connection,
`ssh-keygen -F <address>` on the murmur known-hosts file must find the key, or the run stops: a
first connection that pinned nothing proves nothing. `machines.py` keeps a known-hosts file of its
own for its own checks, so the script pins this one with its own first connection.

A rerun never removes the pin, unless the droplet itself changed (another droplet id or address
than the one pinned). If the farm shows another key, `ssh-config` refuses and says so. The script
never removes the key for you.

**The name must be free.** ssh takes the first value it meets. So a name your config already
answers would send the logins and the install to that other machine. The name is checked when you
answer the question, and again at `plan` and at `apply`:

1. The script reads `~/.ssh/config` and every file it Includes, found as ssh finds them: relative
   paths under `~/.ssh`, globs in sorted order, nested as deep as ssh goes. Then it reads
   `/etc/ssh/ssh_config`, which ssh reads next, and every file that Includes (relative paths under
   `/etc/ssh`).
2. A `Host` line, or a `Match` line's `host` or `originalhost` criterion, that names the chosen
   name exactly, outside the script's own section, makes the name taken. That holds even when
   every setting under it equals ssh's defaults.
3. A wildcard (`Host *`, `Host f*`) names no name. The rehearsal below checks what a wildcard
   would change.

**The rehearsal.** Before any price is shown, and again just before the purchase, the script
checks where ssh will really go. It copies your config to a scratch file, with the exact block
`ssh-config` will write at the exact place. The block holds the placeholder address 192.0.2.1,
a test address that no machine answers. The system config follows, as ssh reads it, and every
Include in the copies becomes the absolute path ssh would really read. Then `ssh -G -F
<scratch file>`, with the host key options above, must report:

- the placeholder address, port 22 and the user `farm`;
- the script's key as the first identity file;
- no `ProxyCommand`, `ProxyJump` or `HostKeyAlias`;
- `accept-new` and the murmur known-hosts file.

Any difference refuses the plan, with no quote. The refusal names the setting and the line of
your config behind it, for example a top-level `Port 2222`, or a `Host *` with another `User` in a
file Included above the section. After the block is written, the same checks run on your real
config against the droplet's real address, before any command runs on the farm.

### 6. Finish

**GitHub first, in two sessions.** The farm needs its own GitHub login. The script prints
`ssh -t <name> 'gh auth login'` (with the host key options of step 5) for your own terminal. It
cannot run that itself: it has no terminal, and its ssh reads nothing from you. It checks the
result with `gh auth status` over ssh.

Only then does it write two lines into `/home/farm/.config/fleet/env`: the dashboard bind (see
[Access](#access-tunnel-by-default-tailscale-on-request)) and `FLEET_FARM_ALIAS=<name>`. Then it
starts the clone and the installer in a second session, which asks nothing:

```text
bash /home/farm/work/murmur/farm/install.sh --remote --yes [--hq-repo owner/name]
```

The clone and the install run detached on the farm, under a lock, with their log in
`/home/farm/.cache/murmur/install.log`. So no ssh has to stay open for them, and a second `finish`
never starts a second install. `finish` waits up to eight minutes; run it again to keep waiting.
After a failure it shows the last lines of the log, and `finish --reinstall` starts it again.
When the install is done, `fleet capacity` must answer on the farm.

With `--yes` the installer never asks. The head office repository (`--hq-repo`, or else
`<your GitHub login>/agent-hq-office`, created if it is missing), your code name and the SSH alias
take their defaults. `--remote` skips the question of whether this is your only machine.

**The dashboard as a service.** The installer installs and enables the user unit
`fleet-dashboard.service`, from `fleet/systemd/`, and cloud-init has already turned linger on.
Like the other farm units, the unit has `Restart=always` and `RestartSec=5`. It also has
`StartLimitIntervalSec=0`, so systemd never stops retrying. After a reboot, the user manager can
start the dashboard before Tailscale has an address. With `FLEET_DASH_BIND=tailscale` the server
then refuses to start and exits, and systemd tries again every five seconds until the address is
there. `fleet dashboard start` still works: it starts the unit.

### 7. Tailscale (only when chosen)

`tailscale` joins the farm to your tailnet, or falls back to the tunnel and says why. See
[Access](#access-tunnel-by-default-tailscale-on-request).

### 8. Logins

The logins only you can make are printed as commands for your own terminal, one at a time. Then
the script checks each one without a terminal. `logins` exits 2 until all of them are done. Each
printed `ssh` command also carries the options of step 5; they are left out below.

Two rules hold for every remote command the script runs or prints:

- ssh runs the command in a shell that is not interactive. On Ubuntu, `.bashrc` stops early in
  such a shell, before the line the installer adds for `~/.local/bin`. So programs installed
  there are named by their absolute path: `/home/farm/.local/bin/claude`,
  `/home/farm/.local/bin/fleet` and `/home/farm/.local/bin/codex`. The user is always `farm`.
- No `~` or `$` is left for your laptop's shell to expand. Remote paths are written out in full,
  and each command is built with `shlex.join`, so what you copy reaches the farm as printed.

The logins:

- **Claude, your first subscription**: `ssh -t <name> /home/farm/.local/bin/claude`, then
  `/login` inside it. This is the farm's default account.
- **Each further subscription** gets its own account directory (`fleet/lib/claude_accounts.py`).
  The script runs `fleet accounts add <account>` on the farm and prints
  `ssh -t <name> 'env CLAUDE_CONFIG_DIR=/home/farm/.fleet/claude-accounts/<account>
  /home/farm/.local/bin/claude'`, then `/login`.
- **The check** is `fleet accounts list --json`, whose rows are `{name, logged_in, email}`. There
  must be one row per subscription, each logged in, and no two with the same email. Otherwise
  the step stops and says why.
- **Codex**, when you chose it:
  1. `farm/install.sh` installs Claude Code only. Cloud-init, which runs as root, has already
     installed Node.js and npm from the distribution's packages.
  2. The `farm` user has no sudo, so it installs Codex into a folder it owns:
     `npm install --prefix /home/farm/.local -g @openai/codex`. The program lands at
     `/home/farm/.local/bin/codex`, and a user-owned install also updates without root.
  3. The script writes `FLEET_CODEX_BIN=/home/farm/.local/bin/codex` into
     `/home/farm/.config/fleet/env`. fleet looks in `~/.local/bin` by itself too; the setting
     names the path for certain.
  4. The login forwards Codex's sign-in port:
     `ssh -L 1455:localhost:1455 -t <name> /home/farm/.local/bin/codex login`. The check is
     `codex login status`.
  5. The script reruns `fleet/install.sh` on the farm. It links the fleet skill into
     `~/.codex/skills` once `~/.codex` exists.
- **One real Codex lane**, if you ask for it with `logins --codex-lane <project> --by <code
  name>`. A lane is one agent doing one task on its own branch. The script spawns one with a
  one-line task on a project already registered on the farm, and waits for it to finish.

### 9. Open

**Tunnel mode.** ssh itself holds the tunnel, through a control socket, so the skill can return
while the tunnel lives on. `/murmur:farm open` runs, with the options of step 5:

```text
ssh -f -N -M -S ~/.config/murmur/<name>.sock -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:<port>:127.0.0.1:7878 <name>
```

- The laptop end is bound to `127.0.0.1` by name. Otherwise a `GatewayPorts yes` in your ssh
  config would make it listen on every interface, and hand your network the dashboard's reads,
  which need no token on a dashboard bound to loopback. After the start, the script checks the
  listener with `lsof`, or `ss` if `lsof` is missing. If anything listens beyond `127.0.0.1`, or
  neither tool is there, it closes the tunnel.
- `-f` sends ssh to the background only after the forward is bound. So a port that cannot bind is
  a clear error, not a silent tunnel.
- The laptop port is 7878, or a free one if 7878 is taken. It is written next to the socket, in
  `~/.config/murmur/<name>.tunnel`. Then the dashboard must answer (`GET /api/version`).
- Before it starts, `ssh -S <socket> -O check <name>` says whether a tunnel is already up. If it
  is and the dashboard answers, `open` only opens the browser. If it is dead (after a sleep, or a
  dropped network), the old socket is removed and a fresh tunnel starts.
- `/murmur:farm open --stop` runs `ssh -S <socket> -O exit <name>` and removes both files.

**Tailscale mode.** There is no tunnel. The dashboard is at `http://<tailnet address>:7878`.

**The token.** Either way, the dashboard token reaches the browser without an argument list or a
log. The script reads it over ssh (`fleet dashboard token`) into memory. It writes a one-shot
local HTML file, mode 0600, that sends the browser to the dashboard with the token in the address
fragment (`#token=...`). It opens that file with `open` on macOS, `wslview` under WSL when it is
installed, or else `xdg-open`, and deletes the file about 20 seconds later. The dashboard accepts
`#token=` as it accepts `?token=`, and removes it from the address at once. A fragment never
reaches the server. The server's failure log writes the path only, never the query string.
`/murmur:farm open` reopens the dashboard at any time.

## Access: tunnel by default, Tailscale on request

The tunnel is the default because it needs nothing installed.

**Where Tailscale is offered.** Tailscale is offered only on a laptop that is on a tailnet
itself, because the skill runs where the browser runs, and its checks are only true there. Under
WSL (`/proc/version` names Microsoft), the Linux side and the Windows browser are two network
environments, and Tailscale belongs to Windows. So under WSL the skill offers the tunnel only,
which WSL forwards to Windows. Elsewhere, the preflight runs `tailscale status --json` on the
laptop. With no Tailscale, or a Tailscale that is not running, it offers the tunnel only and says
why.

**Joining the tailnet.**

1. You make a one-off auth key in your Tailscale admin page. You save it, in your own terminal, as
   `~/.config/murmur/tailscale.key` with mode 0600; the script prints a `umask 077 && cat > ...`
   line for that. The key never passes through the chat, and it never goes into the droplet's
   user data. A key file that others can read is refused.
2. Cloud-init installs the Tailscale package only, and one root-owned helper,
   `/usr/local/sbin/murmur-tailscale-up`. The helper reads a key on stdin into a 0600 file under
   `/run`, runs `tailscale up --auth-key file:<that file>`, and deletes the file. A sudoers entry
   lets the `farm` user run exactly that helper, with no arguments, with `sudo -n`, and nothing
   else. Cloud-init checks the entry with `visudo -c` and removes it if it does not parse.
3. After the install, the script runs `sudo -n /usr/local/sbin/murmur-tailscale-up` over ssh,
   with the key on ssh's stdin, not on an argument list.
4. It restarts the dashboard and checks that this laptop reaches it at the farm's tailnet
   address. If the join failed, the farm got no tailnet address, or this laptop cannot reach it
   (a key from another tailnet, an ACL that keeps this laptop out), the script says why and falls
   back to the tunnel. So the flow never ends at a dashboard you cannot open.

The fallback first switches the bind back to loopback (`FLEET_DASH_BIND=127.0.0.1`), restarts
the dashboard service, and checks over ssh that it listens on `127.0.0.1:7878`. Only then does
the flow go on to the tunnel (`open`). A tunnel to loopback, while the dashboard listens on the
tailnet address only, would connect and then be refused.

**The dashboard listens on the Tailscale address only**, never on `0.0.0.0`.
`FLEET_DASH_BIND=tailscale` means that the server asks `tailscale ip -4` at start and binds to
that address. Without one it refuses to start, and says why. `farm/install.sh` writes this value
when you choose Tailscale on a machine it installs, and replaces any other bind line. On a
machine with a public address and no firewall, `0.0.0.0` would publish the dashboard to the
internet, behind its token only.

**The script chooses the bind, once.** Cloud-init writes a loopback bind, and under `--remote`
the installer leaves the bind as it is. So the script itself writes the one value into
`/home/farm/.config/fleet/env` before the install starts the service: `127.0.0.1` in tunnel mode,
`tailscale` in Tailscale mode. It replaces any earlier bind line, keeps every other line, and
keeps the file at mode 0600. The SSH-only firewall stays in either mode, and
`fleet/dashboard/run.sh` keeps loopback as its own default.

## Security

- Open to the internet: SSH with a key, and nothing else (the `murmur-ssh-only` firewall).
- The DigitalOcean token stays on the laptop, in doctl's own config. The farm never receives it.
  A farm that later creates machines itself logs in to doctl on its own.
- The dashboard token is read into memory for the browser. It is never printed, logged, or put
  on an argument list, and the tunnel does not carry it.
- The Tailscale key file is 0600 on the laptop, and the copy on the farm is deleted after
  `tailscale up`.

## Out of scope

- Providers other than DigitalOcean for this flow, and GPU machines.
- A dashboard hosted by anyone but you.
- A tunnel that restarts by itself. `open` replaces a dead tunnel whenever you run it.

## Tests

Two test files check this record against fakes. Neither reaches DigitalOcean, a droplet or a
tailnet, and neither spends money.

- `tests/test_murmur_farm.py` checks the laptop half, `murmur_farm.py`, one step at a time. Fake
  `doctl`, `ssh`, `ssh-keygen`, `ssh-add`, `gh`, `brew`, `tailscale`, `lsof` and a browser opener
  come first on `PATH` (`tests/fakes/farm`), and the fake `ssh` plays the farm. Only `ssh -G` is
  the real ssh, which never connects. `.github/workflows/plugin-tests.yml` runs it.
- `fleet/tests/one-click-farm-test.py` checks the fleet half: `machines.py`, cloud-init, the
  installer, the dashboard unit and its bind, the server's failure log and
  `fleet accounts list --json`. Its fakes are in `fleet/tests/fakes/core`.
  `.github/workflows/fleet-tests.yml` runs it.

What they check:

**The flow and the money**

- The whole tunnel flow, with a resume after a stop at each step. A failed install says why and
  is restarted only on request. A running install is waited on and never started twice.
- No price, no purchase. A price without the plan's quote, a wrong price, a price that moved
  after the plan (up or down), a typed price that is not a finite number above zero, and a `nan`
  price from doctl all buy nothing.
- A quote binds the whole plan, every term of it, and the cloud-init file. One attempt spends
  it.
- The lost create: the rerun adopts the droplet and never calls create again, and a new purchase
  asks for the price again. The slow create is waited on and never started twice. A droplet that
  never appears needs `forget-attempt` and a new price. `forget-attempt` is refused while the
  droplet may still appear, adopts one that did appear, and is only for a pending create.
- Another farm's droplet with the same name is never adopted. One of this farm's droplets with no
  row is adopted, not bought. Two of them stop the run. A listing that fails buys nothing.
- One farm id: `plan`, the create and a resume use the same `$FLEET_CONFIG/farm-id`, and the
  script writes no id file of its own.

**The firewall and the first boot**

- A right firewall is left alone, also when its rules are written another way (split over
  several rules, or with every port spelled differently). The tag is made before the firewall that
  names it; a tag that already exists is fine, and a refused tag buys nothing.
- These are corrected before the create: a wide or extra inbound rule; SSH narrowed to
  `192.0.2.0/24`, to IPv4 only or to a tag; a deny rule on port 22; outbound rules that let
  nothing or too little out; an outbound deny; a status other than `succeeded`; a missing tag. A
  correction that fails, or a status that never reaches `succeeded`, buys nothing.
- Another firewall over the new droplet (by the `murmur-farm` tag, by this farm's own tag, or by
  droplet id), or two firewalls named `murmur-ssh-only`, buy nothing and are named.
- In tunnel mode, cloud-init has no Tailscale and no sudo. In Tailscale mode, it installs the
  package and the helper, and never the key. The helper takes the key on stdin and deletes it,
  and the sudoers line parses. With Codex, cloud-init adds Node.js and npm from the distribution.

**SSH**

- The marked section is written once, before the first `Host`, and rewritten in place. A broken
  section is refused, at the name question too, and the file is left byte for byte.
- On a fresh laptop the preflight creates `~/.config/murmur` with mode 0700, and the first
  connection pins the host key (checked with `ssh-keygen -F`). A first connection that pins
  nothing stops the run. A pin whose record was lost is adopted, and a changed key is refused. A
  rerun for the same droplet never removes its pin; a pin for another droplet at the same address
  is replaced.
- A hostile config (an earlier `Host *` with `StrictHostKeyChecking no` and
  `UserKnownHostsFile /dev/null`) cannot loosen the host key rules. Every command the script
  builds still resolves (`ssh -G`) to `accept-new` and the murmur file, with `-p 22 -l farm` on
  its command line.
- A taken name is asked again: a `Host` or `Match` line that names it in your config, in a file
  it Includes, or in the system config, also when that line appears after the answer. A name
  routed through a proxy is asked again. A clean config, a wildcard, or a mention only inside the
  script's section passes.
- The rehearsal refuses the plan, with no quote and nothing bought, for a top-level `Port 2222`,
  a top-level `User`, a `Host *` with another `User` in an Included file (by an absolute or a
  relative path), an earlier `IdentityFile`, and a `Host *` with a `ProxyJump` or a
  `ProxyCommand`. `apply` refuses the same when the config changed after the plan. The system
  config is read after yours, and a relative Include in it is read under `/etc/ssh`. A `Host *`
  below the section with another port and user passes, and the real `ssh -G` then says port 22
  and user `farm`.
- A proxy left in force after the write, or a block that `ssh -G` does not resolve to the
  droplet, stops the run before any command runs on the farm.

**The key and doctl**

- A passphrase key that the agent does not hold stops the preflight with the `ssh-add` line (the
  keychain line on macOS), and nothing is bought. A key the agent holds passes. With no key, the
  preflight offers to make one. After the first boot, a failing `BatchMode=yes` connection stops
  the run before any command runs on the farm.
- On macOS, Homebrew installs doctl when you ask. A doctl that is not logged in prints the login
  and never switches the context. An inherited context is ignored, and nothing is bought under
  it. The login line unsets an inherited token.

**The dashboard**

- The tunnel: `open` reuses a live tunnel and replaces a dead one, and `open --stop` ends it and
  removes its files. A forward that cannot bind is an error. With `GatewayPorts yes` in the
  config, the tunnel still binds loopback, and a listener on a wider address closes it. A taken
  7878 moves the tunnel to a free port.
- The token is on no stdout and no argument list, and the handoff file goes away. The dashboard
  takes `#token=` (`fleet/dashboard/test_token_fragment.mjs`). A request that fails with
  `?token=` in its address leaves no token in the server's log.
- The unit: `systemd-analyze --user verify` passes where that tool is installed. The restart
  settings retry forever, every five seconds. `fleet dashboard enable` installs the unit and
  `start` starts it; without the unit, `start` keeps using tmux.
- `FLEET_DASH_BIND=tailscale`: the server binds the Tailscale address, never an unspecified one.
  With no address it refuses to start, and it starts on the retry.

**Tailscale and the bind**

- Under WSL only the tunnel is offered.
- The tailnet path joins with the key on ssh's stdin, never on an argument list, writes the
  `tailscale` bind, and opens the tailnet address. A key file others can read is refused.
- A laptop without Tailscale, or a tailnet that cannot reach the farm, ends in the tunnel with the
  reason said. The fallback writes the loopback bind and restarts the service before the tunnel
  opens.
- The farm's env file: a bind change keeps mode 0600 and every other line, a new file is 0600
  under any umask, and a file that others could read is narrowed.
- The installer: `--yes` never asks, even at a terminal. `--remote --yes` skips the
  only-machine question and takes `--hq-repo`, and a malformed `--hq-repo` is refused. Choosing
  Tailscale writes the `tailscale` bind, never `0.0.0.0`, and replaces every other bind line. The
  tunnel leaves a loopback bind alone. The installer installs and enables the dashboard unit.

**The logins**

- Three further subscriptions make three `fleet accounts add` calls and three different printed
  commands. A missing row, or two subscriptions with one email, stops the step.
- `fleet accounts list --json` rows carry the name, whether it is logged in, and the email.
- Codex installs into the farm's prefix, `FLEET_CODEX_BIN` is written, the login is checked, the
  skill is linked once `~/.codex` exists, and one Codex lane runs on the fake engine.
- Every command the script runs or prints over ssh names `fleet`, `claude` and `codex` by their
  absolute paths, and carries no `~` or `$`. Printed by a Bash client with `HOME=/home/laptop`, it
  still says `/home/farm`.

**The installed plugin**

- `tests/test_plugin_installed_copy.py` runs `murmur_farm.py plan` from an installed copy of the
  plugin.
