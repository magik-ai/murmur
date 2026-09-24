#!/usr/bin/env bash
# Start, stop, restart and inspect the fleet dashboard. It runs as the systemd user unit
# fleet-dashboard.service once `enable` has installed it (farm/install.sh does), so it survives a
# reboot; until then, in a detached tmux session.
#
# Two things an operator expects to work, and which only work because of what is below:
#
#   * `~/.config/fleet/env` is read here as well. It is the one file the fleet's systemd user
#     units take their overrides from, and `install.sh --local` records FLEET_DASH_BIND in it.
#     The dashboard is NOT a unit, so until this script read that file the recorded bind did
#     nothing at all and the claim in the installer was false. An explicit variable in the
#     environment still wins over the file: that is the operator asking for something now.
#   * `status` reports the socket the server is actually listening on, not the bind this shell
#     would have used. Those differ exactly when it matters, after a start with other settings.
#
# The write token is never put in the command string: the process table is world-readable, and a
# secret in argv is a secret everyone on the box has. It travels as an environment entry, or is
# read by the server itself from $FLEET_CONFIG/dash-token.
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
export FLEET_CONFIG="${FLEET_CONFIG:-$HOME/.config/fleet}"
ENVFILE="$FLEET_CONFIG/env"
# The session name is a variable so the suites can drive a dashboard of their own
# without touching the farm's.
SESSION="${FLEET_DASH_SESSION:-fleet-dashboard}"

# KEY=VALUE lines, systemd EnvironmentFile syntax. Only the dashboard's own keys are taken, and
# only when the caller did not set them, so `FLEET_DASH_BIND=0.0.0.0 fleet dashboard start` wins.
if [ -f "$ENVFILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue;; esac
    key="${line%%=*}"; value="${line#*=}"
    case "$key" in
      FLEET_DASH_BIND|FLEET_DASH_PORT|FLEET_DASH_TOKEN|FLEET_DASH_TITLE|FLEET_DASH_HQ_AGENT) ;;
      *) continue;;
    esac
    case "$value" in
      \"*\") value="${value#\"}"; value="${value%\"}";;
      \'*\') value="${value#\'}"; value="${value%\'}";;
    esac
    [ -n "${!key:-}" ] || export "$key=$value"
  done < "$ENVFILE"
fi

PORT="${FLEET_DASH_PORT:-7878}"
BIND="${FLEET_DASH_BIND:-127.0.0.1}"
UNIT="fleet-dashboard.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/$UNIT"
ENV_TOKEN="${FLEET_DASH_TOKEN:-}"
# What the page calls itself, and the name it signs office mail with. Both have defaults in the
# server; they are forwarded only when set, so an unset one stays the server's business.
TITLE="${FLEET_DASH_TITLE:-}"
HQ_AGENT="${FLEET_DASH_HQ_AGENT:-}"
TOKEN_FILE="$FLEET_CONFIG/dash-token"

_loopback() { case "$1" in 127.*|::1|localhost) return 0;; *) return 1;; esac; }
# The unit drives the dashboard once it is installed and a user manager answers.
_unit() { [ -f "$UNIT_FILE" ] && systemctl --user show-environment >/dev/null 2>&1; }
# FLEET_DASH_BIND=tailscale is resolved by the server at start; this is only what a person reads.
_shown_bind() {
  if [ "$BIND" = "tailscale" ]; then
    local ip; ip=$(tailscale ip -4 2>/dev/null | head -1 || true)
    printf '%s' "${ip:-tailscale}"
  else
    printf '%s' "$BIND"
  fi
}
# An IPv6 literal needs brackets in a URL, or the port reads as part of the address.
_url_host() { case "$1" in *:*) printf '[%s]' "$1";; *) printf '%s' "$1";; esac; }

# The token the server is using: an explicit one from the environment, else the one it minted
# into $FLEET_CONFIG/dash-token on its first start.
_token() {
  if [ -n "$ENV_TOKEN" ]; then printf '%s\n' "$ENV_TOKEN"; return 0; fi
  if [ -r "$TOKEN_FILE" ]; then
    local stored; stored="$(sed -n '1p' "$TOKEN_FILE")"
    if [ -n "$stored" ]; then printf '%s\n' "$stored"; return 0; fi
  fi
  return 1
}

