---
name: murmur
description: The front door to murmur, which runs Claude Code and Codex agents as one team. Trigger on "murmur", "install murmur", "update murmur", "what can murmur do", "reinstall murmur", "uninstall murmur". Says which murmur skill does what, and how to install, update, repair or remove murmur.
---

# murmur

murmur runs several coding agents as one team on one repository: each agent
claims its own branch, another agent reviews its work, and only changes that
pass their checks reach the base branch. The person decides what merges.

murmur keeps one clone in `~/work/murmur` on every machine. The skills below
are the same in Claude Code, where the plugin adds them, and in Codex, where
murmur's skill installer writes them into `~/.agents/skills` as
`murmur-<name>`.

## Which skill does what

| The person wants to | Use |
|---|---|
| install murmur on this computer | follow `~/work/murmur/INSTALL.md` (or <https://raw.githubusercontent.com/magik-ai/murmur/main/INSTALL.md> when there is no clone yet) |
| set up this repository | the `init` skill |
| check that the setup works | the `doctor` skill |
| get a farm, an always-on machine for agents | the `farm` skill (a DigitalOcean server), or step 8 of `INSTALL.md` for a machine they own |
| split a goal across agents | the `orchestrate` skill ("fan this out: ...") |
| take approved pull requests into the base branch | the `conductor` skill |
| let work go on overnight | the `night-mode` skill |
| run and watch lanes on a farm | the `fleet` skill |

## Update murmur

Say each step in one line before you run it.

1. Update the clone: `git -C ~/work/murmur pull --ff-only`.
2. Claude Code: `claude plugin marketplace update murmur`, then
   `claude plugin update murmur@murmur`, then ask the person to type
   `/reload-plugins`.
3. Codex: `uv run ~/work/murmur/plugin/scripts/murmur_skills.py install`, then
   tell the person the new skills load in their next Codex session.
4. In each repository set up with murmur, run the `init` skill again. It asks
   only questions that are new. Show the person any `.murmur-new` file, and
   commit the changes they keep through a pull request.
5. On a farm, run `git -C ~/work/murmur pull --ff-only` there too, then
   `fleet dashboard restart`. The `fleet` and `hq` commands run from that
   clone, so the pull updates them.
6. Run the `doctor` skill and tell the person what it says.

## Repair or reinstall

Follow `INSTALL.md` again from the top. Every step checks what is there, and
skips or updates it.

## Uninstall

Ask before each step; nothing here is undone later.

- Claude Code: `claude plugin uninstall murmur@murmur`, then
  `claude plugin marketplace remove murmur`.
- Codex: `uv run ~/work/murmur/plugin/scripts/murmur_skills.py uninstall`.
- The clone: remove `~/work/murmur` only when the person says so.
- The files murmur wrote into a repository stay; they are the person's files.
- A DigitalOcean farm keeps costing money until it is destroyed. Destroy it only
  when the person names it, with the `farm` skill's destroy step.
