<!--
A worked SAMPLE of a memory index. Everything in it is invented: one product (a
scheduling app), one owner (the person whose product it is, who reviews the
product rather than the code), a handful of agents working in one repository,
and a build host (a shared machine that runs their lanes; a lane is one agent
doing one task on its own branch). Read it for the SHAPE, not the content:
every link text is a full one-line claim, so this page answers most questions
without opening anything.
-->

# Memory index

## Sub-indexes (open the one that matches the task)

- [🧪 Checks that cannot fail (6 entries)](index-checks-that-cannot-fail.md)
- [🏗️ Infrastructure and the build host (4 entries)](index-infra.md)

## Latest active

- [🎰 The merge queue threw out three pull requests at once because two pull requests added the same new test file, and the local conflict check had reported no conflict](the-queue-throws-out-the-whole-batch.md)
- [🗓️ Every test shard went red on the same morning on unrelated branches, because one test read the real calendar and its fixture ran out that day](every-shard-red-means-look-at-the-calendar.md)
- [🔁 Four parallel lanes each invented their own loading ring, so the assembled branch was red on thirteen tests that were green in every lane](four-lanes-built-the-same-loading-ring.md)
- [🌙 Five lanes finished overnight but nothing was assembled, because the half-hourly heartbeat only fires while the chat session is open, and the session was closed](the-heartbeat-dies-with-the-session.md)
- [🛑 A stop notice went up on the board four minutes before I armed a merge, and the merge shipped into a half-migrated database](check-the-board-before-arming-a-merge.md)
- [🤖 An automated sweep merged five parked pull requests belonging to other agents, because it selected them by author and every agent pushes as the same account](an-automation-never-picks-work-by-author.md)
- [📝 A one-line comment change on an endpoint fails only inside the merge queue, because the generated client is compared there and nowhere else](the-generated-client-is-checked-only-in-the-queue.md)
- [💀 Cleaning up a test process by name killed the live dashboard on the shared build host, because both ran the same script on different ports](kill-by-port-never-by-name.md)

## Ground rules from the owner

- [🤖 Automation selects work by an explicit branch list it owns, never by author, because one account speaks for every agent](an-automation-never-picks-work-by-author.md)
- [🛑 Read the team board immediately before arming any merge, because a stop notice is a team-wide state that CI cannot see](check-the-board-before-arming-a-merge.md)
- [🔥 Anything long, parallel or noisy runs on the build host, never on the owner's laptop, because the owner works and gives demos on that laptop](heavy-runs-belong-on-the-build-host.md)
- [📖 A report is written for someone who was not watching, so the main text carries no code names and the jargon lives in a closing block](a-report-is-read-by-someone-who-was-not-there.md)
- [🖼️ The owner never opens a pull request, so acceptance is pictures and a live link, and a diff is not an answer](the-owner-never-opens-a-pull-request.md)

## Housekeeping

- One fact, one file. Never add a second, unrelated fact to an existing file.
- A fact that contradicts an older one replaces it, in the same pass.
- A lesson that changes how the team works belongs in the repository law file too.
- Write dates in full in the body, and never in the file name.
