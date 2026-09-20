---
name: a-report-is-read-by-someone-who-was-not-there
description: "On 2026-01-22 the owner read my morning report and asked what language it was written in. Standing rule since: the main text of any report is plain words about the user's experience, and names, paths and numbers go in a closing block for engineers."
metadata:
  type: feedback
---

**What happened (2026-01-22, morning report on the booking flow):** I opened with a
sentence full of internal vocabulary: a guarded write path, a one-shot marker, a gated
call to action, and a build identifier. The owner replied that he understood almost none
of it and told me to make every report readable by a person who was not in the code all
night, with the details kept for whoever wants them.

**Why it matters:** he is a product person and the report is how he decides what to do
next. A page he has to decode is a page he does not act on, and the work behind it may as
well not have happened.

**How to apply:** lead with what was broken for the person using the app, what works now,
and how it was checked. One idea per sentence. Explain any term the first time or replace
it with an everyday word. Keep links and identifiers, but put them under a short closing
block, never inside the sentence that carries the meaning.

Related: [[the-owner-speaks-in-flowing-sentences]], [[the-owner-never-opens-a-pull-request]].
