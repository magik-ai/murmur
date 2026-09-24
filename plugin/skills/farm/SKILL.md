---
name: farm
description: Get a farm on DigitalOcean from this laptop. Trigger on "murmur farm", "a farm in the cloud", "set up a farm", "one-click farm", "move my farm to DigitalOcean". Checks doctl, the ssh key and GitHub, asks a few questions with defaults, prints the plan and the price, buys the droplet only with the price typed back, installs murmur on it, and opens its dashboard through a private tunnel or Tailscale.
---

# Farm

You are getting one person a farm: a DigitalOcean droplet with murmur
installed, the dashboard running as a service, and the dashboard open in their
browser. Nothing listens on the internet but ssh. It takes a few minutes and
every step is safe to run again: a stopped run resumes where it stopped.

The script does the work. Every step is one call, and every call prints one
JSON object:

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py <step> [options]
```

- `said`: the sentence to give the person, in your own words if you like.
- `run_in_your_terminal`: commands the person runs in **their own terminal**.
  Show each one in a code block, exactly as printed, and wait for them to say
  it is done. Never run these yourself: they log in, and the logins happen
  where the person types, never here.
- `next`: the step to run next, when the script knows it.
- Exit code 0 is done, 2 is waiting on the person (do what `said` says, then
  run the same step again), 1 is a refusal (explain it; do not work around it).

Four rules hold for the whole run.

- **Never take a secret through this conversation.** No DigitalOcean token, no
  GitHub or Claude login, no Tailscale key, no passphrase, no dashboard token.
  If the person pastes one here, tell them to revoke it and make a new one.
- **Never spend money without the price typed back.** `plan` prints a sentence
  like "Create farm, $48 a month until you destroy it" and a quote. Show the
  sentence, ask the person to type the number back, and pass exactly what they
  typed as `--confirm-usd`, with the plan's `--quote`. A typed price buys one
  attempt only: if anything goes wrong, run `plan` again and ask again. The
  quote binds the whole plan (name, size, price, region, image, access, Codex,
  head office, cloud-init): if an answer changes after `plan`, run `plan` again.
- **Never invent an answer.** Every question goes to the person with its
  default shown; an empty reply means the default.
- **Never write a file the script should write**, never switch the person's
  doctl context, and never edit `~/.ssh/config` yourself.

Long steps (`apply`, `finish`, `logins` with a Codex lane) wait up to eight
minutes inside the call: run them with a Bash timeout of 600000 ms. If one
returns 2 with `next` naming itself, run it again; nothing is ever bought or
installed twice.

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

- doctl not installed: on macOS with Homebrew the check carries an `ask`.
  Ask the person; only on a yes run `preflight --install-doctl`. Elsewhere give
  them the install link it prints.
- doctl not logged in: the person runs `doctl auth init --context murmur` in
  their own terminal and pastes a DigitalOcean API token **there**. Their
  current doctl context stays what it was.
- no ssh key: the check carries an `ask`. On a yes run `preflight --make-key`
  (a key without a passphrase). A person who wants a passphrase makes the key in
  their own terminal and adds it to the agent.
- a key with a passphrase the agent does not hold: the person runs the printed
  `ssh-add` line in their own terminal. The script's ssh has no terminal, so the
  key must work without one.
- GitHub not logged in on this laptop: `gh auth login` in their terminal.

Run `preflight` again until it exits 0.

## 2. Questions

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py questions
```

A JSON list of what is still unanswered. Ask one question at a time, in order,
with its default and its choices; store each answer as it arrives:

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py answer --id size --value s-4vcpu-8gb
```

Say the size's price and note (the 2 vCPU size runs one or two agents at a
time). The access choices are only the ones this laptop can use: Tailscale is
offered only on a laptop that is on a tailnet, and never under WSL. A name that
a Host or Match line of the person's ssh config or the system config
(`/etc/ssh/ssh_config`), or a file either Includes, already names is refused, whatever that block says; read them the line and ask for
another.
`accounts` names the Claude subscriptions **after the first** (the first one is
the farm's default login). `hq_repo` is empty for a new head office of their
own, or owner/name to join an existing one.

"Where": this skill buys DigitalOcean droplets. For a machine the person
already has, it does not drive the install; tell them to run
`farm/install.sh` there (see the repository's README) and stop.

## 3. Plan

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py plan
```

