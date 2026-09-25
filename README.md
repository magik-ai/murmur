<p align="center">
  <a href="https://murmur.farm">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/assets/readme-dark.png">
      <img alt="murmur: an open-source orchestrator for coding agents. Run Claude Code and Codex as one team on a machine you own." src=".github/assets/readme-light.png" width="100%">
    </picture>
  </a>
</p>

<p align="center">
  <a href="https://murmur.farm"><b>murmur.farm</b></a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="#quick-start">Quick start</a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="docs/00-start-here.md">Handbook</a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-5B4A8A?style=flat-square"></a>
  <a href="https://github.com/magik-ai/murmur/actions/workflows/plugin-tests.yml"><img alt="plugin tests" src="https://github.com/magik-ai/murmur/actions/workflows/plugin-tests.yml/badge.svg"></a>
  <a href="https://github.com/magik-ai/murmur/actions/workflows/fleet-tests.yml"><img alt="fleet tests" src="https://github.com/magik-ai/murmur/actions/workflows/fleet-tests.yml/badge.svg"></a>
  <a href="https://github.com/magik-ai/murmur/actions/workflows/hq-tests.yml"><img alt="hq tests" src="https://github.com/magik-ai/murmur/actions/workflows/hq-tests.yml/badge.svg"></a>
</p>

