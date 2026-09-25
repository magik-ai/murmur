#!/usr/bin/env python3
"""fleet event stream: one append-only ~/.fleet/events.jsonl that replaces mtime-polling
of per-lane logs. Producers (the parsers, the supervisor, spawn) append typed events; consumers
read them with `fleet events --since <cursor> [--follow] [--lane X] [--project P]`.

Why a log, not RSS/subscriptions: filtering "my lanes" is a stateless flag — every event carries
lane+project, so a consumer selects what it wants without any subscription registry to leak or
desync. `--since` is a resume cursor (read only what's new); `--follow` streams (block, like
tail -f) so an agent *reads* events as they happen instead of polling.

append_event is BEST-EFFORT and never raises — it runs inside the live parsers on the hot farm,
so a full disk or a race must never crash a lane. Writers share a short flock so rotation and
the following append are one operation; event payloads stay small."""
import fcntl
import json
import os
import time

STATE = os.path.expanduser(os.environ.get("FLEET_STATE", "~/.fleet"))
EVENTS = os.path.join(STATE, "events.jsonl")
ROTATED_EVENTS = EVENTS + ".1"
EVENTS_LOCK = EVENTS + ".lock"
MAX_BYTES = int(os.environ.get("FLEET_EVENTS_MAX_BYTES", str(8 * 1024 * 1024)))


def append_event(slug, rec, kind, **extra):
    """Append one typed event. Never raises. Keep the payload small (< 4KB) so O_APPEND stays
    atomic across concurrent lane writers."""
    try:
        ev = {"ts": int(time.time()), "kind": kind, "slug": slug,
              "lane": rec.get("lane"), "project": rec.get("project")}
        for k, v in extra.items():
            if v is not None:
                ev[k] = (v[:200] if isinstance(v, str) else v)
        payload = (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
        os.makedirs(STATE, exist_ok=True)
        with open(EVENTS_LOCK, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current_size = os.path.getsize(EVENTS) if os.path.exists(EVENTS) else 0
            if current_size and current_size + len(payload) > MAX_BYTES:
                os.replace(EVENTS, ROTATED_EVENTS)
                directory_fd = os.open(STATE, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            with open(EVENTS, "ab") as f:
                f.write(payload)
    except Exception:
        pass


def _iter_file(fh):
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def read_events(since=0, lane=None, project=None, kinds=None, follow=False, poll=1.0):
    """Yield events matching the filters. `since` is a unix ts (exclusive). With follow=True, block
    and keep yielding new events as producers append them (tail -f semantics)."""
    def keep(ev):
        if ev.get("ts", 0) <= since:
            return False
        if lane and ev.get("lane") != lane:
            return False
        if project and ev.get("project") != project:
            return False
        if kinds and ev.get("kind") not in kinds:
            return False
        return True

    if not os.path.exists(EVENTS) and not os.path.exists(ROTATED_EVENTS):
        if not follow:
            return
        # wait for the file to appear
        while follow and not os.path.exists(EVENTS):
            time.sleep(poll)

    if os.path.exists(ROTATED_EVENTS):
        with open(ROTATED_EVENTS) as history:
            for ev in _iter_file(history):
                if keep(ev):
                    yield ev

    if not follow and not os.path.exists(EVENTS):
        return
    while follow and not os.path.exists(EVENTS):
        time.sleep(poll)

    fh = open(EVENTS)
    try:
        for ev in _iter_file(fh):
            if keep(ev):
                yield ev
        if not follow:
            return
        # stream new appends from the current offset
        while True:
            where = fh.tell()
            line = fh.readline()
            if not line:
                try:
                    rotated = os.fstat(fh.fileno()).st_ino != os.stat(EVENTS).st_ino
                except OSError:
                    rotated = True
                if rotated:
                    fh.close()
                    while not os.path.exists(EVENTS):
                        time.sleep(poll)
                    fh = open(EVENTS)
                    continue
                time.sleep(poll)
                fh.seek(where)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if keep(ev):
                yield ev
    finally:
        fh.close()


def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="fleet events")
    ap.add_argument("--since", type=int, default=0, help="unix ts; only events strictly after it")
    ap.add_argument("--lane", default=None)
    ap.add_argument("--project", default=None)
    ap.add_argument(
        "--kind", default=None,
        help=("comma list: status,spawned,delivered,respawned,respawn-failed,gate-fired,"
              "gate-read-failed,gate-invalid,gate-ambiguous,gate-remove-failed,"
              "gate-accounting-failed,gate-spawn-failed,lane-lock-failed,dropped-scope,"
              "state-read-failed,state-write-failed,ledger-read-failed,ledger-write-failed"),
    )
    ap.add_argument("--follow", action="store_true", help="stream new events (blocks)")
    ap.add_argument("--json", action="store_true", help="raw json lines (default: human)")
    a = ap.parse_args(argv)
    kinds = set(a.kind.split(",")) if a.kind else None
    try:
        for ev in read_events(since=a.since, lane=a.lane, project=a.project,
                              kinds=kinds, follow=a.follow):
            if a.json:
                print(json.dumps(ev, ensure_ascii=False), flush=True)
            else:
                ts = time.strftime("%H:%M:%S", time.localtime(ev.get("ts", 0)))
                extra = ""
                if ev.get("status"):
                    extra += f" status={ev['status']}"
                if ev.get("pr"):
                    extra += f" pr={ev['pr']}"
                if ev.get("dropped"):
                    extra += f" dropped={ev['dropped']}"
                print(f"{ts}  {ev.get('kind',''):<13} {ev.get('lane',''):<26}{extra}", flush=True)
    except (BrokenPipeError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
