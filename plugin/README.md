# The `team` plugin

A Claude Code plugin that carries the working method of this repository into
any project: three skills for the roles an agent team needs, and two hooks
that keep a session inside the rules without anyone repeating them.

A plugin cannot ship a `CLAUDE.md`, so the laws arrive two ways instead: as
skills that load when the work matches them, and as a session-start hook that
injects the short version of the law at the top of every session. The full
text stays in the handbook under `docs/`.

## Install

From this repository, inside Claude Code:

```
/plugin marketplace add <ORG>/<REPO>
/plugin install team@agents-are-a-team
```

The marketplace file sits at the repository root, so the first command needs
nothing but the repository name. Restart the session, or start a new one, so
the session-start hook runs.

## Skills

Each skill loads on its own when the work matches the description, and can
also be called by name.

| Skill | Loads when you say | What it does |
| --- | --- | --- |
| `orchestrate` | "fan this out", "spawn lanes", "run this as a team", "split this across agents" | Splitting a batch into lanes with disjoint file manifests, identity and capacity checks before spawning, waiting for an explicit go, tracking workers through events rather than transcripts, assembling lanes into one pull request, merging only on the owner's word. |
| `night-mode` | "night mode", "unattended run", "have it done by morning", "finish this while I sleep" | Driving the current scope to a defined finish with nobody watching: a frozen scope, a heartbeat checklist, decide alone and log every contested call, three allowed resting states, one report in the morning. |
| `conductor` | "release manager", "keep the queue moving", "conductor", "ride this to production" | Owning the delivery road: queue watching that does not burn the shared API budget, the conveyor from green to deployed, ejection forensics, trains, freezes, the hold veto, and watching production after a wave. |

The three skills use `<OWNER>`, `<TRACKER>` and `<FARM>` as placeholders. Edit
them to your own names, or leave them: an agent reads them as roles.

## Hooks

### `block-generated-edits.sh` (PreToolUse)

Blocks any edit to a generated file, and tells the agent which command
regenerates it instead. It runs before `Edit`, `Write`, `MultiEdit` and
`NotebookEdit`, reads the tool input from standard input, and exits 2 with a
one-line reason when the target path matches.

It is off until a repository turns it on. **To turn it on, create
`.claude/generated-files.txt`** in that repository, one glob per line:

```
docs/contracts/openapi.json  npm run generate:api
src/clients/api/generated/*  npm run generate:api
```

Everything up to the first space is the glob. The rest of the line is the
regeneration command, shown to the agent when an edit is blocked. Blank lines
and lines starting with `#` are ignored. A glob that does not begin with `/`
or `*` matches any path ending that way, so entries can be written relative to
the repository root whatever the checkout is called.

Copy `hooks/generated-files.example.txt` as a starting point. With no such
file the hook exits 0 and says nothing, so installing the plugin never blocks
anything by surprise.

### `session-context.sh` (SessionStart)

Prints the short version of the team's laws as session context at startup,
resume, clear and compact: one batch one branch one pull request, nothing
lands on the main branch directly, claim before you touch, identity is per
session, never bypass a required check with admin rights, never merge red,
never switch off a shipped capability as a fix, the twice rule, write to a
person, and no em-dash.

A repository can replace that text wholesale: write your own short version to
`.claude/team-laws.md` and the hook injects it verbatim instead. Keep it
short. It is paid for at the start of every session.

## Layout

```
.claude-plugin/plugin.json   name, description, version
skills/orchestrate/SKILL.md
skills/night-mode/SKILL.md
skills/conductor/SKILL.md
hooks/hooks.json             both hooks, declared with ${CLAUDE_PLUGIN_ROOT}
hooks/block-generated-edits.sh
hooks/session-context.sh
hooks/generated-files.example.txt
```
