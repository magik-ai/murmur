"""The pre-push guard: the claim, enforced where a push actually happens."""

import sys
from pathlib import Path

from .util import MissingTool, run


# The line that says hq wrote a hook file. It has been in every version of the
# guard, so an older hq's hook is recognised as hq's own and upgraded in place.
MARKER = "agent-hq pre-push guard"

HOOK = """#!/usr/bin/env bash
# agent-hq pre-push guard: refuse pushing to a branch claimed by another agent.
# When hq cannot tell (office unreachable and no claim in the local cache, no
# config, an error), it warns and lets the push through.
# Identity: a worktree-scoped `git config --worktree hq.agent` wins (many agents
# share a farm machine), then the HQ_AGENT env, then hq's own order: this
# session's own name, the clone-wide `git config hq.agent`, and last the
# machine-wide file - which hq ignores when another session wrote it, so a
# guard can never decide "this branch is mine" under a neighbour's name.
hq_bin="$(command -v hq || echo "$HOME/.local/bin/hq")"
[ -x "$hq_bin" ] || exit 0
repo_url="$(git remote get-url origin 2>/dev/null)" || exit 0
# Only a TRULY worktree-scoped value may be forced here. Without
# extensions.worktreeConfig, `git config --worktree` reads .git/config, which
# every linked worktree of the clone shares, so forcing that value would stamp
# one name onto every agent working in this clone.
wt_agent=""
if [ "$(git config --bool extensions.worktreeConfig 2>/dev/null)" = "true" ]; then
  wt_agent="$(git config --worktree hq.agent 2>/dev/null || true)"
fi
export HQ_AGENT="${wt_agent:-${HQ_AGENT:-}}"
[ -n "$HQ_AGENT" ] || unset HQ_AGENT
while read -r _local _lsha remote _rsha; do
  case "$remote" in refs/heads/*) branch="${remote#refs/heads/}" ;; *) continue ;; esac
  # `--` because a branch name is not ours to choose: `refs/heads/-weird` is a
  # legal ref, and without the separator the CLI reads it as an option and
  # exits 2, which this loop turns into a blocked push.
  if ! "$hq_bin" check-push -- "$repo_url" "$branch"; then exit 1; fi
done
exit 0
"""


def written_by_hq(path):
    """Did hq write this hook file?

    `hq hook` never overwrites a `pre-push` it did not write. A repo's own hook
    - a linter, a secret scanner, a hook a team installs from its own tooling -
    would otherwise be lost silently, and the loss would surface later as a
    check that had quietly stopped running. hq's own guard, of any version,
    carries the marker line and is upgraded in place, so re-running `hq hook`
    is the way to update an old guard.

    A file hq cannot read is not hq's: refusing is the safe answer.
    """
    try:
        return MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def cmd_hook(args):
    """Install the guard into a worktree or clone. Every failure is one line.

    This runs while a machine is being set up, usually from a script, so each
    ordinary way it can fail gets one line naming the next step instead of a
    stack trace: a directory that does not exist, a directory that is not a git
    repository, a machine without git at all, and a hooks directory hq may not
    write.
    """
    target = Path(args.dir).resolve()
    if not target.is_dir():
        sys.exit(f"hq: {target} is not a directory - `hq hook` takes the worktree "
                 "or clone to guard, for example `hq hook .`")
    try:
        found = run(["git", "rev-parse", "--git-path", "hooks"],
                    cwd=target, check=False)
    except MissingTool as error:
        sys.exit(f"hq: {error}")
    if found.returncode != 0:
        detail = " ".join((found.stderr or "").split())[:200]
        sys.exit(f"hq: {target} is not inside a git repository ({detail}) - the guard "
                 "belongs in the repo whose pushes it gates")
    git_dir = found.stdout.strip()
    hooks = (target / git_dir).resolve() if not Path(git_dir).is_absolute() else Path(git_dir)
    hook_file = hooks / "pre-push"
    if hook_file.exists() and not written_by_hq(hook_file) and not args.force:
        sys.exit(f"hq: {hook_file} already exists and hq did not write it - "
                 "overwriting it would remove that guard without a word. Move it "
                 "aside, or call hq from it, or pass --force to replace it")
    try:
        hooks.mkdir(parents=True, exist_ok=True)
        hook_file.write_text(HOOK)
        hook_file.chmod(0o755)
    except OSError as error:
        sys.exit(f"hq: cannot write the pre-push guard {hook_file} ({error})")
    print(f"pre-push guard installed: {hook_file}")
