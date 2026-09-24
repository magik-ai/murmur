<!--
Template: copy to your agent's memory directory as MEMORY.md. For Claude Code
auto memory, that directory is ~/.claude/projects/<project>/memory/. This file
is the INDEX. Each fact lives in its own file next to it, written from
_fact.md. Only the structure is shown below, with no real entries: yours will
look nothing like these.

Why this shape. A memory directory grows to hundreds of files, and the index is
the only file an agent reads at the start of a session. Claude Code loads only
the first 200 lines (or 25 KB) of it. So the index must stay readable at a
glance, which means two rules:
  1. Every link text is a FULL ONE-LINE CLAIM, not a topic. "a push to a pull
     request that has already merged never reaches main" can be found by
     search; "merge queue notes" cannot. The link text IS the memory. Open the
     file only for the detail.
  2. When a section grows past about thirty lines, move it into a sub-index
     file and leave one link behind, with a count. An index longer than a
     screen stops being read to the end, and the entries at the bottom stop
     being found.
Optional: start each line with an emoji that marks its theme, so the list can
be scanned by shape. Use one on every line, or on none.
-->

# Memory index

## Sub-indexes (open the one that matches the task)

- [`<Theme: what this group of facts is about>` (`<N>` entries)](index-<theme>.md)
- [`<Theme>` (`<N>` entries)](index-<theme>.md)
- [`<Theme>` (`<N>` entries)](index-<theme>.md)

<!-- Themes that usually earn their own sub-index: active work and
     orchestration, checks that cannot fail (the traps in CI, merge steps and
     verification), infrastructure, product and workflow gotchas. Add one when
     a section outgrows the main index, never before. -->

## Latest active

The work in flight, newest first. Each line is one claim with the outcome
already in it, so the index answers most questions without opening anything.
Prune hard: a finished piece of work moves to a sub-index or is deleted.

- [`<what was being done, what it produced, what is still open>`](<slug>.md)
- [`<what was being done, what it produced, what is still open>`](<slug>.md)

## Ground rules from the owner

Decisions the owner made once and should never have to make again. This
section is the reason the index exists. Each line states the rule, not the
topic, and the file behind it tells the story that produced it.

- [`<the rule, stated as a rule, in one line>`](<slug>.md)
- [`<the rule, stated as a rule, in one line>`](<slug>.md)

## Housekeeping

- One fact, one file. Never add a second, unrelated fact to an existing file.
- A fact that contradicts an older one **replaces** it: edit or delete the old
  file in the same pass. Never leave both to be found later.
- A lesson that changes how work happens does not belong here alone. It
  belongs in the repository law file or the gotchas file too, in the pull
  request that learned it. Memory is a private notebook, not the team's law.
- Write dates in full (`YYYY-MM-DD`) in the body, and never in the file name.
