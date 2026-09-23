"""What every runner adapter is, and everything the three of them share.

A runner is one lane's agent process running in a provider's sandbox instead of on this farm.
The farm still owns the worktree, the branch, the claim, the log and the pull request; the
sandbox only holds a clone and the agent.

The parts that must be identical on every provider live here, because a difference between
them would be a difference in how a lane's work comes home:

- the bootstrap the sandbox runs (design record section 5, step 3): a git credential helper
  that reads the read-only token from the environment, a partial clone of the lane's branch,
  the lane's own commit identity, then `claude -p` on the person's subscription token. It
  never uses `set -x`, because a traced line would print the token into the lane log;
- the small remote scripts that answer "where is HEAD", "give me the new commits" and "what
  is in this file", each one marked with a `# fleet-op:` line so a reader (and the test's fake
  CLI) can tell at a glance what is being asked;
- the env file: mode 0600 inside a mode 0700 directory, deleted as soon as the provider has
  read it, so a secret never reaches an argv or a world-readable path.

An adapter implements `available`, `create`, `run`, `delete` and one buffered `exec_text`;
`head`, `fetch_bundle`, `read_file` and `commit_dirty` are written once, here, on top of it.
"""
import base64
import binascii
import contextlib
import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Where a sandbox keeps the lane's clone. One path for all three providers: DigitalOcean's
# download command takes a workspace-relative path, and one constant keeps the brief, the
# bootstrap and the bundle talking about the same directory.
WORKSPACE = "/workspace"
CLONE_DIR = WORKSPACE + "/repo"
BRIEF_PATH = "/tmp/fleet-brief.md"
SYS_PATH = "/tmp/fleet-sys.md"
ENV_PATH = "/tmp/agent.env"
BOOTSTRAP_PATH = "/tmp/bootstrap.sh"
PR_PATH = "/tmp/fleet-pr.md"
BUNDLE_NAME = "fleet.bundle.b64"

SECRET_NAMES = ("CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN")
PROVIDERS = ("railway", "vercel", "do-agents")
_MODULES = {"railway": "railway", "vercel": "vercel", "do-agents": "do_agents"}

BUNDLE_EMPTY = "FLEET-BUNDLE-EMPTY"
BEGIN = "FLEET-PAYLOAD-BEGIN"
END = "FLEET-PAYLOAD-END"
MISSING = "FLEET-FILE-MISSING"
PROBE_OK = "FLEET-PROBE-OK"

SHA = re.compile(r"\b[0-9a-f]{40}\b")
WHOLE_SHA = re.compile(r"\A[0-9a-f]{40}\Z")
SAFE_REPO = re.compile(r"\A[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\Z")
SAFE_BRANCH = re.compile(r"\A[A-Za-z0-9._/-]+\Z")
SAFE_NAME = re.compile(r"\A[A-Za-z0-9._-]+\Z")
SAFE_PATH = re.compile(r"\A[A-Za-z0-9._/-]+\Z")

# Claude Code's own install line, used only when the provider's image does not carry it.
INSTALL_CLAUDE = "npm install -g @anthropic-ai/claude-code"


class RunnerError(RuntimeError):
    """Something the provider or the sandbox did that the lane cannot work around.

    The message is written for the lane log, so it never carries a secret value: adapters put
    the provider's own stderr through `scrub` before it reaches one of these.
    """


class CommandTimeout(RunnerError):
    """A provider command that did not answer in time: whatever it was doing may have happened."""


class SandboxMayExist(RunnerError):
    """`create` failed after the provider was asked, so a sandbox may be billing already.

    The caller keeps the runner record (it names the sandbox) and tries to delete it by that
    name; a record the provider cannot be addressed by stays on disk for a person to act on.
    """


class Spec:
    """Everything a sandbox needs to become one lane's agent."""

    def __init__(self, slug, repo, branch, base, model, brief_path, sys_path,
                 identity, timeout_s=8 * 3600, vcpus=4):
        if not SAFE_NAME.match(slug or ""):
            raise RunnerError(f"unsafe lane slug {slug!r}")
        if not SAFE_REPO.match(repo or ""):
            raise RunnerError(f"unsafe repository {repo!r} (expected owner/name)")
        if branch and not SAFE_BRANCH.match(branch):
            raise RunnerError(f"unsafe branch {branch!r}")
        self.slug = slug
        self.repo = repo
        self.branch = branch
        self.base = base
        self.model = model or "sonnet"
        self.brief_path = brief_path
        self.sys_path = sys_path
        self.identity = identity or {}
        self.timeout_s = int(timeout_s)
        self.vcpus = int(vcpus)

    @property
    def sandbox_name(self):
        """The provider-visible name. `fleet-` marks it as this farm's, for a person reading
        a provider console and for anyone hunting a sandbox nobody deleted."""
        return "fleet-" + self.slug

    def read(self, path):
        if not path:
            return ""
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()


