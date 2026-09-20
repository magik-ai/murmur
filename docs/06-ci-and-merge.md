# CI and merge

## What a green branch actually proves

A branch that passes its own checks proves one thing: that change works on the
base it was written against. It does not prove the change works next to the
four others about to land today.

Two branches can be green apart and red together. One adds a database
migration, the other adds a second, and only together do they leave two
conflicting histories. One renames a shared function, the other adds a caller
of the old name. Neither branch is wrong. The combination is. That is the
whole reason a merge queue exists.

## The queue builds the combination

A merge queue takes the main branch, adds one candidate on top, builds that
speculative result, and checks it. The change lands only if the combination is
good. Candidates go one at a time, or in small batches, so the combination
tested is the combination that will exist.

The queue therefore does not rerun the full suite. It runs exactly what can
differ on the combined tree: does the application still start, is there still
one migration head, do generated files still match their sources, does it all
still typecheck. Those checks are cheap, and every one of them has been seen
green on two branches apart and red together.

The expensive proof lives where it belongs, on the branch itself.

## The turnstile

If the queue does not run the full suite, something must guarantee the branch
already did. That is the turnstile: a guard in front of the queue refusing any
entry whose own branch run is not green **on that exact head**.

The words "exact head" are load-bearing. Green on an earlier commit of the
branch is not green. A change whose auto-merge was armed before its checks
finished is rejected at the turnstile instead of taking a full queue slot and
failing on a defect its own run had already found.

**The incident behind it:** a change entered a merge queue half a minute
before its own branch run concluded as a failure. The queue accepted it,
because at that moment nothing had said no. The full matrix then ran twice to
find the same defect.

## The hold label is the veto

One label on a change blocks its merge absolutely. No override, no exception,
no "but everything is green". Anyone may add the hold label. Only the owner
removes it.

It exists because green and ready are different states. A change can pass
every check and still be wrong to land now: the owner has not seen the visual
result, a decision is pending, production is mid-incident, or something else
must go first. The veto is how a person says stop without arguing with a
robot. Keep it dumb on purpose: a veto with conditions is one people reason
around.

## A self-hosted CI farm is an accelerator, never an authority

Hosted runners queue up, and waiting a quarter of an hour per change is a real
cost. Running the same tiers on your own machines (<FARM>) is a fair answer.
The part worth reproducing is the speculative combination: one candidate at a
time on the current main branch, because branch-green plus branch-green is
still not combination-green.

Three rules hold the boundary around it.

**It publishes no statuses.** The hosted system stays the authority branch
protection reads. A local green resolves nothing and never justifies bypassing
a gate.

**A verdict goes stale when the base moves.** A local result was computed
against a main branch that has since advanced. A stale green is not a green.

**On disagreement, the hosted verdict wins**, and the divergence is an
incident, not noise. Two systems answering differently about one commit means
one is misconfigured, and you want to know which.

Turning a local farm into a delivery path is a separate, deliberate decision.
It needs published statuses, and then exactly one writer per check name, never
two systems reporting one context in parallel.

## A merge is a deployment

On a project that ships from its main branch, a merge reaches production in
minutes. Two rules follow.

**Merge only complete, releasable states.** Whatever lands is what customers
get.

**Green checks are not health.** Checks prove the invariants somebody thought
to write down. During a wave of merges, watch production directly. More than
one real incident has surfaced while every check was green.

There is an uncomfortable corollary. With the full suite running after the
merge rather than before it, the main branch can be red for a window, and the
bad commit may already be live. So something must watch. A machine that files
an issue the moment a main-branch run goes red is enough. Silence is not a
signal.

## Renaming a required check

A required check is identified by its name. Rename the job and the protection
rule waits for a name that will never report, so either nothing merges or,
worse, the gate quietly stops applying.

Rename the job and update the protection rule in one operation. Inspect the
live protection state before changing it rather than trusting a snippet from a
document: the live state is the only version certain to be current.

## When the main branch goes red

The repair is mechanical, not investigative, and it goes forward. Never
rewrite history, never force-push a shared branch, never disable the deploy
gate to make the red go away.

1. **Confirm it is real.** Read the failing job. A dead runner, a registry
   timeout, or a known-flaky browser test is a rerun, not an incident. Do not
   rerun away a deterministic failure either: name the failing invariant first.
2. **Revert the bad change immediately**, as a new commit on top. Every change
   behind you rides a red base until it lands.
3. **Assume the bad commit is live** until proven otherwise, and confirm
   production has converged back onto the restored head.
4. **Diagnose afterwards, on a branch**, and reland with the regression test
   that fails without the fix.

Reverting and relanding moves forward. Rewriting the history everyone else is
building on does not, and it turns one broken commit into a broken
repository.

## Adopt it in a day

1. Create one veto label with no exceptions and write it into your law file.
   Anyone may add it, only the owner removes it.
2. Set an alarm for a red run on your main branch, with the four repair steps
   above next to it.
3. If your host offers a merge queue, turn it on, so what is tested is the
   combination and not the branch.
4. If you run a merge queue, add the check that refuses an entry not green on
   its exact head. It is a small workflow job, and it can wait until the queue
   has actually accepted something it should not have.
