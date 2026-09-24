---
name: four-lanes-built-the-same-loading-ring
description: "2026-03-14: four lanes replaced the booking app's loading blocks in their own screens, each green on its own. Assembled, thirteen tests were red, and the branch carried four copies of one new loading ring with four different interfaces."
metadata:
  type: project
---

**What happened (2026-03-14, the loading pass across the scheduling app):** four
parallel lanes each swapped a heavy loading block for a small spinning ring in their own
area. Every lane was green on its own branch. On the assembled branch, eight unit tests
and five browser tests went red. One lane's test expected a loader that another lane had
deleted. A shared toolbar lost its default busy label. One heading now appeared twice on
the plan screen. And each lane had created its own version of the ring, with different
names, different defaults and different test identifiers.

**Why it matters:** lanes own separate source folders, but tests, shared components and
generated lists cross those borders, and a lane cannot see its neighbour's change.

**How to apply:** when several lanes need one new shared piece, build that piece first on
the integration branch, or give it to exactly one lane and tell the others to import it.
After assembly, and before opening the pull request, run the tests that touch the whole
combined change, not only each lane's own tests.

Related: [[the-heartbeat-dies-with-the-session]], [[the-queue-throws-out-the-whole-batch]].
