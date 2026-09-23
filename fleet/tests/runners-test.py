"""Runner lanes: the three adapters, the scrub, the work coming home, and every refusal.

Nothing here reaches a provider, spends a cent or touches the live farm. Every test runs
against a throwaway FLEET_STATE, FLEET_CONFIG and HOME, with fake `railway`, `sandbox`,
`doctl`, `gh`, `systemctl`, `systemd-run`, `loginctl` and `tmux` first on PATH; the fakes
record every call into one JSON log a test reads, and the small sandbox scripts (head, bundle,
read-file, commit-dirty) are run for real against a directory standing in for the sandbox, so
the work that comes home is a real git bundle through a real merge into a real worktree, and
the branch it lands on is a real local bare repository.

Run:  python3 tests/runners-test.py      (from the fleet directory)
"""
import glob as _globmodule
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.dirname(HERE)
RUNNERS = os.path.join(FLEET, "lib", "runners")
FAKES = os.path.join(HERE, "fakes", "runners")
sys.path.insert(0, os.path.join(FLEET, "lib"))
sys.path.insert(0, RUNNERS)
import base  # noqa: E402
import do_agents  # noqa: E402
import railway  # noqa: E402
import run_remote  # noqa: E402
import vercel  # noqa: E402

OAUTH = "fake-oauth-token-value-0001"
GITHUB = "fake-github-token-value-0002"
LOOSE_TOKEN = "sk-ant-oat01-" + "Z" * 40
REPO = "magik-ai/murmur"
BRANCH = "fleet/test-lane"


def git(cwd, *args, check=True):
    done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    if check and done.returncode:
        raise AssertionError(f"git {' '.join(args)} in {cwd}: {done.stderr.strip()}")
    return done.stdout.strip()


