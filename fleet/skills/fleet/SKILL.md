---
name: fleet
description: Enter Fleet mode to fan a batch of work out to headless Claude Code agents on a remote farm — trigger on "spawn agents on the farm", "fan this out", "fleet mode"; it spawns and tracks headless workers, each driving one lane to a PR, and merges only on the user's explicit signal.
---

# Fleet mode

`fleet` spawns and tracks headless Claude Code agents on a remote "farm" (a
spare machine, reachable over Tailscale/ssh). Each agent gets its own git
worktree, drives one self-contained slice of work to a PR, then stops. You
(the orchestrator) split the work, get the user's go-ahead, spawn, watch, and
merge only when the user says so.

**This is a personal orchestration capability. Never write these instructions
into a shared project repo — they belong here, or in the user's own
`~/.claude/CLAUDE.md`.**

## Code name & identity

The user gives you a **code name**. From it, YOU pick a fitting **emoji** and an accent **colour** that suit it — e.g. `spider` -> 🕷 + a purple, `vivaldi` -> 🎻 + a warm gold. Confirm the name (and your chosen emoji/colour) with the user before the first spawn.

Pass all three on **every** `fleet spawn`: `--by <name> --icon <emoji> --color <hex>`. All of your agents then share your emoji + colour, so the dashboard groups agents by which orchestrator spawned them. (Omit --icon/--color and the dashboard derives a stable colour from the name.)

**Check the name before you use it: `hq whoami`.** It prints the name hq would sign with and where that name came from, and exits 1 when the name is not this session's own. A codename is per SESSION: after `hq bye` you have none, and a codename found in project memory belongs to a different agent. Spawning with someone else's name in `--by` files your lanes under their card on the dashboard, and mail about those lanes reaches them, not you. If `hq whoami` warns, run `hq hello <your-name>` in THIS session first, then spawn.

## The flow (collaborative — never spawn without an explicit go)

0. **Balance check.** Identity first (`hq whoami`, above), then run `fleet accounts`: one line per Claude
   subscription with its session %, weekly % and scoped (Fable) %, and `<- pick` on the
   account with the most headroom. The Claude pool is **shared with the owner's own
   sessions** — a lane burns the same allowance he works in. `fleet spawn` without
   `--account` takes `auto`: a round-robin over every account under 95% of its session and
   weekly window, so parallel lanes spread evenly across subscriptions. It prefers accounts under 80% of their
   session window, so a long lane does not hit the session cap mid-run. If every account is
   near full, tell the user and hold — a lane on a full account dies on its first step
   without doing anything. Pass a specific `--account <name>` only to pin one on purpose.
   A lane that died on a limit is re-spawned fresh, not with `fleet respawn`.
1. **Split by lane.** Divide the batch into self-contained lanes — disjoint
   files, no shared state. One coherent slice of work = one agent. Check the
   target project for a lanes doc (often a "§17" or similar section in its own
   docs) if one exists.
2. **Propose.** Tell the user: the lanes, how many agents, and which model
   each lane gets (see heuristic below). Wait for explicit approval. Do not
   spawn on an implied yes.
3. **Capacity check.** Run `fleet capacity` (and `fleet metrics` for detail)
   right before spawning. If it reports `BLOCK` or a `WARN` level, tell the
   user and either hold or spawn fewer agents. Never overload the farm, and
   never pass `--force` without the user asking for it.
4. **Spawn**, one call per approved lane:
   ```
   fleet spawn --project <name> --lane <lane> --model <opus|sonnet|haiku> \
       --by <codename> --task "<brief>"          # --account defaults to auto
   ```
   Use `--issue N` instead of `--task` to have the agent read a GitHub issue
   first, or `--brief-file <path>` for a brief too long for a CLI arg — write
   it to a file on the farm first (e.g. `ssh farm "cat > ~/.fleet/briefs/<lane>.md" <<'B' ... B`),
   then pass `--brief-file ~/.fleet/briefs/<lane>.md`.
   A good brief states the concrete task and acceptance criteria; `fleet`
   already injects the workflow/lane/ports/DB-isolation rules for you via
   `lib/brief_template.md` — don't repeat those in the brief itself.
5. **Track.** `fleet status [--project X]` lists every agent plus farm health
   (load, RAM, swap, GPU, agent count, capacity level). `fleet logs <slug>`
   tails one agent's raw stream. `fleet dashboard start` serves a live
   single-page view on `127.0.0.1:7878` (auto-started on spawn too). Reaching it
   from another machine is `FLEET_DASH_BIND`, and changing anything on the page
   needs the token `fleet dashboard token` prints.
6. **Collect & merge.** An agent reaching `pr_open` status is done — it
   opened a PR and stopped on its own. Review it from GitHub (e.g. `/review
   <PR#>`, `gh pr checks`), drive CI green, and **merge only on the user's
   explicit signal** — never auto-merge just because CI is green.

## Model heuristic

- **Opus** — hard, ambiguous, architectural, or risky slices; also use it for
  reviewing other agents' PRs.
