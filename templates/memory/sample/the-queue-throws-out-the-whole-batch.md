---
name: the-queue-throws-out-the-whole-batch
description: "2026-03-18: the merge queue silently ejected three pull requests together because two of them added a new file of the same name. The local conflict check reported no conflict, and my watcher sat waiting on a pull request that had already been thrown out."
metadata:
  type: project
---

**What happened (2026-03-18, three ready pull requests armed at once):** one landed, then
the queue removed all three of the others within five minutes, with no reason given. The
first one brought a new test file into the main branch while another carried its own copy
of that path. The queue builds the candidates together, the clash cannot be resolved, and
the whole batch goes out with it.

**Why it matters:** three traps stack here. My local conflict check said there was no
conflict, because the old command does not treat two additions of one path as one. My
watcher waited an hour for a merge that could never come. And polling too often for that
answer ate the shared read budget for every agent.

**How to apply:** ask the hosting service whether a pull request is mergeable rather than
trusting a local check. After the first merge of a batch, pull the main branch into each
remaining branch, resolve any duplicated new file by keeping one copy, and arm them one
at a time. A watcher reads queue membership every tick and treats disappearance as
ejection.

Related: [[the-generated-client-is-checked-only-in-the-queue]], [[an-automation-never-picks-work-by-author]].
