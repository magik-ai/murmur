<!-- Template: copy to docs/GOTCHAS.md, or let /murmur:init put it there. Keep
     the header as it is. The three entries below are examples: replace them
     with your own as you collect them. -->

# Gotchas

**Status:** current debugging history, read when needed.

This file is **not in the boot read list**. Nobody reads it at the start of a
task. An agent opens it when a symptom is surprising, and adds to it when a
symptom surprised them.

## The format

Each entry is **symptom -> cause -> prevention**, in that order, in one
paragraph.

- **Symptom** is what you actually saw, in the words the tool printed. A future
  agent finds this file by searching for the symptom, so write what it will
  search for, not your tidy summary of it.
- **Cause** is the mechanism, not a guess. "The test was flaky" is not a cause.
  "Two processes ran the same migration at the same time" is.
- **Prevention** is the action that stops a repeat. It says what to do
  instead, clearly enough that a stranger could follow it without asking you.

Add an entry only when the lesson is **specific enough to prevent a repeat**. A
general warning ("be careful with merges") costs everyone a line and helps
nobody. If the lesson changes how work happens, rather than how one tool
behaves, it belongs in the law file instead.

**The twice rule:** when the same mistake happens a second time, the correction
goes here (or into the law file) in the same pull request that fixes the second
occurrence. A lesson that stays in chat is lost.

New entries go at the end. Never delete an entry because it looks old. Delete
it only when the mechanism behind it is gone.

## Entries

- A merge conflict appears inside a generated file (a lock file, a generated
  client, an OpenAPI document, a compiled schema). Resolved by hand, the file
  passes review but fails the build, or passes both and describes a contract
  nobody wrote -> a generated file is output. Merging two outputs line by line
  gives a third output that no generator would ever write, and it silently
  disagrees with its source -> never resolve a conflict in a generated file by
  hand. Take the version from `main`, rerun the generator on your branch, and
  commit what it produces. Mark generated paths so your tools stop offering a
  line-by-line merge, and add a guard that refuses direct edits to those paths
  and prints the command that regenerates them. A warning sign: the two sides
  of the conflict differ in a checksum, an ordering or a version stamp.

- Every branch in the repository goes red on the same morning, on unrelated
  code, with a test failure that no change can explain -> a test fixture held
  an absolute date (an expiry, a trial end, a "valid until"), and the calendar
  moved past it. The assertion that was true yesterday is false for everyone
  today -> when many unrelated branches fail at once, suspect the calendar
  before the branches, and check what changed outside the repository since
  yesterday. To prevent it, never write an absolute date into a fixture. Give
  the time relative to when the test runs (a fixed offset from now), or freeze
  the clock in the test. A fixture with a fixed future date fails on a day
  nobody chose, on every open pull request at once.

- A fix is pushed to a pull request, the push succeeds, the pull request shows
  as merged, and the fix is not on `main` -> the push raced the merge queue.
  The queue tests a temporary branch built from the pull request as it was
  when it entered the queue. A later push is not part of that test: depending
  on the queue, it is left out of the merge or merged without its own checks.
  A push after the merge lands on a branch nobody will merge again -> do not
  push into a queued pull request. Before you push, check whether the pull
  request is queued or already merged. If it is queued, take it out of the
  queue, push, and queue it again. If it has merged, open a follow-up branch
  from the current `main`. After a push that raced the queue, compare `main`
  with the branch tip before you trust the merged state. The same trap catches
  a review finding that arrives while the queue runs, so check for unresolved
  review threads and for the `hold` label before you turn on auto-merge.

<!-- Add your entries below, newest last:
- Symptom, in the words the tool printed -> the mechanism, named exactly -> what
  to do instead, specific enough for a stranger to follow. (date, issue id)
-->
