# Install murmur

**If you are an AI agent** (Claude Code, Codex or another) and your user gave you
this repository or asked you to install murmur, follow this file from top to
bottom. It is written for you. People can follow it too.

Keep your user in the loop:

- Before each step, say in one line what you are about to do.
- Some steps need your user: typing a password, signing in through a browser,
  admin rights, clicking a system dialog. For those, show the exact command or
  action, ask them to do it in their own terminal window, and wait until they
  say it is done. Never ask for a password, token or key in the chat.
- If a command fails, show its message to your user and stop. Do not work
  around it.
- Never commit, stash or discard your user's own changes.
- Every step is safe to run again. If murmur is already installed, the steps
  check it, update what is old and skip the rest. An install that stopped
  halfway resumes when you start again from the top.

Your shell may not keep changes to `PATH` from one command to the next. Right
after you install a tool, call it by its full path, as the steps below do.

## 1. Check the computer

```bash
uname -s; grep -i microsoft /proc/version 2>/dev/null
```

- `Darwin`: a Mac.
- `Linux`, and the second line mentions Microsoft: Windows with WSL. Treat it
  as Linux.
- `Linux` with no second line: Linux. murmur is tested on Ubuntu and Debian.
- `MINGW…`, `MSYS…` or `CYGWIN…` (Git Bash on Windows), or the command fails
  because you run in PowerShell or cmd: Windows without WSL. murmur needs WSL.
  Ask your user to right-click Start, open **Terminal (Admin)**, run
  `wsl --install`, restart the computer, open **Ubuntu** from the Start menu,
  install Claude Code or Codex there, and start you again inside Ubuntu. Install
  nothing here, and stop.

## 2. Install what is missing

Check each tool, and install only what is missing:

```bash
git --version; gh --version; uv --version
```

**On a Mac.**

- On a new Mac, `git --version` may open a dialog that offers the command line
  developer tools. Ask your user to click **Install**, and wait until it has
  finished.
