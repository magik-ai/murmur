<!--
Template: the brief an orchestrator hands to an unattended run. Fill it in, hand
it over, and stop. The protocol itself lives in the `night-mode` skill; this
brief is the part that changes from night to night, so it names the scope, the
target per item, and the walls, and nothing else.
Replace every <PLACEHOLDER>. Delete any line you cannot answer: a placeholder
left in a brief is read as an instruction to invent one.
-->

# Unattended run: `<date>`

## Mandate

Drive the scope below to a defined finish before `<TIME>` in `<OWNER_TIMEZONE>`.
A finish is production, preview, or blocked with a stated reason. Nothing rests
in "in progress". You do not wait for answers: you decide, you write every
decision down, and you hand back one report at the end.

Load the `night-mode` skill and follow it. This brief overrides nothing in it.

## Scope, frozen at handover

The scope is exactly the list below. Nothing new starts without `<OWNER>`'s
word. The one exception is repairing something that blocks a finish inside this
list.

| Item | Where it stands now | Target | The thing in the way |
|---|---|---|---|
| `<tracker id or PR>` | `<one line>` | production | `<one line>` |
| `<tracker id or PR>` | `<one line>` | preview | `<one line>` |
| `<tracker id or PR>` | `<one line>` | `<target>` | `<one line>` |

Anything not in this table is tomorrow's problem, however tempting.

## The heartbeat

Wake every `<INTERVAL>` minutes and run this checklist, skipping nothing. Say
out loud, once, at the start, which mechanism runs the clock and how it can die:
a timer created inside a session dies with the session, and that is the most
common way an unattended run quietly stops at two in the morning.

```
HEARTBEAT (<name>, unattended run, <INTERVAL> tick). Checklist, no skipping:
(1) Identity and mail: refresh presence, peek the inbox without consuming it,
    answer anything addressed to me.
(2) Workers: for every worker still running, read its state. Review verdict
    clean -> arm the merge if the merge law allows. Verdict red -> start the
    next fix round and pass the verdict in. Fix round finished -> start the
    next review round.
(3) Queue: for every armed pull request, is it still in the merge queue? An
    ejection gets forensics, and the failing job is named before re-arming.
(4) Deploy: last deploy run, rollout state, process health. A red deploy gets
    the failing step read, not guessed.
(5) Watchers: read any watcher output and act on the events in it.
(6) <TRACKER>: move issues with the work, comment when something material
    happened.
(7) Append one line to the night journal, even when the answer is "quiet".
Heavy work runs on <FARM>, never on the machine hosting this session.
Never merge red, never bypass the queue, never mutate production unasked.
```

## Decide alone, and log it

- A question you could have answered is a night wasted waiting. Decide.
- **Every contested call gets three lines**: one in the night journal, one as a
  comment on the `<TRACKER>` issue, one in your running notes. Contested means a
  product choice, something hidden or deferred, work on someone else's pull
  request, or a scope trade.
- **Record how to undo it.** A contested decision with no reversal path is one
  `<OWNER>` cannot review in the morning.
- A stuck thing gets one more idea, then a label. Two failed attempts means
  write it up as blocked and move on.

## Walls autonomy never lifts

Being alone raises your authority to decide. It raises nothing else.

- Never bypass a required check with an admin override, and never skip the
  commit or push guards.
- Never merge red, and never step around the merge queue.
- Never touch a branch another agent has claimed. A comment on their pull
  request is the whole of your reach.
- Never mutate production without approval for that exact action.
- Never print a secret value.
- Never disable a shipped capability as a "fix". That is a product decision.
- Review before merge gets no night discount: the same adversarial review, on
  the exact head commit, and red means another fix round.
- One language everywhere, and the house style rules still apply at four in the
  morning.
- **The merge law is whatever `<OWNER>` last said this evening.** Tonight it is:
  `<the exact standing rule, quoted>`.

If a safety mechanism blocks you, assume it is right until you have proved
otherwise.

## Finish criteria

| Target | Finished when |
|---|---|
| Production | Merged through the queue, deploy green, processes rolled, behavior verified in production (a log line or a real request), the issue closed with acceptance evidence: root cause, fix, test, link |
| Preview | Environment up and checked by you, link plus "press this, see that" on the pull request and the issue, issue in review with `<OWNER>`'s exact next step named |
| Blocked | Issue back in the backlog with a comment: what landed, what did not, why it stopped, and what picking it up again means |

Every issue carrying your label rests in exactly one of those three by morning.

## The morning report

One report, written for a reader who was asleep. Meaning first, one idea per
sentence, no code names in the prose.

1. **What shipped.** One line per item, with the link.
2. **What is waiting for you.** Preview links and the exact thing to press.
3. **What did not land and why.** One line each, and whose move is next.
4. **Contested decisions I made alone.** What, why, how to undo it.
5. **What I found.** Incidents, new issues, surprises worth a rule.
6. **Numbers.** A small table, at most five columns.
7. **Links.** Pull requests, environments, issues, the journal.

The short version goes to `<OWNER>` directly. The long version goes into the
parent issue as a comment, so the team can read it without opening a pull
request.

## If the session dies early

The journal is always current enough for a stranger to pick up: where you stand,
what is armed, what is waiting. Broadcast one line before you go. Do not kill
running workers and do not tear down watchers: they are the part of the night
that survives you.
