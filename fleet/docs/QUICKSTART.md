# Quickstart: from a fresh box to a first pull request

Ten steps turn a plain Linux machine into a **farm**: an always-on machine where coding agents
work while nobody watches. At the end, one agent has opened a pull request on your repository.
Each agent works as a **lane**: one task, on its own branch, in its own git worktree.

Replace `<FARM_HOST>` (the farm's ssh host alias), `<PROJECT>`, `<OWNER>/<REPO>`, `<LANE>` and
`<CODENAME>` with your own values. The full guide is [`OPERATIONS.md`](OPERATIONS.md). The ways a
farm can lose work are in [`sharp-edges.md`](sharp-edges.md).

**Shortcut.** On Ubuntu or Debian, [`farm/install.sh`](../../farm) does steps 1, 2, 3 and 5 in one
command. If Python is too old, it stops and prints the line from step 1. It also installs Claude
Code and sets up the [head office](#head-office-is-optional). Then continue with step 4 to log in,
and with step 7. [Chapter 12 of the handbook](../../docs/12-the-machine.md) explains it.

murmur supports two engines, Claude Code and Codex, on your own Linux machine or on a DigitalOcean
Droplet. Anything else is a contribution: see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

---

## Set up a farm, step by step

### 1. Get a box with systemd

Use Ubuntu 22.04 or newer, Debian 12, or another Linux with systemd. It can be a spare PC, a
virtual machine, or a DigitalOcean Droplet. The `/murmur:farm` command of the murmur Claude Code
plugin can create a Droplet from your laptop and install murmur on it. On Windows, use WSL2 with
Ubuntu, with systemd running inside it. The farm needs CPU and memory, not a GPU. fleet runs as an
ordinary user and never needs root; only installing packages uses `sudo`.

```bash
sudo apt update && sudo apt install -y git tmux python3 curl
python3 -V          # must be 3.11 or newer
```

Ubuntu 24.04 and newer, and Debian 12, ship Python 3.11 or newer. Ubuntu 22.04 ships 3.10. There,
add 3.11 from the deadsnakes PPA and put it first on `PATH`. The system's own `/usr/bin/python3`
stays 3.10, because apt needs it. Then check again:

```bash
sudo apt-get install -y software-properties-common && sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt-get install -y python3.11 python3.11-venv && sudo ln -sf /usr/bin/python3.11 /usr/local/bin/python3 && hash -r
python3 -V          # Python 3.11.x
```

### 2. Let user services run when nobody is logged in

```bash
loginctl enable-linger "$USER"              # use sudo if it asks for permission
systemctl --user is-system-running          # "running", or "degraded" but answering
```

These run as systemd user services: the agents themselves, the sweep timer (the janitor that
clears finished worktrees), the supervisor daemon (it restarts lanes that have a restart policy)
and, once you enable it in step 9, the dashboard. Without linger, systemd stops them all when your
last ssh session closes. This is the most common setup mistake.

### 3. Install GitHub's CLI and log in

```bash
sudo apt install -y gh        # or GitHub's own apt repository, for a newer version
gh auth login                 # choose HTTPS, and let it set up git credentials
gh auth status
```

Agents push branches and open pull requests through this login. The sweep asks GitHub whether a
branch was merged. Without `gh`, a lane cannot finish.

### 4. Install an agent CLI and log in on a subscription

Install Claude Code, Codex, or both. murmur's own installer installs Claude Code with:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

fleet starts Claude Code from `~/.local/bin/claude` (the `CLAUDE_BIN` variable changes it) and
Codex from `/usr/bin/codex` (set `FLEET_CODEX_BIN` in `~/.config/fleet/env` to change it).

Log in once, interactively, from a terminal:

```bash
ssh -t <FARM_HOST> claude                               # then type /login
ssh -L 1455:localhost:1455 -t <FARM_HOST> codex login   # the tunnel carries the login callback
```

If you are already on the farm, leave out the `ssh` part. Log in on a **subscription**, not an API
key. fleet removes `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` from every lane, so a lane cannot bill
an API account by accident.

### 5. Install the fleet

```bash
git clone https://github.com/magik-ai/murmur ~/work/murmur
cd ~/work/murmur/fleet && ./install.sh       # add --local if you work on the farm itself
```

The installer prints what it did: the `fleet` command in `~/.local/bin`, the orchestrator skill
(the playbook for the session that splits work into lanes), the example configs in
`~/.config/fleet/`, and the sweep timer. Add `~/.local/bin` to your `PATH`
if it tells you to. `--local` records a dashboard address that only this machine can reach, and
skips the advice about laptops.

### 6. If the farm is remote, shim it from your own machine

Do not install fleet a second time on your laptop. Add this small script instead. It runs each
`fleet` command on the farm over ssh, and quotes every argument, so briefs with quotes and line
breaks arrive intact:

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/fleet <<'EOF'
#!/usr/bin/env bash
args=(); for a in "$@"; do args+=("$(printf %q "$a")"); done
exec ssh <FARM_HOST> "\$HOME/.local/bin/fleet ${args[*]}"
EOF
chmod +x ~/.local/bin/fleet
fleet capacity        # answers from the farm
```

### 7. Register your project

```bash
fleet add-project --name <PROJECT> --repo <OWNER>/<REPO> --port-base 5200
fleet projects
```

This clones the repository to `~/work/<PROJECT>` and records it in
`~/.config/fleet/projects.toml`. A lane's dev server port is the project's `--port-base` (default
5200) plus a slot number. Give each project its own port base.

### 8. Spawn the first lane

```bash
fleet capacity
fleet spawn --project <PROJECT> --lane <LANE> --model sonnet --by <CODENAME> \
      --task "Fix X. Acceptance: the new test fails before the change and passes after."
```

Write the brief as an acceptance contract, not a wish. `--by` is your code name: it tags who
spawned the lane, and the dashboard groups lanes by it. The lane gets a fresh worktree from the
project's base branch, its own ports, and one pass at the work. Put a long brief, or one full of
quotes, in a file: `--brief-file ~/.fleet/briefs/<LANE>.md`. To have fleet start the lane again
until its pull request is merged, add `--restart until-merged` and start the supervisor daemon
with `fleet daemon start`.

### 9. Watch it

```bash
fleet status                  # every lane, and the farm's health
fleet status --json           # the same, for scripts
fleet tail <slug>             # one lane: status, pull request, last message
fleet events --follow         # the event stream: spawned, status, delivered, dropped-scope
fleet dashboard start         # the dashboard on 127.0.0.1:7878; a spawn also starts it
fleet dashboard token         # the token the dashboard needs before it can change anything
fleet dashboard status        # is it running, and on which address
fleet dashboard restart       # after you change its address, title or token
fleet dashboard stop          # stop it with this command, never with a pattern kill
fleet dashboard enable        # run it as a user service that comes back after a reboot
```

`<slug>` is the lane's unique id, printed by `fleet spawn`. Read `fleet events` and
`fleet status --json` rather than grepping log files.

Open the dashboard once as `http://127.0.0.1:7878/?token=<token>`. The browser tab keeps the token
until you close it. From a laptop, open a tunnel first, then use the same address on the laptop:

```bash
ssh -N -L 7878:127.0.0.1:7878 <FARM_HOST>
```

| Tab | What it answers |
|---|---|
| Board | Who is working on what, and is the machine healthy? The screen to keep open |
| Mail | What did the agents say to each other? You can reply to one of them here |
| Machine | Power, services, machines, subscriptions, models and projects |

The power setting is in the header of every tab. It is the same setting as `fleet mode`:

| Dashboard | `fleet mode` | What it does |
|---|---|---|
| Full | `full` | the agents may use every core |
| Shared | `soft` | the agents give way to whatever else runs; new lanes still start |
| Background | `balanced` | the agents keep a small share; no new lane starts |
| Paused | `hard` | the agents are held back hard; no new lane starts |
| Automatic | `auto` | Full, or Shared while the GPU is busy; Full when there is no GPU sensor |

Press Ctrl+K or Cmd+K on any tab to jump to a tab, a lane, a project or a conversation.
[`OPERATIONS.md`](OPERATIONS.md#5-the-dashboard) describes each tab in full.

### 10. Review, merge, clean up

The lane ends by opening a pull request and stopping. **It never merges: merging is your
decision.** Review the pull request on GitHub like any other contribution.

```bash
gh pr view <N> --web
fleet sweep --dry-run         # what the janitor would remove on its next pass
fleet clean --project <PROJECT>
```

The sweep runs every 10 minutes. It removes the worktree of a merged lane. About 15 minutes after
a lane ends, it also clears the lane's card and worktree, unless its pull request is still open.
It keeps uncommitted work, and before it removes a worktree it pushes commits that were never
pushed to `refs/fleet-salvage/<slug>`. Commit and push, and your work is safe.

---

## The everyday loop, once it is set up

```bash
fleet capacity                       # can the farm take another agent?
fleet accounts                       # each Claude subscription's session and weekly use
fleet spawn --project <PROJECT> --lane <LANE> --model sonnet --effort high --task "..."
fleet status                         # lanes plus farm health
fleet logs <slug>                    # one lane's raw output, followed live
fleet msg <slug> "rebase on main before pushing"    # read at the lane's next checkpoint
fleet kill <slug>                    # stop a lane; add --retire so nothing respawns it
fleet clean --project <PROJECT>      # after the merges
```

## Picking an engine and a tier

| Work | Engine and tier |
|---|---|
| hard, unclear, architecture, review | `--model opus --effort xhigh`, or `--engine codex --effort high` |
| an ordinary feature lane | `--model sonnet --effort high` |
| mechanical and well specified | `--model haiku`, or `--engine codex --effort low` |
| one subscription is running hot | the other engine at the same tier: it is a separate pool |

Claude Code is the default engine, and `--model` sets its tier. For Codex, `--effort` sets the
tier on one model. `--effort low|medium|high|xhigh` works on both engines. Claude lanes use
`--account auto` unless you name an account: it spreads lanes across the subscriptions that still
have room. `fleet accounts balance` names the next engine and account to use.

## Head office is optional

The **head office** is a private GitHub repository that agents use for names, branch claims and
messages, through the `hq` command (see [`hq/`](../../hq)). When `hq` is on the farm's `PATH`, each
lane claims its branch, gets a pre-push hook that refuses a branch someone else has claimed, and
starts with its unread mail. `~/.config/fleet/policy.toml` switches it:

```toml
[hq]
enabled = true     # false: spawn without the claim, the hook and the mail
```

Without `hq` on `PATH`, lanes spawn without any of this, and fleet says nothing. With `hq` on
`PATH` but no `[hq]` table, head office stays on, and every spawn prints a warning until you add
the table.

## Golden rules

- One lane is one coherent slice of work. Lanes that change the same files collide when you merge.
- Agents open pull requests and stop. Merging is always your call.
- If `fleet capacity` says `warn`, spawn fewer. If it says `BLOCK`, wait. The capacity check
  blocks only on hardware: memory, disk and temperature.
- Only committed and pushed work is safe. An open pull request protects a worktree for as long as
  it is open. `--force` on `clean` or `sweep` removes uncommitted work.
- Give every lane its own test database, and let it use the ports fleet gives it.
