"""Every test runs in a sandbox: its own HOME, its own config, no real office.

hq resolves who you are and where the head office is from the environment, the
filesystem and the surrounding git repo. A test that forgets one of those three
reads the developer's real identity and, worse, could talk to a real office. The
autouse fixture below cuts all three, so a test has to opt IN to any of them.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Everything hq reads from the environment. Cleared before each test.
HQ_VARIABLES = (
    "HQ_AGENT", "HQ_REPO", "HQ_OWNER", "HQ_BOT_NAME", "HQ_BOT_EMAIL", "HQ_HOME",
    "HQ_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "TERM_SESSION_ID", "TMUX_PANE",
)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """A fresh HOME, a fresh config dir, a fresh state dir, and no git repo.

    The working directory matters: `git config hq.agent` is one of hq's identity
    sources, so a test running inside this checkout would inherit whatever name
    the developer's clone carries.
    """
    for variable in HQ_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("HQ_HOME", str(tmp_path / "state"))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return tmp_path


@pytest.fixture
def as_session(monkeypatch):
    """Become a given session: the key hq uses to tell two agents apart."""
    def become(key):
        for variable in ("HQ_SESSION_ID", "CLAUDE_CODE_SESSION_ID",
                         "TERM_SESSION_ID", "TMUX_PANE"):
            monkeypatch.delenv(variable, raising=False)
        if key:
            monkeypatch.setenv("HQ_SESSION_ID", key)
    return become


@pytest.fixture
def register():
    """What `hq hello` writes locally, without the GitHub round-trip."""
    from hq.config import load_config

    def write(name, key):
        cfg = load_config()
        cfg.state.mkdir(parents=True, exist_ok=True)
        if key:
            cfg.session_dir.mkdir(parents=True, exist_ok=True)
            (cfg.session_dir / key).write_text(name + "\n")
        cfg.identity_file.write_text(name + "\n")
        cfg.identity_owner_file.write_text((key or "") + "\n")
    return write


@pytest.fixture
def git_checkout(tmp_path, monkeypatch):
    """A throwaway repo whose clone-wide `hq.agent` names somebody else."""
    import subprocess

    def make(agent="neighbour"):
        path = tmp_path / f"checkout-{agent}"
        subprocess.run(["git", "init", "--quiet", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "config", "hq.agent", agent], check=True)
        monkeypatch.chdir(path)
        return path
    return make
