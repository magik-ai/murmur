<!--
Template: copy to docs/knowledge/<domain>.md and rename. Keep the Maintainer and
Updated lines at the top, always. Delete the shape you are not using: shape A
(operational knowledge) or shape B (subject orientation). Keeping both headings
empty is worse than picking one.
-->

# `<Domain>`

**Maintainer:** `<NAME>`
**Updated:** `<YYYY-MM-DD>`

One paragraph: what this domain covers, and who should read this file before
touching it. Say what is NOT in scope and where that lives instead.

---

## Shape A: operational knowledge

Use this shape for a domain whose value is measured numbers and hard-won
technique (infrastructure, CI, a provider integration, a pipeline). Every entry
is a claim, its evidence, when it was measured, and the link that proves it.

### `<One-line claim, stated as a fact>`

What the number or behavior is, in one or two sentences. Then the evidence: how
it was measured or observed, on what, and when. Then the link: pull request,
decision record, or incident.

- **Evidence:** `<what was run or observed>`
- **Measured:** `<YYYY-MM-DD>`
- **Link:** `<PR, decision record, or incident>`

### `<Before you trust X, check Y>`

The habit, in the imperative. Say what looks true and is not, what the cheap
check is, and what it costs to skip it.

---

## Shape B: subject orientation

Use this shape for a subject a stranger must be able to enter in one read (a
product area, a subsystem, a risky corner).

### Scope

What this subject is, in three or four sentences. Name the boundary: which
components are in, which neighbours are out, and which document owns each
neighbour.

### Truth map

Where the truth actually lives, as a small table. For each fact the subject
depends on, name the authoritative source and the places that only look
authoritative. This is the section that saves the most time.

| Fact | Where the truth lives | Common wrong source |
|---|---|---|
| `<fact>` | `<file, table, service or endpoint>` | `<what people read instead>` |

### Laws and invariants

The statements that must stay true, in the imperative, one or two sentences
each. Each names what it forbids, so nobody proposes that shape again. If a law
is enforced by a check, name the check.

### How to investigate

The method, as numbered steps, from the symptom to the mechanism. Name the
commands, the logs and the queries that actually answer the question, and the
order to run them in. Say which signal is reliable and which one lies.

### Defect-class history

The kinds of bugs this subject produces, not a bug list. One line per class:
what the class looks like from outside, what causes it, and what now prevents
it. A repeat is a sign the prevention did not take.

### Pointers

Where to go next: the architecture section, the design record, the runbook
entry, the relevant gotchas, the dashboards. One line each, saying what the
reader will find there.
