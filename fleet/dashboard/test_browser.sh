#!/usr/bin/env bash
# Browser level checks against the stub. The first two share one stub and one chromium, because
# starting either is the slow part. The hostile and screenshot passes start their own stub on
# their own port: one of them feeds routes answers the real server would never give, which the
# shared stub must not start doing for everyone else.
#
# Every test_hostile*.mjs and test_screens*.mjs here is run, by glob and not by name, so a lane
# that adds its own hostile or screenshot pass does not have to edit this file to have it run.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)

# A port nothing is listening on, asked of the kernel rather than guessed, so two lanes running
# this script on one machine never take the same socket and read each other's stub as a failure.
free_port() {
  python3 -c 'import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()'
}
PORT=${PORT:-$(free_port)}
python3 "$HERE/test_stub_server.py" "$PORT" & STUB=$!
trap 'kill $STUB 2>/dev/null' EXIT
sleep 2
# chromium needs the system libraries Playwright's browsers ship without. A host with no
# passwordless sudo keeps them unpacked under ~/.local/pwdeps, the path bin/fleet reads too;
# without them chromium exits 127 on libnspr4 and the failure reads as a broken page.
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$HOME/.local/pwdeps/root/usr/lib/x86_64-linux-gnu"
rc=0
DASH_URL="http://127.0.0.1:$PORT" node "$HERE/test_status_colours.mjs" || rc=1
DASH_URL="http://127.0.0.1:$PORT" node "$HERE/test_render_defer.mjs" || rc=1
# A free port of its own for each, so two lanes' checks can never collide on one socket.
for check in "$HERE"/test_hostile*.mjs "$HERE"/test_screens*.mjs; do
  [ -e "$check" ] || continue
  own_port=$(free_port)
  echo "--- $(basename "$check") on port $own_port"
  PORT=$own_port node "$check" || rc=1
done
exit $rc
