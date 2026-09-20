<!--
Template: copy to docs/knowledge/README.md, then add one file per domain using
_domain.md as the skeleton. This README is the contract for the folder; the
domain files are the content.
-->

# Knowledge base

The team's knowledge, carried by its engineers and its agents, written down so
the next person does not relearn it the hard way. This is the briefing a domain
owner would give you across a desk: how the subsystem *actually* behaves, the
hard numbers, the invariants, the techniques that work, and the checks that keep
a green result from lying.

One folder, one file per **domain or subject, never per person**. People rotate,
domains stay. Each file opens with a `Maintainer:` line naming the current owner
and a last-updated date, so a reader can tell at a glance whether they are
reading a fact or a fossil. The maintainer folds in new knowledge as their work
produces it; anyone may open a pull request with a correction.

## The two shapes a file takes

- **Operational knowledge.** Measured numbers (costs, latencies, capacities,
  limits) plus practical techniques and "before you trust X, check Y" habits.
  Each entry is a `### one-line claim` heading followed by the evidence, the
  date it was measured, and a link to the pull request, decision record or
  incident behind it. A number with no date and no link cannot be checked, so
  nobody should act on it.
- **Subject orientation.** Scope, then a truth map, then the laws and
  invariants, then how to investigate, then the defect-class history, then
  pointers. This is the map that makes a stranger productive in the subject in
  one read.

Pick the shape that fits the domain. Mixing sections is fine when the domain
needs both.

## What does not belong here: link, do not duplicate

A duplicated rule is the second-implementation defect in prose, and the copy
always rots. Where this folder and a canonical document disagree, the canonical
document wins and the knowledge file has a bug.

| Kind of content | Where it lives |
|---|---|
| Process law | the repository law file |
| Incident war stories | `docs/GOTCHAS.md`, as symptom, cause, prevention |
| What to do when an alert fires | `docs/RUNBOOK.md`, indexed by what you saw |
| Decisions and their rationale | `docs/adr/` |
| Living design records | `docs/design/` |

The boundary in one line: gotchas tell you what once went wrong, the runbook
tells you what to do when an alert fires, decision records tell you what was
decided, and the knowledge base tells you how the system behaves and how to work
it well.

## How it stays current

The workflow gate that covers documentation covers this folder too: a batch that
changes how a subsystem operationally behaves (its mechanism, capacity, cost,
timing or procedure) updates the matching domain file **in the same pull
request**. Knowledge lands with the change that created it, not in a quarterly
archaeology pass.

An entry whose facts have drifted from reality is fixed or deleted by whoever
discovers the drift, in the pull request that discovers it. A stale fact is
worse than no fact, because it is believed.

## Index

| File | Domain | Maintainer | Last updated |
|---|---|---|---|
| `<domain>.md` | `<what it covers in five words>` | `<OWNER>` | `<YYYY-MM-DD>` |
