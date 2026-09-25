# farm

`install.sh` turns a fresh Ubuntu or Debian machine into a farm: an always-on Linux machine that runs coding agents. The machine can be a spare PC, WSL2 on Windows, or a rented server. Run it on that machine, as your ordinary user:

```bash
curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
```

Or from a clone of the repository: `gh repo clone magik-ai/murmur && bash murmur/farm/install.sh`.

It installs what the farm needs: git, tmux, curl, GitHub's `gh`, uv and Claude Code. It checks for Python 3.11 or newer. It clones murmur to `~/work/murmur` and installs the `fleet` and `hq` commands. It asks a few questions and runs the dashboard as a service. At the end it prints the Claude login and the commands for your first agent. It is safe to run again: it only does what is missing. For what it does and asks, and what a machine costs to rent, see [the machine](../docs/12-the-machine.md).

Agents on a farm run with Claude Code's permission prompts switched off and Codex's sandbox switched off, so they can run any command your user can. Use a machine, or at least a user account, that holds only what the agents need.

To get a farm on DigitalOcean from your laptop instead, use `/murmur:farm` from the [murmur plugin](../plugin/README.md). It creates the server and runs this installer there for you.

Flags:

- `--yes`: ask nothing; every question takes its default.
- `--hq-repo OWNER/NAME`: the head office repository to join (a private GitHub repository the agents use for names, branch claims and messages). The default is `<your GitHub login>/agent-hq-office`, created if it does not exist.
- `--org NAME`: the GitHub owner of the murmur repository to clone, for a fork. The default is `magik-ai`.
- `--no-tailscale`: never offer to install Tailscale.
- `--remote`: this machine is driven from your laptop. The dashboard's address is left as it is (loopback by default), Tailscale is not offered, and the last lines print the ssh tunnel that reaches the dashboard.
- `-h`, `--help`: print the usage text.

The farm needs systemd, because the dashboard, the sweep timer and the supervisor daemon run as systemd user services. A plain container is not a farm: in a fresh `ubuntu:24.04` container, `--yes` stops at step 1/5 with `stop: no systemd here`, before it changes anything. Run it on a machine or virtual machine that boots systemd.

WSL2 works, with two settings. By default, WSL stops a distribution soon after its last terminal closes, and systemd services do not keep it running. [The machine](../docs/12-the-machine.md#what-the-machine-must-be) shows the two settings that keep it on.
