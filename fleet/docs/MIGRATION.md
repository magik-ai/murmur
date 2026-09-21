# Migrating a farm that was running fleet before this branch

Nothing here is needed on a fresh install: a new farm gets these defaults and never notices. This
page is for a machine that has been running an older fleet, where behaviour used to be hardcoded
and is now configuration. Skip a row and the farm keeps running, but that row's behaviour changes.

Work through it once, after `git pull && ./install.sh`, and before the next spawn.

## 1. Head office (agent-hq)

Head office used to be unconditional. It is now gated on the `hq` binary plus `~/.config/fleet/policy.toml`:

```toml
[hq]
enabled = true
```

With the binary on PATH and NO `[hq]` table, fleet keeps head office on and warns once per spawn.
Write the table to settle it, `false` if this farm does not use head office. A box with no `hq`
binary needs nothing.

## 2. Commit identity for lanes

The author and email a lane commits under are now formats in policy.toml. The defaults are
`{agent} (agent)` and `{agent}@agents.local`, so a bare machine with no `git config user.email` can
still commit. If your farm has been pushing under a real address, write the old shapes down or the
authorship of every future lane commit changes:

```toml
[identity]
author_format = "{agent} (agent)"
email_format  = "you+{agent}@example.com"
```

`{agent}` is the lane's code name (`--by`, falling back to the lane name).

## 3. The dashboard bind and its write token

Two changes, both visible from the first `fleet dashboard start`:

- **Bind.** The server binds `FLEET_DASH_BIND`, default `127.0.0.1`. A farm that was reached over a
  tailnet or a LAN must say so, in `~/.config/fleet/env` (which `dashboard/run.sh` now sources):

  ```
  FLEET_DASH_BIND=0.0.0.0
  ```

  `./install.sh --local` writes the loopback value for a single-machine farm. An IPv6 literal
  (`::1`, `::`) is served on an AF_INET6 socket.

- **Token.** Every mutating route now needs a bearer token, loopback or not, and a cross-site
  request is refused whatever token it carries. On first start, if `FLEET_DASH_TOKEN` is unset,
  the server mints one into `$FLEET_CONFIG/dash-token` (mode 600). Read it with

  ```bash
  fleet dashboard token
  ```

  and open the page once as `http://<bind>:7878/?token=<token>`; the tab keeps it. On a
  non-loopback bind the token covers reads too, so a stranger on the network cannot list your
  lanes, their briefs and their results. Pin your own value by exporting `FLEET_DASH_TOKEN`
  (or adding it to `~/.config/fleet/env`) instead of using the generated one.

Restart the dashboard after changing either: `fleet dashboard restart`.

## 4. Sensors

Both hardware sensors are optional and are no longer guessed at a path:

```
FLEET_NVIDIA_SMI=/usr/lib/wsl/lib/nvidia-smi     # only when nvidia-smi is not on PATH
FLEET_LHM_URL=http://<host>:8085/data.json       # LibreHardwareMonitor, for CPU temperature
```

Unset, `fleet mode auto` has no GPU signal, says so once and stays on `full`; CPU temperature
reads UNKNOWN and never blocks a spawn. Put them in `~/.config/fleet/env`.

## 5. The farm's own ssh name

`fleet accounts add` and the dashboard print an `ssh <host>` command for the interactive login.
The host they print is `FLEET_FARM_ALIAS`, falling back to the machine's hostname, which is
usually not how you reach it:

```
FLEET_FARM_ALIAS=farm        # the ssh host alias YOU use for this box
```

## 6. Paper is contrib now, and opt-in

The Paper subsystem moved to `contrib/paper/` and installs only under `./install.sh --with-paper`.
A plain re-run of the installer REMOVES `~/.claude/skills/paper`, `~/.claude/skills/paper-craft`
and their `~/.codex` twins when they point into this checkout, and says so. Re-run with
`--with-paper` to keep them. The two systemd units (`paper-proxy`, `paper-forward`) are left alone
either way; stop and disable them yourself if this farm no longer uses Paper.

`FLEET_HOME` is now written to `~/.config/fleet/env` on every install, not only with
`--with-paper`, so the user units always resolve their scripts against the checkout you installed
from. If you run two clones, the last `./install.sh` wins: that is the one the units follow.

## 7. Project ports

`[<project>.ports]` in `projects.toml` sets the dev-server, API and e2e port bases per project.
With no table a project keeps the numbers fleet used when they were hardcoded (5200 / 8100 / 6100),
so an existing registry needs no edit.

## Check it landed

```bash
fleet spawn --project <P> --lane check --task "..."   # no hq warning, and the identity you expect
fleet dashboard restart && fleet dashboard status     # the live socket, not the environment
fleet dashboard token                                 # the write token
git -C ~/.fleet/worktrees/<P>/<slug> config --worktree user.email
```

If your dashboard is started by a systemd unit outside this repository, `fleet dashboard restart` does not reach it: restart that unit instead, after putting the bind and the token into its environment. The same goes for a daemon unit of your own: the `fleet` command reads `~/.config/fleet/env` itself, a Python service started directly by systemd does not, so give such a unit `EnvironmentFile=-%h/.config/fleet/env` in a drop-in.
