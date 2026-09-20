---
name: init
description: Set up this repository to run agents as a team. Trigger on "set up murmur", "murmur init", "onboard this repo", "install the team contract here". Asks seven questions with defaults, stores the answers, then writes the contract, the tracker rules, the pull request template and the gotchas file without overwriting anything.
---

# Init

You are onboarding one repository. Seven questions, then a handful of files.
It takes a couple of minutes and it is safe to run again later.

Two rules hold for the whole run.

- **Never invent an answer.** Every question goes to the person, with its
  default shown. Silence is not consent, but pressing Enter is: an empty reply
  means the default.
- **Never write a file yourself.** The script writes. You ask, store and
  explain. That is what makes a second run safe.

## 1. Ask what is still unanswered

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_init.py questions
```

It prints a JSON array. Each item has `id`, `prompt`, `type`, `choices` and
`default`. An empty array means everything is answered already: skip to step 3.

## 2. Ask, one question at a time, in the order printed

Put one question in front of the person, wait, then store it before asking the
next. Do not batch all seven into one message: a list of seven prompts gets one
vague reply.

For each item, show the prompt, the choices when there are any, and the
default, like this:

```
Where is work tracked?
  github-issues, linear, jira, notion, none
  default: github-issues  (press Enter to accept)
```

The item with `"multiple": true` takes several values, comma separated. Say so,
and say that the default is all of them, because that is the safe answer: each
value names an action that will need the person's word before it happens.

Store each answer as it arrives:

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_init.py answer --id tracker --value linear
```

An empty reply means the default: pass the default as the value. The script
rejects a value outside the choices and says what the choices are, so a typo
costs one more question and nothing else.

## 3. Write the files

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_init.py apply
```

It prints a JSON report, one line per file, with an action:

- `wrote`: the file was not there, now it is.
- `skipped`: nothing changed, and the note says why (identical, or already
  there and left alone).
- `appended`: four lines were added to the end of an existing law file, giving
  the path of the contract. It is added once and never twice.
- `alongside`: the file exists and differs, so the new version was written next
  to it as `<name>.murmur-new`. Nothing of the person's was touched.

Show the report as a short list in plain words, not as raw JSON. Name every
`alongside` file out loud and say that two versions now sit side by side, and
that they should read both and keep one.

## 4. Say what comes next

Three steps, in this order.

1. Read `.murmur/contract.md`. It is short. It is the file every agent in this
   repository is expected to follow, and it was written from the answers just
   given.
2. Run the doctor, which checks the setup and prints a table plus one word for
   where it stands.
3. Start the first task. The work gets a branch, a pull request and, when a
   tracker was chosen, an issue.

## Running it again

Safe, and expected. Answered questions do not come back, so a second run only
asks what is new, for example after the plugin adds a question. Files that
exist are never overwritten: identical files are skipped, changed files get a
`.murmur-new` version beside them, and an existing law file gets its pointer
only once.

To change an answer, edit `.murmur/config.toml` by hand and run `apply` again.
The contract is regenerated from the answers, so a changed answer shows up
there as a `.murmur-new` file for the person to compare.
