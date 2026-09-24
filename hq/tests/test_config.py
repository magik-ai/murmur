"""Configuration precedence: environment over file over nothing at all.

The file is the durable setup a person writes once with `hq init`. The
environment is how a spawner configures one lane, or one command, inline. When
there is neither, hq must say so in one line instead of guessing a repo.
"""

from pathlib import Path

import pytest

from hq import config as conf


def write_config(text):
    path = conf.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_no_config_at_all_is_an_error_naming_hq_init():
    cfg = conf.load_config()
    assert cfg.repo == ""
    with pytest.raises(SystemExit) as stop:
        conf.require_repo(cfg)
    message = str(stop.value)
    assert "hq init" in message
    assert str(conf.config_path()) in message
    # One line: an agent reads the first line of a failure and nothing else.
    assert message.count("\n") == 0


def test_the_file_is_read():
    write_config(
        'repo = "acme/office"\n'
        'owner = "alice"\n'
        'bot_name = "office-bot"\n'
        'bot_email = "bot@acme.example"\n'
        'clone_url_template = "git@github-acme:{repo}.git"\n'
    )
    cfg = conf.load_config()
    assert cfg.repo == "acme/office"
    assert cfg.owner == "alice"
    assert cfg.bot_name == "office-bot"
    assert cfg.bot_email == "bot@acme.example"
    assert cfg.clone_url() == "git@github-acme:acme/office.git"
    assert conf.require_repo(cfg) == "acme/office"


def test_the_environment_beats_the_file(monkeypatch):
    write_config('repo = "acme/office"\nowner = "alice"\nbot_email = "bot@acme.example"\n')
    monkeypatch.setenv("HQ_REPO", "other/office")
    monkeypatch.setenv("HQ_OWNER", "bob")
    monkeypatch.setenv("HQ_BOT_EMAIL", "lane@acme.example")
    cfg = conf.load_config()
    assert cfg.repo == "other/office"
    assert cfg.owner == "bob"
    assert cfg.bot_email == "lane@acme.example"


def test_an_empty_env_owner_means_nobody_is_sovereign(monkeypatch):
    """Explicitly empty is a value, not an oversight: a lane can strip the
    owner's override rights for the duration of one command."""
    write_config('repo = "acme/office"\nowner = "alice"\n')
    monkeypatch.setenv("HQ_OWNER", "")
    assert conf.load_config().owner == ""


def test_defaults_fill_what_neither_source_sets(monkeypatch):
    monkeypatch.setenv("HQ_REPO", "acme/office")
    cfg = conf.load_config()
    assert cfg.owner == ""  # nobody is sovereign until somebody is named
    assert cfg.bot_name == conf.DEFAULTS["bot_name"]
    assert cfg.bot_email == conf.DEFAULTS["bot_email"]
    assert cfg.clone_url() == "https://github.com/acme/office.git"


def test_the_default_author_email_belongs_to_nobody():
    """Claims commits are pushed to GitHub, and GitHub links a commit to the
    account that owns its author address. The default must be an address no
    account can own: `.invalid` is a reserved top-level domain, and GitHub's
    no-reply domain names somebody's login."""
    email = conf.DEFAULTS["bot_email"]
    assert email.endswith(".invalid")
    assert "users.noreply.github.com" not in email


@pytest.mark.parametrize("where", ["file", "environment"])
def test_the_foreign_address_earlier_configs_carry_reads_as_the_default(
        monkeypatch, where):
    """Earlier versions of `hq init` wrote GitHub's no-reply address for the
    login `hq`, which belongs to an unrelated account. Those files keep working,
    and their claims commits stop carrying that address."""
    if where == "file":
        write_config('repo = "acme/office"\n'
                     'bot_email = "hq@users.noreply.github.com"\n')
    else:
        monkeypatch.setenv("HQ_REPO", "acme/office")
        monkeypatch.setenv("HQ_BOT_EMAIL", "hq@users.noreply.github.com")
    cfg = conf.load_config()
    assert cfg.repo == "acme/office"
    assert cfg.bot_email == conf.DEFAULTS["bot_email"]


def test_home_moves_every_state_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HQ_HOME", str(tmp_path / "elsewhere"))
    cfg = conf.load_config()
    assert cfg.state == tmp_path / "elsewhere"
    assert cfg.cache == tmp_path / "elsewhere" / "repo"
    assert cfg.identity_file == tmp_path / "elsewhere" / "identity"
    assert cfg.session_dir == tmp_path / "elsewhere" / "identity.d"
    assert cfg.lastread_file == tmp_path / "elsewhere" / "lastread"


