"""Installing hq, and caching the head office, are two different jobs.

`hq install` used to do both: it cloned the head office into the state dir and
symlinked `<cache>/bin/hq` into the bin dir. That assumes every head office
repo is a copy of hq's own source. A head office that holds claims, mailboxes
and nothing else - which is what the README tells a stranger to create - gave
an install a traceback, on the path the README calls the upgrade.

So: install only links (or says which installer owns the command), the cache
clone is made lazily by the commands that read the office, and neither of them
assumes a branch called `main`.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from hq import claims, cli
from hq.config import load_config


def install():
    cli.cmd_install(argparse.Namespace())


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True)


def test_install_needs_no_head_office_at_all(monkeypatch, capsys):
    """No repo configured, no network, no clone of anything: installing the
    CLI is a local act. Requiring the office here made the first command a
    stranger runs fail on a machine that is not set up yet."""
    monkeypatch.delenv("HQ_REPO", raising=False)
    monkeypatch.setattr(claims, "ensure_cache",
                        lambda cfg=None: pytest.fail("install must not touch the office"))
    install()
    cfg = load_config()
    target = cfg.bin_dir / "hq"
    assert target.is_symlink()
    assert target.resolve() == cli.clone_script().resolve()
    assert not cfg.cache.exists()  # the cache is somebody else's job
    assert "hq installed" in capsys.readouterr().out


def test_install_links_this_clone_not_a_copy_of_hq_inside_the_office(monkeypatch):
    """The link points at the clone this code runs from. The old version
    pointed at <cache>/bin/hq and crashed when the office had no bin/hq."""
    monkeypatch.setenv("HQ_REPO", "acme/office")
    install()
    target = load_config().bin_dir / "hq"
    assert target.resolve().name == "hq"
    assert target.resolve().parent.name == "bin"
    assert (target.resolve().parent.parent / "src" / "hq" / "cli.py").exists()


def test_install_is_idempotent(monkeypatch):
    install()
    install()
    assert (load_config().bin_dir / "hq").is_symlink()


def test_an_installed_package_is_told_which_installer_owns_the_command(
        monkeypatch, capsys):
    """Installed with uv or pipx there is no clone to link, and no bin dir of
    ours to write into. Say the one line that installs it instead of inventing
    a link."""
    monkeypatch.setattr(cli, "clone_script", lambda: None)
    install()
    out = capsys.readouterr().out
    assert "uv tool install --from . hq-cli" in out
    assert "pipx install ." in out
    assert not (load_config().bin_dir / "hq").exists()


def test_a_failed_link_is_one_line_not_a_traceback(monkeypatch, tmp_path):
    """Setup scripts run this. A stack trace there tells nobody what to do."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory\n")
    config = tmp_path / "home" / ".config" / "hq" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f'bin_dir = "{blocker}/nested"\n')
    with pytest.raises(SystemExit) as stop:
        install()
    message = str(stop.value)
    assert message.startswith("hq: cannot link")
    assert message.count("\n") == 0


def bare_office(path, branch):
    """A head office repo on a named default branch, on disk, no network."""
    git("init", "--bare", f"--initial-branch={branch}", str(path))
    work = path.parent / f"work-{branch}"
    git("clone", str(path), str(work))
    (work / "README.md").write_text("the office\n")
    git("add", "-A", cwd=work)
    git("-c", "user.email=t@example.com", "-c", "user.name=t",
        "commit", "-m", "office", cwd=work)
    git("push", "origin", branch, cwd=work)
    return path


def test_the_cache_clone_follows_the_office_default_branch(monkeypatch, tmp_path):
    """`main` was hardcoded. An office on `master`, or on anything else a team
    uses, was simply wrong - and the failure was a silent one."""
    office = bare_office(tmp_path / "office.git", "trunk")
    config = tmp_path / "home" / ".config" / "hq" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('repo = "acme/office"\n'
                      f'clone_url_template = "{office}"\n')
    cfg = load_config()
    assert claims.default_branch(cfg) == "trunk"
    cache = claims.ensure_cache(cfg)
    head = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cache).stdout.strip()
    assert head == "trunk"


def test_an_unclonable_office_is_a_message_not_a_traceback(monkeypatch, tmp_path):
    config = tmp_path / "home" / ".config" / "hq" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('repo = "acme/office"\n'
                      f'clone_url_template = "{tmp_path / "nowhere.git"}"\n')
    cfg = load_config()
    with pytest.raises(RuntimeError) as stop:
        claims.ensure_cache(cfg)
    assert "cannot clone acme/office" in str(stop.value)
    # The push gate turns that into a fail-open warning rather than dying.
    assert claims.fetch_claims(strict=False, cfg=cfg) is False


WRAPPER = Path(__file__).resolve().parent.parent / "bin" / "hq"


def run_wrapper(monkeypatch, version, argv):
    """Execute `bin/hq` as if this interpreter were `version`.

    The alternative is a subprocess under a real old python, and CI has exactly
    the two supported ones installed, so the case this guards would never be
    exercised where it matters. The guard runs before any import of the package,
    which is the whole point of it, so faking the version is enough to reach it.
    """
    import importlib.machinery
    import importlib.util

    monkeypatch.setattr(sys, "version_info", version)
    monkeypatch.setattr(sys, "argv", argv)
    # An explicit loader, because the file is called `hq` and has no extension
    # python recognises - which is also why it is worth testing this way round.
    loader = importlib.machinery.SourceFileLoader("hq_wrapper", str(WRAPPER))
    spec = importlib.util.spec_from_loader("hq_wrapper", loader)
    loader.exec_module(importlib.util.module_from_spec(spec))


def test_an_old_python_is_one_line_not_a_tomllib_traceback(monkeypatch):
    """`python3 bin/hq` is the install-free path the README documents, and the
    interpreter it lands on is whatever `python3` happens to be. `requires-python`
    guards an install and nothing guards this, so below 3.11 the run died inside
    `import tomllib` with a traceback that never named the requirement."""
    with pytest.raises(SystemExit) as stop:
        run_wrapper(monkeypatch, (3, 10, 20, "final", 0), ["hq", "whoami"])

    message = str(stop.value)
    assert "python 3.11 or newer" in message
    assert "3.10.20" in message          # and which python it actually found
    assert "\n" not in message           # one line, never a stack trace


def test_an_old_python_does_not_block_every_push(monkeypatch, capsys):
    """The same traceback, reached through the pre-push hook, froze the machine.

    The hook reads any non-zero exit from `check-push` as a blocked push. An hq
    that cannot start knows nothing about any claim, and not knowing is never
    evidence of one, so this fails open with a warning like every other way the
    gate can be unable to answer."""
    with pytest.raises(SystemExit) as stop:
        run_wrapper(monkeypatch, (3, 10, 20, "final", 0),
                    ["hq", "check-push", "git@github.com:acme/thing.git", "br"])

    assert stop.value.code == 0                       # the push is not blocked
    err = capsys.readouterr().err
    assert "WARNING" in err and "fail-open" in err
    assert "python 3.11 or newer" in err


def test_a_supported_python_runs_the_wrapper(monkeypatch):
    """The guard must not stand in the way of the versions hq supports."""
    run_wrapper(monkeypatch, sys.version_info, ["hq", "--help"])
