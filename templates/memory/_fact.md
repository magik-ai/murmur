<!--
Template: copy to <slug>.md in your memory directory and rename. One fact per
file, always. The file name is the slug used in the index link.

Naming: a kebab-case sentence fragment that states the claim, not the topic.
"a-queued-pull-request-ignores-later-pushes" is findable by search; "merge-queue"
is not.
-->
---
name: <slug, identical to the file name without .md>
description: "<The whole fact in one or two sentences, with its date. This string
  is what a search returns and often all that is read, so it must stand alone:
  who ruled it or what produced it, what it means, and when.>"
metadata:
  type: <user | feedback | project | reference>
---

**What happened (`<YYYY-MM-DD>`, `<where or in what context>`):** the concrete
event, in two or three sentences. What was being done, what was observed, what
was said. Keep the surprising detail: the detail is why the fact is memorable.

**Why it matters:** what this cost, or would cost next time. One or two
sentences. A fact with no cost attached is trivia and should not be a file.

**How to apply:** the behavior change, in the imperative, specific enough that a
stranger could follow it without asking. Name the command, the check, the order
of steps. If the fact has an exception, name the exception here, because an
unqualified rule gets applied where it does not belong.

Related: [[`<slug>`]], [[`<slug>`]].

<!--
The four types, and what belongs in each:
  user       something about the owner: preferences, working style, context.
  feedback   a correction or a ruling the owner gave. These are the ground
             rules; they outrank everything else you remember.
  project    the state or history of a specific piece of work.
  reference  a durable technical fact about a system or a tool.
Anything you would defend in an argument belongs in the repository law file
instead, where the whole team can see it.
-->
