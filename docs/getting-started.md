# Getting started from zero

This guide takes you from a new Mac to a team of agents that open pull requests
on your repository. You do not need to know the terminal: copy each command,
paste it into Terminal and press Return.

You need:

- a GitHub account;
- a Claude subscription (Pro or Max);
- a Mac. On Linux or Windows, see [other computers](#other-computers).

Your Mac is where you give agents work and read what they did. Agents can run
right on it. A **farm**, an always-on machine that keeps agents working while
your Mac sleeps, is optional: part 4 rents one for you.

## Part 1. Set up the Mac

You do this once. It takes about 15 minutes.

1. Open Terminal: press Cmd+Space, type `Terminal` and press Return.
2. Install Homebrew, the tool that installs the other tools:

   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

   It asks for your Mac password. Nothing appears while you type it; that is
   normal. When it finishes, it prints a few lines under **Next steps**. Copy
   them, paste them and press Return.
3. Install git, GitHub's command-line tool `gh` and `uv`:

   ```bash
   brew install git gh uv
   ```

4. Install Claude Code:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```

   Then close Terminal and open it again, so that it finds the new command.
5. Sign in to GitHub:

   ```bash
   gh auth login
   ```

   Choose `GitHub.com`, then `HTTPS`, answer `Y`, then choose
   `Login with a web browser`. Copy the code it shows, press Return, and paste
   the code in the browser.
6. Sign in to Claude:

   ```bash
   claude
   ```

   The first time, it asks how to sign in. Choose your Claude subscription, not
   an API key, and finish in the browser. Then type `/exit`.

## Part 2. Set up your repository

7. Copy your repository to the Mac and go into its folder:

   ```bash
   gh repo clone your-name/your-repo
   cd your-repo
   ```

   No repository yet? Create one with `gh repo create my-app --private --clone`,
   then `cd my-app`.
8. Start Claude Code in that folder:

   ```bash
   claude
   ```

9. Type these four commands in Claude Code, one at a time:

   ```text
   /plugin marketplace add magik-ai/murmur
   /plugin install murmur@murmur
   /murmur:init
   /murmur:doctor
   ```

   `/murmur:init` asks seven questions. Answer `ok` to each one to keep the
   default. `/murmur:doctor` checks the setup and tells you if anything is
   missing. If Claude Code does not know `/murmur:init` yet, type
   `/reload-plugins` and try again.

## Part 3. Run your first team

You do not need a farm for this: the agents run on your Mac.

10. In Claude Code, describe a goal and ask for a team, for example:

    ```text
    fan this out: add a dark mode switch to the settings page
    ```

11. Claude splits the goal into lanes, one agent per task, and shows you the
    plan. Nothing starts until you say so. Type `go`.
12. Each agent works on its own branch and opens a pull request. Read them on
    GitHub. You decide what merges: tell Claude which pull requests to merge.

The agents stop while your Mac sleeps. For work that goes on overnight, add a
farm.

## Part 4. Add a farm (optional)

A farm is a Linux server that runs agents while your Mac sleeps. The easiest
farm is a DigitalOcean server that murmur rents and sets up for you.

13. Create an account at [digitalocean.com](https://www.digitalocean.com) and
    add a payment method.
14. In Claude Code, in your repository, type:

    ```text
    /murmur:farm
    ```

    It guides you through the rest, one step at a time:

    - It offers to install `doctl`, DigitalOcean's command-line tool. Say yes.
    - It asks you to create an API token on DigitalOcean (API, then Generate
      New Token) and to run `doctl auth init --context murmur` in Terminal.
      Paste the token in Terminal, never in the chat.
    - It offers to create an ssh key. Say yes.
    - It asks a few questions. The defaults are fine.
    - It shows the monthly price. Nothing is bought until you type that price
      back.
    - It creates the server, installs murmur on it, and gives you the commands
      that sign the server in to GitHub and Claude. Run them in Terminal.
    - It opens the farm's dashboard in your browser.

From then on, the lanes run on the farm. [Chapter 12](12-the-machine.md)
explains the farm in full.

## Other computers

- **A Mac mini, or another Mac that stays on.** Follow parts 1 to 3 on it: the
  agents run on it while it is awake. A Mac cannot be a farm yet, because the
  farm's services run on systemd, which only Linux has. Support for a Mac as a
  farm is planned.
- **A Linux computer** with Ubuntu 22.04 or newer, or Debian 12 or newer, can be
  a farm. Sign in as your usual user, not root, and run:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
  ```

  It installs everything and prints the next steps. [farm/](../farm/README.md)
  says what it does.
- **Windows.** Use WSL2 with Ubuntu, then follow the Linux steps.
  [Chapter 12](12-the-machine.md#what-the-machine-must-be) shows the two
  settings that keep it running.
- **A Linux laptop.** Install git, `gh` and `uv` with your package manager,
  Claude Code with the command in step 4, then continue with part 2.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| `command not found: brew` | Run the lines Homebrew printed under **Next steps**, or open a new Terminal window |
| `command not found: claude` | Close Terminal and open it again |
| Claude Code does not know `/murmur:init` | Type `/reload-plugins`, or type `/exit` and start `claude` again |
| `gh` says you are not logged in | Run `gh auth login` again |
