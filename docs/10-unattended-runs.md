# Unattended runs

## What an unattended run is

An unattended run is one long session, nobody watching, that drives work that
is already open to a defined finish and hands back a single report.

The finish is one of three things. Production, meaning merged, deployed, and
verified by observing the real behaviour. Preview, meaning a running
environment plus instructions for what to press and what should happen.
Blocked, meaning a named reason and what picking it up again would take.

Nothing rests in "in progress". An overnight run that produces five
half-finished things has cost a night and returned nothing anyone can act on.

## What it is not

It is not permission to start new work. It is not a lifted safety rule. It is
not "keep going until the context runs out".

It is also not a guarantee that anything ran at all, which is a real failure
mode worth its own section below.

## Freeze the scope before you start

The scope is whatever is already open at the moment the command arrives:
tickets in <TRACKER> carrying this agent's label, its open changes, its
running lanes, plus anything <OWNER> named in the same sentence.

Write that list down before touching anything. Nothing new starts without
<OWNER>'s word. The one exception is repairing something that blocks a finish
inside the frozen scope.

The reason is drift. An agent working alone finds an adjacent improvement at
every step, and each one looks small. Without a frozen list, the morning
report describes a night of interesting work and an unchanged product.

## The heartbeat

An agent left alone stops noticing that it has stopped. It waits on something,
the something never arrives, and no one is there to see the silence.

The fix is a clock. Wake every fifteen to twenty minutes and run the same
checklist, skipping nothing. The checklist itself is kept in one place only,
section 3 of
[`plugin/skills/night-mode/SKILL.md`](../plugin/skills/night-mode/SKILL.md).

Two properties matter more than the contents. The checklist is identical every
time, so nothing depends on judgment at four in the morning. And it writes one
journal line every tick, even when the answer is "quiet", so the night leaves a
readable history rather than a memory.

## Decide alone, and log what was contested

The value of the run is decisions taken without waiting. A question the agent
could have answered itself is a night spent waiting.

Some decisions still need to be visible. A product choice, something hidden or
deferred, a scope trade, or touching someone else's work: each gets a line in
the journal, a comment on the ticket, and a place near the top of the report.

Every contested decision also records how to undo it. A decision <OWNER>
cannot reverse over coffee is not a decision they can review.

## The walls autonomy never lifts

Being alone raises the authority to decide. It raises nothing else.

Never bypass a required check with admin rights. Never merge red and never
step around the merge queue. Never touch a branch another agent has claimed.
Never mutate production without approval for that exact action. Never print a
secret value. Never disable a shipped capability as a fix, because that is a
product decision.

Review before merge gets no night discount: whatever gate the work normally
passes, it passes now. The house writing rules still apply at four in the
morning.

And the merge law is whatever <OWNER> said last that evening. If the standing
rule is "nothing merges without my yes", an unattended run does not lift it.

## The alarm dies with the session, and you must say so

This is the honest caveat, and it belongs in the first message of the run, not
in a footnote.

A timer created inside the session lives exactly as long as the session. Close
the window, let the machine sleep, or drop the network, and the ticks stop.
There is no error. The run simply ends without telling anyone.

Two sturdier options exist.

A headless lane: a worker on <FARM> whose entire job is the checklist on a
loop. It survives your window closing and reports like any other lane.

A schedule outside the session: a cron entry or a hosted scheduled run that
starts a fresh agent each interval with the same checklist. Slower to set up,
and it survives a sleeping machine.

Whichever you choose, name it in the opening message so <OWNER> knows what
kind of night this is.

## The incident behind it

One night, five lanes each finished their work and waited to be collected.

The collector was an alarm living inside a session on a laptop. The laptop
went to sleep. The ticks stopped, silently. In the morning, five completed
pieces of work sat untouched: nothing merged, nothing deployed, nothing
reported, and a night gone.

The lanes had done everything asked of them. The single point of failure was
the part that was supposed to be watching, and it failed in the way nobody
checks for, by producing no output at all.

Two fixes came out of it. The collector does not live inside the window you
close. And the heartbeat writes to a place other people can see, so an absence
of lines is itself visible.

## The morning report

One report, written for someone who was asleep: what shipped, with links; what
is waiting for <OWNER> and the exact thing to press; what did not land and
whose move is next; the contested decisions and how to undo them; anything
found that is worth a rule; a small table of numbers.

The short version goes to <OWNER> directly. The long version goes into the
parent ticket, so the rest of the team can read it without opening a pull
request.

## The procedure lives in a skill

This chapter is the reasoning. The runnable procedure is
[`plugin/skills/night-mode/SKILL.md`](../plugin/skills/night-mode/SKILL.md):
the first ten minutes, the exact heartbeat text to paste, the finish table,
the report shape, and what to do if the session ends early.

Keep one copy. A procedure that exists in a chapter and in a skill will drift,
and the stale copy is the one somebody follows at three in the morning.

## Adopt it in a day

1. Run one short daytime rehearsal first: one ticket, two hours, you nearby.
2. Copy the heartbeat checklist out of the night-mode skill into whatever
   wakes the agent.
3. Open a journal file and require one line per tick, even a quiet one.
4. Decide up front which of the three finishes each scope item is aiming at.
5. Optional, when you have a machine or a scheduler outside your session: move
   the alarm there before the first real overnight run.


## Pick the heartbeat mode on purpose

There are four ways to be woken up during a run: an alarm inside the session, a headless lane on a farm, a schedule outside the session, or nothing at all. The first is the easiest and the most fragile, because it dies when the window closes or the machine sleeps. Say which one you are using before the first tick and write it down. The skill lists the four and when each fits.
