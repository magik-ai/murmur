#!/usr/bin/env bash
# Bootstrap the fleet tool on this machine (a "farm": where headless agents run).
# Idempotent: safe to re-run after `git pull`.
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

PREFIX="$HOME/.local"
AUTOSWEEP=1
SKILLS=1
LOCAL=0
ENVFILE="${FLEET_CONFIG:-$HOME/.config/fleet}/env"
DID=()

usage() {
  cat <<'USAGE'
usage: ./install.sh [options]

  --prefix DIR      where the `fleet` launcher is linked (default: ~/.local, so ~/.local/bin/fleet)
  --no-autosweep    do not enable the 10-minute `fleet sweep` timer
  --no-skills       do not link the agent skills into ~/.claude/skills and ~/.agents/skills
  --local           single machine: no ssh shim advice, and the dashboard binds loopback
                    (FLEET_DASH_BIND=127.0.0.1 in ~/.config/fleet/env, which the units and
                    `fleet dashboard` both read)
  -h, --help        this text

With no options the install is a `fleet` launcher, the orchestrator skill, the two example
configs, FLEET_HOME in ~/.config/fleet/env, and autosweep on a timer.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)       [ $# -ge 2 ] || { echo "install.sh: --prefix needs a directory" >&2; exit 2; }
                    PREFIX="$2"; shift 2;;
    --prefix=*)     PREFIX="${1#*=}"; shift;;
    --no-autosweep) AUTOSWEEP=0; shift;;
    --no-skills)    SKILLS=0; shift;;
    --local)        LOCAL=1; shift;;
    -h|--help)      usage; exit 0;;
    *)              echo "install.sh: unknown option: $1" >&2; echo >&2; usage >&2; exit 2;;
  esac
done
PREFIX="${PREFIX/#\~/$HOME}"

# One key per line, KEY=VALUE, which is systemd EnvironmentFile syntax. Rewritten through a temp
# file rather than `sed -i`: that flag is GNU-only (this script runs on macOS too), and a value
# with a `|`, a `&` or a backslash in it would be interpreted as part of the replacement rather
# than written literally. Nothing here is interpolated into a pattern, so nothing needs escaping.
env_set() {
  local key="$1" value="$2" tmp line wrote=0
  mkdir -p "$(dirname "$ENVFILE")"
  [ -f "$ENVFILE" ] || printf '# fleet environment, read by the fleet systemd user units.\n' > "$ENVFILE"
  tmp="$(mktemp "${ENVFILE}.XXXXXX")"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "$key"=*) if [ "$wrote" = 0 ]; then printf '%s=%s\n' "$key" "$value"; wrote=1; fi ;;
      *)        printf '%s\n' "$line" ;;
    esac
  done < "$ENVFILE" > "$tmp"
  [ "$wrote" = 1 ] || printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENVFILE"
}

