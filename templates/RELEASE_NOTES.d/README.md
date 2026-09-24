<!--
Template: copy to RELEASE_NOTES.d/README.md. The directory matters more than
this file: a directory of small files is the whole point. Replace every
<PLACEHOLDER>.
-->

# Notes: one file per change

This directory is the record of what we ship. There are no releases and no
versions: every merge to `main` deploys within minutes, and these notes are how
a person finds out what changed.

**One file per change, so parallel pull requests never conflict on a shared
list.** In a single shared notes file, every branch adds its line at the
bottom. Once several lanes work at the same time, almost every pull request
conflicts there, and each conflict is resolved by hand, in a hurry, often
badly. One file per change removes that whole class of conflict. The same
applies to any list that only grows, such as an inventory or a registry: split
it into files before you run lanes in parallel, not after.

## Add a note in your pull request

Create one Markdown file here, named `<category>-<slug>.md`:

- **category** is one of `added`, `changed`, `deprecated`, `removed`, `fixed`,
  `security`. These are the standard changelog headings, so the digest can
  group the notes without anyone deciding anything.
- **slug** is a short kebab-case description, unique to your change. Start it
  with the issue or pull request id when you have one
  (`<ID>-<short-description>.md`), so two lanes never pick the same name.

The note is written **for the customer**: the person using the product, not
the engineer who wrote the code. Write one sentence, in the past tense. No
component names, no ticket ids, no internal words. Most notes are exactly one
line. If a change needs more, write one bullet per line.

For example, `fixed-template-button-label.md` contains:

```text
The "Use template" button no longer clips its label on narrow screens.
```

A purely internal change (a refactor, a test, a CI tweak) adds no note. Write
"no user-visible change" in the pull request body instead. The workflow asks
for one or the other, so saying nothing is never the answer.

## What happens to the notes

Set up a scheduled job that collects the notes into one digest, on a fixed
schedule: `<WHEN>`, for example every Friday evening in the owner's time zone.
The job groups the notes by category, writes the digest to `<WHERE>` (for
example `docs/changelog/`), posts it to `<CHANNEL>`, and deletes the notes it
used, in the same run. Nobody writes the digest by hand, and nobody approves
it: a job that waits for approval stops running.

Until that job exists, the notes simply collect here, and the first digest
picks up all of them. Nothing is lost by waiting.

Add a format check that runs on every pull request. It checks each file name
against the category list, and each body against the one-line rule. Keep the
check cheap, and make it required: it is what keeps this directory from
filling up with half-written notes.
