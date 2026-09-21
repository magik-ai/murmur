#!/usr/bin/env python3
"""`fleet status --json` payload: farm metrics/capacity + every lane record, machine-readable.

Imports metrics.collect() directly rather than piping the shell _metrics through `python -`
(that collides: `python -` reads its PROGRAM from stdin, leaving nothing for json.load). Stable
shape is the contract a dashboard outcome column and a future `fleet events` build on."""
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics  # noqa: E402

filt = sys.argv[1] if len(sys.argv) > 1 else ""
farm = metrics.collect()

lanes = []
for fp in sorted(glob.glob(os.path.join(os.environ["FLEET_STATE"], "state", "*.json"))):
    s = None
    last = None
    for attempt in range(2):
        try:
            with open(fp) as handle:
                s = json.load(handle)
            break
        except Exception as exc:
            last = exc
            if attempt == 0:
                time.sleep(0.01)
    if not isinstance(s, dict):
        print(f"fleet status: unreadable state record {fp}: {last}", file=sys.stderr)
        lanes.append({
            "slug": os.path.basename(fp)[:-5], "project": None, "lane": None,
            "status": "state_unreadable", "outcome": "unknown", "state_path": fp,
        })
        continue
    if filt and s.get("project") != filt:
        continue
    pr = s.get("pr_url") or ""
    lanes.append({
        "slug": s.get("slug"), "project": s.get("project"), "lane": s.get("lane"),
        "engine": s.get("engine"), "tier": s.get("effort") or s.get("model"),
        "status": s.get("status"), "outcome": s.get("outcome"),
        "pr": ("#" + pr.rsplit("/", 1)[-1]) if pr else None, "pr_url": pr or None,
        "restart": s.get("restart") or None, "done_when": s.get("done_when") or None,
        "issues": s.get("issues") or None, "scope": s.get("scope") or None,
        "spawned_by": s.get("spawned_by"), "started_at": s.get("started_at"),
        "respawn_count": s.get("respawn_count", 0), "activity": s.get("last_activity"),
    })

print(json.dumps({"farm": farm, "lanes": lanes}))
