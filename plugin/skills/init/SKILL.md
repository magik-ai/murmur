---
name: init
description: Set up this repository to run agents as a team. Trigger on "set up murmur", "murmur init", "onboard this repo", "install the team contract here". Asks seven questions with defaults, stores the answers, then writes the contract, the tracker rules, a pull request template, a lessons file, the list of generated files and, when there is none, a CLAUDE.md. Never overwrites a file that already exists.
---

# Init

You are setting up one repository. Seven questions, then a handful of files.
It takes a couple of minutes, and it is safe to run again later.

Three rules hold for the whole run.

- **Never invent an answer.** Every question goes to the person, with its
  default shown. Silence is not consent, but pressing Enter is: an empty reply
  means the default.
- **Never write a file yourself, and never change one that exists.** The
  script writes. You ask, store and explain. That is what makes a second run
  safe.
- **Stop on an error.** If a command exits with an error, show the person its
  message and stop. Never edit `.murmur/config.toml` to get past it.

## 1. Find what is still unanswered

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_init.py questions
```

It prints a JSON array. Each item has `id`, `prompt`, `type`, `choices` and
`default`. An empty array means everything is answered already: skip to step 3.

## 2. Ask one question at a time, in the order printed

Put one question in front of the person, wait for the reply, and store it
before you ask the next. Do not put all seven in one message: a list of seven
questions gets one vague reply.

For each item, show the prompt, the choices when there are any, and the
default, like this:

```text
Where is work tracked?
  github-issues, linear, jira, notion, none
  default: github-issues  (press Enter to accept)
```

The item with `"multiple": true` takes several values, separated by commas.
Say so. Say also that the default is all of them, because that is the safe
answer: each value names an action that will need the person's word before it
happens.

Store each answer as it arrives:

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_init.py answer --id tracker --value linear
```

An empty reply means the default: pass the default as the value. The script
refuses a value that is not one of the choices and lists the choices, so a
typo costs one more question and nothing else.

## 3. Write the files

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_init.py apply
```

If the person said "just use the defaults" or "set it up, I will adjust later",
skip the questions and run `apply --defaults`: every unanswered question takes
its default.

It prints a JSON report with one entry per file. These are the files:

- `.murmur/config.toml`: the answers.
- `.murmur/contract.md`: the contract every agent here follows, built from the
  answers.
- `.claude/tracker.md`: how to use the chosen tracker.
- `.github/PULL_REQUEST_TEMPLATE.md`, `docs/GOTCHAS.md` (the lessons file) and
  `.claude/generated-files.txt` (the list of generated files that agents must
  not edit by hand): written only when they do not exist yet.
- `CLAUDE.md`: written from a template when the repository has none. It still
  has placeholders to fill in.
- An existing `CLAUDE.md` or `AGENTS.md` gets four lines appended that point to
  the contract.

Each entry has an action:

- `wrote`: the file was not there, now it is.
- `skipped`: nothing changed, and the note says why (identical, or already
  there and left alone).
- `appended`: the four pointer lines were added to the end of an existing
  `CLAUDE.md` or `AGENTS.md`. They are added once, never twice.
- `alongside`: the file exists and differs, so the new version was written next
  to it as `<name>.murmur-new`. Nothing of the person's was touched.

Show the report as a short list in plain words, not as raw JSON. Name every
`alongside` file out loud. Say that two versions now sit side by side, and
that the person should read both and keep one.

If `.claude/generated-files.txt` was written, say that it starts with example
entries, and that edits to those paths are now blocked. The person replaces
them with their own generated files, or deletes them.

## 4. Say what comes next

Three steps, in this order.

1. Read `.murmur/contract.md`. It is short. It is the file every agent in this
   repository is expected to follow, and it was written from the answers just
   given.
2. Run `/murmur:doctor`. It checks the setup and prints a table and one word
   for where the setup stands.
3. Start the first task. The work gets a branch, a pull request and, when a
   tracker was chosen, an issue.

## Running it again

This is safe and expected. Answered questions do not come back, so a second run
asks only what is new, for example after an update of the plugin adds a
question. Files that exist are not overwritten: identical files are skipped,
a changed contract or tracker file gets a `.murmur-new` version beside it, and
the pointer goes into `CLAUDE.md` or `AGENTS.md` only once.

To change an answer, store the new value with `answer` (or the person edits
`.murmur/config.toml` by hand), then run `apply` again. The contract is rebuilt
from the answers, so a changed answer shows up as a `.murmur-new` file for the
person to compare.
