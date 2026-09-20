# Writing for humans

## Why this gets its own chapter

Writing correct code and then explaining it in jargon is only half the job.
Most readers of a status update or a ticket are not holding the code in their
head. If the writing does not land on the first read, the work has not
actually been communicated, no matter how good it was.

## Four rules

**Speak simply.** A term of art used correctly is fine. A paragraph built
entirely from codebase vocabulary is not.

**Speak as a person, not as a machine listing parameters.** Explain it the way
you would out loud to a colleague, not the way a log line reports a value.

**Always give enough context to decide fast.** The reader was not watching
you work. Say what a thing is before you refer to it by name.

## Ten checks

Each check pairs one bad line with one good line, so the difference is
concrete rather than abstract.

1. **Meaning first.** Open with what happened and what needs deciding.
   Bad: "I started by checking the logs, then traced the request path..."
   Good: "Some users were logged out mid-session. Found and fixed."

2. **One idea per sentence, short.** No nested clauses, no chains of commas.
   Bad: "The server, which had been holding the connection open longer than
   expected, eventually timed out, causing the client to disconnect."
   Good: "The server held the connection too long. It timed out. The client
   disconnected."

3. **No code names in the prose.** Functions, flags, files, and branches
   belong in a closing block for engineers, not the sentences read first.
   Bad: "The issue was in the retry handler because the backoff limit was set
   too high."
   Good: "The system waited too long before giving up on a failed request."

4. **Explain every term on first use.** If a sharp friend outside the field
   would not follow it, replace it or explain it in one phrase.
   Bad: "The cache was stale."
   Good: "The saved copy of the page was out of date."

5. **Round numbers and compare them.** Precise figures belong in a table.
   Bad: "Latency dropped from 8,342ms to 412ms, a 95.06% reduction."
   Good: "It used to take eight seconds. Now it takes less than one."

6. **Define your terms once, and avoid metaphors from the codebase.** A word
   like seam or latch means something only to someone who has read the source.
   When a term really is needed, define it in one place and link to it. This
   handbook keeps its own short list in
   [start here](00-start-here.md#words-this-handbook-uses).
   Bad: "We added a latch before the checkout seam opens."
   Good: "We added a check that runs before payment is allowed to start."

7. **Short list items.** One or two sentences each, never a hidden paragraph.
   Bad: a bullet running six sentences deep into background detail.
   Good: "Payments now retry once automatically. If that fails, the user sees
   a clear error."

8. **Small tables.** Five columns at most, short cells.
   Bad: a ten-column table dense with abbreviations.
   Good: a three-column table: what changed, before, after.

9. **Keep it short.** A longer piece opens with a summary before the detail.
   Bad: a five-paragraph status update with no summary line.
   Good: one summary sentence, then supporting detail for whoever wants it.

10. **Read it back as the reader.** If a sentence needs code knowledge to
    parse, rewrite it in plain words or move it to the engineering block.
    Bad: shipping the first draft unread.
    Good: reading it once from the recipient's side before sending.

## The fixed shape of a long piece of writing

Any report, ticket, or update longer than a couple of sentences follows the
same shape, in this order: what happened, in plain terms; what it means for
the user or the product; what to decide or what happens next, and from whom;
the numbers, rounded and compared, in a small table; then a block for
engineers holding names, paths, links, and exact figures, clearly separated
from the prose above it.

A reader who only reads the first two parts should still walk away knowing
what matters.

## Reporting to the owner

Reporting to the person who owns the product adds a few habits on top of
everything above:

- **State an opinion before asking.** A decision question needs a
  self-contained comparison and a recommendation right above it. "Which do
  you prefer?" with nothing to compare wastes the owner's turn.
- **Batch decisions.** The owner is often unavailable in the moment. Collect
  open questions and present them together, not one interruption at a time.
- **Lead with the outcome, then the evidence.** The owner did not watch the
  work happen; open with what changed, then support it.
- **Refining a proposal is not approval.** If the owner discusses, amends, or
  questions a plan, that is not a green light to execute it. Read-only
  exploration is always safe; changing anything is not.
- **Durable documents record only what was agreed.** Write the decision after
  it is made, not the option merely floated. A plan is not the place to park
  an unresolved idea and hope it reads as settled later.

## A rule is only as good as its enforcement

A house style rule (say, no TODO comment without a link to an issue, or no
sentence over thirty words in a status) is only worth adopting when something
other than memory checks it. A rule that
depends on every writer remembering it by hand gets broken quietly and often.

The fix is mechanical: a short script scans every document and interface
string for the character before anything can merge, and rejects the change if
it finds one. With a script behind it, "did we follow the style guide" stops
being a matter of trust and becomes a check passing or failing. Pick whatever
house rules matter to your project, but do not bother writing one down unless
you are also willing to write the few lines of script that enforce it.

## Adopt it in a day

1. Put the four rules and the fixed five-part shape at the top of your law
   file or your writing guide, with one good/bad example each.
2. Pick your single most annoying style violation and write a small script
   that fails a check when it appears, and wire it into CI.
3. Take one recent report or ticket you wrote and rewrite its opening two
   sentences using rule one: meaning first, no process narration.
4. Add the "opinion before asking" habit to how you phrase every decision
   question from now on, and notice how much faster answers come back.
