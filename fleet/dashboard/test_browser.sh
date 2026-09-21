#!/usr/bin/env bash
# Browser level checks against the stub. They share one stub and one chromium, because starting
# either is the slow part. The screenshot pass starts its own stub on its own port, so it is run
# separately and writes its pictures outside the repository.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=${PORT:-7903}
python3 "$HERE/test_stub_server.py" "$PORT" & STUB=$!
trap 'kill $STUB 2>/dev/null' EXIT
sleep 2
# chromium needs the unpacked system libs the CI sandbox binds for its tiers, or it exits 127 on
# libnspr4 and the failure reads as a broken page.
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$HOME/.local/pwdeps/root/usr/lib/x86_64-linux-gnu"
rc=0
DASH_URL="http://127.0.0.1:$PORT" node "$HERE/test_verdict_colours.mjs" || rc=1
DASH_URL="http://127.0.0.1:$PORT" node "$HERE/test_render_defer.mjs" || rc=1
# These two start their own stub on their own port: one of them feeds routes answers the real
# server would never give, which the shared stub must not start doing for everyone else.
node "$HERE/test_hostile.mjs" || rc=1
node "$HERE/test_screens.mjs" || rc=1
exit $rc
