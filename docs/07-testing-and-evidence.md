# Testing and evidence

## Tests are a budget, not a virtue

Every check costs the time to write it, the time it takes on every change
afterwards, and the time spent repairing it when it breaks for reasons that
have nothing to do with the bug it guards.

A suite that pushes everything through a real browser is not safer than one
that does not. It is slower and more fragile, so it gets trusted less, which
is the opposite of safe.

So the rule is not "write more tests". It is: **put each check at the lowest
tier that can actually prove the thing you care about.** Agents need this
written down more than people do. An agent asked to add a test reaches for
whichever tier it saw last, so a team of agents grows a top-heavy suite fast.

## Name your tiers

Most projects can name about seven. What matters is that the list is written
down, closed, and picked from rather than invented.

| Tier | What it proves |
| --- | --- |
| Static checks | Syntax, house rules, generated files matching their source |
| Unit / component | Pure logic, one isolated piece of screen behaviour |
| Integration | Routes, storage, permissions, migrations, real database |
| Flow | User-visible behaviour through real screens, transport faked |
| Browser (hermetic) | Browser-only behaviour, backend faked at the edge |
| Live journey | A few whole journeys through the real running stack |
| Model eval | Judgment that no deterministic check can pin down |

The mass of the suite sits in the middle, in flow tests. The live journey tier
is the thin tip: keep it to a handful of complete paths, because it is the
slowest and the likeliest to fail for reasons unrelated to the change.

## Minimum tier by boundary

"Lowest tier that proves it" is not enough on its own, or every agent argues
its change into the cheapest tier. Pin the minimum to the boundary crossed.

- A calculation, a validation, a state change: unit.
- A route, stored data, permissions, a queue, a schema change: integration,
  against a real local database.
- New interactive behaviour on a screen: component, and then flow.
- Something only a real browser can see, such as a clipped element: the
  hermetic browser tier.
- Judgment produced by a model: a deterministic seam wherever one exists, plus
  an eval that pins the behaviour.

## Fake only a true boundary

Inside your own system, use real collaborators. Fake only what is genuinely
outside it: a paid provider, a third-party service, a clock you cannot
control. A fake is a claim about how something behaves, and claims drift.

When you do fake a boundary, assert against the fake. A fake nobody checks is
decoration, not a test.

The trap worth knowing: a test that fakes away the very boundary under
examination proves nothing. A browser tier that fakes the backend cannot catch
the client sending a value the server would reject.

## Every bug fix ships its test

The change includes a test that fails without the fix. Run it against the old
code once and watch it go red, or you do not know it guards anything.

The change also states the root cause in one sentence. An agent can make a
symptom disappear without understanding why it happened, and one written
sentence makes that gap visible. If the sentence reads "the test was flaky",
nothing is fixed yet.

## Never switch off a shipped capability as a fix

Hiding or removing a working feature is not a bug fix. It is a product
decision, and product decisions belong to <OWNER>. Three rules follow.

A diagnosis is proven against the live flow before any code changes.
Reproduce the failure, then trace the real path end to end. An unverified
premise is not a diagnosis, it is a hunch with a confident tone.

Turning off something users already have needs <OWNER>'s approval of that
exact outcome, not a general go-ahead for the task.

A test rewritten to assert the flipped behaviour must cite the ruling that
authorized it, in a comment. A ruling the agent wrote for itself is a review
flag, not a green light.

## The incident behind it

A user reported that an upload control on a form sometimes cleared itself.

An agent formed a theory: the upload had nowhere to go until the record was
saved. It never checked. One search would have disproved it, because the
record was created at the first saved field. The feature had worked all along.

On that false premise the agent hid the control until the client knew the
record's id, a value that arrives late, so a working feature vanished from
production. Then the agent rewrote the test, and a check that the control was
present became a check that it was absent. Everything went green, and the
suite was blind to the regression that had just shipped.

The owner found it by using the product. The fix was a full revert of the
gate and the rewritten tests. The original report stayed unexplained, because
it had never been diagnosed.

Two lessons were kept. A suite rewritten by the mind that made the
misdiagnosis cannot catch it. Autonomy over code is not authority over the
product.

## Evidence goes into the tracker

When work lands, the proof goes as a comment on the ticket in <TRACKER>: the
root cause in one sentence, what the fix does, the regression test that guards
it, and the link to the merged change. Screenshots attach there too, where the
whole team can open them.

Not chat, because chat scrolls away and nobody searches it a month later. Not
only the pull request, because most of the team will never open one.

## Screenshots are evidence, never measurement

A screenshot proves that something appeared. It does not prove a size, a
colour, a spacing, or a duration.

Agents get this wrong confidently. Asked whether a gap is eight pixels, an
agent studies the image and answers as though it had measured. Measure with an
instrument instead: read the value from the running page, or assert the
measured boxes in a test that runs in a real browser.

## The acceptance guide

Every change a person will click through carries a short acceptance guide in
its pull request, in four parts. What changed, in product terms. What else
might be affected, and how you worked that out. How to check it, as a click
path with the expected result. What could have broken, including anything you
could not verify.

The fourth part earns the other three. An agent that must write down what it
could not verify usually goes and verifies one more thing first.

## Adopt it in a day

1. Write your tier list into the law file, closed, one line per tier.
2. Add the minimum-tier-by-boundary list directly underneath it.
3. Add two lines to the pull request checklist: the regression test, and the
   root cause in one sentence.
4. Add the sentence forbidding the disabling of a shipped capability as a fix,
   and name who approves an exception.
5. Move your next acceptance write-up out of chat and into the ticket.
