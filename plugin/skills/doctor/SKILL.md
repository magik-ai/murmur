---
name: doctor
description: Check that this repository is set up to run agents as a team. Trigger on "murmur doctor", "check my setup", "is this repo set up", "why is the team plugin not working". Prints a table of checks and one word for where the setup stands, and repairs only the safe items when asked.
---

# Doctor

You are checking a setup, not changing a repository. Run the script, explain
the table in plain words, and offer a repair only where a repair is safe.
Never push, delete or rename a branch, and never change a file the person
wrote.

**Where the scripts are.** The commands below run murmur's scripts from
`${CLAUDE_PLUGIN_ROOT}`, the plugin's folder. Claude Code fills it in, and
murmur's skill installer for Codex writes it in. If it is ever empty, use
`~/work/murmur/plugin`, and clone murmur there first if that folder is missing:
`git clone https://github.com/magik-ai/murmur ~/work/murmur`.

## 1. Run it

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_doctor.py
```

It prints one row per check, then a last line with the status.

## 2. Say the status first

The status is one word. Lead with it, in your own words, not the script's.

| Status | What to say |
|---|---|
| `current` | Everything checked is in place. Nothing to do. |
| `warnings` | It works, but something will cause trouble later. Name the rows. |
| `setup-required` | Something needed is missing. Name the rows marked `missing` and what fixes each. |
| `repaired` | A safe repair was made, and nothing else is wrong. |

## 3. Explain only the rows that are not `ok`

A row that passed needs no comment. For each row that did not, say what it
means and what it costs, one sentence each.

- **git repository**: this directory is not a git checkout, so nothing else can
  be checked. Move to the repository first.
- **config**: the answers from the init run are missing, incomplete, or in a
  file that cannot be read. Missing or incomplete: run the init skill. Cannot
  be read: the person fixes the file by hand, because it is theirs.
- **contract**: the file every agent is supposed to follow is not there. Run
  the init skill.
- **git remote**: there is no remote, so there is nothing to push to; or the
  remote refused the connection, usually an access problem; or it did not
  answer within five seconds, usually a network problem.
- **base branch**: the branch named in the answers does not exist on the
  remote. Either the name is wrong or the branch was never pushed.
- **hooks**: a hook script that ships with the plugin is not executable. The
  hooks are started through `bash`, so they still run; the repair only
  restores the file mode.
- **uv**: the skills run their scripts with `uv run`, so init, doctor and farm
  need it.
- **gh**: needed for pull requests and, with some trackers, for issues. If it
  is not signed in, the person runs `gh auth login`. Never do it for them.
- **tracker**: a tracker was chosen but its rules file, `.claude/tracker.md`,
  is not there, so an agent has to ask what to do on every task. Running the
  init skill again writes it.
- **claude**: Claude Code, which the agents run in, is not on the path.
- **stale branches**: local branches with no upstream branch whose last commit
  is more than a week old. Work that exists on one machine only can be lost.
  Name them and ask whether to push or delete each one. Do neither on your own.
- **head office** and **agent machine**: optional upgrades. The state
  `optional` is not a fault, and you never present it as one.

## 4. Offer the repair, and only the safe one

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_doctor.py --fix
```

It repairs exactly two things: it makes the plugin's hook scripts executable,
and it creates the config file from the defaults when there is no config file
at all. Offer it only when the hooks row is not `ok`, or when the config row
says the file is not there, and say which of the two it will do.

Never offer it as a general fix. It does not touch a file a person wrote (a
config file that exists but cannot be read is left alone), it does not push,
delete or rename a branch, it does not sign anyone in, and it does not write
the contract. Everything else on the table is either a decision for the person
or a job for the init skill.
