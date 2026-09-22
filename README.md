# murmur

Run dozens of coding agents (Claude Code, Codex) as a team: named agents with per-session identity, branch claims and mail between them, a remote farm that spawns and cleans up after them, a merge discipline that keeps main green, and the written laws that let it run overnight without you.

**Status: private pilot. Not ready for strangers yet.** The plan is in [internal/PLAN.md](internal/PLAN.md).

## What is inside

- `hq/` the head office: session registry, branch claims, mail, identity, the claims guard. State lives in a GitHub repo.
- `fleet/` the farm CLI: spawn, group, watch, message, verify, sweep, and a dashboard of four
  tabs: Board (who is running and what is being verified, the screen you keep open), Mail (the
  same head office your agents talk through, not a second store), Queue (the merge-result
  verification runs and their logs) and Machine (power, services, accounts, engines, projects,
  health). From the page a person can stop a lane, pause the farm and resume it, add an account
  and enqueue a verification; spawning and provider keys stay at a terminal on purpose. Runs on a
  Linux box you own.
- `farm/install.sh` one command that turns a fresh Ubuntu box or VPS into that farm: `curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash` (see `docs/12-the-machine.md`).
- `plugin/` a Claude Code plugin: the orchestration and night-mode skills, the generated-file guard hook, session context.
- `docs/` the handbook: twelve short documents a team adopts in a week.
- `templates/` fill-in files: repo law, product briefing, pull request template, lessons file, memory index, briefs.

## Five-minute quickstart (target shape, not yet true)

```
/murmur:init                                  # answers seven questions, writes the files
/plugin marketplace add magik-ai/murmur
/plugin install murmur@murmur
murmur doctor                                 # checks the setup; head office and farm are optional
```

Then read `docs/00-start-here.md`.
