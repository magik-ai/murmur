"""Railway sandboxes: the reference adapter.

Railway is the only provider whose documentation shows both a live-streaming exec and stdin
forwarding (`internal/research/report-hosting-cli.md`, section 2), so the bootstrap travels on
stdin, the agent's output arrives line by line, and nothing needs a workaround. The other two
adapters are written to look like this one wherever their CLI lets them.

The default idle stop (30 minutes) is left alone on purpose: it is Railway's own backstop for a
sandbox this farm somehow fails to delete, and Railway defers it while an exec is running, so a
working lane is never cut off by it.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import base  # noqa: E402


class Railway(base.Runner):
    id = "railway"
    cli = "railway"
    label = "Railway sandboxes"
    output = "stream-json"

    def available(self):
        return self._version_check(
            ["railway", "--version"],
            "the railway CLI is not installed on this farm (npm i -g @railway/cli)")

    def create(self, spec):
        """One sandbox, with both secrets handed over as a 0600 env file.

        VERIFIED: `railway sandbox create --json --env-file F` and that `--variable` would put
        values on a command line, which is why the file is the only road here.
        """
        values = self.secrets()
        missing = self.missing()
        if missing:
            raise base.RunnerError(
                f"railway is missing the secret {', '.join(missing)} "
                "(store it: fleet hosts secret railway <NAME>)")
        # Built before the provider is asked, so a brief the bootstrap refuses costs nothing.
        handle = self._handle(spec, None)
        with base.private_files({"agent.env": base.env_text(values)}) as paths:
            try:
                code, out, err = self._capture(
                    ["railway", "sandbox", "create", "--json", "--env-file",
                     paths["agent.env"]])
            except base.CommandTimeout as exc:
                raise base.SandboxMayExist(str(exc))
        if code:
            raise base.RunnerError(f"railway could not create a sandbox: {base.first_line(err) or code}")
        try:
            handle["id"] = _sandbox_id(out)
        except base.RunnerError as exc:
            # The create succeeded, so a sandbox exists; only its id is unknown.
            raise base.SandboxMayExist(str(exc))
        return handle

    def run(self, handle):
        """The bootstrap on stdin, the agent's stream on stdout, line by line.

        VERIFIED: `railway sandbox exec --id ID -- <cmd>` streams live and forwards piped
        stdin, so `bash -s` reads the whole bootstrap from it and nothing large or private
        reaches an argv.
        """
        argv = ["railway", "sandbox", "exec", "--id", _id(handle), "--", "bash", "-s"]
        yield from base.stream_lines(argv, handle["bootstrap"])

    def exec_text(self, handle, script):
        code, out, err = self._capture(
            ["railway", "sandbox", "exec", "--id", _id(handle), "--", "bash", "-s"],
            stdin_text=script)
        if code:
            raise base.RunnerError(f"railway exec failed: {base.first_line(err) or code}")
        return out

    def delete(self, handle):
        code, _out, err = self._capture(["railway", "sandbox", "destroy", _id(handle)],
                                        timeout=120)
        if code:
            raise base.RunnerError(f"railway could not destroy the sandbox: "
                                   f"{base.first_line(err) or code}")


def _id(handle):
    value = (handle or {}).get("id")
    if not value:
        raise base.RunnerError("this runner record has no sandbox id")
    return str(value)


def _sandbox_id(text):
    """The id out of `create --json`.

    UNVERIFIED: the documentation shows the flag but not the shape of the object, so the three
    spellings a Railway object could plausibly use are all accepted, and anything else is a
    sentence rather than a lane that dies later with no sandbox to delete.
    """
    try:
        data = json.loads(text or "")
    except ValueError:
        raise base.RunnerError("railway create did not answer with JSON")
    if isinstance(data, dict):
        for key in ("id", "sandboxId", "sandbox_id"):
            if data.get(key):
                return str(data[key])
        nested = data.get("sandbox")
        if isinstance(nested, dict) and nested.get("id"):
            return str(nested["id"])
    raise base.RunnerError("railway create answered without a sandbox id")


RUNNER = Railway
