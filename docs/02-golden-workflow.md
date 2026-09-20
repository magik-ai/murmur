# The golden workflow

## One change, ten gates

A single change moves through ten gates, from a fresh branch to a merged
commit. The list is short on purpose: a lane can recite it, and an orchestrator
can ask "which gate are you at?" and get a one word answer back.

The gates live in the law file (see
[`templates/CLAUDE.md`](../templates/CLAUDE.md), Golden Workflow). This chapter
says why each one exists.

## The ten gates

### 1. Branch from fresh main, in a worktree of its own

Fetch first, branch from the current tip, and work in a checkout nothing else
touches.

**The incident behind it.** A lane pushed a review fix to a branch whose pull
request had already merged underneath it. The push succeeded, the checks went
green, and the fix was simply not on `main`. A merged branch is dead the
moment it lands, so the next change starts from a new branch.

### 2. Implement one coherent batch, committing each reviewable slice

One batch is one idea, committed in slices a reviewer can read on their own.
The test for "one batch" is the two-pull-requests rule below.

### 3. Keep the documents current, in the same change

A change to a key contract or a major architectural decision moves the
architecture document and its decision record. Adding, moving, or retiring a
document moves the index. Changing how a subsystem behaves moves that subject's
knowledge file. Documents updated in a follow-up change are documents updated
never.

### 4. Add a release note, or declare there is none

Every change either adds a one sentence note written for a customer, or states
in the pull request body: no user-visible change.

Write it as one file per change, in a directory, never as a line appended to a
shared list. The parallel lanes chapter explains why a shared append-only file
is the most reliable conflict generator you can build.

The declaration matters as much as the note, because silence is ambiguous: a
missing note might mean an internal change, or a forgetful lane.

### 5. Run the affected checks locally

Lint, tests, build, contract checks: the ones this change can plausibly break.
Not the whole suite, the affected part.

### 6. Merge main into the branch while you work, and rerun

`main` moves under long-lived work. Merging it in early and often turns one
painful reconciliation into several trivial ones, and it surfaces a conflict
while both authors still remember their code.

### 7. Open the pull request with the one template

Exactly one template, used by every change. Walkthrough below.

### 8. Run an adversarial review on the exact head commit

A second agent, ideally a different model or vendor, reviews the change. A
writer checking its own work misses exactly what it was blind to, which is why
this is the highest leverage gate in the list.

Two details make it real. The review names the exact commit it read, because a
review of an older commit is not a review of this change. And it ends in a
verdict, clean or not clean, rather than in observations a lane can read
generously. The verdict is one line, `VERDICT <sha> CLEAN` or
`VERDICT <sha> RED`, and nothing else on that line. Use a deeper pass for
authentication, security, migrations, durability, or encrypted user content.

### 9. Fix every in-scope finding in the same change

In-scope findings are fixed here. Out-of-scope work becomes a ticket in the
`<TRACKER>` with a link back, not a comment saying "noted". A finding that
changes what a user experiences goes to the `<OWNER>` before the merge: whoever
found it is rarely the right person to decide it.

### 10. Arm auto-merge only after every gate has passed

Green checks qualify a change for merging; only the owner's explicit signal
merges it, and auto-merge is armed only after that signal. Arm it last, then
confirm the host reports the change merged, and only then remove the worktree.

**The incident behind it.** A lane armed auto-merge the moment it opened the
pull request, out of habit, while the adversarial review was still running. The
checks finished first and the change landed two minutes before the findings
posted, which then had to chase the merged code in a follow-up. A change
awaiting a named review keeps auto-merge off, and the reviewer holds the only
trigger.

Never bypass a gate with an administrator override. That power exists for
repairing a broken repository, not for being in a hurry. Each use makes the
gates below it advisory.

## One change, start to finish, with commands

The ten gates above say why. This is what they look like at a terminal, for a
single change on GitHub. Replace the names in angle brackets.

```bash
# Gate 1: branch from the current tip, in a working copy of its own.
git fetch origin
git worktree add ../<name> -b <branch> origin/main
cd ../<name>

# Gate 2: make the change, then commit each reviewable slice.
# The commit subject is "Type: subject": a capitalized type, an imperative
# verb, no full stop at the end.
git add <the files you changed>
git commit -m "Fix: keep the upload control visible before the first save"

# Gates 3 to 6: documents updated, a release note added or declared, the
# affected checks run locally, and the main branch merged in if it moved.
git merge origin/main

# Gate 7: push and open the pull request with the repository template.
git push -u origin <branch>
gh pr create --title "<ID>: <what changed>" \
             --body-file .github/PULL_REQUEST_TEMPLATE.md

# Gate 8: hand the exact head commit to the reviewer.
git rev-parse HEAD

# Gate 9: fix every in-scope finding here, then push again.

# Gate 10: wait for the owner's signal, then arm auto-merge.
gh pr merge <N> --auto --squash

# After the host reports it merged, remove the working copy.
git worktree remove ../<name>
```

Fill the pull request body with the template's own sections rather than
posting it blank. Most hosts open an editor with the template already loaded,
so `--body-file` is only needed when you are scripting it.

## The pull request template, section by section

The template is [`templates/PULL_REQUEST_TEMPLATE.md`](../templates/PULL_REQUEST_TEMPLATE.md).
Four sections, each with a job.

**Summary.** One or two sentences: what changed and why. This becomes the body
of the squash commit, so write it for whoever reads the history in six months,
not for the reviewer who has the diff open today.

**Slice.** Which thin vertical slice this is, with a link to the parent task in
the `<TRACKER>`.

**Acceptance guide.** The part that decides whether a non-author can act on the
change. It answers four questions. What changed, in product words a
non-engineer can follow. Which features might be affected, with that blast
radius derived by tracing callers and importers of the changed code, plus a
line saying how it was derived. How to check, as click paths with expected
outcomes. What could have broken, including what you could not verify.

The "how it was derived" line is load-bearing. A blast radius asserted from
memory and one traced through the code look identical on the page.

**Checklist.** Short, and every item is something that has actually gone wrong:
branched off fresh `main`, house style respected, checks green locally with any
known flake named, tests at the lowest tier that proves the behavior, one
backward-compatible migration, no secrets, adversarial review run on this head
commit, documents in sync, release note added or declared.

## Too hard to review in one sitting means two pull requests

This is the only rule about size, and it is deliberately subjective. Not a line
count, not a file count. Can one reviewer hold the whole change in their head
in a single pass? If not, splitting it is the work, moved earlier to where it
is cheap.

An oversized change also defeats gate 8. A reviewer facing forty files reads
ten carefully and skims the rest, and nobody learns which ten.

## Adopt it in a day

1. Copy [`templates/PULL_REQUEST_TEMPLATE.md`](../templates/PULL_REQUEST_TEMPLATE.md)
   into your repository, and delete any section you will not fill honestly.
2. Put the ten gates in your law file as a bare numbered list.
3. If you adopt only one gate, adopt gate 8. A review by a mind that did not
   write the code pays for itself immediately.
4. Stop arming auto-merge when the pull request opens. Arm it last, after the
   review verdict.
5. Write the acceptance guide for your last merged change retroactively. If you
   cannot say how you derived its blast radius, close that gap first.