def test_the_file_is_re_read_every_time(monkeypatch):
    """No caching: `HQ_REPO=... hq who` has to work, and a lane may
    be reconfigured between two calls in one shell."""
    write_config('repo = "acme/office"\n')
    assert conf.load_config().repo == "acme/office"
    write_config('repo = "acme/second-office"\n')
    assert conf.load_config().repo == "acme/second-office"


def test_a_hq_table_is_accepted_too():
    write_config('[hq]\nrepo = "acme/office"\nowner = "alice"\n')
    cfg = conf.load_config()
    assert (cfg.repo, cfg.owner) == ("acme/office", "alice")


def test_a_broken_file_says_which_file(monkeypatch):
    write_config("repo = \n")
    with pytest.raises(SystemExit) as stop:
        conf.load_config()
    assert str(conf.config_path()) in str(stop.value)


SAMPLE = (
    "# a comment\n"
    "\n"
    'repo = "acme/office"   # trailing comment\n'
    'owner = "alice"\n'
    "[hq]\n"
    'bot_name = "office-bot"\n'
)

# Malformed input that a more forgiving parser might accept and tomllib
# rejects. Two parsers that disagree would make the same config file fail open
# on one python and block every push on another.
MALFORMED = (
    'repo = "acme/office',            # unterminated string
    "repo = acme/office\n",           # bare value
    'repo = "a" "b"\n',                # trailing junk after the string
    "[hq\nrepo = \"acme/office\"\n",   # unterminated table header
    'repo = "a"\nrepo = "b"\n',        # duplicate key
)


def test_there_is_exactly_one_config_parser():
    """No fallback parser: two parsers that disagree about a broken file
    would give the push gate two verdicts."""
    assert not hasattr(conf, "parse_simple_toml")


@pytest.mark.parametrize("text", MALFORMED)
def test_malformed_input_is_rejected_the_same_way_everywhere(text):
    """One parser, one verdict, on every supported python."""
    write_config(text)
    with pytest.raises(conf.ConfigError):
        conf.read_config_file(conf.config_path())


def test_the_sample_file_reads_as_tomllib_reads_it():
    import tomllib

    write_config(SAMPLE)
    assert conf.read_config_file(conf.config_path()) == {
        "repo": "acme/office", "owner": "alice", "bot_name": "office-bot"}
    assert tomllib.loads(SAMPLE)["repo"] == "acme/office"


def test_hq_init_writes_a_file_its_own_parser_can_read(monkeypatch):
    import argparse

    from hq.cli import cmd_init

    cmd_init(argparse.Namespace(repo="acme/office", owner="alice", bot_name=None,
                                bot_email=None, home=None, force=False))
    cfg = conf.load_config()
    assert (cfg.repo, cfg.owner) == ("acme/office", "alice")
    assert conf.read_config_file(conf.config_path())["repo"] == "acme/office"

    # A second init does not quietly replace a working setup.
    with pytest.raises(SystemExit) as stop:
        cmd_init(argparse.Namespace(repo="other/office", owner=None, bot_name=None,
                                    bot_email=None, home=None, force=False))
    assert "--force" in str(stop.value)


def init(**overrides):
    import argparse

    from hq.cli import cmd_init

    fields = dict(repo="acme/office", owner=None, bot_name=None, bot_email=None,
                  home=None, force=False)
    fields.update(overrides)
    cmd_init(argparse.Namespace(**fields))


def test_hq_init_writes_the_default_author_email():
    init()
    written = conf.read_config_file(conf.config_path())
    assert written["bot_email"] == conf.DEFAULTS["bot_email"]


def test_a_quote_in_a_value_is_escaped_not_pasted():
    """Pasted unescaped, `--owner 'al"ice'` would write `owner = "al"ice"`: a
    file hq cannot parse, from a command that exited 0. The breakage would only
    show at the next command, on a machine nobody is watching any more."""
    init(owner='al"ice')
    assert conf.load_config().owner == 'al"ice'


def test_a_backslash_in_a_value_is_escaped_not_pasted(monkeypatch):
    """A Windows-style path is the everyday way to get a backslash in. TOML
    reads `\\a` as an escape, so an unescaped one is either a parse error or,
    worse, a silently different path."""
    monkeypatch.delenv("HQ_HOME", raising=False)  # the file is the subject here
    init(home=r"C:\agents\hq-home")
    cfg = conf.load_config()
    assert str(cfg.state) == r"C:\agents\hq-home"


def test_every_value_survives_the_round_trip_unchanged():
    init(owner='al"ice', bot_name=r"bot\one", bot_email='q"uote@acme.example',
         home=r"C:\state\hq")
    cfg = conf.load_config()
    assert cfg.owner == 'al"ice'
    assert cfg.bot_name == r"bot\one"
    assert cfg.bot_email == 'q"uote@acme.example'


