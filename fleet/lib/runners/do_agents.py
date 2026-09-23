"""DigitalOcean Managed Agents (Harness Runtime): the provider that runs the agent for you.

This one is shaped by what DigitalOcean's own tooling does, not by what this farm would
prefer (`internal/research/report-hosting-cli.md`, section 1):

- `exec` is buffered and reads no stdin, so the bootstrap runs in one call, as a `sh -c`
  argument, and the agent is started separately;
- the agent is started by `prompt`, which streams the adapter's own prose rather than Claude
  Code's stream-json, so `output` is text and a runner lane pipes it into `parse_generic.py`;
- there is no way to read a file back out of an exec's stdout reliably, so a bundle is written
  into the workspace and fetched with `download`;
- the `harness-runtime` commands merged into doctl on 2026-09-22 and a released build may not
  carry them, so `available()` asks `doctl harness-runtime --help` first and says so plainly.

UNVERIFIED, and said here as well as on the page: whether DigitalOcean's `claude-code` adapter
authenticates with CLAUDE_CODE_OAUTH_TOKEN at all. Its documentation talks about an Anthropic
API key and about routing through its own inference, which would be billed by DigitalOcean.
The secret slot is declared with the documented name; the first live Test on a farm is what
will settle it.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import base  # noqa: E402

# The spec file every session is created from. `agent: claude-code` is the documented adapter
# name, and the two slots are the guest environment variables the bootstrap and the adapter
# read. The ${VAR} placeholders are the documented spelling; the values themselves arrive as
# `--secret NAME=@<0600 file>`, so no token is ever written into this file.
# UNVERIFIED: whether a value given by --secret overrides the client-side ${VAR} expansion.
SPEC_YAML = """agent: claude-code
secrets:
  CLAUDE_CODE_OAUTH_TOKEN: ${CLAUDE_CODE_OAUTH_TOKEN}
  GITHUB_TOKEN: ${GITHUB_TOKEN}
"""


class DOAgents(base.Runner):
    id = "do-agents"
    cli = "doctl"
    label = "DigitalOcean Managed Agents"
    output = "text"
    runs_agent_itself = False

    def available(self):
        if not self.cli_installed():
            return False, ("doctl is not installed on this farm "
                           "(https://docs.digitalocean.com/reference/doctl/how-to/install/)")
        code, _out, err = self._capture(["doctl", "harness-runtime", "--help"], timeout=30)
        if code:
            return False, ("this doctl has no harness-runtime commands yet; they merged on "
                           "2026-09-22, so update doctl "
                           f"({base.first_line(err) or 'the help exited with an error'})")
        return True, "doctl can reach its harness-runtime commands"

    def create(self, spec):
        """One session from a spec file, with both secrets read out of 0600 files.

        SOURCE (doctl's own code, not the product docs): `--secret NAME=@path` reads the value
        from a file, which is why nothing here is on a command line.
        """
        missing = self.missing()
        if missing:
            raise base.RunnerError(
                f"do-agents is missing the secret {', '.join(missing)} "
                "(store it: fleet hosts secret do-agents <NAME>)")
        name = spec.sandbox_name
        # Built before the provider is asked, so a brief the bootstrap refuses costs nothing.
        handle = self._handle(spec, name)
        files = dict(self.secrets(), **{"harness.yaml": SPEC_YAML})
        with base.private_files(files) as paths:
            argv = ["doctl", "harness-runtime", "create", paths["harness.yaml"], "--name", name]
            for key in base.SECRET_NAMES:
                argv += ["--secret", f"{key}=@{paths[key]}"]
            try:
                code, _out, err = self._capture(argv)
            except base.CommandTimeout as exc:
                raise base.SandboxMayExist(str(exc))
        if code:
            raise base.RunnerError(f"doctl could not create a session: "
                                   f"{base.first_line(err) or code}")
        return handle

    def run(self, handle):
        """The bootstrap first, in one buffered exec, then the agent through `prompt`.

        VERIFIED: `exec S -- sh -c '...'` runs one command and returns its output.
        SOURCE: `prompt S - --on-hitl approve` reads the prompt from stdin and streams until
        the run completes, resolving every approval itself so nothing waits for a keyboard.
        """
        name = _name(handle)
        code, out, err = self._capture(
            ["doctl", "harness-runtime", "exec", name, "--workdir", base.WORKSPACE,
             "--", "sh", "-c", handle["bootstrap"]], timeout=1800)
        for line in (out or "").splitlines():
            yield line
        if code:
            raise base.RunnerError(f"the bootstrap failed inside the session: "
                                   f"{base.first_line(err) or code}")
        argv = ["doctl", "harness-runtime", "prompt", name, "-", "--on-hitl", "approve"]
        yield from base.stream_lines(argv, handle.get("brief") or "")

    def exec_text(self, handle, script):
        code, out, err = self._capture(
            ["doctl", "harness-runtime", "exec", _name(handle), "--workdir", base.WORKSPACE,
             "--", "sh", "-c", script])
        if code:
            raise base.RunnerError(f"doctl exec failed: {base.first_line(err) or code}")
        return out

    def addressable(self, record):
        return bool((record or {}).get("name") or (record or {}).get("id"))

    def fetch_bundle(self, handle, base_sha):
        """Written inside the session, then fetched: `exec` output is buffered and would have
        to carry the whole bundle through it otherwise.

        VERIFIED: `download S --workspace-path <path> --save-to <path>`, and the path is
        workspace-relative, which is why every provider clones into the same workspace.
        """
        name = _name(handle)
        remote = f"{base.WORKSPACE}/{base.BUNDLE_NAME}"
        text = self.exec_text(handle, base.bundle_script(base_sha, out_path=remote))
        if base.BUNDLE_EMPTY in (text or ""):
            return None
        with base.temp_dir() as folder:
            local = os.path.join(folder, base.BUNDLE_NAME)
            code, _out, err = self._capture(
                ["doctl", "harness-runtime", "download", name,
                 "--workspace-path", base.BUNDLE_NAME, "--save-to", local])
            if code:
                raise base.RunnerError(f"doctl could not download the bundle: "
                                       f"{base.first_line(err) or code}")
            with open(local, encoding="utf-8", errors="replace") as handle_in:
                payload = base.payload(handle_in.read())
        return self._write_bundle(payload)

    def delete(self, handle):
        code, _out, err = self._capture(
            ["doctl", "harness-runtime", "remove", _name(handle)], timeout=120)
        if code:
            raise base.RunnerError(f"doctl could not remove the session: "
                                   f"{base.first_line(err) or code}")


def _name(handle):
    value = (handle or {}).get("name") or (handle or {}).get("id")
    if not value:
        raise base.RunnerError("this runner record has no session name")
    return str(value)


RUNNER = DOAgents
