<!--
Template: the brief an orchestrator hands to ONE worker driving ONE lane.
Keep it short. A brief is not documentation: it is the task, the acceptance
criteria, and the territory. Everything else the worker needs, it reads from the
repository law file itself.

DO NOT REPEAT WHAT THE HARNESS ALREADY INJECTS. A spawner usually prepends the
workflow gates, the worktree and branch rules, port and database isolation, the
commit identity, the branch claim and the unread mail. Repeating them makes the
brief long, and a long brief gets skimmed, which is how the ONE instruction that
was actually specific to this lane gets missed. Check what your spawner injects
once, write it down, and never duplicate it again.
A brief too long for a command line argument goes into a file on the worker's
machine and is passed by path.
-->

# Lane: `<lane-name>`

**Tracker id:** `<ID>` (put it in the branch name and the pull request title)
**Model:** `<tier>`
**Spawned by:** `<orchestrator code name>`

## The task

Two to five sentences. What to build or fix, and why it matters, in the product
terms a reader needs to judge whether the result is right. Name the entry point
you already found, so the worker does not spend its first hour re-finding it.

If this is a bug fix, state the reproduction and the observed behavior, not your
diagnosis. A worker handed a diagnosis stops looking, and diagnoses handed down
from an orchestrator are wrong often enough to matter.

## Acceptance criteria

The list a reviewer will check. Concrete, observable, and each one testable by
someone who did not write the code.

- [ ] `<observable behavior, stated as what a user or a caller sees>`
- [ ] `<the regression test that fails without the fix>`
- [ ] `<the check that must be green>`
- [ ] `<the document or note updated in the same pull request>`

Out of scope, explicitly: `<the neighbouring work you must NOT do>`. Finding
something out of scope means filing it, not fixing it.

## Path manifest (your territory)

You own exactly these paths. They are disjoint from every other live lane.

Staying inside them is the **manifest guard**. In version one that guard is a
convention rather than a hook: the orchestrator diffs your branch against this
list before assembling anything, so a path you do not own is something you will
be asked to explain. Diff your own changed paths against the list before you
open the pull request.

```
<path/or/glob>
<path/or/glob>
```

- **Never edit outside the manifest.** Not "just one line", not a rename that
  leaks, not an import fix in a neighbour's file.
- If the task genuinely cannot be done inside the manifest, **stop and report
  it**. A territory that is wrong is the orchestrator's mistake to fix, not
  yours to work around, and working around it silently collides with a lane you
  cannot see.
- Shared files everyone wants (composition roots, generated surfaces,
  registries, append-only inventories) are sequenced by the orchestrator, one
  lane at a time. If you need one, ask.
- Numbers that must be unique (migrations, decision records) are reserved for
  you at the start: `<the reserved numbers, or "ask before creating one">`.

## Working rules specific to this lane

- **Use the worktree you were given.** Do not create another one, do not switch
  branches inside it, do not work in the main checkout. The worktree has its own
  environment, and environments here are path-pinned: a copied or shared one
  silently imports a neighbour's code and produces results that do not
  reproduce.
- Commit each reviewable slice, and push. Only committed and pushed work
  survives; an untracked file in a worktree protects nothing.
- `<Whether this lane opens its own pull request, or stops after pushing because
  the orchestrator assembles several lanes into one. Say which. Grouped lanes do
  NOT open pull requests.>`

## Finish

**Post your verdict as your last action, then stop.** The verdict is the only
thing the orchestrator reads, so it must stand alone:

1. What you did, in two or three sentences, in product terms.
2. Every acceptance criterion, each marked met or not met.
3. The branch name and the pull request link, if you opened one.
4. What you changed outside the obvious: any file a reviewer would be surprised
   to see in the diff, and why it is there.
5. What you could not verify, and what you would check next. Say this plainly.
   An honest "I could not run the end-to-end suite here" is worth more than a
   confident claim that will be checked and found false.
6. Anything you found and did not fix, so it can be filed.

Never claim a check passed without running it. The orchestrator verifies
load-bearing claims against the artifact, and a claim that does not survive that
costs more trust than the bug did.
