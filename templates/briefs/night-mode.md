<!--
Template: the brief an orchestrator hands to an unattended run. Fill it in,
hand it over, and stop. The procedure lives in the `night-mode` skill. This
brief holds only what changes from one night to the next: the scope, the target
for each item, and the limits.
Replace every <PLACEHOLDER>. Delete any line you cannot answer: an agent reads
a placeholder left in a brief as an instruction to invent a value.
The heartbeat checklist below is a copy of section 3 of the night-mode skill.
When the skill changes, update this copy.
-->

# Unattended run: `<date>`

Heartbeat mode: <alarm | lane | schedule | none>  (the night-mode skill says what each means)
Night journal: <a comment on the parent issue, or a file on its own branch>  (never only in this session)

## Mandate

Drive the scope below to a defined finish before `<TIME>` in `<OWNER_TIMEZONE>`.
A finish is production, preview, or blocked with a stated reason. Nothing is
left "in progress". You do not wait for answers: you decide, you write every
decision down, and you hand back one report at the end.

Load the `night-mode` skill and follow it. This brief overrides nothing in it.

## Scope, frozen at handover

The scope is exactly the list below. Nothing new starts without `<OWNER>`'s
word. The one exception is repairing something that blocks a finish inside
this list.

| Item | Where it stands now | Target | What is in the way |
|---|---|---|---|
| `<tracker id or PR>` | `<one line>` | production | `<one line>` |
| `<tracker id or PR>` | `<one line>` | preview | `<one line>` |
| `<tracker id or PR>` | `<one line>` | `<target>` | `<one line>` |

Anything not in this table waits for tomorrow, however tempting it is.

## The heartbeat

Wake every `<INTERVAL>` minutes and run this checklist, skipping nothing. At
the start, say once which mechanism runs the clock and how it can stop. A
timer created inside a session stops with the session, and that is the most
common way an unattended run quietly stops in the middle of the night.

```text
HEARTBEAT (<name>, unattended run, <interval> tick). Checklist, no skipping:
(1) Identity and mail: read the inbox without marking it read (hq inbox --peek;
    any hq command also keeps my presence fresh), and answer anything
    addressed to me.
(2) Lanes: for every worker still running, read its state. Review verdict
    clean -> arm the merge if the merge rule allows. Verdict red -> start the
    next fix round and pass the verdict in. Fix round finished -> start the
    next review round.
(3) Queue: for every armed pull request, is it still in the merge queue? An
    ejection gets investigated, and the failing job is named before re-arming.
(4) Deploy: last deploy run, rollout state, process health. For a red deploy,
    read the failing step; do not guess.
(5) Watchers: read any watcher output and act on the events in it.
(6) <TRACKER>: move issues with the work, and comment when something important
    happened. If this session cannot write to the tracker, leave the update in
    the night journal for the orchestrator to post.
(7) Add one line to the night journal, even if the answer is "quiet".
Heavy work runs on <FARM> when there is one, never on the machine hosting this
session. With no farm, run it here, one job at a time.
Never merge red, never bypass the merge queue, never change production unasked.
```

## Decide alone, and log it

- A question you could have answered yourself wastes the night waiting.
  Decide.
- **Every contested decision gets three records**: a line in the night
  journal, a comment on the `<TRACKER>` issue, and an entry in the memory note
  for the run. A decision is contested when it is a product choice, something
  hidden or deferred, work on someone else's pull request, or a trade within
  the scope.
- **Record how to undo it.** `<OWNER>` cannot review a contested decision in
  the morning without a way to reverse it.
- A stuck item gets one more idea, then a label. If two attempts fail, write
  it up as blocked and move on.

## Limits that autonomy never lifts

Working alone gives you more authority to decide. It gives you nothing else.

- Never bypass a required check with an admin override, and never skip the
  commit or push guards.
- Never merge red, and never go around the merge queue.
- Never touch a branch another agent has claimed. A comment on their pull
  request is as far as you go.
- Never change production without approval for that exact action.
- Never print a secret value.
- Never switch off a shipped feature as a "fix". That is a product decision.
- Review before merge still applies at night: the same adversarial review, of
  the exact head commit, and another fix round when it is red.
- Everything you commit is in the repository's one language, and the house
  style rules still apply at night.
- **The merge rule is whatever `<OWNER>` last said this evening.** Tonight it
  is: `<the exact standing rule, quoted>`.

If a safety mechanism blocks you, assume it is right until you have proved
otherwise.

## When an item is finished

| Target | Finished when |
|---|---|
| Production | Merged (through the merge queue where there is one), deploy green, processes restarted on the new version, behavior verified in production (a log line or a real request), and the issue closed with acceptance evidence: root cause, fix, test, link |
| Preview | Environment up and checked by you, the link plus "press this, see that" on the pull request and the issue, and the issue in review with `<OWNER>`'s exact next step named |
| Blocked | Issue back in the backlog with a comment: what landed, what did not, why it stopped, and what it takes to pick it up again |

By morning, every issue that carries your label is in exactly one of those
three states.

## The morning report

One report, written for a reader who was asleep. Meaning first, one idea per
sentence, no code names in the prose.

1. **What shipped.** One line per item, with the link.
2. **What is waiting for you.** Preview links and the exact thing to press.
3. **What did not land, and why.** One line each, and whose move is next.
4. **Contested decisions I made alone.** What, why, and how to undo it.
5. **What I found.** Incidents, new issues, surprises worth a rule.
6. **Numbers.** A small table, at most five columns.
7. **Links.** Pull requests, environments, issues, the journal.

The short version goes to `<OWNER>` directly. The long version goes on the
parent issue as a comment, so the team can read it without opening a pull
request.

## If the session ends early

Keep the journal current enough for a stranger to pick up at any moment: where
you stand, what is armed, what is waiting. Send the team one line before you
go. Do not stop running workers, and do not remove watchers: they are the part
of the night that continues without you.
