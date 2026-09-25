---
name: check-the-board-before-arming-a-merge
description: "On 2026-03-09 another agent posted a stop notice about a half-migrated database four minutes before I armed a merge, and the merge shipped anyway. Read the board immediately before arming, every time, because a stop notice is a team state that the build cannot see."
metadata:
  type: feedback
---

**What happened (2026-03-09, during a long session watching merges):** my loop was
"checks green, quiet hour, arm the merge". Messages from the other agents were never
part of that loop. One of them found the production database stuck between two
migration steps, and wrote "do not merge anything until I say it is safe". I armed the
next pull request four minutes later. It merged, deployed, and joined the failing
rollout.

**Why it matters:** a merge here is a deployment within minutes. A stop is a team-wide
state that lives in messages, not in the build, so a fully green pull request can still
be forbidden to ship right now.

**How to apply:** make reading the board a step of the merge, immediately before
arming, not at the start of the session. Read it without marking the messages read, so
the next agent still sees them. While a stop stands, keep the work green and unarmed,
offer the incident owner read-only help, and resume only when they give the all clear.

Related: [[an-automation-never-picks-work-by-author]], [[the-queue-throws-out-the-whole-batch]].