mkdir -p "$PREFIX/bin" ~/.config/fleet ~/.fleet/state ~/.fleet/logs ~/.fleet/worktrees ~/.fleet/briefs
ln -sfn "$HERE/bin/fleet" "$PREFIX/bin/fleet"
DID+=("fleet launcher       -> $PREFIX/bin/fleet")
# Every install: the user units resolve their scripts through FLEET_HOME, so the clone you
# installed from must be the clone they run. Two checkouts and only one of them ever writing
# this key is how a unit ends up running another tree's code.
env_set FLEET_HOME "$HERE"
DID+=("FLEET_HOME=$HERE -> $ENVFILE")
# Only what is run by its path. Every Python file is run through python3, and marking the library
# modules executable left a git checkout showing changes nobody made.
chmod +x "$HERE"/bin/fleet "$HERE"/dashboard/*.sh 2>/dev/null || true

if [ "$SKILLS" = 1 ]; then
  mkdir -p ~/.claude/skills
  ln -sfn "$HERE/skills/fleet" ~/.claude/skills/fleet
  DID+=("orchestrator skill   -> ~/.claude/skills/fleet")
  # Codex reads a user's skills from ~/.agents/skills, so the same playbook is linked there when
  # Codex is on this box (it makes ~/.codex when it first runs) or that folder is in use already.
  if [ -d ~/.codex ] || [ -d ~/.agents ] || command -v codex >/dev/null 2>&1 \
     || [ -x ~/.local/bin/codex ]; then
    if mkdir -p ~/.agents/skills 2>/dev/null \
       && ln -sfn "$HERE/skills/fleet" ~/.agents/skills/fleet 2>/dev/null; then
      DID+=("orchestrator skill   -> ~/.agents/skills/fleet (Codex)")
    else
      DID+=("orchestrator skill   -> could not link into ~/.agents/skills")
    fi
  fi
  # Earlier installs linked it into ~/.codex/skills, where Codex no longer looks. That link goes,
  # but only when it points into this clone: anything else there is not this script's.
  old_link=~/.codex/skills/fleet
  if [ -L "$old_link" ]; then
    case "$(readlink "$old_link")" in
      "$HERE"/*) rm -f "$old_link"; DID+=("old skill link       -> ~/.codex/skills/fleet removed");;
    esac
  fi
else
  DID+=("skills               -> skipped (--no-skills)")
fi

[ -f ~/.config/fleet/policy.toml ]   || cp "$HERE/config/policy.example.toml"   ~/.config/fleet/policy.toml
[ -f ~/.config/fleet/projects.toml ] || cp "$HERE/config/projects.example.toml" ~/.config/fleet/projects.toml
DID+=("config               -> ~/.config/fleet/{policy,projects}.toml (existing files kept)")

# Single-machine farm: nothing reaches this box from another host, so keep the dashboard on
# loopback and skip the shim advice.
if [ "$LOCAL" = 1 ]; then
  env_set FLEET_DASH_BIND 127.0.0.1
  DID+=("FLEET_DASH_BIND=127.0.0.1 -> $ENVFILE (local mode)")
fi

# Post-merge worktree janitor on a timer, so nobody has to remember `fleet sweep`.
if [ "$AUTOSWEEP" = 1 ]; then
  if "$HERE/bin/fleet" autosweep on >/dev/null 2>&1; then
    DID+=("autosweep            -> fleet sweep every 10 min")
  else
    DID+=("autosweep            -> could not enable (no systemd user manager?); run 'fleet sweep' yourself")
  fi
else
  DID+=("autosweep            -> skipped (--no-autosweep)")
fi

echo "fleet installed from $HERE"
for line in "${DID[@]}"; do echo "  $line"; done

case ":$PATH:" in
  *":$PREFIX/bin:"*) : ;;
  *) echo "NOTE: add $PREFIX/bin to PATH (e.g. echo 'export PATH=\"$PREFIX/bin:\$PATH\"' >> ~/.bashrc)";;
esac
if [ "$LOCAL" = 1 ]; then
  echo "NOTE: local mode records FLEET_DASH_BIND=127.0.0.1 in $ENVFILE, and 'fleet dashboard'"
  echo "      reads that file, so the board is reachable from this machine only. Widen it with"
  echo "      FLEET_DASH_BIND in the same file, then 'fleet dashboard restart'."
else
  # \$HOME stays escaped inside the shim, so it is the farm's home the command finds and not
  # the laptop's: the two differ whenever the laptop is a Mac or the user names differ.
  echo "From another machine, run fleet over ssh instead of installing it there. On that machine:"
  cat <<'SHIM'
mkdir -p ~/.local/bin
cat > ~/.local/bin/fleet <<'EOF'
#!/usr/bin/env bash
args=(); for a in "$@"; do args+=("$(printf %q "$a")"); done
exec ssh <FARM_HOST> "\$HOME/.local/bin/fleet ${args[*]}"
EOF
chmod +x ~/.local/bin/fleet     # <FARM_HOST> is an ssh host alias for this box
SHIM
fi
echo "next: register a project  ->  fleet add-project --name myproj --repo owner/name"
echo "      then                ->  fleet help"
