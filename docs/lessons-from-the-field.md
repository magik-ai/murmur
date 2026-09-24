# Lessons from the field

Ten failures from running coding agents on a real project, with every name
removed so only the mechanism is left. Each entry says what happened, why, and
what to do. In a lessons file these three parts are the symptom, the cause and
the prevention: see [`templates/GOTCHAS.md`](../templates/GOTCHAS.md) and
[chapter 08](08-knowledge-and-memory.md).

## A push to a queued pull request never reached main

**What happened.** A pull request showed as merged and its branch was green.
But the main branch did not have the newest commit, and it failed the very
test that commit fixed. The pull request said "merged", so the loss looked like
success. It showed only when someone read the merged file on main.

**Why.** The merge queue tests a temporary branch built from the pull request
as it was when it entered the queue. A later push is not part of that test.
Depending on the queue, such a push is left out of the merge, as it was here,
or merged without its own checks. So nobody tested the new commit, nobody
merged it, and it was left on a branch that was finished once the pull request
closed.

**What to do.** Do not push to a pull request that is in the merge queue.
Before you push, check whether the pull request is queued or already merged.
If it is queued, take it out of the queue first, then push and queue it again.
If it has merged, open a follow-up branch from the current main. After any
merge where a push raced the queue, compare main with the branch tip before you
believe the merge.

## A generated file conflicted again and again

**What happened.** The same pull request kept getting merge conflicts, always
in a file its author never opened: a lock file, a generated client, an API
document. Resolving the conflict by hand gave a file that looked right and
passed review, but no longer matched the sources it describes.

**Why.** Two things, neither of them the author's mistake. A generated file
changes faster than a pull request lives, so with several branches open, each
one falls behind at least once. And the generator wrote project-wide counters
into a single line, so unrelated changes always collided on that line. A
line-by-line merge of two generator outputs gives a third output that no
generator would ever write.

**What to do.** Never resolve a conflict in a generated file by hand. Take
main's version, rerun the generator on top of current main, and commit what it
produces. Mark generated paths so your tools stop offering a line-by-line
merge, and block hand edits to them ([chapter 11](11-safety-hooks.md)). Make
generators write one row per area instead of global counters, so unrelated work
touches unrelated lines.

## A clean merge deleted the branch's own work

**What happened.** A round of merges brought main into several branches. On
one branch, the conflict step settled every conflicted file by taking one side
whole, then committed and pushed. The working copy was clean and the diff
looked plausible. About two thousand lines of the branch's own tests and code
were gone.

**Why.** Two things together. When you merge main into your branch, git calls
main "theirs". So "take theirs" means "throw away my own work", the opposite of
how it reads. And the take-one-side step had been written for generated files,
where either side is safe because the next step rebuilds the file. It was then
reused on a list that had grown to include hand-written code. Nothing rebuilds
a test file.

**What to do.** Take one side whole only for a file that a generator rewrites
in the next step. For every other conflicted file, compare the merge base with
each side before you commit, and check that each side's changes survive in the
result. Then run the tests the branch itself added: a merge that undid the
branch still passes main's tests.

## A date in a test fixture turned every branch red on one morning

**What happened.** At one moment, every open branch started failing the same
test, on unrelated code, with an error that no change could explain. Main still
looked green, because its last run was before that moment. It looked like a
flaky test. It was not: from that minute it failed for everyone, every time.

**Why.** A test fixture held a fixed calendar date as the end of a period, and
the rule under test compared that date with the real clock. When real time
passed the date, every period in the tests lay in the past. An assertion that
was true the day before was now false for the whole repository.

**What to do.** When many unrelated branches fail at once, suspect the calendar
before the branches. A test of a rule that compares with the current time must
either set the clock explicitly or place its dates relative to now. A fixed
future date in a fixture fails on a day nobody chose, and on every open pull
request at once.

## A safety check that could only ever say "all clear"

**What happened.** For months, a safety check ran before every deploy and
never stopped one, which looked like a quiet system. The check searched the
service log for two event names and let the deploy go ahead when it found
none. It found none every time.

**Why.** Neither event name was ever logged. Hours of production logs from a
real, active session held no match, and the names did not appear anywhere in
the source code either. The check searched for text nobody had written, so its
answer carried no information. From the outside, a check that can only say
"all clear" looks the same as one that works.

**What to do.** Check the structure of a record, such as a field, not the
wording of a message: a field survives someone rewording a log line. Give the
check a test with production-like data, so "matches nothing" fails a test
instead of passing in silence. Make it fail closed: an empty result looks the
same as a quiet system, so treat it as a reason to stop. When you inherit a
one-line check, break the thing it guards and see the check go red before you
trust its green.

