---
name: farm
description: Get a farm on DigitalOcean from this laptop. Trigger on "murmur farm", "a farm in the cloud", "set up a farm", "one-click farm", "move my farm to DigitalOcean". Checks doctl, the ssh key and GitHub, asks a few questions with defaults, prints the plan and the price, buys the droplet only with the price typed back, installs murmur on it, and opens its dashboard through a private tunnel or Tailscale.
---

# Farm

You are getting one person a farm: a DigitalOcean droplet (a rented Linux
server) with murmur installed, the dashboard running as a service, and the
dashboard open in their browser. A firewall lets in ssh and nothing else. It
takes a few minutes, and every step is safe to run again: a stopped run
resumes where it stopped.

This skill only buys DigitalOcean droplets. If the person wants a farm on a
machine they already have, tell them to run `farm/install.sh` on that machine
(see `farm/README.md` in the murmur repository) and stop.

**Where the scripts are.** The commands below run murmur's scripts from
`${CLAUDE_PLUGIN_ROOT}`, the plugin's folder. Claude Code fills it in, and
murmur's skill installer for Codex writes it in. If it is ever empty, use
`~/work/murmur/plugin`, and clone murmur there first if that folder is missing:
`git clone https://github.com/magik-ai/murmur ~/work/murmur`.

The script does the work. Every step is one call, and every call prints one
JSON object:

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py <step> [options]
```

- `said`: the sentence to give the person, in your own words if you like.
- `run_in_your_terminal`: commands the person runs in **their own terminal**.
  Show each one in a code block, exactly as printed, and wait for them to say
  it is done. Never run these yourself: they log in, and a login happens where
  the person types, never here.
- `next`: the step to run next, when the script knows it.
- Exit code 0 means done. 2 means waiting on the person: do what `said` says,
  then run the same step again. 1 means refused: explain why, and do not work
  around it.

Four rules hold for the whole run.

- **Never take a secret through this conversation.** No DigitalOcean token, no
  GitHub or Claude login, no Tailscale key, no passphrase, no dashboard token.
  If the person pastes one here, tell them to revoke it and make a new one.
- **Never spend money without the price typed back.** `plan` prints a sentence
  like "Create farm, $48 a month until you destroy it" and a quote. Show the
  sentence, ask the person to type the number back, and pass exactly what they
  typed as `--confirm-usd`, together with the plan's `--quote`. A typed price
  buys one attempt only: if anything goes wrong, run `plan` again and ask
  again. The quote covers the whole plan (name, size, price, region, image,
  access, Codex, head office, cloud-init file). If an answer changes after
  `plan`, run `plan` again.
- **Never invent an answer.** Every question goes to the person with its
  default shown. A reply of `ok` or `default`, or an empty reply, means the
  default.
- **Never write a file the script should write.** Never switch the person's
  doctl context, and never edit `~/.ssh/config` yourself.

Some steps wait inside the call for up to eight minutes: `apply`, `finish`,
and `logins` when Codex is on. Give such a command ten minutes (in Claude Code,
a Bash timeout of 600000 ms). If your agent cuts commands off sooner, pass
`--wait 50` and run the step again while it returns 2. If a step returns 2 with
`next` naming itself, or the command times out, run the same step again.
Nothing is ever bought or installed twice.

## 0. Where the flow stands

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py status
```

`next` names the step to start from. On a first run it is `preflight`.

## 1. Preflight

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py preflight
```

Each entry of `checks` that is not `ok` says what is missing:

- doctl is not installed: on macOS with Homebrew, the check carries an `ask`.
  Ask the person, and only on a yes run `preflight --install-doctl`. Elsewhere,
  give them the install link the check prints.
- doctl is not logged in: the person runs the printed
  `doctl auth init --context murmur` line in their own terminal and pastes a
  DigitalOcean API token **there**. Their current doctl context stays what it
  was.
- there is no ssh key: the check carries an `ask`. On a yes run
  `preflight --make-key`, which makes a key without a passphrase. A person who
  wants a passphrase makes the key in their own terminal and adds it to the
  ssh agent.
- the key has a passphrase and the ssh agent does not hold it: the person runs
  the printed `ssh-add` line in their own terminal. The script's ssh has no
  terminal, so the key must work without one.
- GitHub is not logged in on this laptop: the person runs `gh auth login` in
  their own terminal.

Run `preflight` again until it exits 0.

## 2. Questions

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py questions
```

