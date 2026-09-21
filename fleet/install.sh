#!/usr/bin/env bash
# Bootstrap the fleet tool on this machine (a "farm": where headless agents run).
# Idempotent: safe to re-run after `git pull`.
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

PREFIX="$HOME/.local"
AUTOSWEEP=1
SKILLS=1
PAPER=0
LOCAL=0
ENVFILE="${FLEET_CONFIG:-$HOME/.config/fleet}/env"
DID=()

usage() {
  cat <<'USAGE'
usage: ./install.sh [options]

  --prefix DIR      where the `fleet` launcher is linked (default: ~/.local, so ~/.local/bin/fleet)
  --no-autosweep    do not enable the 10-minute `fleet sweep` timer
  --no-skills       do not link the agent skills into ~/.claude/skills and ~/.codex/skills
  --with-paper      also install the optional Paper subsystem (contrib/paper): its two
                    systemd user units and its two skills. Off by default.
  --local           single machine: no ssh shim advice, and the dashboard binds loopback
                    (FLEET_DASH_BIND=127.0.0.1 in ~/.config/fleet/env, which the units and
                    `fleet dashboard` both read)
  -h, --help        this text

With no options the install is a `fleet` launcher, the orchestrator skill, the two example
configs, FLEET_HOME in ~/.config/fleet/env, and autosweep on a timer. It also removes any
Paper skill link that points into this checkout, since Paper is --with-paper now.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)       [ $# -ge 2 ] || { echo "install.sh: --prefix needs a directory" >&2; exit 2; }
                    PREFIX="$2"; shift 2;;
    --prefix=*)     PREFIX="${1#*=}"; shift;;
    --no-autosweep) AUTOSWEEP=0; shift;;
    --no-skills)    SKILLS=0; shift;;
    --with-paper)   PAPER=1; shift;;
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
# Every install, not only --with-paper: the user units resolve their scripts through FLEET_HOME,
# so the clone you installed from must be the clone they run. Two checkouts and only one of them
# ever writing this key is how a unit ends up running another tree's code.
env_set FLEET_HOME "$HERE"
DID+=("FLEET_HOME=$HERE -> $ENVFILE")
chmod +x "$HERE"/bin/fleet "$HERE"/lib/*.py "$HERE"/dashboard/*.sh "$HERE"/dashboard/*.py 2>/dev/null || true

if [ "$SKILLS" = 1 ]; then
  mkdir -p ~/.claude/skills
  ln -sfn "$HERE/skills/fleet" ~/.claude/skills/fleet
  DID+=("orchestrator skill   -> ~/.claude/skills/fleet")
  # Codex reads on-demand skills the same way, so link the same playbook if Codex is here
  if [ -d ~/.codex ]; then
    mkdir -p ~/.codex/skills
    ln -sfn "$HERE/skills/fleet" ~/.codex/skills/fleet 2>/dev/null || true
    DID+=("orchestrator skill   -> ~/.codex/skills/fleet")
  fi
else
  DID+=("skills               -> skipped (--no-skills)")
fi

[ -f ~/.config/fleet/policy.toml ]   || cp "$HERE/config/policy.example.toml"   ~/.config/fleet/policy.toml
[ -f ~/.config/fleet/projects.toml ] || cp "$HERE/config/projects.example.toml" ~/.config/fleet/projects.toml
DID+=("config               -> ~/.config/fleet/{policy,projects}.toml (existing files kept)")

# Optional Paper subsystem. Opt-in: a farm that never touches Paper installs none of it.
if [ "$PAPER" = 1 ]; then
  chmod +x "$HERE"/contrib/paper/scripts/*.py 2>/dev/null || true
  if [ "$SKILLS" = 1 ]; then
    ln -sfn "$HERE/contrib/paper/skills/paper"       ~/.claude/skills/paper
    ln -sfn "$HERE/contrib/paper/skills/paper-craft" ~/.claude/skills/paper-craft
    DID+=("paper skills         -> ~/.claude/skills/{paper,paper-craft}")
    if [ -d ~/.codex ]; then
      ln -sfn "$HERE/contrib/paper/skills/paper"       ~/.codex/skills/paper       2>/dev/null || true
      ln -sfn "$HERE/contrib/paper/skills/paper-craft" ~/.codex/skills/paper-craft 2>/dev/null || true
      DID+=("paper skills         -> ~/.codex/{paper,paper-craft}")
    fi
  fi
  ud="$HOME/.config/systemd/user"
  mkdir -p "$ud"
  cp "$HERE"/contrib/paper/systemd/paper-proxy.service "$HERE"/contrib/paper/systemd/paper-forward.service "$ud/"
  systemctl --user daemon-reload 2>/dev/null || true
  DID+=("paper units          -> $ud/paper-{proxy,forward}.service (not started)")
  DID+=("  start the queue    -> systemctl --user enable --now paper-proxy")
  DID+=("  remote Paper host  -> systemctl --user enable --now paper-forward")
else
  # Paper used to be installed unconditionally, so `git pull && ./install.sh` on an existing farm
  # would leave ~/.claude/skills/paper and paper-craft pointing at files that are no longer where
  # they were. A dangling skill symlink fails silently at load time, which is the worst way for an
  # agent to lose a capability. Only links into THIS checkout are touched.
  paper_unlinked=()
  for skdir in ~/.claude/skills ~/.codex/skills; do
    [ -d "$skdir" ] || continue
    for link in "$skdir"/paper*; do
      [ -L "$link" ] || continue
      case "$(readlink "$link")" in
        "$HERE"/*) rm -f "$link"; paper_unlinked+=("$link") ;;
      esac
    done
  done
  if [ ${#paper_unlinked[@]} -gt 0 ]; then
    DID+=("paper skills         -> removed ${#paper_unlinked[@]} link(s) into this checkout (re-run with --with-paper to keep them):")
    for link in "${paper_unlinked[@]}"; do DID+=("                          $link"); done
  fi
fi

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
  echo "From another machine, run fleet over ssh instead of installing it there:"
  echo "  printf '#!/usr/bin/env bash\\nargs=(); for a in \"\$@\"; do args+=(\"\$(printf %%q \"\$a\")\"); done\\nexec ssh <FARM_HOST> \"\$HOME/.local/bin/fleet \${args[*]}\"\\n' > ~/.local/bin/fleet"
  echo "  chmod +x ~/.local/bin/fleet     # <FARM_HOST> is an ssh host alias for this box"
fi
echo "next: register a project  ->  fleet add-project --name myproj --repo owner/name"
echo "      then                ->  fleet help"
