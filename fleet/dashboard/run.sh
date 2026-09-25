#!/usr/bin/env bash
# Start, stop, restart and inspect the fleet dashboard. It runs as the systemd user unit
# fleet-dashboard.service once `enable` has installed it (farm/install.sh does), so it survives a
# reboot; until then, in a detached tmux session.
#
# Three things an operator expects to work, and which only work because of what is below:
#
#   * `~/.config/fleet/env` is read here as well. It is the one file the fleet's systemd user
#     units take their overrides from, and `install.sh --local` records FLEET_DASH_BIND in it.
#     The dashboard is NOT a unit, so until this script read that file the recorded bind did
#     nothing at all and the claim in the installer was false. An explicit variable in the
#     environment still wins over the file: that is the operator asking for something now.
#   * `status` reports the socket the server is actually listening on, not the bind this shell
#     would have used. Those differ exactly when it matters, after a start with other settings.
#   * Running means answering. `status` says running only when the dashboard on that socket
#     answers, and `start` says the dashboard is up only once it answers and its token exists,
#     so `fleet dashboard token` works on the very next line. A tmux session is no proof: the
#     server in it may have died, and whatever else runs in it is not a dashboard.
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
# How many seconds `start` waits for the dashboard to answer. The server reads the machine once
# before it listens, a second or two, longer on a loaded box. A variable for the suites, like the
# session name, and for `fleet spawn`, which starts the dashboard without waiting for it (0).
WAIT="${FLEET_DASH_WAIT:-20}"
case "$WAIT" in ''|*[!0-9]*) WAIT=20;; esac

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
# What the server in tmux says also goes here. A server that stops before it answers takes its
# tmux session with it, and this file is where its last words are left for `start` to quote. The
# unit's go to the journal instead.
LOG="${FLEET_STATE:-$HOME/.fleet}/dashboard.log"

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
  # A tmux session with this name is not a listening socket, and it used to stand in for one:
  # a server that died at once, or a session running anything else, read as a dashboard.
  [ -n "$out" ] || return 1
  printf '%s\n' "$out"
}

# Where to ask a listening socket for an answer: its own address, or loopback for a wildcard,
# which answers for every interface of this machine.
_probe_host() { # host:port as the kernel printed it
  local host="${1%:*}"
  host="${host%%\%*}"; host="${host#[}"; host="${host%]}"
  case "$host" in ''|'*'|0.0.0.0) host=127.0.0.1;; ::) host=::1;; esac
  printf '%s' "$host"
}

# Whether a fleet dashboard answers at HOST:PORT. Something listening there may be another
# program; /api/version is the dashboard's own, served on every bind without a token. It is asked
# directly, never through a proxy: this is a call to this machine.
_answers() { # host port
  python3 - "$1" "$2" >/dev/null 2>&1 <<'PY'
import json
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]
if ":" in host:
    host = f"[{host}]"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(f"http://{host}:{port}/api/version", timeout=3) as reply:
        said = json.loads(reply.read(65536) or b"{}")
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if isinstance(said, dict) and "v" in said else 1)
PY
}

# Where the dashboard answers, or nothing: the socket the kernel has on the port, then an answer
# from the server behind it.
_serving() {
  local live; live="$(_live_socket || true)"
  [ -n "$live" ] || return 1
  _answers "$(_probe_host "$live")" "$PORT" || return 1
  printf '%s\n' "$live"
}

# Wait up to $WAIT seconds for the dashboard to answer with its token in place, and print where
# it answers (nothing when it did not). Given a tmux session, stop as soon as the session is gone:
# the server in it has exited, and no answer is coming.
_wait_up() { # [tmux session]
  local live="" deadline=$((SECONDS + WAIT))
  while :; do
    live="$(_serving || true)"
    if [ -n "$live" ] && _token >/dev/null; then break; fi
    [ "$SECONDS" -lt "$deadline" ] || break
    if [ -n "${1:-}" ] && ! tmux has-session -t "$1" 2>/dev/null; then break; fi
    sleep 0.5
  done
  printf '%s' "$live"
}

# The server's last line in the log its tmux session wrote.
_last_words() {
  [ -r "$LOG" ] || return 0
  grep -v '^[[:space:]]*$' "$LOG" 2>/dev/null | tail -n 1 || true
}

# What to do when the dashboard does not come up, for the kind of address it was given.
_bind_advice() {
  if [ "$BIND" = "tailscale" ]; then
    echo "  FLEET_DASH_BIND=tailscale needs this machine's Tailscale address: run 'sudo tailscale up', check it with 'tailscale ip -4', then 'fleet dashboard start' again" >&2
  elif ! _loopback "$BIND"; then
    echo "  FLEET_DASH_BIND=$BIND must be an address this machine has ('ip -brief address' lists them), with port $PORT free. Set FLEET_DASH_BIND in $ENVFILE to one of them, or to tailscale, or take the line out to stay on 127.0.0.1 and reach the page over ssh (ssh -N -L $PORT:127.0.0.1:$PORT <this machine>). Then run 'fleet dashboard start' again" >&2
  else
    echo "  on a loopback address the usual cause is another program on port $PORT ('ss -ltnp \"sport = :$PORT\"' names it): stop it, or set FLEET_DASH_PORT in $ENVFILE to a free port, then run 'fleet dashboard start' again" >&2
  fi
}

