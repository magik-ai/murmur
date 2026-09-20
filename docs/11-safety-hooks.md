# Safety hooks

## Rules that do not depend on remembering

A rule an agent has to remember is a rule that holds until the session gets
long, the task gets urgent, or the instruction scrolls out of view.

A hook is the same rule enforced by a script. The script runs whether or not
anybody remembered it, on the first hour of the session and the ninth alike.
Anything that can be checked by a script eventually should be, and the rest
stays in the law file where a human decides.

## The pattern

A hook is a small script that runs before a tool call. It reads what the agent
is about to do. If that matches something forbidden, it exits non-zero and
prints two things: one line saying why, and the command that does the job
properly.

The remedy line is the part people leave out, and it is the part that works. A
bare block makes an agent creative, and a creative agent finds another route
to the same forbidden place. A block that names the correct command turns the
agent around in one step.

Three properties make a hook worth having. It is fast, because it runs on
every matching call. It is silent on success, because a hook that prints on
every pass teaches everyone to ignore it. And it blocks a named list, never a
broad category, because a hook that blocks too much gets switched off.

## Generated artifacts, the first hook worth writing

Every project has files produced by a generator: an interface schema, a typed
client, an inventory, a catalog.

Hand-editing one is always wrong, because the next regeneration silently
erases the edit. It is also the mistake agents make most often, for an obvious
reason: the file looks like an ordinary file, and editing it makes the
immediate problem go away.

The list of protected paths lives next to the hook, as a glob list anyone can
edit. It grows over the life of the project, and that is normal.

One rule travels with this hook. Never hand-resolve a merge conflict inside a
generated file. Regenerate it on the updated base instead, because a
hand-merged generated file is a file that matches neither source.

## A minimal hook

```bash
#!/usr/bin/env bash
# Blocks hand-edits of generated files. A non-zero exit stops the tool call.
set -euo pipefail

path=$(cat | python3 -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null) || path=""
[ -n "$path" ] || exit 0

case "$path" in
  */contracts/*.json|*/generated/*|*/GENERATED_INVENTORY.md)
    echo "BLOCKED: $path is a generated file. Never hand-edit it." >&2
    echo "Regenerate instead: <your generate command>" >&2
    exit 2
    ;;
esac
exit 0
```

Register it to run before the tools that write files, matching on edit and
write calls. That registration is a few lines of configuration in your
harness, next to the script.

Note what the hook does not do. It does not block the generator itself, which
runs as a shell command and never touches this path check. The point is to
make the correct route the only open one.

## Secrets

Never run a command that prints a secret value. One provisioning command that
echoes a connection string with the password inside it turns a routine task
into a rotation obligation, and it does so silently.

To check whether two secrets match, compare hashes rather than values. Hashing
both and comparing the digests answers the question without revealing either.

Any exposure means rotation, regardless of what was deleted afterwards. The
message may be gone from the chat while the value survives in a transcript, a
log, a scroll buffer, or someone's terminal history. Rotation is cheap.
Assuming a secret is gone is not.

Secrets reach production through whatever secret pipeline the project uses,
never by hand-editing live configuration.

## Production is read-only by default

Reading production is free and should stay free: logs, status, events, history.
An agent that cannot look at production will guess instead, which is worse.

Anything that changes state is different. It needs approval scoped to that
exact action, at the time, and approval for one action never extends to the
next. "You can restart that one process" is not "you can restart processes".

This is written for how agents generalize. An approval reads to an agent as a
category of permission unless it is worded as one action, once.

Prefer fixing forward through the repository and the deploy pipeline over
editing the running system by hand. A hand edit is invisible to everyone else
and disappears on the next deploy, which makes the next incident harder.

Destructive actions and paid provisioning follow the same rule, explicitly:
deleting data, removing a branch, tearing down an environment, or spending
money needs a yes for that action.

## When a safety mechanism blocks you, assume it is right

The instinct when a guard fires is to route around it: another tool, a force
flag, a quick disable and a promise to put it back.

Start from the opposite assumption. The mechanism knows something you do not,
until you have proven otherwise. In practice it usually did, and the minutes
spent understanding the block were cheaper than the incident it prevented.

If you do prove the rule wrong, the fix is to change the rule in the open, in
a reviewed change, with the reason written down. It is never to step over it
once and leave it standing for the next agent.

## The incident behind it

A routine provisioning command printed its output into a session transcript.
Inside that output was a connection string, and inside the connection string
was a password.

Nothing was attacked and nothing leaked further. It still cost real work: the
credential had to be treated as exposed, rotated, and every place that used it
updated, all for a task that had been a five-minute change.

The rule that came out of it is short. Never run a command that can echo a
secret. Compare hashes when you need to know if two secrets match. Treat any
appearance of a value as exposure, and rotate.

## Adopt it in a day

1. List the generated files in your repository and put them behind the hook
   above, with your own glob list.
2. Make sure every block prints the remedy command, not just the refusal.
3. Write the production sentence into your law file: read-only by default,
   each mutation approved for that action alone.
4. Add the three secret rules: never echo, compare hashes, rotate on any
   exposure.
5. The next time a guard blocks you, write down what it saved or why it was
   wrong. That list is what justifies keeping the hooks.
