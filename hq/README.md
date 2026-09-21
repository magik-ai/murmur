# agent-hq

`hq` is a coordination layer for a fleet of coding agents that all push with
one GitHub authorization. One GitHub login means git cannot tell your agents
apart, and nothing in GitHub stops two of them from working the same branch at
the same time. `hq` is the missing piece: a **head office** repo that holds who
is live, who owns which branch, and who said what to whom.

The head office is a GitHub repo, not a host, so it survives any single machine
(laptop asleep, build box down) and is reachable from anywhere your `gh` auth
works, including a phone browser. It coordinates work in OTHER repositories;
nothing here changes any target repo's own workflow.

One CLI, no runtime dependencies. It needs `python` 3.11 or newer, `git` and
`gh`, because those are the three things that still work on a machine where
nothing else does. 3.11 is the floor because the config file is read with the
standard library's `tomllib`; the alternative was a second, hand-written parser
that disagreed with `tomllib` about malformed input, so the same config file
failed open on one python and blocked every push on another.

## Install

From a clone, which is the only way that works today:

```sh
git clone https://github.com/<your-org>/agent-hq.git
cd agent-hq
uv tool install --from . hq-cli     # or: pipx install .
```

Or run it in place, with no install at all:

```sh
python3 bin/hq --help
```

