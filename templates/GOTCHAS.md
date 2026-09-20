<!-- Template: copy to docs/GOTCHAS.md. Keep the header as written, replace the
     three examples with your own once you have them. The examples below are real
     incidents, rewritten with every name removed. -->

# Gotchas

**Status:** current debugging history, loaded on demand.

This file is deliberately **out of the boot contract**. Nobody reads it at the
start of a task. An agent opens it when a symptom is surprising, and extends it
when a symptom was surprising to them.

## The format

Each entry is **symptom -> cause -> prevention**, in that order, in one
paragraph.

- **Symptom** is what you actually saw, in the words the tool printed. A future
  agent finds this file by searching for the symptom, so write the symptom it
  will search for, not your tidy summary of it.
- **Cause** is the mechanism, not the guess. "The test was flaky" is not a
  cause. "Two processes ran the same migration concurrently" is.
- **Prevention** is the action that stops the repeat. It names what to do
  instead, and it is specific enough that a stranger could follow it without
  asking you.

Add an entry only when the lesson is **specific enough to prevent a repeat**. A
general warning ("be careful with merges") costs everyone a line and saves
nobody. If the lesson changes how work happens rather than how one tool
behaves, it belongs in the law file instead.

**The twice rule:** when the same mistake happens a second time, the correction
lands here (or in the law file) in the very PR that fixes the second occurrence.
A lesson that stays in chat is a lesson lost.

Newest entries go at the end. Never delete an entry because it looks old:
delete it only when the mechanism behind it is gone.

## Entries

- A merge conflict appears inside a generated file (a lock file, a generated
  client, an OpenAPI document, a compiled schema) and resolving it by hand
  produces a file that passes review but fails the build, or worse, passes both
  and encodes a contract nobody wrote -> a generated file is an output, so
  merging two outputs line by line produces a third output that no generator
  would ever emit, and the hand-edited result silently disagrees with its
  source -> never hand-resolve a conflict in a generated file. Take the version
  from `main`, re-run the generator on your branch, and commit what it produces.
  Mark generated paths so the tooling stops offering you a line-level merge, and
  add a pre-edit guard that refuses a direct edit to those paths and prints the
  generate command instead. The tell that you are about to get this wrong is a
  conflict whose two sides differ in a checksum, an ordering, or a version
  stamp.

- Every branch in the repository goes red on the same morning, on unrelated
  code, with a test failure that nobody's change can explain -> a test fixture
  carried an absolute date (an expiry, a trial end, a "valid until"), and the
  calendar walked past it, so the assertion that was true yesterday is false for
  everyone today -> when many unrelated branches fail at once, suspect the
  calendar before the branches, and check what changed between yesterday and
  today outside the repository. Prevent it by never writing an absolute date
  into a fixture: express the time relative to the moment the test runs (a fixed
  offset from now), or freeze the clock explicitly in the test. A fixture with a
  hard-coded future date is a bomb with the fuse already lit, and the blast
  radius is every open PR at once.

- A fix is pushed to a pull request that is already sitting in the merge queue,
  the push succeeds, the checks go green, the PR merges, and the fix is simply
  not on `main` -> the queue took a snapshot of the head commit when the PR
  entered it, and it merges that snapshot; anything pushed afterwards is not in
  the merge, and the branch it landed on is dead the moment the PR closes -> do
  not push into a queued pull request. Before pushing, check whether the PR is
  queued or already merged, and if it is, remove it from the queue first or open
  a fresh follow-up branch from current `main`. The same trap catches a review
  finding that arrives while the queue is running, so check for unresolved
  conversations and for the blocking label before enabling auto-merge at all.

<!-- your entries below, newest last:
- Symptom, in the words the tool printed -> the mechanism, named exactly -> what
  to do instead, specific enough for a stranger to follow. (date, issue id)
-->
