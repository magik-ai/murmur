# Getting started from zero

This guide takes you from a new computer to a team of agents that open pull
requests on your repository. It works on a Mac, on Windows and on Linux. You
install one program yourself, Claude Code, and it installs the rest. You do not
need to know the terminal: copy each command, paste it, and press Enter.

You need:

- a GitHub account;
- a Claude subscription (Pro or Max);
- a computer: a Mac, a Windows PC, or a Linux PC.

## Step 1. Install Claude Code

Do the part for your computer, then go on to step 2.

### On a Mac

1. Open Terminal: press Cmd+Space, type `Terminal` and press Enter.
2. Install Claude Code:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```

3. Close Terminal and open it again, so that it finds the new command.

### On Windows

murmur runs on Windows inside WSL: a Linux (Ubuntu) that Windows runs for you.
You need Windows 11, or Windows 10 version 2004 or newer.

1. Right-click the Start button and choose **Terminal (Admin)**. On Windows 10
   it is called **Windows PowerShell (Admin)**.
2. Install WSL, then restart the computer:

   ```powershell
   wsl --install
   ```

3. After the restart, open **Ubuntu** from the Start menu. It asks you to choose
   a user name and a password.
4. In the Ubuntu window, install Claude Code. To paste in Ubuntu, right-click
   or press Ctrl+Shift+V:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```

5. Close Ubuntu and open it again. From now on, do everything in Ubuntu, not in
   PowerShell.

### On Linux

1. Open a terminal.
2. Install Claude Code:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```

   If it says `curl: command not found`, run `sudo apt install -y curl` first.
3. Close the terminal and open it again.

## Step 2. Sign in to Claude

```bash
claude
```

The first time, it asks how to sign in. Choose your Claude subscription, not an
API key, and finish in the browser. If no browser opens, copy the link it prints
into your browser.

## Step 3. Let Claude install murmur

In Claude Code, paste:

```text
Install murmur for this repo: https://github.com/magik-ai/murmur
```

If you started Claude Code outside your project's folder, name your repository
in the same message, for example
`Install murmur for my repo your-name/your-app: https://github.com/magik-ai/murmur`.
If you have no repository yet, say so, and Claude creates one.

Claude follows murmur's [install steps](../INSTALL.md). It installs git,
GitHub's tool `gh` and `uv` if they are missing, asks you a few questions with
defaults, sets up your repository and opens a pull request with the setup. Some
steps need you: signing in to GitHub, typing your password. Claude shows the
exact command. Open a second terminal window, run it there, and tell Claude
when it is done.

## Step 4. Run your first team

You do not need a farm for this: the agents run on your computer.

1. In Claude Code, describe a goal and ask for a team, for example:

   ```text
   fan this out: add a dark mode switch to the settings page
   ```

2. Claude splits the goal into lanes, one agent per task, and shows you the
   plan. Nothing starts until you say so. Type `go`.
3. Each agent works on its own branch and opens a pull request. Read them on
   GitHub. You decide what merges: tell Claude which pull requests to merge.

The agents work while your computer is on and awake. For work that goes on
while it is off, add a farm.

## Step 5. Add a farm (optional)

A farm is an always-on Linux machine that runs agents for you. Tell Claude you
want one:

```text
Set up a murmur farm for me.
```

It offers two ways:

- **Rent a DigitalOcean server.** You need a DigitalOcean account with a
  payment method. Claude shows the monthly price and buys nothing until you
  type that price back. Then it installs murmur on the server and opens its
  dashboard. It asks you for one API token from DigitalOcean: paste it in your
  terminal when Claude says so, never in the chat.
- **Use a Linux computer or server you own:** Ubuntu 22.04 or newer, or
  Debian 12 or newer, with systemd, or a Windows PC with WSL. You run one
  command on that machine (over ssh for a server), and it installs everything.
  On Windows, first switch on the two settings in
  [chapter 12](12-the-machine.md#what-the-machine-must-be) that keep WSL
  running when its window is closed.

A Mac cannot be a farm yet, because the farm's services need Linux:
[#8](https://github.com/magik-ai/murmur/issues/8) tracks it.

Agents on a farm run without asking before each command, so they can do
anything your user can do on that machine. Keep only what they need on it.
[Chapter 12](12-the-machine.md) explains the farm in full.

## Prefer Codex?

Everything above works in Codex too. In step 1, install Codex instead of
Claude Code, or next to it:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

In step 2, sign in with `codex login` and choose your ChatGPT plan. In step 3,
start `codex` in your project's folder and paste the same message. murmur gives
Codex the same skills as Claude Code. The one difference is in step 4: without
a farm, Codex runs the lanes one after another instead of side by side.

## Doing it by hand

If you would rather not let an agent install anything:

- **Mac:** install [Homebrew](https://brew.sh), then run
  `brew install git gh uv`.
- **Linux and WSL:** run `sudo apt update && sudo apt install -y git gh curl`,
  then `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- Sign in to GitHub with `gh auth login`: choose `GitHub.com`, `HTTPS`, `Y`
  and `Login with a web browser`.
- Then follow the [quick start in the README](../README.md#1-set-up-a-repository).

## If something goes wrong

| What you see | What to do |
| --- | --- |
| `command not found` right after an install | Close the terminal and open it again |
| No browser opens when you sign in | Copy the link from the terminal into your browser |
| Claude asks you to run a command yourself | Run it in a second terminal window, then tell Claude it is done |
| Claude Code does not know `/murmur:init` | Type `/reload-plugins`, or type `/exit` and start `claude` again |
