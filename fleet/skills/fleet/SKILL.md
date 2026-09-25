---
name: fleet
description: Drive a farm of headless coding agents with the fleet command. Trigger on "spawn agents on the farm", "fan this out" or "fleet mode". Split a batch into lanes, spawn one headless Claude Code or Codex agent per lane, track each lane to a pull request, and merge only on the user's explicit signal.
---

# Fleet mode

`fleet` spawns and tracks headless coding agents (Claude Code or Codex) on a
farm: an always-on Linux machine, either this one or one you reach over ssh.
Each agent works one lane: one self-contained slice of work, in its own git
worktree, on its own branch, driven to a pull request. Then it stops. You are
the orchestrator. You split the work, get the user's go-ahead, spawn, watch,
and merge only when the user says so.

These instructions are about the farm, not about any one project. Do not copy
them into a project's repository.

## Code name and mark

The user gives you a code name. Confirm it with the user before the first
spawn, and pass it on every spawn with `--by <codename>`. The dashboard groups
lanes by it, and head office mail about your lanes reaches you under it.

Your code name has one mark on the dashboard: an emoji and a colour. On your
first spawn, pick ones that suit the name (for `spider`, say, a spider emoji
and a purple) and pass them with `--icon <emoji> --color <hex>`. The farm
registers the mark then and keeps it for every later spawn, whatever you pass.
To change it later, run `fleet identity <codename> --icon <emoji> --color
<hex>`. Without `--icon` and `--color`, the farm picks a mark from the name.

**If the farm uses the head office (see below), check the name before you use
it: `hq whoami`.** It prints the name `hq` would sign with and where that name
came from. It exits 1 when there is no name, or when the name is not this
session's own. A code name belongs to one session: after `hq bye` you have
none, and a code name you find in project memory belongs to a different agent.
If you spawn with someone else's name in `--by`, your lanes land under their
card on the dashboard, and mail about those lanes reaches them, not you. If
`hq whoami` warns, run `hq hello <your-name>` in this session first, then
spawn.

## The flow

Never spawn without an explicit go from the user.

0. **Identity and accounts.** If the farm uses the head office, check your
   name first (`hq whoami`, above). Then run
   `fleet accounts`. It prints one line per Claude subscription account: its
   session and weekly use in percent, any per-model window, and `<- pick` on
   the account with the most room. Lanes draw on the same subscriptions that
   people use for their own sessions. A spawn without `--account` takes
   `auto`: it takes turns over every account under 95% of its session and
   weekly windows, and it prefers accounts under 80% of their session window,
   so a long lane does not hit the session cap halfway. If every account is
   nearly full, tell the user and hold: a lane on a full account dies on its
   first step without doing anything. Pass `--account <name>` only when a
   lane must use that one account (Claude lanes only; Codex lanes refuse it).
   When a lane died on a usage limit, spawn it again once an account has room.
1. **Split into lanes.** Divide the batch into self-contained lanes: disjoint
   files, no shared state. One coherent slice of work is one lane. If the
   project describes how it splits work into lanes (for example in its
   `CLAUDE.md`), follow that.
2. **Propose.** Tell the user the lanes, how many agents, and which engine and
   tier each lane gets (see "Engines and tiers"). Wait for explicit approval.
   Do not spawn on an implied yes.
3. **Check capacity.** Run `fleet capacity` right before you spawn
   (`fleet metrics` has the detail). It prints `OK` or `BLOCK`, the level in
   brackets (`ok`, `warn` or `block`) and the reasons. On `BLOCK` or `[warn]`,
   tell the user and either hold or spawn fewer agents. Never overload the
   farm, and never pass `--force` unless the user asks for it.
4. **Spawn**, one call per approved lane:

   ```bash
   fleet spawn --project <name> --lane <lane> --model <opus|sonnet|haiku> \
       --by <codename> --task "<brief>"          # --account defaults to auto
   ```

   Name the lane with letters, digits, `.`, `_` and `-` only, starting with a
   letter or digit. The project and your code name follow the same rule, and
   `fleet spawn` refuses any other name.

   Use `--issue <N>` instead of `--task` to have the agent start from a
   GitHub issue. For a long brief, or one full of quotes, write it to a file
   on the farm and pass `--brief-file`:

   ```bash
   ssh <farm> 'mkdir -p ~/.fleet/briefs && cat > ~/.fleet/briefs/<lane>.md' <<'BRIEF'
   ...the brief...
   BRIEF
   fleet spawn --project <name> --lane <lane> --by <codename> \
       --brief-file <farm-home>/.fleet/briefs/<lane>.md
   ```

   Give `--brief-file` the file's full path on the farm (`ssh <farm> 'echo ~'`
   prints the farm's home directory). Through the ssh shim, your own shell
   would turn `~` into your laptop's home directory. On the farm itself,
   `~/.fleet/briefs/<lane>.md` works as it is.

   A good brief states the concrete task and how to tell it is done. `fleet`
   already adds the rules every lane needs, from `fleet/lib/brief_template.md`:
   the worktree, the ports, a private test database, the inbox, how to finish.
   Do not repeat them in the brief.

   To have the farm start a lane again until it delivers, add
   `--restart until-pr` or `--restart until-merged`. To start a lane only once
   another has delivered, add `--after <lane>` (it waits for that lane's pull
   request to merge; `--after <lane>:pr-open` waits for it to open). Both need
   the supervisor running: `fleet daemon start`, and `fleet daemon status` to
   check it.
