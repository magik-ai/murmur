"""`fleet runner test|reap`, and the check `fleet spawn --runner` makes before it starts a lane.

Three commands, each with one job:

- `test <provider> --project P` spends a few cents to answer the only question a page can ask
  honestly: do the two stored secrets work inside a real sandbox of this provider, on this
  farm, today. It creates the smallest sandbox, runs `claude --version` and a `git ls-remote`
  of the project, deletes it, and writes `$FLEET_STATE/hosts/<provider>/tested.json`.
- `reap [--dry-run]` is what stands between a hard kill and a sandbox that bills forever. A
  handle file whose lane's unit is gone, inactive or failed is a sandbox nobody is watching:
  its work comes home, then it is deleted. A unit that is `deactivating` is a stop in
  progress, and run_remote.py is doing exactly this work already, so it is left alone.
- `preflight <provider>` is `fleet spawn --runner`'s check, in one place rather than in bash:
  it refuses with one sentence, or prints where the sandbox will keep the clone and which
  parser the lane's run.sh should pipe the stream into.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
LIB = os.path.dirname(HERE)
if LIB not in sys.path:
    sys.path.insert(0, LIB)
import base  # noqa: E402
import run_remote  # noqa: E402
import scrub  # noqa: E402

# A Test sandbox is the smallest thing that can answer the question, and it is deleted in the
# same breath, so its budget is minutes rather than the hours a lane gets.
TEST_TIMEOUT_S = 600
TEST_VCPUS = 1
# systemd states that mean nobody is watching this lane any more. `deactivating` is missing on
# purpose: that is a stop in progress, and its own handler is bringing the work home.
DEAD_STATES = ("inactive", "failed")


def state_dir():
    return os.environ.get("FLEET_STATE") or os.path.expanduser("~/.fleet")


def config_dir():
    return os.environ.get("FLEET_CONFIG") or os.path.expanduser("~/.config/fleet")


def project_repo(project):
    """The owner/name of a registered project, or a sentence saying it is not registered."""
    path = os.path.join(config_dir(), "projects.toml")
    try:
        import tomllib
        with open(path, "rb") as handle:
            registry = tomllib.load(handle)
    except FileNotFoundError:
        raise base.RunnerError(f"no project registry at {path} (fleet add-project)")
    except (OSError, ValueError) as exc:
        raise base.RunnerError(f"the project registry could not be read: {exc}")
    repo = (registry.get(project) or {}).get("repo")
    if not repo:
        raise base.RunnerError(f"project '{project}' is not registered (fleet add-project)")
    return repo


class Scrubbed:
    """A text stream that scrubs everything written to it.

    Every sentence these commands print can carry a provider CLI's own stderr (a failed
    create, a failed delete, a version check), and a careless CLI may echo the token it was
    given. `main` puts one of these on stdout and on stderr, so no print can forget.
    """

    def __init__(self, stream, secrets):
        self.stream = stream
        self.secrets = secrets

    def write(self, text):
        return self.stream.write(scrub.scrub(text, self.secrets))

    def __getattr__(self, name):
        return getattr(self.stream, name)


def write_tested(provider, ok, seconds, detail):
    """The Test result the dashboard reads, one small file per provider.

    GET /api/hosts serves it verbatim, so the detail is scrubbed here as well, and the file
    is 0600 like every other record that may quote a provider.
    """
    folder = os.path.join(state_dir(), "hosts", provider)
    os.makedirs(folder, exist_ok=True)
    record = {"ok": bool(ok), "at": int(time.time()), "seconds": round(seconds, 1),
              "detail": scrub.scrub(detail, scrub.stored_secrets(state_dir()))}
    path = os.path.join(folder, "tested.json")
    temporary = path + ".tmp"
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(record, out)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return record


def cmd_test(args):
    runner = base.runner_for(args.provider, state_dir())
    repo = project_repo(args.project)
    ready, sentence = runner.available()
    if not ready:
        write_tested(args.provider, False, 0.0, sentence)
        print(sentence)
        return 1
    missing = runner.missing()
    if missing:
        sentence = (f"{args.provider} has no {', '.join(missing)} stored yet "
                    f"(fleet hosts secret {args.provider} {missing[0]})")
        write_tested(args.provider, False, 0.0, sentence)
        print(sentence)
        return 1
    spec = base.Spec(slug=f"test-{args.provider}-{os.getpid()}", repo=repo, branch="main",
                     base="", model="sonnet", brief_path=None, sys_path=None,
                     identity={}, timeout_s=TEST_TIMEOUT_S, vcpus=TEST_VCPUS)
    started = time.time()
    handle = None
    unanswered = False
    ok, detail = False, ""
    # The same record a lane writes, before the provider is asked, so a Test sandbox this
    # command never hears back about is still reaped. It has no unit, so the pid that owns it
    # is what tells the reaper it is still in use.
    record = {"slug": spec.slug, "provider": args.provider, "name": spec.sandbox_name,
              "repo": repo, "branch": spec.branch, "pid": os.getpid(),
              "created_at": int(time.time())}
    run_remote.write_handle(record)
    try:
        try:
            handle = runner.create(spec)
        except (base.SandboxMayExist, KeyboardInterrupt):
            # Ctrl-C during create stops only the local CLI; the provider may have the sandbox.
            unanswered = True
            raise
        record.update(base.durable(handle))
        run_remote.write_handle(record)
        ok, output = runner.probe(handle, repo)
        detail = base.first_line(output) or "the sandbox answered"
        if not ok:
            detail = f"the checks did not finish inside the sandbox: {detail}"
    except base.RunnerError as exc:
        ok, detail = False, str(exc)
    finally:
        forget = True
        target = handle or (record if unanswered else None)
        if target and not runner.addressable(target):
            forget = False
            detail = (f"{detail} ({args.provider} may have made a sandbox this farm cannot "
                      f"name; delete it by hand in the {args.provider} console, then remove "
                      f"{run_remote.handle_path(spec.slug)})").strip()
        elif target:
            try:
                runner.delete(target)
            except base.RunnerError as exc:
                ok = False
                forget = False
                detail = (f"{detail} (and the sandbox could not be deleted, so its record "
                          f"stays for fleet runner reap: {exc})").strip()
        if forget:
            run_remote.drop_handle(spec.slug)
    seconds = time.time() - started
    write_tested(args.provider, ok, seconds, detail)
    if ok:
        print(f"{args.provider}: the two secrets work in a real sandbox, "
              f"{seconds:.0f} seconds, and it is deleted.")
        return 0
    print(f"{args.provider}: the test failed after {seconds:.0f} seconds. {detail}")
    return 1


def unit_state(slug):
    """(LoadState, ActiveState) for a lane's unit, or None when systemd did not answer.

    A systemctl that fails (no user bus, no XDG_RUNTIME_DIR, a timeout) says nothing about
    the lane, and reading that as "gone" would destroy the sandbox of a lane that is still
    working. Only an explicit answer counts.
    """
    try:
        done = subprocess.run(
            ["systemctl", "--user", "show", f"fleet-{slug}",
             "--property=LoadState", "--property=ActiveState"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode:
        return None
    values = {}
    for line in (done.stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    if not values.get("LoadState") or not values.get("ActiveState"):
        return None
    return values["LoadState"], values["ActiveState"]


def _process_alive(pid):
    """Whether the process a record names still runs (`fleet runner test` has no unit)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def cmd_reap(args):
    records = sorted(glob.glob(os.path.join(state_dir(), "runners", "*.json")))
    if not records:
        print("no runner sandboxes are recorded")
        return 0
    reaped = kept = 0
    secrets = scrub.stored_secrets(state_dir())
    for path in records:
        try:
            with open(path, encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError) as exc:
            print(f"  keep {os.path.basename(path)} - it cannot be read ({exc})")
            kept += 1
            continue
        slug = record.get("slug") or os.path.basename(path)[:-5]
        if _process_alive(record.get("pid")):
            print(f"  keep {slug} - the process that owns it is still running")
            kept += 1
            continue
        answer = unit_state(slug)
        if answer is None:
            print(f"  keep {slug} - its unit could not be asked (systemctl --user did not "
                  f"answer), so it may still be running")
            kept += 1
            continue
        load_state, active_state = answer
        alive = load_state != "not-found" and active_state not in DEAD_STATES
        if alive:
            print(f"  keep {slug} - its unit is {active_state}")
            kept += 1
            continue
        why = "its unit is gone" if load_state == "not-found" else f"its unit is {active_state}"
        if args.dry_run:
            print(f"  would reap {slug} - {why}")
            reaped += 1
            continue
        reaped += _reap_one(record, slug, secrets, why)
    print(f"  ({reaped} sandbox(es) reaped, {kept} left alone)")
    return 0


