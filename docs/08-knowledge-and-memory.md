# Knowledge and memory

An agent starts every session knowing nothing from earlier sessions. Unless
someone writes down what it learned, the lesson is lost when the session ends,
and the next agent makes the same mistake. This is why a team of agents
forgets faster than a team of people.

This chapter says where each kind of learning goes:

| What you learned | Where it goes | Who reads it, and when |
| --- | --- | --- |
| A rule the team now follows | The law file | Every agent, at the start |
| A debugging lesson | The lessons file | Anyone, when a symptom looks familiar |
| How one part of the system behaves | A knowledge file | Anyone working on that part |
| An agent's running notes | Its memory | That agent, each session |

The law file is the file in your repository that says how work happens
([chapter 01](01-repo-law.md)).

## The twice rule

The first time an agent makes a mistake, fix the mistake and move on. Most
one-off mistakes never happen again, and a rule for each one is noise.

The second time the same mistake happens, it is a pattern, and a pattern needs
a rule. So the change that fixes the second occurrence also adds a line to the
law file or the lessons file. That change does not merge without the line.

A lesson that stays only in chat gets learned a third time.

## The lessons file

Keep one running file of debugging stories. Each entry has three parts, in
this order:

1. **Symptom**: what you actually saw, in the words the tool printed. The next
   agent finds the entry by searching for those words.
2. **Cause**: the real mechanism, not a guess.
3. **Prevention**: the concrete step that stops a repeat, such as a check to
   run or a rule to follow.

An entry earns its place only if it is specific enough to prevent a repeat.
"Be more careful" is not an entry. "This exact symptom means this exact cause,
so run this exact check first" is.

Do not load this file at the start of every session. Over the life of a
project it grows to thousands of lines, and reading it every time would crowd
out more useful context. Instead, search it when a symptom looks familiar,
before you start debugging from scratch.

The template is [`templates/GOTCHAS.md`](../templates/GOTCHAS.md), and
`/murmur:init` copies it to `docs/GOTCHAS.md` in your repository.
[Lessons from the field](lessons-from-the-field.md) has ten more examples.

**The incident behind it.** One project let this file grow without the
three-part shape, and narrated debugging sessions mixed with real lessons. The
file became too noisy to search, so agents stopped checking it before they
debugged. That defeated the reason for keeping it.

## One knowledge file per domain

Keep one file per subject area (a domain), separate from the lessons file. A
knowledge file says how one part of the system really behaves: its measured
numbers (costs, timings, limits), the facts that must always hold, and the
checks that show whether "looks fine" is true.

Write one file per domain, never one per person. People leave a project, and
domains stay. Each file opens with a maintainer line and a last-updated date,
so a reader can tell whether to trust it or to check it.

Two shapes cover almost everything:

- **Operational knowledge**: measured facts and habits. Each one is a short
  claim with its evidence and a date, so a number that has aged can be found
  and refreshed.
- **Subject orientation**: a map for a newcomer. It covers what the subject
  includes, the facts that must always hold, how to investigate it, and the
  mistakes made in it before.

Pick the shape that fits, or mix them when a domain needs both.

Knowledge lands in the same change that created it, not in a cleanup later.
If a change alters how a part of the system behaves, what it costs or how long
it takes, the matching knowledge file changes in the same reviewed change. A
knowledge file that no longer matches reality does more harm than an empty
one, because readers believe it. Whoever notices a stale line fixes or deletes
it at once, in whatever change found it.

The templates are in [`templates/knowledge/`](../templates/knowledge/): a
README for the folder and `_domain.md` for each domain file.

## The memory index

An agent that works on one project across many sessions collects notes:
things worth remembering that are neither lessons nor domain knowledge. Keep
them as one fact per file, plus an index.

- Each fact lives in its own small file. A short header says what it is and
  when it was learned, and the body holds one clear idea.
- The index lists the facts. Each link text is the whole fact in one line, so
  the index answers most questions without opening anything.
- When a section of the index grows past about thirty lines, move it into a
  sub-index for that topic. Leave one link behind, with a count of its facts.

One fact per file sounds wasteful until you try the alternative. One growing
file of mixed facts becomes as hard to search as a lessons file without its
three-part shape. Small files are easy to search, easy to link to, and easy to
delete when a fact stops being true.

The templates are in [`templates/memory/`](../templates/memory/), with a
worked example in [`templates/memory/sample/`](../templates/memory/sample/).

## What to publish, and what never to

Publish the law file, the lessons file and the knowledge files. They are how a
new contributor, human or agent, gets up to speed quickly.

An agent's memory is different. It collects whatever sessions happened to
learn about one team: people, internal addresses, one-off arrangements. Much
of it was never meant to be public. Treat it as private notes, not as
documentation. If a fact in it is a lasting lesson, move it into the lessons
file or a knowledge file, with anything identifying removed. Never publish the
memory as it is.

## Adopt it in a day

1. Create the lessons file with the symptom, cause and prevention header and
   one real example.
2. Pick your most fragile subsystem and write its first knowledge file, with a
   maintainer line.
3. Add the twice rule to your law file: the second time a mistake happens, the
   change that fixes it also adds a line to the lessons file.
4. Start a memory index, even with one entry, so the habit of one fact per
   file exists before the pile grows large enough to need it.
