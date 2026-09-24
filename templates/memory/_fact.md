<!--
Template: copy to <slug>.md in your memory directory, and rename it. Delete
this comment and the one at the end: the front matter must be the first thing
in the file. Always one fact per file. The file name is the slug used in the
index link.

Naming: a kebab-case phrase that states the claim, not the topic.
"a-push-after-the-merge-never-reaches-main" can be found by search;
"merge-queue" cannot.
-->
---
name: <slug, identical to the file name without .md>
description: "<The whole fact in one or two sentences, with its date. A search
  returns this string, and often nothing else is read, so it must stand alone:
  who decided it or what produced it, what it means, and when.>"
metadata:
  type: <user | feedback | project | reference>
---

**What happened (`<YYYY-MM-DD>`, `<where or in what context>`):** the concrete
event, in two or three sentences. What was being done, what was seen, what was
said. Keep the surprising detail: it is what makes the fact memorable.

**Why it matters:** what this cost, or would cost next time. One or two
sentences. A fact with no cost attached is trivia, and should not be a file.

**How to apply:** the change in behavior, in the imperative, specific enough
that a stranger could follow it without asking. Name the command, the check,
the order of steps. If the fact has an exception, name it here, because a rule
without its exception gets applied where it does not belong.

Related: [[`<slug>`]], [[`<slug>`]].

<!--
The four types, and what belongs in each:
  user       about the owner: preferences, role, working style.
  feedback   a correction or a decision the owner gave. These are the ground
             rules; they outrank everything else you remember.
  project    the state or history of a specific piece of work.
  reference  a durable fact about a system or a tool, or where to find
             information outside the repository.
Anything you would defend in an argument belongs in the repository law file
instead, where the whole team can see it.
-->
