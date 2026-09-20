---
name: the-owner-never-opens-a-pull-request
description: "Established 2026-02-03: the owner does not open pull requests or read diffs, so anything needing his eyes arrives as before and after pictures plus a live link, with one question per point he has to decide."
metadata:
  type: user
---

**What happened (2026-02-03, the reminder settings screen):** I asked him to look at a
pull request and say whether the new layout was right. He never opened it. Two days
later, when the same change was shown as two screenshots side by side with a link to a
running preview, he answered in four minutes and asked for one spacing change.

**Why it matters:** he is the product decision, and a decision that waits on him reading
code does not happen. Every day a visual change sits unconfirmed is a day the work cannot
ship.

**How to apply:** package anything visual as pictures of the old state and the new state,
a link he can click and use himself, and a short numbered list where each point ends in a
question he can answer with yes, no, or a number. Keep the code links at the bottom for
whoever reviews the work. Never send raw output from a working session as if it were an
acceptance package.

Related: [[a-report-is-read-by-someone-who-was-not-there]], [[the-owner-speaks-in-flowing-sentences]].
