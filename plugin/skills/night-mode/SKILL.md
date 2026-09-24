---
name: night-mode
description: Unattended long run. Trigger on "night mode", "unattended run", "have it done by morning", "finish this while I sleep". Drives the CURRENT scope to a defined finish (production, preview, or blocked with a stated reason) on a heartbeat, decides alone, logs every contested call, and hands back one report at the end.
---

# Night mode

"Night mode" always means one thing: **drive the current scope to a defined
finish while nobody is watching.** There are three finishes: production
(merged, deployed, verified), preview (a running environment plus
instructions), or blocked (with a named reason, and what it takes to pick the
work up again). Nothing is left "in progress".

You do not wait for answers. You decide, you write each decision down, and at
the end you hand back one report with every artifact attached.

## 1. Freeze the scope

The scope is what is already open when the command arrives: issues in
<TRACKER> that carry your agent label, your open pull requests, your running
lanes (a lane is one worker on one task, on its own branch), plus anything
<OWNER> named in the same message. Write that list down before you touch
anything.

Nothing new starts without <OWNER>'s word. The one exception is repairing
something that blocks a finish inside the frozen scope.

## 2. The first ten minutes

1. Confirm your identity. If you use a head office (the `hq` command), run
   `hq whoami`, then `hq hello <name> --task "night run: <scope in one line>"`.
   Without one, still state your name and scope in whatever shared log the
   team reads.
2. Send <OWNER> one message: each scope item, its target (production or
   preview), and what stands in the way. Do not wait for a reply.
3. Start the heartbeat (section 3), and tell <OWNER> in one sentence how it
   could stop.
4. Open the night journal at `<scratchpad>/night-<date>.md`. Write one line per
   heartbeat: the time, what happened, what is next.
5. Open a memory note for the run: the mandate, the scope, the targets, and an
   empty list headed "contested decisions" that you add to all night.

## 3. The heartbeat

An unattended run needs a clock, because an agent left alone does not notice
that it has stopped. Wake on a fixed interval (every fifteen to twenty
minutes works well) and run the same checklist every time, skipping nothing.

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

**Choose how the heartbeat wakes you before the first tick, and write the
choice into the night journal.** Ask <OWNER> if it was not stated:

| Mode | What wakes you | When to pick it |
|---|---|---|
| alarm | a timer inside this session | the window and the machine stay awake all night |
| lane | a headless lane on <FARM> that reruns the checklist | you have a farm, and the session may close |
| schedule | a cloud or cron schedule outside the session | you have neither a farm nor a machine that stays awake |
| none | nothing; you work in one long stretch and hand over | the scope is small enough to finish before the session ends |

**The alarm is fragile, and you must say so once, at the start.** A timer
created inside the session lives only as long as the session. If the window
closes, the machine sleeps or the network drops, the ticks stop and nobody
notices.

Two sturdier options, in order of preference:

- **A headless lane.** Spawn a worker on <FARM> whose whole job is the
  checklist above, in a loop. It survives your window closing, and it reports
  through the same channels as any other lane. With no farm, the same worker
  can run as a local headless session, but it then stops when the machine
  does.
- **A schedule outside the session.** A cron entry or a hosted scheduled run
  that starts a fresh agent each interval with the same checklist. It takes
  longer to set up, but it survives the machine sleeping.

Whichever you pick, name it in the opening message, so <OWNER> knows what kind
of night this is.

## 4. Decision rules

- **Decide alone.** A question you could have answered yourself wastes the
  night waiting.
- **Log every contested decision.** A product choice, something hidden or
  deferred, work on someone else's pull request, a trade within the scope: each
  one gets a line in the night journal, a comment on the <TRACKER> issue, and
  an entry in the memory note. They lead the morning report.
- **Record how to undo it.** <OWNER> cannot review a contested decision in the
  morning without a way to reverse it.
- **Review before merge still applies at night.** Whatever gate the work
  normally passes, it passes now: an adversarial review of the exact head
  commit, a verdict posted on the pull request, and another fix round when it
  is red.
- **Light work by hand, heavy work on <FARM>.** Builds, full test suites and
  environments go to the farm. Check the account quota before every spawn: a
  worker started on an exhausted account fails on its first step, having done
  nothing. **If you have no farm**, run the heavy work as a local headless
  session, one job at a time, and check your own subscription usage first.
- **A stuck item gets one more idea, then a label.** If two attempts fail,
  write it up as blocked and move to the next item, rather than spending the
  night on one problem.

## 5. Limits that autonomy never lifts

Working alone gives you more authority to decide. It gives you nothing else.

- Never bypass a required check with admin rights, and never skip the commit
  or push guards.
- Never merge red, and never go around the merge queue.
- Never touch a branch another agent has claimed. A comment on their pull
  request is as far as you go.
- Never change production without approval for that exact action. Reading is
  free; changing is not.
- Never print a secret value. Compare hashes instead.
- Never switch off a shipped feature as a "fix". That is a product decision.
- Everything you commit is in the repository's one language, and the house
  style rules still apply at night.
- The merge rule is whatever <OWNER> last said this evening. If the standing
  rule is "nothing merges without my yes", night mode does not lift it.
  "Finish it yourself" lifts it only for the named scope.

If a safety mechanism blocks you, assume it is right until you have proven
otherwise.

## 6. When an item is finished

| Target | Finished when |
| --- | --- |
| Production | Merged (through the merge queue where there is one), deploy green, processes restarted on the new version, behavior verified in production (a log line or a real request), and the issue closed with acceptance evidence: root cause, fix, test, link |
| Preview | Environment up and checked by you, the link plus "press this, see that" written on the pull request and the issue, and the issue in review with <OWNER>'s exact next step named |
| Blocked | Issue back in the backlog with a comment: what landed, what did not, why it stopped (someone else's decision, a third party, a quota), and what it takes to pick it up again |

By morning, every issue that carries your label is in exactly one of those
three states. An issue still marked in progress, with no worker, no pull
request and no comment, is the failure this protocol exists to prevent.

## 7. The morning report

One shape, written for a reader who was asleep. Meaning first, one idea per
sentence, no code names in the prose.

1. **What shipped.** One line per item, with the link.
2. **What is waiting for you.** Preview links and the exact thing to press.
3. **What did not land, and why.** One line each, and whose move is next.
4. **Contested decisions I made alone.** What, why, and how to undo it.
5. **What I found.** Incidents, new issues, surprises worth a rule.
6. **Numbers.** A small table, at most five columns.
7. **Links.** Pull requests, environments, issues, the night journal, the
   memory note.

The short version goes to <OWNER> directly. The long version goes on the parent
issue as a comment, so the rest of the team can read it without opening a pull
request. Close the memory note with a dated summary of the night.

## 8. Handover if the session ends early

Sessions end unexpectedly. Plan for it from the first tick.

- Keep the journal and the memory note current enough for a stranger to pick
  up: where you stand, what is armed, what is waiting.
- Send the team one line before you go.
- Do not stop running lanes, and do not remove watchers. They are the part of
  the night that continues without you.
- The next session starts by reading the journal, not by planning again.
