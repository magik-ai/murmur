# Testing and evidence

This chapter answers three questions. Where should each test go? What must a
bug fix include? Where does the proof of finished work go?

The owner, below, is the person whose product it is. The law file is the file
in your repository that says how work happens ([chapter 01](01-repo-law.md)).

## Put each check at the lowest tier that proves it

More tests are not automatically better. Every check has a cost, and you pay
it again and again:

- the time to write it;
- the time it adds to every later change;
- the time to repair it when it breaks for reasons unrelated to the bug it
  guards.

A suite that runs everything through a real browser is not safer. It is
slower and breaks more often, so people trust it less.

So the rule is not "write more tests". The rule is: **put each check at the
lowest tier that can prove what you care about.** Agents need this written
down more than people do. An agent asked to add a test uses whichever tier it
saw last, so a team of agents quickly grows a suite that is heavy at the top.

## Name your tiers

Most projects can name about seven tiers. Write the list down and close it,
so agents pick from it instead of inventing new tiers.

| Tier | What it proves |
| --- | --- |
| Static checks | Syntax, house rules, generated files match their source |
| Unit or component | Pure logic, or one isolated piece of a screen |
| Integration | Routes, storage, permissions, migrations, a real database |
| Flow | What a user sees through real screens, network faked |
| Browser, sealed off | Browser-only behaviour, backend faked at the edge |
| Live journey | A few whole journeys through the real running system |
| Model eval | A model's judgement, which no fixed check can pin down |

Most of the suite sits in the middle, in flow tests. The live journey tier is
a thin tip: a handful of complete paths, no more. It is the slowest tier and
the most likely to fail for unrelated reasons.

## Set a minimum tier for each kind of change

On its own, the rule above lets every agent argue that its change needs only
the cheapest tier. So tie a minimum tier to what the change touches:

- A calculation, a validation or a state change: unit.
- A route, stored data, permissions, a queue or a schema change: integration,
  against a real local database.
- New interactive behaviour on a screen: component, then flow.
- Something only a real browser can see, such as a clipped element: browser.
- A judgement made by a model: a fixed check wherever one is possible, plus an
  eval (a scored set of example cases) that pins the behaviour.

## Fake only a true boundary

Inside your own system, use the real parts. Fake only what is truly outside
it: a paid provider, a third-party service, a clock you cannot control. A fake
is a claim about how something behaves, and claims go out of date.

When you do fake a boundary, assert against the fake. A fake that no test
checks adds nothing.

One trap: a test that fakes the very boundary it examines proves nothing. A
browser test that fakes the backend cannot catch the client sending a value
the server would reject.

## Every bug fix ships its test

The change includes a test that fails without the fix. Run it once against the
old code and watch it fail. Otherwise you do not know that it guards anything.

The change also states the root cause in one sentence. An agent can make a
symptom disappear without understanding why it happened. One written sentence
makes that gap visible. If the sentence says "the test was flaky", nothing is
fixed yet.

## Never switch off a working feature as a fix

Hiding or removing a feature that users have is not a bug fix. It is a product
decision, and product decisions belong to the owner. Three rules follow.

1. Prove the diagnosis against the live flow before you change any code.
   Reproduce the failure, then trace the real path from end to end. A premise
   you have not checked is a guess, not a diagnosis.
2. Turning off something users already have needs the owner's approval of that
   exact outcome. A general go-ahead for the task is not enough.
3. A test rewritten to expect the new behaviour must cite, in a comment, the
   decision that allowed it. A decision the agent wrote for itself is a reason
   to review the change, not permission.

### The incident behind it

A user reported that an upload control on a form sometimes cleared itself.

An agent guessed the cause: the upload had nowhere to go until the record was
saved. It never checked. One search would have shown that the record was
created when the first field was saved. The feature had worked all along.

Based on that wrong guess, the agent hid the control until the page knew the
record's id. That value arrives late, so a working feature vanished from
production. Then the agent rewrote the test. A check that the control was
present became a check that it was absent. Everything went green, and the
suite could no longer see that a working feature had just broken.

The person who owned the product found it by using the product. The fix was a
full revert. Two lessons stayed:

- A suite rewritten by the agent that made the wrong diagnosis cannot catch
  that diagnosis.
- Freedom to change the code is not authority over the product.

## Put the evidence in the tracker

When work lands, post the proof as a comment on the ticket in your tracker:

- the root cause, in one sentence;
- what the fix does;
- the regression test that guards it (the test that fails without the fix);
- the link to the merged change.

Attach screenshots there too, where the whole team can open them. Do not leave
the proof only in chat, which scrolls away. Do not leave it only in the pull
request, which most of the team never opens.

If your tracker is GitHub Issues, post the comment on the issue that the pull
request closes. Drag the screenshots into that same comment, so the picture
and the explanation stay together. For other trackers, the adapters in
[`templates/trackers/`](../templates/trackers/) show how to post evidence.
`/murmur:init` copies the one you choose to `.claude/tracker.md`.

## Screenshots show, they do not measure

A screenshot proves that something appeared. It does not prove a size, a
colour, a spacing or a duration.

Agents get this wrong with confidence. Ask an agent whether a gap is eight
pixels, and it studies the image and answers as if it had measured. Measure
with a tool instead: read the value from the running page, or assert the
measured sizes in a test that runs in a real browser.

## The acceptance guide

Every change that a person will click through carries a short acceptance guide
in its pull request. It has four parts:

1. **What changed**, in product terms.
2. **What else might be affected**, and how you worked that out.
3. **How to check it**: a click path with the expected result.
4. **What could have broken**, including anything you could not verify.

The fourth part makes the other three work. An agent that must write down
what it could not verify usually goes and verifies one more thing.

The pull request template,
[`templates/PULL_REQUEST_TEMPLATE.md`](../templates/PULL_REQUEST_TEMPLATE.md),
has these four parts as headings.

## Adopt it in a day

1. Write your tier list into the law file: closed, one line per tier.
2. Add the minimum tier for each kind of change directly under it.
3. Add two lines to the pull request checklist: the regression test, and the
   root cause in one sentence.
4. Add the rule against switching off a working feature as a fix, and name who
   approves an exception.
5. Move your next acceptance write-up out of chat and into the ticket.
