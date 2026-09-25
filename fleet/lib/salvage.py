"""Rescue committed-but-unpushed work before the janitor removes a terminal worktree.

The sweep's dirt() check only sees UNCOMMITTED changes, so a worktree holding local commits that
were never pushed (branch not merged, not in origin) reads as clean and gets removed — the commits
lived only there, so they are lost. This pushes those commits to a hidden ref namespace
(refs/fleet-salvage/<slug>) that does not appear in the branch list, then a cleanup pass drops any
salvage ref whose tip has since landed in origin/<base>, so the namespace never becomes a
graveyard.
"""
import os
import subprocess

SALVAGE_NS = "refs/fleet-salvage"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)


def unpushed_shas(worktree, remote="origin"):
    """Commits on HEAD reachable from NO ref on <remote>: genuinely unpushed. Empty when all are
    pushed; None when git cannot tell (a broken worktree), which is not the same as "none"."""
    result = _git(worktree, "rev-list", "HEAD", "--not", f"--remotes={remote}")
    if result.returncode:
        return None
    return [line for line in result.stdout.split() if line]


def salvage(worktree, slug, remote="origin"):
    """Push HEAD to refs/fleet-salvage/<slug> when it carries unpushed commits.

    Returns (saved, detail). saved is True when the commits are now on <remote>, and None when
    there was nothing unpushed. It is False when there may be commits that are NOT on <remote>:
    the push failed, git could not list them, or the slug is unsafe. The caller must then keep
    the worktree and its branch, because they hold the only copy."""
    if not slug or os.path.basename(slug) != slug:
        return False, f"unsafe slug {slug!r}"
    shas = unpushed_shas(worktree, remote)
    if shas is None:
        return False, "git could not list the unpushed commits"
    if not shas:
        return None, "nothing unpushed"
    ref = f"{SALVAGE_NS}/{slug}"
    result = _git(worktree, "push", "--force", remote, f"HEAD:{ref}")
    if result.returncode:
        return False, (result.stderr or "push failed").strip()
    return True, f"{len(shas)} commit(s) -> {ref}"


def cleanup_landed(repo, base, remote="origin"):
    """Drop every salvage ref whose tip already landed in <remote>/<base> (the lane's PR merged).
    Returns the list of dropped ref names. Requires <remote>/<base> to be fetched first."""
    ls = _git(repo, "ls-remote", remote, f"{SALVAGE_NS}/*")
    if ls.returncode:
        return []
    dropped = []
    for line in ls.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        landed = _git(repo, "merge-base", "--is-ancestor", sha, f"{remote}/{base}")
        if landed.returncode == 0:
            if _git(repo, "push", remote, "--delete", ref).returncode == 0:
                dropped.append(ref)
    return dropped
