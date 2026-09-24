# farm

One command that turns a fresh Ubuntu or Debian machine (a spare PC, WSL2, a rented VPS) into a farm that runs agents:

```bash
curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
```

While this repository is private: `gh repo clone magik-ai/murmur && bash murmur/farm/install.sh`.

What it does, what it asks and what it costs to rent the box: `docs/12-the-machine.md`. Flags: `--yes` (no questions), `--org NAME`, `--no-tailscale`, `--help`.

A plain container is not a farm: in a fresh `ubuntu:24.04` container (checked 2026-09-24, as a non-root user with passwordless sudo) `--yes` stops at step 1/5 with `stop: no systemd here`, before it changes anything. That is intended, because the sweep, the daemon and the dashboard are systemd user services. Run it on a machine or VM that boots systemd, WSL2 included. Not yet run on a real VPS by a stranger.