def runner_for(provider, state_dir=None):
    """The adapter for a provider id, or a RunnerError naming the three that exist."""
    if provider not in _MODULES:
        raise RunnerError(f"unknown runner provider {provider!r} "
                          f"(one of {', '.join(PROVIDERS)})")
    module = importlib.import_module(_MODULES[provider])
    return module.RUNNER(state_dir)


def state_root(state_dir=None):
    return state_dir or os.environ.get("FLEET_STATE") or os.path.expanduser("~/.fleet")


def secret_path(provider, name, state_dir=None):
    return os.path.join(state_root(state_dir), "secrets", "hosts", provider, name)


def read_secret(provider, name, state_dir=None):
    """The stored value, or None. Read from a 0600 file the core lane's `fleet hosts secret`
    wrote; it is never passed on an argv and never printed."""
    try:
        with open(secret_path(provider, name, state_dir), encoding="utf-8") as handle:
            value = handle.read().strip()
    except (OSError, UnicodeError):
        return None
    return value or None


def missing_secrets(provider, state_dir=None):
    return [name for name in SECRET_NAMES if not read_secret(provider, name, state_dir)]


@contextlib.contextmanager
def private_files(files):
    """Files of text, each 0600, in one 0700 directory, removed when the block ends.

    The one shape in which anything private leaves this farm: the env file of secrets a
    provider reads, a secret per file for `NAME=@<file>`, a bootstrap or a pull request body
    too large or too structured for an argv. Nothing about it reaches an argv, a log or an
    exception. Yields a dict of the same names to their paths.
    """
    folder = tempfile.mkdtemp(prefix="fleet-runner-")
    os.chmod(folder, 0o700)
    paths = {}
    try:
        for name, text in files.items():
            if not SAFE_NAME.match(name):
                raise RunnerError(f"unsafe file name {name!r}")
            path = os.path.join(folder, name)
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                out.write(text)
            paths[name] = path
        yield paths
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def env_text(values):
    """KEY=VALUE lines for an env file. A value spanning lines would inject a second key."""
    lines = []
    for key, value in values.items():
        if "\n" in value or "\r" in value:
            raise RunnerError(f"the stored value for {key} spans more than one line")
        lines.append(f"{key}={value}\n")
    return "".join(lines)


@contextlib.contextmanager
def temp_dir():
    """A 0700 directory, removed when the block ends: somewhere a provider may write."""
    folder = tempfile.mkdtemp(prefix="fleet-runner-")
    os.chmod(folder, 0o700)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _heredoc(marker, text, path):
    """A quoted heredoc: the sandbox writes the text byte for byte, expanding nothing.

    The brief is the only large thing that has to reach a sandbox that takes one stdin, so it
    travels inside the bootstrap. A brief that contained the marker line would end the
    heredoc early, so that is refused rather than silently truncated.
    """
    if any(line.strip() == marker for line in text.splitlines()):
        raise RunnerError(f"the text to send contains the line {marker}")
    return f"cat > {path} <<'{marker}'\n{text}\n{marker}\n"


ENV_PROLOGUE = f"""if [ -f {ENV_PATH} ]; then
  set -a
  . {ENV_PATH}
  set +a
  rm -f {ENV_PATH}
fi
"""

CREDENTIAL_HELPER = (
    "git config --global credential.helper "
    "'!f() { test \"$1\" = get && printf \"username=x-access-token\\npassword=%s\\n\" "
    "\"${GITHUB_TOKEN}\"; }; f'\n"
)