def _reap_one(record, slug, secrets, why):
    provider = record.get("provider") or ""
    try:
        runner = base.runner_for(provider, state_dir())
    except base.RunnerError as exc:
        print(f"  keep {slug} - {exc}")
        return 0
    lane_args = argparse.Namespace(
        slug=slug, worktree=record.get("worktree") or "", branch=record.get("branch") or "",
        repo=record.get("repo") or "", base_branch=record.get("base_branch") or "main")
    if not runner.addressable(record):
        print(f"  keep {slug} - {why}, but {provider} may hold a sandbox this farm cannot "
              f"name; delete it by hand in the {provider} console, then remove "
              f"{run_remote.handle_path(slug)}")
        return 0
    lane = run_remote.Lane(lane_args, runner, secrets)
    lane.record = record
    lane.handle = dict(record)
    if record.get("base") and lane_args.worktree and os.path.isdir(lane_args.worktree):
        try:
            lane.bring_home(final=True)
        except base.RunnerError as exc:
            print(f"  {slug} - the work could not be brought home: {exc}")
        # A lane that died hard never reached its own pull request step, and without one
        # --done-when pr-open never finishes and --restart until-pr buys another sandbox.
        try:
            lane.open_pull_request()
        except (base.RunnerError, subprocess.SubprocessError, OSError) as exc:
            print(f"  {slug} - the pull request could not be opened: {exc}")
    try:
        runner.delete(lane.handle)
    except base.RunnerError as exc:
        print(f"  keep {slug} - the sandbox could not be deleted, so it may still be "
              f"billing: {exc}")
        return 0
    run_remote.drop_handle(slug)
    print(f"  reaped {slug} - {why}, work brought home and the sandbox deleted")
    return 1


