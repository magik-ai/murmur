# Lessons from the field

These are real incidents from a working repository, rewritten with every company,
product, person, host, ticket and date removed, so that only the mechanism is
left. Each entry keeps the format `templates/GOTCHAS.md` prescribes: symptom,
then cause, then prevention.

## A push into a queued pull request vanishes at merge

**Symptom.** A pull request reports MERGED and its branch is green, but the main
branch is missing the newest commit, and it goes red on the very test that commit
fixed. The loss masquerades as success, because the terminal state says merged. It
becomes visible only when you read the merged file out of the main branch.

**Cause.** A merge queue snapshots the head commit when the pull request enters the
queue, and it merges that snapshot. A push afterwards neither ejects the entry nor
refreshes it, so the new commit is verified by nobody and merged by nobody, and the
branch holding it dies when the pull request closes.

**Prevention.** Never push into a queued pull request. Either open a new pull
request from current main, or take the entry out of the queue first, push, and
re-queue so the snapshot is retaken. After any merge where a push raced the queue,
diff the main branch against the branch tip before believing the merged state.

## A generated file conflicts forever, and hand-merging it invents a contract

**Symptom.** The same pull request goes dirty again and again, and the conflict
always sits in a file the author never opened: a lock file, a generated client, an
API document. Resolving it by hand produces a plausible file that passes review
while disagreeing with the sources it claims to describe.

**Cause.** Two faults, neither of them a mistake by the author. A generated file
changes faster than a pull request lives, so with several branches in flight every
branch is overtaken at least once. And a generator that writes repository-wide
counters into one line makes independent changes collide on that line
unconditionally, because a line-based merge of two outputs produces a third output
no generator would emit.

**Prevention.** Never resolve a conflict in a generated file by hand. Take the
main branch version, rerun the generator on top of current main, and commit what it
produces. Mark generated paths so the tooling stops offering a line-level merge,
and make generators emit per-area rows instead of global counters, so unrelated
work touches unrelated lines.

## A clean merge that quietly deleted a branch's own work

**Symptom.** A train of merges brings the main branch into several sibling
branches. On one of them the conflict loop resolved every conflicted path by taking
one side wholesale, committed, and pushed. The working tree was clean and the diff
looked plausible, while about two thousand lines of the branch's own tests and
service code had just been thrown away.

**Cause.** Two things compounding. The side-taking flag names the branch being
merged in, so on a train it means "throw away my own work", the opposite of what it
suggests while you read it. And the wholesale resolution had been written for
generated files, where either side is safe because the next step rebuilds the file,
then reused on a list that had grown to include hand-written source. Nothing
rebuilds a test file.

**Prevention.** A blanket side-taking resolution is valid only for a file a
generator will rewrite in the next step. For every other conflicted path, diff the
merge base against each side before committing, and confirm each named change from
both lists survives in the resolved file. Then run the tests the branch itself
added: a merge that reverted the branch still passes the main branch's suite.

## A date written into a fixture turns every branch red on one morning

**Symptom.** At a round-numbered instant, every open branch starts failing the same
test, on unrelated code, with an error no change can explain. The main branch still
looks green because its last run predates the instant. It reads like a flake and it
is not: from that minute it fails for everyone, forever.

**Cause.** A fixture carried an absolute calendar date as a period end, and the
rule under test compares that end against the real wall clock. When real time
walked past the literal, every scenario's period was in the past, and the
assertion that had been true the day before was false for the whole repository.

**Prevention.** When many unrelated branches fail at once, suspect the calendar
before the branches. A test that exercises a rule comparing against the current time
must either inject the clock explicitly or anchor its instants relative to now. An
absolute future date in a fixture is a bomb with the fuse already lit, and its blast
radius is every open pull request at once.

## A guard that could only ever say "all clear"

**Symptom.** For months a safety check ran before every deploy and never held one
back, which looked like a quiet system. The check was a one-line search of the
service log for two event names, with the rule "proceed on zero matches", and it
printed zero every single time.

**Cause.** Neither event name was ever emitted. Hours of production logs holding a
real live session produced no matches, and the strings did not appear anywhere in
the source either. The check was matching prose nobody had ever written, so its
answer carried no information. A guard whose only possible answer is "all clear"
is indistinguishable from the outside from a guard that works.

**Prevention.** Gate on the structure of a record, not the wording of a message,
because a field survives someone rewording a log line. Give the guard a test with
production-shaped fixtures so "matches nothing" is a red test rather than a silent
zero, and make it fail closed: "the query returned nothing" and "nothing is
happening" produce the same output. Whenever you inherit a one-line check, break the
thing it guards on purpose and require a red before trusting any green from it.

## A green preview that served a bundle older than the commit it built

**Symptom.** The preview deploy is green, the image is new, the container restarted
on schedule, and the served frontend bundle is byte-identical to the previous build.
A change provably present in the checked-out commit appears in no served file, while
a second artifact baked into the same image does contain it. The only tell is
content that should exist and does not.

