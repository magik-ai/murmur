"""Who this session is, and whether that name is its own to act under."""

import os
import sys

from .config import load_config
from .util import MissingTool, run, slug


# The session key contract, in priority order.
#
# HQ_SESSION_ID is the one a spawner is asked to set: it is hq's own variable, so
# hq can promise what it means. The other three are best-effort fallbacks and each
# is somebody else's variable. CLAUDE_CODE_SESSION_ID in particular is not a
# documented interface of that runtime: it works today, it may be renamed tomorrow
# without warning, and when it disappears an agent silently drops to a terminal id
# or to no key at all. TERM_SESSION_ID and TMUX_PANE identify a terminal, not a
# session, so two agents in one pane look like one agent.
#
# The order stays as it is, because changing it would rename every live session on
# a machine mid-flight. What changes is that hq now says which one answered:
# `hq whoami` prints the variable, so a spawner that forgot HQ_SESSION_ID can see
# the fallback it is leaning on before the fallback goes away.
SESSION_VARIABLES = (
    "HQ_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "TERM_SESSION_ID",
    "TMUX_PANE",
)


def session_key_source():
    """(key, variable) for this session, or (None, None).

    A key that is stable within one agent session and differs between two
    sessions on the same machine. A process with none of the variables set gets
    no key, and that absence is itself the answer: such a caller cannot prove
    which session it is, so it never inherits a shared file another session
    wrote."""
    for variable in SESSION_VARIABLES:
        value = os.environ.get(variable)
        if value:
            return slug(value), variable
    return None, None


def session_key():
    return session_key_source()[0]


def shared_identity_owner(cfg=None):
    """The session that last ran `hq hello` on this machine, if it recorded one."""
    cfg = cfg or load_config()
    if not cfg.identity_owner_file.exists():
        return None
    return cfg.identity_owner_file.read_text().strip() or None


def identity():
    """Resolution order mirrors the pre-push hook: HQ_AGENT env (an explicit
    override, and the only signal that survives anything), then a truly
    worktree-scoped `git config --worktree hq.agent`, then THIS session's own
    file, then the clone-wide `git config hq.agent`, and only then the
    machine-wide file.

    The machine-wide file is the one that used to mis-attribute work: it is
    last-writer-wins, so a second `hq hello` on one machine silently renamed
    every other live session. It is now used only when it is not demonstrably
    somebody else's - when no session claimed it, or when this very session did.
    Anything else resolves to no identity, which fails loudly rather than
    signing another agent's name."""
    return identity_source()[0]


# Where a name came from. The first three belong to THIS session and are the only
# sources allowed to sign work; the last two are shared with every other session on
# the machine and are read-only hints.
SESSION_SCOPED_SOURCES = ("HQ_AGENT", "worktree config", "session file")


def identity_source(cfg=None):
    """The resolved name and the source it came from, or (None, None).

    `cfg` is for the one caller that must survive a config file hq cannot read.
    Loading it here would exit the process, and `hq bye` has local files to
    remove first - files whose location depends on HQ_HOME and the default, not
    on anything inside the broken file.

    Sources, in order: the HQ_AGENT environment variable, a truly worktree-scoped
    `git config --worktree hq.agent`, this session's own file, the clone-wide
    `git config hq.agent`, and last the machine-wide file.

    The last two are shared state. A clone-wide config is one value for every
    worktree of the clone, and the machine-wide file is last-writer-wins, so both
    can hand this session a name that belongs to a different agent. They still
    answer reads, because a listing under a stale name is harmless, but
    `require_identity` refuses to ACT on them."""
    name = os.environ.get("HQ_AGENT")
    if name:
        return name, "HQ_AGENT"
    name = worktree_agent()
    if name:
        return name, "worktree config"
    cfg = cfg or load_config()
    key = session_key()
    if key:
        mine = cfg.session_dir / key
        if mine.exists():
            name = mine.read_text().strip()
            if name:
                return name, "session file"
    name = repo_agent()
    if name:
        return name, "clone config"
    if cfg.identity_file.exists():
        owner = shared_identity_owner(cfg)
        if owner is None or owner == key:
            name = cfg.identity_file.read_text().strip()
            if name:
                return name, "machine file"
    return None, None


def git_config(*args):
    """`git config ...`, where every way of not getting an answer is "".

    No git on the machine is one of those ways. Resolving a name must not
    depend on git: a name can come from four places that are not git, and hq
    asks git first, so a missing git used to end every one of those commands in
    a FileNotFoundError traceback before the other sources were even tried.
    `hq whoami` could not answer a question about a file on disk, and `hq bye`
    died BEFORE the local cleanup that finding 7 put first - so a machine
    without git kept its identity for ever, exactly the failure that fix
    removed for an unconfigured machine.

    Not being able to ask git is not evidence about who this session is, in the
    same way that not reaching the office is not evidence about a claim.
    """
    try:
        got = run(["git", "config", *args], check=False)
    except MissingTool:
        return ""
    return (got.stdout or "").strip() if got.returncode == 0 else ""


def worktree_agent():
    """`hq.agent` scoped to THIS worktree alone.

    Only real when `extensions.worktreeConfig` is on: without it git documents
    `--worktree` as a synonym for `--local`, so it would hand back the very
    clone-wide value this exists to distinguish from."""
    if git_config("--bool", "extensions.worktreeConfig") != "true":
        return ""
    return git_config("--worktree", "hq.agent")


def repo_agent():
    """`hq.agent` from the repository config.

    Plain `git config hq.agent` writes to `.git/config`, which every linked
    worktree of the clone shares - so this is clone-wide state, not the
    per-worktree signal it reads like. It stays as a fallback for setups that
    rely on it, but it no longer outranks a session that said hello."""
    return git_config("hq.agent")


def require_identity(strict=True):
    """The name this session may act under.

    `strict` is the default because every caller that reaches this function WRITES
    something under a name: it closes a session issue, claims a branch, sends mail,
    or moves a mailbox cursor. A name inherited from the clone-wide config or the
    machine-wide file is shared with every other session here, so acting on it signs
    or consumes another agent's work. That is not hypothetical: on 2026-09-16 a
    session whose own file had just been removed by `hq bye` fell through to the
    shared state and signed a second `hq bye` as a different, live agent, taking that
    agent off the board. Reads that only display something may pass strict=False."""
    name, source = identity_source()
    if name and (not strict or source in SESSION_SCOPED_SOURCES):
        return name
    if name and strict:
        sys.exit(
            f"hq: '{name}' comes from the {source}, which every session on this "
            "machine shares, so hq will not act under it. Run `hq hello <your-name>` "
            "in THIS session, or prefix the command with HQ_AGENT=<your-name>. "
            "`hq whoami` shows what hq currently thinks you are."
        )
    cfg = load_config()
    owner = shared_identity_owner(cfg)
    if owner is not None and owner != session_key() and cfg.identity_file.exists():
        sys.exit(
            "hq: this machine's identity file belongs to another session "
            f"(written by session {owner}), so hq will not sign your work with "
            f"'{cfg.identity_file.read_text().strip()}'. Run `hq hello <your-name>` "
            "in THIS session, or prefix the command with HQ_AGENT=<your-name>."
        )
    sys.exit("hq: no identity - run `hq hello <name>` first (or set HQ_AGENT)")


def is_sovereign(name, cfg=None):
    """The owner works hands-on with sovereign rights: claims warn them, never
    block them. An empty `owner` in the config means nobody has that power."""
    cfg = cfg or load_config()
    return bool(cfg.owner) and name == cfg.owner