`questions` lists what is still unanswered. Ask one question at a time, in
order, with its default and its choices. Store each answer as it arrives:

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py answer --id size --value s-4vcpu-8gb
```

- `size`: say each size's price. Do not promise how many agents a size runs.
  The farm's installer sizes the memory limits to the machine: on the 2 vCPU
  size (4 GB), a new agent starts while 1 GB of memory is free. If
  `fleet capacity` on the farm still blocks on free memory, the person lowers
  `ram_min_gb` and `warn_ram_gb` in `~/.config/fleet/policy.toml` there.
- `access`: the choices are only the ones this laptop can use. Tailscale is
  offered only when this laptop is on a tailnet, and never under WSL.
- `name`: the script refuses a name that the person's ssh config or the
  system ssh config (`/etc/ssh/ssh_config`), or a file either one includes,
  already names in a Host or Match line. Read the person the line it quotes
  and ask for another name.
- `accounts`: the Claude subscriptions **after the first**. The first one is
  the farm's default login.
- `hq_repo`: empty for a new head office of their own, named
  `<their GitHub login>/agent-hq-office`, or `owner/name` to join an existing
  one. (The head office is a private GitHub repository the agents use for
  names, branch claims and messages.)

## 3. Plan

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py plan
```

Nothing is created. The plan first checks where ssh will really send the name:
it resolves the person's config, with the block `ssh-config` will write, using
`ssh -G`. If a line of their config would change where ssh goes (another port
or user, another key offered first, a proxy), the plan refuses, gives no quote
and names that line. Read it to them. Once they have changed it, run `plan`
again.

Show the `sentence`. Offer the `commands` and the `cloud_init` file to anyone
who wants to read them.

When `buys` is false, nothing will be bought:

- no `adopts` field: this farm already has a registry entry. Run `apply` with
  no price and no quote; it resumes the flow and buys nothing.
- `adopts` is true: one droplet already exists for this farm. Run `apply` with
  no price and no quote; it adopts that droplet and buys nothing.
- `adopts` is false: more than one droplet has this farm's name and tag. Show
  the person the list in `said` and stop. Nothing is bought or adopted until
  only one is left.

## 4. Apply

Only after the person has typed the price back:

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py apply --confirm-usd 48 --quote <quote>
```

It checks the answers against the quote, and the typed price against the
quoted price and the live price. Any difference refuses: run `plan` again.
Then it sets up the firewall, creates the droplet, and waits for its first
boot.

If DigitalOcean's answer to the create was lost, the attempt is pending, not
failed: run `apply` again, with no price, and it adopts the droplet when it
appears. If `next` is `forget-attempt`, no droplet appeared within ten
minutes: run `forget-attempt`, then `plan` again, and the person types the
price again.

## 5. ssh

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py ssh-config
```

It writes the `Host <name>` block in its own marked section of
`~/.ssh/config`, checks that ssh really goes there, and pins the new droplet's
host key on the first connection. A refusal here means something in the
person's ssh config wins over the section. Read them the sentence.

The pin is kept: a rerun removes it only when the droplet itself changed
(another droplet id or address than the one pinned). If the farm shows
another key, `ssh-config` refuses. Read the person the sentence, and never
remove the key for them.

## 6. Finish

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py finish
```

The first time, it prints an `ssh -t ... gh auth login` line for the person's
own terminal: the farm needs its own GitHub login. When they say it is done,
run `finish` again. It clones murmur on the farm and runs the installer with no
questions, and the dashboard becomes a service.

If the install fails, `said` gives its last lines and the log's path on the
farm. Once the cause is fixed, run `finish --reinstall`.

## 7. Tailscale (only when chosen)

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py tailscale
```

The person makes a one-off auth key in their Tailscale admin page and saves it
from their own terminal as `~/.config/murmur/tailscale.key`, mode 600. The
script prints the line to use. The key goes to the farm over ssh, never
through this conversation. If this laptop cannot reach the farm on the
tailnet, the script says why and switches to the ssh tunnel by itself. Tell the
person which one they got.

## 8. Logins

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py logins
```

It prints one `ssh -t ... claude` line per Claude subscription (the person
then types `/login` inside it) and, with Codex, a `codex login` line. The
person runs each in their own terminal, one at a time. Run `logins` again until
it exits 0. It refuses when two subscriptions are signed in with the same
email address. With Codex and a registered project,
`logins --codex-lane <project> --by <code name>` runs one real Codex lane (one
agent on one task) to prove that Codex works.

## 9. Open

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py open
```

It opens the dashboard in the person's browser, already signed in: through a
background ssh tunnel that listens on this laptop only, or at the farm's
tailnet address. Run it again any time to reopen; a dead tunnel is replaced.
`open --stop` closes the tunnel.

## When it is done

Tell the person, in plain words:

- where the dashboard is, and that `open` reopens it;
- what the farm costs a month, and that only destroying the droplet stops the
  cost. The command, run from this laptop, is
  `uv run --no-project --python 3.11 ${CLAUDE_PLUGIN_ROOT}/lib/machines.py destroy <name> --confirm <name>`.
  It needs Python 3.11 or newer, which uv provides; a Mac's own `python3` is
  older. Run it only when the person asks for it by name;
- the next steps: register a project on the farm
  (`ssh <name> /home/farm/.local/bin/fleet add-project --name myproj --repo owner/name`)
  and spawn the first lane.
