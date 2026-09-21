# The machine

Agents that run without a person watching need a computer that stays on. This chapter is for
the person choosing that computer: what it has to be, where to get one, what it costs, and the
one command that turns it into a farm. No step here needs you to write code.

## Do you need one at all?

Not on day one. Everything in chapters 00 to 11 works on the laptop you already have: one or
two agents in Claude Code windows, the contract, the tracker, the review. The farm answers
two specific problems:

- **Your laptop cannot hold the agents.** Ten Claude Code windows plus a build plus a browser
  is what killed the reference laptop in July. Past three or four parallel agents, move them.
- **Work must continue when you close the lid.** Night mode, a queue that merges at 3am, a
  janitor that runs every ten minutes: all of that needs a machine that does not sleep.

If neither is true yet, skip this chapter and come back when it is.

## What the machine has to be

| Needs | Why |
|---|---|
| Linux with systemd (Ubuntu 22.04 or newer, Debian 12) | the daemon, the sweep timer and the dashboard are user services |
| Python 3.11 or newer | the head office CLI reads its config with the standard library parser |
| CPU and RAM, not a GPU | agents are processes that read, write and run tests; nothing here trains a model |
| Always on, reachable over ssh | you drive it from your laptop; nothing is installed twice |
| Your own GitHub login and your own Claude subscription | agents push and open pull requests as you; the fleet refuses API keys so a lane cannot bill an account |

Windows works through WSL2 with Ubuntu inside; that is how the reference farm runs. macOS is
not a farm yet: no systemd, so the services have no home. Use a Mac to drive a Linux box.

## Three ways to get one

**1. A computer you already own.** A desktop PC at home, even one you also game on: the fleet
hands the CPU back when a game starts and takes it again when it stops. Install Ubuntu, or on
Windows run `wsl --install` and use Ubuntu inside. Cost: electricity. The reference farm is a
gaming PC at home, driven from a laptop over a private network.

**2. A rented virtual server (VPS).** A slice of a machine in a data centre, yours in five
minutes, billed monthly, deleted when you stop. This is the right answer for a pilot: nothing
at home has to stay on, and a mistake is one click from a fresh start. Pick Ubuntu 24.04 when
the provider asks for an image, and add your ssh key during creation so you never see a
password.

| Size | Fits | Hetzner (EU, cheapest) | DigitalOcean (more regions) |
|---|---|---|---|
| 2 vCPU, 4 GB, 40 GB | one lane at a time, no browser tests | CX23, about 4 euro a month | 24 dollars a month |
| 4 vCPU, 8 GB, 80 GB | three to five lanes, front-end builds | CX33, about 6.50 euro a month | 48 dollars a month |
| 8 vCPU, 16 GB | a full team with a merge queue and browser tests | CX43, about 12 euro a month | 96 dollars a month |

Prices are September 2026 list prices and move; the ratio does not. Start at 4 vCPU and 8 GB:
a lane idles at a few hundred megabytes, but one front-end build peaks at 1.3 GB and 1.5
cores, and two lanes building at once on a 4 GB box is how you meet the out-of-memory killer.

**3. A cloud VM at your company.** Same as a VPS, on the account your company already pays.
Ask for Ubuntu, 4 vCPU, 8 GB, a public ssh port, nothing else open.

## One command

On the new machine, logged in as an ordinary user (not root):

```bash
curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
```

While the repository is private, the same script by another road, after `gh auth login` on
that machine:

```bash
gh repo clone magik-ai/murmur && bash murmur/farm/install.sh
```

The script is idempotent: run it again after anything changes and it does only what is
missing. It does five things and tells you each one:

1. **System packages.** git, tmux, python, curl and GitHub's command line, from their official
   sources. This is the only step that asks for sudo.
2. **Your user.** Services keep running after you log out (`linger`), plus `uv` and the Claude
   Code CLI, both under your own home directory.
3. **The tools.** It logs you into GitHub if you are not (a browser link), clones the fleet and
   the head office CLI and installs both.
4. **Configuration.** Three or four questions, each with a default you can accept by pressing
   Enter: is this a single machine, which private repository is the head office (it creates one
   for you if you name a new one), your code name as the owner, the ssh alias you will use, and
   whether to reach the dashboard over Tailscale.
5. **What only you can do.** It prints the two logins it cannot do for you and the first spawn.

`--yes` takes every default without asking, for a script or a second machine.

### The two logins

The script cannot log in for you, and should not.

```bash
gh auth login            # GitHub: choose HTTPS, let it configure git credentials
claude                   # then type /login and follow the link
```

Both are your accounts. Every branch an agent pushes and every pull request it opens carries
your login, which is exactly why the head office exists: it tells the agents apart when GitHub
cannot. The Claude login must be a subscription, not an API key. The fleet unsets the key
variable at spawn, so a lane that finds no subscription stops instead of billing something.

## Reaching the dashboard

The dashboard shows every agent and the check queue, and it can start and stop things, so it
is never left open to the internet. Two ways in:

- **Tailscale** (recommended). A private network between your devices; free for personal use.
  `sudo tailscale up` on the farm, the app on your laptop, and the dashboard is at
  `http://<farm's tailscale address>:7878`. The installer offers to set this up.
- **An ssh tunnel.** No extra software: `ssh -N -L 7878:127.0.0.1:7878 farm` on your laptop,
  then `http://127.0.0.1:7878`. The tunnel lives as long as that terminal.

Either way the page asks for a token once per browser. Get it with `fleet dashboard token` and
open `http://...:7878/?token=<it>`; the tab remembers.

## Security in four lines

- The only port open to the world is ssh, with a key, not a password. Every VPS provider has a
  firewall screen: allow 22, deny the rest. The dashboard never appears there.
- Agents run as your user with your logins. Give them a GitHub account or a machine that you
  would be comfortable seeing push to your repositories, because that is what they do.
- The head office repository is private. Anyone who can read it can read every message your
  agents ever sent.
- A lane's worktree is disposable. Anything worth keeping is pushed or written to a pull
  request before the janitor comes, which is every ten minutes.

## When something is off

```bash
fleet capacity                 # can the farm take another agent, and why not
fleet status                   # every lane plus RAM, load, temperature
systemctl --user status fleet-daemon fleet-dashboard   # the two long-lived services
hq whoami                      # the name this session would sign with
gh auth status                 # the GitHub login
```

The list of ways the farm bites, each with its fix, is `docs/sharp-edges.md` in the fleet
repository. Read it once before the first night.
