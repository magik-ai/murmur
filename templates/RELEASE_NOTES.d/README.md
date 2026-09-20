<!--
Template: copy to RELEASE_NOTES.d/README.md (the directory name matters more
than the file: a directory of small files is the whole point). Replace every
<PLACEHOLDER>.
-->

# Notes: one file per change

This directory is the whole record of what we ship. There are no releases and no
versions: every merge to `main` deploys within minutes, and these notes are how
a person finds out what changed.

**One file per change, so parallel pull requests never conflict on a shared
list.** This is not a style preference. A single shared notes file, appended to
at the bottom by every branch, was the single biggest source of merge churn we
had: three lanes editing one tail produced a conflict on almost every pull
request, and each conflict was resolved by hand, badly, in a hurry. Splitting it
into one file per change removed the conflict class entirely. The same reasoning
applies to any append-only inventory a team keeps: split it before you
parallelize, not after.

## Add a note in your pull request

Create one Markdown file here, named `<category>-<slug>.md`:

- **category** is one of `added`, `changed`, `deprecated`, `removed`, `fixed`,
  `security`. They map to the standard changelog headings, so the digest can
  group them without a human deciding anything.
- **slug** is a short kebab-case description, unique to your change. Prefix it
  with the issue or pull request id when you have one
  (`<ID>-<short-description>.md`), so two lanes never collide on a name.

The file body is the one-sentence, past-tense, **customer-facing** note. Write
it for the person using the product, not for the engineer who wrote the code. No
component names, no ticket ids, no internal vocabulary. One bullet per line, and
most notes are exactly one line.

```
# fixed-template-button-label.md
The "Use template" button no longer clips its label on narrow screens.
```

A purely internal change (a refactor, a test, a CI tweak) adds no note. Say "no
user-visible change" in the pull request body instead. The workflow gate asks
for one or the other, so silence is never the answer.

## What happens to the notes

A scheduled job collects the accumulated notes into one digest, on a fixed
cadence (`<WHEN>`, for example every Friday evening in the owner's time zone).
It groups them by category, writes the digest to `<WHERE>` (for example
`docs/changelog/`), posts it to `<CHANNEL>`, and deletes the notes it consumed
in the same run. Nobody writes the digest by hand and nobody approves it: if it
needed approval, it would not run.

Until that job is live, notes simply accumulate here and the first digest
collects every one of them. Nothing is lost by waiting.

A format check runs on every pull request: it validates the file name against
the category list and the body against the one-line rule. That check is the only
thing standing between this directory and a pile of half-written notes, so keep
it cheap and keep it required.
