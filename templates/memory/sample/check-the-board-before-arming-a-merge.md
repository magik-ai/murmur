---
name: check-the-board-before-arming-a-merge
description: "On 2026-03-09 another agent posted a stop notice about a half-migrated database three minutes before I armed a merge, and the merge shipped anyway. Read the board immediately before arming, every time, because a stop notice is a team state that the build cannot see."
metadata:
  type: feedback
---

**What happened (2026-03-09, during a long shepherding session):** my loop was
"checks green, quiet hour, arm the merge". Messages from the other agents were never part
of that loop. One of them found the production database stuck between two migration
steps and wrote "do not merge anything until I say it is safe". I armed the next pull
request four minutes later. It merged, deployed, and joined the failing rollout.

**Why it matters:** a merge here is a deployment within minutes. A stop is a team-wide
state that lives in messages, not in the build, so a perfectly green pull request can
still be forbidden to ship right now.

**How to apply:** make reading the board a step of the merge gate, immediately before
arming, not at the start of the session. Read it without consuming it, so the next agent
still sees the same messages. While a stop stands, keep the work green and unarmed, offer
the incident owner read-only help, and resume only on their all clear.

Related: [[an-automation-never-picks-work-by-author]], [[the-queue-throws-out-the-whole-batch]].
