#!/usr/bin/env python3
"""Serve the real dashboard page against a queue containing every verdict, so the colours can be
checked. The live farm has never had an `ejected` or `cancelled` card while I was looking, and
"I could not find one" is not the same as "it renders correctly"."""
import http.server
import json
import pathlib
import socketserver
import sys

# The page under test is the one next to this file: a hardcoded checkout path silently serves a
# DIFFERENT tree than the worktree you are testing, which is exactly how a green reading gets
# produced for code nobody ran.
PAGE = str(pathlib.Path(__file__).resolve().with_name("index.html"))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7901

STATES = ["passed", "passed_partial", "failed", "ejected", "cancelled", "conflict", "blocked"]
QUEUE = {
    "updated": 1785326000,
    "daemon_alive": True,
    "refresh_age": 4,
    "running": [],
    "queued": [],
    "recent": [
        {
            "id": f"ci-{i}-000000000000000000000",
            "project": "demo",
            "repo": "your-org/demo",
            "pr": 1000 + i,
            "branch": f"probe/{state}",
            "state": state,
            "reason": f"stub record in state {state}",
            "started": 1785326000,
            "ended": 1785326800,
            "tiers": [
                {"name": "changes", "state": "passed", "started": 1785326000, "ended": 1785326004},
                {"name": "backend", "state": "passed", "started": 1785326004, "ended": 1785326700},
            ],
            "uncovered": [],
        }
        for i, state in enumerate(STATES)
    ],
}


class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/ci/log"):
            return self._json({"id": "x", "tier": "backend", "content": "stub log body\n"})
        if self.path.startswith("/api/ci"):
            return self._json(QUEUE)
        if self.path.startswith("/api/"):
            return self._json({"agents": [], "farm": {}})
        body = open(PAGE, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), H) as srv:
    srv.serve_forever()
