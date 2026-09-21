# fleet sweep — the farm janitor and how not to lose work to it

`fleet sweep` runs automatically every 10 minutes (`fleet-sweep.timer`) and keeps
the farm free of dead worktrees and stale dashboard cards. It is deliberately
aggressive about the obviously dead, so every agent must know its contract.

## What it removes

**Pass A — git worktrees.** A worktree is removed when its branch's PR is
MERGED (GitHub is the authority; squash-merge makes ancestry checks useless).
Kept: worktrees of live agents, branches with an OPEN PR, branches whose PR was
CLOSED unmerged (owner's call), and merged-but-dirty trees (tracked changes)
unless `--force`.

**Pass B — dashboard cards (`~/.fleet/state/*.json`).** A card is reaped when
its PR is merged, its status is `killed`, or it is terminal
(`done_no_pr` / `delivered` / `failed`) and older than the grace period.

## Parameters

| Parameter | Value | Meaning |
|---|---|---|
| `GRACE` | 900 s (15 min) | A just-finished card stays visible this long |
| `--force` | off | The only way a worktree with tracked uncommitted changes is removed, and its dirt is snapshotted first. There is no age at which the janitor does this on its own |
| autosweep | every 10 min | `fleet autosweep status` / `off` / `on [minutes]` |

## What counts as "dirty"

Only **tracked** uncommitted modifications protect a worktree, and they protect
it for as long as they exist: nothing buries them on a timer, only
`fleet sweep --force` does, after an autopsy snapshot. Untracked scratch files
protect NOTHING, every agent leaves untracked noise, so it cannot be a keep
signal. The harness-owned `.fleet-hooks/` directory never counts.

## Nothing is deleted outright

- Reaped cards move to `~/.fleet/state-archive/<YYYY-MM>/`.
- When a dirty-but-long-dead tree is buried, its dirt is snapshotted first to
  `<slug>.dirt.txt` in the archive (git status + first 200 KB of diff).
- **Committed-but-unpushed commits are rescued before burial.** A terminal
  worktree carrying local commits that were never pushed (branch not merged, not
  in origin) reads as clean to the dirt check, so it used to be removed and the
  commits lost. The sweep now pushes such commits to a hidden ref namespace,
  `refs/fleet-salvage/<slug>`, before it removes the worktree. The ref does not
  show up in the branch list; a later pass drops it automatically once the same
  work lands in `origin/<base>` (the lane's PR merged), so the namespace never
  becomes a graveyard. Recover with `git fetch origin '+refs/fleet-salvage/*:refs/fleet-salvage/*'`.
- Removed worktree contents are otherwise GONE. Uncommitted changes get only the
  `.dirt.txt` autopsy; commit and push to be truly safe.

## When a state record is unreadable

The sweep refuses to run for the whole project and prints

    ABORT   1 unreadable state record(s): <name>.json
            refusing to remove anything - liveness cannot be established.

That is deliberate. A torn record may belong to a RUNNING lane, and the janitor
would have no way to tell — so it deletes nothing rather than risk deleting a
live worktree. Expect it while a lane is mid-write; the next pass is normally
clean.

A record that stays unparseable past the grace window is not in flight, it is
debris. That pass still aborts, and the file is retired to
`~/.fleet/state-archive/<YYYY-MM>/<name>.json.corrupt` — archived, never deleted,
because it may be the only trace of what that lane was doing. The pass after
that sees a clean state directory and the janitor resumes on its own.

So: **one ABORT is normal, a repeating ABORT clears itself within one grace
window.** If it survives longer than that, the state directory is not writable —
that is the thing to investigate, not the record.

## How to keep your work safe (agents, read this)

1. **Running lanes are never touched.** The janitor only looks at terminal
   states.
2. **Commit and push; open a PR.** An OPEN PR protects both your worktree and
   your card indefinitely. Tracked-but-uncommitted changes are kept until
   somebody sweeps with `--force`, which is not a plan: nobody reviews a dirty
   worktree. Untracked files buy you nothing. Committed-but-unpushed commits are now caught by the
   salvage pass (`refs/fleet-salvage/<slug>`), but that is a safety net, not a
   plan — push, so your work is on a real branch with a real PR.
3. **Finish loudly.** Once your status is terminal, your card disappears after
   ~15 minutes — put durable output in the PR, the issue, or your report, never
   only in the worktree.
4. **Preview before panicking:** `fleet sweep --dry-run` shows exactly what the
   next pass would take.
5. **Recovery:** check `~/.fleet/state-archive/` for the card and the `.dirt.txt`
   autopsy; if the work was pushed, the branch is still on origin; if it was
   committed but never pushed, look for `refs/fleet-salvage/<slug>` on origin.