5. **Track.** `<slug>` is the lane's unique id, printed by `fleet spawn`.
   - `fleet status [--project X]` lists every lane plus the farm's health:
     load, RAM, swap, CPU and GPU readings when there are sensors, the agent
     count and the capacity level. `fleet status --json` is for scripts.
   - `fleet tail <slug>` shows one lane: status, pull request, last message.
   - `fleet events --follow` streams what happens (spawned, status, delivered,
     respawned, dropped-scope). Read it instead of polling logs.
   - `fleet logs <slug>` follows one lane's raw output.
   - `fleet msg <slug> "..."` corrects a lane without restarting it. The lane
     reads its inbox at its next checkpoint.
   - `fleet dashboard start` serves a live page on `127.0.0.1:7878`; every
     spawn also starts it. `FLEET_DASH_BIND` makes it reachable from another
     machine, and changing anything on the page needs the token that
     `fleet dashboard token` prints.
6. **Collect and merge.** A lane whose status is `pr_open` is done: it opened
   a pull request and stopped. Other end states are `done_no_pr` (finished
   without a pull request), `failed`, `ended` and `killed`, and the daemon
   writes `delivered` and `gave_up`. Review each pull request on GitHub (for
   example `gh pr view <N>` and `gh pr checks <N>`) and get its checks green.
   A lane is one pass: its agent has exited, so review comments never reach
   it. To act on a review, spawn a new lane with the findings in its brief (it
   starts on a new branch and opens a new pull request), or ask the user.
   **The user decides what merges.** After the user's explicit yes, the
   conductor merges it if one runs; otherwise you do. Lanes never merge, and
   green checks alone are never a yes.

## Engines and tiers

- **Opus** (`--model opus`): hard, unclear, architectural or risky slices.
  Also use it to review other agents' pull requests.
- **Sonnet** (`--model sonnet`): ordinary, well-scoped slices. It is the
  default.
- **Haiku** (`--model haiku`): mechanical work such as docs, renames and small
  fixes.
- **Codex** (`--engine codex`): one model, with the tier set by
  `--effort low|medium|high|xhigh` (default `medium`). `--effort` works on
  Claude lanes too, but which levels exist depends on the Claude model.

## What you sequence (lanes do not)

Each lane is told, by `fleet/lib/brief_template.md`, not to decide things that
depend on other lanes. Those are yours:

- **Migration numbers.** A lane whose pull request adds a database migration
  says so in its final report and in its pull request. Track these. The first
  one to merge keeps its number. Before you merge the next, have it renumbered
  (or re-parented onto the new latest migration) and checked again. If the
  project's migration tool can detect two migrations that collide, have CI run
  that check.
- **Merge order.** Disjoint lanes can merge in any order. When two lanes touch
  a shared file or interface, decide the order yourself, and bring the later
  one up to date with the base branch before you merge it.

## Grouped lanes: one integration pull request (`fleet group`)

When several lanes build one change together, do not put them on one shared
branch, and do not let each open its own pull request. Two agents on one
branch under one identity push and revert each other's work, and nobody can
tell whose commit is whose. A lane must never push to a pull request someone
else is driving, least of all one that is in the merge queue: take it out of
the queue first.

The rule: each lane works on its own branch, inside a declared set of
files (its territory), and no lane opens a pull request. You assemble the lane
branches into one integration branch and one pull request. It merges like any
other pull request: after the user's yes, by the conductor if one runs,
otherwise by you. The lanes run on the farm; assembly stays with you.

- **Territories must not overlap.** `fleet group start` reads a TOML spec and
  refuses overlapping globs before a single agent spawns.
- **A pre-push check guards each territory.** A lane cannot push a change to a
  file outside its territory, or inside a sibling's; such a lane is marked
  blocked. (The lane's pre-push hook runs `fleet group guard`; you do not run
  it yourself.)
- **Each lane commits under its own author** (`group-<group>-<lane>`), so the
  assembly and `git log` show whose slice each commit is.
