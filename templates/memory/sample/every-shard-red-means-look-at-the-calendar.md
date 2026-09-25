---
name: every-shard-red-means-look-at-the-calendar
description: "2026-03-17: every server test shard went red at once, on unrelated branches and on the main branch. A reminder email test read the real clock, and its sample booking expired that morning, so it could never pass again."
metadata:
  type: project
---

**What happened (2026-03-17, morning):** all server test shards failed together, on two
of my branches and on the main branch. Nothing in the diffs could explain it. The
failing test checked the wording of a reminder email, and it never told the code which
day to pretend it was, so the wording came from the real clock. The sample booking in
the fixture ended that day, and the email that had always said "tomorrow" now said
"today".

**Why it matters:** I spent forty minutes searching my own changes for a fault that was
never there. Once you know the pattern, you recognise it in a minute.

**How to apply:** when the same failure appears on several unrelated branches, and the
last green run on the main branch was yesterday, stop reading your diff. Read the date
inside the failing assertion. Any test whose expected text depends on the day must set
that day explicitly instead of reading the clock. Fix the fixture on its own small
branch, because every other branch is blocked until the fix lands.

Related: [[the-generated-client-is-checked-only-in-the-queue]], [[check-the-board-before-arming-a-merge]].
