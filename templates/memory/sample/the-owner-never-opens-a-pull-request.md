---
name: the-owner-never-opens-a-pull-request
description: "Learned 2026-02-03: the owner does not open pull requests or read diffs. Anything that needs the owner's eyes arrives as before and after pictures plus a live link, with one question for each point the owner has to decide."
metadata:
  type: user
---

**What happened (2026-02-03, the reminder settings screen):** I asked the owner to look
at a pull request and say whether the new layout was right. The pull request was never
opened. Two days later, I showed the same change as two screenshots side by side, with a
link to a running preview. The owner answered in four minutes and asked for one spacing
change.

**Why it matters:** the owner makes the product decisions, and a decision that waits on
reading code does not happen. Every day a visual change waits for confirmation is a day
it cannot ship.

**How to apply:** package anything visual as pictures of the old state and the new
state, a link the owner can open and use, and a short numbered list where each point
ends in a question with a yes, no or number answer. Put the code links at the bottom,
for whoever reviews the code. Never send raw output from a working session as if it
were an acceptance package.

Related: [[a-report-is-read-by-someone-who-was-not-there]], [[an-automation-never-picks-work-by-author]].
