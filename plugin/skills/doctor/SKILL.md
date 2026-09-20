---
name: doctor
description: Check that this repository is set up to run agents as a team. Trigger on "murmur doctor", "check my setup", "is this repo set up", "why is the team plugin not working". Prints a table of checks and one word for where the setup stands, and repairs only the safe items when asked.
---

# Doctor

You are checking a setup, not changing a repository. Run the script, read the
table out loud in plain words, and offer a repair only where a repair is safe.

## 1. Run it

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_doctor.py
```

It prints one row per check and a last line with the status.

## 2. Explain the status first

The status is one word. Lead with it, in the person's words, not the script's.

| Status | What to say |
|---|---|
| `current` | Everything checked is in place, nothing to do. |
| `warnings` | It works, but something will bite later. Name the rows. |
| `setup-required` | Something needed is not there yet. Run the init skill. |
| `repaired` | A safe repair was made, and nothing else is wrong. |

## 3. Explain only the rows that are not `ok`

A row that passed needs no commentary. For each row that did not, say what it
means and what it costs, in one sentence each.

- **git repository**: this directory is not a checkout, so nothing else can be
  checked. Move to the repository first.
- **config**: the answers from the init run are missing or incomplete. This is
  the one row that makes the whole setup incomplete.
- **contract**: the file every agent is supposed to follow is not there.
- **git remote**: the host did not answer within five seconds. Usually a
  network or an access problem, occasionally a wrong remote address.
- **base branch**: the branch the answers name does not exist on the host.
  Either the name is wrong or the branch was never pushed.
- **hooks**: a guard script that ships with the plugin is not executable, so it
  cannot run. Safe to repair.
- **uv**: the scripts here run with it, so nothing works without it.
- **gh**: needed for pull requests and, with some trackers, for issues. Not
  signed in is fixed by the person running `gh auth login`, never by you.
- **tracker**: a tracker was chosen but its rules file is absent, so an agent
  has to ask what to do on every task. Running the init skill again writes it.
- **claude**: the agents run in it.
- **stale branches**: local branches with no remote copy, idle for more than a
  week. Work that only exists on one machine is work that can vanish. Name
  them and ask whether to push or delete, and do neither on your own.
- **head office** and **agent machine**: these are optional upgrades. A row
  saying `optional, not set up` is not a fault, and you never present it as
  one.

## 4. Offer the repair, and only the safe one

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_doctor.py --fix
```

It repairs exactly two things: it makes the shipped hook scripts executable,
and it creates a missing config file from the defaults. Offer it when one of
those two rows is not `ok`, and say which of the two it will do.

Never offer it as a general fix. It does not touch a file a person wrote, it
does not push, delete or rename a branch, it does not sign anyone in, and it
does not write the contract. Everything else on the table is either a decision
for the person or a job for the init skill.
