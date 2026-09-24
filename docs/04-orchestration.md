# Orchestration

Once more than two agents work in one repository, someone has to hold the whole
picture. That is the orchestrator: an agent that splits a batch of work into
lanes (one agent, one task, one branch each), starts them, checks what they
report and assembles the result. It is a coordination role, not a
senior-engineer role. Its value is knowing what every lane is touching, not
writing the best code in the room.

The procedure an agent follows is the plugin's `orchestrate` skill,
[`plugin/skills/orchestrate/SKILL.md`](../plugin/skills/orchestrate/SKILL.md).
This chapter explains why the role works the way it does.

## Four jobs, in priority order

1. **Guard scope.** Nothing else matters if two lanes edit the same file. Every
   lane declares its paths before it starts, and no two lanes may declare the
   same path. An overlap is refused, not warned about, because in a busy
   session nobody reads a warning.
2. **Order the shared files.** A few files, the spine of the repository, are
   wanted by everyone: where the application is wired together, generated
   interfaces, shared registries, lists that only grow. The orchestrator alone
   sets their order, one lane at a time. See
   [parallel lanes](03-parallel-lanes.md).
3. **Verify before reporting.** The orchestrator is the last check between a
   worker's claim and the owner's decision. An unverified claim that reaches
   the owner is worse than none, because the owner will act on it.
4. **Keep the record accurate.** The lane registry and the tracker are the
   only lasting memory in the system. The orchestrator's context ends with its
   session.

## It never writes product code

An orchestrator editing product code means one of two things. Either the task
was small enough to do directly and never needed a team. Or the role has
drifted, and the map of who owns what is now kept by an agent that is busy
debugging. Both are reasons to stop.

## Working with lanes

**Resume, never relaunch.** Workers die on network hiccups. A resumed session
comes back with its full context. A fresh launch on the same task starts again
from a summary, which is slower and less accurate. Work committed before a
crash survives it.

**Never message a lane in the middle of a turn.** Wait until it is idle. A
message that arrives during a turn can start a second turn in the same working
copy.

**What goes wrong without it.** Two turns run at once in one checkout. Both
write files and neither knows about the other. Because it is the same process
writing to the same tree, git shows no conflict marker. The damage looks like a
clean commit.

**Launch detached.** A worker started in the foreground dies when the tool call
that started it times out, and on a long task it always does. On a farm (an
always-on machine that runs agents with murmur's `fleet` tool), `fleet spawn`
starts every worker as a background service.

**Stop a lane only after its change has merged**, not when it opens the pull
request. Review feedback has to reach the worker that wrote the code while its
context is still loaded. Otherwise the fix is made by a stranger reading a
diff.

## Subagents, and the verification contract

Sending work to many subagents at once is where an orchestrator saves the most
time, and it is only useful if their output can be trusted. So every
investigation prompt carries the same contract, and a report that misses it
goes back. For each finding, the report gives:

- its severity;
- the file and line;
- a concrete failure scenario, with concrete inputs;
- whether it is **confirmed** (the code path was traced) or **plausible** (it
  still needs proof at runtime).

It also says what was checked and found correct. A report that lists only
defects has usually stopped reading halfway, and the owner needs to know what
is sound as much as what is broken.

Then the orchestrator does its own part.

**Never read a worker's raw transcript.** It is the whole message log. It uses
up the context the orchestrator needs for everything else, and the completion
summary already carries the information.

**Check the claims a decision depends on against the real thing, not against
more code.** Read the installed dependency, query the live system, and run the
test instead of repeating that it passes.

**What goes wrong without it.** Two investigation reports arrive with the same
confidence and tone. One claims a syntax error that is valid in the language
version the project runs. The other claims a library treats an empty allowlist
as "skip the check entirely", which is right, and a real security hole. Nothing
in the reports tells them apart. Opening the installed library settles each in
about a minute.

## Choosing a model

Split by how much judgement the work needs, not by how hard it looks:

- The **strongest model** takes ambiguous, architectural or risky work, and
  always reviews another agent's change. Catching one bad merge is worth many
  cheap runs.
- A **mid model** is the default and covers most lanes.
- The **cheapest model** does mechanical work: renames, repetitive fixes,
  routine documentation edits.

## Check quota and capacity before you spawn

**Account headroom.** Workers use the same subscription allowance you work in.
Spread lanes across accounts and prefer the one with the most left. A worker
started on an exhausted account dies on its first step, having done nothing,
and must then start clean instead of resuming. On a farm, `fleet accounts`
shows each account's session and weekly use. For Claude lanes, `fleet spawn`
picks an account with headroom unless you name one with `--account`.

**Machine capacity.** Check the machine right before you spawn, not at the
start of the session, and spawn fewer or wait if it says so. On a farm,
`fleet capacity` checks free memory, free disk, temperatures and the number of
running agents, and prints `OK` or `BLOCK` with its reasons.

## Never spawn without an explicit go

Propose the lanes, the number of workers, the model for each lane and what
lands at the end. Then stop and wait.

**Refining a proposal is not approval.** If the owner amends the plan, asks
about a lane or trims the scope, that is a conversation about the plan, not an
instruction to run it. Read-only exploration is always safe; spawning is not.
Never act on an implied yes.

## Adopt it in a day

1. Name the role out loud before your next multi-agent batch, and write down
   which session holds it.
2. Add the verification contract, all five parts, to your standard
   investigation prompt.
3. Write your three model tiers into your law file, so choosing a model stops
   being a new decision in every session.
4. Make one sentence a habit: a proposal is not approved until the owner says a
   word that means go.
5. Give every lane a short brief with its task, acceptance criteria and path
   manifest, starting from
   [`templates/briefs/lane.md`](../templates/briefs/lane.md).
