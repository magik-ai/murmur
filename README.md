# agents-are-a-team

Run dozens of coding agents (Claude Code, Codex) as a team: named agents with per-session identity, branch claims and mail between them, a remote farm that spawns and cleans up after them, a merge discipline that keeps main green, and the written laws that let it run overnight without you.

**Status: private pilot. Not ready for strangers yet.** The plan is in [internal/PLAN.md](internal/PLAN.md).

## What is inside

- `hq/` the head office: session registry, branch claims, mail, identity, pre-push guard. State lives in a GitHub repo.
- `fleet/` the farm CLI: spawn, group, watch, message, verify, sweep. Runs on a Linux box you own.
- `plugin/` a Claude Code plugin: the orchestration and night-mode skills, the generated-file guard hook, session context.
- `docs/` the handbook: twelve short documents a team adopts in a week.
- `templates/` fill-in files: repo law, product briefing, pull request template, lessons file, memory index, briefs.

## Five-minute quickstart (target shape, not yet true)

```
uv tool install agents-are-a-team          # hq and fleet on your Mac
hq init --repo <your-org>/head-office      # one private repo becomes the head office
/plugin marketplace add magik-ai/agents-are-a-team && /plugin install team   # in Claude Code
fleet farm install user@your-linux-box     # optional: a farm for headless workers
```

Then read `docs/00-start-here.md`.
