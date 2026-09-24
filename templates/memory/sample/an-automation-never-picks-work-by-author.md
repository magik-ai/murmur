---
name: an-automation-never-picks-work-by-author
description: "On 2026-03-05 my nightly merge job merged five pull requests that belonged to other agents, because it selected them by author and every agent on this team pushes under the same account. Automation selects work by an explicit branch list it owns, never by author."
metadata:
  type: feedback
---

**What happened (2026-03-05, the scheduling app repository):** I set up a merge job that
merged every green, unlabelled, conflict-free pull request "by me". All of our agents
push through one shared account, so "by me" meant everybody. In about twenty minutes it
merged five pull requests that other agents had parked. One was a pricing
screen waiting for the owner. Another was a set of test fixtures held back until a
contract change landed.

**Why it matters:** nothing red merged, and nothing with a stop label was touched, so
the guards worked. The selection was the hole, and it cost two agents a morning of
reverts.

**How to apply:** an automation picks pull requests from a list of branches the
orchestrator created in this session, or from a branch prefix it owns, and from nothing
else. Before arming any of them, check the claims on the board: a branch claimed by
another agent is a hard stop. A parked pull request often has no label at all, so a
missing label is not permission.

Related: [[check-the-board-before-arming-a-merge]], [[the-queue-throws-out-the-whole-batch]].