def bootstrap(spec, with_agent=True):
    """The script a sandbox runs, from an empty box to a working agent (section 5, step 3).

    `with_agent=False` stops one line short of starting the agent: DigitalOcean's own adapter
    starts it, through `prompt`, in the checkout this script prepares.

    There is no `set -x` anywhere in it, and the two tokens are only ever read from the
    environment the provider set up, never interpolated into this text.
    """
    brief = spec.read(spec.brief_path)
    system = spec.read(spec.sys_path)
    name = (spec.identity or {}).get("name", "")
    email = (spec.identity or {}).get("email", "")
    script = [
        "# fleet-op: bootstrap\n",
        "# No shell tracing here, ever: a traced line would print the tokens into the log.\n",
        "set -eu\n",
        "umask 077\n",
        ENV_PROLOGUE,
        _heredoc("FLEET_BRIEF_EOF", brief, BRIEF_PATH),
        _heredoc("FLEET_SYS_EOF", system, SYS_PATH),
        "# The read-only token reaches git through a helper, so it is in no URL and in no\n"
        "# process list inside the sandbox either.\n",
        CREDENTIAL_HELPER,
        f"mkdir -p {WORKSPACE}\n",
        f"if [ ! -d {CLONE_DIR}/.git ]; then\n"
        f"  git clone --filter=blob:none --branch '{spec.branch}' "
        f"'https://github.com/{spec.repo}.git' {CLONE_DIR}\n"
        "fi\n",
        f"cd {CLONE_DIR}\n",
        f"git config user.name '{_quote(name)}'\n",
        f"git config user.email '{_quote(email)}'\n",
        "# Whichever way this script ends, the work in the tree becomes a commit, so the\n"
        "# farm's next bundle carries it home.\n",
        f"trap 'cd {CLONE_DIR} && git add -A && git diff --cached --quiet "
        "|| git commit -q -m \"wip: uncommitted work at exit\"' EXIT INT TERM\n",
        f"command -v claude >/dev/null 2>&1 || {INSTALL_CLAUDE} >/dev/null 2>&1 || true\n",
        "unset ANTHROPIC_API_KEY\n",
    ]
    if with_agent:
        # The brief and the system prompt stay files (section 5, step 3): the brief reaches
        # `claude -p` on its stdin, so neither is in the sandbox's process list or against
        # ARG_MAX. No --include-partial-messages: a token split across two delta lines could
        # slip past the scrub, and nothing here needs a half-written sentence.
        agent = (f"claude -p --model '{_quote(spec.model)}' "
                 "--output-format stream-json --verbose --dangerously-skip-permissions")
        script.append(
            # UNVERIFIED by this lane's research: --append-system-prompt-file. claude 2.1 lists
            # it only in bracket form, `--append-system-prompt[-file]`, so both spellings count.
            # A claude that lists neither gets the framing ahead of the brief on the same stdin
            # instead, which keeps the argv clean either way.
            "if claude --help 2>/dev/null "
            "| grep -Eq -- '--append-system-prompt(-file|\\[-file\\])'; then\n"
            f"  {agent} --append-system-prompt-file {SYS_PATH} < {BRIEF_PATH}\n"
            "else\n"
            f"  cat {SYS_PATH} {BRIEF_PATH} | {agent}\n"
            "fi\n"
        )
    return "".join(script)


def _quote(value):
    """A value going inside single quotes in a generated script. A single quote in a name
    would end the quoting, so it is dropped rather than escaped into something unreadable."""
    return (value or "").replace("'", "")


def head_script():
    return (f"# fleet-op: head\n"
            f"cd {CLONE_DIR} 2>/dev/null || exit 1\n"
            f"git rev-parse HEAD\n")


def commit_dirty_script():
    """Commit whatever the agent left in the tree, so the last bundle carries it home."""
    return (f"# fleet-op: commit-dirty\n"
            f"cd {CLONE_DIR} 2>/dev/null || exit 1\n"
            f"git add -A\n"
            f"git diff --cached --quiet || git commit -q -m 'wip: uncommitted work at exit'\n"
            f"git rev-parse HEAD\n")


def bundle_script(base_sha, out_path=None):
    """Print the commits after <base> as one base64 bundle, or say the range is empty.

    base64 on every provider, because two of the three give no promise about binary output,
    and a bundle that arrives corrupted would look like lost work.
    """
    if not SHA.match(base_sha or ""):
        raise RunnerError(f"unsafe base commit {base_sha!r}")
    target = f"> {out_path}" if out_path else ""
    return (f"# fleet-op: bundle\n"
            f"set -eu\n"
            f"cd {CLONE_DIR}\n"
            f"if [ -z \"$(git rev-list {base_sha}..HEAD 2>/dev/null | head -n 1)\" ]; then\n"
            f"  echo '{BUNDLE_EMPTY}'\n"
            f"  exit 0\n"
            f"fi\n"
            f"git bundle create /tmp/fleet.bundle {base_sha}..HEAD >/dev/null 2>&1\n"
            f"{{ echo '{BEGIN}'; base64 < /tmp/fleet.bundle; echo '{END}'; }} {target}\n")


