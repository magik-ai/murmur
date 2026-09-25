# Install murmur

**If you are an AI agent** (Claude Code, Codex or another) and your user gave you
this repository or asked you to install murmur, follow this file from top to
bottom. It is written for you. People can follow it too.

Keep your user in the loop:

- Before each step, say in one line what you are about to do.
- Some steps need your user: typing a password, signing in through a browser,
  admin rights. For those, show the exact command, ask them to run it in their
  own terminal window, and wait until they say it is done. Never ask for a
  password, token or key in the chat.
- If a command fails, show its message to your user and stop. Do not work
  around it.

## 1. Check the computer

```bash
uname -s; cat /proc/version 2>/dev/null
```

- `Darwin`: a Mac.
- `Linux`, and `/proc/version` mentions `microsoft`: Windows with WSL. Treat it
  as Linux.
- `Linux`: Linux. murmur is tested on Ubuntu and Debian.
- The command fails, or you run in PowerShell or cmd: Windows without WSL.
  murmur needs WSL. Ask your user to right-click Start, open **Terminal
  (Admin)**, run `wsl --install`, restart the computer, open **Ubuntu** from
  the Start menu, install Claude Code or Codex there, and start you again
  inside Ubuntu. Stop here.

## 2. Install what is missing

Check each tool, and install only what is missing:

```bash
git --version; gh --version; uv --version
```

**On a Mac.** If `brew --version` fails, ask your user to install Homebrew in
their own terminal. It asks for their password:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

They also run the lines it prints under **Next steps**. Then install the
missing tools yourself:

```bash
brew install git gh uv
```

**On Linux and WSL.** git and gh need `sudo`. If `sudo -n true` succeeds, run
this yourself; otherwise ask your user to run it:

```bash
sudo apt-get update && sudo apt-get install -y git gh curl
```

Install uv yourself. It needs no password:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

## 3. Make sure GitHub is signed in

```bash
gh auth status
```

If it is not signed in, ask your user to run this in their own terminal and to
choose `GitHub.com`, `HTTPS`, `Y` and `Login with a web browser`:

```bash
gh auth login
```

When they say it is done, run `gh auth status` again.

## 4. Find the repository to set up

```bash
git rev-parse --show-toplevel
```

If you are not inside a git repository, ask your user which repository to set
up, clone it with `gh repo clone OWNER/NAME`, and go into it. If they have
none, offer `gh repo create NAME --private --clone`.

## 5. Get murmur

In Claude Code, install the plugin. It adds `/murmur:init`, `/murmur:doctor`,
`/murmur:farm` and the skills that run a team:

```bash
claude plugin marketplace add magik-ai/murmur
claude plugin install murmur@murmur
```

In every agent, Claude Code included, keep a copy of murmur to run the setup
from:

```bash
if [ -d ~/.murmur/.git ]; then git -C ~/.murmur pull --ff-only; else git clone --depth 1 https://github.com/magik-ai/murmur ~/.murmur; fi
```

## 6. Set up the repository

Run these from the root of your user's repository.

1. See which questions are open:

   ```bash
   uv run ~/.murmur/plugin/scripts/murmur_init.py questions
   ```

   It prints a JSON list. Each item has an `id`, a `prompt`, `choices` and a
   `default`. Ask your user one question at a time: show the choices and the
   default, and wait for the reply. `ok` or an empty reply means the default.
   Store each answer before you ask the next question:

   ```bash
   uv run ~/.murmur/plugin/scripts/murmur_init.py answer --id ID --value VALUE
   ```

   If your user says to use the defaults, skip the questions.
2. If your user works with Codex and the repository has no `AGENTS.md`, create
   it with the single line `# AGENTS.md`, so that murmur adds its pointer there
   too.
3. Write the files. murmur never overwrites a file that exists:

   ```bash
   uv run ~/.murmur/plugin/scripts/murmur_init.py apply
   ```

   Use `apply --defaults` if your user chose the defaults. Tell your user in
   plain words what it wrote. If it wrote a `.murmur-new` file, say that two
   versions now sit side by side and that they should keep one. If it created
   `CLAUDE.md`, that file still has blanks such as `<NAME>` and `<DOC>`: offer
   to fill them in with your user now, or leave them for later.
4. Save the setup on GitHub. Agents start their branches from GitHub, so they
   do not see files that exist only on this computer. Show your user what
   murmur wrote (`git status`), and with their yes, commit exactly those files:

   - If the repository has no commits yet, commit them on the default branch
     and push:

     ```bash
     git add <the files the apply report lists>
     git commit -m "Set up murmur"
     git push -u origin HEAD
     ```

   - Otherwise, commit them on a new branch, push it and open a pull request,
     then ask your user to merge it:

     ```bash
     git switch -c murmur-setup
     git add <the files the apply report lists>
     git commit -m "Set up murmur"
     git push -u origin murmur-setup
     gh pr create --fill
     ```

5. Check the setup, and show your user what it says:

   ```bash
   uv run ~/.murmur/plugin/scripts/murmur_doctor.py
   ```

## 7. Tell your user what comes next

In a few lines:

- In Claude Code, they can now ask for a team, for example
  `fan this out: add a dark mode switch to the settings page`. Claude shows a
  plan and starts nothing until they say go. Agents open pull requests; your
  user decides what merges.
- A farm is optional: an always-on Linux machine that runs agents while their
  computer is off. Offer it. If they want one, go on to step 8.
- The handbook explains the method:
  <https://github.com/magik-ai/murmur/tree/main/docs>

## 8. A farm, only if your user wants one

Ask which way they prefer.

- **Rent a DigitalOcean server.** Follow
  `~/.murmur/plugin/skills/farm/SKILL.md` yourself, and read
  `${CLAUDE_PLUGIN_ROOT}` in it as `~/.murmur/plugin`. In Claude Code, your
  user can also type `/murmur:farm`. It needs a DigitalOcean account. It shows
  the monthly price and buys nothing until your user types that price back.
- **Use a Linux computer they own:** Ubuntu 22.04 or newer, Debian 12 or newer,
  or Windows with WSL. Ask your user to run this on that computer, in their own
  terminal. It asks for their password and a few questions:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
  ```

A Mac cannot be a farm yet ([#8](https://github.com/magik-ai/murmur/issues/8)).

Tell your user that farm agents run without permission prompts, so they can run
any command the farm's user can. The farm should hold only what the agents
need.
