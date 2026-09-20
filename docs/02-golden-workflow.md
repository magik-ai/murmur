# The golden workflow

## One change, ten gates

A single change moves through ten gates, from a fresh branch to a merged
commit. The list is short on purpose: a lane can recite it, and an orchestrator
can ask "which gate are you at?" and get a one word answer back.

The gates themselves live in the law file (see
[`templates/CLAUDE.md`](../templates/CLAUDE.md), the Golden Workflow section).
This chapter says why each one exists.

## The ten gates

### 1. Branch from fresh main, in a worktree of its own

Fetch first, branch from the current tip, and work in a checkout nothing else
touches. Never continue work by reusing a branch that has already merged.

**The incident behind it.** A lane pushed a review fix to a branch whose pull
request had already merged underneath it. The push succeeded, the checks went
green, and the fix was simply not on `main`. A merged branch is dead the moment
it lands.

### 2. Implement one coherent batch, committing each reviewable slice

One batch is one idea. Commit in slices a reviewer can read on their own. The
test for "one batch" is the two-pull-requests rule at the end of this chapter.

### 3. Keep the documents current, in the same change

If the change alters a key contract or a major architectural decision, the
architecture document and its decision record move with it. If it adds, moves,
or retires a document, the index moves with it. If it changes how a subsystem
actually behaves, the knowledge file for that subject moves with it.

Documents updated in a follow-up change are documents updated never.

### 4. Add a release note, or declare there is none

Every change either adds a one sentence note written for a customer, or states
in the pull request body: no user-visible change.

Write it as one file per change, in a directory, never as a line appended to a
shared list. The parallel lanes chapter explains why a shared append-only file
is the most reliable conflict generator you can build.

The "or declare" half matters as much as the note. A missing note might mean an
internal change, or it might mean a lane forgot. The declaration removes the
guess.

### 5. Run the affected checks locally

Lint, tests, build, contract checks: the ones this change can plausibly break.
Not the whole suite, the affected part. A lane that runs everything on every
save soon stops running anything.

### 6. Merge main into the branch while you work, and rerun

`main` moves under long-lived work. Merging it in early and often turns one
large painful reconciliation into several trivial ones, and it surfaces a
conflicting change while both authors still remember their code.

### 7. Open the pull request with the one template

There is exactly one template, and every change uses it. Walkthrough below.

### 8. Run an adversarial review on the exact head commit

A second agent, ideally a different model or a different vendor, reviews the
change. A writer checking its own work misses exactly what it was already blind
to, which is why this is the highest leverage gate in the list.

Two details make it real. The review names the exact commit it read, because a
review of an older commit is not a review of this change. And it ends in a
verdict, clean or not clean, rather than in observations a lane can interpret
generously. Use a deeper pass for authentication, security, data migrations,
durability, or encrypted user content.

### 9. Fix every in-scope finding in the same change

In-scope findings are fixed here. Genuinely out-of-scope work becomes a ticket
in the `<TRACKER>` with a link back, not a comment saying "noted".

A finding that changes what a user experiences goes to the `<OWNER>` before the
merge, not after. Whoever found it is rarely the right person to decide it.

### 10. Arm auto-merge only after every gate has passed

Arm it last, then confirm the host reports the change merged, and only then
remove the worktree.

**The incident behind it.** A lane armed auto-merge the moment it opened the
pull request, out of habit, while the adversarial review was still running. The
checks finished first and the change landed two minutes before the review
posted its findings, which then had to chase the merged code in a follow-up.
Auto-merge plus an in-flight review is a race, and it is a race you lose at the
worst possible time. A change awaiting a named review keeps auto-merge off, and
the reviewer holds the only trigger.

Never bypass a gate with an administrator override. That power exists for
repairing a broken repository, not for being in a hurry. Each time it lands a
change, every gate below it becomes advisory, and an advisory gate is not a
gate at all.

## The pull request template, section by section

The template is [`templates/PULL_REQUEST_TEMPLATE.md`](../templates/PULL_REQUEST_TEMPLATE.md).
Four sections, each with a job.

**Summary.** One or two sentences: what changed and why. This text becomes the
body of the squash commit, so write it for whoever reads the history in six
months, not for the reviewer who has the diff open today.

**Slice.** Which thin vertical slice this is, with a link to the parent task in
the `<TRACKER>`. It is also where the two-pull-requests rule bites.

**Acceptance guide.** The part that decides whether a non-author can act on the
change. It answers four questions. What changed, in product words a
non-engineer can follow. Which product features might be affected, with the
blast radius derived by tracing the callers and importers of the changed code,
and a sentence saying how it was derived. How to check, as concrete click paths
with expected outcomes, or the exact checks to inspect when there is no
interface. What could have broken, honestly, including anything you could not
verify.

The "how it was derived" line is the load-bearing one. A blast radius asserted
from memory and one traced through the code look identical on the page, and
only one of them is worth trusting. Saying which it is takes six words.

**Checklist.** Short, and every item is something that has actually gone wrong:
branched off fresh `main`, house style respected, checks green locally with any
known flake named, tests at the lowest tier that proves the behavior, one
backward-compatible migration, no secrets, adversarial review run on this head
commit, documents in sync, release note added or declared. Keep those and add
your own stack's below them.

## Too hard to review in one sitting means two pull requests

This is the only rule about size, and it is deliberately subjective. Not a line
count and not a file count. Can one reviewer hold the whole change in their
head in a single pass? If not, it is not one batch, and splitting it is not
extra work: it is the work, moved earlier, to where it is cheap.

An oversized change also defeats gate 8. A reviewer facing forty files reads
the first ten carefully and skims the rest, and nobody finds out which ten.

## Adopt it in a day

1. Copy [`templates/PULL_REQUEST_TEMPLATE.md`](../templates/PULL_REQUEST_TEMPLATE.md)
   into your repository, and delete any section you will not fill honestly.
2. Put the ten gates in your law file as a bare numbered list. The commentary
   belongs here, not there.
3. If you can adopt only one gate, adopt gate 8. A review by a mind that did
   not write the code pays for itself immediately.
4. Break the habit of arming auto-merge when the pull request opens. Arm it as
   the last action, after the review verdict.
5. Take your last merged change and write its acceptance guide retroactively.
   If you cannot say how you derived its blast radius, close that gap first.
