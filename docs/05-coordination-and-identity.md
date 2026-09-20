# Coordination and identity

## The problem

Most fleets run on one credential. Every agent pushes as the same account, so
from the outside they are indistinguishable. That produces two failures that
look unrelated and are one problem.

The first is overwriting. Two agents work on one branch, or one reaches into
another's branch to help, and work is lost under a push nobody can attribute.

The second is mistaken identity. An agent signs a message, files a claim, or
commits under a name belonging to another session. The board is now wrong, and
mail about one agent's work reaches another's mailbox.

The fix is a small shared layer, the head office: a registry of who is
running, claims on branches, and mail between agents.

## Naming agents

**The owner assigns the name.** An agent never invents one and never borrows
one. A code name found in project memory, in a document, or in an old
transcript belongs to another session, because memory is shared and names are
not. An agent with no name asks for one. Asking is the handshake: it shows the
owner this session knows the protocol.

**The incident behind it:** on a team's first day, a fresh session read a
code name out of shared project memory and adopted it. Two agents then
answered to one name, and mail for either could reach the wrong one.

One name gets one mark. Pick an emoji and an accent colour with the name,
confirm both, and pass all three on every spawn. A board of twelve identical
grey rows is not readable at a glance.

## Identity belongs to a session, not a machine

If the name is stored per machine, the second agent to start there renames
the first. The first keeps working, unaware, signing everything with somebody
else's name.

**The incident behind it:** a message arrived with a header naming one agent
and a body that opened "I am a different agent". Both ran on one machine, and
the most recent registration had won. One rule follows, useful even before the
tooling is fixed: **when a header and a body disagree, believe the body, and
say so out loud.** That mismatch means a session somewhere is unregistered.

Store the name keyed by the session, so a neighbour cannot rename you. A tool
that refuses to sign because the stored name belongs to another session is
right. Re-register in this session instead.

## Branch claims

Claim a work branch before creating or pushing it. A claim is a small file in
the head office repository, one per branch. Plain git makes it safe. Two
agents cannot both win the same claim, because each of them writes the file
and pushes it, and the second push is rejected for being behind. The loser
reads the winner's name and picks another branch.

The **claims guard** enforces the claim in every working copy. It is a
pre-push hook that refuses a push to a branch somebody else holds, and it
ships with the head office tool. It fails open with a loud warning when the
head office is unreachable, so an outage never blocks hands-on work, and fails
closed when the pusher's identity cannot be resolved, because signing the
wrong name is worse than not pushing.

Do not confuse it with the **manifest guard**, which is a different check with
a different job: it confirms that a lane touched only the paths it was given.
In version one that one is a convention, not a hook. The orchestrator reads
the diff before assembling the work. The claims guard answers who owns a
branch, the manifest guard answers which files a lane may touch.

**A refused claim means write to whoever holds it.** It never means finding
another route to that branch. No merges into it, no rebases of it, no
pushes. That branch is somebody's live work, and working around the claim is
the exact failure the claim prevents.

Release the claim on merge.

## Commit authorship

Set the git author in each working copy to that agent's name, with a tagged
address marking it as an agent. Branch history then shows whose slice each
commit is, which is what makes assembly and review possible.

Squash-merge keeps the other end tidy: the main branch carries the change
author, so the project log stays under the owner while the branch work below
stays attributable.

## Mail, and the cursor law

Agents talk without routing every sentence through the owner. Mail does that:
a message to one agent or a broadcast to all, and an inbox each agent reads.

The trap is the read cursor. **Reading consumes.** The marker moves per name
per machine, so mail printed once is gone from every later read by a process
signing as that name there. Four rules follow.

- A watcher or a script never reads the inbox normally. It peeks, or reads the
  underlying store with a timestamp filter.
- Never read the inbox twice in one step. The second read says "empty", and
  that emptiness is not information.
- When a teammate says you have gone silent, re-show recent mail without
  moving the cursor before anything else.
- A local subagent must not register under its parent's name on the parent's
  machine, or it eats its parent's mail.

**The incident behind it:** a watcher polled the inbox every minute and threw
the output away, because it was looking for one word. An afternoon of
coordination mail was consumed and never read by anyone.

## The head office lives in a repository

Keep the coordination state in a repository, not on a machine. It then
survives a laptop closing and <FARM> going down, and it is reachable anywhere
the owner can authenticate, including a phone.

Two consequences matter. If the head office repository is public, every
message in it is public, so write mail accordingly. And if the hosting service
is down, coordination is down with it: agents commit locally and wait rather
than inventing a side channel.

## Finish loudly, because a janitor is coming

A team of agents accumulates dead working copies and stale board entries, so
something sweeps them. Assume that sweeper runs on a timer.

Only **committed and pushed** work is safe. An open change for review protects
its working copy indefinitely. Tracked but uncommitted edits buy a delay.
**Untracked scratch protects nothing**, and scratch is where an agent tends to
leave its findings.

So finish loudly. Durable output goes to the change, the issue, or the report,
never only to a working copy. Before trusting that last night's work is
there, ask the sweeper what its next pass would take.

## Adopt it in a day

1. Give every running agent a name from you, and make an identity check the
   first thing each session does.
2. Put claims on branches, even if version one is a file agents append to by
   hand.
3. Install the claims guard if you run the head office tool, so a script
   enforces the claim rather than everyone remembering it. Otherwise write the
   claim as the first line of the pull request body, where anyone can see it.
4. Set the per-agent git author in every working copy, and confirm
   squash-merge is on.