_access_note() {
  local token; token="$(_token || true)"
  if [ -n "$token" ]; then
    echo "  write access: bearer token required (open it once as http://$(_url_host "$(_shown_bind)"):$PORT/?token=\$(fleet dashboard token))"
  else
    # The server stores its token before it listens, so one that answers without it could not.
    echo "  READ-ONLY: the server could not store a write token in $TOKEN_FILE. Set FLEET_DASH_TOKEN in $ENVFILE, then run 'fleet dashboard restart'"
  fi
  if ! _loopback "$BIND"; then echo "  bound to $BIND, so reading needs the token too"; fi
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
  local live; live="$(_wait_up)"
  if [ -z "$live" ]; then
    echo "dashboard unit started, but no dashboard answered on port $PORT within $WAIT seconds: 'journalctl --user -u $UNIT' says why, and the unit tries again every 5 seconds" >&2
    _bind_advice
    return 1
  fi
  echo "dashboard up on $live ($UNIT)"
}

_start() {
  local live ip
  if _unit; then
    _start_unit || return 1
  elif tmux has-session -t "$SESSION" 2>/dev/null; then
    # Started a moment ago by another start, perhaps: it gets the same wait a new one would.
    live="$(_wait_up "$SESSION")"
    if [ -z "$live" ]; then
      if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "tmux session $SESSION is there, but no dashboard answers on port $PORT: 'fleet dashboard restart' starts a fresh one" >&2
      else
        echo "the dashboard in tmux $SESSION stopped before it answered: 'fleet dashboard start' starts a fresh one" >&2
      fi
      return 1
    fi
    echo "dashboard already running on $live (tmux $SESSION); 'fleet dashboard restart' to pick up new settings"
  else
    # -e keeps every value out of the command string. An explicit token is passed this way; a
    # minted one is never passed at all, the server reads its own file.
    envargs=(-e "FLEET_CONFIG=$FLEET_CONFIG" -e "FLEET_DASH_PORT=$PORT" -e "FLEET_DASH_BIND=$BIND"
             -e "PYTHONUNBUFFERED=1")
    if [ -n "$ENV_TOKEN" ]; then envargs+=(-e "FLEET_DASH_TOKEN=$ENV_TOKEN"); fi
    if [ -n "$TITLE" ]; then envargs+=(-e "FLEET_DASH_TITLE=$TITLE"); fi
    if [ -n "$HQ_AGENT" ]; then envargs+=(-e "FLEET_DASH_HQ_AGENT=$HQ_AGENT"); fi
    mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
    : > "$LOG" 2>/dev/null || true
    # What the server says goes to the pane and, through tee, to $LOG. The command is given to
    # tmux as separate words, which it runs as they are, with no shell of the user's in between.
    if ! tmux new-session -d -s "$SESSION" -c "$HERE" "${envargs[@]}" \
         sh -c 'python3 server.py 2>&1 | tee "$1"' sh "$LOG" 2>/dev/null; then
      # tmux older than 3.2 has no `new-session -e`: export instead, still never argv. One that
      # old may also take the command only as one string, for its shell to read.
      export FLEET_DASH_PORT="$PORT" FLEET_DASH_BIND="$BIND" PYTHONUNBUFFERED=1
      if [ -n "$ENV_TOKEN" ]; then export FLEET_DASH_TOKEN="$ENV_TOKEN"; fi
      if [ -n "$TITLE" ]; then export FLEET_DASH_TITLE="$TITLE"; fi
      if [ -n "$HQ_AGENT" ]; then export FLEET_DASH_HQ_AGENT="$HQ_AGENT"; fi
      tmux new-session -d -s "$SESSION" -c "$HERE" "python3 server.py 2>&1 | tee $(printf '%q' "$LOG")"
    fi
    live="$(_wait_up "$SESSION")"
    if [ -z "$live" ]; then
      # Do not report a dashboard that is not there. The usual cause is a bind this box cannot
      # serve; the server's reason is the last line it wrote before its session closed.
      local said; said="$(_last_words)"
      if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "dashboard did NOT answer on port $PORT within $WAIT seconds, and is still starting or stuck in tmux $SESSION ('tmux attach -t $SESSION' shows it)${said:+. Its last line: $said}" >&2
      else
        echo "dashboard did NOT come up on $(_url_host "$(_shown_bind)"):$PORT: the server stopped${said:+. It said: $said}" >&2
        _bind_advice
      fi
      return 1
    fi
    echo "dashboard up on $live"
  fi
  _access_note
  if ! _loopback "$BIND"; then
    ip=$(tailscale ip -4 2>/dev/null | head -1 || true)
    # An `if`, not `[ -n "$ip" ] && echo`: that line is the last of the function, and without
    # Tailscale its false test made every start on a wide address exit 1.
    if [ -n "$ip" ]; then echo "  reachable on the tailnet:  http://$ip:$PORT"; fi
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
    # Running only when the dashboard answers: a unit that is active, or a tmux session that is
    # there, can hold a server that died or never started.
    live="$(_serving || true)"
    if _unit; then
      state="$(systemctl --user is-active "$UNIT" 2>/dev/null || true)"
      if [ -n "$live" ]; then
        echo "$UNIT: ${state:-unknown}, running on $live"
      elif [ "$state" = "active" ] || [ "$state" = "activating" ]; then
        echo "$UNIT: $state, but no dashboard answers on port $PORT: 'journalctl --user -u $UNIT' says why"
      else
        echo "$UNIT: ${state:-unknown}, stopped"
      fi
    elif [ -n "$live" ]; then
      if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "running on $live"
      else
        echo "running on $live, but not in tmux $SESSION, so 'fleet dashboard stop' does not reach it"
      fi
    elif tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "not answering: tmux session $SESSION is there, but no dashboard answers on port $PORT; 'fleet dashboard restart' starts a fresh one"
    else
      other="$(_live_socket || true)"
      if [ -n "$other" ]; then
        echo "stopped (no tmux $SESSION), but something else is listening on $other"
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
