#!/usr/bin/env bash
# Browser-level dashboard checks against a stub carrying every verdict state. Kept together because
# both need the same stub and the same unpacked chromium libs.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=${PORT:-7903}
python3 "$HERE/test_stub_server.py" "$PORT" & STUB=$!
trap 'kill $STUB 2>/dev/null' EXIT
sleep 2
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$HOME/.local/pwdeps/root/usr/lib/x86_64-linux-gnu"
rc=0
DASH_URL="http://127.0.0.1:$PORT" node "$HERE/test_verdict_colours.mjs" || rc=1
DASH_URL="http://127.0.0.1:$PORT" node "$HERE/test_render_defer.mjs" || rc=1
exit $rc
