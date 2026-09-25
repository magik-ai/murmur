# Writing for humans

Agents write reports, pull requests, tickets and questions. Most people who
read them are not holding the code in their head. If a text does not make
sense on the first read, the work has not reached its reader, however good
the work was.

This chapter gives four rules, ten checks with a bad and a good example each,
a fixed shape for long texts, and habits for reporting to the owner.

## Four rules

1. **Speak simply.** A technical term used correctly is fine. A paragraph made
   only of words from the code is not.
2. **Speak as a person, not as a machine listing values.** Explain it the way
   you would say it to a colleague, not the way a log line reports a value.
3. **Give enough context to decide fast.** The reader was not watching you
   work. Say what a thing is before you use its name.
4. **Back one house style rule with a script.** A rule that only memory checks
   is broken quietly and often. See
   [below](#a-style-rule-needs-a-script-behind-it).

## Ten checks

Each check comes with one bad line and one good line.

1. **Meaning first.** Open with what happened and what needs deciding.
   - Bad: "I started by checking the logs, then traced the request path..."
   - Good: "Some users were logged out mid-session. We found the cause and
     fixed it."
2. **One idea per sentence, about fifteen words.** No nested clauses and no
   chains of commas.
   - Bad: "The server, which had been holding the connection open longer than
     expected, eventually timed out, causing the client to disconnect."
   - Good: "The server held the connection too long. It timed out. The client
     disconnected."
3. **No names from the code in the prose.** Functions, flags, files and
   branches go in a closing block for engineers, not in the sentences people
   read first.
   - Bad: "The issue was in the retry handler because the backoff limit was
     set too high."
   - Good: "The system waited too long before giving up on a failed request."
4. **Explain every term the first time you use it.** If a smart friend outside
   the field would not follow a word, replace it or explain it in one phrase.
   - Bad: "The cache was stale."
   - Good: "The saved copy of the page was out of date."
5. **Round the numbers and compare them.** Exact figures belong in a table.
   - Bad: "Latency dropped from 8,342ms to 412ms, a 95.06% reduction."
   - Good: "It used to take eight seconds. Now it takes less than one."
6. **No metaphors from the codebase.** A word like "seam" or "latch" means
   something only to someone who has read the source. When you really need a
   term, define it once, in one place, and link to it. This handbook keeps its
   list in [Start here](00-start-here.md#words-this-handbook-uses).
   - Bad: "We added a latch before the checkout seam opens."
   - Good: "We added a check that runs before payment can start."
7. **Short list items.** One or two sentences each, never a hidden paragraph.
   - Bad: a bullet that runs six sentences deep into background detail.
   - Good: "Payments now retry once. If that fails, the user sees a clear
     error."
8. **Small tables.** At most five columns, with short cells.
   - Bad: a ten-column table full of abbreviations.
   - Good: a three-column table: what changed, before, after.
9. **Keep it short.** A chat status stays under about 120 words. A longer text
   opens with a one-sentence summary.
   - Bad: a five-paragraph status update with no summary line.
   - Good: one summary sentence, then the detail for whoever wants it.
10. **Read it back as the reader.** If a sentence needs knowledge of the code,
    rewrite it in plain words or move it to the block for engineers.
    - Bad: sending the first draft unread.
    - Good: reading it once as the reader before you send it.

## The shape of a long text

A report, ticket or update longer than a few sentences follows this order:

1. What happened, in plain words.
2. What it means for the user or the product.
3. What needs deciding, or what happens next, and who does it.
4. The numbers, rounded and compared, in a small table.
5. A block for engineers, clearly separated from the rest: names, paths,
   links and exact figures.

A reader who stops after the first two parts should still know what matters.

## Reporting to the owner

The owner is the person whose product it is. They did not watch the work, and
their time is the scarcest in the project. Five habits help:

- **Recommend before you ask.** Put a short comparison of the options and your
  recommendation right above the question. "Which do you prefer?" with nothing
  to compare wastes the owner's turn.
- **Batch your questions.** The owner is often not available. Collect the open
  questions and ask them together, not one interruption at a time.
- **Lead with the outcome, then the evidence.** Open with what changed, then
  show why you believe it.
- **Discussing a plan is not approving it.** If the owner discusses, changes or
  questions a plan, that is not permission to carry it out. Reading and
  exploring are always safe. Changing anything is not.
- **Lasting documents record only what was agreed.** Write a decision down
  after it is made, not when it is first suggested. Do not park an open idea
  in a plan and hope it reads as settled later.

## A style rule needs a script behind it

A house style rule is worth adopting only if something other than memory
checks it. Two examples: no TODO comment without a link to an issue, or no
sentence over thirty words in a status. A rule that depends on every writer
remembering it is broken quietly and often.

The fix is a short script. Before a change can merge, it scans every document
and every piece of interface text for the forbidden pattern, and it fails the
check if it finds one. Then "did we follow the style guide?" is a check that
passes or fails, not a matter of trust.

Choose the rules that matter to your project. Do not write a rule down unless
you will also write the few lines of script that enforce it.

## Adopt it in a day

1. Put the four rules and the five-part shape at the top of your law file or
   your writing guide, with one bad and one good example each.
2. Pick the style mistake that annoys you most. Write a small script that
   fails when it appears, and run it on every pull request.
3. Take one recent report you wrote. Rewrite its first two sentences so they
   say what happened and what it means, with no story of how you worked.
4. From now on, put a recommendation above every decision question, and notice
   how much faster the answers come.
