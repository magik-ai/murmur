#!/usr/bin/env bash
# murmur farm installer: turn a fresh Ubuntu or Debian box into a machine that runs agents.
#
#   curl -fsSL https://raw.githubusercontent.com/magik-ai/murmur/main/farm/install.sh | bash
#
# or, while the repository is private and you were invited to it:
#
#   gh repo clone magik-ai/murmur && bash murmur/farm/install.sh
#
# It is idempotent: run it again after a change and it only does what is missing. Everything
# runs as your ordinary user; sudo is asked for only to install packages. It does five things:
#
#   1. system packages: git, tmux, python3 (3.11+), curl, GitHub's CLI
#   2. user services survive logout (loginctl enable-linger), uv, the Claude Code CLI
#   3. clones murmur (it carries the fleet and the head office CLI), installs both under ~/.local/bin
#   4. asks a few questions and writes the config: head office repository, owner, dashboard reach
#   5. prints the two logins only you can do (GitHub, Claude) and the first spawn
#
# Flags:
#   --yes            no questions, take every default (a single machine, dashboard on loopback)
#   --org NAME       GitHub owner (user or org) that holds the murmur repository; default magik-ai
#   --no-tailscale   never offer to install Tailscale
#   -h, --help       this text
#
# Windows: install WSL2 with Ubuntu first (wsl --install), then run this inside it.
# macOS: not supported as a farm yet; run the agents on a Linux box and drive it over ssh.
set -euo pipefail

ORG="magik-ai"
YES=0
OFFER_TAILSCALE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1;;
    --org) ORG="$2"; shift;;
    --no-tailscale) OFFER_TAILSCALE=0;;
    -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown flag: $1 (see --help)" >&2; exit 2;;
  esac
  shift
done

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf '\nstop: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Questions read from the terminal even when the script itself arrives on stdin (curl | bash).
ask() { # ask VAR "prompt" "default"
  local var="$1" prompt="$2" default="$3" answer=""
  if [ "$YES" = 1 ] || [ ! -e /dev/tty ]; then
    printf -v "$var" '%s' "$default"; note "$prompt: $default (default)"; return
  fi
  printf '  %s [%s]: ' "$prompt" "$default" > /dev/tty
  IFS= read -r answer < /dev/tty || answer=""
  printf -v "$var" '%s' "${answer:-$default}"
}

# ---------------------------------------------------------------------------------------------
say "1/5  System"
[ "$(id -u)" != 0 ] || die "run this as an ordinary user, not root: the agents run as you"
if ! have apt-get; then die "this installer knows Ubuntu and Debian (apt). On another Linux, follow docs/12-the-machine.md by hand"; fi
if ! have systemctl; then die "no systemd here. The farm needs it for services that outlive your ssh session"; fi
if grep -qi microsoft /proc/version 2>/dev/null; then note "WSL2 detected: fine, this is how the reference farm runs"; fi