That path runs on whatever `python3` the machine has, so it checks the version
before it imports anything: an older interpreter gets one line naming the
requirement instead of a traceback about a missing `tomllib`, and `check-push`
there warns and lets the push through rather than freezing every push on the
machine behind a stack trace. Which also means an older interpreter has no push
gate at all: see [Check the interpreter](#check-the-interpreter-before-you-trust-the-gate).

> Not on PyPI yet. When it is published, `uv tool install hq-cli` and
> `pipx install hq-cli` will be the one-line install; until then the name
> resolves to nothing, so use the clone above.

`bin/hq` is a thin wrapper over the `hq` package in `src/`. `hq install`
symlinks it from THIS clone into your bin dir, so `git pull` here is the
upgrade with no reinstall step. It links and nothing else: it needs no
configured head office, and it never assumes your head office repo contains a
copy of hq. The cache clone of the office is made lazily, by the first command
that actually reads the office, on whatever branch that repo calls default.

## Configure

Nothing in the source names an organisation. Point `hq` at your own head
office once:

```sh
hq init --repo your-org/agent-hq --owner alice
```

That writes `${XDG_CONFIG_HOME:-~/.config}/hq/config.toml`:

```toml
repo = "your-org/agent-hq"
owner = "alice"                  # the sovereign; empty means nobody is
bot_name = "hq"                  # author of claims commits
bot_email = "hq@users.noreply.github.com"
# home = "~/.agent-hq"           # state and the cache clone
# bin_dir = "~/.local/bin"       # where `hq install` links the CLI
# clone_url_template = "https://github.com/{repo}.git"
```

`repo` is the head office. `owner` is the one human who works hands-on: claims
warn them rather than blocking them. Leave `owner` empty and nobody has that
power, which is the right default for a team.

The environment overrides the file, key by key, for a spawner that configures
one lane or one command inline:

| variable | overrides |
| --- | --- |
| `HQ_REPO` | `repo` |
| `HQ_OWNER` | `owner` |
| `HQ_BOT_NAME` | `bot_name` |
| `HQ_BOT_EMAIL` | `bot_email` |
| `HQ_HOME` | `home` |

With neither set, every command that needs the repo stops with one line telling
you to run `hq init`. The exception is `check-push`, the push gate: an
unconfigured `hq` knows of no claim, so it warns and lets the push through,
exactly as it does when the network is down. A hook that outlived its config
must not block every push in the repo.

**A public head office makes every message public.** Mailboxes are issues and
messages are issue comments, so anyone who can read the repo can read the mail,
the session registry and the full claims history, including whatever your
agents paste into a message while debugging. Use a private repository for your
head office unless you actually want an audit trail the world can read.

## Concepts

- **Session registry.** Every agent session, interactive or headless, says
  `hq hello <name>` when it starts. Names are ASSIGNED by the owner, never
  invented and never borrowed: a codename is per SESSION, so one found in
  shared project memory belongs to ANOTHER agent. That happened on day one,
  when a fresh session adopted a name it read in memory. Valid sources are only
  the owner in the CURRENT conversation, or the spawner-set
  `git config hq.agent` / `HQ_AGENT` of a dedicated worktree. An agent without
  a name from one of those must ask the owner, and asking is the handshake that
  proves it knows this protocol. `hq hello` warns when a same-named session was
  live minutes ago. Live sessions are open issues labelled `session`; a session
  that stops heartbeating goes stale by `updated_at`.

- **Branch claims.** Before working on a branch, an agent runs
  `hq claim <branch>`. Claims are JSON files on the `claims` branch of the head
  office repo, and git push is the compare-and-swap: two agents claiming at
  once cannot both win, because the second push is rejected and the loser is
  shown the owner. A pre-push hook in each worktree refuses a push to a branch
  claimed by someone else.

- **Messages.** `hq msg <agent> "text"` comments on that agent's inbox issue
  (label `inbox`); `hq inbox` reads yours. Broadcast goes to the issue titled
  `inbox: all`.

- **Identity.** The commit AUTHOR on work branches is
  `<agent> (agent) <you+<agent>@example.com>`. Squash-merge makes the permanent
  main-history author the PR author, so the target repo's history stays clean
  while branch work stays attributable.

## Identity, the hard part

Four incidents, all the same shape: `hq` signed one agent's work with another
agent's name. Each fix is in `tests/test_identity.py`, and each is a rule worth
stealing even if you never run this tool.

Resolution order, everywhere (CLI and hook): `HQ_AGENT` env, then a genuinely
worktree-scoped `git config --worktree hq.agent`, then **this session's own
file** (`<home>/identity.d/<session>`), then the clone-wide `git config
hq.agent`, and last the machine-wide `<home>/identity`.

**A name belongs to a session, not to a machine.** `hq hello` writes a file
keyed by this session's key, so a second `hq hello` on the same machine no
longer renames every other live session. The machine-wide file survives for
callers that export no session key at all, and `hq` reads it only when it is
not demonstrably somebody else's: it records which session wrote it, and a
different session gets a refusal instead of a wrong signature.

```
hq: this machine's identity file belongs to another session (written by
session 1f4c...), so hq will not sign your work with 'alice'.
Run `hq hello <your-name>` in THIS session, or prefix with HQ_AGENT=<name>.
```

This is why mail once arrived headed `from alice` while its body said "I'm
bob": both ran on one machine, and the last `hello` won. Failing loudly beats
signing another agent's name, including in the pre-push guard, where an
unresolvable identity blocks the push rather than mistaking someone else's
claimed branch for its own.

**A spawner must export `HQ_SESSION_ID`.** That is the contract, and the only
variable in the list that `hq` owns. `hq` reads, in order, `HQ_SESSION_ID`,
`CLAUDE_CODE_SESSION_ID`, `TERM_SESSION_ID`, `TMUX_PANE`, and the last three
belong to somebody else. `CLAUDE_CODE_SESSION_ID` is not a documented interface
of that runtime: it works today and may be renamed tomorrow without warning,
and the day it goes away every agent silently drops to a terminal id or to no
key at all. `TERM_SESSION_ID` and `TMUX_PANE` identify a terminal, not a
session, so two agents sharing one pane look like one agent. Set
`HQ_SESSION_ID` to anything stable and unique per session, ideally the
spawner's own run id, and none of that can reach you.

**Check your identity before you act.** `hq whoami` prints the name `hq` would
sign with, the source it came from and which variable supplied the session key,
and it exits 1 when that name is not this session's own. It is offline and
instant, so make it the step before any action that writes under a name.

**Only three sources belong to this session:** `HQ_AGENT`, a truly
worktree-scoped `git config --worktree hq.agent`, and this session's own file.
The clone-wide `git config hq.agent` and the machine-wide file are shared with
every other session on the machine, so they answer reads but `hq` REFUSES to
act on them: `claim`, `release`, `msg`, `inbox` and the office half of `bye` all
stop with an error naming the source. The hole this closes was found on
2026-09-16: a session that
had just run `hq bye` lost its own file, fell through to shared state, and its
next `hq bye` closed a different live agent's session.

`hq bye` does its local cleanup first, before anything that needs the head
office and before the identity rule above, so a machine that was never
configured cannot keep a name whose session has ended. Removing a local file
signs nothing, so it does not need a name `hq` may act under. It removes both
files `hq hello` wrote, the session one and the machine-wide one, and only when
they still name this session: the machine-wide file is shared, so another
agent's name there is not this goodbye's to take. On a machine that exports no
session id there is nowhere to write but that shared file, which is why a
keyless `hq bye` clears it and then says the registry issue is still open,
naming the one command that closes it: `HQ_AGENT=<name> hq bye`. A config file
`hq` cannot read does not stop that cleanup either: where the state dir is
comes from `HQ_HOME` or the default, so the files go and the broken config is
the exit line.

**`git config hq.agent` is not per-worktree** unless
`extensions.worktreeConfig` is enabled. Plain `git config` writes `.git/config`,
which every linked worktree of the clone shares, and git documents `--worktree`
as a synonym for `--local` while that extension is off. One lane setting it
therefore renamed every agent working anywhere in that clone: the second shape
of the same bug, and the reason it kept coming back after the identity file
took the blame. Measured on a shared checkout carrying `hq.agent = alice`, a
session that had said `hq hello bob` still resolved to alice in every worktree
of that clone. `hq` now trusts `--worktree` only with the extension on, a
session that said hello outranks the clone-wide value, and the pre-push hook
forces only a genuinely worktree-scoped name. Give a lane its own name with
`git config extensions.worktreeConfig true && git config --worktree hq.agent <name>`,
or simply say `hq hello` in the session.

## Reading mail consumes it

`hq inbox` moves a read cursor that is per **name** per **machine**. The mail it
prints is gone from every later `hq inbox` by any process signing as that name
on that machine. Two agents lost an afternoon of mail this way (2026-09-14): a
watcher polled `hq inbox` and discarded the output, and a second call in the
same step read "inbox empty".

- Watchers and scripts use `hq inbox --peek` (no cursor move) or read the
  mailbox issue directly
  (`gh api repos/<org>/<repo>/issues/<n>/comments?since=<ts>`).
- Never call `hq inbox` twice in one step.
- When a teammate says you are silent: `hq inbox --recent 6` re-shows the last
  six hours without moving the cursor.
- A plain read prints where the cursor moved to, so the consumption is never
  silent.

Two limits keep a mailbox readable. A name nobody has read as before is a NEW
session with no backlog to catch up on, so a first read shows the last 24 hours
rather than every broadcast ever sent: unbounded, that was 191 KB one loud
night, past the 128 KB a single argv string holds, and spawners that inline
mail into a prompt refused to start lanes. And a single read is capped at 40 KB,
dropping from the OLD end, because the newest mail is the mail that still
changes what you do. Truncation always says so, and `hq inbox --all` lifts both.

## The push gate

`hq hook <dir>` installs a pre-push guard in a worktree. It asks
`hq check-push` before every push and refuses a branch claimed by someone else.

Re-running it upgrades an older hq guard in place, which is how a worktree picks
up a fixed one. A `pre-push` hook hq did not write is never replaced silently -
it is somebody's guard, and losing one surfaces months later as a check that
quietly stopped running - so hq refuses in one line and `--force` overrides.

Fail-open is for NOT KNOWING. When the head office is unreachable and the local
cache holds no claim for the branch, the push goes through with a loud warning,
because offline hands-on work must never be blocked by an absence of
information. But a claim already in the cache IS knowing: it is positive
evidence that the branch belongs to someone else, and an outage does not make it
less true, so that push is refused. The guard used to wave exactly those pushes
through, which is the one case it exists for.

**Exit 1 means one thing: a live claim by somebody else.** The hook reads any
non-zero exit as a refused push, so everything else `check-push` might hit is a
warning and an open gate: a config file it cannot read, an interpreter too old
to start on, an unreachable office, an argument it cannot parse, or anything
nobody foresaw. A gate that could not run knows of no claim, and not knowing is
never evidence of one. That is also why the hook passes the branch name after
`--`: `refs/heads/-weird` is a ref git pushes like any other, and without the
separator the CLI read it as an option and refused the push.

### A config file the gate cannot read

The same rule applies to a broken `config.toml`: the gate warns and does not
refuse the push, because a stray character in a config file is not evidence of a
claim, and a gate that dies on one freezes every push on the machine.

Two things still hold on that machine, and both are worth knowing:

- **The environment carries the gate past the broken file.** `HQ_REPO` is read
  whatever the file does, so with it set the office is still asked and a live
  claim still blocks. Set it in the spawner and an unreadable file costs you
  nothing.
- **Otherwise the gate falls back to the local claims cache**, and a claim
  already on disk still blocks: a config hq cannot parse is not permission. But
  `home` is a config file key, so if that file is where your state dir was named,
  hq cannot honour it and searches `~/.agent-hq` instead. It says so rather than
  reporting that empty directory as an absence of claims:

```
hq: the local cache under /home/a/.agent-hq holds no live claim by another
    agent for acme/thing#lane either; pushing unverified (fail-open)
    (a `home` set in that config file could not be read, so
    /home/a/.agent-hq may not be this machine's state dir; set HQ_HOME if the
    gate is to be sure it read the right cache)
```

On a machine that never had a default state dir, that line says
`/home/a/.agent-hq, which does not exist, may not be this machine's state dir`,
which settles it: a directory hq never created holds no cache, so the silence
above is not an answer about that branch at all.

Set `HQ_HOME` on any machine whose state dir is not the default and the gate
reads the right cache no matter what happens to the file.

### Check the interpreter before you trust the gate

**A machine whose `python3` is older than 3.11 has no push gate.** hq will not
run there, and by the rule above a gate that could not run knows of no claim, so
`check-push` warns and lets the push through. That is not a one-off warning
somebody acknowledges once: it happens on EVERY push on that machine, for as
long as that interpreter is the one the hook finds, and the pushes it waves
through include pushes to branches another agent has claimed.

This is a deliberate trade. Two TOML parsers disagreed about malformed input, so
the same config file failed open on one python and blocked every push on
another; one parser is worth more than two supported versions. The cost is that
the floor is now a deployment requirement rather than a nicety, and it is easy
to miss: **Ubuntu 22.04 LTS ships python 3.10**, and so do plenty of build
images and long-lived VMs.

So before you rely on the guard, check the interpreter on every machine that
pushes:

```sh
python3 --version                     # 3.11 or newer, or that machine is ungated
hq check-push -- "$(git remote get-url origin)" some-branch
```

The second line tells you which state the machine is in. On an older python it
answers with the warning below and exits 0, which is exactly what it will do for
every real push on that machine:

```
hq: WARNING - needs python 3.11 or newer, this is python 3.10.20 (...);
run it with a newer interpreter, or install it with
`uv tool install --from . hq-cli`; pushing unverified (fail-open)
```

## Layout

- `src/hq/` : the CLI, split by what it coordinates. `config` (where hq is
  pointed), `identity` (who this session is), `claims` (the compare-and-swap
  branch and its push gate), `mail`, `registry`, `github`, `hook`, `cli`.
- `bin/hq` : thin wrapper, for running a clone with no install at all, and the
  file `hq install` symlinks into your bin dir. It is THIS clone's wrapper, not
  a copy of hq inside the head office: installing hq and caching the office are
  two different jobs.
- `tests/` : pytest, no network. `pytest` runs them; CI runs them on 3.11 and
  3.12.
- `claims` branch : `claims/<repo>/<branch-slug>.json`, one file per claim.
- Issues : `session: <name>` (registry), `inbox: <name>` (mailboxes).

## Commands

```
hq init --repo O/N [--owner NAME]  write the config file
hq install                         symlink this clone's bin/hq into the bin dir
hq hello NAME [--task T]           register this session
hq bye                             close this session's registry issue
hq who                             list live sessions
hq whoami                          the name hq would sign with, and where it came from
hq claim BRANCH [--repo O/N] [--ttl H] [--note T]
hq release BRANCH [--repo O/N] [--force]
hq claims [--repo O/N]             list active claims
hq feed [--hours H]                the whole office as one timeline
hq msg NAME TEXT                   message an agent ('all' broadcasts)
hq inbox [--peek] [--recent H] [--all]
hq hook DIR [--force]              install the pre-push guard (--force
                                   replaces a hook hq did not write)
hq check-push REPO BRANCH          used by the hook; exit 1 = blocked
```

## Non-goals

Not a CI system. Not a task board: the issues in your target repos remain the
board. Not a chat product: the feed is a timeline, not a channel to sit in.

## Development

```sh
pip install -e ".[test]"   # python 3.11 or newer
pytest
```
