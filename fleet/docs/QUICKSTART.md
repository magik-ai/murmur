# Quickstart: from a fresh box to a first pull request

Ten steps. At the end, a headless agent has opened a pull request on your repository from a machine
you are not sitting at. Full detail lives in [`OPERATIONS.md`](OPERATIONS.md); the ways this bites
are in [`sharp-edges.md`](sharp-edges.md).

Substitute your own values for `<FARM_HOST>`, `<PROJECT>`, `<OWNER>/<REPO>` and `<LANE>`.

---

### 1. Get a box with systemd

Any Ubuntu (22.04 or newer) or comparable systemd distribution: a spare desktop, a VM, a cloud
instance. It needs CPU and RAM rather than a GPU. Everything below runs as an ordinary user, and
nothing in the fleet needs root.

```bash
sudo apt update && sudo apt install -y git tmux python3 curl
python3 -V          # must be 3.11 or newer
```

### 2. Let user services run when nobody is logged in

```bash
loginctl enable-linger "$USER"
systemctl --user is-system-running          # running, or degraded but answering
```

Without linger, the sweep timer, the supervisor daemon and the CI queue die when your ssh session
closes. This is the single most common setup mistake.

### 3. Install GitHub's CLI and log in

```bash
sudo apt install -y gh        # or the upstream apt repository for a current version
gh auth login                 # choose HTTPS, and let it configure git credentials
gh auth status
```

Agents push branches and open pull requests through this login, and the janitor asks GitHub whether
a branch was merged. A farm without `gh` cannot finish a lane.

### 4. Install an agent CLI and log in on a subscription

Install `claude` and/or `codex`, then log in once, interactively, over a terminal session:

```bash
ssh -t <FARM_HOST> claude                     # then /login
ssh -L 1455:localhost:1455 -t <FARM_HOST> codex login   # the tunnel carries the OAuth callback back
```

Log in on a **subscription**, not an API key: the fleet unsets `ANTHROPIC_API_KEY` at spawn, so a
lane cannot quietly bill an API account. If the farm is the machine you are already on, drop the
`ssh` prefix.

### 5. Install the fleet

```bash
git clone https://github.com/magik-ai/murmur ~/work/murmur
cd ~/work/murmur/fleet && ./install.sh
```

It prints what it did: the launcher, the orchestrator skill, the example configs, the sweep timer.
On a single machine use `./install.sh --local`, which skips the ssh shim advice and records a
loopback dashboard bind. Add `~/.local/bin` to your PATH if the installer says so.

### 6. If the farm is remote, shim it from your own machine

```bash
printf '#!/usr/bin/env bash\nargs=(); for a in "$@"; do args+=("$(printf %%q "$a")"); done\nexec ssh <FARM_HOST> "$HOME/.local/bin/fleet ${args[*]}"\n' > ~/.local/bin/fleet
chmod +x ~/.local/bin/fleet
fleet capacity        # answers from the farm
```

Do not install the tool twice. The shim quotes every argument, which is what makes a brief with
quotes and newlines survive the trip.

### 7. Register your project

```bash
fleet add-project --name <PROJECT> --repo <OWNER>/<REPO>
fleet projects
```

This clones the repository to `~/work/<PROJECT>` and records it in `~/.config/fleet/projects.toml`.
Give each project its own `--port-base` so lanes from different projects never fight over a port.

### 8. Spawn the first lane

```bash
fleet capacity
fleet spawn --project <PROJECT> --lane <LANE> --model sonnet \
      --by <CODENAME> \
      --task "Fix X. Acceptance: the new test fails before the change and passes after."
```

Write the brief as an acceptance contract, not a wish. A lane gets a fresh worktree off the base
branch, its own ports, and one pass at the work. Long or punctuation-heavy briefs belong in a file:
`--brief-file ~/.fleet/briefs/<LANE>.md`. To have the work driven all the way to a merge instead of
one pass, add `--restart until-merged` and start the daemon (`fleet daemon start`).

### 9. Watch it

```bash
fleet status                  # every lane plus farm health
fleet tail <slug>             # one lane, human-readable, with its last message
fleet events --follow         # the event stream: spawned, status, delivered, dropped-scope
fleet dashboard start         # the board on 127.0.0.1:7878, started for you on the first spawn
fleet dashboard stop          # never a pattern kill, this is a shared service
fleet dashboard restart       # after changing the bind, the title or the token
fleet dashboard status        # is it running, and on what socket
fleet dashboard token         # the bearer token the board needs before it can change anything
```

Prefer `fleet events` and `fleet status --json` over grepping logs.

Open the board once as `http://127.0.0.1:7878/?token=<token>`. The tab keeps the token from then
on, so you paste it once per browser and never again. Reaching the board from another machine is
`FLEET_DASH_BIND` in `~/.config/fleet/env` plus `fleet dashboard restart`, and then the token
covers reading as well as writing.

