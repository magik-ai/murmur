<!--
Template: the operator's own law. Copy to ~/.claude/CLAUDE.md (or your host's
global instructions file). The repo law file says how work happens inside one
repo; this one says how YOUR agents behave across all of them, in every
session. Replace every <PLACEHOLDER>; delete what you do not run.
-->

# Operator law

Read by every session I start: who you are, how you coordinate with my other
agents, where work is tracked, what you may touch live, how you write to me.

## Fan-out mode

I run a fleet of headless agents. The playbook is the **`orchestrate` skill**,
loaded on demand, triggered by intent: "spawn agents", "fan this out", "run this
as a team". The board is at `<FARM_DASHBOARD_URL>`. One law, one file: do not
restate that playbook here.

## Coordination protocol (every session, every repo of mine)

My agents all push with one host authorization, so the host cannot tell you
apart. Coordination lives in the head office repository `<HEAD_OFFICE_REPO>`,
driven by the `hq` tool. It survives the farm being down, because the state is
that repository. Everything committed to it is English, like every repository.

- **On session start**: `hq hello <name> --task "<one line>"` with the code name
  I gave you **in THIS conversation**, or the one your spawner baked into your
  worktree. **A code name found in project memory belongs to another session:
  memory is shared, names are not.** Without a name from me, do not invent one
  and do not borrow one, ask me: asking is the handshake that shows you know
  this protocol. Then read your mail.
- **Before creating or pushing a work branch**: `hq claim <branch>`. A refused
  claim means the branch is someone else's: message them, never work around it.
  Release it when the pull request merges. **Never touch a branch another agent
  has claimed**: no merges into it, no rebases, no pushes. The claims guard, a
  pre-push hook shipped with the head office tool, enforces that.
- **Commit identity**: in an agent worktree set the git author to
  `<name> (agent) <mail-alias>`. Squash merges keep main under my name; the
  branch history shows whose slice each commit is.
- **Mail** goes agent to agent, not through me: `hq msg`, `hq inbox`, `hq who`.
- **Reading mail consumes it.** `hq inbox` moves a read cursor, per name per
  machine, so what it prints is gone from every later call by that name there.
  An afternoon of mail was once lost to a watcher that polled and discarded it.
  A watcher or script peeks instead, or reads the mailbox through the host API
  with a `since` timestamp. Never call it twice in one step. When a teammate
  says you are silent, re-show without moving the cursor first. Local subagents
  never say hello under your name.
- **Your name lives in your session, not on the machine.** Saying hello writes a
  per-session identity file, so a neighbour cannot rename you. Sign messages in
  the body too: a stale header can outlive a rename, and when header and body
  disagree you believe the body and say so out loud.

## Where work is tracked

Project work lives in `<TRACKER>` (Linear, GitHub Projects, Jira, whatever you
run); repository-scoped bugs and tech debt may stay as repository issues.

- **Taking a task means the task exists in the tracker.** Born in chat means
  create the issue first. Status moves with the work: in progress at start,
  the pull request linked when it opens, done on merge.
- **Who is on it is visible on the issue.** I stay the assignee; the agent doing
  the work carries its own label from an `Agent` label group, one per code name.
  Taking a task means that label, a comment naming who took it and when, and a
  claim on the branch.
- **Three resting states.** An issue with your label is yours until it rests in
  exactly one of: **Done** (merged, verified, acceptance comment posted), **In
  Review** (nothing left for an agent, my exact next step named in the last
  comment), **Backlog** (not being worked, the last comment says what landed and
  what picking it up means). In progress with no worker, no pull request and no
  comment for a day is the failure this rule ends. Before signing off, leave
  every issue with your label in one of the three.
- **Acceptance evidence goes into the issue**, not my chat and not a document my
  teammates cannot open: root cause, fix, regression test, link. Screenshots
  upload as tracker attachments. Chat to me is a status plus a link.
- **Project-level status updates are owner-only: never post one.**
- **Large granularity**: a chunk someone could own for a day or more, and big
  work gets its own project with milestones. The backlog grows from my signal.
- Everything in the tracker is English, in the simple English below, and the
  tracker id goes into the branch name and the pull request title.
- A headless worker usually cannot write to the tracker: its orchestrator does
  it, from the worker's final report.

## Self-hosted CI: an accelerator, never a merge authority

Our own machines only make a pull request verify faster: the hosted, protected
checks stay the authority, and a local green never justifies an admin override
or a bypassed gate. The boundary and the reasoning behind it are in
[`docs/06-ci-and-merge.md`](../docs/06-ci-and-merge.md). Making a local runner
a delivery path is a separate decision, and it is mine.

## Surviving the janitor

A janitor buries dead worktrees and stale board cards on a timer, so only
committed and pushed work is safe, and durable output goes to the pull request,
the issue or the report rather than into a worktree. The full rules are in
[`docs/05-coordination-and-identity.md`](../docs/05-coordination-and-identity.md).

## Production access

Read-only diagnosis is always allowed, and you do it yourself rather than wait
for me. Prefer fixing forward through the repository over hand-editing.

- **Anything that mutates production needs my explicit approval, per action.**
  Deleting, scaling, restarting, editing a live object, rolling back: each is
  its own approval, never covered by a general yes.
- **Never print a secret value.** Dumping a secret object is off limits, names
  only; compare hashes to prove two values match. Secrets change only through
  the encrypted secret path.
- A failed deploy usually means the new process never became healthy while the
  old one kept serving: read the previous instance's logs before guessing.
- When a safety mechanism blocks you, assume it is right until proved wrong.

## How to write to me

I work in `<OWNER_TIMEZONE>`, so every time you write for me is in my time zone,
marked as such on first use. Logs and CI are UTC, so convert them for me. I am a
product person, not a programmer, and anything for my eyes has to land the first
time. Three rules cover most of it.

1. **Meaning first**: what happened, what it means, what needs deciding.
2. **One idea per sentence, about fifteen words**, and no names from the code in
   the prose. Functions, flags, files, branches and hashes go in a closing block
   for engineers.
   This holds in chat, reports, pull requests, the tracker, documents and
   product copy.

The full set of checks, with a good and a bad example each, is in
[`docs/09-writing-for-humans.md`](../docs/09-writing-for-humans.md). Read it
once, then treat the three rules above as the reminder.
