<!--
Template: copy to your agent memory directory as MEMORY.md. This file is the
INDEX. The facts themselves live one per file next to it, each written from
_fact.md. Structure only below: no real entries, because yours will be nothing
like ours.

Why this shape. A memory directory grows into hundreds of files, and the index
is the only thing an agent reads at boot. So the index must stay readable at a
glance, which means two rules:
  1. Every link text is a FULL ONE-LINE CLAIM, not a topic. "the queue takes a
     snapshot of the head commit when a pull request enters it" is findable;
     "merge queue notes" is not. The link text IS the memory; opening the file
     is for the detail.
  2. When a section passes roughly thirty lines, it moves into a sub-index file
     and leaves one link behind with a count. An index longer than a screen
     stops being read to the end, and the entries at the bottom stop being
     found.
Optional: a leading emoji pair per line makes the list scannable by shape. Use
it consistently or not at all.
-->

# Memory index

## Sub-indexes (open the one that matches the task)

- [`<Theme: what this group of facts is about>` (`<N>` entries)](index-<theme>.md)
- [`<Theme>` (`<N>` entries)](index-<theme>.md)
- [`<Theme>` (`<N>` entries)](index-<theme>.md)

<!-- Themes that earn their own sub-index, from experience: active work and
     orchestration, checks that cannot fail (the traps in CI, gates and
     verification), infrastructure, product and workflow gotchas. Add one when a
     section outgrows the main index, never before. -->

## Latest active

The work in flight, newest first. Each line is one claim, with the outcome
already in it, so the index answers most questions without opening anything.
Prune ruthlessly: a finished piece of work moves to a sub-index or is deleted.

- [`<what was being done, what it produced, what is still open>`](<slug>.md)
- [`<what was being done, what it produced, what is still open>`](<slug>.md)

## Ground rules (the owner's, non-negotiable)

Rulings the owner made once and should never have to make again. This section is
the reason the index exists. Each line states the rule, not the topic, and the
file behind it carries the story that produced it.

- [`<the rule, stated as a rule, in one line>`](<slug>.md)
- [`<the rule, stated as a rule, in one line>`](<slug>.md)

## Housekeeping

- One fact, one file. Never append a second unrelated fact to an existing file.
- A fact that contradicts an older one **replaces** it: edit or delete the old
  file in the same pass, and never leave both to be found later.
- A lesson that changes how work happens does not belong here alone. It belongs
  in the repository law file or the gotchas file, in the pull request that
  learned it. Memory is the operator's notebook, not the team's law.
- Dates are absolute in the body and never in the file name.
