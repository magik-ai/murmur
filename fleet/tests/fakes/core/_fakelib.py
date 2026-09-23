"""What every fake provider CLI in this directory shares.

A fake records the call and then answers from environment variables. It never reaches a
network, never spends money and never runs the command it was given. The record is one JSON
line per call in $FAKE_LOG, `{"argv": [...], "stdin": "..."}`, which is what a test reads to
prove that a secret never reached an argv.
"""
import json
import os
import sys
import time


def record():
    """Append this call to $FAKE_LOG and give back its argv (argv[0] is the bare name)."""
    argv = [os.path.basename(sys.argv[0])] + sys.argv[1:]
    log = os.environ.get("FAKE_LOG")
    if log:
        line = json.dumps({"argv": argv, "stdin": stdin_text()}, sort_keys=True)
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return argv


def stdin_text():
    """Whatever was piped in, or "" when nothing was. Never blocks on a terminal."""
    try:
        if sys.stdin is None or sys.stdin.closed or sys.stdin.isatty():
            return ""
        import select
        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
        if not ready:
            return ""
        return sys.stdin.read()
    except Exception:
        return ""


def slow(name):
    """Sleep when the test asked this fake to be slow, so a caller's timeout can fire."""
    seconds = os.environ.get(f"FAKE_{name}_SLEEP")
    if seconds:
        time.sleep(float(seconds))


def flag(name, default=""):
    return os.environ.get(name, default)


def out(text):
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def die(text, code=1):
    sys.stderr.write(text if text.endswith("\n") else text + "\n")
    raise SystemExit(code)


def load_json_file(path, fallback):
    if not path or not os.path.exists(path):
        return fallback
    with open(path, encoding="utf-8") as handle:
        body = handle.read().strip()
    return json.loads(body) if body else fallback


def save_json_file(path, value):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)


def value_after(argv, flagname):
    """The value of `--flag value` in an argv, or "" when the flag is not there."""
    if flagname in argv:
        index = argv.index(flagname)
        if index + 1 < len(argv):
            return argv[index + 1]
    return ""
