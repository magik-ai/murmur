"""Vercel Sandbox: files in, one exec, everything else through more execs.

Two facts from the research (`internal/research/report-hosting-cli.md`, section 3) shape this
adapter. First, `-e` / `--env` put values on the command line, so the only way to hand over a
secret that keeps this lane's rule is the documented `sandbox copy`: a 0600 file goes in, the
bootstrap sources it and deletes it, and the sandbox is created `--non-persistent` so no stop
can snapshot it. Second, live streaming from a non-interactive `exec` is not documented, which
is marked UNVERIFIED on the one method that depends on it; the lane still works if the output
only arrives in blocks, it just arrives less smoothly than on Railway.

A session also has a hard cap (45 minutes on Hobby, 24 hours on Pro), so the lane's own budget
is passed as `--timeout` rather than left at the five minute default.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import base  # noqa: E402


class Vercel(base.Runner):
    id = "vercel"
    cli = "sandbox"
    label = "Vercel Sandbox"
    output = "stream-json"

    def available(self):
        # UNVERIFIED: no `sandbox whoami` exists, so this only proves the CLI is installed and
        # answers. Whether it is logged in shows up on the first create.
        return self._version_check(
            ["sandbox", "--version"],
            "the sandbox CLI is not installed on this farm (npm i -g sandbox)")

    def create(self, spec):
        """Create, then copy in the env file and the bootstrap.

        VERIFIED: `create --name N --vcpus 4 --timeout <duration> --non-persistent` and
        `copy ./f N:/abs/path`, one file per call. UNVERIFIED: whether `--timeout` takes a bare
        number, so a unit is always written.
        """
        missing = self.missing()
        if missing:
            raise base.RunnerError(
                f"vercel is missing the secret {', '.join(missing)} "
                "(store it: fleet hosts secret vercel <NAME>)")
        name = spec.sandbox_name
        # Built before the provider is asked, so a brief the bootstrap refuses costs nothing.
        handle = self._handle(spec, name)
        try:
            code, _out, err = self._capture(
                ["sandbox", "create", "--name", name, "--vcpus", str(spec.vcpus),
                 "--timeout", _duration(spec.timeout_s), "--non-persistent"])
        except base.CommandTimeout as exc:
            raise base.SandboxMayExist(str(exc))
        if code:
            raise base.RunnerError(f"the sandbox CLI could not create one: "
                                   f"{base.first_line(err) or code}")
        try:
            with base.private_files({"agent.env": base.env_text(self.secrets()),
                                     "bootstrap.sh": handle["bootstrap"]}) as paths:
                self._copy(name, paths["agent.env"], base.ENV_PATH)
                self._copy(name, paths["bootstrap.sh"], base.BOOTSTRAP_PATH)
        except base.RunnerError as exc:
            # The sandbox exists by now, and its name is all it takes to remove it.
            raise base.SandboxMayExist(str(exc))
        return handle

    def run(self, handle):
        """UNVERIFIED: the docs do not promise that a non-interactive exec streams. The
        bootstrap is a copied file rather than stdin for the same reason: stdin forwarding is
        not documented either."""
        argv = ["sandbox", "exec", _name(handle), "--", "bash", base.BOOTSTRAP_PATH]
        yield from base.stream_lines(argv)

    def exec_text(self, handle, script):
        # The short scripts carry a commit id and paths this farm built, never a secret and
        # never a value a person typed, so `bash -c` with the script as one argument is safe.
        code, out, err = self._capture(
            ["sandbox", "exec", _name(handle), "--", "bash", "-c", script])
        if code:
            raise base.RunnerError(f"the sandbox exec failed: {base.first_line(err) or code}")
        return out

    def delete(self, handle):
        code, _out, err = self._capture(["sandbox", "remove", _name(handle)], timeout=120)
        if code:
            raise base.RunnerError(f"the sandbox CLI could not remove the sandbox: "
                                   f"{base.first_line(err) or code}")

    def addressable(self, record):
        return bool((record or {}).get("name") or (record or {}).get("id"))

    def _copy(self, name, local_path, remote_path):
        code, _out, err = self._capture(
            ["sandbox", "copy", local_path, f"{name}:{remote_path}"])
        if code:
            raise base.RunnerError(f"the sandbox CLI could not copy a file in: "
                                   f"{base.first_line(err) or code}")


def _name(handle):
    value = (handle or {}).get("name") or (handle or {}).get("id")
    if not value:
        raise base.RunnerError("this runner record has no sandbox name")
    return str(value)


def _duration(seconds):
    """Vercel's own examples write a duration with a unit (`5h`), never a bare number."""
    minutes = max(1, int(seconds) // 60)
    return f"{minutes}m"


RUNNER = Vercel