# What the server is REALLY bound to, asked of the kernel. `ss` where it exists, /proc otherwise.
_live_socket() {
  local out=""
  if command -v ss >/dev/null 2>&1; then
    out=$(ss -ltnH "sport = :$PORT" 2>/dev/null | awk '{print $4}' | head -1)
  fi
  if [ -z "$out" ]; then
    out=$(python3 - "$PORT" <<'PY' 2>/dev/null || true
import ipaddress, struct, sys
port = int(sys.argv[1])
for path, size in (("/proc/net/tcp", 4), ("/proc/net/tcp6", 16)):
    try:
        lines = open(path).read().splitlines()[1:]
    except OSError:
        continue
    for line in lines:
        fields = line.split()
        if len(fields) < 4 or fields[3] != "0A":          # 0A = LISTEN
            continue
        raw, _, hexport = fields[1].partition(":")
        if int(hexport, 16) != port:
            continue
        packed = b"".join(struct.pack("<I", int(raw[i:i + 8], 16)) for i in range(0, len(raw), 8))
        addr = ipaddress.ip_address(packed[:size])
        print(f"[{addr}]:{port}" if addr.version == 6 else f"{addr}:{port}")
        raise SystemExit(0)
PY
)
  fi
  if [ -z "$out" ] && command -v lsof >/dev/null 2>&1; then
    # macOS and BSD have neither ss nor /proc/net/tcp
    out=$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9; exit}')
  fi
  if [ -z "$out" ] && tmux has-session -t "$SESSION" 2>/dev/null; then
    # last resort: the session exists, report the configured address
    out="$BIND:$PORT"
  fi
  [ -n "$out" ] || return 1
  printf '%s\n' "$out"
}

_access_note() {
  local token; token="$(_token || true)"
  if [ -n "$token" ]; then
    echo "  write access: bearer token required (open it once as http://$(_url_host "$(_shown_bind)"):$PORT/?token=\$(fleet dashboard token))"
  else
    echo "  write access: the server mints a token into $TOKEN_FILE on its first start; read it with 'fleet dashboard token'"
  fi
  if ! _loopback "$BIND"; then echo "  bound to $BIND, so reading needs the token too"; fi
}

# The same wait _start does for tmux: report the socket the kernel has, or say it is not there.
_wait_live() {
  local live=""
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    live="$(_live_socket || true)"
    [ -n "$live" ] && break
    sleep 0.5
  done
  printf '%s' "$live"
}

_enable() {
  local py; py="$(command -v python3)"
  [ -n "$py" ] || { echo "no python3 on PATH; the dashboard unit needs one" >&2; return 1; }
  local fleet; fleet="$(dirname "$HERE")"       # this checkout, never another tree's code
  mkdir -p "$UNIT_DIR"
  sed "s#__FLEET__#$fleet#g; s#__PY__#$py#g" "$fleet/systemd/$UNIT" > "$UNIT_FILE"
  systemctl --user daemon-reload
  # A dashboard still in tmux holds the port the unit needs.
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  for _ in 1 2 3 4 5; do _live_socket >/dev/null 2>&1 || break; sleep 1; done
  systemctl --user enable --now "$UNIT" >/dev/null 2>&1 \
    || { echo "could not enable $UNIT; see: systemctl --user status $UNIT" >&2; return 1; }
  echo "dashboard unit installed and enabled: $UNIT_FILE"
}

_start_unit() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    for _ in 1 2 3 4 5; do _live_socket >/dev/null 2>&1 || break; sleep 1; done
  fi
  systemctl --user start "$UNIT" \
    || { echo "could not start $UNIT; see: journalctl --user -u $UNIT" >&2; return 1; }
  local live; live="$(_wait_live)"
  if [ -z "$live" ]; then
    echo "dashboard unit started, but nothing listens on port $PORT yet: journalctl --user -u $UNIT says why (with FLEET_DASH_BIND=tailscale it waits for a tailnet address)" >&2
    return 1
  fi
  echo "dashboard up on $live ($UNIT)"
}

