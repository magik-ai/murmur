<!-- Template: copy to the root of your repository as AGENTS.md. This file gives
     the SHAPE, not the content: each heading says what belongs under it.
     Delete these comments and write about your own product. Keep it under
     three screens. If it grows past that, move the detail to docs/knowledge/. -->

# AGENTS.md: domain and orientation

One paragraph: what `<PRODUCT>` is, in a sentence a stranger understands, and
what this file is for (explaining the product and its customers to an agent).
Then point to where the rules live: the process law file, the architecture
file, the doc index, and the knowledge file for each domain. Do not repeat
rules here, because copies drift apart. If one rule is broken much more often
than the others, repeat that one rule and link to its source.

## Product domain

The vocabulary. Six to ten terms in bold, one or two sentences each. Define the
nouns everyone in the repository uses: what a customer creates, what a
customer consumes, where ownership ends, and the two or three user roles. Say
clearly what the product does NOT have, wherever an agent would otherwise
assume a familiar model that you do not use. Link the knowledge file behind
each term that has one.

## The canonical journey

The main user path, as a short arrow diagram in a code block, from the first
contact to the moment the product has delivered value. Then a few lines on
which part of the system owns each step, and which older path was retired and
must not come back. An agent that knows this path can place any ticket on it.

## Product north star

What "excellent" means here, stated as a principle an agent can apply when it
has to decide alone. Name the trade-off you have chosen, and the kind of
solution you refuse even when it would pass the tests. If you once built an
approach and then removed it, say so in one line, and say why, so nobody
proposes it again.

## The system, end to end

Three or four short paragraphs: how the system runs, how a piece of work
finishes, how it recovers from failure, and where its lasting state lives.
Give enough to orient an agent, never the mechanism in detail: link the
architecture section or the design doc for that. Add one more paragraph only
for a surface that is the face of the product and easy to underestimate.

**The rule over all of it:** one paragraph naming the single invariant that
settles arguments about this system, and what it forbids by name, so nobody
proposes that design again.

## Who we build for

The customer segments, each with a **stable id**. Group them, mark their
priority, and name the one or two that drive growth. Then two or three findings
that shape every feature: the insight behind what you sell, and the most
common objection you must answer. Every id used here must exist in the
research files below, and must be the same id used in prompts, tickets, briefs
and tests.

| Id | Segment | Priority | Why it matters |
|---|---|---|---|
| `<SEG-01>` | `<who>` | P0 | `<one line>` |
| `<SEG-02>` | `<who>` | P1 | `<one line>` |

## Research index

List the evidence files by path, one line each. Say what an agent will find in
each one, and how the ids connect them: the customer profiles and the jobs they
need done, the research that marks each pain as confirmed, weak or refuted, and
the backlog that traces every feature id back to a segment and a signal. Say in
one line where actionable work is tracked, and which id format links a branch
and a pull request back to it.

## Skill doors

Not every agent finds this repository's skills by itself: an agent from
another vendor may not look where your skills are kept. List the skill files by
path, each with the one situation that should send an agent there (design or
visual work, infrastructure and deploys, a risky subsystem). Name the live
authority for each area (a route, a doc, the running system), and say plainly
that its rules are not repeated here.
