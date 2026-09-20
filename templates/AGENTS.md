<!-- Template: copy to the root of your repo as AGENTS.md. This file is SHAPE,
     not content: each heading says what belongs under it. Delete these comments
     and write your own product. Keep it under three screens; if it grows past
     that, the detail belongs in docs/knowledge/. -->

# AGENTS.md: domain and orientation

One paragraph: what `<PRODUCT>` is, in a sentence a stranger understands, and
what this file is for (orienting an agent to the product and its customers).
Then point at where the laws actually live: the process law file, the
architecture file, the doc index, and the per-domain knowledge files. Do not
restate law here; duplicated law drifts. If exactly one law is broken more often
than the rest, repeat that one and link its source.

## Product domain

The vocabulary. Six to ten bold terms, one or two sentences each, defining the
nouns everybody in the repository uses: the thing a customer creates, the thing
a customer consumes, the ownership boundary, the two or three user roles. Say
explicitly what the product does NOT have, where an agent would otherwise assume
a familiar model that you do not run. Link the knowledge file behind each term
that has one.

## The canonical journey

The main user path, as a short arrow diagram in a code block, from first touch
to the moment the product has delivered value. Then a few lines naming which
engine or subsystem owns each leg of it, and which older path was retired and
must not be reintroduced. An agent that knows this path can place any ticket on
it.

## Product north star

What "excellent" means here, stated as a principle an agent can apply to a
decision it faces alone. Name the trade you have deliberately chosen, and the
kind of solution you refuse even when it would pass tests. Close with one
sentence on how you improve behavior instead (better context and evaluation, not
more hard-coded rules) and one line of history: the mechanism you built,
reverted, and why.

## The system, end to end

Four short paragraphs, each opening with **It `<verb>`s**: how it runs, how it
completes, how it recovers, what it sees (its durable state). Enough to orient,
never the mechanism detail; link the architecture section or design doc for
that. Add a fifth paragraph only for a surface that is the product's face and
easy to underestimate.

**The law over all of it:** one paragraph naming the single invariant that
decides arguments about this system, and what it forbids by name, so nobody
proposes that shape again.

## Who we build for

The customer record, with **stable ids**. Group the segments, mark their
priority, and name the one or two that are the growth engine. Then two or three
findings that shape every feature: the insight behind what you sell, and the
leading objection you must answer. An id used here must resolve in the research
files below, and must be the same id used in prompts, tickets, briefs and tests.

| Id | Segment | Priority | Why it matters |
|---|---|---|---|
| `<SEG-01>` | `<who>` | P0 | `<one line>` |
| `<SEG-02>` | `<who>` | P1 | `<one line>` |

## Research index

List the evidence files by path, one line each, saying what an agent will find
in each and how the ids join them: the profiles and jobs to be done, the sourcing
pass that marks each pain confirmed, weak or refuted, and the backlog that traces
every feature id back to a segment and a signal. Say in one line where actionable
work is tracked and what id format links a branch and a PR back to it.

## Skill doors

Agents from other vendors do not discover this repository's skills on their own.
List the skill files by path, each with the one situation that should send an
agent there (design or visual work, infrastructure and deploy duty, a risky
subsystem). Name the live authority for each area (a route, a doc, the running
system) and say plainly that its law is not restated here.
