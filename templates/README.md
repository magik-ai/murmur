# Templates

Fill-in files for your own repository. Copy the ones you need, replace every
`<PLACEHOLDER>`, and delete the parts you will not use. Keep only the rules you
will enforce: a rule nobody enforces teaches agents that rules are optional.

If you use the murmur plugin, `/murmur:init` copies the main files for you. See
[What /murmur:init copies](#what-murmurinit-copies) below.

## The files

| File | What it is for | When to use it |
|---|---|---|
| [`CLAUDE.md`](CLAUDE.md) | The law file: how work happens in your repository. Read order, the ten workflow steps, commit format, hard rules. | Day one. Copy it to your repository root. |
| [`personal-CLAUDE.md`](personal-CLAUDE.md) | Your own rules for every agent session, in every repository: names, branch claims, mail, production access, how to write to you. | When you run agents in more than one repository, or more than one agent at a time. Copy it to `~/.claude/CLAUDE.md`. |
| [`AGENTS.md`](AGENTS.md) | A product briefing for agents: vocabulary, the main user journey, customers. It gives the headings; you write the content. Codex reads this file, so it also points to the law file. | When agents keep misreading the product, or when you use Codex. |
| [`PULL_REQUEST_TEMPLATE.md`](PULL_REQUEST_TEMPLATE.md) | The pull request body: summary, how to check the change, a checklist. | Day one. Copy it to `.github/PULL_REQUEST_TEMPLATE.md`. |
| [`GOTCHAS.md`](GOTCHAS.md) | The lessons file. One entry per surprise: symptom, cause, prevention. | Day one. Copy it to `docs/GOTCHAS.md`. |
| [`knowledge/README.md`](knowledge/README.md), [`knowledge/_domain.md`](knowledge/_domain.md) | One knowledge file per domain: how a subsystem really behaves, measured numbers, how to debug it. | When the same subsystem keeps costing you time. |
| [`RELEASE_NOTES.d/README.md`](RELEASE_NOTES.d/README.md) | Release notes as one small file per change, so parallel pull requests never conflict on one list. | When users need to know what changed. |
| [`memory/MEMORY.md`](memory/MEMORY.md), [`memory/_fact.md`](memory/_fact.md) | An agent's memory directory: an index of one-line claims, and one fact per file. | When an agent's memory grows past a screen. |
| [`memory/sample/`](memory/sample/MEMORY.md) | A made-up memory directory, filled in, to show the shape. | Read it once before you start your own. |
| [`briefs/lane.md`](briefs/lane.md) | The brief for one agent doing one task on its own branch (a lane). | Each time you hand a task to a worker agent. |
| [`briefs/review.md`](briefs/review.md) | The brief for an adversarial reviewer: a second agent whose only job is to find what is wrong with one exact commit. | Before every merge. |
| [`briefs/night-mode.md`](briefs/night-mode.md) | The brief for an unattended run: the scope, the target for each item, the limits. | When agents work while nobody watches. |
| [`trackers/`](trackers/README.md) | How agents take a task, link a pull request and post evidence in your tracker: GitHub Issues, Linear, Jira, Notion, or no tracker. | Day one. Copy the one you use to `.claude/tracker.md`. |
| [`hooks/`](hooks/) | A guard that stops agents from editing generated files by hand, with its path list and its registration. | When a generated file (a client, a schema, a lock file) gets edited by hand. |
| [`scripts/next_number.sh`](scripts/next_number.sh) | Prints the next free number for decision records and migrations, checking `main` and every open pull request. | When two lanes might create numbered files at the same time. |
| [`github/hold-check.yml`](github/hold-check.yml) | A GitHub Actions check that fails while a pull request has the `hold` label. | When you start using the `hold` label. Copy it to `.github/workflows/` and make its check required. |

## What /murmur:init copies

`/murmur:init` asks seven questions, stores your answers in
`.murmur/config.toml`, then writes these files. It never replaces any other
file you already have: the last column says what it does instead.

| Template | Written to | If that file already exists |
|---|---|---|
| `CLAUDE.md`, sections 0, 2, 3 and 7, under your answers | `.murmur/contract.md` | A differing version is written beside it, as `.murmur-new` |
| `CLAUDE.md`, with repository, product and tracker filled in, and sections 0, 2, 3 and 7 each replaced by a line pointing to the contract | `CLAUDE.md`, only when you have none | Your file is kept, and four lines pointing to the contract are added at its end |
| `trackers/<your tracker>.md` | `.claude/tracker.md` | A differing version is written beside it, as `.murmur-new` |
| `PULL_REQUEST_TEMPLATE.md` | `.github/PULL_REQUEST_TEMPLATE.md` | Left as it is |
| `GOTCHAS.md` | `docs/GOTCHAS.md` | Left as it is |
| The plugin's copy of `hooks/generated-files.example.txt` | `.claude/generated-files.txt` | Left as it is |

If you have an `AGENTS.md`, the same four lines are added to it. The other
templates are for you to copy by hand when you need them.

## Placeholders that can stay

Most placeholders are blanks for you to fill. Three of them name roles instead:
`<OWNER>` (the person whose product it is), `<TRACKER>` (where work is tracked)
and `<FARM>` (an always-on machine that runs agents, if you have one). You can
leave these in. With the plugin installed, a hook tells every agent at the start
of each session what they mean in your repository. It reads your answers from
`.murmur/config.toml`. Before `/murmur:init` has run, `<OWNER>` is the person
who gave the agent its name, `<TRACKER>` is the pull request itself, and there
is no `<FARM>`.

## The generated-file guard without the plugin

The plugin registers this guard for you. Without the plugin, set it up by hand:

1. Copy `hooks/block-generated-edits.sh` to
   `.claude/hooks/block-generated-edits.sh` in your repository.
2. Copy `hooks/generated-files.example.txt` to `.claude/generated-files.txt`,
   and list your generated paths in it, each with the command that regenerates
   it.
3. Copy `hooks/settings.json` to `.claude/settings.json`, or add its `hooks`
   block to the settings file you already have.

The script is the same file the plugin ships. Use the plugin or this copy, not
both. With no list file, the guard blocks nothing. `.claude/settings.json` is
committed, so the guard applies to every agent and every person who opens the
repository. The `matcher` names Claude Code's editing tools. It does not cover
shell commands, so a command such as `sed -i` can still change a generated
file. The
[safety hooks chapter](../docs/11-safety-hooks.md) explains the guard in full.
