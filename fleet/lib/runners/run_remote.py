"""What a runner lane's unit runs instead of the engine: one lane, in a provider's sandbox.

Design record section 5, steps 1 to 8, in order, because the order is the whole safety
argument:

1. the branch is pushed from the farm's worktree first, so the claims guard runs before a
   sandbox exists, and that commit is the base every bundle is measured from;
2. the handle file is written BEFORE the provider is asked for anything, so a sandbox this
   farm never heard the answer about is still reaped;
3. the sandbox is created, the bootstrap runs inside it, and the agent starts;
4. its output is scrubbed line by line on its way to stdout, which is the lane log;
5. the work comes home every five minutes when the sandbox's HEAD has moved, and at the end:
   bundle, fetch, `merge --ff-only`, push, so the worktree always holds the latest commit and
   `fleet salvage` and the sweep protect a runner lane exactly as they protect a local one;
6. at the end the sandbox's `/tmp/fleet-pr.md` becomes a pull request, opened from the farm;
7. the sandbox is deleted and the handle file removed, on every path out: a normal end, an
   exception, SIGTERM, SIGINT, and a stdout that closed under us.

Farm-side sentences go to stderr, never stdout: stdout belongs to the remote agent alone,
because a parser is reading it.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
LIB = os.path.dirname(HERE)
if LIB not in sys.path:
    sys.path.insert(0, LIB)
import base  # noqa: E402
import scrub  # noqa: E402

# How often the work comes home while the agent is still running. Five minutes in the design
# record; the tests turn it down so a bring-home can be watched happening.
INTERVAL_S = int(os.environ.get("FLEET_RUNNER_INTERVAL_S") or 300)


class Stop(Exception):
    """SIGTERM or SIGINT arrived. Everything after this is the bring-home."""


class Deadline(Stop):
    """The lane's wall clock ran out. A hung agent keeps one exec open, and on Railway an
    open exec defers the idle stop, so this is the only backstop a live unit has."""


def state_dir():
    return os.environ.get("FLEET_STATE") or os.path.expanduser("~/.fleet")


def handle_path(slug, state=None):
    return os.path.join(state or state_dir(), "runners", f"{slug}.json")


def write_handle(record):
    """The runner record, written atomically so the reaper never reads half a file."""
    path = handle_path(record["slug"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as out:
        json.dump(record, out)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def drop_handle(slug):
    try:
        os.unlink(handle_path(slug))
    except OSError:
        pass


def git(worktree, *args):
    return subprocess.run(["git", "-C", worktree, *args], capture_output=True, text=True,
                          timeout=600)


def scrub_stderr(secrets):
    """Put a scrubbing filter on this process's stderr, for everything it and its children
    write there.

    A provider CLI's own error text is the one stream this farm does not write, so it is
    filtered at the file descriptor rather than at the call site: whatever doctl, railway or
    the sandbox CLI prints goes through here before it reaches the lane's `.err` log.
    """
    read_fd, write_fd = os.pipe()
    original = os.dup(2)
    os.dup2(write_fd, 2)
    os.close(write_fd)
    try:
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    def pump():
        with os.fdopen(read_fd, "r", errors="replace") as source, \
                os.fdopen(original, "w", errors="replace") as sink:
            for line in source:
                sink.write(scrub.scrub(line, secrets))
                sink.flush()

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return thread


def close_scrubbed_stderr(thread):
    """Let the filter finish before the process does, or the last sentence is lost.

    The pump is a daemon thread, and interpreter shutdown does not wait for one. Pointing
    this process's stderr at /dev/null closes the last writing end of the pipe, so the pump
    reaches end of file and drains what is still in it.
    """
    try:
        sys.stderr.flush()
    except (BrokenPipeError, ValueError, OSError):
        pass
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
    except OSError:
        return
    if thread:
        thread.join(timeout=10)


def _git_reason(text):
    """The line of git's stderr that says why, not the `To <remote>` line before it."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in lines:
        if line.lower().startswith(("error", "fatal", "remote:", "!")):
            return line
    return lines[0] if lines else "git gave no reason"