missing=()
for pkg in git tmux python3 curl ca-certificates; do dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg"); done
if [ ${#missing[@]} -gt 0 ]; then
  note "installing: ${missing[*]}"
  sudo apt-get update -qq >/dev/null && sudo apt-get install -y -qq "${missing[@]}" >/tmp/murmur-apt.log 2>&1 || { tail -5 /tmp/murmur-apt.log; die "apt could not install ${missing[*]}"; }
fi
pyv=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "python3 is $pyv; the head office CLI needs 3.11 or newer (Ubuntu 24.04 ships 3.12)"
note "python3 $pyv"

if ! have gh; then
  note "installing GitHub's CLI from its own repository"
  sudo mkdir -p -m 755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
  sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt-get update -qq >/dev/null && sudo apt-get install -y -qq gh >>/tmp/murmur-apt.log 2>&1 || { tail -5 /tmp/murmur-apt.log; die "apt could not install gh"; }
fi
note "gh $(gh --version | head -1 | awk '{print $3}')"

# ---------------------------------------------------------------------------------------------
say "2/5  Your user: services that outlive a login, uv, Claude Code"
if loginctl show-user "$USER" >/dev/null 2>&1; then
  if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
    loginctl enable-linger "$USER" && note "linger on: the sweep, the daemon and the dashboard keep running after you log out"
  else
    note "linger already on"
  fi
else
  note "WARNING: no systemd user session for $USER; log in over ssh once and rerun, or run: sudo loginctl enable-linger $USER"
fi
mkdir -p "$HOME/.local/bin"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
  export PATH="$HOME/.local/bin:$PATH"
  grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  note "added ~/.local/bin to PATH in ~/.bashrc";;
esac

if ! have uv; then
  curl -LsSf https://astral.sh/uv/install.sh | sh -s -- --quiet >/dev/null 2>&1 || die "uv did not install; see https://docs.astral.sh/uv/"
  export PATH="$HOME/.local/bin:$PATH"
fi
note "uv $(uv --version | awk '{print $2}')"

if ! have claude; then
  note "installing Claude Code (the agent CLI)"
  curl -fsSL https://claude.ai/install.sh | bash >/dev/null 2>&1 || die "Claude Code did not install; see https://docs.anthropic.com/en/docs/claude-code/setup"
  export PATH="$HOME/.local/bin:$PATH"
fi
have claude && note "claude $(claude --version 2>/dev/null | head -1)"

# ---------------------------------------------------------------------------------------------
say "3/5  The fleet and the head office CLI"
if ! gh auth status >/dev/null 2>&1; then
  if [ "$YES" = 1 ] || [ ! -e /dev/tty ]; then
    die "gh is not logged in. Run: gh auth login   (choose HTTPS, let it configure git), then rerun this script"
  fi
  note "GitHub login: choose GitHub.com, HTTPS, and let it set up git credentials"
  gh auth login < /dev/tty || die "GitHub login did not finish"
fi
gh_user=$(gh api user --jq .login 2>/dev/null || echo "?")
note "GitHub: signed in as $gh_user"

mkdir -p "$HOME/work"
clone_or_pull() { # clone_or_pull repo dir
  if [ -d "$2/.git" ]; then
    git -C "$2" pull -q --ff-only 2>/dev/null || note "WARNING: could not fast-forward $2, left as is"
    note "$1: updated"
  else
    gh repo clone "$1" "$2" -- -q || die "cannot clone $1. Were you invited to it? Check: gh repo view $1"
    note "$1: cloned to $2"
  fi
}
clone_or_pull "$ORG/murmur" "$HOME/work/murmur"
FLEET_SRC="$HOME/work/murmur/fleet"
HQ_SRC="$HOME/work/murmur/hq"
[ -f "$FLEET_SRC/install.sh" ] && [ -f "$HQ_SRC/bin/hq" ] || die "the murmur clone has no fleet/ or hq/ directory; is $ORG/murmur the right repository?"

single="yes"
ask single "Is this the only machine, with you working on it directly? (yes = dashboard stays local)" "yes"
if [ "$single" = "yes" ] || [ "$single" = "y" ]; then
  (cd "$FLEET_SRC" && ./install.sh --local >/tmp/murmur-fleet-install.log 2>&1) || { tail -20 /tmp/murmur-fleet-install.log; die "fleet install failed (log above)"; }
else
  (cd "$FLEET_SRC" && ./install.sh >/tmp/murmur-fleet-install.log 2>&1) || { tail -20 /tmp/murmur-fleet-install.log; die "fleet install failed (log above)"; }
fi
note "fleet: $(grep -c . /tmp/murmur-fleet-install.log) lines of install report in /tmp/murmur-fleet-install.log"
(cd "$HQ_SRC" && python3 bin/hq install >/dev/null) || die "hq install failed"
note "hq: linked into ~/.local/bin"

# ---------------------------------------------------------------------------------------------
say "4/5  Configuration"
hq_conf="${XDG_CONFIG_HOME:-$HOME/.config}/hq/config.toml"
if [ -f "$hq_conf" ]; then
  note "head office already configured in $hq_conf, left alone"
else
  note "The head office is a small PRIVATE GitHub repository where agents register, claim branches and"
  note "leave each other mail. Everyone who can read it can read the mail, so keep it private."
  office="$gh_user/agent-hq-office"
  ask office "Head office repository (owner/name; created if missing)" "$office"
  owner="$gh_user"
  ask owner "Your own code name as the owner (claims warn you instead of blocking you)" "$owner"
  if ! gh repo view "$office" >/dev/null 2>&1; then
    gh repo create "$office" --private --description "murmur head office: agent sessions, branch claims, mail" >/dev/null \
      && note "created private repository $office" \
      || die "could not create $office; create it by hand and rerun"
  fi
  hq init --repo "$office" --owner "$owner" >/dev/null && note "hq config written to $hq_conf"
fi

fleet_env="${FLEET_CONFIG:-$HOME/.config/fleet}/env"
farm_alias="farm"
ask farm_alias "The ssh alias you will use for this box from your laptop" "farm"
grep -q '^FLEET_FARM_ALIAS=' "$fleet_env" 2>/dev/null || echo "FLEET_FARM_ALIAS=$farm_alias" >> "$fleet_env"

policy="${FLEET_CONFIG:-$HOME/.config/fleet}/policy.toml"
if ! grep -q '^\[hq\]' "$policy" 2>/dev/null; then
  printf '\n[hq]\nenabled = true\n' >> "$policy"
  note "policy.toml: head office on for every lane"
fi
# The shipped limits assume a big box (spawns stop below 6 GB free). Size them to this machine
# once, so a small VPS can spawn at all; the numbers are yours to tune in policy.toml afterwards.
if ! grep -q '^\[limits\]' "$policy" 2>/dev/null; then
  total_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0)
  cpus=$(nproc 2>/dev/null || echo 2)
  if [ "$total_gb" -gt 0 ] && [ "$total_gb" -lt 12 ]; then
    floor=$(( total_gb / 4 )); [ "$floor" -ge 1 ] || floor=1
    warn=$(( floor + 1 ))
    agents=$(( cpus * 2 )); [ "$agents" -ge 2 ] || agents=2
    printf '\n[limits]\nram_min_gb = %s\nwarn_ram_gb = %s\nmax_agents = %s\n' "$floor" "$warn" "$agents" >> "$policy"
    note "policy.toml: limits sized for ${total_gb} GB and ${cpus} CPUs (spawns stop below ${floor} GB free, at most ${agents} agents)"
  fi
fi

if [ "$single" != "yes" ] && [ "$single" != "y" ] && [ "$OFFER_TAILSCALE" = 1 ]; then
  ts="yes"
  ask ts "Reach the dashboard over Tailscale (a private network between your devices; free for personal use)?" "yes"
  if [ "$ts" = "yes" ] || [ "$ts" = "y" ]; then
    have tailscale || { curl -fsSL https://tailscale.com/install.sh | sh >/dev/null 2>&1 || note "WARNING: Tailscale did not install; see https://tailscale.com/download"; }
    if have tailscale; then
      note "run once, and follow the link it prints:  sudo tailscale up"
      grep -q '^FLEET_DASH_BIND=' "$fleet_env" 2>/dev/null || echo "FLEET_DASH_BIND=0.0.0.0" >> "$fleet_env"
      note "dashboard will listen on every interface and ask for its token; on Tailscale that is only your devices"
    fi
  else
    note "dashboard stays on loopback; reach it with an ssh tunnel:  ssh -N -L 7878:127.0.0.1:7878 $farm_alias"
  fi
fi

# ---------------------------------------------------------------------------------------------
say "5/5  Done. Two logins only you can do, then the first agent"
cat <<EOF

  1. Log the agent CLI into your Claude subscription (never an API key; the fleet refuses keys):
       claude          then type  /login  and follow the link
     On a remote box:  ssh -t $farm_alias claude

  2. Register the repository the agents will work on:
       fleet add-project --name myproj --repo owner/name

  3. Say hello to the head office and spawn the first lane:
       hq hello $USER-1 --task "first spawn"
       fleet capacity
       fleet spawn --project myproj --lane hello --model sonnet --by $USER-1 \\
             --task "Add a line to README.md saying this repository is run by agents as a team. Open a pull request."
       fleet status

  Dashboard:  fleet dashboard start     then   fleet dashboard token
  Check:      fleet capacity   hq whoami   gh auth status
  Upgrade:    git -C ~/work/murmur pull    (both tools run from that clone)
  Read next:  ~/work/murmur/docs/12-the-machine.md
EOF
