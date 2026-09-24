# The `murmur` plugin

A Claude Code plugin that carries the working method of this repository into
any project: two skills that set a repository up and check it, three skills for
the roles an agent team needs, and two hooks that keep a session inside the
rules without anyone repeating them.

A plugin cannot ship a `CLAUDE.md`, so the laws arrive two ways instead: as
skills that load when the work matches them, and as a session-start hook that
injects the short version of the law at the top of every session. The full
text stays in the handbook under `docs/`.

The agents it orchestrates are Claude Code and Codex, running on your own
machine or on a DigitalOcean Droplet (the `fleet` farm in this repository).
Those are the engines and machines murmur ships; another one is a contribution,
see `CONTRIBUTING.md` at the repository root.

## Install

From this repository, inside Claude Code:

```
/plugin marketplace add magik-ai/murmur
/plugin install murmur@murmur
```

The marketplace file sits at the repository root, so the first command needs
nothing but the repository name. Restart the session, or start a new one, so
the session-start hook runs.

## Start here

Run `/murmur:init` in the repository you want to set up. It asks seven questions, one at a time, each with a default, and writes the contract, the tracker rules, the pull request template, the lessons file and the guard list. It never overwrites a file you already have: a differing contract or tracker file is written alongside as `.murmur-new`, the pull request template, the lessons file and the guard list are left alone when they exist, and an existing `CLAUDE.md` or `AGENTS.md` gets a four-line pointer to the contract. Run it again later and it asks only what is new. Then `/murmur:doctor` checks the setup and says which optional pieces (a head office, an agent machine) are not set up yet.

## Skills

Each skill loads on its own when the work matches the description, and can
also be called by name.

| Skill | Loads when you say | What it does |
| --- | --- | --- |
| `init` | "set up murmur", "murmur init", "onboard this repo" | Seven questions with defaults, then the contract, the tracker rules, the pull request template, the lessons file and the guard list, never overwriting a file you have. |
| `doctor` | "murmur doctor", "check my setup", "is this repo set up" | A table of checks and one word for where the setup stands, naming the optional pieces (a head office, an agent machine) that are not set up yet. |
| `farm` | "murmur farm", "a farm in the cloud", "set up a farm" | From your laptop: checks doctl, your ssh key and GitHub, asks a few questions, prints the plan and the price, buys a DigitalOcean droplet only with the price typed back, installs murmur on it and opens its dashboard through a private tunnel or Tailscale. Every login is a command for your own terminal. |
| `orchestrate` | "fan this out", "spawn lanes", "run this as a team", "split this across agents" | Splitting a batch into lanes with disjoint file manifests, identity and capacity checks before spawning, waiting for an explicit go, tracking workers through events rather than transcripts, assembling lanes into one pull request, merging only on the owner's word. |
| `night-mode` | "night mode", "unattended run", "have it done by morning", "finish this while I sleep" | Driving the current scope to a defined finish with nobody watching: a frozen scope, a heartbeat checklist, decide alone and log every contested call, three allowed resting states, one report in the morning. |
| `conductor` | "release manager", "keep the queue moving", "conductor", "ride this to production" | Owning the delivery road: queue watching that does not burn the shared API budget, the conveyor from green to deployed, ejection forensics, trains, freezes, the hold veto, and watching production after a wave. |

The three role skills use `<OWNER>` for the person who owns the product.
`orchestrate` and `night-mode` also use `<TRACKER>` for wherever work is
tracked, and `night-mode` uses `<FARM>` for a machine that runs headless
workers. Edit them to your own names, or leave them: an agent reads them as
roles.

## Hooks

### `block-generated-edits.sh` (PreToolUse)

Blocks any edit to a generated file, and tells the agent which command
regenerates it instead. It runs before `Edit`, `Write`, `MultiEdit` and
`NotebookEdit`, reads the tool input from standard input, and exits 2 with a
one-line reason when the target path matches.

It is off until a repository has `.claude/generated-files.txt`, one glob per
line. `/murmur:init` writes that file from the example below, so after init the
guard is on for the example's entries: edit the file to your own generated
paths, or empty it to switch the guard off.

```
docs/contracts/openapi.json  npm run generate:api
src/clients/api/generated/*  npm run generate:api
```

Everything up to the first space is the glob. The rest of the line is the
regeneration command, shown to the agent when an edit is blocked. Blank lines
and lines starting with `#` are ignored. A glob that does not begin with `/`
or `*` matches any path ending that way, so entries can be written relative to
the repository root whatever the checkout is called.

`hooks/generated-files.example.txt` is the starting point init copies. With no
such file the hook exits 0 and says nothing, so installing the plugin alone
never blocks anything by surprise.

### `session-context.sh` (SessionStart)

Prints the short version of the team's laws as session context at startup,
resume, clear and compact: one batch one branch one pull request, nothing
lands on the main branch directly, claim before you touch, identity is per
session, never bypass a required check with admin rights, never merge red,
never switch off a shipped capability as a fix, the twice rule, and write to a
person.

A repository can replace that text wholesale: write your own short version to
`.claude/team-laws.md` and the hook injects it verbatim instead. Keep it
short. It is paid for at the start of every session.

After the laws the hook adds a second block, read from `.murmur/config.toml`:
which repository this is, which branch work merges into, where work is tracked,
whether there is a farm, and where branch claims live. The skills and the
handbook speak of `<OWNER>`, `<TRACKER>` and `<FARM>`; this block is what
turns those three words into this repository's answers, so a skill never has
to be edited per repository. Before init has run, the block says so and tells
the agent to run `/murmur:init`. A config file that cannot be read produces one
note and never a failed session.

## Layout

```
.claude-plugin/plugin.json   name, description, version
commands/init.md             the /murmur:init command
commands/doctor.md           the /murmur:doctor command
commands/farm.md             the /murmur:farm command
skills/init/SKILL.md
skills/doctor/SKILL.md
skills/farm/SKILL.md
scripts/murmur_init.py       what init runs: asks nothing itself, writes every file
scripts/murmur_doctor.py     what doctor runs: the checks and their table
scripts/murmur_farm.py       what farm runs: one step per call, one JSON answer each
lib/ -> ../fleet/lib/*       machines.py, host_presets.py, scrub.py: symlinks, so the farm
                             skill and `fleet machines` are one implementation
templates -> ../templates    the files init writes from
skills/orchestrate/SKILL.md
skills/night-mode/SKILL.md
skills/conductor/SKILL.md
hooks/hooks.json             both hooks, declared with ${CLAUDE_PLUGIN_ROOT}
hooks/block-generated-edits.sh
hooks/session-context.sh
hooks/generated-files.example.txt
```
