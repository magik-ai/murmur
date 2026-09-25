<!--
Template: copy to docs/knowledge/README.md. Then add one file per domain, using
_domain.md as the skeleton. This README sets the rules for the folder; the
domain files hold the content.
-->

# Knowledge base

What the team's engineers and agents know, written down so the next person does
not have to learn it the hard way. It is the briefing a domain expert would
give you in person: how the subsystem *really* behaves, the hard numbers, the
invariants (the rules that must always hold), the techniques that work, and the
checks that make a green result mean something.

One folder, one file per **domain or subject, never per person**. People move
on; domains stay. Each file opens with a `Maintainer:` line naming the person
who looks after it, and the date of the last update, so a reader can see at a
glance whether it is current. The maintainer adds new knowledge as their work
produces it. Anyone may open a pull request with a correction.

## The two shapes a file takes

- **Operational knowledge.** Measured numbers (costs, latencies, capacities,
  limits) plus practical techniques and "before you trust X, check Y" habits.
  Each entry is a `### one-line claim` heading, followed by the evidence, the
  date it was measured, and a link to the pull request, decision record or
  incident behind it. A number with no date and no link cannot be checked, so
  nobody should act on it.
- **Subject orientation.** The scope, then a truth map (where each fact really
  lives), then the rules and invariants, then how to investigate, then the
  kinds of defects the subject has had, then pointers. This is the map that
  lets a stranger work in the subject after one read.

Pick the shape that fits the domain. A domain that needs both can mix them.

## What does not belong here: link, do not copy

A copied rule is the second-implementation defect in prose, and the copy always
goes stale. When this folder and the main document on a subject disagree, the
main document wins, and the knowledge file has a bug.

| Kind of content | Where it lives |
|---|---|
| Process law | the repository law file |
| Incident stories | `docs/GOTCHAS.md`, as symptom, cause, prevention |
| What to do when an alert fires | `docs/RUNBOOK.md`, indexed by what you saw |
| Decisions and their reasons | `docs/adr/` |
| Design records that are still changing | `docs/design/` |

The boundary in one line: gotchas say what once went wrong, the runbook says
what to do when an alert fires, decision records say what was decided, and the
knowledge base says how the system behaves and how to work with it well.

## How it stays current

The workflow step that covers documentation covers this folder too. A batch
that changes how a subsystem behaves in practice (its mechanism, capacity,
cost, timing or procedure) updates the matching domain file **in the same pull
request**. Knowledge lands with the change that created it, not in a cleanup
months later.

When a fact has drifted from reality, whoever notices it fixes or deletes it,
in the pull request where they noticed. A stale fact is worse than no fact,
because people believe it.

## Index

| File | Domain | Maintainer | Last updated |
|---|---|---|---|
| `<domain>.md` | `<what it covers in five words>` | `<NAME>` | `<YYYY-MM-DD>` |
