# The `murmur` plugin

The murmur plugin for Claude Code sets up a repository so that coding agents
can work on it as a team, and gives those agents the rules and the roles to do
it. The agents are Claude Code and Codex, running on your own machine or on a
farm: an always-on Linux machine that runs agents (the `fleet` part of this
repository).

It gives you three commands, three skills for the roles in an agent team, and
two hooks that keep every session inside the team's rules. The words used here
(lane, farm, head office and so on) are explained in
[the handbook's start page](../docs/00-start-here.md).

## Install

You need Claude Code, git and [uv](https://docs.astral.sh/uv/): the commands
run their scripts with `uv run`. GitHub's command-line tool, `gh`, is needed
for pull requests. The session-start hook runs your own `python3`, which must
be Python 3.11 or newer to read `.murmur/config.toml`.

Inside Claude Code, add this repository as a plugin marketplace and install the
plugin:

```text
/plugin marketplace add magik-ai/murmur
/plugin install murmur@murmur
```

Start a new session, so that the session-start hook runs. Then, in the
repository you want to set up:

```text
/murmur:init
/murmur:doctor
```

## Updating

Claude Code installs a new version of the plugin only when its version
number, in `.claude-plugin/plugin.json`, changes.

Auto-update is off for this marketplace unless you turn it on: run `/plugin`,
open **Marketplaces**, choose `murmur` and select **Enable auto-update**. To
update by hand, refresh the marketplace inside Claude Code:

```text
/plugin marketplace update murmur
```

Then update the plugin from its page in `/plugin`, or in your terminal:

```bash
claude plugin update murmur@murmur
```

Start a new session afterwards, so the new version loads.

## Commands

| Command | What it does |
| --- | --- |
| `/murmur:init` | Sets up the repository you are in: seven questions, then the files in [What init writes](#what-init-writes). |
| `/murmur:doctor` | Checks the setup, and prints a table and one word for where it stands. |
| `/murmur:farm` | Gets you a farm, a DigitalOcean Droplet with murmur installed, from your laptop. |

Each command runs the skill of the same name (`init`, `doctor`, `farm`). The
skills also load by themselves when you ask for the same thing in your own
words, for example "set up murmur" or "check my setup".

**init** asks its questions one at a time, each with a default. Answer `ok` to
keep a default. Run it again later, and it asks only the questions that are
new.

**doctor** ends with one of four words: `current`, `warnings`,
`setup-required` or `repaired`. It also names the optional pieces that are not
set up yet: a head office (a private GitHub repository the agents use for
names, branch claims and messages) and a separate machine for agents. `--fix`
repairs two safe things only. It makes the plugin's hook scripts executable,
and it creates `.murmur/config.toml` from the defaults when there is none.

**farm** checks doctl, your ssh key and GitHub, asks a few questions, and
shows the plan and the monthly price. It buys the Droplet only after you type
the price back. Then it installs murmur on it, and opens the farm's dashboard
through an ssh tunnel or Tailscale. Every login is a command you run in your
own terminal. What a farm is and what it costs:
[the machine](../docs/12-the-machine.md).

## Role skills

These skills load when the work matches their description. You can also call
them by name.

| Skill | Loads when you say | What it does |
| --- | --- | --- |
| `orchestrate` | "fan this out", "spawn lanes", "run this as a team", "split this across agents" | Splits work into lanes whose files do not overlap, and starts them after your go. |
| `conductor` | "release manager", "keep the queue moving", "conductor", "ride this to production" | Takes a green pull request to production. It watches the merge queue, finds out why a change was thrown out of it, and respects the `hold` label. |
| `night-mode` | "night mode", "unattended run", "have it done by morning", "finish this while I sleep" | Finishes a fixed list of work while nobody watches, and reports in the morning. |

A lane is one agent on one task, on its own branch. The orchestrator checks
identity and capacity before it starts lanes, and follows them through events
rather than transcripts. When several lanes build one change, it assembles
them into one pull request.

You decide what merges. After your yes, the conductor (or the orchestrator, if
you run no conductor) merges it. Lanes never merge.

Night mode wakes on a timer and runs the same checklist each time. It decides
alone, and writes down every decision someone could dispute. Each item ends in
production, on a preview, or blocked with a stated reason.

The role skills say `<OWNER>` for the person whose product it is, `<TRACKER>`
for wherever work is tracked, and `<FARM>` for a machine that runs agents
without a screen. You do not need to edit them: the session-start hook tells
the agent what those words mean in your repository.

## Hooks

A plugin cannot ship a `CLAUDE.md`, so the rules reach the agent in two ways:
through the skills above, and through a hook that adds the short version of
the rules at the start of every session. The full text is the handbook in
[`docs/`](../docs/).

### `block-generated-edits.sh` (before every edit)

This hook blocks edits to generated files, and tells the agent which command
regenerates the file instead. It runs before each call to Claude Code's
editing tools: `Edit`, `Write` and `NotebookEdit`. It does not see shell
commands. When the target path matches, it exits with code 2, which blocks the
edit, and prints the reason.

It is off until the repository has `.claude/generated-files.txt`, with one
glob per line:

```text
docs/contracts/openapi.json  npm run generate:api
src/clients/api/generated/*  npm run generate:api
```

Everything up to the first space is the glob. The rest of the line is the
command that regenerates the file; the agent sees it when an edit is blocked.
Blank lines and lines starting with `#` are ignored. A glob that does not begin
with `/` or `*` matches any path that ends that way, so you can write entries
relative to the repository root.

`/murmur:init` creates this file from `hooks/generated-files.example.txt`, with
four example entries. After init, edits to those example paths are blocked:
replace the entries with your own generated files, or delete them to turn the
guard off. Without the file the hook does nothing, so installing the plugin
alone never blocks an edit.

### `session-context.sh` (session start)

At startup, on resume, in a forked session, after `/clear` and after
compaction, this hook adds a short version of the team's rules to the session:

- one batch, one branch, one pull request;
- nothing lands on the main branch directly;
- claim a branch before you touch it;
- your name belongs to this session;
- never bypass a required check with admin rights;
- never merge red;
- never switch off a shipped feature as a fix;
- the twice rule: a mistake made twice is written into the rules or the
  lessons file;
- write for a person.

To use your own rules instead, write a short version to `.claude/team-laws.md`.
The hook then adds that file word for word. Keep it short: it is read at the
start of every session.

After the rules, the hook adds a second block, read from `.murmur/config.toml`:
which repository this is, which branch work merges into, where work is
tracked, whether there is a farm, and where branch claims are kept. This block
is what turns `<OWNER>`, `<TRACKER>` and `<FARM>` into this repository's
answers. Before init has run, the block says so and tells the agent to run
`/murmur:init`. If the config file cannot be read, the block says so in one
line, and the session starts normally.

## What init writes

| File | What it is | If the file already exists |
| --- | --- | --- |
| `.murmur/config.toml` | Your seven answers | Updated with your answers |
| `.murmur/contract.md` | The contract every agent in the repository follows, built from your answers | When it differs, the new version is written beside it as `contract.md.murmur-new` |
| `.claude/tracker.md` | How agents use your tracker | When it differs, the new version is written beside it as `tracker.md.murmur-new` |
| `.github/PULL_REQUEST_TEMPLATE.md` | A pull request template | Left alone |
| `docs/GOTCHAS.md` | The lessons file: symptom, cause, prevention | Left alone |
| `.claude/generated-files.txt` | The list of generated files, for the guard hook | Left alone |
| `CLAUDE.md` | Written from a template when you have none, with the contract's four sections left to the contract; it has placeholders to fill in | Four lines are added at the end, once, pointing to the contract |
| `AGENTS.md` | Not created | Four lines are added at the end, once, pointing to the contract |

Apart from `.murmur/config.toml`, which holds your answers, init never
overwrites a file you have. If `.murmur/config.toml` exists but cannot be read,
init stops and changes nothing. When two versions of a file sit side by side,
read both and keep one.

## Layout

```text
.claude-plugin/plugin.json   name, description, version
commands/                    init.md, doctor.md, farm.md: hand-overs to the skills of the same name
skills/init/SKILL.md
skills/doctor/SKILL.md
skills/farm/SKILL.md
skills/orchestrate/SKILL.md
skills/night-mode/SKILL.md
skills/conductor/SKILL.md
scripts/murmur_init.py       what init runs: asks nothing itself, writes every file
scripts/murmur_doctor.py     what doctor runs: the checks and their table
scripts/murmur_farm.py       what farm runs: one step per call, one JSON answer each
lib/                         machines.py, host_presets.py, scrub.py: symlinks to fleet/lib,
                             so the farm skill and `fleet machines` share one implementation
templates -> ../templates    the files init writes from
hooks/hooks.json             both hooks, declared with ${CLAUDE_PLUGIN_ROOT}
hooks/block-generated-edits.sh
hooks/session-context.sh
hooks/generated-files.example.txt
```

To add another agent engine or machine provider, see
[CONTRIBUTING.md](../CONTRIBUTING.md).