## A green preview served an old front end

**What happened.** The preview deploy was green: the image was new and the
container had restarted. But the front-end files it served were identical to
the previous build. A change that was clearly in the checked-out commit was in
no served file, while another file built into the same image did contain it.
The only sign was content that should have been there and was not.

**Why.** A race left the build cache stale. A new push cancelled the build
still running for the same pull request. That cancelled build had already
written cache entries under the same key, including stale compiled front-end
files. The next build took them as a valid cache hit and shipped an old front
end inside a new image.

**What to do.** Build preview environments without the cache. A preview exists
to show the latest commit, and a few uncached minutes beat a preview that is
silently stale. When a deployed change is not visible, look at the files inside
the running container before you doubt the code. Searching the live files for
a marker string tells "not built" from "not served" in one command.

## Another session committed in a shared working copy and undid a merged fix

**What happened.** A shared branch had two commits with the same title, from
two authors, minutes apart. The second one deleted a module, a test file and
several hundred lines of a fix that had merged an hour earlier. Nothing in the
diff said "revert", and auto-merge was already on for that commit.

**Why.** Two agent sessions shared one machine, and so one git directory. The
second session reset the branch that the first had checked out, and committed
in that working copy while the first session's commands were still running.
The branch moved underneath those commands, but git's staging area (the index)
still held the older files. The next commit recorded that old snapshot, which,
compared with the new head, undid everything that had landed in between.

**What to do.** One branch has one committer. To get work onto someone else's
branch, send them a message; never commit on their branch. In a chain of
commands, check before every commit that the author is you and that the status
lists exactly the files you changed. If the head moved, or a staged file
surprises you, stop and read the reflog (git's record of where each branch has
pointed). If a pull request on your branch has a head you did not push, turn
off its auto-merge before you repair anything.

## A session next door changed an agent's git name in the middle of a batch

**What happened.** The configured author name was right at the start of a
batch, and the first three commits had the right author. Then a commit in the
same working copy came out under another agent's name. Nothing in that working
copy had changed.

**Why.** Setting a git identity without a scope writes it into the shared
repository config, which every worktree (extra working copy) of that clone
reads. A session next door set its own name in its own worktree, and so
renamed every other session on the machine, including one halfway through a
batch. A worktree does not isolate anything that lives in the shared git
directory.

**What to do.** Set the identity per worktree when you create it. Turn on
per-worktree config once with `git config extensions.worktreeConfig true`, then
run `git config --worktree user.name "<name>"` (and `user.email`) in each
worktree. Check the author on the commit itself afterwards, not the config
before it, because the value can change in between. Fix a commit made under the
wrong name before you push it: `git commit --amend --reset-author --no-edit`.

## Thirty tests failed together, and each passed alone

**What happened.** A branch failed about thirty tests in one file, each saying
that a database column did not exist. The same file was green on main, the
migration that adds the column was correct, and every failing test passed on
its own or in a small group. It looked exactly like a broken migration.

**Why.** It was not the migration. An earlier test in the same file moved the
database schema backwards to test a real upgrade. It then restored the schema
to a fixed revision, the newest one on the day the test was written. Once a
newer migration landed, that restore stopped one revision short and left the
shared database incomplete for the rest of the run. Small groups passed
because the guilty test was not in them.

**What to do.** A test that changes shared state restores it to the current
newest revision, never to a fixed one. A fixed restore is right until the next
change lands, and then it is silently partial. Put this rule in a teardown
assertion that fails the guilty test by name, not in a comment: a comment
cannot notice when it stops being true. "Green alone, red together" points at
shared state. It is never a flaky test.

## A session setting made a shared connection pool read-only

**What happened.** Production writes failed with "cannot execute INSERT in a
read-only transaction", about a thousand a minute, for over an hour. Reads
worked, the database reported healthy, there was plenty of disk, and newly
started application instances failed in the same way.

**Why.** A maintenance script connected through the application's own
connection pooler and switched its session to read-only. That pooler runs in
transaction mode: it lends one server connection to many clients, one
transaction at a time, and does not reset session settings between them. The
read-only setting outlived the script on that server connection. Every
application transaction that landed there was read-only, and new instances
borrowed from the same pooler.

**What to do.** Scripts and people never use the application's credentials or
its pool. Give inspection its own read-only role on a session-mode pool, where
a session setting ends with the session. Do read-only work in a read-only
transaction, never with a session-level setting through any pooler. If it
happens anyway, recreate the pool: that drops every affected server connection.
