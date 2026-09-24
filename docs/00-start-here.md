# Start here

This handbook describes a way to run several coding agents on one repository as
a team. It gives every agent a role, keeps the rules in one file, and adds a few
small tools that enforce those rules. murmur ships the tools: a Claude Code
plugin, a runner for a farm of agents, and a coordination command called `hq`.
You can follow the method without them.

## Why a team of agents needs rules

One coding agent is easy to manage: you give it a task, watch it work and read
the diff. Ten agents at once is a different job. You are now running a team, and
a team needs what human teams have always needed:

- **Ownership.** Each piece of work has one owner, so two agents never edit the
  same file at once and silently erase each other's changes.
- **A shared record.** The state of the work lives outside any one agent's
  context or any one person's head, because nobody can hold the whole picture.
- **Review by a different mind.** A writer checking its own work misses what it
  was already blind to.
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

**Orchestrator.** An agent that splits a batch of work into lanes and writes no
product code. It keeps two lanes from editing the same file, and sets the order
for the few shared files every lane wants. It checks what lanes report before
passing it on to you, and keeps the shared board up to date. See
[orchestration](04-orchestration.md).

**Lane.** One agent doing one task on its own branch, from start to finish: it
writes the change, reviews it, opens the pull request, answers the review and
sees the change merged. It owns a fixed set of paths and touches nothing else.
The urge to "fix something nearby while I am here" is a reason to stop.

**Conductor (release manager).** Owns the merge queue: what merges, in what
order, and what waits. It can stop any merge, however green the checks are. It
does not build features or decide product questions.

A team may add approvers, such as a technical owner who signs off on
architecture. They approve on top of the four roles; they are not a fifth role.

## Rules live in one file

Each repository has one file that says how work happens: what a change must
include before it merges, how review works, and what is forbidden. This handbook
calls it the law file. Every other document links to it instead of repeating
it, because a copied rule drifts and people follow the stale copy.
[Repo law](01-repo-law.md) explains how to write one.

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
3. **Day 3: review by someone who did not write the change.** Every change is
   read by a different mind, human or agent, before it merges. No other rule in
   the method does as much good.
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
orchestrator, lane, conductor) are described [above](#the-four-roles).

Three placeholders appear in angle brackets in the plugin's skills and some
templates. `<OWNER>` is the person who runs the repository and names the
agents. `<TRACKER>` is where the team tracks work. `<FARM>` is the machine that
runs agents, if there is one. `/murmur:init` stores which tracker you use and
whether you have a farm in `.murmur/config.toml`. At the start of every
session, the plugin's session hook reads that file and tells the agent what
`<TRACKER>` and `<FARM>` mean here. It also tells the agent that `<OWNER>` is
the person who gave it its name. Before `/murmur:init` has run, `<TRACKER>`
means the pull request itself, and there is no `<FARM>`.

**Farm.** An always-on Linux machine that runs agents for you, with nobody at
the screen. It is optional: every rule here also works on a laptop.
[The machine](12-the-machine.md) explains how to get one.

**Gate.** One numbered step that a change passes between a new branch and a
merge. The ten gates are in [the golden workflow](02-golden-workflow.md).

**Head office.** A private GitHub repository that agents use to register their
names, claim branches and send each other messages. murmur's `hq` command reads
and writes it. See [coordination and identity](05-coordination-and-identity.md).

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
finished lanes. On a farm, `fleet sweep` runs every ten minutes by default. Only
committed and pushed work is safe from it.

**Turnstile.** A check in front of the merge queue that refuses a change whose
own branch checks have not passed on that exact commit.

**Worktree.** An extra working copy of the same git repository, with its own
branch, made with `git worktree add`. Each lane works in its own worktree.
