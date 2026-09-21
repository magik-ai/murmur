# fleet

Spawn and track a fleet of **headless Claude Code agents** on a "farm": any
machine with spare cores, local or reachable over ssh (the one this was built on
is a WSL distro on a desktop PC). An orchestrator fans a batch of work out to the
farm: one agent per lane, each in its own git worktree, each driving a slice to
a pull request. A live dashboard shows the lot; the farm never overloads.

It's **project-agnostic**: point it at any repo. Each worker grounds itself in
that repo's own `CLAUDE.md`.

> **Everyday cheat sheet: [`docs/QUICKSTART.md`](docs/QUICKSTART.md).**
> Full setup, access, recovery and troubleshooting for the whole rig (farm +
> fleet): [`docs/OPERATIONS.md`](docs/OPERATIONS.md).
>
> How to run every check in this repo, and how to tell whether the farm is still in sync with
> the project: [`docs/VERIFYING.md`](docs/VERIFYING.md).
>
> Merge-result verification on the farm (an accelerator, never a merge
> authority): [`docs/CI.md`](docs/CI.md).
>
> Upgrading a farm that ran an older fleet: [`docs/MIGRATION.md`](docs/MIGRATION.md).

## Why

Past ~4-5 parallel agents a laptop dies (RAM, heat). The documented pattern is:
run the agents on a separate machine, pull finished branches back over git.
`fleet` is the thin harness that makes a Claude Code orchestrator do exactly
that, on the subscription (no API billing), with capacity guards so the box
stays healthy.

## Install (on the farm)

Clone this repository onto the machine that will run the agents, install it, and register the
first project:

```bash
git clone https://github.com/magik-ai/murmur ~/work/murmur   # fleet lives in murmur/fleet
cd ~/work/murmur/fleet && ./install.sh
fleet add-project --name myproj --repo owner/name   # clones the repo and registers it
```

`install.sh` puts `fleet` on your PATH and seeds `~/.config/fleet/` from `config/*.example.toml`.
Tune the capacity limits, the per-lane commit identity and the optional head-office integration in
`~/.config/fleet/policy.toml`; register further repos in `~/.config/fleet/projects.toml`.

### Optional: drive the farm from another machine

If you orchestrate from a laptop rather than on the farm itself, a one-line shim makes a local
`fleet` call run over ssh, so the orchestrator never has to know it is remote. Nothing requires
it, and working directly on the farm is fully supported.

```bash
printf '#!/usr/bin/env bash\nargs=(); for a in "$@"; do args+=("$(printf %%q "$a")"); done\nexec ssh farm "\$HOME/.local/bin/fleet ${args[*]}"\n' > ~/.local/bin/fleet
chmod +x ~/.local/bin/fleet   # `farm` is an ssh host alias for the farm machine
```

## Use

```bash
fleet capacity                       # can the farm take another agent?
fleet spawn --project myproj --lane battles --model sonnet \
      --task "Implement X. Acceptance: …"
fleet status                         # table of agents + farm health
fleet logs <slug>                    # tail one agent's raw stream
fleet dashboard start                # web view on 127.0.0.1:7878 (see FLEET_DASH_BIND)
fleet dashboard token                # the bearer token every write needs
fleet clean --all                    # remove finished agents' worktrees
```

Spawn a worker with `--issue N` (it reads the GitHub issue), `--task "…"`
(inline brief), or `--brief-file path` (a brief written on the farm).

The dashboard can stop an account and flip a model, so changing anything through it needs a
bearer token, on loopback as much as anywhere else, and a cross-site request is refused whatever
token it carries. The first start mints one into `~/.config/fleet/dash-token` (mode 600) unless
`FLEET_DASH_TOKEN` is set; `fleet dashboard token` prints it, and you open the page once as
`http://<bind>:7878/?token=<token>`. Widen the bind with `FLEET_DASH_BIND` and the token covers
reading too, because a lane's brief and its result are not public either.

### Grouped lanes, one PR

Use a group when several disjoint lanes contribute to one coherent change. Each
lane gets its own branch and author identity, and a pre-push territory guard;
only `group assemble` creates the integration PR.

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
fleet group assemble lesson --dry-run
fleet group assemble lesson       # pushes group/lesson/integration and opens one PR
```

Territories are mandatory and overlapping glob languages are rejected before
any worker starts. A collision during assembly is aborted and reported for
human resolution; Fleet never auto-resolves it or merges the resulting PR.

## How it works

- **spawn** → capacity check → fresh worktree off `origin/main` → deterministic
  ports → launches `claude -p "<brief>" --model … --output-format stream-json
  --dangerously-skip-permissions` in a detached `tmux` session.
- The stream is teed to a raw log and parsed into `~/.fleet/state/<slug>.json`
  (status, model, cost, tokens, last activity, PR url). The terminal `result`
  event marks the agent done.
- Each worker's **system framing** (`lib/brief_template.md`) enforces: stay in
  your lane, use a **private test DB** named by your agent-id (never the shared
  one), **don't run the full suite locally** (that's CI's job), don't hardcode a
  migration number. These are the traps that stall parallel agents.
- **Capacity** (`lib/metrics.py` + `config/policy.example.toml`; live overrides in `~/.config/fleet/policy.toml`) blocks a spawn when free
  RAM / agent count / GPU temp cross a limit.

## Layout

```
bin/fleet              CLI (bash)
lib/metrics.py         telemetry + capacity verdict (JSON)
lib/parse_stream.py    stream-json -> per-agent state file
lib/brief_template.md  system framing injected into every worker
dashboard/             stdlib HTTP server + single-page UI
config/*.example.toml  policy (limits) + projects (registry)
```

Runtime lives outside the repo: `~/.fleet/` (state, logs, worktrees) and
`~/.config/fleet/` (projects.toml, policy.toml).

## Not included

The orchestrator's own instructions ("how I fan out") belong in a user-level
`~/.claude/CLAUDE.md` plus a `/fleet` command, not here, so the tool stays
generic and never leaks into a shared project repo.
