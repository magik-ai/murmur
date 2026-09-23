"""The spine of the fake provider CLIs the runner tests put first on PATH.

Nothing here reaches a provider, spends money or touches the live farm. Each fake:

- appends one JSON line per call to `$FAKE_LOG`, `{"argv": [...], "stdin": "..."}`, so a test
  can assert on the exact argv a provider was asked for, and on what never appeared in it;
- runs the small sandbox scripts (head, bundle, read-file, commit-dirty) FOR REAL against
  `$FAKE_SANDBOX`, a directory standing in for the sandbox's filesystem, with `/workspace` and
  `/tmp` rewritten into it. That way a test exercises the real git commands and the real
  bundle, and work genuinely comes home;
- plays `$FAKE_TRANSCRIPT` for anything that would start an agent, line by line. A transcript
  may print a stored secret, which is how the scrub is proved, and may carry directives:
  `@sleep <seconds>`, `@commit <message>` (a real commit inside the fake sandbox, so HEAD
  moves mid-run), `@stderr <text>` and `@exit <code>`.

A secret VALUE is never written to the log: an env file is recorded by its mode and its key
names only, because the test's whole point is that values stay out of places people read.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

REAL_OPS = ("head", "bundle", "read-file", "commit-dirty")


def root():
    path = os.environ.get("FAKE_SANDBOX") or ""
    if not path:
        sys.stderr.write("FAKE_SANDBOX is not set\n")
        raise SystemExit(2)
    os.makedirs(os.path.join(path, "tmp"), exist_ok=True)
    os.makedirs(os.path.join(path, "workspace"), exist_ok=True)
    return path


def log(argv, stdin_text="", extra=None):
    entry = {"argv": list(argv), "stdin": stdin_text}
    if os.environ.get("FAKE_WATCH_FILE"):
        entry["watch"] = _watching()
    if extra:
        entry.update(extra)
    path = os.environ.get("FAKE_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def _watching():
    """Whether a file already said what a test is watching for, at the moment of this call.

    It is how a test asks "did that happen BEFORE this call": the kill path has to mark a
    runner lane's record killed before it stops the unit, and only the fake can see the order.
    """
    try:
        with open(os.environ["FAKE_WATCH_FILE"], encoding="utf-8") as handle:
            return os.environ.get("FAKE_WATCH_TEXT", "") in handle.read()
    except (OSError, KeyError):
        return False


def handle_exists():
    """Whether the farm had already written its runner record: the test for "the handle file
    is written BEFORE the provider is asked for anything"."""
    path = os.environ.get("FAKE_HANDLE_PATH") or ""
    return bool(path and os.path.exists(path))


def read_stdin():
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def env_file_facts(path):
    """What a test may know about a secret file: its mode and its key names, never a value."""
    try:
        mode = oct(os.stat(path).st_mode & 0o777)
        with open(path, encoding="utf-8") as handle:
            keys = [line.split("=", 1)[0] for line in handle if "=" in line]
    except OSError:
        return {"mode": "", "keys": []}
    return {"mode": mode, "keys": keys}


def secret_file_facts(path):
    try:
        return {"mode": oct(os.stat(path).st_mode & 0o777), "bytes": os.stat(path).st_size}
    except OSError:
        return {"mode": "", "bytes": 0}


def local(path_text):
    """Every sandbox path in a script, moved into the fake sandbox directory.

    One pass, not two: the fake sandbox itself lives under /tmp, so a second pass would
    rewrite the paths the first one had already produced.
    """
    prefix = root()
    return re.sub(r"/workspace|/tmp/", lambda found: prefix + found.group(0), path_text)


def op_of(script):
    for line in (script or "").splitlines():
        if line.startswith("# fleet-op:"):
            return line.split(":", 1)[1].strip()
    return ""


def run_script(script):
    """Run one of the small scripts for real, against the fake sandbox."""
    done = subprocess.run(["sh", "-c", local(script)], capture_output=True, text=True,
                          cwd=root())
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    return done.returncode


def play_transcript():
    """Everything an agent would have printed, plus the directives a test needs."""
    path = os.environ.get("FAKE_TRANSCRIPT")
    if not path or not os.path.exists(path):
        print("fake sandbox: nothing to say")
        return 0
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    for line in lines:
        if line.startswith("@sleep "):
            sys.stdout.flush()
            time.sleep(float(line.split(None, 1)[1]))
        elif line.startswith("@commit "):
            _commit(line.split(None, 1)[1])
        elif line.startswith("@stderr "):
            sys.stderr.write(line.split(None, 1)[1] + "\n")
            sys.stderr.flush()
        elif line.startswith("@exit "):
            sys.stdout.flush()
            return int(line.split(None, 1)[1])
        else:
            print(line)
            sys.stdout.flush()
    return 0


def _commit(message):
    """A real commit inside the fake sandbox's clone, so the farm sees HEAD move."""
    repo = os.path.join(root(), "workspace", "repo")
    stamp = str(time.time())
    with open(os.path.join(repo, "agent-work.txt"), "a", encoding="utf-8") as handle:
        handle.write(stamp + "\n")
    for argv in (["git", "add", "-A"], ["git", "commit", "-q", "-m", message]):
        subprocess.run(argv, cwd=repo, capture_output=True, text=True)


def dispatch(script):
    """A script from the farm: run it if it is one of the small ones, else play the agent."""
    if op_of(script) in REAL_OPS:
        return run_script(script)
    return play_transcript()


def copy_in(local_path, remote_path):
    target = local(remote_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(local_path, target)
    return target


def value_after(argv, flag):
    if flag in argv:
        index = argv.index(flag)
        if index + 1 < len(argv):
            return argv[index + 1]
    return ""


def after_dashes(argv):
    return argv[argv.index("--") + 1:] if "--" in argv else []
