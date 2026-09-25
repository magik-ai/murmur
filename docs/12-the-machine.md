# The machine

Agents that run while nobody watches need a computer that stays on. murmur calls it a farm: an
always-on Linux machine that runs agents. This chapter is for the person who chooses that
machine and pays for it. It covers whether you need one, what it must be, where to get one, what
it costs, how to set it up and how to reach its dashboard. No step here needs you to write code.

## Do you need one?

Not on day one. Everything in chapters 00 to 11 works on the laptop you already have, with one
or two agents in Claude Code windows. A farm solves two problems:

- **Your laptop cannot carry the agents.** Several agents, a build and a browser at once can
  make a laptop unusable. Past three or four agents at once, move them to a farm.
- **Work must go on when you close the lid.** Night mode (an agent finishing work while you
  sleep, [chapter 10](10-unattended-runs.md)) needs a machine that does not sleep. So does the
  sweep, a job that clears away the working copies of finished lanes every ten minutes.

If neither is true yet, skip this chapter and come back when it is.

## What the machine must be

| It needs | Why |
| --- | --- |
| Linux with systemd: Ubuntu 22.04 or newer, or Debian 12 or newer | Each agent, the sweep and the dashboard run as systemd user services |
| Python 3.11 or newer | murmur's tools need it |
| CPU and memory, not a graphics card | Agents read, write and run tests; nothing here trains a model |
| Always on, and reachable over ssh | You drive it from your laptop |
| Your own GitHub login and your own agent subscription | Agents push and open pull requests as you, and run on your subscription (see [the two logins](#the-two-logins)) |

Ubuntu 24.04 and newer, and Debian 12 and newer, come with Python 3.11 or newer. Ubuntu 22.04
comes with 3.10: the installer stops there and prints one line to paste that adds 3.11. The same
line is in step 1 of [the quickstart](../fleet/docs/QUICKSTART.md).

The subscription is a Claude plan, plus a ChatGPT login if you also run Codex agents.

Windows works through WSL2: run `wsl --install`, then do everything below inside the Ubuntu it
installs. By default, WSL shuts Ubuntu down about 15 seconds after its last terminal closes, and
the farm's systemd services do not keep it running. To keep the farm on, add these lines to
`%UserProfile%\.wslconfig` on Windows (the second setting needs Windows 11):

```ini
[general]
instanceIdleTimeout=-1

[wsl2]
vmIdleTimeout=-1
```

Then run `wsl --shutdown` once in PowerShell, and open Ubuntu again.

macOS is not supported as a farm, because it has no systemd. Use a Mac to drive a Linux machine
over ssh.

## Three ways to get one

### 1. A computer you already own

A desktop PC at home works. Install Ubuntu on it, or use WSL2 on Windows with the settings
described above. It costs only electricity. Then run
[the install command](#set-it-up-with-one-command) on it.

Farm agents run with their permission prompts switched off, so they can run any command your
user can. On a computer you also use yourself, give the farm a user account of its own, or use
another machine. [Security](#security) explains why, and what that means under WSL2.

The farm can share the machine with you. `fleet mode` caps the share of the processor that the
agents may use. In `auto` mode, the default, the farm steps back to about half the processor
while an NVIDIA graphics card is busy, which usually means you are using the machine. To see
the card it needs the `nvidia-smi` tool; without it, `auto` stays on full power.

### 2. A DigitalOcean Droplet, set up from your laptop

`/murmur:farm` is a command in the murmur plugin for Claude Code. From your laptop, it rents a
DigitalOcean Droplet (a virtual server), installs murmur on it and opens its dashboard. It buys
nothing until you type the price back.

Before you start, you need on your laptop:

- the murmur plugin in Claude Code, and `uv`, which runs the plugin's scripts;
- `doctl`, DigitalOcean's command-line tool, logged in with `doctl auth init --context murmur`
  in your own terminal. On a Mac with Homebrew, `/murmur:farm` offers to install `doctl` for
  you;
- an ssh key that works without typing a passphrase. `/murmur:farm` offers to make one. If your
  key has a passphrase, add it to your ssh agent with `ssh-add` first;
- GitHub's command-line tool, logged in (`gh auth login`).

Then run `/murmur:farm` in Claude Code. It goes through these steps:

1. **Questions**, each with a default:
   - the farm's name (`farm`);
   - its size (4 vCPU, 8 GB);
   - the region (the nearest one by your time zone);
   - how you reach the dashboard: an ssh tunnel, or Tailscale if your laptop is already on it;
   - whether to also run Codex agents;
   - any further Claude subscriptions;
   - the head office repository to join. The head office is a private GitHub repository your
     agents use for names, branch claims and messages. Leave it empty to get a new one.
2. **The plan and the price.** Nothing is created yet. You see a sentence such as "Create farm,
   $48 a month until you destroy it". Type the price back to buy.
3. **The Droplet.** It runs Ubuntu 24.04 behind a DigitalOcean firewall that lets in only ssh.
   The command adds a `Host farm` entry (or your farm's name) to your `~/.ssh/config`.
4. **The install.** You log the farm into GitHub with a command it prints for your own terminal.
   Then it installs murmur on the farm, asking nothing.
5. **Tailscale, if you chose it.** You make a one-off auth key on Tailscale's admin page and
   save it in a file on your laptop; the command prints the line to use. The key goes to the
   farm over ssh. If your laptop cannot reach the farm over Tailscale, it switches to the ssh
   tunnel and says why.
6. **The logins.** It prints one command per Claude subscription for your own terminal (then you
   type `/login`), and the Codex login if you chose Codex.
7. **The dashboard** opens in your browser, through a private ssh tunnel or over Tailscale.

Every login happens in your own terminal, never in the chat. If a step stops, run `/murmur:farm`
again: it picks up where it stopped, and it never buys a second Droplet.

A Droplet is billed until you destroy it, even while it is switched off. To stop paying, destroy
it in DigitalOcean's control panel, or ask Claude Code to destroy the farm by name.

### 3. Another rented server, or a company cloud machine

Any provider that rents virtual servers (a VPS) works. So does a virtual machine on your
company's cloud account. It must be a virtual machine that boots systemd, not a container. You
create the server yourself, then run [the install command](#set-it-up-with-one-command) on it.

- Pick Ubuntu 24.04 when the provider asks for an image.
- Add your ssh key while you create it, so you never need a password.
- Start with 4 vCPU and 8 GB of memory.
- Open only the ssh port (22) to the internet, and nothing else.

Prices differ between providers, so compare them on each provider's own page.

## Sizes and prices

These are the three Droplet sizes `/murmur:farm` offers, at DigitalOcean's list prices on
2026-09-23. Prices change: before it buys, `/murmur:farm` asks DigitalOcean for today's price
and shows you that one.

| Size | Disk | Price a month | Good for |
| --- | --- | --- | --- |
| 2 vCPU, 4 GB | 80 GB | $24 | Light work; check the memory limits below |
| 4 vCPU, 8 GB | 160 GB | $48 | The default, and the place to start |
| 8 vCPU, 16 GB | 320 GB | $96 | More agents at once, heavier builds |

Start with 4 vCPU and 8 GB. An agent needs little while it thinks, and a lot in short bursts,
such as a front-end build or a test run. Two bursts at once on a 4 GB machine can run it out of
memory.

The default limits in fleet suit a large machine: no new agent starts while less than 6 GB of
memory is free, and fleet warns below 8 GB. On a machine with less than 12 GB of memory, the
installer in the next section lowers both: to 1 GB and 2 GB on a 4 GB machine, and to 2 GB and
3 GB on an 8 GB machine. It changes them only while they are still the shipped values. If
`fleet capacity` still says `BLOCK` because of free RAM, open `~/.config/fleet/policy.toml` and
lower `ram_min_gb` and `warn_ram_gb` in its `[limits]` table.

## Set it up with one command

The installer runs as an ordinary user, not root, and the agents will run as that user.

If the provider gave you only root, create such a user first, with sudo rights and your ssh key.
As root, with your own user name in place of `alice`:

```bash
adduser alice
usermod -aG sudo alice
mkdir -p /home/alice/.ssh
cp /root/.ssh/authorized_keys /home/alice/.ssh/
chown -R alice:alice /home/alice/.ssh
```

Then log out, and log in over ssh as `alice`.

On the new machine, as your ordinary user, run:

```bash
curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
```

To read the script first, open [`farm/install.sh`](../farm/install.sh) in this repository. It is
safe to run again: after any change, it does only what is missing. It works in five steps and
reports each one:

1. **System packages.** git, tmux, Python, curl, and GitHub's command-line tool (`gh`) from
   GitHub's own package source. The script uses sudo only to install packages. If Python is
   older than 3.11, it stops and prints the fix.
2. **Your user.** Your services keep running after you log out (systemd calls this "linger"). It
   installs `uv` (a Python tool runner) and the Claude Code command-line tool in your home
   folder.
3. **The tools.** It logs you into GitHub if needed (you follow a browser link). It clones
   murmur into `~/work/murmur` and installs `fleet` (the command that runs the farm) and `hq`
   (the head office tool). It asks whether this is your only machine and you work on it
   directly. If yes, the dashboard can be reached from this machine only.
4. **Configuration.** A few questions, each with a default you accept by pressing Enter:
   - the head office repository. The default is `<your GitHub login>/agent-hq-office`, and the
     script creates it as a private repository if it does not exist;
   - your own code name as the owner;
   - the ssh alias you will use for this machine from your laptop (default `farm`);
   - whether to reach the dashboard over Tailscale, if you said you drive this machine from
     another one.

   It also starts the dashboard as a service that comes back after a reboot.
5. **What only you can do.** It prints the Claude login, how to register your first project and
   the commands that start the first agent.

Flags go after `bash -s --`, for example:

```bash
curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash -s -- --yes
```

| Flag | What it does |
| --- | --- |
| `--yes` | Asks nothing and takes every default. Log in with `gh auth login` first |
| `--hq-repo OWNER/NAME` | Joins this head office repository instead of the default |
| `--no-tailscale` | Never offers Tailscale |
| `--remote` | For a machine you drive from your laptop: the dashboard stays local, and the script prints the ssh tunnel command |

Add `--help` the same way to print every flag. The comment at the top of
[`farm/install.sh`](../farm/install.sh) holds the same text.

### Reach the farm by name

This chapter reaches the farm as `farm`, for example with `ssh farm`. `/murmur:farm` adds that
name to your laptop for you. The installer only records the name, so that the commands it and
the dashboard print use it. For any other machine, add this block once to `~/.ssh/config` on
your laptop:

```text
Host farm
  HostName <the farm's address>
  User <your user on the farm>
```

### The two logins

The script cannot log in for you, and it should not:

```bash
gh auth login    # GitHub: choose HTTPS, and let it set up git credentials
claude           # then type /login and follow the link
```

To do the Claude login from your laptop, run `ssh -t farm claude`.

Both are your own accounts. Every branch an agent pushes and every pull request it opens carries
your GitHub login. That is why the head office exists: it tells the agents apart when GitHub
cannot.

The Claude login must be a subscription, not an API key. Whenever fleet starts a Claude Code
or Codex agent, it removes `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`,
`CODEX_API_KEY`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX` and `CLAUDE_CODE_USE_FOUNDRY`
from its environment, so an agent does not switch to paid API use by accident. Do not set up other
API credentials on the farm either, such as an `apiKeyHelper` in Claude Code's settings or a Codex
login made with an API key.

Next, register a project and start the first agent. The installer prints the commands, and
[the quickstart](../fleet/docs/QUICKSTART.md) explains each one.

## Reach the dashboard

The dashboard is a web page served by the farm on port 7878. It shows every agent and can start
and stop things, so it is never open to the internet. By default it listens only on the farm
itself. There are two ways in from your laptop:

- **An ssh tunnel.** No extra software. On your laptop, run
  `ssh -N -L 7878:127.0.0.1:7878 farm`, then open `http://127.0.0.1:7878`. The tunnel lasts as
  long as that terminal stays open.
- **Tailscale**, a private network between your own devices, free for personal use. Run
  `sudo tailscale up` on the farm and install the Tailscale app on your laptop. The dashboard is
  then at `http://<the farm's Tailscale address>:7878`. The installer offers to set this up.

`/murmur:farm` sets up one of the two for you and opens the page.

Every change made on the page needs a token. Print it on the farm with `fleet dashboard token`.
Then open the page once with the token at the end of the address, for example
`http://127.0.0.1:7878/#token=<token>`. The page keeps the token for that browser tab and
removes it from the address bar. Over Tailscale, the page needs the token to show anything at
all.

Through the tunnel, the page also works without the token, read-only. Every button is still
there, but disabled, with one sentence saying why. A read-only dashboard is a fine way to watch
a farm.

### What you see

The page has three tabs.

- **Board** is the screen to leave open. Until the farm is fully set up, it starts with a
  checklist of what is missing. Until the first agent runs, it shows the commands that start
  one. After that it shows the machine's load, memory and disk, each subscription's usage, and
  every agent as a card with its status, its GitHub checks and its engine. It shows a
  temperature only when the machine has a processor temperature sensor that fleet can read.
- **Mail** shows the messages between agents. It reads the same head office the agents use, not
  a separate copy.
- **Machine** is where you change the farm after setup:
  - **Power**: throttle the farm to give the machine back to you, drain it (save every agent's
    work to git and stop them all), or resume it (start the agent runner again, which restarts
    the agents that have a restart policy). Each action says what it will do before it does it.
  - **Services**: start and stop the agent runner (`fleet daemon`) and the sweep timer. The
    agent runner only restarts lanes that have a restart policy. Stopping it stops those
    restarts, not the agents that are running.
  - **Accounts**: add a subscription. You pick the engine and a name, and the page gives you the
    exact command to run in a terminal. Then it notices the login by itself.
  - Models, machines, projects, and a list of anything still missing.

Three things the page never does:

- It never starts a new agent. That stays a command a person types, with a code name behind it,
  because it spends money under that name.
- It never stops or restarts itself. A page cannot take down the server that draws it, so it
  shows you `fleet dashboard restart` instead.
- It never takes a provider key. There is no field for one. Claude Code and Codex need no key.
  Only an engine added as a contribution may use one, and its key goes in at a terminal, through
  standard input: `fleet models auth <id> < <key file>`.

## Security

- **Agents run without permission prompts.** Each lane runs Claude Code with
  `--dangerously-skip-permissions`, or Codex with `--dangerously-bypass-approvals-and-sandbox`.
  So an agent can run any command, and read any file, that its user can. If that user can use
  sudo without a password, so can the agents.
- **Keep the farm apart from your own things.** On a computer you also use yourself, give the
  farm a user account of its own, and keep your own files, keys and other logins out of it.
  Under WSL2 that is not enough, because every Linux user can reach your Windows files under
  `/mnt/c`. There, use a machine of its own.
- **Agents use the farm user's logins.** On a machine you set up yourself, agents run as the user
  that ran the installer, with its GitHub login and subscriptions. On `/murmur:farm` Droplets,
  they run as a user called `farm`, without sudo rights.
- Open only ssh to the internet, and log in with a key, never a password. In your provider's
  firewall, allow port 22 and nothing else. `/murmur:farm` sets this up on DigitalOcean.
- The head office repository is private. Anyone who can read it can read every message your
  agents ever sent.
- The sweep removes the working copies of finished lanes, so push anything worth keeping
  ([coordination and identity](05-coordination-and-identity.md)).

## When something is off

```bash
fleet capacity          # can the farm take another agent, and if not, why not
fleet status            # every agent, plus the machine's load and memory
fleet dashboard status  # is the dashboard running, and where it listens
hq whoami               # the name this session would sign with
gh auth status          # the GitHub login
```

The ways a farm can go wrong, each with its fix, are in
[sharp edges](../fleet/docs/sharp-edges.md). Read it once before the first night.