- **A merge conflict at assembly is the collision detector, not an error to
  fix.** `assemble` stops, reports the files and lanes that collide, and never
  resolves a conflict itself. Disjoint lanes merge cleanly.
- **`assemble --dry-run`** merges the pushed lanes and runs the checks, then
  stops before it pushes or opens the pull request. Like a real run, it prints
  the merge order and each lane's files first.

```text
fleet group start NAME --project X --spec FILE   # spawn the lane branches
fleet group status NAME [--json]                 # working | pushed | blocked | collision
fleet group assemble NAME [--dry-run]            # integration branch -> one pull request
```

A spec has one `[[lanes]]` table per lane. `territory` is one glob or a list
of globs. Each lane needs exactly one of `task` (the brief itself) or `brief`
(a file, relative to the spec). `engine`, `model`, `effort` and `by` are
optional:

```toml
[[lanes]]
name = "api"
territory = ["server/export/**"]
task = "Add the export endpoint. Done when its tests pass."

[[lanes]]
name = "ui"
territory = "web/src/export/**"
brief = "briefs/ui.md"
model = "opus"
```

**Who owns a branch.** Before you spawn any lane onto an existing branch or
pull request, check whether another orchestrator is already driving it
(`fleet status` for live lanes in that area, `gh pr view` for who is active).
If someone is, leave it alone: a second orchestrator on that branch only gets
in the way.

## Command reference

```text
fleet accounts                   each Claude account's session and weekly use, and the pick
fleet capacity                   can the farm take another agent now?
fleet metrics                    full farm telemetry (JSON)
fleet spawn --project X --lane L --by <codename> (--task "..." | --issue N | --brief-file F)
            [--engine claude|codex] [--model M] [--effort low|medium|high|xhigh]
            [--account auto|<name>] [--icon <emoji>] [--color <hex>]
            [--restart until-pr|until-merged|until-file:<path>]
            [--after <lane>[:pr-open|pr-merged]] [--force]
fleet status [--project X] [--json]   every lane plus farm health
fleet tail <slug>                one lane: status, pull request, last message
fleet events [--follow] [--lane L] [--project X]   the event stream
fleet logs <slug>                follow one lane's raw output
fleet msg <slug> ["text"]        write to a lane's inbox (no text: read it)
fleet kill [--retire] <slug>     stop a lane; --retire also stops its respawns
fleet salvage <slug>             commit and push a lane's work before a clean
fleet clean [--project X] [--by <codename>] [--dry-run]
                                 remove finished lanes' worktrees that hold no unsaved work
fleet sweep --dry-run            what the next sweep would remove
fleet daemon start|stop|status   the supervisor behind --restart and --after
fleet group start|status|assemble   grouped lanes -> one integration pull request
fleet add-project --name N --repo owner/name [--branch B] [--port-base 5200]
fleet projects                   list registered projects
fleet identity [<name>] [--icon E] [--color C]   show or set a code name's mark
fleet dashboard start|stop|restart|status|token|enable
                                 the web dashboard (127.0.0.1:7878); `token` prints
                                 the bearer token a write needs
```

If the farm is another machine, `fleet` on your side is usually a small ssh
shim that runs the same command on the farm (see `fleet/README.md`).
It behaves the same, but paths in its output are paths on the farm, and a `~`
you type is expanded on your side before the shim sends it.

## Head office (optional)

The head office is a private GitHub repository that agents use for names,
branch claims and messages, through the `hq` command. `fleet` uses it when
`hq` is on the farm's `PATH` and `[hq] enabled` in
`~/.config/fleet/policy.toml` is not `false`. Then every lane gets a claim on
its branch, a pre-push hook that refuses a branch someone else has claimed, and
its unread `hq` mail in its first prompt. A farm without `hq` does none of
this.

When the farm uses the head office, you as the orchestrator also:

- run `hq hello <codename>` at the start. If the user never gave you a code
  name, ask for one; never invent it;
- run `hq claim <branch>` for any integration or review branch you create
  yourself;
- check `hq who` and `hq claims` before you assign territories: a claimed
  branch is someone's live lane;
- settle questions between lanes with `hq msg <agent> "..."`, rather than
  routing every question through the user.

## The sweep

The sweep, `fleet sweep`, runs every 10 minutes. It removes the
worktrees of merged branches. It archives the cards of finished lanes about 15
minutes after they end, and removes their worktrees too. Only pushed work and
open pull requests are truly safe. A worktree with uncommitted changes, tracked
or untracked, is kept until someone runs `fleet sweep --force`, which saves the
changes first. Commits that were never pushed are pushed to
`refs/fleet-salvage/<slug>` before a worktree is removed. The full rules are in
[fleet/docs/SWEEP.md](../../docs/SWEEP.md). As the orchestrator, make sure your
lanes push their work and finish where people read it (pull request, issue or
report), never only in a worktree.
