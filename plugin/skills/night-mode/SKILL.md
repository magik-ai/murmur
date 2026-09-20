---
name: night-mode
description: Unattended long run. Trigger on "night mode", "unattended run", "have it done by morning", "finish this while I sleep". Drives the CURRENT scope to a defined finish (production, preview, or blocked with a stated reason) on a heartbeat, decides alone, logs every contested call, and hands back one report at the end.
---

# Night mode

"Night mode" always means one thing: **drive the current scope to a defined
finish while nobody is watching.** A finish is production (merged, deployed,
verified), preview (a running environment plus instructions), or blocked (with
a named reason and what picking it up again means). Nothing rests in "in
progress".

You do not wait for answers. You decide, you write each decision down, and at
the end you hand back one report with every artifact attached.

## 1. Freeze the scope

Scope is what is already open when the command arrives: issues in <TRACKER>
carrying your agent label, your open pull requests, your running lanes, plus
anything <OWNER> named in the same sentence. Write that list down before you
touch anything.

Nothing new starts without <OWNER>'s word. The one exception is repairing
something that blocks a finish inside the frozen scope.

## 2. The first ten minutes

1. Confirm identity. If you run a head office, `hq whoami`, then
   `hq hello <name> --task "night run: <scope in one line>"`. Without one,
   still state your name and scope in whatever shared log the team reads.
2. Send <OWNER> one message: each scope item, its target (production or
   preview), and what stands in the way. Do not wait for a reply.
3. Arm the heartbeat (section 3) and tell <OWNER> in one sentence how it can
   die.
4. Open the night journal at `<scratchpad>/night-<date>.md`. One line per
   heartbeat: timestamp, what happened, what is next.
5. Open a memory note for the run: the mandate, the scope, the targets, and an
   empty list headed "contested decisions" that you append to all night.

## 3. The heartbeat

An unattended run needs a clock, because an agent left alone stops noticing
that it has stopped. Wake on a fixed interval (fifteen to twenty minutes is
the working range) and run the same checklist every time, skipping nothing.

```
HEARTBEAT (<name>, unattended run, <interval> tick). Checklist, no skipping:
(1) Identity and mail: refresh presence, peek the inbox without consuming it,
    answer anything addressed to me.
(2) Lanes: for every worker still running, read its state. Review verdict
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
(7) Append one line to the night journal, even if the answer is "quiet".
Heavy work runs on <FARM>, never on the machine hosting this session.
Never merge red, never bypass the queue, never mutate production unasked.
```

**The alarm is fragile and you must say so out loud, once, at the start.** A
timer created inside the session lives only as long as the session: close the
window, let the machine sleep, lose the network, and the ticks stop silently.
That is the most common way an unattended run quietly dies at 2am.

Two sturdier options, in order of preference:

- **A headless lane.** Spawn a worker on <FARM> whose whole job is the
  checklist above on a loop. It survives your window closing, and it reports
  through the same channels as any other lane.
- **A schedule outside the session.** A cron entry or a hosted scheduled run
  that starts a fresh agent each interval with the same checklist. Slower to
  set up, but it survives the machine sleeping.

Whichever you pick, name it in the opening message so <OWNER> knows what kind
of night this is.

## 4. Decision rules

- **Decide alone.** A question you could have answered is a night wasted
  waiting.
- **Log every contested call.** A product choice, something hidden or
  deferred, work on someone else's pull request, a scope trade: each one gets
  a line in the night journal, a comment on the <TRACKER> issue, and an entry
  in the memory note. They lead the morning report.
- **Record how to undo it.** A contested decision without a reversal path is a
  decision <OWNER> cannot review in the morning.
- **Review before merge does not get a night discount.** Whatever gate the
  work normally passes, it passes now: an adversarial review on the exact head
  commit, verdict posted on the pull request, red means another fix round.
- **Light work by hand, heavy work on <FARM>.** Builds, full test suites and
  environments go to the farm. Check the account quota before every spawn; a
  worker started on an exhausted account dies on its first step having done
  nothing.
- **A stuck thing gets one more idea, then a label.** If two attempts fail,
  write it up as blocked and move to the next item rather than burning the
  night on one wall.

## 5. Walls autonomy never lifts

Being alone raises your authority to decide. It raises nothing else.

- Never bypass a required check with admin rights, and never skip the
  pre-commit or pre-push guards.
- Never merge red, and never step around the merge queue.
- Never touch a branch another agent has claimed. A comment on their pull
  request is the whole of your reach.
- Never mutate production without approval for that exact action. Reading is
  free; changing is not.
- Never print a secret value. Compare hashes instead.
- Never disable a shipped capability as a "fix". That is a product decision.
- One language everywhere, and the house style rules still apply at 4am.
- The merge law is whatever <OWNER> last said this evening. If the standing
  rule is "nothing merges without my yes", night mode does not lift it.
  "Finish it yourself" lifts it only for the named scope.

If a safety mechanism blocks you, assume it is right until you have proven
otherwise. In practice it usually was.

## 6. Finish criteria

| Target | Finished when |
| --- | --- |
| Production | Merged through the queue, deploy green, processes rolled, behavior verified in production (a log line or a real request), the issue closed with acceptance evidence: root cause, fix, test, link |
| Preview | Environment up and checked by you, link plus "press this, see that" written on the pull request and the issue, issue in review with <OWNER>'s exact next step named |
| Blocked | Issue back in the backlog with a comment: what landed, what did not, why it stopped (someone else's ruling, a third party, a quota), and what picking it up again means |

Every issue carrying your label rests in exactly one of those three states by
morning. An issue still marked in progress, with no worker, no pull request
and no comment, is the failure this protocol exists to prevent.

## 7. The morning report

One shape, written for a reader who was asleep. Meaning first, one idea per
sentence, no code names in the prose.

1. **What shipped.** One line per item, with the link.
2. **What is waiting for you.** Preview links and the exact thing to press.
3. **What did not land and why.** One line each, and whose move is next.
4. **Contested decisions I made alone.** What, why, how to undo it.
5. **What I found.** Incidents, new issues, surprises worth a rule.
6. **Numbers.** A small table, at most five columns.
7. **Links.** Pull requests, environments, issues, the night journal, the
   memory note.

The short version goes to <OWNER> directly. The long version goes into the
parent issue as a comment, so the rest of the team can read it without opening
a pull request. Close the memory note with a dated summary of the night.

## 8. Handover if the session ends early

Sessions die. Plan for it from the first tick.

- The journal and the memory note are always current enough to be picked up by
  a stranger: where you stand, what is armed, what is waiting.
- Broadcast one line to the team before you go.
- Do not kill running lanes and do not tear down watchers. They are the part
  of the night that survives you.
- The next session starts by reading the journal, not by re-planning.
