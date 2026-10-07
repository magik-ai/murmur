# Changelog

All notable changes to murmur are written down here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version numbers
follow [Semantic Versioning](https://semver.org/) from the first tagged release.

## Unreleased

### Added

- Agents check the farm before they start any lane, in every session: the
  `fleet` command is there, the farm answers, the repository is registered on
  it, and an account has room. If a check fails, the agent starts nothing and
  says which check failed and how to fix it. It no longer falls back to
  running lanes on the laptop without saying so.
- When a farm runs a repository's agents, init writes a farm block into its
  `CLAUDE.md` and `AGENTS.md`: the repository's name on the farm and that
  check. The doctor runs the same check.
- [INSTALL.md](INSTALL.md) now goes past the farm: steps 9 to 13 connect the
  laptop to the farm and its head office, register the repository, and end
  with a first lane running on the farm and a first message in the head
  office. `farm/install.sh` and `/murmur:farm` end by sending the agent there.

### Fixed

- A subscription card on the Board says when its session and its weekly limit
  reset, each on its own line. It used to name only the soonest reset, which
  was always the session's.

## 0.2.0 - 2026-09-25

murmur now installs through your agent, on a Mac, Windows or Linux, and its
skills work in Codex as well as in Claude Code.

### Install through your agent

- Paste `Install murmur for this repo: https://github.com/magik-ai/murmur` into
  Claude Code or Codex. [INSTALL.md](INSTALL.md) takes the agent from checking
  the computer to a pull request with the repository's setup, and asks the
  person only for what needs them: passwords, sign-ins and answers.
- [Getting started from zero](docs/getting-started.md) starts from a new Mac,
  Windows (through WSL) or Linux computer.
- murmur.farm starts with "Ask your agent". Every Copy button now pastes one
  command that works, and a line under each box says what that way needs.

### Codex

- `plugin/scripts/murmur_skills.py install` writes murmur's skills into Codex's
  `~/.agents/skills` as `murmur-<name>`, with their script paths filled in.
  `status` and `uninstall` go with it.
- `murmur_init.py apply --agents-md` points `AGENTS.md` at the contract. A
  `CLAUDE.md` that init writes next to an `AGENTS.md` starts with `@AGENTS.md`,
  and the contract carries the rule about generated files, which Codex has no
  hook for.
- The doctor takes Codex as well as Claude Code.
- hq takes Codex's `CODEX_THREAD_ID` as a session key. A Codex session in tmux
  that registered under `TMUX_PANE` says `hq hello` once more.
- Without a farm, lanes run as background Claude Code subagents in their own
  worktrees, or one at a time in Codex.

### Also added

- The `murmur` skill says which skill does what and how to update, repair or
  uninstall murmur; `/murmur:update` runs the update.
- The doctor warns when a file init writes is missing, a `.murmur-new` file is
  waiting, `CLAUDE.md` still has blanks, `CLAUDE.md` or `AGENTS.md` has no
  pointer to the contract, or the setup is not on the base branch on GitHub.
- `/murmur:farm` ends by making `fleet` on the laptop run on the farm.
- A docs test, run in CI, keeps the newcomer docs, the skills and the landing
  page in agreement.
- murmur.farm sends HSTS, nosniff and referrer-policy headers.

### Changed

- murmur keeps its clone in `~/work/murmur` on every machine.
- The README says to commit and push the files `/murmur:init` wrote: agents
  start their branches from GitHub.

### Fixed

- `/murmur:farm` no longer skips the step that signs the farm in to Claude and
  Codex.
- The farm installer stops before it changes anything on a machine where
  systemd does not run, and says what to do on WSL and as root. Its last lines
  no longer ask for `hq hello` or `hq whoami`.
- `fleet dashboard status` says running only when the dashboard answers.
  `fleet dashboard start` waits until it answers, so `fleet dashboard token`
  right after the first start finds the token, and says why when it does not
  come up.
- The dashboard says "Needs a login" for Claude Code and Codex until one is
  signed in on the farm, instead of "Connected".
- `fleet/install.sh` links the fleet skill into `~/.agents/skills`, where Codex
  reads skills now. The fleet skill says Claude lanes default to Opus.
- The policy test's fake `hq` no longer calls itself.

## 0.1.0 - 2026-09-25

The first public release. It contains:

### Plugin (`plugin/`)

- `/murmur:init` sets up a repository for team work. It asks seven questions
  and writes a rules file for agents, the tracker rules, a pull request template
  and a lessons file. It never replaces a file you already have.
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
  works on its own branch in its own git worktree. Claude Code agents run Opus
  and Codex agents run GPT-6 Sol unless you pick another model;
  `FLEET_CLAUDE_MODEL` and `FLEET_CODEX_MODEL` change the defaults.
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

### Security

- The dashboard refuses requests for any host name other than this machine
  when it listens on a loopback address, so a website cannot read it through
  DNS rebinding.
- `fleet spawn --after` no longer runs lane names or other values as code, and
  spawn refuses names that are not plain.
- Reading the dashboard can no longer trigger back-to-back GitHub calls.
- An account name such as `.` can no longer remove every extra account.
- Claude Code and Codex lanes run without any API-key variables, and secrets
  are scrubbed from lane briefs, results and logs on the dashboard.
- The policy in [SECURITY.md](SECURITY.md) says what murmur does and does not
  protect against.

### Also included

- `farm/install.sh`: one command that turns an Ubuntu or Debian machine into a farm.
- A handbook of 13 chapters (`docs/`) and templates for your own repository
  (`templates/`).
- The Starling Almanac design system (`design/`) and the murmur.farm landing
  page (`site/`).