- **Sonnet** — ordinary, well-scoped slices (the default).
- **Haiku** — mechanical work: docs, renames, small fixes.

## Sequencing the orchestrator owns (agents don't)

Each spawned agent is told (via `lib/brief_template.md`) not to hardcode
sequencing decisions — that responsibility is yours:

- **Migration numbers.** If an agent's final report flags "adds a migration",
  track it. Whoever's PR lands first keeps its migration number; reparent the
  next one's `down_revision` onto the new head before merging it. CI should
  assert exactly one head.
- **Merge order.** Disjoint lanes can land in any order. If two lanes touch a
  shared file or contract, decide the order yourself and do a pre-merge
  freshness check (rebase/merge latest base into the later one) before
  merging.

## Grouped lanes — one integration PR (`fleet group`)

When several lanes contribute to ONE coherent change, do **not** put them on a
shared branch and do **not** let each open its own PR. Both have burned us:
two agents on one branch under one identity (#2822) produced endless
push/revert churn with no attribution, and a lane pushing to a PR someone else
was already driving ejected it from the merge queue and restarted a 35-min CI
cycle every time.

The contract: **each lane on its OWN branch, inside a declared file territory,
and NO lane opens a PR.** The orchestrator assembles the lane branches into one
integration branch → **one** PR → merge on the owner's word. Implementation is
on the farm; assembly and merge stay with you.

- **Territories are declared and must be disjoint.** Overlapping globs are
  refused at `start`, before a single agent spawns.
- **Territory-guard** blocks a push that touches a file outside the lane's own
  territory or inside a sibling's, and marks the lane blocked.
- **Per-lane commit identity** — each lane commits under its own git author, so
  assembly and `git log` show whose slice each commit is.
- **A merge conflict at assemble is the collision detector, not an error to
  fix.** Assemble aborts, reports the colliding files and lanes, and NEVER
  auto-resolves. Disjoint lanes merge clean by construction.
- `assemble --dry-run` prints the merge order and per-lane file sets first.

```
fleet group start NAME --project X --spec FILE   # spawn disjoint lane branches
fleet group status NAME [--json]                 # working|pushed|blocked|collision
fleet group assemble NAME [--dry-run]            # integration branch -> ONE PR
fleet group guard ...                            # the pre-push territory check
```

**Ownership rule (learned the hard way).** Before spawning ANY lane onto an
existing branch or PR, check whether another orchestrator is already driving it
(`fleet status` for live lanes in that area, `gh pr view` for who's active). If
someone is, hands off — a second orchestrator touching that branch is pure
interference even with good intentions.

## Command reference

```
fleet accounts                  per-account session/weekly usage and the next pick (step 0)
fleet spawn --project X --lane L --model opus|sonnet|haiku --by <codename>
            (--issue N | --task "..." | --brief-file f) [--account auto|<name>] [--force]
fleet status [--project X]      table of agents + farm health
fleet metrics                   full telemetry JSON (pretty)
fleet capacity                  can we spawn right now?
fleet logs <slug>               tail an agent's raw stream
fleet kill <slug>               stop an agent
fleet clean [--all]             remove finished agents' worktrees
fleet add-project --name N --repo owner/name [--port-base 5200]
fleet projects                  list registered projects
fleet dashboard start|stop|restart|status|token
                                web dashboard (127.0.0.1:7878; `token` prints
                                the bearer token a write needs)
fleet group start|status|assemble|guard   grouped lanes -> one integration PR
```

From a laptop that isn't the farm itself, `fleet …` runs identically via an
ssh shim — no behavior difference, just don't assume you're on the farm's
local filesystem when reasoning about paths.

## Agent HQ (coordination layer, optional)

Head office is a deployment's own coordination layer, not part of the harness. It
is wired in when the `hq` CLI is on PATH and `[hq] enabled` in
`~/.config/fleet/policy.toml` does not say `false`; a farm without the binary has
none of it and never mentions it. Where it IS on, every spawned lane gets an
attributable git author, a claim on its branch, the claims pre-push guard, and
unread `hq` mail folded into its launch prompt. As the ORCHESTRATOR you must
also: `hq hello <codename>` at start (if the user never gave you a codename, ASK
for one, never invent it; asking is the handshake that shows you know this
protocol), `hq claim` any integration or review branch you create yourself, check
`hq who` / `hq claims` before assigning territories (a claimed branch is
someone's live lane), and coordinate cross-lane questions with
`hq msg <agent> "..."` rather than routing every question through the user.

## Sweep awareness

The farm janitor (`fleet sweep`, every 10 min) buries terminal lanes: cards
vanish ~15 min after finishing, and only pushed work / OPEN PRs are truly safe.
A worktree with tracked uncommitted changes is kept (and reported) until someone
runs `fleet sweep --force`, which snapshots the dirt first; untracked scratch
protects nothing at all. Full contract: `docs/SWEEP.md` in the fleet repo. As
the orchestrator, make sure your lanes push their work and finish loudly (PR /
issue / report) - and never park results only in a worktree.
