# farm

One command that turns a fresh Ubuntu or Debian machine (a spare PC, WSL2, a rented VPS) into a farm that runs agents:

```bash
curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
```

While this repository is private: `gh repo clone magik-ai/murmur && bash murmur/farm/install.sh`.

What it does, what it asks and what it costs to rent the box: `docs/12-the-machine.md`. Flags: `--yes` (no questions), `--org NAME`, `--no-tailscale`, `--help`.

Tested on a fresh Ubuntu 24.04 container (2026-09-21): steps one to five run to the end with `--yes`; the linger step warns where no systemd user session exists, as in a container. Not yet run on a real VPS by a stranger.
