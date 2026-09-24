# Start here

This handbook describes a way to run several coding agents on one repository as
a team. It gives every agent a role, keeps the rules in one file, and adds a few
small tools that enforce those rules. murmur ships the tools: a Claude Code
plugin, `fleet` for running agents on an always-on machine, and a coordination
command called `hq`. You can follow the method without them.

## Why a team of agents needs rules

One coding agent is easy to manage: you give it a task, watch it work and read
the diff. Ten agents at once is a different job. You are now running a team, and
a team needs what human teams have always needed:

- **One agent per piece of work.** Each piece of work belongs to one agent, so
  two agents never edit the same file at once and silently erase each other's
  changes.
- **A shared record.** The state of the work lives outside any one agent's
  context or any one person's head, because nobody can hold the whole picture.
- **Review by someone else.** Another agent or a person reads every change
  before it merges.
- **A merge process that tests changes together.** Two branches that each pass
  their own checks can still break each other when they land.

The method is not a smarter prompt, and it does not depend on one vendor's
agent. Most of it is discipline enforced by a script instead of by memory,
because memory is the first thing that fails under load. It assumes GitHub for
issues, pull requests and the merge queue. With another host, you map the steps
yourself.

## The four roles

Every session in a shared repository plays one of these roles at a time. The
role says what the session may and may not do.

**Owner.** The person whose product it is, usually you. You decide what ships,
how a feature should feel, and when a risky change may go out. You should not
have to read every diff, or open a pull request to find out what changed. A
decision that needs you should reach you as a plain question with a
recommendation.

**Orchestrator.** The agent (or the person) that splits a goal into lanes and
starts them. It writes no product code. It keeps two lanes from editing the
same file, and sets the order for the few shared files every lane wants. It
checks what lanes report before passing it on to you, and keeps the board up to
date. See [orchestration](04-orchestration.md).

**Lane.** One agent doing one task on its own branch: it writes the change,
gets it reviewed and opens the pull request. It owns a fixed set of paths and
touches nothing else. The urge to "fix something nearby while I am here" is a
reason to stop.

**Conductor (release manager).** Runs the merge queue: the order in which
changes merge, and what waits. It can stop any merge, however green the checks
are. It does not build features or decide product questions.

**Who merges.** You decide what merges. After your yes, the conductor (or the
orchestrator, if you run no conductor) merges it. Lanes never merge.

A team may add approvers, such as a technical owner who signs off on
architecture. They approve on top of the four roles; they are not a fifth role.

## Rules live in one file

Each repository keeps its rules in one place: what a change must include before
it merges, how review works, and what is forbidden. This handbook calls it the
law file. Every other document links to it instead of repeating it, because a
copied rule drifts and people follow the stale copy.

With the murmur plugin, the core rules live in `.murmur/contract.md`, and
`CLAUDE.md` (and `AGENTS.md`, if you keep one) points to it. Without the
plugin, `CLAUDE.md` holds the rules. [Repo law](01-repo-law.md) explains how to
write them.

## Week one, in order

Adopt the method one layer a day. Installing all of it at once produces a pile
of rules that nobody follows.

1. **Day 1: the law file and a pull request template.** Write the law file. Put
   one template on every pull request, so a reviewer (human or agent) always
   finds the same shape: what changed, why, and how it was checked. With the
   murmur plugin, `/murmur:init` writes a first version of both.
2. **Day 2: worktrees and a tracker.** One task gets one isolated working copy
   (a git worktree) and one branch. Every task is a ticket in a shared tracker
   before work starts, so "what is everyone doing?" has an answer.
3. **Day 3: review by someone who did not write the change.** Another agent or
   a person reads every change before it merges. Gate 8 of
   [the golden workflow](02-golden-workflow.md) explains why this rule matters
   most.
4. **Day 4: a lessons file and the twice rule.** The first time something goes
   wrong, fix it. The second time, the fix also adds an entry to the lessons
   file or a line to the law file, so a third time is harder. `/murmur:init`
   creates the lessons file as `docs/GOTCHAS.md`.
5. **Day 5: a first unattended run.** Let one agent take one small, well-scoped
   task from ticket to merged change without anyone watching every step. It is
   the rehearsal for longer runs.

## What to read next

Read the chapters in order the first time; [the handbook index](README.md) lists
them. If you start with only a few, read these:

- [The golden workflow](02-golden-workflow.md): the ten steps one change passes.
- [Parallel lanes](03-parallel-lanes.md): before you run more than one agent.
- [Coordination and identity](05-coordination-and-identity.md): before two
  agents need to know about each other.
- [The machine](12-the-machine.md): when your laptop is no longer enough. Where
  to get a farm, what it costs, and the command that sets it up.

## Words this handbook uses

Other chapters use these words as defined here. The four roles (owner,
orchestrator, lane, conductor) are described [above](#the-four-roles). The
plugin's skills and some templates also use three placeholders, `<OWNER>`,
`<TRACKER>` and `<FARM>`. The
[templates README](../templates/README.md#placeholders-that-can-stay) explains
them.

**Batch.** One coherent change: one branch and one pull request, committed in
slices a reviewer can read one at a time. The larger piece of work that an
orchestrator splits into lanes is a goal.

**Board.** The shared view of who is working on what. On a farm, it is the
dashboard's Board tab. Without a farm, keep a short written list of what each
lane is doing and what it is waiting for.

**Farm.** An always-on Linux machine that runs agents for you, with nobody at
the screen. It is optional: every rule here also works on a laptop.
[The machine](12-the-machine.md) explains how to get one.

**fleet.** The command that runs a farm: it starts agents, watches them and
serves the dashboard. Its code is in the `fleet/` folder. The `farm/` folder
holds only the installer.

**Gate.** One numbered step that a change passes between a new branch and a
merge. The ten gates are in [the golden workflow](02-golden-workflow.md).

**Head office.** A private GitHub repository that agents use to register their
names, claim branches and send each other messages. murmur's `hq` command reads
and writes it. See [coordination and identity](05-coordination-and-identity.md).

**Manifest.** The list of paths one lane may change, written down before it
starts. A fleet group spec calls this list the lane's `territory`. See
[parallel lanes](03-parallel-lanes.md).

**Night mode.** An unattended run: an agent drives a fixed scope of work to a
defined finish while nobody watches, then reports. See
[unattended runs](10-unattended-runs.md).

**Review verdict.** The one-line answer an adversarial reviewer (a second agent
whose job is to find what is wrong) gives about one exact commit:
`VERDICT <sha> CLEAN` or `VERDICT <sha> RED`. The hash is part of the verdict,
because a verdict about an older commit says nothing about this one.

**Spine file.** A file that most changes want to touch, such as the place where
the application is wired together, a generated interface or a shared registry.
One lane holds it at a time.

**Sweep.** The clean-up job that removes the worktrees and board entries of
finished lanes. On a farm, `fleet sweep` runs every ten minutes by default.
[Coordination and identity](05-coordination-and-identity.md) says what it
keeps.

**Turnstile.** A check in front of the merge queue that refuses a change whose
own branch checks have not passed on that exact commit.

**Worktree.** An extra working copy of the same git repository, with its own
branch, made with `git worktree add`. Each lane works in its own worktree.
