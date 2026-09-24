# Safety hooks

A rule that an agent must remember holds until the session gets long, the
task gets urgent, or the instruction scrolls out of view. A hook is the same
rule enforced by a script: a small program that the tool the agent runs in,
such as Claude Code, starts at a set moment, for example before every file
edit. It runs whether or not anybody remembered the rule, in the first hour of
a session and the ninth alike.

This chapter covers the two hooks the murmur plugin ships, and three rules
that no hook can fully enforce: secrets, production, and what to do when a
guard blocks you. Anything a script can check should become a hook in time.
The rest stays in the law file (the file in your repository that says how
work happens), where a person decides.

## What a good hook looks like

A blocking hook runs before a tool call and reads what the agent is about to
do. If that matches something forbidden, it blocks the call and prints two
things:

1. one line saying why;
2. the command that does the job properly.

The second line is the part people leave out, and it is the part that works.
An agent that is refused with no alternative tries another route to the same
file. A refusal that names the correct command turns the agent around in one
step.

A hook is worth having when it is:

- **fast**, because it runs on every matching call;
- **silent on success**, because a hook that prints on every pass teaches
  everyone to ignore it;
- **narrow**: it blocks a named list, never a broad category, because a hook
  that blocks too much gets switched off.

## The first hook: generated files

Every project has files that a generator writes: an interface schema, a typed
client, an inventory, a catalog.

Editing one by hand is always wrong, because the next run of the generator
erases the edit. It is also the mistake agents make most often. The file looks
like an ordinary file, and editing it makes the problem in front of the agent
go away.

One rule goes with this hook. Never resolve a merge conflict inside a
generated file by hand. Rerun the generator on the updated base instead. A
hand-merged generated file matches neither of its sources.

### How the murmur hook works

The script is
[`plugin/hooks/block-generated-edits.sh`](../plugin/hooks/block-generated-edits.sh).
The plugin runs it before every `Edit`, `Write`, `MultiEdit` and
`NotebookEdit` call in Claude Code.

The script holds no paths. It reads `.claude/generated-files.txt` in your
repository, one protected path per line:

```text
docs/contracts/openapi.json  npm run generate:api
src/clients/api/generated/*  npm run generate:api
```

- Everything up to the first space is a glob (a path pattern).
- The rest of the line is the command that regenerates the file. The agent
  sees it when an edit is refused.
- Blank lines and lines that start with `#` are ignored.
- A glob that does not start with `/` or `*` matches any path that ends that
  way. So you can write paths relative to the repository root, whatever the
  checkout folder is called.

When the file being edited matches, the script exits with code 2, which
blocks the edit, and the agent sees:

```text
BLOCKED: <path> is generated, never hand-edit it.
Regenerate instead: <command>
```

With no list file, the hook exits quietly and blocks nothing. `/murmur:init`
writes the list from
[an example](../plugin/hooks/generated-files.example.txt), so after init the
guard is on for the example's paths. Edit the list to name your own generated
files, or empty it to switch the guard off.

The hook does not block the generator itself. The generator runs as a shell
command, which this check never sees. So the correct route stays open, and it
is the only open one.

A repository that does not use the plugin can use the same script from
[`templates/hooks/`](../templates/hooks/). Copy
[`settings.json`](../templates/hooks/settings.json) to
`.claude/settings.json`, the script to `.claude/hooks/`, and the example list
to `.claude/generated-files.txt`. Use the plugin or the copy, not both, so
there are never two copies that drift apart.

## The second hook: the short rules at session start

The plugin's other hook is
[`session-context.sh`](../plugin/hooks/session-context.sh). It runs when a
session starts, resumes, is cleared or is compacted. It puts a short version
of the team's rules in front of the agent before it acts. Then it adds what
this repository answered at `/murmur:init`: the repository, the branch that
work merges into, the tracker, whether there is a farm, and where branch
claims live.

To use your own short version of the rules, write it to
`.claude/team-laws.md`. The hook then uses that file, word for word, instead.
Keep it short: every session pays for it at the start.

## Secrets

Never run a command that prints a secret value. One setup command that echoes
a connection string with the password inside turns a routine task into a
rotation job, and it does so silently.

To check whether two secrets match, compare their hashes, not their values.
Hash both and compare the results. That answers the question without showing
either secret.

Any exposure means rotation, whatever was deleted afterwards. The message may
be gone from the chat while the value survives in a transcript, a log, a
scroll buffer or someone's terminal history. Rotating is cheap. Assuming a
secret is gone is not.

Secrets reach production through the project's secret pipeline, never by
hand-editing live configuration.

### The incident behind it

A routine setup command printed its output into a session transcript. The
output held a connection string, and the connection string held a password.

Nothing was attacked, and nothing leaked further. It still cost real work. The
credential had to be treated as exposed and rotated, and every place that used
it had to be updated. The original task had been a five-minute change.

## Production is read-only by default

Reading production is free, and it should stay free: logs, status, events,
history. An agent that cannot look at production guesses instead, which is
worse.

Anything that changes state is different. It needs approval for that exact
action, at that time, and approval for one action never extends to the next.
"You can restart that one process" does not mean "you can restart processes".

This rule is worded for how agents generalize. An agent reads an approval
as a whole category of permission unless it is worded as one action, once.

Fix forward through the repository and the deploy pipeline. Do not edit the
running system by hand. A hand edit is invisible to everyone else and
disappears on the next deploy, which makes the next incident harder.

Destructive actions and paid provisioning follow the same rule. Deleting
data, removing a branch, tearing down an environment or spending money each
needs a yes for that action.

## When a guard blocks you, assume it is right

When a guard fires, the instinct is to go around it: another tool, a force
flag, a quick disable and a promise to put it back.

Start from the opposite assumption. The guard knows something you do not,
until you have proven otherwise. In practice it usually does, and the minutes
spent understanding the block cost less than the incident it prevented.

If you do prove the rule wrong, change the rule in the open: in a reviewed
change, with the reason written down. Never step over it once and leave it
standing for the next agent.

## Adopt it in a day

1. List your repository's generated files in `.claude/generated-files.txt`,
   each with the command that regenerates it, and switch on the hook.
2. Make sure every block prints the correct command, not only the refusal.
3. Write the production rule into your law file: read-only by default, and
   each change approved for that action alone.
4. Add the three secret rules: never print a secret, compare hashes, rotate
   after any exposure.
5. The next time a guard blocks you, write down what it saved you from, or why
   it was wrong. That list is what justifies keeping the hooks.