def read_file_script(path):
    if not SAFE_PATH.match(path or ""):
        raise RunnerError(f"unsafe path {path!r}")
    return (f"# fleet-op: read-file\n"
            f"[ -f '{path}' ] || {{ echo '{MISSING}'; exit 0; }}\n"
            f"echo '{BEGIN}'\n"
            f"base64 < '{path}'\n"
            f"echo '{END}'\n")


def probe_script(repo):
    """The Test of design section 5: the two secrets, exercised, and nothing else."""
    if not SAFE_REPO.match(repo or ""):
        raise RunnerError(f"unsafe repository {repo!r} (expected owner/name)")
    return ("# fleet-op: probe\n"
            "set -eu\n"
            + ENV_PROLOGUE
            + CREDENTIAL_HELPER
            + f"command -v claude >/dev/null 2>&1 || {INSTALL_CLAUDE} >/dev/null 2>&1 || true\n"
            + "claude --version\n"
            + f"git ls-remote 'https://github.com/{repo}' HEAD >/dev/null\n"
            + f"echo '{PROBE_OK}'\n")


def payload(text):
    """The base64 between the two markers, decoded. None when the sandbox said there was
    nothing (an empty commit range, a file that is not there)."""
    if text is None:
        return None
    lines = text.splitlines()
    if BEGIN not in lines:
        return None
    body = lines[lines.index(BEGIN) + 1:]
    if END in body:
        body = body[:body.index(END)]
    try:
        return base64.b64decode("".join(part.strip() for part in body), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RunnerError(f"the sandbox sent a bundle this farm cannot decode: {exc}")


# What a runner record on disk keeps. The handle an adapter hands back also carries the
# bootstrap and the brief, which are large and belong in the lane log's world, not in a file
# the reaper reads; `durable` drops them.
DURABLE = ("provider", "name", "id", "slug", "repo", "branch", "worktree", "base",
           "created_at")


def durable(handle):
    return {key: value for key, value in (handle or {}).items() if key in DURABLE}


def last_sha(text):
    """The commit a script printed last, or None. Only a last line that IS a commit id counts:
    a provider banner or warning that happens to hold 40 hex characters is not a HEAD."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines and WHOLE_SHA.match(lines[-1]) else None


def first_line(text):
    """The first line a provider CLI printed, for a sentence a person will read."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[0].strip() if lines else ""


def stream_lines(argv, stdin_text=None):
    """Run a provider command, feed it stdin, and yield its stdout line by line as it arrives.

    Its stderr stays on this process's stderr on purpose: run_remote.py puts a scrubbing
    filter there before it starts anything, so a provider that prints a token into an error
    still cannot write one into the lane log.
    """
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, bufsize=1)
    # The bootstrap carries the whole brief, which is easily larger than a pipe buffer, and a
    # sandbox that answers while it is still being fed would deadlock a straight write.
    threading.Thread(target=_feed, args=(process, stdin_text), daemon=True).start()
    try:
        for line in process.stdout:
            yield line.rstrip("\n")
    finally:
        try:
            process.stdout.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()


def _feed(process, text):
    try:
        if text is not None:
            process.stdin.write(text)
        process.stdin.close()
    except (BrokenPipeError, ValueError, OSError):
        pass