class Farm:
    """A whole farm in a temporary directory: state, config, a remote, a worktree, a sandbox."""

    def __init__(self, providers=base.PROVIDERS, project="murmur"):
        self.root = tempfile.mkdtemp(prefix="fleet-runners-test-")
        self.state = os.path.join(self.root, "state")
        self.config = os.path.join(self.root, "config")
        self.home = os.path.join(self.root, "home")
        self.sandbox = os.path.join(self.root, "sandbox")
        self.log = os.path.join(self.root, "calls.jsonl")
        self.transcript = os.path.join(self.root, "transcript.txt")
        self.project = project
        for folder in (self.state, self.config, self.home,
                       os.path.join(self.sandbox, "tmp")):
            os.makedirs(folder, exist_ok=True)
        for provider in providers:
            folder = os.path.join(self.state, "secrets", "hosts", provider)
            os.makedirs(folder, exist_ok=True)
            self.write_secret(provider, "CLAUDE_CODE_OAUTH_TOKEN", OAUTH)
            self.write_secret(provider, "GITHUB_TOKEN", GITHUB)
        self.brief = os.path.join(self.root, "brief.md")
        self.sys_file = os.path.join(self.root, "sys.md")
        _write(self.brief, "Do the slice. Commit your work.\n")
        _write(self.sys_file, "You are a fleet worker agent.\n")
        self.set_transcript("the agent says hello")
        self._build_git()
        self._write_registry()

    # Building. ---------------------------------------------------------------------------

    def _build_git(self):
        self.remote = os.path.join(self.root, "remote.git")
        seed = os.path.join(self.root, "seed")
        # Both name their branch: a runner whose git defaults to `master` would otherwise
        # clone a remote whose HEAD points at nothing.
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.remote], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", seed], check=True)
        self._identity(seed)
        _write(os.path.join(seed, "README.md"), "murmur\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "Feat: the first commit")
        git(seed, "remote", "add", "origin", self.remote)
        git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")

        self.work = os.path.join(self.root, "worktree")
        subprocess.run(["git", "clone", "-q", self.remote, self.work], check=True)
        self._identity(self.work)
        git(self.work, "checkout", "-q", "-b", BRANCH)

        self.clone = os.path.join(self.sandbox, "workspace", "repo")
        os.makedirs(os.path.dirname(self.clone), exist_ok=True)
        subprocess.run(["git", "clone", "-q", self.remote, self.clone], check=True)
        self._identity(self.clone)
        git(self.clone, "checkout", "-q", "-b", BRANCH)

        self.project_path = os.path.join(self.root, "project")
        subprocess.run(["git", "clone", "-q", self.remote, self.project_path], check=True)
        self._identity(self.project_path)

    def _identity(self, repo):
        git(repo, "config", "user.name", "test (agent)")
        git(repo, "config", "user.email", "test@agents.local")

    def _write_registry(self):
        _write(os.path.join(self.config, "projects.toml"),
               f'[{self.project}]\nrepo = "{REPO}"\npath = "{self.project_path}"\n'
               f'branch = "main"\n')
        # Head office is a deployment's own layer and never runs in a test.
        _write(os.path.join(self.config, "policy.toml"), "[hq]\nenabled = false\n")

    # Using. ------------------------------------------------------------------------------

    def write_secret(self, provider, name, value):
        path = os.path.join(self.state, "secrets", "hosts", provider, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write(path, value)
        os.chmod(path, 0o600)

    def drop_secret(self, provider, name):
        os.unlink(os.path.join(self.state, "secrets", "hosts", provider, name))

    def set_transcript(self, *lines):
        _write(self.transcript, "\n".join(lines) + "\n")

    def set_pr_file(self, text):
        _write(os.path.join(self.sandbox, "tmp", "fleet-pr.md"), text)

    def env(self, **extra):
        environment = {
            "PATH": FAKES + ":/usr/local/bin:/usr/bin:/bin",
            "HOME": self.home,
            "FLEET_STATE": self.state,
            "FLEET_CONFIG": self.config,
            "FAKE_LOG": self.log,
            "FAKE_TRANSCRIPT": self.transcript,
            "FAKE_SANDBOX": self.sandbox,
            "FLEET_RUNNER_INTERVAL_S": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "LANG": "C",
            # bin/fleet runs under `set -u` and its kill audit reads $USER.
            "USER": os.environ.get("USER", "farm"),
            "LOGNAME": os.environ.get("LOGNAME", "farm"),
        }
        environment.update({key: str(value) for key, value in extra.items()})
        return environment

    def calls(self, cli=None):
        entries = []
        if not os.path.exists(self.log):
            return entries
        with open(self.log, encoding="utf-8") as handle:
            for line in handle:
                entry = json.loads(line)
                if cli is None or entry["argv"][0] == cli:
                    entries.append(entry)
        return entries

    def argvs(self, cli):
        return [entry["argv"] for entry in self.calls(cli)]

    def log_text(self):
        return open(self.log, encoding="utf-8").read() if os.path.exists(self.log) else ""

    def handle_path(self, slug):
        return os.path.join(self.state, "runners", f"{slug}.json")

    def clean(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _glob(pattern):
    return sorted(_globmodule.glob(pattern))


def _write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def spec_for(farm, slug="lane-1"):
    return base.Spec(slug=slug, repo=REPO, branch=BRANCH,
                     base=git(farm.work, "rev-parse", "HEAD"), model="sonnet",
                     brief_path=farm.brief, sys_path=farm.sys_file,
                     identity={"name": "test (agent)", "email": "test@agents.local"},
                     timeout_s=3600)


class AdapterCase(unittest.TestCase):
    """A farm and the environment the adapters read, for the in-process adapter tests."""

    def setUp(self):
        self.farm = Farm()
        self.addCleanup(self.farm.clean)
        patch = mock.patch.dict(os.environ, self.farm.env())
        patch.start()
        self.addCleanup(patch.stop)


class Bootstrap(AdapterCase):
    def test_the_bootstrap_follows_every_rule_of_section_five(self):
        script = base.bootstrap(spec_for(self.farm))
        self.assertNotIn("set -x", script)
        self.assertNotIn("--include-partial-messages", script)
        self.assertIn("credential.helper", script)
        self.assertIn("$GITHUB_TOKEN", script.replace("${GITHUB_TOKEN}", "$GITHUB_TOKEN"))
        self.assertIn(f"git clone --filter=blob:none --branch '{BRANCH}'", script)
        self.assertIn("git config user.name 'test (agent)'", script)
        self.assertIn("git config user.email 'test@agents.local'", script)
        self.assertIn("unset ANTHROPIC_API_KEY", script)
        self.assertIn("--output-format stream-json --verbose", script)
        self.assertIn('wip: uncommitted work at exit', script)
        self.assertIn("claude -p", script)

    def test_the_brief_and_the_system_prompt_stay_files_and_off_the_argv(self):
        # Section 5 step 3: sent as files. Inlining them back with $(cat ...) would put the
        # whole brief in the sandbox's process list and against ARG_MAX.
        script = base.bootstrap(spec_for(self.farm))
        self.assertNotIn("$(cat", script)
        self.assertIn(f"< {base.BRIEF_PATH}", script)
        self.assertIn(f"--append-system-prompt-file {base.SYS_PATH}", script)

    def test_the_system_prompt_flag_is_found_in_either_spelling_of_the_help(self):
        # claude 2.1 writes the flag only as `--append-system-prompt[-file]`, inside the
        # --bare description; an older help lists `--append-system-prompt-file` on its own.
        script = base.bootstrap(spec_for(self.farm))
        start = script.index("if claude --help")
        snippet = script[start:script.index("fi\n", start) + 3]
        folder = os.path.join(self.farm.root, "probe")
        os.makedirs(folder)
        brief, sys_file = os.path.join(folder, "brief.md"), os.path.join(folder, "sys.md")
        _write(brief, "the brief\n")
        _write(sys_file, "the framing\n")
        snippet = snippet.replace(base.BRIEF_PATH, brief).replace(base.SYS_PATH, sys_file)
        fake = os.path.join(folder, "claude")
        _write(fake, '#!/bin/sh\nif [ "$1" = "--help" ]; then cat "$HELP_TEXT"; exit 0; fi\n'
                     'echo "$@" > "$ARGV_OUT"\ncat > "$STDIN_OUT"\n')
        os.chmod(fake, 0o755)
        helps = {
            "bracket": "  --bare  Minimal mode: context only through --system-prompt[-file], "
                       "--append-system-prompt[-file], --add-dir\n",
            "plain": "  --append-system-prompt-file <file>  Append a file to the prompt\n",
            "absent": "  --model <model>  The model\n",
        }
        for spelling, text in helps.items():
            help_file = os.path.join(folder, f"help-{spelling}.txt")
            _write(help_file, text)
            outputs = {"ARGV_OUT": os.path.join(folder, f"argv-{spelling}"),
                       "STDIN_OUT": os.path.join(folder, f"stdin-{spelling}")}
            subprocess.run(["bash", "-c", snippet], check=True, timeout=30,
                           env=dict(os.environ, PATH=f"{folder}:/usr/bin:/bin",
                                    HELP_TEXT=help_file, **outputs))
            argv = open(outputs["ARGV_OUT"], encoding="utf-8").read()
            stdin = open(outputs["STDIN_OUT"], encoding="utf-8").read()
            if spelling == "absent":
                self.assertNotIn("--append-system-prompt", argv, spelling)
                self.assertEqual(stdin, "the framing\nthe brief\n", spelling)
            else:
                self.assertIn(f"--append-system-prompt-file {sys_file}", argv, spelling)
                self.assertEqual(stdin, "the brief\n", spelling)

    def test_no_token_value_is_ever_written_into_the_bootstrap(self):
        script = base.bootstrap(spec_for(self.farm))
        self.assertNotIn(OAUTH, script)
        self.assertNotIn(GITHUB, script)

    def test_the_digitalocean_bootstrap_stops_before_the_agent(self):
        script = base.bootstrap(spec_for(self.farm), with_agent=False)
        self.assertNotIn("claude -p", script)
        self.assertIn("git clone --filter=blob:none", script)

    def test_a_brief_that_would_end_the_heredoc_is_refused(self):
        _write(self.farm.brief, "a line\nFLEET_BRIEF_EOF\nanother\n")
        with self.assertRaises(base.RunnerError):
            base.bootstrap(spec_for(self.farm))

    def test_every_private_file_is_0600_in_a_0700_directory_and_then_gone(self):
        # One shape for anything private on disk (the env file, a secret per file, the
        # bootstrap, a pull request body), not three copies of it.
        for name in ("env_file", "spill_file", "secret_files"):
            self.assertFalse(hasattr(base, name), name)
        files = {"agent.env": base.env_text({"A": "one", "B": "two"}), "B": "two"}
        with base.private_files(files) as paths:
            for path in paths.values():
                self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
            folder = os.path.dirname(paths["B"])
            self.assertEqual(oct(os.stat(folder).st_mode & 0o777), "0o700")
            self.assertEqual(open(paths["agent.env"]).read(), "A=one\nB=two\n")
        self.assertFalse(os.path.exists(folder))
        with self.assertRaises(base.RunnerError):
            base.env_text({"A": "one\nB=injected"})


class RailwayAdapter(AdapterCase):
    def test_the_argv_of_a_whole_lane(self):
        runner = railway.RUNNER(self.farm.state)
        spec = spec_for(self.farm)
        handle = runner.create(spec)
        self.assertEqual(list(runner.run(handle))[-1], "the agent says hello")
        head = runner.head(handle)
        runner.fetch_bundle(handle, spec.base)
        runner.read_file(handle, base.PR_PATH)
        runner.delete(handle)
        argvs = self.farm.argvs("railway")
        self.assertEqual(argvs[0], ["railway", "sandbox", "create", "--json", "--env-file",
                                    argvs[0][-1]])
        for index in range(1, len(argvs) - 1):
            self.assertEqual(argvs[index], ["railway", "sandbox", "exec", "--id", "sbx-fake-01",
                                            "--", "bash", "-s"])
        self.assertEqual(argvs[-1], ["railway", "sandbox", "destroy", "sbx-fake-01"])
        self.assertEqual(head, git(self.farm.clone, "rev-parse", "HEAD"))

    def test_the_secrets_travel_as_a_0600_file_and_never_on_an_argv(self):
        runner = railway.RUNNER(self.farm.state)
        runner.create(spec_for(self.farm))
        created = self.farm.calls("railway")[0]
        self.assertEqual(created["env_file"]["mode"], "0o600")
        self.assertEqual(sorted(created["env_file"]["keys"]), sorted(base.SECRET_NAMES))
        self.assertNotIn(OAUTH, self.farm.log_text())
        self.assertNotIn(GITHUB, self.farm.log_text())

    def test_a_missing_secret_is_a_sentence_not_a_sandbox(self):
        self.farm.drop_secret("railway", "GITHUB_TOKEN")
        runner = railway.RUNNER(self.farm.state)
        with self.assertRaises(base.RunnerError) as caught:
            runner.create(spec_for(self.farm))
        self.assertIn("GITHUB_TOKEN", str(caught.exception))
        self.assertEqual(self.farm.argvs("railway"), [])

    def test_an_empty_range_makes_no_bundle(self):
        runner = railway.RUNNER(self.farm.state)
        spec = spec_for(self.farm)
        handle = runner.create(spec)
        self.assertIsNone(runner.fetch_bundle(handle, spec.base))

    def test_a_bundle_carries_the_new_commits(self):
        runner = railway.RUNNER(self.farm.state)
        spec = spec_for(self.farm)
        handle = runner.create(spec)
        _write(os.path.join(self.farm.clone, "new.txt"), "work\n")
        git(self.farm.clone, "add", "-A")
        git(self.farm.clone, "commit", "-q", "-m", "Feat: work in the sandbox")
        path = runner.fetch_bundle(handle, spec.base)
        self.assertTrue(path and os.path.exists(path))
        self.addCleanup(os.unlink, path)
        heads = subprocess.run(["git", "bundle", "list-heads", path], capture_output=True,
                               text=True).stdout
        self.assertIn(git(self.farm.clone, "rev-parse", "HEAD"), heads)

    def test_read_file_answers_none_when_it_is_not_there(self):
        runner = railway.RUNNER(self.farm.state)
        handle = runner.create(spec_for(self.farm))
        self.assertIsNone(runner.read_file(handle, base.PR_PATH))
        self.farm.set_pr_file("Feat: a title\n\nthe body\n")
        self.assertEqual(runner.read_file(handle, base.PR_PATH),
                         "Feat: a title\n\nthe body\n")

    def test_a_hex_string_in_a_banner_is_not_taken_for_head(self):
        runner = railway.RUNNER(self.farm.state)
        noise = "c0ffee" + "0" * 34
        real = "a" * 40
        answers = {
            f"railway: cache {noise} is stale\n": None,
            f"railway: cache {noise} is stale\n{real}\n\n": real,
            f"{real}\nrailway: session {noise} closed\n": None,
        }
        for text, expected in answers.items():
            with mock.patch.object(runner, "exec_text", return_value=text):
                self.assertEqual(runner.head({"id": "sbx"}), expected, text)
                self.assertEqual(runner.commit_dirty({"id": "sbx"}), expected, text)

    def test_available_says_what_is_missing(self):
        runner = railway.RUNNER(self.farm.state)
        self.assertTrue(runner.available()[0])
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            ready, sentence = railway.RUNNER(self.farm.state).available()
        self.assertFalse(ready)
        self.assertIn("railway", sentence)


class VercelAdapter(AdapterCase):
    def test_the_argv_of_a_whole_lane(self):
        runner = vercel.RUNNER(self.farm.state)
        spec = spec_for(self.farm)
        handle = runner.create(spec)
        name = "fleet-lane-1"
        self.assertEqual(list(runner.run(handle))[-1], "the agent says hello")
        runner.head(handle)
        runner.delete(handle)
        argvs = self.farm.argvs("sandbox")
        self.assertEqual(argvs[0], ["sandbox", "create", "--name", name, "--vcpus", "4",
                                    "--timeout", "60m", "--non-persistent"])
        self.assertEqual(argvs[1][:2], ["sandbox", "copy"])
        self.assertEqual(argvs[1][3], f"{name}:/tmp/agent.env")
        self.assertEqual(argvs[2][3], f"{name}:/tmp/bootstrap.sh")
        self.assertEqual(argvs[3], ["sandbox", "exec", name, "--", "bash", "/tmp/bootstrap.sh"])
        self.assertEqual(argvs[4][:5], ["sandbox", "exec", name, "--", "bash"])
        self.assertEqual(argvs[-1], ["sandbox", "remove", name])

    def test_the_env_file_is_copied_in_as_0600_and_holds_both_names(self):
        runner = vercel.RUNNER(self.farm.state)
        runner.create(spec_for(self.farm))
        copied = [entry for entry in self.farm.calls("sandbox") if "env_file" in entry]
        self.assertEqual(copied[0]["env_file"]["mode"], "0o600")
        self.assertEqual(sorted(copied[0]["env_file"]["keys"]), sorted(base.SECRET_NAMES))
        self.assertNotIn(OAUTH, self.farm.log_text())

    def test_the_session_budget_is_written_with_a_unit(self):
        self.assertEqual(vercel._duration(3600), "60m")
        self.assertEqual(vercel._duration(30), "1m")


class DigitalOceanAdapter(AdapterCase):
    def test_the_argv_of_a_whole_lane(self):
        runner = do_agents.RUNNER(self.farm.state)
        spec = spec_for(self.farm)
        handle = runner.create(spec)
        name = "fleet-lane-1"
        list(runner.run(handle))
        runner.fetch_bundle(handle, spec.base)
        runner.delete(handle)
        argvs = self.farm.argvs("doctl")
        self.assertEqual(argvs[0][:3], ["doctl", "harness-runtime", "create"])
        self.assertEqual(argvs[0][4:6], ["--name", name])
        self.assertIn("--secret", argvs[0])
        self.assertEqual(argvs[1][:7],
                         ["doctl", "harness-runtime", "exec", name, "--workdir",
                          "/workspace", "--"])
        self.assertEqual(argvs[2], ["doctl", "harness-runtime", "prompt", name, "-",
                                    "--on-hitl", "approve"])
        self.assertEqual(argvs[-1], ["doctl", "harness-runtime", "remove", name])

    def test_the_spec_names_the_adapter_and_both_secret_slots(self):
        runner = do_agents.RUNNER(self.farm.state)
        runner.create(spec_for(self.farm))
        created = self.farm.calls("doctl")[0]
        self.assertIn("agent: claude-code", created["spec"])
        for name in base.SECRET_NAMES:
            self.assertIn(name, created["spec"])
            self.assertEqual(created["secrets"][name]["mode"], "0o600")
        self.assertNotIn(OAUTH, created["spec"])
        self.assertNotIn(OAUTH, self.farm.log_text())

    def test_the_brief_reaches_prompt_on_stdin(self):
        runner = do_agents.RUNNER(self.farm.state)
        handle = runner.create(spec_for(self.farm))
        list(runner.run(handle))
        prompted = [entry for entry in self.farm.calls("doctl")
                    if entry["argv"][2] == "prompt"]
        self.assertIn("Do the slice.", prompted[0]["stdin"])

    def test_the_bundle_is_written_then_downloaded(self):
        runner = do_agents.RUNNER(self.farm.state)
        spec = spec_for(self.farm)
        handle = runner.create(spec)
        _write(os.path.join(self.farm.clone, "new.txt"), "work\n")
        git(self.farm.clone, "add", "-A")
        git(self.farm.clone, "commit", "-q", "-m", "Feat: work in the session")
        path = runner.fetch_bundle(handle, spec.base)
        self.addCleanup(os.unlink, path)
        self.assertTrue(os.path.exists(path))
        downloads = [entry["argv"] for entry in self.farm.calls("doctl")
                     if entry["argv"][2] == "download"]
        self.assertEqual(downloads[0][3:6],
                         ["fleet-lane-1", "--workspace-path", base.BUNDLE_NAME])

    def test_the_output_is_text_so_the_lane_reads_it_with_the_generic_parser(self):
        self.assertEqual(do_agents.RUNNER.output, "text")

    def test_a_doctl_without_harness_runtime_is_a_sentence(self):
        with mock.patch.dict(os.environ, {"FAKE_DOCTL_NO_HARNESS": "1"}):
            ready, sentence = do_agents.RUNNER(self.farm.state).available()
        self.assertFalse(ready)
        self.assertIn("harness-runtime", sentence)
        self.assertTrue(do_agents.RUNNER(self.farm.state).available()[0])


class Lane(unittest.TestCase):
    """run_remote.py end to end, as the unit runs it: a subprocess, with fakes on PATH."""

    def setUp(self):
        self.farm = Farm()
        self.addCleanup(self.farm.clean)

    def lane_argv(self, provider="railway", slug="lane-1"):
        return [sys.executable, os.path.join(RUNNERS, "run_remote.py"), provider,
                "--slug", slug, "--worktree", self.farm.work, "--repo", REPO,
                "--branch", BRANCH, "--model", "sonnet", "--brief", self.farm.brief,
                "--sys", self.farm.sys_file, "--identity-name", "test (agent)",
                "--identity-email", "test@agents.local", "--base-branch", "main"]

    def run_lane(self, provider="railway", slug="lane-1", timeout=120, lane_args=(), **extra):
        env = self.farm.env(FAKE_HANDLE_PATH=self.farm.handle_path(slug), **extra)
        return subprocess.run(self.lane_argv(provider, slug) + list(lane_args),
                              capture_output=True, text=True, env=env, timeout=timeout)

    # The steps of section 5, in order. ----------------------------------------------------

    def test_the_handle_file_is_written_before_the_provider_is_asked(self):
        done = self.run_lane()
        self.assertEqual(done.returncode, 0, done.stderr)
        created = self.farm.calls("railway")[0]
        self.assertTrue(created["handle_exists"],
                        "the runner record must exist before create is called")

    def test_a_refused_first_push_buys_no_sandbox(self):
        # The claims guard (or anything else) refusing the branch: work made in a sandbox
        # could never be pushed home, so no sandbox is created at all.
        hook = os.path.join(self.farm.remote, "hooks", "pre-receive")
        _write(hook, "#!/bin/sh\necho 'refused: this branch is claimed by another agent' >&2\n"
                     "exit 1\n")
        os.chmod(hook, 0o755)
        done = self.run_lane()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("could not be pushed", done.stderr)
        self.assertEqual([argv for argv in self.farm.argvs("railway")
                          if argv[:3] == ["railway", "sandbox", "create"]], [])
        self.assertFalse(os.path.exists(self.farm.handle_path("lane-1")))

    def test_the_handle_file_is_gone_and_the_sandbox_deleted_at_the_end(self):
        self.run_lane()
        self.assertFalse(os.path.exists(self.farm.handle_path("lane-1")))
        self.assertIn(["railway", "sandbox", "destroy", "sbx-fake-01"],
                      self.farm.argvs("railway"))

    def test_the_work_comes_home_mid_run_and_at_the_end(self):
        self.farm.set_transcript("starting", "@commit Feat: the middle", "@sleep 3",
                                 "still working", "@commit Feat: the end", "done")
        done = self.run_lane(timeout=180)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertGreaterEqual(done.stderr.count("brought the work home"), 2, done.stderr)
        log = git(self.farm.work, "log", "--oneline")
        self.assertIn("Feat: the middle", log)
        self.assertIn("Feat: the end", log)
        pushed = git(self.farm.remote, "log", "--oneline", BRANCH)
        self.assertIn("Feat: the end", pushed)

    def test_an_empty_range_brings_nothing_home(self):
        before = git(self.farm.work, "rev-parse", "HEAD")
        done = self.run_lane()
        self.assertNotIn("brought the work home", done.stderr)
        self.assertEqual(git(self.farm.work, "rev-parse", "HEAD"), before)

    def test_a_dirty_tree_is_committed_at_the_end(self):
        _write(os.path.join(self.farm.clone, "left-behind.txt"), "half a thought\n")
        done = self.run_lane()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("wip: uncommitted work at exit", git(self.farm.work, "log", "--oneline"))

    def test_the_pull_request_is_opened_with_the_title_the_sandbox_wrote(self):
        self.farm.set_pr_file("Feat: what the lane did\n\nThe body, for a person.\n")
        self.farm.set_transcript("working", "@commit Feat: what the lane did")
        done = self.run_lane()
        created = [entry for entry in self.farm.calls("gh")
                   if entry["argv"][:3] == ["gh", "pr", "create"]]
        self.assertEqual(len(created), 1, done.stderr)
        argv = created[0]["argv"]
        self.assertEqual(argv[3:5], ["--head", BRANCH])
        self.assertEqual(argv[5:7], ["--title", "Feat: what the lane did"])
        self.assertIn("The body, for a person.", created[0]["body"])
        self.assertNotIn("--draft", argv)

    def test_the_pull_request_text_is_scrubbed_before_it_is_published(self):
        # The one path where text leaves the sandbox and becomes public: the title is an argv
        # of a farm process and the body is published on GitHub.
        self.farm.set_pr_file(f"Feat: done {OAUTH}\n\nthe body carries {GITHUB} "
                              f"and {LOOSE_TOKEN}\n")
        self.farm.set_transcript("working", "@commit Feat: a lane that leaks")
        done = self.run_lane()
        created = [entry for entry in self.farm.calls("gh")
                   if entry["argv"][:3] == ["gh", "pr", "create"]]
        self.assertEqual(len(created), 1, done.stderr)
        published = json.dumps(created[0]["argv"]) + created[0]["body"]
        for secret in (OAUTH, GITHUB, LOOSE_TOKEN):
            self.assertNotIn(secret, published)
        self.assertIn("Feat: done [redacted]", created[0]["argv"])

    def test_a_missing_pull_request_file_gives_a_draft_named_for_the_branch(self):
        self.farm.set_transcript("working", "@commit Feat: no pr file")
        done = self.run_lane()
        created = [entry["argv"] for entry in self.farm.calls("gh")
                   if entry["argv"][:3] == ["gh", "pr", "create"]]
        self.assertTrue(created, done.stderr)
        self.assertIn("--draft", created[0])
        self.assertEqual(created[0][created[0].index("--title") + 1], BRANCH)

    def test_an_open_pull_request_is_not_opened_twice(self):
        self.farm.set_transcript("working", "@commit Feat: already open")
        self.run_lane(FAKE_PR_LIST='[{"number":3}]')
        self.assertEqual([entry for entry in self.farm.calls("gh")
                          if entry["argv"][:3] == ["gh", "pr", "create"]], [])

    def test_a_branch_with_nothing_on_it_opens_no_pull_request(self):
        self.run_lane()
        self.assertEqual([entry for entry in self.farm.calls("gh")
                          if entry["argv"][:3] == ["gh", "pr", "create"]], [])

    # A create that fails after the provider answered. -------------------------------------

    def test_an_unreadable_create_answer_keeps_the_record_for_a_person(self):
        # Railway made a sandbox but its answer carries no id, and `destroy` takes only an id,
        # so nothing on this farm can delete it: the record must survive to say so.
        done = self.run_lane(FAKE_CREATE_UNUSABLE="1")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(len([argv for argv in self.farm.argvs("railway")
                              if argv[:3] == ["railway", "sandbox", "create"]]), 1)
        self.assertTrue(os.path.exists(self.farm.handle_path("lane-1")), done.stderr)
        with open(self.farm.handle_path("lane-1"), encoding="utf-8") as handle:
            record = json.load(handle)
        self.assertEqual(record["name"], "fleet-lane-1")
        self.assertIn("by hand", done.stderr)

    def test_a_failure_after_create_deletes_the_sandbox_by_its_name(self):
        done = self.run_lane("vercel", FAKE_COPY_FAILS="1")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn(["sandbox", "remove", "fleet-lane-1"], self.farm.argvs("sandbox"))
        self.assertFalse(os.path.exists(self.farm.handle_path("lane-1")), done.stderr)

    def test_a_sandbox_that_would_not_go_keeps_its_record_for_the_reaper(self):
        done = self.run_lane(FAKE_DESTROY_FAILS="1")
        self.assertIn(["railway", "sandbox", "destroy", "sbx-fake-01"],
                      self.farm.argvs("railway"))
        self.assertTrue(os.path.exists(self.farm.handle_path("lane-1")), done.stderr)

    def test_a_brief_the_bootstrap_refuses_never_reaches_the_provider(self):
        _write(self.farm.brief, "a line\nFLEET_BRIEF_EOF\nanother\n")
        done = self.run_lane()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual([argv for argv in self.farm.argvs("railway")
                          if argv[:3] == ["railway", "sandbox", "create"]], [])
        self.assertFalse(os.path.exists(self.farm.handle_path("lane-1")), done.stderr)

    # The scrub. ---------------------------------------------------------------------------

    def test_no_secret_reaches_the_lane_log_the_stream_or_the_error_log(self):
        self.farm.set_transcript(
            f"the agent printed its environment: CLAUDE_CODE_OAUTH_TOKEN={OAUTH}",
            f"and a key that was never stored here: {LOOSE_TOKEN}",
            f"@stderr the provider CLI failed with {GITHUB}")
        lane_log = os.path.join(self.farm.root, "lane.jsonl")
        error_log = os.path.join(self.farm.root, "lane.err")
        with open(lane_log, "w") as out, open(error_log, "w") as err:
            subprocess.run(self.lane_argv(), stdout=out, stderr=err, timeout=120,
                           env=self.farm.env(
                               FAKE_HANDLE_PATH=self.farm.handle_path("lane-1")))
        streamed = open(lane_log, encoding="utf-8").read()
        errors = open(error_log, encoding="utf-8").read()
        for secret in (OAUTH, GITHUB, LOOSE_TOKEN):
            self.assertNotIn(secret, streamed)
            self.assertNotIn(secret, errors)
        self.assertIn("[redacted]", streamed)
        self.assertIn("[redacted]", errors)

    # Stopping. ----------------------------------------------------------------------------

    def test_a_lane_past_its_wall_clock_is_brought_home_and_deleted(self):
        self.farm.set_transcript("started", "@commit Feat: work before the deadline",
                                 "@sleep 60", "never printed")
        started = time.time()
        done = self.run_lane(lane_args=["--timeout-s", "3"], timeout=90)
        self.assertLess(time.time() - started, 45, done.stderr)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("wall clock", done.stderr)
        self.assertIn(["railway", "sandbox", "destroy", "sbx-fake-01"],
                      self.farm.argvs("railway"))
        self.assertIn("Feat: work before the deadline", git(self.farm.work, "log", "--oneline"))

    def test_a_stop_with_the_lane_log_already_closed_still_deletes_the_sandbox(self):
        self.farm.set_transcript("started", "@commit Feat: work before the stop", "@sleep 30")
        env = self.farm.env(FAKE_HANDLE_PATH=self.farm.handle_path("lane-1"))
        process = subprocess.Popen(self.lane_argv(), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, env=env)
        self.addCleanup(_reap_process, process)
        _wait_for(lambda: os.path.exists(self.farm.handle_path("lane-1")), 60)
        _wait_for(lambda: bool(self.farm.calls("railway")), 60)
        process.stdout.close()
        time.sleep(1)
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=90)
        self.assertIn(["railway", "sandbox", "destroy", "sbx-fake-01"],
                      self.farm.argvs("railway"))
        self.assertFalse(os.path.exists(self.farm.handle_path("lane-1")))
        self.assertIn("Feat: work before the stop", git(self.farm.work, "log", "--oneline"))


    def stop_during_create(self, provider, cli):
        env = self.farm.env(FAKE_HANDLE_PATH=self.farm.handle_path("lane-1"),
                            FAKE_CREATE_SLOW="30")
        process = subprocess.Popen(self.lane_argv(provider), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, env=env)
        self.addCleanup(_reap_process, process)
        _wait_for(lambda: any("create" in argv for argv in self.farm.argvs(cli)), 60)
        process.send_signal(signal.SIGTERM)
        _out, err = process.communicate(timeout=90)
        return err

    def test_a_stop_while_create_is_in_flight_deletes_the_sandbox_by_its_name(self):
        # `fleet kill` right after spawn: the provider may already hold the sandbox.
        err = self.stop_during_create("vercel", "sandbox")
        self.assertIn(["sandbox", "remove", "fleet-lane-1"], self.farm.argvs("sandbox"), err)
        self.assertFalse(os.path.exists(self.farm.handle_path("lane-1")), err)

    def test_a_stop_while_a_railway_create_is_in_flight_keeps_the_record_for_a_person(self):
        # Railway destroys by id only, and no id came back: the record must say so.
        err = self.stop_during_create("railway", "railway")
        self.assertTrue(os.path.exists(self.farm.handle_path("lane-1")), err)
        self.assertIn("by hand", err)
        done = subprocess.run([sys.executable, os.path.join(RUNNERS, "cli.py"), "reap"],
                              capture_output=True, text=True, env=self.farm.env(), timeout=120)
        self.assertIn("keep lane-1", done.stdout)
        self.assertIn("by hand", done.stdout)

    def test_the_wall_clock_running_out_during_create_deletes_the_sandbox_by_its_name(self):
        done = self.run_lane("vercel", lane_args=["--timeout-s", "1"], timeout=90,
                             FAKE_CREATE_SLOW="30")
        self.assertEqual(done.returncode, 124, done.stderr)
        self.assertIn(["sandbox", "remove", "fleet-lane-1"], self.farm.argvs("sandbox"))
        self.assertFalse(os.path.exists(self.farm.handle_path("lane-1")), done.stderr)


class Reap(unittest.TestCase):
    def setUp(self):
        self.farm = Farm()
        self.addCleanup(self.farm.clean)
        self.stopping = "lane-stopping"
        self.dead = "lane-dead"
        for slug in (self.stopping, self.dead):
            record = {"slug": slug, "provider": "railway", "id": "sbx-fake-01",
                      "name": f"fleet-{slug}", "base": git(self.farm.work, "rev-parse", "HEAD"),
                      "worktree": self.farm.work, "branch": BRANCH, "repo": REPO,
                      "base_branch": "main", "created_at": int(time.time())}
            path = self.farm.handle_path(slug)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _write(path, json.dumps(record))

    def reap(self, *args, **extra):
        states = json.dumps({f"fleet-{self.stopping}": "deactivating"})
        env = self.farm.env(FAKE_UNIT_STATES=states, **extra)
        return subprocess.run([sys.executable, os.path.join(RUNNERS, "cli.py"), "reap", *args],
                              capture_output=True, text=True, env=env, timeout=120)

    def test_a_stop_in_progress_is_left_alone_and_a_dead_lane_is_finished(self):
        done = self.reap()
        self.assertIn(f"keep {self.stopping}", done.stdout)
        self.assertIn(f"reaped {self.dead}", done.stdout)
        self.assertTrue(os.path.exists(self.farm.handle_path(self.stopping)))
        self.assertFalse(os.path.exists(self.farm.handle_path(self.dead)))
        self.assertEqual(self.farm.argvs("railway").count(
            ["railway", "sandbox", "destroy", "sbx-fake-01"]), 1)

    def test_the_dead_lane_s_work_comes_home_before_the_sandbox_goes(self):
        _write(os.path.join(self.farm.clone, "rescued.txt"), "work nobody saw\n")
        git(self.farm.clone, "add", "-A")
        git(self.farm.clone, "commit", "-q", "-m", "Feat: rescued by the reaper")
        self.reap()
        self.assertIn("Feat: rescued by the reaper", git(self.farm.work, "log", "--oneline"))

    def test_a_record_with_only_a_name_is_deleted_by_that_name(self):
        record = {"slug": "lane-named", "provider": "vercel", "name": "fleet-lane-named",
                  "base": git(self.farm.work, "rev-parse", "HEAD"), "branch": BRANCH,
                  "repo": REPO}
        _write(self.farm.handle_path("lane-named"), json.dumps(record))
        done = self.reap()
        self.assertIn(["sandbox", "remove", "fleet-lane-named"], self.farm.argvs("sandbox"))
        self.assertFalse(os.path.exists(self.farm.handle_path("lane-named")), done.stdout)

    def test_a_railway_record_with_no_id_is_kept_and_named_for_a_person(self):
        record = {"slug": "lane-noid", "provider": "railway", "name": "fleet-lane-noid",
                  "branch": BRANCH, "repo": REPO}
        _write(self.farm.handle_path("lane-noid"), json.dumps(record))
        done = self.reap()
        self.assertIn("keep lane-noid", done.stdout)
        self.assertIn("by hand", done.stdout)
        self.assertTrue(os.path.exists(self.farm.handle_path("lane-noid")))

    def test_a_delete_error_that_echoes_a_token_is_scrubbed(self):
        done = self.reap(FAKE_RAILWAY_LEAKS="1")
        self.assertIn(f"keep {self.dead}", done.stdout)
        self.assertIn("[redacted]", done.stdout)
        self.assertNotIn(OAUTH, done.stdout + done.stderr)

    def test_a_systemd_that_cannot_answer_reaps_nothing(self):
        done = self.reap(FAKE_SYSTEMCTL_FAILS="1")
        self.assertNotIn("reaped", done.stdout.replace("0 sandbox(es) reaped", ""))
        self.assertEqual(self.farm.argvs("railway"), [])
        self.assertTrue(os.path.exists(self.farm.handle_path(self.dead)))
        self.assertIn("could not be asked", done.stdout)

    def test_a_record_whose_process_is_alive_is_left_alone(self):
        # A `fleet runner test` has no unit; its record carries the pid that owns it.
        record = {"slug": "test-railway-1", "provider": "railway", "id": "sbx-fake-01",
                  "name": "fleet-test-railway-1", "pid": os.getpid()}
        _write(self.farm.handle_path("test-railway-1"), json.dumps(record))
        done = self.reap()
        self.assertIn("keep test-railway-1", done.stdout)
        self.assertTrue(os.path.exists(self.farm.handle_path("test-railway-1")))

    def test_a_dead_lane_gets_its_pull_request_before_the_sandbox_goes(self):
        # Otherwise --done-when pr-open never finishes and --restart until-pr buys another.
        _write(os.path.join(self.farm.clone, "rescued.txt"), "work nobody saw\n")
        git(self.farm.clone, "add", "-A")
        git(self.farm.clone, "commit", "-q", "-m", "Feat: rescued by the reaper")
        self.farm.set_pr_file("Feat: rescued\n\nThe reaper opened this.\n")
        done = self.reap()
        created = [entry for entry in self.farm.calls("gh")
                   if entry["argv"][:3] == ["gh", "pr", "create"]]
        self.assertEqual(len(created), 1, done.stdout + done.stderr)
        self.assertIn("Feat: rescued", created[0]["argv"])
        order = [entry["argv"][:3] for entry in self.farm.calls()
                 if entry["argv"][:3] in (["gh", "pr", "create"],
                                          ["railway", "sandbox", "destroy"])]
        self.assertEqual(order[0], ["gh", "pr", "create"])

    def test_dry_run_only_lists(self):
        done = self.reap("--dry-run")
        self.assertIn(f"would reap {self.dead}", done.stdout)
        self.assertTrue(os.path.exists(self.farm.handle_path(self.dead)))
        self.assertEqual(self.farm.argvs("railway"), [])


class TestCommand(unittest.TestCase):
    def setUp(self):
        self.farm = Farm()
        self.addCleanup(self.farm.clean)

    def run_test(self, provider="railway", **extra):
        return subprocess.run(
            [sys.executable, os.path.join(RUNNERS, "cli.py"), "test", provider,
             "--project", self.farm.project],
            capture_output=True, text=True, env=self.farm.env(**extra), timeout=120)

    def result_file(self, provider="railway"):
        path = os.path.join(self.farm.state, "hosts", provider, "tested.json")
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_a_passing_test_writes_the_seconds_and_deletes_the_sandbox(self):
        self.farm.set_transcript("claude 2.0.1", base.PROBE_OK)
        done = self.run_test()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        record = self.result_file()
        self.assertTrue(record["ok"])
        self.assertGreaterEqual(record["seconds"], 0)
        self.assertIn("seconds", done.stdout)
        self.assertIn(["railway", "sandbox", "destroy", "sbx-fake-01"],
                      self.farm.argvs("railway"))

    def test_a_failing_test_says_so_and_still_deletes(self):
        self.farm.set_transcript("claude: command not found", "@exit 1")
        done = self.run_test()
        self.assertEqual(done.returncode, 1)
        self.assertFalse(self.result_file()["ok"])
        self.assertIn(["railway", "sandbox", "destroy", "sbx-fake-01"],
                      self.farm.argvs("railway"))

    def test_a_provider_whose_cli_is_missing_never_creates_anything(self):
        done = self.run_test("do-agents", FAKE_DOCTL_NO_HARNESS="1")
        self.assertEqual(done.returncode, 1)
        self.assertIn("harness-runtime", done.stdout)
        self.assertFalse(self.result_file("do-agents")["ok"])
        self.assertEqual([argv for argv in self.farm.argvs("doctl")
                          if argv[2] == "create"], [])

    def test_a_provider_error_that_echoes_a_token_is_scrubbed_everywhere(self):
        # The failure path: a create that fails with the provider's own stderr, which is what
        # GET /api/hosts serves verbatim from tested.json.
        done = self.run_test(FAKE_RAILWAY_LEAKS="1")
        self.assertEqual(done.returncode, 1)
        path = os.path.join(self.farm.state, "hosts", "railway", "tested.json")
        self.assertNotIn(OAUTH, open(path, encoding="utf-8").read())
        self.assertIn("[redacted]", self.result_file()["detail"])
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        self.assertNotIn(OAUTH, done.stdout + done.stderr)

    def test_a_test_sandbox_whose_create_answer_is_unusable_keeps_a_record(self):
        done = self.run_test(FAKE_CREATE_UNUSABLE="1")
        self.assertEqual(done.returncode, 1)
        records = _glob(os.path.join(self.farm.state, "runners", "test-railway-*.json"))
        self.assertEqual(len(records), 1, done.stdout)
        with open(records[0], encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["provider"], "railway")
        self.assertIn("by hand", done.stdout)

    def test_a_test_sandbox_that_fails_after_create_is_deleted_by_name(self):
        done = self.run_test("vercel", FAKE_COPY_FAILS="1")
        self.assertEqual(done.returncode, 1)
        removed = [argv for argv in self.farm.argvs("sandbox") if argv[:2] == ["sandbox", "remove"]]
        self.assertEqual(len(removed), 1, done.stdout)
        self.assertEqual(_glob(os.path.join(self.farm.state, "runners", "*.json")), [])

    def test_a_ctrl_c_while_the_test_sandbox_is_created_deletes_it_by_name(self):
        process = subprocess.Popen(
            [sys.executable, os.path.join(RUNNERS, "cli.py"), "test", "vercel",
             "--project", self.farm.project], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=self.farm.env(FAKE_CREATE_SLOW="30"))
        self.addCleanup(_reap_process, process)
        _wait_for(lambda: any(argv[:2] == ["sandbox", "create"]
                              for argv in self.farm.argvs("sandbox")), 60)
        process.send_signal(signal.SIGINT)
        out, err = process.communicate(timeout=90)
        created = [argv for argv in self.farm.argvs("sandbox") if argv[:2] == ["sandbox", "create"]]
        name = created[0][created[0].index("--name") + 1]
        self.assertIn(["sandbox", "remove", name], self.farm.argvs("sandbox"), out + err)
        self.assertEqual(_glob(os.path.join(self.farm.state, "runners", "*.json")), [])

    def test_a_passing_test_leaves_no_record_behind(self):
        self.farm.set_transcript("claude 2.0.1", base.PROBE_OK)
        self.assertEqual(self.run_test().returncode, 0)
        self.assertEqual(_glob(os.path.join(self.farm.state, "runners", "*.json")), [])

    def test_a_secret_value_never_reaches_the_result_file(self):
        # Every road into tested.json: the probe's own output, a provider error raised as an
        # exception (create fails echoing the token), and a delete that fails the same way.
        roads = {
            "probe output": dict(),
            "create error": dict(FAKE_RAILWAY_LEAKS="1"),
        }
        for road, extra in roads.items():
            self.farm.set_transcript(f"claude 2.0.1 {OAUTH}", base.PROBE_OK)
            done = self.run_test(**extra)
            path = os.path.join(self.farm.state, "hosts", "railway", "tested.json")
            self.assertNotIn(OAUTH, open(path, encoding="utf-8").read(), road)
            self.assertNotIn(OAUTH, done.stdout + done.stderr, road)
        self.farm.set_transcript("claude 2.0.1", base.PROBE_OK)
        done = self.run_test(FAKE_DESTROY_LEAKS="1")
        self.assertEqual(done.returncode, 1)
        self.assertIn("[redacted]", self.result_file()["detail"])
        self.assertNotIn(OAUTH, json.dumps(self.result_file()) + done.stdout)


class Preflight(unittest.TestCase):
    def setUp(self):
        self.farm = Farm()
        self.addCleanup(self.farm.clean)

    def preflight(self, provider="railway", **extra):
        return subprocess.run(
            [sys.executable, os.path.join(RUNNERS, "cli.py"), "preflight", provider],
            capture_output=True, text=True, env=self.farm.env(**extra), timeout=120)

    def test_it_answers_with_the_clone_path_and_the_parser(self):
        done = self.preflight()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), f"{base.CLONE_DIR}\tstream-json")
        self.assertEqual(self.preflight("do-agents").stdout.strip(),
                         f"{base.CLONE_DIR}\ttext")

    def test_a_missing_secret_refuses_in_one_sentence(self):
        self.farm.drop_secret("railway", "CLAUDE_CODE_OAUTH_TOKEN")
        done = self.preflight()
        self.assertEqual(done.returncode, 1)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", done.stderr)
        self.assertEqual(len(done.stderr.strip().splitlines()), 1)

    def test_a_version_check_that_echoes_a_token_is_scrubbed(self):
        done = self.preflight(FAKE_RAILWAY_LEAKS="1")
        self.assertEqual(done.returncode, 1)
        self.assertIn("[redacted]", done.stderr)
        self.assertNotIn(OAUTH, done.stdout + done.stderr)

    def test_an_unknown_provider_names_the_three_that_exist(self):
        done = self.preflight("hetzner")
        self.assertEqual(done.returncode, 1)
        self.assertIn("railway", done.stderr)


