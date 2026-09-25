# hq

hq is a small command-line tool for coding agents that all push to GitHub
under one login. It gives each agent session a name. It lets an agent claim a
branch, so that no other agent pushes to it. And it carries messages between
agents.

## Why you need it

When all your agents push with one GitHub login, git and GitHub cannot tell
them apart. Nothing stops two agents from working on the same branch at the
same time.

hq fills that gap with a **head office**: a private GitHub repository that
records who is working, who holds which branch, and who said what to whom.
Sessions and messages are GitHub issues in that repository. Branch claims are
small files on its `claims` branch.

The head office is a repository, not a server. It keeps working when any one of
your machines is off, and you can read it wherever you can use GitHub. hq does
not change how your project repositories work.

hq is part of [murmur](../README.md). murmur's installer for a farm (an
always-on Linux machine that runs agents) sets hq up, and murmur's dashboard
shows its sessions and mail. You can also use hq on its own.

A few words this page uses:

- **Session**: one running agent, or one terminal where you work by hand.
- **Claim**: a record that says "this branch belongs to this name until this
  time".
- **Owner**: the person in charge, named in the config. A claim never blocks
  the owner's pushes.

The [glossary](../docs/00-start-here.md) explains the other words murmur uses.

## What you need

- Python 3.11 or newer.
- git.
- The GitHub CLI `gh`, signed in with the login your agents use
  (`gh auth login`).
- A private GitHub repository for the head office. It can be empty.

hq has no other dependencies.

## Install

hq is not on PyPI. Install it from a clone of murmur:

```bash
git clone https://github.com/magik-ai/murmur.git
cd murmur/hq
```

Then pick one of these three ways.

**Link the clone.** This is what murmur's farm installer does.

```bash
python3 bin/hq install
```

This links `bin/hq` into `~/.local/bin`, so make sure that directory is on your
`PATH`. To upgrade, run `git pull` in the clone. This way, hq runs on the
machine's `python3`, which must be 3.11 or newer.

**Install it as a tool** with uv or pipx:

```bash
uv tool install --from . hq-cli
```

```bash
pipx install .
```

To upgrade, run `git pull`, then `uv tool install --reinstall --from . hq-cli`
or `pipx install --force .`. Without those flags, running the install command
again can leave the old code in place.

**Run it in place**, with no install:

```bash
python3 bin/hq --help
```

## Walkthrough

This takes about five minutes. You need a clone of a project repository whose
`origin` remote is on GitHub. The examples call the project
`your-org/storefront` and the head office `your-org/agent-hq-office`, the name
murmur's farm installer gives a new head office. Use your own names.

1. Create the head office. Keep it private: anyone who can read it can read
   all the mail.

   ```bash
   gh repo create your-org/agent-hq-office --private
   ```

2. Point hq at it, and name yourself as the owner:

   ```bash
   hq init --repo your-org/agent-hq-office --owner alice
   ```

   ```text
   hq configured: /home/you/.config/hq/config.toml
     repo  your-org/agent-hq-office
     owner alice
   ```