def test_init_refuses_to_leave_a_config_it_cannot_read_back(monkeypatch, capsys):
    """The escaping is the fix; this is the guarantee. If hq ever writes a file
    it cannot parse again, init says so and removes it, instead of exiting 0 on
    a machine that is now broken for every other command."""
    from hq import cli

    monkeypatch.setattr(cli, "toml_string", lambda value: f'"{value}"')
    with pytest.raises(SystemExit) as stop:
        init(owner='al"ice')
    assert "nothing was configured" in str(stop.value)
    assert not conf.config_path().exists()


def test_bytes_that_are_not_utf8_are_a_config_error_not_a_decode_crash():
    """`read_config_file` promises one exception type for "there is a file and
    hq cannot use it". A non-UTF-8 file must not break that promise with a
    `UnicodeDecodeError`, which is a `ValueError`: every caller catching
    `ConfigError` would miss it, including the push gate.
    """
    path = conf.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'owner = "Jos\xe9"\n')
    with pytest.raises(conf.ConfigError):
        conf.read_config_file(path)


def test_a_non_utf8_file_still_stops_every_other_command_with_one_line():
    """Fail-open belongs to the push gate alone. Everything else must still
    get the one-line exit, not a traceback."""
    path = conf.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'owner = "Jos\xe9"\n')
    with pytest.raises(SystemExit) as stop:
        conf.load_config()
    assert str(conf.config_path()) in str(stop.value)


def test_init_reports_an_unwritable_config_dir_as_one_line(monkeypatch):
    """A config directory hq may not write is an ordinary first-run accident on
    a locked-down machine. A PermissionError traceback would tell a person
    setting up a new machine nothing about what to do next. Every other failure
    in init is one line; so is this one."""
    import os

    if os.geteuid() == 0:
        pytest.skip("root writes into a read-only directory, so there is nothing to test")
    locked = Path(os.environ["HOME"]) / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(locked / "config"))
    try:
        with pytest.raises(SystemExit) as stop:
            init()
    finally:
        locked.chmod(0o700)
    message = str(stop.value)
    assert "\n" not in message
    assert "nothing was configured" in message
    assert str(conf.config_path()) in message


def test_a_failed_write_leaves_no_half_written_config_behind(monkeypatch):
    """A config file hq wrote but cannot read is worse than no config file:
    `hq init` itself then refuses to overwrite it, so the machine is stuck on a
    file the failure created. A write that dies partway cleans up after
    itself."""
    import pathlib

    real_write = pathlib.Path.write_text

    def half_a_file(self, data, *args, **kwargs):
        real_write(self, data[:20], *args, **kwargs)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pathlib.Path, "write_text", half_a_file)
    with pytest.raises(SystemExit) as stop:
        init()
    message = str(stop.value)
    assert "\n" not in message
    assert "nothing was configured" in message
    assert not conf.config_path().exists()


def test_init_writes_utf8_whatever_the_machine_locale_is(tmp_path):
    """The config file is UTF-8 because `read_config_file` decodes UTF-8.

    `write_text` without an encoding uses the machine's locale, which under
    `LC_ALL=C` is ASCII: `hq init --bot-name José` - an ordinary git author
    name - would die with a UnicodeEncodeError traceback and leave a zero-byte
    config.toml behind, which the next `hq init` refuses to overwrite. On a
    latin-1 locale it would be quieter and no better: the file written would not
    be the file hq reads.

    Run as a subprocess because a locale is a property of the process, not
    something a test can monkeypatch.
    """
    import json
    import os
    import subprocess
    import sys

    src = str(Path(conf.__file__).resolve().parent.parent)
    home = tmp_path / "ascii-home"
    home.mkdir()
    env = dict(os.environ)
    env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                "PYTHONPATH": src, "LC_ALL": "C", "LANG": "C",
                "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"})
    for variable in ("HQ_HOME", "HQ_REPO", "HQ_OWNER", "HQ_AGENT"):
        env.pop(variable, None)

    result = subprocess.run(
        [sys.executable, "-m", "hq.cli", "init", "--repo", "acme/office",
         "--owner", "José", "--bot-name", "Ramírez"],
        env=env, capture_output=True, text=True, errors="replace", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr

    # The file hq wrote is the file hq reads, accents and all.
    read_back = subprocess.run(
        [sys.executable, "-c",
         "import json, sys; sys.path.insert(0, sys.argv[1]);"
         "from hq.config import load_config;"
         "cfg = load_config(); print(json.dumps([cfg.owner, cfg.bot_name]))",
         src],
        env=env, capture_output=True, text=True, errors="replace", timeout=60)
    assert read_back.returncode == 0, read_back.stderr
    assert json.loads(read_back.stdout) == ["José", "Ramírez"]