def say(message):
    """One farm-side sentence into the lane's error log, where the farm's own voice belongs."""
    try:
        sys.stderr.write(f"[runner] {message}\n")
        sys.stderr.flush()
    except (BrokenPipeError, ValueError, OSError):
        pass


class Lane:
    """One runner lane's farm side: the worktree, the record, and the sandbox it owns."""

    def __init__(self, args, runner, secrets):
        self.args = args
        self.runner = runner
        self.secrets = secrets
        self.handle = None
        self.record = {}
        self.lock = threading.Lock()
        self.stop_timer = threading.Event()
        self.stdout_open = True
        self.pr_opened = False
        # True once `create` failed in a way that may have left a sandbox behind.
        self.unanswered = False
        self.last_home = time.time()

    # The three steps that touch the farm's git. ------------------------------------------

    def push_base(self):
        """Step 1: push the lane's branch, and keep that commit as the base.

        A refused push (the claims guard, a protected branch, no network) ends the lane here:
        work made in a sandbox could never come home to this branch, so no sandbox is bought.
        """
        done = git(self.args.worktree, "push", "origin", f"HEAD:{self.args.branch}")
        if done.returncode:
            raise base.RunnerError(
                f"the branch could not be pushed, so no sandbox was started: "
                f"{_git_reason(done.stderr)}")
        head = git(self.args.worktree, "rev-parse", "HEAD")
        if head.returncode:
            raise base.RunnerError("this worktree has no commit to start from")
        return head.stdout.strip()

    def bring_home(self, final=False):
        """Steps 5 and 6: the sandbox's new commits, into the worktree and on to origin."""
        if not self.handle:
            return False
        if final:
            try:
                self.runner.commit_dirty(self.handle)
            except base.RunnerError as exc:
                say(f"the sandbox could not commit what was left in its tree: {exc}")
        bundle = self.runner.fetch_bundle(self.handle, self.record["base"])
        if not bundle:
            return False
        try:
            fetched = git(self.args.worktree, "fetch", bundle)
            if fetched.returncode:
                say(f"the bundle could not be read: {base.first_line(fetched.stderr)}")
                return False
            merged = git(self.args.worktree, "merge", "--ff-only", "FETCH_HEAD")
            if merged.returncode:
                say("the sandbox's commits do not fast-forward this worktree, so they were "
                    "left alone; they are in FETCH_HEAD")
                return False
            head = git(self.args.worktree, "rev-parse", "HEAD").stdout.strip()
            pushed = git(self.args.worktree, "push", "origin", f"HEAD:{self.args.branch}")
            if pushed.returncode:
                say(f"the work is in the worktree but the push failed: "
                    f"{base.first_line(pushed.stderr)}")
            self.record["base"] = head or self.record["base"]
            write_handle(self.record)
            say(f"brought the work home at {head[:8] if head else '?'}")
            return True
        finally:
            try:
                os.unlink(bundle)
            except OSError:
                pass

    def open_pull_request(self):
        """Step 7: the pull request the sandbox asked for, opened from the farm."""
        if self.pr_opened:
            return
        # Ahead of the project's base branch is the honest question, and a farm that cannot
        # answer it (no origin/<base> fetched) falls back to "did this lane commit anything
        # at all", which is the commit it was pushed at.
        ahead = git(self.args.worktree, "rev-list", "--count",
                    f"origin/{self.args.base_branch}..HEAD")
        if ahead.returncode:
            head = git(self.args.worktree, "rev-parse", "HEAD").stdout.strip()
            count = 0 if head == self.record.get("first_base") else 1
        else:
            count = int((ahead.stdout or "0").strip() or 0)
        if not count:
            say("the branch has nothing on top of the base, so no pull request was opened")
            return
        listed = subprocess.run(
            ["gh", "pr", "list", "--head", self.args.branch, "--json", "number"],
            cwd=self.args.worktree, capture_output=True, text=True, timeout=120)
        if listed.returncode == 0 and (listed.stdout or "").strip() not in ("", "[]"):
            say("a pull request for this branch is already open")
            self.pr_opened = True
            return
        text = None
        try:
            text = self.runner.read_file(self.handle, base.PR_PATH)
        except base.RunnerError as exc:
            say(f"the sandbox's pull request file could not be read: {exc}")
        if text is not None:
            # The title becomes an argv of a farm process and the body is published on
            # GitHub, so both are scrubbed like every other line that leaves the sandbox.
            text = scrub.scrub(text, self.secrets)
        draft = text is None
        if draft:
            title, body = self.args.branch, (
                "This lane finished without writing /tmp/fleet-pr.md, so the farm opened a "
                "draft. Read the lane log for what it did.\n")
        else:
            lines = text.splitlines()
            title = (lines[0] if lines else self.args.branch).strip() or self.args.branch
            body = "\n".join(lines[1:]).strip() + "\n"
        with base.private_files({"pr-body.md": body}) as paths:
            argv = ["gh", "pr", "create", "--head", self.args.branch, "--title", title,
                    "--body-file", paths["pr-body.md"]]
            if draft:
                argv.append("--draft")
            created = subprocess.run(argv, cwd=self.args.worktree, capture_output=True,
                                     text=True, timeout=300)
        if created.returncode:
            say(f"the pull request could not be opened: {base.first_line(created.stderr)}")
            return
        self.pr_opened = True
        say(f"opened the pull request: {base.first_line(created.stdout)}")

    # The run itself. ---------------------------------------------------------------------

    def watch(self):
        """The five minute bring-home, on its own thread, so a quiet agent still comes home."""
        while not self.stop_timer.wait(min(INTERVAL_S, 5)):
            if time.time() - self.last_home < INTERVAL_S:
                continue
            with self.lock:
                self.last_home = time.time()
                try:
                    head = self.runner.head(self.handle) if self.handle else None
                    if head and head != self.record["base"]:
                        self.bring_home()
                except base.RunnerError as exc:
                    say(f"a mid-run check did not answer: {exc}")

    def stream(self):
        for line in self.runner.run(self.handle):
            if self.stdout_open:
                try:
                    sys.stdout.write(scrub.scrub(line, self.secrets) + "\n")
                    sys.stdout.flush()
                except (BrokenPipeError, ValueError, OSError):
                    # The lane's tee is gone. The sandbox still has to be brought home and
                    # deleted, so this is noted and the run continues without a reader.
                    self.stdout_open = False
                    say("the lane log closed; the sandbox is still being finished")

    def finish(self):
        """Every path out ends here: bring home, pull request, delete, forget.

        The runner record is only forgotten once no sandbox can be left behind: a delete that
        failed, or a sandbox this farm cannot name, keeps it for the reaper and for a person.
        """
        self.stop_timer.set()
        with self.lock:
            forget = True
            if self.unanswered and not self.handle:
                forget = self.delete_unanswered()
            elif self.handle:
                try:
                    self.bring_home(final=True)
                except base.RunnerError as exc:
                    say(f"the last bring-home failed: {exc}")
                try:
                    self.open_pull_request()
                except (base.RunnerError, subprocess.SubprocessError, OSError) as exc:
                    say(f"the pull request step failed: {exc}")
                try:
                    self.runner.delete(self.handle)
                    say("the sandbox is deleted")
                except base.RunnerError as exc:
                    forget = False
                    say(f"the sandbox could not be deleted, so it may still be billing; its "
                        f"record stays for fleet runner reap: {exc}")
            if forget:
                drop_handle(self.args.slug)

    def delete_unanswered(self):
        """`create` failed after the provider was asked: delete by the record's name, or say
        plainly that a person has to. True when nothing can be billing any more."""
        provider = self.record.get("provider") or "the provider"
        if not self.runner.addressable(self.record):
            say(f"{provider} may have made a sandbox this farm cannot name; delete it by hand "
                f"in the {provider} console, then remove {handle_path(self.args.slug)}")
            return False
        try:
            self.runner.delete(self.record)
        except base.RunnerError as exc:
            say(f"the sandbox {self.record.get('name')} could not be deleted, so it may still "
                f"be billing; its record stays for fleet runner reap: {exc}")
            return False
        say(f"the sandbox {self.record.get('name')} is deleted")
        return True


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="run_remote.py",
        description="Run one lane's agent in a provider sandbox and bring its work home.")
    parser.add_argument("provider", choices=list(base.PROVIDERS))
    parser.add_argument("--slug", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--brief", required=True)
    parser.add_argument("--sys", dest="sys_path", required=True)
    parser.add_argument("--identity-name", default="")
    parser.add_argument("--identity-email", default="")
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--timeout-s", type=int, default=8 * 3600)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    secrets = scrub.stored_secrets(state_dir())
    filter_thread = scrub_stderr(secrets)
    runner = base.runner_for(args.provider, state_dir())
    lane = Lane(args, runner, secrets)

    def handler(_signum, _frame):
        raise Stop()

    def deadline(_signum, _frame):
        raise Deadline()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(max(1, args.timeout_s))

    spec = base.Spec(slug=args.slug, repo=args.repo, branch=args.branch, base="",
                     model=args.model, brief_path=args.brief, sys_path=args.sys_path,
                     identity={"name": args.identity_name, "email": args.identity_email},
                     timeout_s=args.timeout_s)
    code = 0
    try:
        spec.base = lane.push_base()
        lane.record = {"slug": args.slug, "provider": args.provider, "base": spec.base,
                       "first_base": spec.base, "worktree": args.worktree,
                       "branch": args.branch, "repo": args.repo,
                       "base_branch": args.base_branch, "name": spec.sandbox_name,
                       "created_at": int(time.time())}
        write_handle(lane.record)
        say(f"the branch is at {spec.base[:8]}; asking {args.provider} for a sandbox")
        try:
            lane.handle = runner.create(spec)
        except (base.SandboxMayExist, Stop):
            # A stop or the wall clock landing while `create` is in flight kills only the
            # local CLI: the provider may already hold the sandbox, so it is looked for by
            # name exactly like a create that failed after the provider was asked.
            lane.unanswered = True
            raise
        lane.record.update(base.durable(lane.handle))
        lane.record["base"] = spec.base
        write_handle(lane.record)
        say(f"the sandbox is {lane.record.get('id') or lane.record.get('name')}")
        lane.last_home = time.time()
        # The timer thread only starts once there is a sandbox to ask about.
        threading.Thread(target=lane.watch, daemon=True).start()
        lane.stream()
    except Deadline:
        say(f"the lane's wall clock ran out after {args.timeout_s} seconds; bringing the "
            f"work home before the sandbox goes")
        code = 124
    except Stop:
        say("a stop arrived; bringing the work home before the sandbox goes")
        code = 143
    except base.RunnerError as exc:
        say(f"{exc}")
        code = 1
    except Exception as exc:  # noqa: BLE001 - the sandbox must be deleted whatever this was
        say(f"the run ended with an unexpected error: {type(exc).__name__}: {exc}")
        code = 1
    finally:
        # A second stop must not interrupt the delete: a sandbox nobody deletes keeps billing.
        signal.alarm(0)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            lane.finish()
        except Exception as exc:  # noqa: BLE001
            say(f"the cleanup itself failed: {type(exc).__name__}: {exc}")
        _silence_stdout()
        close_scrubbed_stderr(filter_thread)
    return code


def _silence_stdout():
    """Python flushes stdout as it exits, and a closed pipe would make that the last word."""
    try:
        sys.stdout.flush()
    except (BrokenPipeError, ValueError, OSError):
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