The board is a small product of its own, four tabs down the left side:

| Tab | Answers, in one line |
|---|---|
| Board | who is running, what is being verified, is the machine healthy: the screen you keep open |
| Mail | what the agents said to each other, and where you reply to one of them |
| Queue | every merge-result verification run, and the log of the stage that failed |
| Machine | set up and run the farm: power, services, accounts, engines, projects, health, settings |

**The Board is the one to leave open.** Two strips sit under the header: the machine strip (load,
memory, disk, GPU, temperature, capacity, the countdown to the next sweep) and the accounts strip
(one card per subscription with its session and weekly bars and the reset countdown, red when it
is out of room). Below them the page is a two-pane canvas: agents on the left, the verification
queue on the right (running and waiting runs, plus a count of recent ones that links to the Queue
tab). One splitter between the panes is draggable, its position is remembered by your browser, and
under 1100 px the two panes stack into one column. Clicking an agent opens a drawer with its
brief, its result, its checks, its log and a box to send it a message.

While a prerequisite is still missing, or no agent has ever run on this farm, the Board is a setup
checklist instead: one line per step, with the spawn command already filled in with the name of
your first registered project. The checklist goes away on its own once the farm is complete.

The header carries the same controls on every tab: the product name (`FLEET_DASH_TITLE`), the
capacity pill with the reason on hover, a project filter, the freshness label, the jump palette,
the theme switch, and the power mode. The power mode is a four-state control, Full, Shared,
Background and Paused, plus Automatic, and it is the same setting as `fleet mode`: Full leaves
every core to the agents, Shared and Background hand CPU back to whatever else you are doing,
Paused stops new spawns, and Automatic picks one of the four from how busy the machine is.

Every live panel carries a freshness label, "Live" or "Stale" with a time, so you can always tell
whether you are looking at the current state or the last good read. Mail runs 45 seconds behind
the office by design, and the label is how you see that rather than guess at it.

Press Cmd+K (Ctrl+K on Linux and Windows) anywhere on the page to open the jump palette and go
straight to a tab, an agent, a project or a conversation. The switch in the header flips the whole
page between light and dark, and the choice is remembered per browser.

### 10. Review, merge, clean up

The lane ends by opening a pull request and stopping. **Merging is your decision, never the
agent's.** Review it on GitHub like any other contribution.

```bash
gh pr view <N> --web
fleet sweep --dry-run         # what the janitor would remove next pass
fleet clean --project <PROJECT>
```

After a merge, the janitor removes that worktree and reaps the card on its own within ten minutes.
Only pushed work is safe from it.

---

## The everyday loop, once it is set up

```bash
fleet capacity                       # can the farm take another agent?
fleet accounts                       # subscription windows and reset countdowns
fleet spawn --project <PROJECT> --lane <LANE> --model sonnet --effort high --task "..."
fleet status                         # lanes plus farm health
fleet logs <slug>                    # raw stream of one lane
fleet msg <slug> "rebase on main before pushing"    # a correction, read at the lane's next checkpoint
fleet clean --project <PROJECT>      # after the merges
```

## Picking an engine and a tier

| work | engine and tier |
|---|---|
| hard, ambiguous, architectural, review | `--model opus --effort xhigh`, or `--engine codex --effort high` |
| an ordinary feature lane | `--model sonnet --effort high` |
| mechanical and well specified | `--model haiku`, or `--engine codex --effort low` |
| one subscription is running hot | the other engine at the same tier, a separate pool |

`--effort low|medium|high|xhigh` works on both engines. With several subscriptions configured,
`--account auto` spreads a batch across the ones with headroom, and `fleet accounts balance` names
the next engine and account to use.

## Head office (agent-hq) is optional

Branch claims, the pre-push claims guard and the AGENT-HQ paragraph in every brief are a
deployment's own coordination layer. Fleet wires them up only when the `hq` CLI is on PATH, and
then `~/.config/fleet/policy.toml` decides:

```toml
[hq]
enabled = true     # or false to spawn without the claim, the hook and the mail
```

A box with no `hq` binary spawns exactly as before, minus all of it, and says nothing. A box that
has the binary but no `[hq]` table keeps head office ON and warns once per spawn until you write
the table, so an upgrade cannot drop a running farm's claims in silence.

## Golden rules

- One lane is one coherent slice of work. Overlapping lanes collide in the merge, not in the farm.
- Agents open pull requests and stop. Merging is always a human call.
- If capacity says amber or red, spawn fewer or wait. Hardware is the only hard gate.
- Only committed and pushed work survives the janitor. An open pull request protects a worktree
  indefinitely; untracked scratch protects nothing.
- Give every lane its own test database and its own ports. Shared ones are what stall a batch.