> **AI agents:** to install murmur for your user, read and follow
> [INSTALL.md](https://raw.githubusercontent.com/magik-ai/murmur/main/INSTALL.md).

murmur is an open-source tool for running several AI coding agents as one team.
It works with Claude Code and Codex, on your laptop or on a machine you own.

With murmur, every agent:

- has a name, so you can see who did what;
- claims its branch in the head office before it starts, so no two agents work
  on the same branch;
- gets its work reviewed by a different agent;
- merges only after `main` with the change on top passes the tests (GitHub's
  merge queue checks this).

With a farm (an always-on machine for your agents), you also get one dashboard
that shows every agent, and the work can go on overnight while you sleep.

## Why murmur

One coding agent is easy to watch. You give it a task, you read the diff.

Ten agents at once are a team, and a team needs rules. Who owns which task?
Who checks the work? How do two finished changes get into `main` without
breaking it? Without answers, agents overwrite each other's work, review
their own mistakes, and merge changes that pass alone but fail together.

murmur is those rules, written down, plus the tools that make agents follow them.

## What is inside

murmur has three parts. You can start with the first one and add the others later.

**1. The plugin** ([`plugin/`](plugin)). A Claude Code plugin. `/murmur:init`
sets up a repository for team work: it asks seven questions and writes a rules
file for agents, a pull request template and a lessons file. Its skills tell
agents how to split work, review it, merge it and keep working while you are away.

<img alt="The murmur plugin in Claude Code, setting up a repository with seven questions." src=".github/assets/plugin.webp" width="100%">

**2. The farm** ([`fleet/`](fleet)). Runs agents on an always-on Linux machine,
as many as its CPU and memory allow. A web dashboard shows every agent, every
subscription's usage limits and the machine's health, with a stop button for each agent.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".github/assets/board-dark.webp">
  <img alt="The Board tab of the dashboard: machine load, memory and disk, each subscription's limits, and one card per agent with its status and checks." src=".github/assets/board.webp" width="100%">
</picture>

**3. The head office** ([`hq/`](hq)). A small command-line tool. Agents use it
to register their names, claim branches and send each other messages. It stores
everything in a private GitHub repository, so it works even when the farm is off.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".github/assets/mail-dark.webp">
  <img alt="The Mail tab: conversations on the left, one thread in the middle, the agents that are online on the right." src=".github/assets/mail.webp" width="100%">
</picture>

The repository also has a [handbook](docs/00-start-here.md) that explains the
method in 13 chapters, [templates](templates) for your own repository,
and a [one-command installer](farm) for the farm.

## Quick start

### The easy way: ask your agent

Open Claude Code or Codex in your repository and paste:

```text
Install murmur for this repo: https://github.com/magik-ai/murmur
```

Your agent follows [INSTALL.md](INSTALL.md): it checks your computer, installs
what is missing, asks you a few questions and sets up the repository. It asks
you to do only the parts that need you, such as signing in to GitHub.

No Claude Code or Codex yet, or new to the terminal?
[Getting started from zero](docs/getting-started.md) sets up a Mac, a Windows
PC or a Linux PC, one command at a time.

The steps below do the same by hand.

### 1. Set up a repository

On your laptop you need Claude Code, git, the GitHub CLI (`gh`) and
[uv](https://docs.astral.sh/uv/). The plugin's commands run their scripts with
`uv run`.

Open Claude Code inside the repository you want to set up, then run:

```text
/plugin marketplace add magik-ai/murmur
/plugin install murmur@murmur
/murmur:init
/murmur:doctor
```

`/murmur:init` asks seven questions. Answer `ok` to keep a default. It never
replaces a file you already have. If you have a `CLAUDE.md` or `AGENTS.md`, it
adds a short pointer at the end. If another file it wants to write already
exists, it leaves yours alone or writes its version next to it as a
`.murmur-new` file for you to compare.

`/murmur:doctor` checks the setup and tells you what is missing.

If a `/murmur:` command is not found right after the install, run
`/reload-plugins` or start a new Claude Code session.

### 2. Run your first team

In Claude Code, describe a goal and ask for a team, for example:

```text
fan this out: add a dark mode switch to the settings page
```

The orchestrate skill splits the goal into lanes: one agent per task, each
with its own files and its own branch. It shows you the plan and waits for your
go before it starts anything. Without a farm, the lanes run as local sessions
on your laptop. [Chapter 4 of the handbook](docs/04-orchestration.md) explains
the whole flow.

### 3. Add a head office (optional)

The head office gives agents names, branch claims and messages that work
across sessions and machines. It is a private GitHub repository that the `hq`
tool reads and writes. To set it up, follow
[the hq install steps](hq/README.md#install). When `/murmur:init` asks where
branch claims are recorded, answer `private-github-repo`. If you already
answered, set `coordination = "private-github-repo"` in `.murmur/config.toml`.

### 4. Add a farm (optional)

You do not need a farm on day one. Once you run three or four agents at the
same time, give them a machine that stays on. There are two ways:

- **A new cloud machine.** In Claude Code, run `/murmur:farm`. It creates a
  DigitalOcean Droplet, installs murmur on it and opens its dashboard through
  an SSH tunnel or Tailscale. Before it buys anything, it shows you the monthly
  price and asks you to type it back.
- **A machine you already have.** On an Ubuntu or Debian machine, run:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
  ```

Then read [the first chapter of the handbook](docs/00-start-here.md). When you
set up the farm, read [chapter 12, the machine](docs/12-the-machine.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".github/assets/machine-dark.webp">
  <img alt="The Machine tab: power settings, the farm's services, its machines, subscriptions, models and projects." src=".github/assets/machine.webp" width="100%">
</picture>

## How the work moves

Each job has one owner, and nobody does two jobs:

| Role | What it does |
| --- | --- |
| You | Set the goal, answer questions, decide what ships |
| Orchestrator | Splits the goal into tasks, so each agent gets its own files |
| Lanes | One agent per task: from the first commit to a reviewed pull request |
| Conductor | Merges finished work into `main` after you say yes, and can stop any merge |

You decide what merges. Lanes never merge their own work.

Every change goes through five main steps. The handbook's
[golden workflow](docs/02-golden-workflow.md) breaks them into ten smaller ones.

1. **Claim a branch.** Other agents see the claim and stay away.
2. **Work alone**, in a separate copy of the repository (a git worktree).
3. **Get a review** from an agent that did not write the change.
4. **Test with `main`**: run the tests on `main` with this change on top, not
   just on the branch. GitHub's merge queue can do this for you.
5. **Merge.** `main` stays green, and the agent picks up the next task.

## What it runs on

| | What murmur supports today |
| --- | --- |
| Agents | Claude Code and Codex, each signed in with its own subscription |
| Your laptop | Claude Code, git, the GitHub CLI (`gh`) and [uv](https://docs.astral.sh/uv/) |
| The farm (optional) | Ubuntu 22.04 or newer, or Debian 12 or newer, with systemd. Your own machine or a DigitalOcean Droplet |
| Head office | A private GitHub repository |
| Price | Free and open source (MIT). You pay only for your subscriptions and your machine |

murmur ships only the engines and machines that have been tested on real
projects. To add another agent engine or cloud provider, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

| Where | What you find |
| --- | --- |
| [`docs/`](docs) | The handbook: the method, one chapter per topic, in reading order |
| [`plugin/`](plugin) | The Claude Code plugin: commands, skills and hooks |
| [`fleet/`](fleet) | The farm: the `fleet` command, the dashboard, [quick start](fleet/docs/QUICKSTART.md) and [operations guide](fleet/docs/OPERATIONS.md) |
| [`hq/`](hq) | The head office: names, branch claims and messages |
| [`farm/`](farm) | The one-command farm installer |
| [`templates/`](templates) | Files to copy into your own repository |

## Questions people ask first

<details>
<summary><b>Do I need a farm?</b></summary>
<br>
No. The plugin and the head office work on your laptop. A separate machine
helps once three or four agents run at the same time, or when you want work to
continue after you close the laptop.
</details>

<details>
<summary><b>Which agents does it run?</b></summary>
<br>
Claude Code and Codex. Each one uses its own subscription. The farm removes
<code>ANTHROPIC_API_KEY</code> and <code>OPENAI_API_KEY</code> from each
agent's environment, so an agent does not switch to paid API use by accident.
Do not set up any other API credentials on the farm.
</details>

<details>
<summary><b>Can agents on a farm do anything on that machine?</b></summary>
<br>
Yes. To work without a person at the keyboard, farm agents run with Claude
Code's permission prompts switched off and with Codex's sandbox switched off.
They can run any command the farm's user can. Use a machine, or at least a user
account, that holds only what the agents need. <a href="SECURITY.md">SECURITY.md</a>
lists what murmur does and does not protect against.
</details>

<details>
<summary><b>Does it need GitHub?</b></summary>
<br>
Yes. The head office, the branch claims and the merge queue all use GitHub.
</details>

<details>
<summary><b>Where does the dashboard run, and who can open it?</b></summary>
<br>
It runs on the farm. By default it listens only on the farm itself. From your
laptop you open it through an SSH tunnel or your own Tailscale network. Any
change made from the page needs a secret token.
</details>

<details>
<summary><b>What does it cost?</b></summary>
<br>
murmur is free (MIT license). You pay only for your agent subscriptions and, if
you use one, the farm machine.
</details>

## Contributing

Bug reports, fixes and new engines or providers are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) first. Please report security problems
privately, as [SECURITY.md](SECURITY.md) describes. Everyone taking part
follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Delivered by

murmur is made by [Ilya Chernyakov](https://chernyakov.ai). You can find him on
[GitHub](https://github.com/ilya-chernyakov), [X](https://x.com/ilyachernyakov),
[LinkedIn](https://www.linkedin.com/in/ichernyakov/) and at
[chernyakov.ai](https://chernyakov.ai).

## License

murmur is released under the [MIT License](LICENSE).

<br>

<p align="center">
  <a href="https://murmur.farm">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/assets/mark-dusk.svg">
      <img alt="murmur" src=".github/assets/mark.svg" width="56">
    </picture>
  </a>
</p>

<p align="center">The name comes from a murmuration: thousands of starlings that fly as one<br>because each bird follows a few simple rules about its nearest neighbours.</p>
