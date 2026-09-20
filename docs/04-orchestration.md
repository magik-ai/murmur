# Orchestration

## What the role is for

Once more than two agents work in one repository, somebody has to hold the
whole picture. That somebody is the orchestrator. It is a coordination role,
not a senior-engineer role: its value is knowing what every lane is touching,
not writing the best code in the room.

This chapter explains why the role is shaped the way it is. The procedure
lives in the `orchestrate` skill (`plugin/skills/orchestrate/SKILL.md`), which
is the manual an agent actually loads.

## The four jobs, in priority order

**One, guard scope.** Nothing else matters if two lanes edit the same file.
Every lane declares the paths it owns before it starts, and no two lanes may
declare the same path. An overlap is refused, not warned about, because a
warning in a busy session is a warning nobody reads.

**Two, serialize the spine.** A few files in every project are wanted by
everyone: the place where the application is wired together, generated
interface files, shared registries, any list that only ever grows. These are
the orchestrator's alone to sequence. One lane touches a spine file at a time,
in an order the orchestrator picks.

**Three, verify before reporting.** The orchestrator is the last checkpoint
between a worker's claim and <OWNER>'s decision. A claim that reaches the
owner unverified is worse than no claim, because the owner will act on it.

**Four, keep the board honest.** The lane registry and <TRACKER> are the only
durable memory in the system. An orchestrator's own context is not memory: it
ends when the session ends.

## The one thing it never does

It does not implement. An orchestrator editing product code means one of two
things. Either the task was small enough to do directly and never needed a
fleet, or the role has drifted and the scope map is now kept by an agent that
is also busy debugging. Both are worth stopping for.

## Talking to lanes

Four habits, each learned the same way.

**Resume, never relaunch.** Worker processes die on network hiccups. A resumed
thread comes back with its full context intact. A fresh launch on the same task
throws that away and starts again from a summary, which is both slower and less
accurate. In every observed crash, work that was committed before the death
survived.

**Never message a lane mid-turn.** Wait until it is idle. A message landing
during a turn can start a second turn in the same working copy.

**The incident behind it:** two turns ran concurrently in one checkout. Both
were writing files, neither knew about the other, and because they were the
same process writing to the same tree, git produced no conflict marker at all.
The damage looked like a clean commit.

**Launch detached.** A worker started in the foreground dies when the launching
tool call times out, which for a long task is always.

**Kill a lane only after its change is merged.** Not when it opens the change
for review. Review feedback needs to reach the same worker that wrote the code,
with its context still loaded, otherwise the fix is made by a stranger reading
a diff.

## Running subagents, and the verification contract

Fan-out is the orchestrator's real leverage, and it is only worth anything if
the output can be trusted. So every investigation prompt carries the same
contract, and a report that does not meet it is sent back.

Each finding must state its severity, the file and line, and a concrete failure
scenario with concrete inputs. Each finding must be marked **confirmed** (the
code path was actually traced) or **plausible** (it still needs runtime proof).
And the report must also say what was checked and found correct, because a
report that is all defects is usually a report that stopped reading halfway,
and the owner needs the assurance as much as the defect list.

Then the orchestrator does its own part.

**Never read a worker's raw transcript.** It is the entire message log. Reading
one will consume the context the orchestrator needs for everything else, in
exchange for information the completion summary already carried.

**Verify load-bearing claims against the artifact, not against more code.**
Read the installed dependency. Query the live system. Run the test rather than
forwarding the claim that it passes.

**The incident behind it:** two investigation reports arrived with identical
confidence and identical tone. One claimed a syntax error that was in fact
valid on the language version the project runs. The other claimed a library
treats an empty allowlist as "skip the check entirely", which was exactly
right and a real security hole. Nothing in either report distinguished them.
Opening the installed library settled both in about a minute each.

## The model heuristic

Three tiers, split by judgement rather than difficulty. The **strongest
model** takes ambiguous, architectural, or risky work, and always reviews
another agent's change, because catching one bad merge is worth many cheap
runs. A **mid model** is the default and covers most lanes. The **cheapest
model** does mechanical work: renames, repetitive fixes, documentation
sweeps.

## Capacity and quota, before anything is spawned

Check two things before spawning, every time.

**Account headroom.** Workers spend the same allowance the owner works in.
Spread lanes across accounts and prefer the one with the most left. A worker
started on an exhausted account dies on its first step having done nothing,
and must then be started clean rather than resumed.

**Machine capacity.** Check load, memory, and running worker count on <FARM>
right before spawning, not at the start of the session. If the check says
wait, spawn fewer or wait.

## Never spawn without an explicit go

Propose the lanes, the worker count, the model each lane gets, and what lands
at the end. Then stop.

**Refining a proposal is not approval.** If the owner amends the plan, asks
about a lane, or trims the scope, that is a conversation about the plan, not an
instruction to run it. Read-only exploration is always safe. Spawning is not.
Never act on an implied yes.

## Adopt it in a day

1. Name the role out loud before your next multi-agent batch, and write down
   which session is holding it.
2. Add the verification contract to your standard investigation prompt, all
   five parts, including what was checked and found correct.
3. Write your three model tiers into your law file so lane assignment stops
   being a per-session judgement call.
4. Adopt one sentence as a habit: a proposal is not approved until the owner
   says a word that means go.
