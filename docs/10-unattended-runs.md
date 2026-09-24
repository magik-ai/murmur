# Unattended runs

An unattended run is one long session that works while nobody watches. It
takes work that is already open, drives each piece to a clear finish, and
hands back one report. murmur calls this night mode, because the usual case is
a run you start in the evening and read about in the morning. The steps are
in the [`night-mode` skill](../plugin/skills/night-mode/SKILL.md). Claude Code
loads it when you say "night mode", "unattended run" or "finish this while I
sleep".

Every piece of work ends in one of three states:

| Finish | What it means |
| --- | --- |
| Production | Merged, deployed, and checked by watching the real behaviour |
| Preview | A running environment, plus what to press and what should happen |
| Blocked | A named reason, and what picking it up again would take |

Nothing rests in "in progress". A night that leaves five half-finished pieces
has cost a night and produced nothing anyone can act on.

Words used below: a lane is one agent doing one task on its own branch.
`<OWNER>` is the person whose product it is, `<TRACKER>` is wherever your team
tracks work, and `<FARM>` is your always-on machine that runs agents, if you
have one ([chapter 12](12-the-machine.md)).

## What it is not

It is not permission to start new work. It does not lift any safety rule. It
is not "keep going until the context runs out". And it does not guarantee
that anything ran at all: an alarm inside the session dies silently when the
session ends (see below).

## Freeze the scope before you start

The scope is whatever is already open when the run starts:

- tickets in `<TRACKER>` that carry this agent's label;
- its open pull requests;
- its running lanes;
- anything `<OWNER>` named in the same message.

Write that list down before touching anything. Nothing new starts without
`<OWNER>`'s word. The only exception is repairing something that blocks a
finish inside the frozen scope.

The reason is drift. An agent working alone finds a nearby improvement at
every step, and each one looks small. Without a frozen list, the morning
report describes a night of interesting work and an unchanged product.

## The heartbeat

An agent left alone does not notice when it has stopped. It waits for
something, the something never comes, and nobody sees that it went quiet.

The fix is a clock. Every fifteen to twenty minutes, the agent wakes and runs
the same checklist, skipping nothing: mail, running lanes, the merge queue,
the last deploy, any watchers, the tracker, and one line in the night journal.
The checklist text is in section 3 of the night-mode skill. The
[night-mode brief](../templates/briefs/night-mode.md) carries the same
checklist, ready to hand to an agent.

Two properties matter more than the contents:

- The checklist is the same every time, so nothing depends on judgement at
  four in the morning.
- It writes one journal line on every tick, even when the answer is "quiet".
  So the night leaves a record that anyone can read.

## Choose what wakes the agent, and say so

Pick one of four heartbeat modes before the first tick, and write the choice
in the night journal:

| Mode | What wakes the agent | Pick it when |
| --- | --- | --- |
| alarm | A timer inside this session | The window and machine stay awake all night |
| lane | A headless lane on `<FARM>` | You have a farm, and the session may close |
| schedule | A cron job or hosted schedule | You have no farm and no machine that stays awake |
| none | Nothing: one long stretch, then a handover | The scope fits in one session |

A headless lane is an agent that runs without a window, and its whole job is
to rerun the checklist.

### An alarm dies with the session

Say this in the first message of the run, not in a footnote.

A timer created inside a session lives only as long as that session. Close
the window, let the machine sleep or lose the network, and the ticks stop.
There is no error. The run just ends without telling anyone.

Two options are sturdier:

- **A headless lane.** A worker on `<FARM>` whose whole job is the checklist,
  on a loop. It survives your window closing and reports like any other lane.
  With no farm, the same worker can run as a headless session on your own
  machine, but then it stops when that machine does.
- **A schedule outside the session.** A cron entry or a hosted scheduled run
  starts a fresh agent at each interval, with the same checklist. It takes
  longer to set up, and it survives a sleeping machine.

Whichever you choose, name it in the opening message, so `<OWNER>` knows what
kind of night this is.

### The incident behind it

One night, five lanes finished their work and waited to be collected. The
collector was an alarm inside a session on a laptop. The laptop went to sleep,
and the ticks stopped without a sound. In the morning, five finished pieces of
work sat untouched: nothing merged, nothing deployed, nothing reported.

The lanes had done everything asked of them. The part that failed was the part
meant to watch, and it failed by producing nothing, which nobody checks for.
Two fixes came out of it:

- The collector does not live in a window you close.
- The heartbeat writes where other people can see it, so missing lines are
  visible too.

## Decide alone, and log every contested call

The value of the run is decisions made without waiting. A question the agent
could answer itself is a night spent waiting.

Some decisions must still be visible: a product choice, something hidden or
deferred, a scope trade, or work on someone else's pull request. Each one gets
a line in the journal, a comment on the ticket, and a place in the morning
report.

Each contested decision also records how to undo it. If `<OWNER>` cannot
easily undo a decision in the morning, they cannot really review it.

A stuck item gets one more attempt with a new idea. After two failed attempts,
write it up as blocked and move on to the next item.

## Rules that never lift

Being alone raises the agent's authority to decide. It raises nothing else.

- Never bypass a required check with admin rights.
- Never merge red, and never step around the merge queue.
- Never touch a branch another agent has claimed.
- Never change production without approval for that exact action.
- Never print a secret value.
- Never switch off a working feature as a fix. That is a product decision.
- Review before merge is not skipped at night. Whatever review the work
  normally passes, it passes now.
- The house writing rules still apply at four in the morning.

The merge rule is whatever `<OWNER>` said last that evening. If the standing
rule is "nothing merges without my yes", night mode does not lift it. "Finish
it yourself" lifts it only for the scope that was named.

## The morning report

One report, written for someone who was asleep:

1. What shipped, with links.
2. What is waiting for `<OWNER>`, and the exact thing to press.
3. What did not land, and whose move is next.
4. The contested decisions, and how to undo each one.
5. Anything found that is worth a rule.
6. A small table of numbers.
7. Links: pull requests, environments, tickets and the journal.

The short version goes to `<OWNER>` directly. The long version goes into the
parent ticket as a comment, so the rest of the team can read it without
opening a pull request.

## The procedure lives in the skill

This chapter gives the reasons. The steps are in the night-mode skill: the
first ten minutes, the heartbeat text to paste, the finish table, the report
shape, and what to do if the session ends early. To hand a run to an agent,
fill in the [night-mode brief](../templates/briefs/night-mode.md).

Keep one copy of the procedure. A procedure written in both a chapter and a
skill drifts apart, and the stale copy is the one somebody follows at three in
the morning.

## Adopt it in a day

1. Rehearse once in the daytime: one ticket, two hours, you nearby.
2. Copy the heartbeat checklist from the night-mode skill into whatever wakes
   the agent.
3. Open a journal file, and require one line per tick, even a quiet one.
4. Decide up front which of the three finishes each scope item is aiming at.
5. When you have a farm or a scheduler outside your session, move the alarm
   there before the first real overnight run.
