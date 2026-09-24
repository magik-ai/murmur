<!--
Template: the brief an orchestrator hands to ONE worker driving ONE lane (one
agent doing one task on its own branch). Keep it short. A brief is not
documentation: it is the task, the acceptance criteria, and the territory. The
worker reads everything else from the repository law file.

DO NOT REPEAT WHAT THE SPAWNER ALREADY ADDS. A spawner usually adds the
workflow steps, the worktree and branch rules, port and database isolation,
the commit identity, the branch claim and the unread mail (murmur's
`fleet spawn` does). Repeating them makes the brief long. A long brief gets
skimmed, and that is how the ONE instruction specific to this lane gets
missed. Check once what your spawner adds, write it down, and never repeat it.
Put a long brief in a file on the worker's machine and pass it by path (with
fleet: `fleet spawn --brief-file <path>`).
-->

# Lane: `<lane-name>`

**Tracker id:** `<ID>` (put it in the branch name and the pull request title)
**Model:** `<tier>`
**Spawned by:** `<orchestrator code name>`

## The task

Two to five sentences. What to build or fix, and why it matters, in the
product terms a reader needs to judge whether the result is right. Name the
entry point you already found, so the worker does not spend its first hour
finding it again.

For a bug fix, give the steps to reproduce it and the behavior you saw, not
your diagnosis. A worker handed a diagnosis stops looking, and an
orchestrator's diagnosis is wrong often enough to matter.

## Acceptance criteria

The list a reviewer will check. Each item is concrete, observable, and
testable by someone who did not write the code.

- [ ] `<observable behavior, stated as what a user or a caller sees>`
- [ ] `<the regression test that fails without the fix>`
- [ ] `<the check that must be green>`
- [ ] `<the document or note updated in the same pull request>`

Out of scope, explicitly: `<the neighbouring work you must NOT do>`. If you
find something out of scope, file it. Do not fix it.

## Path manifest (your territory)

You own exactly these paths. No other live lane owns any of them.

Staying inside them is the **manifest guard**. On a farm, lanes started as a
group (`fleet group start`) get a pre-push hook that refuses a push with files
outside the lane's paths. Elsewhere the guard is a convention: before
assembling anything, the orchestrator compares your branch with this list, and
you will be asked to explain any path you do not own. Either way, compare your
changed paths with the list before you push.

```text
<path/or/glob>
<path/or/glob>
```

- **Never edit outside the manifest.** Not "just one line", not a rename that
  spills over, not an import fix in a neighbour's file.
- If the task really cannot be done inside the manifest, **stop and report
  it**. A wrong territory is the orchestrator's mistake to fix, not yours to
  work around. Working around it silently collides with a lane you cannot see.
- Shared files that every lane wants (the place where the app is wired
  together, generated files, registries, lists that only grow) are handed out
  by the orchestrator, one lane at a time. If you need one, ask.
- Numbers that must be unique (migrations, decision records) are reserved for
  you at the start: `<the reserved numbers, or "ask before creating one">`.

## Working rules for this lane

- **Use the worktree you were given.** Do not create another one, do not
  switch branches inside it, and do not work in the main checkout. The
  worktree has its own environment. Environments here are tied to their path:
  a copied or shared one silently imports a neighbour's code, and gives results
  that do not reproduce.
- Commit each reviewable slice, and push. The orchestrator and the reviewers
  see only what you pushed, and the worktree of a finished lane is removed.
- `<Say whether this lane opens its own pull request, or stops after pushing
  because the orchestrator assembles several lanes into one. Grouped lanes do
  NOT open pull requests.>`

## Finish

**Post your final report as your last action, then stop.** The report is the
only thing the orchestrator reads, so it must stand alone:

1. What you did, in two or three sentences, in product terms.
2. Every acceptance criterion, each marked met or not met.
3. The branch name, and the pull request link if you opened one.
4. Anything you changed beyond the obvious: any file a reviewer would be
   surprised to see in the diff, and why it is there.
5. What you could not verify, and what you would check next. Say this
   plainly: "I could not run the end-to-end suite here" is worth more than a
   confident claim that will be checked and found false.
6. Anything you found and did not fix, so it can be filed.

Never claim a check passed without running it. The orchestrator checks
important claims against the real result, and a claim that fails that check
costs more trust than the bug did.
