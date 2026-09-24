# CI and merge

CI (continuous integration) is the set of automated checks that runs on every
change. This chapter covers what those checks prove, and how to merge many
changes a day without breaking `main`. The short version: before a change
lands, test `main` plus the change, not only the change on its own branch.

## What a green branch proves

A branch that passes its own checks proves that the change works on the base it
was written against. It does not prove the change works next to the four others
landing today.

Two branches can be green apart and red together. One adds a database migration
and another adds a second; together they leave two competing migration
histories. One renames a shared function; the other adds a caller of the old
name. Neither branch is wrong. The combination is, and that is why a merge
queue exists.

## The merge queue tests the combination

A merge queue takes `main`, adds a candidate change on top, and checks the
result. The change lands only if the combination passes. Candidates go one at
a time or in small batches, so what was tested is what will exist on `main`.

GitHub's merge queue is a setting in the branch protection for `main`. The
workflows it runs need the `merge_group` event as a trigger.

The queue does not need the full suite. Run only what can differ on the
combined tree: does the application still start, is there still one migration
head, do generated files still match their sources, does it all still
typecheck. These checks are cheap, and each one catches changes that are green
apart and red together. The expensive proof belongs on the branch, before the
change enters the queue.

## The turnstile

If the queue skips the full suite, something must guarantee that the branch
already ran it. That is the turnstile: a check in front of the queue that
refuses any change whose own branch run is not green **on that exact head
commit**.

Green on an earlier commit of the branch is not green. A change whose
auto-merge was armed before its checks finished is stopped at the turnstile. It
does not take a queue slot and then fail on a defect its own run had already
found.

**What goes wrong without it.** A change enters the queue half a minute before
its own branch run fails. The queue accepts it, because at that moment nothing
has said no. The full set of checks then runs twice to find the same defect.

murmur does not ship a turnstile. It is a small workflow job you write: a
required check that runs in the queue and fails unless the pull request's own
checks passed on its current head commit.

## A review verdict belongs to one commit

The same rule applies to review. An adversarial review ends in a one-line
verdict that names the commit it read: `VERDICT <sha> CLEAN` or
`VERDICT <sha> RED`. Before you merge, compare that hash with the head of the
pull request:

```bash
gh pr view <N> --json headRefOid --jq .headRefOid
```

If the branch has moved since the review, the verdict is about a different
change: review the new head. The review gate is in
[the golden workflow](02-golden-workflow.md), and the reviewer's brief is
[`templates/briefs/review.md`](../templates/briefs/review.md).

## The hold label is the veto

One label blocks a change's merge absolutely: no override, no exception, no
"but everything is green". Anyone may add the `hold` label. Only the owner
removes it.

Green and ready are different states. A change can pass every check and still
be wrong to land now. Perhaps the owner has not seen the visual result, a
decision is pending, production is in the middle of an incident, or something
else must go first. The veto lets a person say stop without arguing with
automation. Keep it simple: a veto with conditions is one that people argue
their way around.

GitHub does not block a merge because of a label, so make the veto real with a
small required check that fails while the `hold` label is present.

## Your own CI machines: faster, never the authority

Hosted runners queue up, and waiting a quarter of an hour per change is a real
cost. Running checks on machines you own is a fair answer. murmur does not
include such a runner; this section is for teams that build one. If you do,
test the combination as the queue does, `main` plus one candidate at a time,
and follow three rules.

**It publishes no statuses.** The hosted checks stay the authority that branch
protection reads. A local green decides nothing and never justifies bypassing a
gate.

**A result goes stale when the base moves.** A local result was computed
against a `main` that has since moved on. A stale green is not green.

**When the two disagree, the hosted result wins**, and the disagreement is an
incident, not noise: one of the two systems is misconfigured, and you want to
know which.

Making your own machines a delivery path is a separate decision. It needs
published statuses, and then exactly one system writing each check name.

## A merge is a deployment

When a project ships from `main`, a merge reaches production within minutes.
Two rules follow.

**Merge only complete, releasable states.** Whatever lands is what customers
get.

**Green checks are not health.** Checks prove only what somebody thought to
write down. During a wave of merges, watch production directly. More than one
real incident has appeared while every check was green.

And one consequence: because the queue runs only the cheap checks, the full
suite on `main` runs after the merge. `main` can be red for a while, and the
bad commit may already be live. So something must watch. A job that opens an
issue as soon as a run on `main` fails is enough. Silence is not a signal.

## Renaming a required check

GitHub identifies a required check by its name. Rename the job, and the
protection rule keeps waiting for a name that will never report again. Then
either nothing merges, or someone deletes the requirement to unblock it and the
gate quietly stops applying.

Rename the job and update the protection rule together. Look at the live
protection settings before you change them, rather than trusting a snippet in a
document: only the live settings are certain to be current.

## When main goes red

The repair is mechanical, not investigative, and it moves forward. Never
rewrite history, never force-push a shared branch, and never switch off the
deploy checks to make the red go away.

1. **Confirm it is real.** Read the failing job. A dead runner, a registry
   timeout or a known flaky browser test calls for a rerun, not an incident.
   But never rerun away a failure that repeats every time: name what broke
   first.
2. **Revert the bad change immediately**, as a new commit on top. Every change
   behind it rides on a red base until the revert lands.
3. **Assume the bad commit is live** until you know otherwise, and confirm that
   production is back on the repaired `main`.
4. **Diagnose afterwards, on a branch**, and land the fix again with the
   regression test that fails without it.

Reverting and relanding moves forward. Rewriting the history everyone builds on
turns one broken commit into a broken repository.

## Adopt it in a day

1. Create one veto label with no exceptions and write it into your law file:
   anyone may add it, only the owner removes it. Add the required check that
   enforces it.
2. Set an alarm for a failed run on `main`, with the four repair steps above
   next to it.
3. If your host offers a merge queue, turn it on, so the combination is tested
   and not only the branch.
4. Once the queue runs, add the turnstile. It can wait until the queue has
   accepted something it should not have.

The matching rules are in the core contract and the CI section of
[`templates/CLAUDE.md`](../templates/CLAUDE.md). The plugin's `conductor` skill
is the procedure for the agent that runs the queue.