_start() {
  if _unit; then
    _start_unit || return 1
  elif tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "dashboard already running (tmux $SESSION); 'fleet dashboard restart' to pick up new settings"
  else
    # -e keeps every value out of the command string. An explicit token is passed this way; a
    # minted one is never passed at all, the server reads its own file.
    envargs=(-e "FLEET_CONFIG=$FLEET_CONFIG" -e "FLEET_DASH_PORT=$PORT" -e "FLEET_DASH_BIND=$BIND")
    if [ -n "$ENV_TOKEN" ]; then envargs+=(-e "FLEET_DASH_TOKEN=$ENV_TOKEN"); fi
    if [ -n "$TITLE" ]; then envargs+=(-e "FLEET_DASH_TITLE=$TITLE"); fi
    if [ -n "$HQ_AGENT" ]; then envargs+=(-e "FLEET_DASH_HQ_AGENT=$HQ_AGENT"); fi
    if ! tmux new-session -d -s "$SESSION" -c "$HERE" "${envargs[@]}" "python3 server.py" 2>/dev/null; then
      # tmux older than 3.2 has no `new-session -e`: export instead, still never argv.
      export FLEET_DASH_PORT="$PORT" FLEET_DASH_BIND="$BIND"
      if [ -n "$ENV_TOKEN" ]; then export FLEET_DASH_TOKEN="$ENV_TOKEN"; fi
      if [ -n "$TITLE" ]; then export FLEET_DASH_TITLE="$TITLE"; fi
      if [ -n "$HQ_AGENT" ]; then export FLEET_DASH_HQ_AGENT="$HQ_AGENT"; fi
      tmux new-session -d -s "$SESSION" -c "$HERE" "python3 server.py"
    fi
    live=""
    for _ in 1 2 3 4 5 6 7 8; do
      live="$(_live_socket || true)"
      [ -n "$live" ] && break
      sleep 0.5
    done
    if [ -z "$live" ]; then
      # Do not report a dashboard that is not there. The usual cause is a bind this box cannot
      # serve, and the tmux session is already gone with the message in it.
      echo "dashboard did NOT come up on $BIND:$PORT: check FLEET_DASH_BIND and the port" >&2
      return 1
    fi
    echo "dashboard up on $live"
  fi
  _access_note
  if ! _loopback "$BIND"; then
    ip=$(tailscale ip -4 2>/dev/null | head -1 || true)
    [ -n "$ip" ] && echo "  reachable on the tailnet:  http://$ip:$PORT"
  fi
}

case "${1:-start}" in
  start) _start ;;
  enable) _enable && _start ;;
  stop)
    if _unit; then
      systemctl --user stop "$UNIT" && echo "dashboard stopped ($UNIT; it starts again at boot)"
    else
      tmux kill-session -t "$SESSION" 2>/dev/null && echo "dashboard stopped" || echo "not running"
    fi
    ;;
  restart)
    if _unit; then systemctl --user stop "$UNIT" 2>/dev/null && echo "dashboard stopped" || true; fi
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "dashboard stopped" || true
    # The old server holds the port until its socket is released.
    for _ in 1 2 3 4 5; do _live_socket >/dev/null 2>&1 || break; sleep 1; done
    _start
    ;;
  status)
    if _unit; then
      live="$(_live_socket || true)"
      echo "$UNIT: $(systemctl --user is-active "$UNIT" 2>/dev/null || true)${live:+, listening on $live}"
    elif tmux has-session -t "$SESSION" 2>/dev/null; then
      live="$(_live_socket || true)"
      if [ -n "$live" ]; then
        echo "running on $live"
      else
        echo "running (tmux $SESSION), but nothing is listening on port $PORT - check 'fleet dashboard restart'"
      fi
    else
      live="$(_live_socket || true)"
      if [ -n "$live" ]; then
        echo "stopped (no tmux $SESSION), but something else is listening on $live"
      else
        echo "stopped"
      fi
    fi
    ;;
  token)
    if token="$(_token)"; then
      printf '%s\n' "$token"
    else
      echo "no dashboard token yet: start the dashboard once ('fleet dashboard start'), or set FLEET_DASH_TOKEN" >&2
      exit 1
    fi
    ;;
  *) echo "usage: run.sh start|stop|restart|status|token|enable";;
esac
