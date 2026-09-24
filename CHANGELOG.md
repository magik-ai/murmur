# Changelog

All notable changes to murmur are written down here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version numbers
follow [Semantic Versioning](https://semver.org/) from the first tagged release.

## Unreleased

The first public release. It contains:

### Plugin (`plugin/`)

- `/murmur:init` sets up a repository for team work. It asks seven questions
  and writes a rules file for agents, the tracker rules, a pull request template
  and a lessons file. It never overwrites an existing file.
- `/murmur:doctor` checks the setup and reports what is missing.
- `/murmur:farm` creates a farm on a DigitalOcean Droplet from your laptop. It
  buys the Droplet only after you type the monthly price back, installs murmur
  on it and opens the dashboard through an SSH tunnel or Tailscale.
- Skills for splitting work across agents (orchestrate), merging it
  (conductor) and working unattended (night mode).
- Hooks that tell each session how the repository is set up and block edits to
  generated files.

### Farm (`fleet/`)

- `fleet` starts Claude Code and Codex agents on a Linux machine. Each agent
  works on its own branch in its own git worktree.
- Capacity limits and power settings keep the machine responsive. A supervisor
  restarts agents that have a restart policy, and a sweep timer cleans up
  finished work.
- A web dashboard with three tabs: Board (agents, machine health, subscription
  limits), Mail (messages between agents) and Machine (power, services,
  machines, accounts, models and projects).
- Machines: a Linux machine you reach over SSH, or a DigitalOcean Droplet.

### Head office (`hq/`)

- A command-line tool with no dependencies. Agents register their names, claim
  branches (with a pre-push guard) and send each other messages through a
  private GitHub repository.

### Also included

- `farm/install.sh`: one command that turns an Ubuntu or Debian machine into a farm.
- A handbook of 13 chapters (`docs/`) and templates for your own repository
  (`templates/`).
- The Starling Almanac design system (`design/`) and the murmur.farm landing
  page (`site/`).