- If `brew --version` fails, ask your user to install Homebrew in their own
  terminal. It asks for their password, and at the end it prints lines under
  **Next steps** that they run too:

  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```

- Then install the missing tools yourself, calling brew by its full path
  (`/opt/homebrew/bin/brew` on Apple silicon, `/usr/local/bin/brew` on Intel):

  ```bash
  /opt/homebrew/bin/brew install git gh uv
  ```

**On Linux and WSL.**

- git and gh need `sudo`. If `sudo -n true` succeeds, run this yourself;
  otherwise ask your user to run it:

  ```bash
  sudo apt-get update && sudo apt-get install -y git gh curl
  ```

  If apt has no `gh` package, GitHub's own instructions add it:
  <https://github.com/cli/cli/blob/trunk/docs/install_linux.md>.
- Install uv yourself. It needs no password, and it lands in `~/.local/bin`:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

  Use `~/.local/bin/uv` wherever the steps below say `uv`, until a new shell
  finds it by name.

The gh in some distributions' package lists is old. That is fine on this
computer. A farm needs gh 2.40 or newer, and the farm's installer brings its
own.

## 3. Sign in to GitHub, and tell git who you are

```bash
gh auth status
```

If it is not signed in, ask your user to run this in their own terminal and to
choose `GitHub.com`, `HTTPS`, `Y` and `Login with a web browser`. If no browser
opens, they open <https://github.com/login/device> and type the code:

```bash
gh auth login
```

When they say it is done, run `gh auth status` again.

Commits need a name and an email:

```bash
git config --global user.name; git config --global user.email
```

If either is empty, ask your user what to use. Suggest their GitHub name and
their private GitHub address, which this prints:

```bash
gh api user --jq '"\(.login) \(.id)+\(.login)@users.noreply.github.com"'
```

With their yes, set both with `git config --global user.name "…"` and
`git config --global user.email "…"`.

## 4. Get murmur and its skills

murmur lives in one folder, `~/work/murmur`, on every computer:

```bash
if [ -d ~/work/murmur/.git ]; then git -C ~/work/murmur pull --ff-only; else git clone https://github.com/magik-ai/murmur ~/work/murmur; fi
```

Then give your agent murmur's skills, so that it can do the work later without
this file:

- **Claude Code.** Install the plugin. It adds `/murmur:init`,
  `/murmur:doctor`, `/murmur:farm`, `/murmur:update` and the skills that run a
  team:

  ```bash
  claude plugin marketplace add magik-ai/murmur
  claude plugin install murmur@murmur
  ```

  If either says murmur is already there, update it instead:
  `claude plugin marketplace update murmur`, then
  `claude plugin update murmur@murmur`. If there is no `claude` command (the
  desktop app or an editor), ask your user to type these in Claude Code, one
  at a time: `/plugin marketplace add magik-ai/murmur`,
  `/plugin install murmur@murmur`, `/reload-plugins`.
- **Codex.** Write the skills into Codex's skills folder, `~/.agents/skills`:

  ```bash
  uv run ~/work/murmur/plugin/scripts/murmur_skills.py install
  ```

  Codex then has `$murmur`, `$murmur-init`, `$murmur-doctor`, `$murmur-farm`,
  `$murmur-orchestrate`, `$murmur-conductor`, `$murmur-night-mode` and
  `$fleet`.

A running session loads new skills only when it starts again. You do not need
to restart now: keep following this file. When a step below names a skill,
read it from `~/work/murmur/plugin/skills/<name>/SKILL.md`, and wherever it
says `${CLAUDE_PLUGIN_ROOT}`, use `~/work/murmur/plugin`.

## 5. Find the repository to set up

Work from the repository's top folder:

```bash
git rev-parse --show-toplevel && git remote get-url origin
```

- Not inside a git repository: ask your user which repository to set up, clone
  it with `gh repo clone OWNER/NAME`, and go into it. If they have none, offer
  `gh repo create NAME --private --add-readme --clone`.
- A repository with no `origin`: offer
  `gh repo create NAME --private --source . --push`.
- An `origin` that is not on GitHub, or one your user cannot push to: murmur
  needs a GitHub repository they can push to. Say so, and stop.

## 6. Set up the repository

Run these from the repository's top folder.

1. See which questions are open:

   ```bash
   uv run ~/work/murmur/plugin/scripts/murmur_init.py questions
   ```

   It prints a JSON list. Each item has an `id`, a `prompt`, `choices` and a
   `default`. Ask your user one question at a time: show the choices and the
   default, and wait for the reply. `ok` or an empty reply means the default.
   Store each answer before you ask the next question:

   ```bash
   uv run ~/work/murmur/plugin/scripts/murmur_init.py answer --id ID --value VALUE
   ```

   If your user says to use the defaults, skip the questions. An empty list
   means everything is answered already.
2. Write the files. murmur never overwrites a file that exists:

   ```bash
   uv run ~/work/murmur/plugin/scripts/murmur_init.py apply
   ```

   Add `--defaults` if your user chose the defaults, and `--agents-md` if they
   use Codex: Codex reads `AGENTS.md`, so murmur then points it at the contract
   too. Tell your user in plain words what the report says it wrote:
   - A `.murmur-new` file means two versions now sit side by side. Your user
     keeps one; never commit a `.murmur-new` file.
   - If it created `CLAUDE.md`, its entry lists `placeholders` such as `<NAME>`
     and `<DOC>`. Offer to fill them in with your user now, one at a time, or
     leave them for later.
3. Save the setup on GitHub. Agents start their branches from GitHub, so they
   do not see files that exist only on this computer. Show your user what
   murmur wrote, and with their yes commit exactly those files, never their own
   changes:

   - A repository with no commits yet: commit on the default branch and push.

     ```bash
     git add <the files the apply report lists>
     git commit -m "Set up murmur"
     git branch -M main    # or the base branch your user chose
     git push -u origin HEAD
     ```

   - Any other repository: branch from the base branch on GitHub, push, and
     open a pull request. Your user's own changes stay where they are.

     ```bash
     git fetch origin main    # or the base branch your user chose
     git switch -c murmur-setup origin/main
     git add <the files the apply report lists>
     git commit -m "Set up murmur"
     git push -u origin murmur-setup
     gh pr create --fill
     ```

     Ask your user to merge it; never merge it yourself. Tell them they are now
     on the `murmur-setup` branch, and that `git switch -` takes them back.
4. Check the setup, and tell your user what it says:

   ```bash
   uv run ~/work/murmur/plugin/scripts/murmur_doctor.py
   ```

   Until the setup is merged, it warns that the base branch on GitHub does not
   have it yet. That warning goes away after the merge.

## 7. Tell your user what comes next

In a few lines:

- To load murmur's skills: in Claude Code, type `/reload-plugins`; in Codex,
  start a new session.
- Then they can ask for a team:
  `fan this out: add a dark mode switch to the settings page`. The agent shows
  a plan and starts nothing until they say go. Each lane opens a pull request;
  your user decides what merges. Without a farm, lanes run on this computer:
  side by side in Claude Code, one after another in Codex.
- `update murmur` updates everything later, and `murmur doctor` checks a
  repository at any time.
- A farm is optional: an always-on Linux machine that runs agents while their
  computer is off. Offer it. If they want one, go on to step 8.
- The handbook explains the method:
  <https://github.com/magik-ai/murmur/tree/main/docs>

## 8. A farm, only if your user wants one

Ask which way they prefer.

- **Rent a DigitalOcean server.** Follow the `farm` skill
  (`~/work/murmur/plugin/skills/farm/SKILL.md`). In Claude Code, your user can
  also type `/murmur:farm`. It needs a DigitalOcean account. It shows the
  monthly price and buys nothing until your user types that price back. At the
  end, the `fleet` command on this computer runs on the farm, so a team started
  here runs there. In Codex, your user approves the network prompts, and long
  steps take `--wait 50` and a rerun.
- **A Linux computer or server they already have**: Ubuntu 24.04 or newer, or
  Debian 12 or newer, with systemd. Ubuntu 22.04 works too, after one extra
  command for Python 3.11 that the installer prints. On that machine, logged in
  as their usual user and not root (over ssh for a server), your user runs:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
  ```

  It asks for their password and a few questions, and ends with the commands
  for the first agent. A server that has only `root` needs an ordinary user
  first: `adduser NAME && usermod -aG sudo NAME`, then log in as that user. If
  you yourself run on that machine, gh is signed in and `sudo -n true`
  succeeds, you may run the installer for them with `--yes`, which takes every
  default.
- **A Windows PC with WSL** works like a Linux computer, once systemd is on in
  WSL and two settings keep WSL running when its window closes:
  <https://github.com/magik-ai/murmur/blob/main/docs/12-the-machine.md#what-the-machine-must-be>.
- **A Mac cannot be a farm yet**
  ([#8](https://github.com/magik-ai/murmur/issues/8)). A Mac can rent a
  DigitalOcean farm and drive it.

Tell your user that farm agents run without permission prompts, so they can run
any command the farm's user can. The farm should hold only what the agents
need.

## Update, repair or uninstall

The `murmur` skill (`~/work/murmur/plugin/skills/murmur/SKILL.md`) has the
steps. To update: `git -C ~/work/murmur pull --ff-only`, then update the Claude
Code plugin or write the Codex skills again as in step 4, run step 6 again in
each repository, and pull on the farm too. To repair, run this file again from
the top.
