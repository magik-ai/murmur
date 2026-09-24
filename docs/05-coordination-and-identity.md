# Coordination and identity

## The problem

Most setups run every agent under one GitHub login, so from the outside all the
agents look the same. That causes two failures that look unrelated but share
one cause.

The first is overwriting. Two agents work on one branch, or one reaches into
another's branch to help, and work is lost under a push nobody can attribute.

The second is mistaken identity. An agent signs a message, claims a branch or
commits under a name that belongs to another session. The board is now wrong,
and mail about one agent's work reaches another.

The fix is a small shared layer, the head office: a private GitHub repository
that records who is running, who holds which branch, and the messages between
agents. murmur's `hq` command reads and writes it; see
[`hq/README.md`](../hq/README.md) for setup. Without it, follow the same rules
in any channel your team agrees on.

A lane is one agent doing one task on its own branch. A farm is an always-on
machine that runs agents with murmur's `fleet` tool.
[The glossary](00-start-here.md#words-this-handbook-uses) has the other words.

## Naming agents

**You assign the name.** An agent never invents a name and never borrows one. A
code name found in project memory, a document or an old transcript belongs to
another session: memory is shared, names are not. An agent without a name asks
you for one. Asking shows that the session knows the rules.

**What goes wrong without it.** A new session reads a code name from shared
project memory and adopts it. Now two agents answer to one name, and mail for
either can reach the wrong one. `hq hello <name>` warns when a session with the
same name was active in the last three hours.

**One name, one mark.** Pick an emoji and an accent colour with the name, and
confirm both. A board of identical grey rows cannot be read at a glance. On a
farm, the first `fleet spawn --by <name> --icon <emoji> --color <hex>` records
them, and later spawns reuse them. To change them, run
`fleet identity <name> --icon <emoji> --color <hex>`.

## A name belongs to a session, not a machine

If the name is stored per machine, the second agent to start there renames the
first, which keeps working and signs everything with somebody else's name.

**What goes wrong without it.** A message arrives with a header naming one
agent and a body that begins "I am a different agent". Both ran on one machine,
and the latest registration won. One rule follows, useful even before your
tooling is fixed: **when a header and a body disagree, believe the body, and
say so.** The mismatch means a session somewhere is unregistered.

`hq hello <name>` stores the name keyed by the session, so a neighbour cannot
rename you. `hq whoami` prints the name hq would sign with and where it came
from, and exits with an error when that name is not this session's own. Run it
before anything that acts under a name. When hq refuses to act because the
stored name belongs to another session, it is right: run `hq hello <name>` in
this session.

## Branch claims

Claim a work branch before you create or push it, and release it when the pull
request merges:

```bash
hq claim <branch>     # before you create or push the branch
hq claims             # list the active claims
hq release <branch>   # after the pull request merges
```

A claim is a small file in the head office repository. If another agent holds a
live claim on the branch, `hq claim` refuses, names the holder and shows the
command to message them. Plain git keeps this safe without a lock server. When
two agents claim the same branch at once, the second push is rejected, hq
re-reads the claims, finds the first claim and refuses. A claim lasts 24 hours
unless you pass `--ttl <hours>`.

**A refused claim means: write to whoever holds it.** It never means finding
another route to that branch: no merges into it, no rebases of it, no pushes to
it. That branch is somebody's live work, and working around the claim is the
exact failure claims prevent.

The **claims guard** is a pre-push hook that refuses a push to a branch someone
else holds. Install it in each worktree with `hq hook <dir>`. On a farm,
`fleet spawn` installs it in every lane when `hq` is installed. It behaves like
this:

- When the head office cannot be reached, it checks the claims it already has
  on disk. A claim it knows about still blocks the push. Otherwise the push goes
  through with a warning, so an outage never blocks your work.
- When it cannot tell who is pushing, it treats the pusher as a stranger, so
  any live claim on the branch blocks the push.
- The owner named in hq's settings (`hq init --owner <name>`) is told about the
  claim but not blocked. Leave that setting empty for a team.

Do not confuse it with the **manifest guard**, which checks that a lane changed
only the paths it was given. For lanes a farm runs as a group
(`fleet group start`), a pre-push hook enforces it. Everywhere else, the
orchestrator (the agent coordinating the lanes) compares each lane's diff with
its paths before assembly.

## Commit authorship

Set the git author in each worktree to the agent's name, with an address that
marks it as an agent. The branch history then shows whose slice each commit is,
which makes assembly and review possible. Set it for the worktree only, because
plain `git config` changes every worktree of the clone:

```bash
git config extensions.worktreeConfig true
git config --worktree user.name "<name> (agent)"
git config --worktree user.email "<name>@agents.local"
```

On a farm, `fleet spawn` does this for every lane, with those shapes as the
defaults; the `[identity]` table in `~/.config/fleet/policy.toml` changes them.
Squash-merge then keeps `main` tidy: each pull request lands as one commit, and
the per-agent commits stay visible in the pull request.

## Mail, and why reading it consumes it

Agents talk to each other without routing every sentence through you:

```bash
hq msg <name> "<text>"   # to one agent
hq msg all "<text>"      # to every agent
hq inbox                 # your unread mail
```

The trap is the read cursor. **Reading consumes.** `hq inbox` moves a marker
that is kept per name, per machine. Mail it has printed once is gone from every
later read by any process signing as that name on that machine. Four rules
follow:

- A watcher or a script never reads the inbox normally. It uses
  `hq inbox --peek`, which shows unread mail without moving the cursor.
- Never read the inbox twice in one step. The second read says "empty", and
  that tells you nothing.
- When a teammate says you have gone quiet, first re-show recent mail without
  moving the cursor: `hq inbox --recent 6` shows the last six hours.
- A local subagent must not register under its parent's name on the parent's
  machine, or it eats its parent's mail.

**What goes wrong without it.** A watcher polls the inbox every minute and
throws the output away, because it is looking for one word. An afternoon of
coordination mail is consumed, and nobody reads it.

## The head office lives in a repository

Keep the coordination state in a repository, not on a machine. It then
survives your laptop closing and the farm going down, and you can reach it
wherever you can sign in to GitHub, including on a phone.

Two consequences follow. A public head office makes every message public, so
keep it private. And if GitHub is down, coordination is down too: agents commit
locally and wait, rather than inventing a side channel.

## Push your work before the sweep removes it

A team of agents leaves dead worktrees and stale board entries behind, so
something sweeps them away on a timer. On a farm, `fleet sweep` runs every ten
minutes by default.

Only **committed and pushed** work is safe. The sweep never touches a running
lane, and it keeps a worktree while its pull request is open. Once a lane has
finished, its worktree is removed, unless it holds uncommitted changes. Those
keep it only until someone runs `fleet sweep --force`, which saves a snapshot
and then removes it.

So put lasting output in the pull request, the issue or the report, never only
in a worktree. Before you trust that last night's work is still there, ask
what the next pass would remove with `fleet sweep --dry-run`. The full rules
are in [`fleet/docs/SWEEP.md`](../fleet/docs/SWEEP.md).

## Adopt it in a day

1. Give every running agent a name yourself, and make an identity check
   (`hq whoami`) the first thing each session does.
2. Put claims on branches, even if the first version is a file that agents
   append to by hand.
3. With the head office, install the claims guard (`hq hook <dir>`), so a
   script enforces claims instead of everyone remembering them. Without it,
   record each claim where everyone can see it, before the first push.
4. Set the per-agent git author in every worktree, and confirm squash-merge is
   turned on.
5. For the rules your agents follow in every repository, start from
   [`templates/personal-CLAUDE.md`](../templates/personal-CLAUDE.md).
