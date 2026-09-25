# The golden workflow

A change passes ten gates on its way from a fresh branch to a merged commit. A
gate is one numbered step. The list is short, so a lane (one agent doing one
task on its own branch) can recite it. An orchestrator (the agent coordinating
the lanes) can ask "which gate are you at?" and get a number back.

The gates are written in the law file (the Golden Workflow section of
[`templates/CLAUDE.md`](../templates/CLAUDE.md)). This chapter explains why
each one exists, then shows the commands for one change on GitHub.

## The ten gates

### 1. Branch from fresh main, in a worktree of its own

If your team records branch claims, claim the branch first
([coordination and identity](05-coordination-and-identity.md#branch-claims)).
Fetch, branch from the current tip of `main`, and work in a worktree (a
separate working copy) that nothing else touches. Never reuse a merged branch.

**What goes wrong without it.** A lane pushes a review fix to a branch whose
pull request has already merged. The push succeeds and the checks go green, but
the fix never reaches `main`. A merged branch is finished; the next change
starts on a new one.

### 2. Implement one coherent batch, committing each reviewable slice

A batch is one idea, committed in slices a reviewer can read one at a time. The
test for "one batch" is the size rule below.

### 3. Keep the documents current, in the same change

A change to a key contract or a major architecture decision updates the
architecture document and adds a decision record. Adding, moving or retiring a
document updates the index. A change to how a subsystem behaves updates that
subject's knowledge file. A document left for a follow-up change is usually
never updated.

### 4. Add a release note, or declare there is none

Every change either adds a one-sentence note written for customers, or says
"no user-visible change" in the pull request body. The declaration matters as
much as the note: without it, a missing note could mean an internal change or a
lane that forgot.

Write each note as its own file in `RELEASE_NOTES.d/`, never as a line in a
shared list; [parallel lanes](03-parallel-lanes.md) explains why. The template
is
[`templates/RELEASE_NOTES.d/README.md`](../templates/RELEASE_NOTES.d/README.md).

### 5. Run the affected checks locally

Lint, tests, build and contract checks: the ones this change could plausibly
break, not the whole suite.

### 6. Merge main into the branch while you work, and rerun

`main` keeps moving while you work. Merging it in early and often turns one
painful reconciliation into several small ones, and it shows a conflict while
both authors still remember their code.

### 7. Open the pull request with the shared template

Every change uses the same template, explained below.

### 8. Run an adversarial review on the exact head commit

A second agent, ideally a different model or one from a different vendor,
reviews the change and tries to find what is wrong. A writer checking its own
work misses exactly what it was blind to, so no gate does more good than this
one.

Two details make it work. The review names the exact commit it read, because a
review of an older commit is not a review of this change. And it ends in a
verdict, not in remarks a lane can read generously: one line with nothing else
on it, `VERDICT <sha> CLEAN` or `VERDICT <sha> RED`. Use a deeper review for
authentication, security, migrations, durability or encrypted user content. The
brief for the reviewer is
[`templates/briefs/review.md`](../templates/briefs/review.md).

### 9. Fix every in-scope finding in the same change

Out-of-scope work becomes a ticket in the tracker with a link back, not a
comment saying "noted". A finding that changes what users experience goes to
the owner before the merge: whoever found it is rarely the right person to
decide it.

### 10. Arm auto-merge only after every gate has passed

Green checks make a change eligible to merge. You decide what merges. After
your yes, the conductor (or the orchestrator, if you run no conductor) arms
auto-merge: the host then merges the change by itself once its checks pass.
Lanes never merge. Arm it last, confirm that the host reports the change as
merged, and only then remove the worktree.

**What goes wrong without it.** An agent arms auto-merge as soon as the pull
request opens, out of habit, while the adversarial review is still running. The
checks finish first and the change lands two minutes before the findings
arrive, which then have to chase the merged code in a follow-up. While a review
is running, auto-merge stays off.

Never bypass a gate with an administrator override. That power exists to repair
a broken repository, not to save time, and each use turns the gates into
suggestions.

## One change, start to finish, with commands

This is one change on GitHub at a terminal. Start in your main checkout, called
`<repo>` here, and replace the other names in angle brackets.

```bash
# Gate 1: claim the branch (skip this line if you use no head office), fetch,
# then branch from the current tip of main in a new worktree.
hq claim <branch>
git fetch origin
git worktree add ../<name> -b <branch> origin/main
cd ../<name>

# Gate 2: commit each reviewable slice. Check where you are first, every time.
git branch --show-current
git status --short
git add <the files you changed>
git commit -m "Fix: keep the upload control visible before the first save"

# Gates 3 to 6: documents, release note, local checks, then merge main in.
git fetch origin
git merge origin/main

# Gate 7: push and open the pull request. pr-body.md is a copy of
# .github/PULL_REQUEST_TEMPLATE.md with every section filled in.
git push -u origin <branch>
gh pr create --title "<ID>: <what changed>" --body-file pr-body.md

# Gate 8: give the reviewer the exact head commit.
git rev-parse HEAD

# Gate 9: fix every in-scope finding here, then push again.

# Gate 10: after your yes, the conductor or the orchestrator arms auto-merge.
gh pr merge <N> --auto --squash

# After the host reports the merge: back to the main checkout, then remove the
# worktree and the branch. After a squash merge git does not see the branch as
# merged, so deleting it needs -D.
cd ../<repo>
git worktree remove ../<name>
git branch -D <branch>
```

You can also open the pull request on the GitHub website, which fills the body
from the template. Either way, replace every comment in it with real content.

## The pull request template, section by section

The template is
[`templates/PULL_REQUEST_TEMPLATE.md`](../templates/PULL_REQUEST_TEMPLATE.md);
copy it to `.github/PULL_REQUEST_TEMPLATE.md`. It has five sections.

**Summary.** One or two sentences: what changed and why. It becomes the body of
the squash commit. Write it for whoever reads the history in six months, not
for the reviewer who has the diff open today.

**Parent task.** A link to the task in the tracker, and which part of it this
pull request delivers.

**Acceptance guide.** This decides whether someone who did not write the change
can act on it. It answers four questions:

- What changed, in product words a non-engineer can follow?
- Which features might be affected (the blast radius)? Derive it by tracing the
  callers and importers of the changed code, and add a line saying how.
- How do you check it? Give click paths with expected results.
- What could have broken, including what you could not verify?

The "how it was derived" line matters: a blast radius guessed from memory and
one traced through the code look the same on the page.

**Checklist.** Short, and every item is something that has gone wrong before:
branched from fresh `main`; house style respected; checks green locally, with
any known flaky test named; tests at the lowest tier that proves the behavior;
for a schema change, exactly one migration that works with the deployed code;
no secrets; adversarial review on this head commit; documents in sync; a
release note, or "no user-visible change".

**Notes.** Trade-offs, follow-ups and manual test steps.

## Too hard to review in one sitting means two pull requests

This is the only rule about size, and it is a judgement, not a line or file
count. Can one reviewer hold the whole change in their head in one pass? If
not, split it. Splitting is work you would do anyway, moved earlier, to where
it is cheap.

An oversized change also defeats gate 8. A reviewer facing forty files reads
ten carefully and skims the rest, and nobody learns which ten.

## Adopt it in a day

1. Copy [`templates/PULL_REQUEST_TEMPLATE.md`](../templates/PULL_REQUEST_TEMPLATE.md)
   to `.github/PULL_REQUEST_TEMPLATE.md` (`/murmur:init` does this), and delete
   any section you will not fill in properly.
2. Put the ten gates in your law file as a plain numbered list.
3. If you adopt only one gate, adopt gate 8.
4. Stop arming auto-merge when the pull request opens. Arm it last, after the
   review verdict and your yes.
5. Write the acceptance guide for your last merged change, after the fact. If
   you cannot say how you derived its blast radius, close that gap first.