class Runner:
    """One provider. Adapters override the five provider-shaped methods below."""

    id = ""
    cli = ""
    label = ""
    # False for a provider whose own adapter starts the agent (DigitalOcean): then the
    # bootstrap stops one line short and the brief is handed over separately.
    runs_agent_itself = True
    # Which parser a runner lane's run.sh pipes the stream into: stream-json for a sandbox
    # that runs `claude -p` itself, text for DigitalOcean, whose adapter prints prose.
    output = "stream-json"
    clone_dir = CLONE_DIR

    def __init__(self, state_dir=None, timeout_s=300):
        self.state_dir = state_root(state_dir)
        self.timeout_s = timeout_s

    # Provider-shaped. --------------------------------------------------------------------

    def available(self):
        """(True, sentence) when this farm could use the provider right now, else (False, why)."""
        raise NotImplementedError

    def create(self, spec):
        """Make one sandbox and return its handle: a small dict this farm can write to disk."""
        raise NotImplementedError

    def run(self, handle):
        """Start the agent and yield its output line by line, as it arrives."""
        raise NotImplementedError

    def delete(self, handle):
        """Destroy the sandbox. Costs stop here, so this runs on every path out."""
        raise NotImplementedError

    def exec_text(self, handle, script):
        """Run a short script inside the sandbox and return everything it printed."""
        raise NotImplementedError

    # Written once for every provider. ----------------------------------------------------

    def head(self, handle):
        """The sandbox's current commit, or None while there is no checkout yet."""
        return last_sha(self.exec_text(handle, head_script()))

    def commit_dirty(self, handle):
        """Commit what the agent left behind; returns the commit the sandbox is on."""
        return last_sha(self.exec_text(handle, commit_dirty_script()))

    def fetch_bundle(self, handle, base_sha):
        """A local path holding `base..HEAD` as a git bundle, or None for an empty range."""
        text = self.exec_text(handle, bundle_script(base_sha))
        if text is None or BUNDLE_EMPTY in text:
            return None
        return self._write_bundle(payload(text))

    def read_file(self, handle, path):
        """A file's text from inside the sandbox, or None when it is not there."""
        text = self.exec_text(handle, read_file_script(path))
        if text is None or MISSING in text:
            return None
        raw = payload(text)
        if raw is None:
            return None
        return raw.decode("utf-8", errors="replace")

    def probe(self, handle, repo):
        """Test: the stored secrets, used once each, inside a live sandbox."""
        text = self.exec_text(handle, probe_script(repo)) or ""
        return PROBE_OK in text, text

    def secrets(self):
        """The two values this provider needs, read fresh from their 0600 files."""
        values = {}
        for name in SECRET_NAMES:
            value = read_secret(self.id, name, self.state_dir)
            if value:
                values[name] = value
        return values

    def missing(self):
        return missing_secrets(self.id, self.state_dir)

    def addressable(self, record):
        """Whether `delete` can find this sandbox from a runner record alone. An id always
        can; providers whose sandbox is named by this farm (`fleet-<slug>`) accept the name."""
        return bool((record or {}).get("id"))

    def cli_installed(self):
        return bool(shutil.which(self.cli))

    def _handle(self, spec, sandbox_id):
        """The dict that is this sandbox for the rest of the run."""
        return {"provider": self.id, "name": spec.sandbox_name, "id": sandbox_id,
                "slug": spec.slug, "repo": spec.repo, "branch": spec.branch,
                "base": spec.base,
                "bootstrap": bootstrap(spec, with_agent=self.runs_agent_itself),
                "brief": spec.read(spec.brief_path)}

    # Shared plumbing. --------------------------------------------------------------------

    def _write_bundle(self, raw):
        if not raw:
            return None
        handle = tempfile.NamedTemporaryFile(prefix="fleet-bundle-", suffix=".bundle",
                                             delete=False)
        with handle:
            handle.write(raw)
        return handle.name

    def _capture(self, argv, stdin_text=None, timeout=None):
        """Run a provider command and return (returncode, stdout, stderr).

        argv is always a list, so nothing the caller holds can become another command. The
        caller scrubs before it shows any of this to anyone.
        """
        try:
            # Always an stdin pipe, even when there is nothing to send: a provider CLI that
            # reads stdin must never inherit this lane's, and block on it.
            done = subprocess.run(argv, input=stdin_text or "", capture_output=True,
                                  text=True, timeout=timeout or self.timeout_s)
        except FileNotFoundError:
            raise RunnerError(f"{self.cli} is not installed on this farm")
        except subprocess.TimeoutExpired:
            raise CommandTimeout(f"{argv[0]} {argv[1] if len(argv) > 1 else ''} "
                              f"did not answer in {timeout or self.timeout_s} seconds")
        return done.returncode, done.stdout, done.stderr

    def _version_check(self, argv, sentence_when_missing):
        if not self.cli_installed():
            return False, sentence_when_missing
        try:
            code, _out, err = self._capture(argv, timeout=30)
        except RunnerError as exc:
            return False, str(exc)
        if code:
            first = (err or "").strip().splitlines()
            return False, f"{self.cli} answered with an error: {first[0] if first else code}"
        return True, f"{self.cli} is installed"
