#!/usr/bin/env bash
# Verdict colours, against a stub carrying EVERY state. The live queue rarely holds an ejected or a
# cancelled card, and "I could not find one to look at" is not evidence that it renders correctly.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=${PORT:-7901}
python3 "$HERE/test_stub_server.py" "$PORT" & STUB=$!
trap 'kill $STUB 2>/dev/null' EXIT
sleep 2
# chromium needs the unpacked system libs the CI sandbox binds for its tiers, or it exits 127 on
# libnspr4 and the failure reads as a broken page.
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$HOME/.local/pwdeps/root/usr/lib/x86_64-linux-gnu"
DASH_URL="http://127.0.0.1:$PORT" node "$HERE/test_verdict_colours.mjs"
