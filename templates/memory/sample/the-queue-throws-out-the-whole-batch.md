---
name: the-queue-throws-out-the-whole-batch
description: "2026-03-18: the merge queue removed three pull requests together, without a clear reason, because two pull requests in the batch added a new file at the same path. The local conflict check reported no conflict, and my watcher kept waiting on a pull request that had already been thrown out."
metadata:
  type: project
---

**What happened (2026-03-18, four ready pull requests armed at once):** one merged. Then,
within five minutes, the queue removed the other three, with no clear reason given. The
first one had brought a new test file into the main branch, and another one carried its
own copy of a file at that same path. The queue had built the remaining candidates as
one group, the clash could not be resolved, and the whole group went out with it.

**Why it matters:** three traps stack up here. My local conflict check said there was
no conflict, because it did not treat two new files at the same path as a clash. My
watcher waited an hour for a merge that could never come. And polling too often for that
answer used up the shared API budget for every agent.

**How to apply:** ask the hosting service whether a pull request can be merged, rather
than trusting a local check. After the first merge of a batch, merge the main branch
into each remaining branch, resolve any duplicated new file by keeping one copy, and arm
them one at a time. A watcher checks queue membership on every tick, and treats a pull
request that disappeared as thrown out.

Related: [[the-generated-client-is-checked-only-in-the-queue]], [[an-automation-never-picks-work-by-author]].
