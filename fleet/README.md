# fleet

fleet runs many coding agents at once on one Linux machine, which murmur calls a **farm**. It
starts Claude Code and Codex agents headless (no chat window, nobody typing), gives each one its
own git worktree and branch, and shows them all on a web dashboard. It is for people who already
use coding agents and want to run more of them than a laptop can hold, or keep them working while
the laptop is closed.

A **lane** is one agent doing one task on its own branch. The **orchestrator** is the agent (or
the person) that splits the work into lanes and starts them. The handbook's
[glossary](../docs/00-start-here.md#words-this-handbook-uses) explains the other words.

fleet works with any repository. Each agent reads that repository's own `CLAUDE.md` and follows
its rules. fleet is one part of murmur; the [main README](../README.md) describes the others.

## Install

The farm needs Linux with systemd, Python 3.11 or newer, git, tmux, the GitHub CLI (`gh`) logged
in, and Claude Code or Codex logged in on a subscription. [`docs/QUICKSTART.md`](docs/QUICKSTART.md)
walks through each one.

On the farm, clone murmur, run the installer, and register the repository your agents will work
on:

```bash
git clone https://github.com/magik-ai/murmur ~/work/murmur
cd ~/work/murmur/fleet && ./install.sh
export PATH="$HOME/.local/bin:$PATH"   # if install.sh said so
fleet add-project --name myproj --repo your-org/your-repo   # clones it to ~/work/myproj
```

`install.sh` links the `fleet` command into `~/.local/bin` and the orchestrator skill into
`~/.claude/skills/fleet`. It copies the example `policy.toml` and `projects.toml` into
`~/.config/fleet/`, and never overwrites your own copies. It also turns on a timer that runs
`fleet sweep` every 10 minutes: the **sweep** removes the worktrees of finished lanes.
`./install.sh --help` lists its options.

On a fresh Ubuntu or Debian machine, [`farm/install.sh`](../farm) does all of this in one command.
It also installs the system packages and Claude Code, and runs the dashboard as a service. It
sets up the **head office** too: a private GitHub repository that agents use for names, branch
claims and messages. See [chapter 12 of the handbook](../docs/12-the-machine.md).

### Optional: drive the farm from your laptop

You can work on the farm directly. If you would rather type `fleet` commands on your laptop, do
not install fleet there. Put the small script below on the laptop instead. It sends each `fleet`
command to the farm over ssh. It quotes every argument, so a brief with quotes or line breaks
arrives unchanged. It calls fleet by its full path, because a command run over ssh usually has no
`~/.local/bin` on its `PATH`.

`farm` is the farm's ssh host alias. `/murmur:farm` adds it to your `~/.ssh/config`. For any
other machine, add it there yourself:

```text
Host farm
  HostName <the farm's address>
  User <your user on the farm>
```

Then create the script:

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/fleet <<'EOF'
#!/usr/bin/env bash
# Run fleet on the farm over ssh, with every argument quoted for the remote shell.
args=(); for a in "$@"; do args+=("$(printf %q "$a")"); done
exec ssh farm "\$HOME/.local/bin/fleet ${args[*]}"
EOF
chmod +x ~/.local/bin/fleet
fleet capacity      # the answer now comes from the farm
```

## Use

```bash
fleet capacity                    # can the farm take another agent?
fleet spawn --project myproj --lane login-form --model sonnet \
      --task "Add a login form. Acceptance: the new test fails before and passes after."
fleet status                      # every lane, and the farm's health
fleet tail <slug>                 # one lane: status, pull request, last message
fleet logs <slug>                 # one lane's raw output, followed live
fleet dashboard start             # the web dashboard on http://127.0.0.1:7878
fleet dashboard token             # the token the dashboard needs to change anything
fleet clean --project myproj      # remove the worktrees of finished lanes
```

`fleet spawn` prints the lane's **slug**, its unique id: the lane name, the time and a number.
Give the task in one of three ways: `--task "..."` (inline), `--brief-file <path>` (a file on the
farm, best for long briefs), or `--issue N` (the agent reads that GitHub issue). `fleet help`
lists every command.

A lane is one pass. Its agent works until it opens a pull request, and then it exits. It does not
wait for review, and review comments do not reach it. To act on a review, fix the branch yourself,
or spawn a new lane with the findings in its brief. A new lane always starts on a new branch.

You decide what merges. After your yes, the conductor (the agent that takes approved pull
requests through the merge queue) merges it, or the orchestrator if you run no conductor. Lanes
never merge.

### The dashboard

The dashboard is a web page with three tabs:

- **Board** is the screen to keep open. It shows the machine's load, memory, disk and (where there
  is a sensor) temperatures, one card per subscription with its usage limits, and every lane with
  its status, model, cost and pull request. Click a lane to read its brief, its result, its GitHub
  checks and its log, or to send it a message. While part of the setup is missing, the Board
  starts with a checklist of what to fix.
- **Mail** shows the messages the agents sent each other through the head office, as
  conversations. You can reply from this tab.
- **Machine** holds the controls: power, services, machines, subscriptions, models and projects.

From the page you can stop or retire a lane, send a lane a message, send head office mail, change
the power setting, and throttle, drain or resume the whole farm. You can also start and stop the
sweep timer and the supervisor daemon, which the page calls the agent runner. The daemon only
restarts lanes that have a restart policy: stopping it stops no running lane. You can add or
remove subscriptions, models, projects and machines too. A few things stay at a terminal: spawning
a lane, `fleet clean` and `fleet sweep`, storing a key for an engine you added
(`fleet models auth <id>` reads it from standard input), and restarting the dashboard itself.

Every change made through the page needs a bearer token, even from the farm itself. The dashboard
creates one on its first start, in `~/.config/fleet/dash-token`, unless you set
`FLEET_DASH_TOKEN`. `fleet dashboard token` prints it. Open the page once as
`http://127.0.0.1:7878/#token=<token>`, and that browser tab keeps it. A request from another
website is refused, whatever token it carries.

By default, the dashboard listens on `127.0.0.1` only. To reach it from your laptop, use a tunnel:
`ssh -N -L 7878:127.0.0.1:7878 farm`, then open the same address. You can also set
`FLEET_DASH_BIND` in `~/.config/fleet/env` and run `fleet dashboard restart`. With any address
other than loopback, reading the page needs the token too. The
[operations guide](docs/OPERATIONS.md#5-the-dashboard) has the details.

### Several lanes, one pull request

Use a **group** when several lanes each build one part of a single change. Each lane gets its own
branch, its own commit author and a **territory**: the files it may change. A push that changes
files outside the lane's territory is refused. When the lanes have pushed, `fleet group assemble`
merges them into one integration branch and opens one pull request.

```toml
branch_base = "main"

[[lanes]]
name = "lesson-screen"
brief = "briefs/lesson-screen.md"
territory = ["frontend/src/screens/lesson/**"]

[[lanes]]
name = "lesson-api"
task = "Add the lesson endpoint and focused tests."
territory = ["backend/api/lesson/**", "backend/tests/test_lesson*.py"]
engine = "codex"
effort = "high"
```

```bash
fleet group start lesson --project myproj --spec lesson-group.toml
fleet group status lesson --json
fleet group assemble lesson --dry-run   # the merge order and each lane's files; pushes nothing
fleet group assemble lesson             # pushes group/lesson/integration, opens one pull request
```

Every lane needs a territory and exactly one of `task` or `brief`. A spec whose territories
overlap is refused before any agent starts. Before it pushes, `assemble` checks the result for
conflict markers and syntax errors, and runs the project's `validation` command if
`projects.toml` sets one. If two lanes conflict, it stops and names the files. It never resolves
a conflict and never merges the pull request.

## How it works

- **Spawn.** `fleet spawn` checks capacity and the power setting. It then creates a worktree and a
  new branch from the project's base branch on `origin`, and hands the lane its port numbers. It
  starts the engine headless (for Claude Code, `claude -p` with `--output-format stream-json`) as
  a systemd user service in `fleet.slice`, so the power setting can cap its CPU and memory.
- **No permission prompts.** Nobody sits at a lane's keyboard, so Claude Code runs with
  `--dangerously-skip-permissions`, and Codex with `--dangerously-bypass-approvals-and-sandbox`,
  which switches off its approvals and its sandbox. A lane can run any command the farm's user
  can run. Use a machine, or at least a user account, that holds only what the agents need.
- **State.** The engine's output goes to `~/.fleet/logs/<slug>.jsonl` and is read into
  `~/.fleet/state/<slug>.json`: status, model, cost, tokens, last activity and pull request.
  `fleet status` and the dashboard read these files.
- **Framing.** Every lane gets the same extra instructions, from `lib/brief_template.md`: stay in
  your lane, use your own test database and the ports you were given, run only the tests you
  touched, open a pull request, never merge, and stop.
- **Capacity.** `lib/metrics.py` blocks a new spawn when free memory or free disk is below a floor,
  or when the GPU or CPU is too hot. The number of agents never blocks; it only raises a warning.
  With the default limits, a spawn needs 6 GB of free memory. On a machine with less than 12 GB,
  `farm/install.sh` lowers `ram_min_gb` and `warn_ram_gb` in `~/.config/fleet/policy.toml` to
  fit; after an install by hand, lower them yourself. A `warn` whose only reason is
  `CPU temp UNKNOWN` is normal on a machine without a temperature sensor.
- **Clean-up.** The sweep timer removes the worktree of a lane whose pull request has merged. It
  also clears finished lanes that have no open pull request, 15 minutes after they end. It keeps
  uncommitted work, and it saves commits that were never pushed to a hidden ref on `origin` first.

## Layout

```text
bin/fleet               the fleet command (bash)
lib/                    the Python behind it: capacity (metrics.py), power (mode.py), the
                        supervisor daemon (supervisor.py), engine output readers (parse_*.py),
                        and the instructions every lane gets (brief_template.md)
dashboard/              a standard-library HTTP server and the single-page dashboard
config/*.example.toml   example policy (limits, power, commit identity), projects and model catalog
systemd/                the user units: supervisor daemon, dashboard, sweep service and timer
skills/fleet/           the orchestrator skill
install.sh              links the command, the skill and the example configs into place
docs/                   the quickstart, the operations guide, the sweep rules, sharp edges, tests
```

Apart from `audit.log`, a record of kills and cleans that git ignores, nothing fleet writes at
runtime lives in the clone. State, logs and worktrees go to `~/.fleet/`, and settings to
`~/.config/fleet/` (`policy.toml`, `projects.toml`, `env`).

## The orchestrator skill

`skills/fleet/SKILL.md` is the orchestrator's playbook: how to split work into lanes, spawn
them, watch them, and merge only after your yes. `install.sh` links it into
`~/.claude/skills/fleet`, and into `~/.codex/skills/fleet` when `~/.codex` exists. It belongs to
your own setup. Do not copy it into a shared project repository.

## More documentation

| Document | What it covers |
|---|---|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | From a fresh machine to a first pull request, and the everyday commands |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Setup, access, daily running, recovery and troubleshooting |
| [`docs/SWEEP.md`](docs/SWEEP.md) | What the sweep removes, and how not to lose work to it |
| [`docs/sharp-edges.md`](docs/sharp-edges.md) | The failure modes that can destroy work, and their guards |
| [`docs/VERIFYING.md`](docs/VERIFYING.md) | How to run the test suites before you change fleet itself |
| [`../docs/12-the-machine.md`](../docs/12-the-machine.md) | Choosing the machine, and the one-command installer |
