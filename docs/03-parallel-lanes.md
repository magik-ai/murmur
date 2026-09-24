# Parallel lanes

A lane is one agent doing one task on its own branch, in its own worktree (a
separate working copy of the repository). This chapter is about running several
lanes at once in one repository without losing work. The orchestrator is the
agent that coordinates them.

## The failure this chapter prevents

The worst failure in parallel work is two lanes editing the same file. In its
worst form there is no conflict at all: the merge is clean, the checks are
green, and one lane's work is quietly gone. Careful reading does not catch it,
so the rules below make it impossible, instead of relying on care.

## A lane owns paths, not a topic

Before a lane starts, write down the paths it may touch. That list is its
manifest, and it goes in the lane's brief
([`templates/briefs/lane.md`](../templates/briefs/lane.md)).

Keep every manifest in one lane list that the orchestrator owns: a file such as
`docs/process/TEAM_LANES.md` (the name the law file template uses). On a farm,
the group spec that `fleet group start` reads can serve as that list. Copies
kept per lane drift; one list does not. To decide whether a path is free, read
the list, not a lane's memory of it.

A lane whose paths overlap a live lane is refused, not warned about. If your
tooling offers an override, treat using it as an incident. On a farm (an
always-on machine that runs agents with murmur's `fleet` tool),
`fleet group start` refuses a group of lanes with overlapping paths before any
agent starts.

**A path outside the manifest is a blocker, not an invitation.** A lane that
needs a file it does not own stops and reports. Before opening the pull
request, it compares every changed path with its manifest and explains any
extra one.

## Spine files get one lane at a time

Some files every lane wants to touch: the place where the application is wired
together, generated interfaces (a schema, a client, an inventory), shared
registries and lists that only grow. They are the spine of the repository.
Never work on them in parallel. One lane holds each, in an order the
orchestrator sets.

**What goes wrong without it.** Two lanes each add a block to one large shared
file. The blocks look alike, so git combines them with no conflict marker, and
the build passes. One lane's block is simply missing, and nobody notices until
a "merged" feature turns out not to exist. Review does not make a spine file
safe. One lane at a time does.

## Never hand-resolve a generated file

A generated file is an output. Merging two outputs line by line produces a
third that no generator would write.

**What goes wrong without it.** A lane resolves a conflict in a generated
inventory by hand. The numbers look plausible and pass review. From then on,
every merge of `main` conflicts in that file again, and the pull request cannot
merge for days, because its counters describe an old base.

The fix is mechanical: take the version from `main`, rerun the generator on
your branch, and commit what it produces. To stop it happening again:

- Mark generated paths in `.gitattributes` (for example with `-merge`), so git
  does not attempt a line-by-line merge.
- Add a guard that refuses a direct edit and prints the command that
  regenerates the file. The murmur plugin's guard reads
  `.claude/generated-files.txt`; see [safety hooks](11-safety-hooks.md).
- If the generator writes counters for the whole repository, make it write one
  row per domain, so unrelated work touches unrelated lines.

## Reserve numbers across every open pull request

Anything numbered in sequence, such as decision records and migrations,
collides when lanes run in parallel. Checking `main` is not enough: the number
another lane took an hour ago sits in an open pull request, invisible to your
tree. So each lane reserves its numbers at the start of its batch with
[`templates/scripts/next_number.sh`](../templates/scripts/next_number.sh),
which scans `main` and every open pull request by default:

```bash
scripts/next_number.sh              # every kind: main plus open pull requests
scripts/next_number.sh adr          # one kind only
scripts/next_number.sh --main-only  # skip the pull request scan
```

Run `git fetch origin` first, so the `main` you scan is current. The pull
request scan needs `gh`, signed in. If `gh` is missing or cannot list pull
requests, the script scans `main` only and prints a note saying so. Use
`--main-only` only when you are offline, and expect to renumber.

**What goes wrong without it.** A lane renumbers a migration to dodge a
collision: a rename plus an edit inside the file. The rename is staged with the
old contents while the edit stays unstaged, so the commit has the new file name
with the old identifier inside. Local checks pass, because they read the
working tree. CI fails, because it reads the commit. After a rename plus an
edit, check the commit (`git show HEAD:<path>`), not the tree.

## One file per change, never a shared list

Wherever lanes must record something (release notes, an inventory, known
issues), give each change its own file in a directory instead of a line in a
shared document. The cost is a directory a script assembles later. The benefit
is that the most-touched file in the repository stops producing conflicts.
Split an append-only file before parallel work starts, not after the first
collision. The release notes template,
[`templates/RELEASE_NOTES.d/README.md`](../templates/RELEASE_NOTES.d/README.md),
shows the pattern.

## Grouped lanes assemble into one pull request

When several lanes build one feature, they do not merge separately. Each lane
pushes its own branch and opens no pull request. The orchestrator merges the
lane branches into one integration branch and opens a single pull request.

A conflict during assembly is the collision detector doing its job: two lanes
touched the same ground, and you want to know before the work reaches `main`.
Never let an automatic resolver settle it. Take it back to the two lanes,
decide which change is correct, and have one of them redo its part.

On a farm, `fleet group assemble <name>` does the assembly. It stops at the
first conflict, names the files and lanes, and never resolves anything itself.
Run it with `--dry-run` first to see the merge order and each lane's files.

## A clean merge can still lose work

When two parents touched one file, compare the merge result with **both**
parents and confirm that each named change survived. Do it before you trust a
green check: the checks ran on what the merge produced, and cannot know what it
should have contained.

```bash
git diff HEAD^1 HEAD -- <file>   # what came in from the other branch
git diff HEAD^2 HEAD -- <file>   # what your own branch contributes
```

Confirm by identifier (this function, this key, this row). A line count tells
you nothing.

## Environment traps

These cost lanes whole days, and none of them looks like an environment problem
at first.

- **One environment per worktree.** An editable install (`pip install -e .`)
  points at one worktree's files. With a shared environment, a test can import
  a different checkout from the one under test.
- **An activated environment beats the working directory.** If your shell
  profile activates a virtual environment (it exports `VIRTUAL_ENV`), installs
  can go there, whichever worktree you are in. Unset it and pass an explicit
  interpreter path.
- **Never run another worktree's scripts.** A script's first line (the `#!`
  line) can name that worktree's Python.
- **Fixed dates in fixtures are time bombs.** A test pinned to one day passes
  until the calendar moves past it, and then every branch goes red at once on
  unrelated code. When many lanes fail together, suspect the calendar first.
- **Trust the fresh database in CI over your local one.** A local database
  drifts from the migration history. When database tests fail locally but pass
  in CI, believe CI instead of spending a day repairing one machine.

## Adopt it in a day

1. Write a path manifest for every lane running now, in one file the
   orchestrator owns.
2. List your spine files by name and mark them one-lane-at-a-time in the law
   file (the worktrees section of
   [`templates/CLAUDE.md`](../templates/CLAUDE.md)).
3. Convert your most conflict-prone shared list into one file per change.
4. Copy [`templates/scripts/next_number.sh`](../templates/scripts/next_number.sh),
   point its `KINDS` list at your own numbered paths, and run it at the start
   of every batch.
5. The next time two lanes touch one file, compare the merge with both parents,
   by identifier, before you look at the checks.
