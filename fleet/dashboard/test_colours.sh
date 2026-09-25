#!/usr/bin/env bash
# The five status colours, against a stub carrying EVERY state. A live farm rarely shows all five
# at once, and "I could not find one to look at" is not evidence that it renders correctly.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=${PORT:-7901}
python3 "$HERE/test_stub_server.py" "$PORT" & STUB=$!
trap 'kill $STUB 2>/dev/null' EXIT
sleep 2
# chromium needs the system libraries Playwright's browsers ship without. A host with no
# passwordless sudo keeps them unpacked under ~/.local/pwdeps, the path bin/fleet reads too;
# without them chromium exits 127 on libnspr4 and the failure reads as a broken page.
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$HOME/.local/pwdeps/root/usr/lib/x86_64-linux-gnu"
DASH_URL="http://127.0.0.1:$PORT" node "$HERE/test_status_colours.mjs"
