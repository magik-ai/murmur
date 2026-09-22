# Changelog

Keep a Changelog format, semver from the first tag.

## Unreleased

- Dashboard v2: four tabs. Board (agents with two filters and a search, the verification queue beside them, machine and account strips, a setup checklist), Mail (three fixed panes, plain words), Queue (a table with a detail panel and a log viewer; verify, cancel, runner on and off), Machine (power with honest confirms and jobs, services, accounts with a real add flow and login states, engines with an installed check, projects, health, settings). New routes for services, jobs, power, kill, queue writes, login state, engines, project removal (2026-09-22).
- The farm dashboard is a product: seven tabs (Overview, Agents, Mail, Queue, Projects, Accounts, System), an agent mail tab on the head office, honest empty and error states with the fix command, a first-run checklist, light and dark, a Cmd+K palette, no constant that names one farm; new routes /api/config, /api/health, /api/projects, /api/agent/log, /api/agent/msg, /api/mail/* (2026-09-21).
- `farm/install.sh`: one-command farm installer for Ubuntu and Debian, and chapter 12 of the handbook, the machine: where to get one, sizes and prices, the two logins, reaching the dashboard (2026-09-21).
- hq and fleet are merged upstream (agent-hq #544, #545; fleet #1, #2) and both machines of the reference farm run them; the import into this repository is next (2026-09-20).
- The session hook reads `.murmur/config.toml` and tells the agent what <OWNER>, <TRACKER> and <FARM> mean in this repository (2026-09-20).
- The name is murmur. MIT. init and doctor skills with scripts; tracker adapters; lessons from the field; a synthetic memory sample; the first-stranger review applied (2026-09-20, night).

- Plan, research and skeleton (2026-09-20).
- Handbook chapters 00 to 11, thirteen templates, the plugin with three skills and two hooks, all first drafts (2026-09-20).