3. Start a session. hq keeps one name per session, and it tells sessions apart
   by a session key from the environment (see
   [Names and sessions](#names-and-sessions)). In a plain terminal, set one
   yourself:

   ```bash
   export HQ_SESSION_ID="terminal-$$"
   hq hello alice --task "try hq"
   hq whoami
   ```

   ```text
   hello alice: session #1 registered; identity saved for session terminal-4242
   whoami: alice  (source: session file; session terminal-4242 from HQ_SESSION_ID)
   ```

   `hq hello` opened the issue `session: alice` in the head office. `hq who`
   lists the live sessions.

4. In your project clone, make a branch and claim it:

   ```bash
   cd ~/src/storefront
   git switch -c feature/signup
   hq claim feature/signup --note "signup page"
   ```

   ```text
   claimed your-org/storefront#feature/signup for alice until 2026-10-02T09:00:00Z
   ```

   A claim lasts 24 hours unless you pass `--ttl HOURS`. `hq claims` lists all
   live claims.

5. Install the push guard in this clone. Then push as a second agent, bob:

   ```bash
   hq hook .
   HQ_AGENT=bob git push origin feature/signup
   ```

   ```text
   pre-push guard installed: /home/you/src/storefront/.git/hooks/pre-push
   hq: PUSH BLOCKED - your-org/storefront#feature/signup is claimed by alice until 2026-10-02T09:00:00Z.
       Coordinate first:  hq msg alice "..."   (or have alice run: hq release feature/signup)
   ```

   `HQ_AGENT` sets the name for one command. The guard refused bob's push, so
   git sent nothing. Your own push, as alice, goes through.

6. Send bob a message, and read it as bob:

   ```bash
   hq msg bob "feature/signup is mine until tonight"
   HQ_AGENT=bob hq inbox
   ```

   ```text
   sent to bob (inbox issue #2)
   --- 2026-10-01T09:05:00Z
   **from alice** (2026-10-01T09:05:00Z):
   feature/signup is mine until tonight

   [read cursor for 'bob' on this machine advanced to 2026-10-01T09:05:10Z; `hq inbox --recent 6` re-shows recent mail without moving it]
   ```

   Reading moved bob's read cursor, so the next `hq inbox` as bob shows nothing
   new. See [Mail](#mail).

7. Look back, then finish:

   ```bash
   hq feed
   hq release feature/signup
   hq bye
   ```

   `hq feed` prints the last 24 hours of mail, claims and sessions as one
   timeline. `hq release` gives the branch back. `hq bye` clears this
   session's name and closes its issue.

## Commands

| Command | What it does |
| --- | --- |
| `hq init --repo OWNER/NAME` | Write the config file. |
| `hq install` | Link this clone's `bin/hq` into your bin directory. |
| `hq hello NAME` | Register this session under a name. |
| `hq whoami` | Show the name hq would use, and where it came from. |
| `hq who` | List the sessions. |
| `hq bye` | End this session. |
| `hq claim BRANCH` | Claim a branch. |
| `hq release BRANCH` | Give a claim back. |
| `hq claims` | List the live claims. |
| `hq hook DIR` | Install the push guard in a clone. |
| `hq check-push REPO BRANCH` | The check the push guard runs. |
| `hq msg NAME TEXT` | Send a message. |
| `hq inbox` | Read your mail. |
| `hq feed` | Show the head office as one timeline. |

`hq --help` lists them all, and `hq COMMAND --help` shows the options of one
command. The sections below give the details.

### Sessions

**`hq hello NAME [--task TEXT]`** registers this session under NAME. hq
lowercases the name, and turns each run of characters other than letters,
digits, `.`, `_` and `-` into one `-`. It saves the name for this session on
this machine. It opens the issue `session: NAME` in the head office, or reuses
the open one, and posts a heartbeat comment on it.

Use the name the owner gave this session. A name you find in shared notes or
project memory belongs to another session. If a session with the same name was
active in the last three hours, hq warns you:

```text
hq: WARNING - a session named 'alice' was live 12 minutes ago. If that was not you, you are taking another agent's name (did it come from shared project memory?) - stop and ask the owner for YOUR codename.
```

**`hq whoami`** prints the name hq would use, where the name came from, and the
session key. It exits 1 when there is no name, or when the name comes from a
source that other sessions share (see [Names and sessions](#names-and-sessions)).
It needs no network, so run it before anything that acts under a name.

**`hq who`** lists the open session issues, most recently updated first. Each
line shows the name, `live` or `STALE`, the hours since the last update, and
the machine the session started on:

```text
alice              live  updated  0.2h ago  machine: build-box (you)
```

A session is `STALE` after three hours without an update.

**`hq bye`** ends this session. First it removes this session's name from this
machine. Then it closes the session issue with a `bye` comment. If the name
comes from a shared source, hq does not close the issue. It prints the command
that does instead: `HQ_AGENT=<name> hq bye`.

### Claims and the push guard

**`hq claim BRANCH [--repo OWNER/NAME] [--ttl HOURS] [--note TEXT]`** claims
BRANCH for this session.

- hq finds the repository from the `origin` remote of the current directory.
  It reads GitHub remotes over HTTPS or SSH, including SSH host aliases from
  `~/.ssh/config`. `--repo` names the repository instead.
- A claim lasts 24 hours unless you pass `--ttl HOURS`.
- `--note` is shown next to the claim in `hq claims`.
- Claiming a branch you already hold renews your claim.

If another name holds a live claim on the branch, hq stops:

```text
hq: your-org/storefront#feature/signup is CLAIMED by bob until 2026-10-02T09:00:00Z - talk first: hq msg bob "..."
```

Each claim is a JSON file on the `claims` branch of the head office. Its path
is `claims/<repo>/<branch>.json`, where each run of characters other than
letters, digits, `.`, `_` and `-` becomes `-`. For example:
`claims/your-org-storefront/feature-signup.json`. The first claim creates the
`claims` branch.

hq keeps its own clone of the head office in the state directory: the
**cache**. It writes each change to the claims as one commit there, and pushes
it. The push decides who got there first. When two sessions
claim the same branch at once, one push wins. The other push is rejected; hq
fetches again, sees the winner's claim, and stops with the message above.

If the push gets no answer within 30 seconds, hq cannot know whether the claim
landed, and says so:

```text
hq: the claims push did not answer within 30s - it may or may not have landed. Run `hq claims` to see which, before retrying
```

**`hq release BRANCH [--repo OWNER/NAME] [--force]`** deletes the claim. The
name that holds it, and the owner, can release it. `--force` releases a claim
that belongs to another name. An expired claim blocks nothing, so you do not
have to release it.

**`hq claims [--repo OWNER/NAME]`** lists the live claims: repository, branch,
holder, expiry and note.

**`hq hook DIR [--force]`** installs the push guard, a git `pre-push` hook, in
the clone that contains DIR. Git shares hooks between all worktrees of a
clone, so one install covers them all. Run `hq hook` again to upgrade the
guard; hq knows its own guard by the line `agent-hq pre-push guard`. hq does
not replace a `pre-push` hook that it did not write, unless you pass
`--force`:

```text
hq: /home/you/src/storefront/.git/hooks/pre-push already exists and hq did not write it - overwriting it would remove that guard without a word. Move it aside, or call hq from it, or pass --force to replace it
```

For every branch you push, the guard runs
`hq check-push -- <origin URL> <branch>`, and refuses the push when that
command fails. Some details:

- The guard looks for `hq` on your `PATH`, then at `~/.local/bin/hq`. If it
  finds neither, it lets every push through without a word.
- It checks claims for the repository that `origin` names, whichever remote
  you push to. A clone without an `origin` remote is not guarded.
- It checks the push under this session's name (see
  [Names and sessions](#names-and-sessions)).

**`hq check-push [--] REPO BRANCH`** is the check the guard runs. REPO is a
remote URL or `OWNER/NAME`. It exits 1 only when another name holds a live
claim on the branch and you are not the owner. See
[How the push guard decides](#how-the-push-guard-decides).

### Mail

**`hq msg NAME TEXT`** sends TEXT to NAME, lowercased like the names of
`hq hello`. The message is a comment on the issue `inbox: NAME` in the head
office. hq opens that issue if it does not
exist, so check the spelling: a mistyped name gets a mailbox nobody reads.
`hq msg all "..."` writes to `inbox: all`, which every session reads.

**`hq inbox [--peek] [--recent HOURS] [--all]`** shows your mail: new comments
on `inbox: <your name>` and on `inbox: all`.

A plain `hq inbox` **consumes** the mail it shows. It moves a read cursor that
is kept per name and per machine. After that, no `hq inbox` by any process
using the same name on this machine shows those messages again. When a read
shows mail, it also prints where the cursor moved to.

- `--peek` shows new mail without moving the cursor. Use it in watchers and
  scripts.
- `--recent HOURS` shows the last HOURS of mail, whatever the cursor says, and
  does not move the cursor. If someone says you missed a message, run
  `hq inbox --recent 6`.
- `--all` shows every message ever sent, with no size limit. On its own, it
  moves the cursor like a plain read.

Two limits keep the output small. The first read of a name on a machine shows
only the last 24 hours. And one read shows about 40,000 bytes at most: hq drops
the oldest messages first, and says how many it left out. It always shows the
newest message, even a longer one. `--all` lifts both limits.

Do not run a plain `hq inbox` twice in one step. The second call finds nothing.

**`hq feed [--hours HOURS]`** prints one timeline of the head office: messages,
claim changes and sessions, for the last 24 hours or the last HOURS. It is
meant for a person catching up:

```text
01 Oct 09:01  [claim] claim your-org/storefront#feature/signup by alice
01 Oct 09:05  [mail] alice -> bob: feature/signup is mine until tonight
01 Oct 09:05  [session] alice active
```

### Setup

**`hq init --repo OWNER/NAME [--owner NAME] [--bot-name NAME] [--bot-email EMAIL] [--home DIR] [--force]`**
writes the config file (see [Configuration](#configuration)). Then it reads the
file back to check it. It does not replace an existing file unless you pass
`--force`. It needs no network.

**`hq install`** links this clone's `bin/hq` into your bin directory,
`~/.local/bin` unless you set `bin_dir`. It needs no configured head office.
If you installed hq with uv or pipx, there is nothing to link, so it prints the
upgrade commands instead.

## Configuration

`hq init` writes `~/.config/hq/config.toml`, or
`$XDG_CONFIG_HOME/hq/config.toml` when `XDG_CONFIG_HOME` is set. hq reads the
file again on every command. Keys can sit at the top level or in an `[hq]`
table.

```toml
repo = "your-org/agent-hq-office"
owner = "alice"
bot_name = "hq"
bot_email = "hq@example.invalid"
# home = "~/.agent-hq"
# bin_dir = "~/.local/bin"
# clone_url_template = "https://github.com/{repo}.git"
```

| Key | Default | Variable | What it is |
| --- | --- | --- | --- |
| `repo` | none | `HQ_REPO` | The head office, as `OWNER/NAME`. Every command except `init`, `install`, `whoami`, `hook` and `check-push` needs it. |
| `owner` | nobody | `HQ_OWNER` | The person in charge. A claim never blocks this name's pushes: hq prints a note ending `owner's push allowed` instead. This name may also release any claim. |
| `bot_name` | `hq` | `HQ_BOT_NAME` | Author name of the commits on the `claims` branch. |
| `bot_email` | `hq@example.invalid` | `HQ_BOT_EMAIL` | Author email of those commits. |
| `home` | `~/.agent-hq` | `HQ_HOME` | The state directory. |
| `bin_dir` | `~/.local/bin` | none | Where `hq install` puts the link. |
| `clone_url_template` | `https://github.com/{repo}.git` | none | How hq clones the head office. `{repo}` becomes the value of `repo`. Use `git@github.com:{repo}.git` if git on this machine talks to GitHub over SSH. |

Environment variables override the file, key by key. A program that starts
agents (a spawner) can use them to configure one agent, or one command. An
empty `HQ_OWNER=` means nobody is the owner for that command.

**About `bot_email`.** hq pushes the claims commits to the head office on
GitHub, and GitHub links a commit to the account that owns its author email.
The default address uses `.invalid`, a reserved domain name that can never be
registered, so GitHub links these commits to nobody. Set your own address if
you want them linked to your account. If `bot_email` is
`hq@users.noreply.github.com`, hq uses the default instead, because that
address belongs to another GitHub login.

**Keep the head office private.** Mailboxes are issues, and messages are issue
comments. Anyone who can read the repository can read all the mail, the
sessions and the whole claims history. That includes anything an agent pastes
into a message.

### The state directory

hq keeps its local state in `~/.agent-hq`, or in the directory that `home` or
`HQ_HOME` names:

| Path | What it holds |
| --- | --- |
| `repo/` | The cache: hq's clone of the head office, for claims. hq makes it on first use. |
| `claims.index` | A scratch file that hq uses to build claims commits. |
| `identity.d/<session key>` | The name of each session on this machine. |
| `identity` | The name from the last `hq hello` on this machine. |
| `identity.session` | Which session wrote `identity`. |
| `lastread` | The `hq inbox` read cursors, one per name. |
| `presence.d/`, `presence.lock` | When this machine last sent a heartbeat for each name. |

## Names and sessions

A name belongs to a session, not to a machine. Several agents often share one
machine. If they shared one name file, the last `hq hello` would rename all the
others, and hq would sign one agent's work with another agent's name.

### The session key

hq tells sessions apart by a session key. It takes the key from the first of
these environment variables that is set:

1. `HQ_SESSION_ID`. This is hq's own variable. A spawner should set it for
   each agent it starts, to a value unique to that session, such as its own
   run ID.
2. `CLAUDE_CODE_SESSION_ID`, set by Claude Code.
3. `TERM_SESSION_ID`, set by some terminal programs.
4. `TMUX_PANE`, set by tmux.

The last three belong to other programs. The last two identify a terminal,
not an agent: two agents in one terminal pane get one key. `hq whoami` shows
which variable gave the key.

When none of the four is set, the session has no key. `hq hello` then can only
write the machine-wide name file, and hq will not act under a name from that
file. Set `HQ_SESSION_ID`, or put `HQ_AGENT=<name>` in front of each command.

### Where a name comes from

hq looks for the name in this order, and uses the first it finds:

1. `HQ_AGENT` in the environment. It sets the name for one command or one
   process.
2. `git config --worktree hq.agent`, but only when the clone has
   `extensions.worktreeConfig` turned on.
3. This session's own file, `identity.d/<session key>` in the state directory.
   `hq hello` writes it.
4. The clone-wide `git config hq.agent`.
5. The machine-wide file `identity` in the state directory, from the last
   `hq hello` on this machine. hq skips it when another session wrote it.

The first three belong to this session. The last two are shared by every
session on the machine, so a name from them may be another agent's. hq still
shows such a name in `hq whoami`, with a warning. But it will not act under
it: `hq claim`, `hq release`, `hq msg` and `hq inbox` stop with an error that
names the source, and `hq bye` does not close the session issue.

The push guard differs in two ways. It puts a name from source 2 ahead of
`HQ_AGENT`. And it uses whatever name hq finds, shared or not. When it finds no
name at all, any claim blocks the push.

Names are lowercase: `hq hello` lowercases them for you. If you set `HQ_AGENT`
yourself, use the same lowercase name.

### One name per worktree

To give each worktree of a clone its own name, turn on per-worktree config
once, then set the name in each worktree:

```bash
git config extensions.worktreeConfig true
git config --worktree hq.agent <name>
```

Without the extension, git treats `--worktree` like `--local` (or refuses it,
when the clone has linked worktrees). `--local` writes the clone-wide
`.git/config`, which every worktree of the clone shares.

### Heartbeats

`hq who` counts a session as live while its issue was updated in the last three
hours. So any command that acts under this session's own name refreshes that
issue: `hq claim`, `hq release`, `hq msg` and `hq inbox`, `--peek` included. It
does this at most once an hour per name per machine. A background process
posts the heartbeat, so the command never waits for GitHub, and never fails
because of it. A name with no open session issue gets no heartbeat: only
`hq hello` registers a session.

## How the push guard decides

`hq check-push` exits 1 for one reason only: another name holds a live claim
on the branch you push, and you are not the owner. The guard turns exit 1 into
a refused push.

In every other case, hq prints a warning and lets the push through. The rule
is simple: not knowing about a claim is not evidence of one. This happens
when:

- no head office is configured;
- the head office cannot be reached, and the cache holds no claim on the
  branch by another name;
- the config file cannot be read or parsed;
- the machine's `python3` is older than 3.11 (see below);
- hq cannot read its own arguments;
- anything else goes wrong that hq did not foresee.

A claim that hq already knows about still blocks. When the head office cannot
be reached, hq checks the cache. If the cache holds a live claim by another
name, the push is refused, and the message says the claim came from the local
cache.

**A config file hq cannot read.** hq still reads the environment. With
`HQ_REPO` set, the guard asks the head office as usual. Without it, the guard
can only check the local cache. And if your state directory is not the default,
the guard cannot know where it is: `home` is set in the broken file. hq says
so:

```text
    (a `home` set in that config file could not be read, so /home/you/.agent-hq may not be this machine's state dir; set HQ_HOME so that the push check reads the right cache)
```

Set `HQ_HOME` on any machine whose state directory is not the default. Then
the guard reads the right cache whatever happens to the file.

**An old Python.** If you linked the clone with `hq install`, or run
`python3 bin/hq`, hq runs on the machine's `python3`. If that is older than
3.11, hq cannot start. The guard then lets every push through, with this
warning each time:

```text
hq: WARNING - needs python 3.11 or newer, this is python 3.10.12 (/usr/bin/python3); run it with a newer interpreter, or install it with `uv tool install --from . hq-cli`; pushing unverified (fail-open)
```

Ubuntu 22.04, for example, ships Python 3.10. An `hq` installed with uv or pipx
uses the Python it was installed with, which is always 3.11 or newer. Check
each machine that pushes:

```bash
python3 --version
hq check-push -- "$(git remote get-url origin)" some-branch
```

When the guard works and nobody holds `some-branch`, the second command prints
nothing.

## Troubleshooting

### No head office is configured

```text
hq: no head office repo configured - run `hq init --repo owner/name` (or set HQ_REPO); config file: /home/you/.config/hq/config.toml
```

Run `hq init --repo OWNER/NAME`, or set `HQ_REPO`.

### hq will not act under your name

```text
hq: 'alice' comes from the machine file, which every session on this machine shares, so hq will not act under it. Run `hq hello <your-name>` in THIS session, or prefix the command with HQ_AGENT=<your-name>. `hq whoami` shows what hq currently thinks you are.
```

The same message can name `the clone config` instead. Two more messages mean
the same thing:

```text
hq: this machine's identity file belongs to another session (written by session 1f4c2a), so hq will not sign your work with 'alice'. Run `hq hello <your-name>` in THIS session, or prefix the command with HQ_AGENT=<your-name>.
hq: no identity - run `hq hello <name>` first (or set HQ_AGENT)
```

This session has no name of its own. Run `hq hello <name>` in this session,
with a session key set (see [The session key](#the-session-key)). Or put
`HQ_AGENT=<name>` in front of the command. `hq whoami` shows what hq sees.

If `hq hello` warns that a session with your name was live a few minutes ago,
another session may be using that name. Stop and ask the owner for your own.

### gh fails

```text
hq: `gh issue list` failed (...) - check `gh auth status` and that the head office repo exists and is visible to this login
```

The text in brackets is what `gh` said. Run `gh auth status`. Check that this
login can see the head office, and that `repo` names it correctly. If `gh` is
not installed, hq says so, and you need to install the GitHub CLI and run
`gh auth login`.

### git cannot reach the head office

```text
hq: cannot reach your-org/agent-hq-office (...) - try again
hq: WARNING - cannot reach your-org/agent-hq-office and the local cache holds no live claim by another agent for your-org/storefront#feature/signup; pushing unverified (fail-open)
```

Claims travel over git, not `gh`. hq fetches them from the URL that
`clone_url_template` gives. Check that git on this machine can fetch from that
URL. The second message means that a push went through unchecked.

### A claim did not go through

```text
hq: the claims push did not answer within 30s - it may or may not have landed. Run `hq claims` to see which, before retrying
```

Run `hq claims` to see whether your claim is there, before you try again.

```text
hq: the claims push failed twice - git said:
```

Read git's message below that line. If git rejected the push because the
`claims` branch had moved, other claims landed while hq tried: run the command
again. If git says this login may not push, give it write access to the head
office.

```text
hq: cannot build the claims commit (...) - nothing was pushed and no claim changed; the cache clone is /home/you/.agent-hq/repo
```

hq could not write to its cache. Check that the state directory is writable
and that git works. If the cache is broken, delete it: hq clones it again on
the next command.

### hq cannot tell which repository you mean

```text
hq: not inside a git repo with an origin remote - pass --repo owner/name
```

Run the command inside your project clone, or pass `--repo OWNER/NAME`. hq says
`cannot parse owner/name from origin url` when `origin` is not a GitHub
address it can read; pass `--repo` then too.

### Pushes go through with no message at all

The guard is not installed in this clone, or it cannot find `hq`, or the clone
has no `origin` remote. Check all three:

```bash
cat "$(git rev-parse --git-path hooks)/pre-push"
command -v hq || ls -l ~/.local/bin/hq
git remote get-url origin
```

### The inbox is empty, but someone sent you mail

Another process on this machine may have read it under the same name, which
moved the cursor. Or the message went to a different name.
`hq inbox --recent 6` shows the last six hours without moving the cursor. hq
only reads open issues, so do not close mailbox issues.

### A session shows STALE in hq who

Nothing updated its issue for three hours. Any claim, release, message or
inbox read under that session's own name refreshes it, at most once an hour.
So does `hq hello` with the same name.

## Development

```bash
cd hq
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q
python3 bin/hq-selftest
```

The tests use git and bash, and no network. CI runs them on Python 3.11 and
3.12 ([workflow](../.github/workflows/hq-tests.yml)).

- `src/hq/`: the package. `cli` (the commands), `config`, `identity`,
  `registry` (hello, bye, who, feed), `claims` (claims and the push guard's
  check), `hook`, `mail`, `presence` (heartbeats), `github` (the `gh` calls)
  and `util`.
- `bin/hq`: runs the clone without installing it. `hq install` links this file.
- `bin/hq-selftest`: the identity checks, with no test framework.
- `tests/`: the pytest suite.

## What hq is not

hq is not a task tracker: your issues and boards stay where they are. It is not
a chat app: `hq feed` is a log to read, not a channel to sit in. And it is not a
CI system.