def fake_fleet_home(root):
    """A copy of the shipped `bin/fleet` with a stub dashboard launcher.

    The script itself is the one that ships, byte for byte, so these tests exercise the real
    spawn. Only its dashboard starter is replaced, because no test may start this farm's
    dashboard, and its systemd is the fake one on PATH.
    """
    home = os.path.join(root, "fleet-home")
    os.makedirs(os.path.join(home, "bin"), exist_ok=True)
    os.makedirs(os.path.join(home, "dashboard"), exist_ok=True)
    binary = os.path.join(home, "bin", "fleet")
    shutil.copyfile(os.path.join(FLEET, "bin", "fleet"), binary)
    os.chmod(binary, 0o755)
    for name in ("lib", "systemd"):
        target = os.path.join(home, name)
        if not os.path.exists(target):
            os.symlink(os.path.join(FLEET, name), target)
    stub = os.path.join(home, "dashboard", "run.sh")
    _write(stub, "#!/bin/sh\nexit 0\n")
    os.chmod(stub, 0o755)
    return binary


class FleetCommand(unittest.TestCase):
    """`fleet spawn --runner`, `fleet kill` and `fleet sweep`, run as the shipped script."""

    def setUp(self):
        self.farm = Farm()
        self.addCleanup(self.farm.clean)
        self.fleet = fake_fleet_home(self.farm.root)

    def run_fleet(self, *args, **extra):
        return subprocess.run(["bash", self.fleet, *args], capture_output=True, text=True,
                              env=self.farm.env(**extra), timeout=300)

    def spawn(self, *args, **extra):
        return self.run_fleet("spawn", "--project", self.farm.project, "--lane", "remote",
                              "--task", "Do the slice.", "--force", *args, **extra)

    def record(self):
        states = sorted(_glob(os.path.join(self.farm.state, "state", "*.json")))
        with open(states[-1], encoding="utf-8") as handle:
            return json.load(handle), states[-1]

    def run_script(self):
        scripts = sorted(_glob(os.path.join(self.farm.state, "logs", "*.run.sh")))
        return open(scripts[-1], encoding="utf-8").read()

    # The refusals, one sentence each. -----------------------------------------------------

    def test_an_explicit_account_is_refused(self):
        done = self.spawn("--runner", "railway", "--account", "work")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", done.stdout)
        self.assertEqual(_glob(os.path.join(self.farm.state, "state", "*.json")), [])

    def test_another_engine_is_refused(self):
        done = self.spawn("--runner", "railway", "--engine", "codex")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("only the claude engine", done.stdout)

    def test_a_missing_secret_is_refused(self):
        self.farm.drop_secret("railway", "CLAUDE_CODE_OAUTH_TOKEN")
        done = self.spawn("--runner", "railway")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", done.stderr)

    def test_a_missing_cli_is_refused(self):
        thin = os.path.join(self.farm.root, "thin-path")
        os.makedirs(thin, exist_ok=True)
        for name in ("systemctl", "systemd-run", "gh", "tmux", "loginctl"):
            link = os.path.join(thin, name)
            if not os.path.exists(link):
                os.symlink(os.path.join(FAKES, name), link)
        done = self.spawn("--runner", "railway",
                          PATH=thin + ":/usr/local/bin:/usr/bin:/bin")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("railway", done.stderr)

    def test_a_provider_whose_check_fails_is_refused(self):
        done = self.spawn("--runner", "do-agents", FAKE_DOCTL_NO_HARNESS="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("harness-runtime", done.stderr)

    def test_a_farm_whose_sweep_timer_is_off_is_refused(self):
        done = self.spawn("--runner", "railway", FAKE_SWEEP_TIMER="disabled")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("sweep timer is off", done.stdout)

    def test_an_unknown_runner_is_refused(self):
        done = self.spawn("--runner", "hetzner")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("railway", done.stderr)

    # What a runner lane's unit gets. ------------------------------------------------------

    def test_the_run_script_streams_from_the_sandbox_through_the_stream_parser(self):
        done = self.spawn("--runner", "railway")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        script = self.run_script()
        self.assertIn("trap '' TERM", script)
        self.assertIn("runners/run_remote.py", script)
        self.assertIn('--timeout-s "28800"', script)
        self.assertIn("parse_stream.py", script)
        self.assertNotIn("parse_generic.py", script)
        self.assertIn("tee", script)
        self.assertLess(script.index("trap '' TERM"), script.index("| tee "))
        unit = [argv for argv in self.farm.argvs("systemd-run")][0]
        self.assertIn("--property=TimeoutStopSec=120", unit)
        record, _path = self.record()
        self.assertEqual(record["runner"], "railway")

    def test_the_runner_timeout_sets_the_lane_s_wall_clock(self):
        for given, seconds in (("90m", 5400), ("2h", 7200), ("1d", 86400), ("600", 600),
                               ("08h", 28800)):
            # One lane per duration: a spawn's branch is named for the lane and the minute.
            done = self.run_fleet("spawn", "--project", self.farm.project,
                                  "--lane", f"remote-{seconds}", "--task", "Do the slice.",
                                  "--force", "--runner", "railway", "--runner-timeout", given)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            script, = _glob(os.path.join(self.farm.state, "logs", f"remote-{seconds}-*.run.sh"))
            with open(script, encoding="utf-8") as handle:
                self.assertIn(f'--timeout-s "{seconds}"', handle.read(), given)

    def test_a_runner_timeout_that_is_not_a_duration_is_refused(self):
        for given in ("eight hours", "0h", "5w", "-1h", "1h; rm -rf ~"):
            done = self.spawn("--runner", "railway", "--runner-timeout", given)
            self.assertNotEqual(done.returncode, 0, given)
            self.assertIn("not a duration", done.stdout, given)
        done = self.spawn("--runner-timeout", "2h")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("has no --runner", done.stdout)
        self.assertEqual(_glob(os.path.join(self.farm.state, "state", "*.json")), [])

    def test_a_digitalocean_lane_reads_its_text_with_the_generic_parser(self):
        self.assertEqual(self.spawn("--runner", "do-agents").returncode, 0)
        script = self.run_script()
        self.assertIn("parse_generic.py", script)
        self.assertNotIn("parse_stream.py", script)

    def test_the_brief_names_the_sandbox_clone_and_carries_the_runner_paragraph(self):
        self.assertEqual(self.spawn("--runner", "railway").returncode, 0)
        briefs = sorted(_glob(os.path.join(self.farm.state, "logs", "*.sys")))
        brief = open(briefs[-1], encoding="utf-8").read()
        self.assertIn(base.CLONE_DIR, brief)
        self.assertNotIn(os.path.join(self.farm.state, "worktrees"), brief)
        self.assertIn("/tmp/fleet-pr.md", brief)
        self.assertNotIn("open a PR with `gh pr create`", brief)
        self.assertNotIn("runner-swap", brief)

    def test_a_local_lane_is_left_exactly_as_it_was(self):
        # A local lane resolves a Claude account, so the throwaway home carries one; a runner
        # lane must never need this, which is what the refusal tests above prove.
        claude_home = os.path.join(self.farm.home, ".claude")
        os.makedirs(claude_home, exist_ok=True)
        _write(os.path.join(claude_home, ".credentials.json"), "{}")
        done = self.spawn()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        script = self.run_script()
        self.assertNotIn("trap '' TERM", script)
        self.assertNotIn("run_remote.py", script)
        unit = [argv for argv in self.farm.argvs("systemd-run")][0]
        self.assertNotIn("--property=TimeoutStopSec=120", unit)
        briefs = sorted(_glob(os.path.join(self.farm.state, "logs", "*.sys")))
        brief = open(briefs[-1], encoding="utf-8").read()
        self.assertIn("open a PR with `gh pr create`", brief)
        self.assertNotIn("You run in a remote sandbox", brief)
        self.assertNotIn("runner-swap", brief)
        record, _path = self.record()
        self.assertNotIn("runner", record)

    def test_a_huge_brief_is_not_spilled_for_a_runner_lane(self):
        # A local lane hands the engine a pointer when the prompt is too big for one argument.
        # A runner lane's prompt never goes on an argv at all, and that pointer would name a
        # farm path the sandbox cannot read.
        big = os.path.join(self.farm.root, "big-brief.md")
        _write(big, "Do the slice, at length. " * 6000)
        done = self.run_fleet("spawn", "--project", self.farm.project, "--lane", "remote",
                              "--brief-file", big, "--force", "--runner", "railway")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("spilled", done.stdout)
        self.assertEqual(_glob(os.path.join(self.farm.state, "briefs", "*.prompt.md")), [])
        tasks = _glob(os.path.join(self.farm.state, "logs", "*.task"))
        self.assertGreater(os.path.getsize(tasks[-1]), 120000)

    # Stopping one, and the janitor. -------------------------------------------------------

    def test_kill_marks_a_runner_lane_before_it_stops_the_unit(self):
        self.assertEqual(self.spawn("--runner", "railway").returncode, 0)
        record, path = self.record()
        done = self.run_fleet("kill", record["slug"],
                              FAKE_WATCH_FILE=path, FAKE_WATCH_TEXT='"status": "killed"')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        stops = [entry for entry in self.farm.calls("systemctl")
                 if "stop" in entry["argv"]]
        self.assertIn("--no-block", stops[0]["argv"])
        self.assertTrue(stops[0]["watch"],
                        "the record must say killed before the unit is stopped")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["status"], "killed")

    def test_kill_replaces_the_record_atomically(self):
        # A dashboard reading during a bare truncate-and-write sees half a file; os.replace
        # swaps in a whole new file, which shows as a new inode.
        self.assertEqual(self.spawn("--runner", "railway").returncode, 0)
        record, path = self.record()
        before = os.stat(path).st_ino
        done = self.run_fleet("kill", record["slug"])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotEqual(os.stat(path).st_ino, before)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["status"], "killed")
        self.assertEqual(_glob(os.path.join(self.farm.state, "state", "*.tmp")), [])

    def test_the_sweep_runs_the_reaper_and_passes_its_dry_run_through(self):
        path = self.farm.handle_path("lane-dead")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write(path, json.dumps({"slug": "lane-dead", "provider": "railway",
                                 "id": "sbx-fake-01", "worktree": self.farm.work,
                                 "branch": BRANCH, "repo": REPO,
                                 "base": git(self.farm.work, "rev-parse", "HEAD")}))
        done = self.run_fleet("sweep", "--dry-run")
        self.assertIn("would reap lane-dead", done.stdout)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.farm.argvs("railway"), [])


def _wait_for(predicate, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    raise AssertionError("the lane never reached the state this test waits for")


def _reap_process(process):
    if process.poll() is None:
        process.kill()
        process.wait(timeout=30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