def cmd_preflight(args):
    """What `fleet spawn --runner` needs to know, in one call: can this farm do it, and how."""
    runner = base.runner_for(args.provider, state_dir())
    missing = runner.missing()
    if missing:
        sys.stderr.write(
            f"REFUSING to spawn: {args.provider} has no {', '.join(missing)} stored "
            f"(store it: fleet hosts secret {args.provider} {missing[0]})\n")
        return 1
    ready, sentence = runner.available()
    if not ready:
        sys.stderr.write(f"REFUSING to spawn: {sentence}\n")
        return 1
    print(f"{runner.clone_dir}\t{runner.output}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fleet runner",
        description="Cloud sandboxes that run one lane (fleet spawn --runner <provider>).")
    subcommands = parser.add_subparsers(dest="command")
    test = subcommands.add_parser("test", help="prove the stored secrets work, and say how "
                                               "long it took (it spends a few cents)")
    test.add_argument("provider", choices=list(base.PROVIDERS))
    test.add_argument("--project", required=True)
    test.set_defaults(handler=cmd_test)
    reap = subcommands.add_parser("reap", help="finish every sandbox whose lane is gone")
    reap.add_argument("--dry-run", action="store_true")
    reap.set_defaults(handler=cmd_reap)
    preflight = subcommands.add_parser(
        "preflight", help="what spawn checks: the secrets, the CLI and the provider")
    preflight.add_argument("provider")
    preflight.set_defaults(handler=cmd_preflight)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    secrets = scrub.stored_secrets(state_dir())
    sys.stdout = Scrubbed(sys.stdout, secrets)
    sys.stderr = Scrubbed(sys.stderr, secrets)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 1
    try:
        return args.handler(args)
    except base.RunnerError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
