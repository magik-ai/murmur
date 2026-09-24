<!-- Sub-index. Same rule as the main index: every link text is a full claim. -->

# Checks that cannot fail

Traps in continuous integration, in the merge queue, and in the habits around
them. A check that gives a false answer is worse than a missing check, so each
entry names the false answer and what to read instead.

- [🎰 The merge queue throws out the whole batch when two pull requests add the same new file, and the local conflict check does not see that kind of clash](the-queue-throws-out-the-whole-batch.md)
- [📝 A one-line comment change on an endpoint passes branch checks and fails inside the queue, because the generated client is compared only there](the-generated-client-is-checked-only-in-the-queue.md)
- [🗓️ When unrelated branches go red in the same hour, the branches are innocent and the calendar is the suspect](every-shard-red-means-look-at-the-calendar.md)
- [🛑 Green checks never prove a merge is allowed, because a stop notice lives on the team board and not in the build](check-the-board-before-arming-a-merge.md)
- [🤖 Selecting pull requests by author matches every agent's work, because one account pushes for all of them](an-automation-never-picks-work-by-author.md)
- [🔁 Lanes that are each green can still be red together, so the assembled branch is tested again before the pull request opens](four-lanes-built-the-same-loading-ring.md)