**Cause.** The build layer cache was poisoned by a race. A new push cancels the
in-flight build for the same pull request, and a cancelled build that already wrote
cache entries under the same key can leave a stale compiled-assets layer behind. The
next build takes a valid-looking cache hit for that layer and ships an old frontend
inside a fresh image.

**Prevention.** Build preview environments with the cache disabled: a preview exists
to show the head, so a few uncached minutes beat a silently stale review surface.
When a deployed change is invisible, check the running container's filesystem before
doubting the code. Searching the live files for a marker string separates "not
built" from "not served" in one command.

## A sibling session committed into my worktree and reverted a merged fix

**Symptom.** A shared branch carried two commits with the same title from two
different authors minutes apart, and the second deleted a module, a test file and
several hundred lines of a fix that had merged an hour earlier. Nothing in the diff
said "revert", and auto-merge was already armed on that head.

**Cause.** Two agent sessions shared one machine and therefore one git directory.
The second reset the branch the first had checked out and committed inside that
worktree while the first session's command chain was still running. The head moved
under the chain while the index still held the older tree, so the commit faithfully
recorded a stale snapshot, which relative to the new head was a revert of everything
that had landed in between.

**Prevention.** One branch has one committer, and a shared cut is fed by message,
never by committing on someone else's branch. Inside a command chain, verify before
every commit that the author is you and that the status lists exactly the files you
changed. A moved head or a surprise staged file means stop and read the reflog, and
a pull request on your branch with a head you did not push gets auto-merge disarmed
before anything is repaired.

## A neighbour renamed me mid-batch and I nearly signed a commit as them

**Symptom.** The configured author name was correct at the start of a batch and the
first three commits were attributed correctly, then a commit in the very same
worktree came out authored by a different agent. Nothing in that worktree had
changed.

**Cause.** Setting an identity without a scope writes into the shared repository
config, which every worktree of that clone reads. A sibling session setting its own
name in its own worktree silently renames every other session on the machine,
including ones halfway through a batch. A worktree is not an isolation boundary for
anything living in the git directory.

**Prevention.** Write identity into the per-worktree scope when the worktree is
created, so a neighbour cannot reach it. Verify the author on the commit itself
afterwards rather than reading the config before it, because the value can change
between the read and the write. A commit already made under the wrong name is fixed
by amending with a reset author, before it is pushed.

## Dozens of tests fail together and every one of them passes alone

**Symptom.** A branch fails thirty-odd tests in one file with an error saying a
database column does not exist. The same file is green on the main branch, the
migration that adds the column is correct, and every failing test passes on its own
or in a small subset. It reads exactly like a broken migration.

**Cause.** It was not the migration. One earlier test in the same file moved the
schema backwards to exercise a real upgrade, then restored it to a pinned revision
that had been the head the day the test was written. Once a newer migration landed,
the restore stopped one revision short and left the shared database incomplete for
the rest of the run. Subsets pass because the offending test is not in them.

**Prevention.** A test that moves shared state restores it to the current head,
never to a pinned identifier, because a pinned restore is correct until the next
change lands and then silently partial. Put the invariant in a teardown assertion
that fails the guilty test by name, not in a comment, since a comment cannot notice
when it stops being true. "Green alone, red together" is a statement about shared
state, never a flake.

## A session setting poisoned a shared connection pool

**Symptom.** Production writes fail with "cannot execute INSERT in a read-only
transaction", about a thousand a minute, for over an hour. Reads work, the database
cluster reports healthy, there is plenty of disk, and freshly started application
instances fail in exactly the same way.

**Cause.** A maintenance script connected through the application's own connection
pooler and set read-only at the session level. That pooler runs in transaction mode:
it lends one server connection to many clients, one transaction at a time, and does
not reset session settings between them. The flag outlived the script on that server
connection, so every application transaction landing there was read-only, and new
instances borrow from the same pooler.

**Prevention.** Scripts and people never use the application's credentials or its
pool. Give inspection its own read-only role on a session-mode pool, where a session
setting dies with the session. Read-only work is a read-only transaction, never a
session-level setting through any pooler. Recreating the pool drops every poisoned
server connection if it happens anyway.

## Source headings used

These ten entries come from the following headings in the source file:

1. A push into a queued PR silently vanishes at merge
2. A PR conflicts again and again on a file nobody edited by hand
3. Resolving a conflict with "take their side" deleted 2000 lines and the merge looked clean
4. A billing test suite that hardcodes calendar dates is a time bomb, not a flake
5. The deploy guard that let every deploy through
6. A green preview deploy served a frontend from before the commit it checked out
7. A sibling session committed into my worktree, and my next commit reverted a merged fix
8. A neighbour renamed me mid-batch and I nearly signed a commit as them
9. Thirty-two tests die on a column that "does not exist", and every one of them passes alone
10. A script's read-only flag broke every app write through the shared pool
