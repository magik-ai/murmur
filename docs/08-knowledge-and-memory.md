# Knowledge and memory

## The problem this solves

An agent that fixes a bug today and forgets the lesson by next week is not
actually learning: it is guessing fresh every time. A team of agents forgets
faster than a team of humans, because each session starts with a blank
context. Without a deliberate place to put what was learned, every hard-won
fact lives in one transcript and dies with it.

This chapter covers three separate stores, each with a different job: a rule
that is now enforced, a lesson that might repeat, and a fact that a domain
owner would tell you across a desk.

## The twice rule

The first time an agent makes a mistake, fix the mistake and move on. Writing
a rule for a one-off is noise; most one-offs never happen again.

The second time the *same* mistake happens, that is a pattern, and a pattern
needs a rule, not another one-off fix. The rule: when an agent makes the same
mistake twice, the fix that resolves the second occurrence also adds a line to
the law file or the lessons file. A lesson that stays only in chat is a lesson
that gets made a third time.

This turns "we should really write that down" from a wish into a gate: the
second fix does not merge without the line that prevents the third.

## The lessons file

Keep one running file of debugging war stories, in a fixed shape: **symptom,
then cause, then prevention.** Symptom is what you actually observed, in
plain terms. Cause is the real mechanism, not a guess. Prevention is the
concrete thing that stops it from happening again, a check to run or a rule to
follow.

This file is deliberately kept out of the material an agent reads at the start
of every session. It grows into thousands of lines over the life of a project,
and reading all of it every time would crowd out everything else useful in
that budget. Instead, it is read on demand: when a symptom looks familiar,
search it before debugging from scratch.

An entry earns its place only when the lesson is specific enough to actually
prevent a repeat. "Be more careful" is not an entry. "This exact symptom means
this exact cause, so run this exact check first" is.

**The incident behind it:** a project once let this file grow without the
symptom-cause-prevention discipline, mixing narrated debugging sessions in with
real lessons. The file became too noisy to search, and agents stopped checking
it before debugging, which defeated the entire purpose of keeping it.

## One knowledge file per domain

Separate from the lessons file, keep one file per subject area: how a
particular part of the system actually behaves, its measured numbers (costs,
timings, limits), its invariants, and the checks that keep a "looks fine" from
being a lie.

A domain file, not a person file. People rotate off a project; domains
outlive them. Each file opens with a maintainer line naming who currently owns
that domain and a last-updated date, so a reader knows whether to trust it or
go verify.

Two shapes cover almost everything:

- **Operational knowledge**: measured facts and habits, each written as a
  short claim with its evidence and a date attached, so a number that ages out
  can be spotted and refreshed.
- **Subject orientation**: a map for a stranger, covering what the subject
  covers, the invariants that must hold, how to investigate it, and the
  history of mistakes specific to it.

Pick whichever shape fits, or mix them when a domain genuinely needs both.

Knowledge lands in the same change that created it, not in a separate cleanup
pass later. If a change alters how a subsystem behaves, cost, or is timed, the
matching knowledge file updates in the same reviewed change. A knowledge file
that has drifted from reality is worse than an empty one: whoever notices the
drift fixes or deletes the stale line on the spot, in whatever change
uncovered it.

## The memory index

Separate again from both of the above: a running agent accumulates memory
across many sessions on the same project, things worth remembering that are
not quite lessons and not quite domain knowledge, closer to running notes.

The pattern that scales is one fact per file, plus an index. A top-level index
file lists sub-indexes by topic, each with a rough count of how many facts it
holds. Each individual fact lives in its own small file with a short header
(what it is, when it was learned) and one clear idea in the body. New
sub-indexes are added as topics accumulate enough facts to need one.

One fact per file sounds wasteful until the alternative is tried: a single
growing file of mixed facts becomes exactly as unsearchable as the lessons
file above without its symptom-cause-prevention structure. Small files are
easy to grep, easy to link to individually, and easy to delete outright when
a fact stops being true.

## What to publish, and what never to

A project's law file, its lessons file, and its knowledge files are meant to
be shared: they are how a new contributor, human or agent, gets fast. Publish
all of them.

The personal memory directory is different. It accumulates whatever a session
happened to learn about the people, the infrastructure, and the day-to-day
texture of one specific team, including things that were never meant to be
public: names, internal addresses, one-off arrangements. Treat it as personal
notes, not documentation. If a fact in there is genuinely a durable lesson, it
belongs promoted into a lessons file or a knowledge file, scrubbed of anything
identifying, not published as-is.

## Adopt it in a day

1. Create an empty lessons file with the symptom, cause, prevention header and
   one real example.
2. Pick your single most fragile subsystem and write its first knowledge file,
   with a maintainer line.
3. Add the twice-rule sentence to your law file: second occurrence of a
   mistake requires a line in the lessons file, in the same change that fixes
   it.
4. Start a memory index, even with one entry, so the habit of writing one fact
   per file exists before the pile grows large enough to need it.
