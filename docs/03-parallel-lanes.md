# Parallel lanes

## The one failure everything here prevents

Two lanes editing the same file is the failure that costs a rebuild. In its
worst form it produces no conflict at all: the merge is clean, the checks are
green, and one lane's work is quietly gone. Every rule in this chapter follows
from that fact, because careful reading does not catch it.

## Manifests: a lane owns paths, not a topic

Before a lane starts, write down the paths it may touch. That list is its
manifest, and it belongs in the brief.

Keep the manifests in one registry the orchestrator owns. Per-lane copies
drift; the registry does not. Read it, not a lane's recollection, when deciding
whether a path is free.

Allocating a lane that overlaps a live lane is a refusal, not a warning. If the
harness offers an override, treat using it as an incident.

**A path outside the manifest is a blocker, not an invitation.** A lane that
needs a file it does not own stops and reports. It does not "fix it while
here". Before opening the pull request, it diffs every changed path against the
manifest, and an extra path is something to explain.

## Spine files are hand-sequenced

Some files every lane wants to touch. They are the spine of the repository, and
they are never worked in parallel: composition roots where everything is wired
together, generated surfaces (a schema, a client, an inventory), shared
registries, and append-only inventories. One lane at a time in each, in an
order the orchestrator sets.

**The incident behind it.** Two lanes each appended a block to one large shared
file. The blocks were similar in shape, so the merge spliced them cleanly with
no conflict marker, the build passed, and one lane's block was simply not
there. Nobody noticed until a feature that had been "merged" turned out not to
exist. A spine file is made safe by one lane holding it at a time, not by
careful review.

## Never hand-resolve a generated file

A generated file is an output. Merging two outputs line by line produces a
third that no generator would emit.

**The incident behind it.** A lane resolved a conflict in a generated inventory
by hand. The numbers looked plausible, so the change passed review. Every later
merge of `main` conflicted in the same file again, and the pull request sat
unmergeable for days while its counters encoded a stale base.

The fix is mechanical. Take the version from `main`, rerun the generator on
your branch, and commit what it produces. Mark generated paths so the tooling
stops offering a line-level merge, and add a guard that refuses a direct edit
and prints the generate command instead. Fix the generator too if it emits
repository-wide counters: per-domain rows mean unrelated work touches unrelated
lines.

## Reserve numbers across every open pull request

Anything numbered sequentially (decision records, schema migrations) collides
when lanes run in parallel. Reserving a number by looking at `main` is not enough. The number another lane
claimed an hour ago sits in an open pull request, invisible to your tree. The
reservation script scans `main` and every open pull request, and each lane
reserves at batch start.

**The incident behind it.** A lane renumbered a migration to dodge a collision,
which is a rename plus an edit inside the file. The rename was staged carrying
the original contents while the edit stayed in the working tree, so the commit
shipped the new filename with the old identifier. Every local check passed,
because local tools read the tree, and every job went red once it ran from the
commit. After a rename plus an edit, verify from the commit, not the tree.

## One file per change, never a shared list

Anywhere lanes must record something (release notes, an inventory, a list of
known issues), give each change its own file in a directory instead of a line
in one shared document.

The cost is a directory a script assembles later. The benefit is that the
most-touched path in the repository stops producing conflicts entirely. Split
an append-only file before parallel work starts, not after the first
collision.

## Grouped lanes assemble into one pull request

When several lanes build one coherent feature, they do not merge separately.
They assemble onto one integration branch, and that branch opens a single pull
request.

A conflict at assembly is the collision detector doing its job. Two lanes
touched the same ground, and you want that before the work reaches `main`.

Never let an automated resolver settle such a conflict. Take it back to the two
lanes, decide which change is correct, and have one redo its part.

## A clean merge can still lose work

When two parents touched one file, diff the merge result against **both**
parents and confirm each named change survived. Do this before believing a
green check: the checks ran on what the merge produced, and cannot know what it
should have contained. Confirm by identifier (this function, this key, this
row), because a line count tells you nothing.

## Environment traps

These cost lanes whole days, and none of them looks like an environment problem
at first.

- **One environment per worktree.** Installs that point at a source directory
  are pinned to a path, so a shared environment makes a test import a different
  checkout than the one under test.
- **An activated environment outranks the working directory.** A variable
  exported in a shell profile wins over where you are standing, so an install
  run inside one worktree can land in another's environment. Unset it and pass
  an explicit interpreter path.
- **Never run another worktree's scripts.** Their first line pins that
  checkout.
- **Absolute dates in fixtures are time bombs.** A test pinned to a specific
  day passes until the calendar walks past it, and then every branch goes red
  at once on unrelated code. When many lanes fail together, suspect the
  calendar before the code.
- **Trust the fresh database in CI over the local one.** A local database
  drifts from the migration history. When database-backed tests fail locally
  and pass in CI, believe CI rather than spending a day repairing one
  machine.

## Adopt it in a day

1. Write a path manifest for every lane running now, in one file the
   orchestrator owns.
2. List your spine files by name, and mark them one-lane-at-a-time in the law
   file (see [`templates/CLAUDE.md`](../templates/CLAUDE.md), worktrees).
3. Convert your most conflict-prone shared list into one file per change.
4. Make number reservation scan open pull requests, not just `main`.
5. Next time two lanes touch one file, diff the merge against both parents by
   identifier before looking at the checks.