Nothing is created. The plan first rehearses where ssh will really send the
name: the person's config with the block `ssh-config` will write, resolved with
`ssh -G`. If a line of their config would move it (another port or user, a key
offered first, a proxy), the plan refuses, gives no quote and names that line:
read it to them; once they change it, run `plan` again. Show the `sentence`, and offer the `commands` and the
`cloud_init` file for anyone who wants to read them. If `buys` is false and
`adopts` is true, one droplet already exists for this farm: run `apply` with no
price and no quote, and it adopts that droplet and buys nothing. If `adopts` is
false, more than one droplet has this farm's name and tag: show the person the
list in `said` and stop; nothing is bought or adopted until only one is left.

## 4. Apply

Only after the person typed the price back:

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py apply --confirm-usd 48 --quote <quote>
```

It checks the plan against the quote (any changed answer refuses: run `plan`
again), the price against the quote and the live price (any difference
refuses: run `plan` again), checks the firewall, creates the droplet, and
waits for its first boot. If
DigitalOcean's answer was lost, the attempt is pending, never failed: run
`apply` again (no price) and it adopts the droplet when it appears. If
`next` is `forget-attempt`, nothing appeared in ten minutes: run
`forget-attempt`, then `plan` again, and the person types the price again.

## 5. ssh

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py ssh-config
```

Writes the `Host <name>` block in its own marked section of `~/.ssh/config`,
checks ssh really goes there, and pins the new droplet's host key with the
first connection. A refusal here means something in the person's ssh config
wins over the section; read them the sentence.

The pin is kept for good: a rerun never removes it unless the droplet itself
changed (another id or address than the one pinned). If the farm shows another
key, ssh-config refuses; read the person the sentence and never remove the key
for them.

## 6. Finish

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py finish
```

The first time, it prints `ssh -t ... gh auth login` for the person's own
terminal: the farm needs its own GitHub login. When they say it is done, run
`finish` again: it clones murmur on the box and runs the installer, with no
questions, and the dashboard becomes a service.

## 7. Tailscale (only when chosen)

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py tailscale
```

The person makes a one-off auth key in their Tailscale admin page and saves it
in their own terminal as `~/.config/murmur/tailscale.key`, mode 600 (the
script prints the line). The key goes to the box over ssh, never through here.
If this laptop cannot reach the farm on the tailnet, the script says why and
switches to the tunnel by itself; tell the person which one they got.

## 8. Logins

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py logins
```

It prints one `ssh -t ... claude` line per Claude subscription (then `/login`
inside it), and, with Codex, the `codex login` line. The person runs each in
their own terminal, one at a time; run `logins` again until it exits 0. It
refuses when two subscriptions are signed in as the same email. With Codex and
a registered project, `logins --codex-lane <project> --by <code name>` runs one
real Codex lane to prove it works.

## 9. Open

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/murmur_farm.py open
```

Opens the dashboard in the person's browser, signed in: through a background
ssh tunnel bound to this laptop only, or at the farm's tailnet address. Run it
again any time to reopen (a dead tunnel is replaced); `open --stop` closes the
tunnel.

## When it is done

Tell the person, in plain words: where the dashboard is (`open` reopens it),
what the farm costs a month and that only destroying the droplet stops it
(`python3 ${CLAUDE_PLUGIN_ROOT}/lib/machines.py destroy <name> --confirm <name>`
from this laptop, which you run only when the person asks for it by name), and the
next steps: register a project on the farm (`ssh <name>
/home/farm/.local/bin/fleet add-project --name myproj --repo owner/name`) and
spawn the first lane.
