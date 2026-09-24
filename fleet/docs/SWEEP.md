# fleet sweep

`fleet sweep` cleans up after finished lanes. A lane is one agent doing one
task on its own branch, in its own git worktree under `~/.fleet/worktrees/`.
The sweep removes worktrees that are no longer needed, and it archives the
dashboard cards of lanes that are done. A card is the lane's entry on the
dashboard; it comes from the lane's state record, `~/.fleet/state/<slug>.json`.
`<slug>` is the lane's unique id, printed by `fleet spawn`.

The sweep removes what is clearly finished, on a timer, without asking. Read
this page to know what it keeps, what it removes and what it saves first.

## When it runs

`./install.sh` turns on the timer with `fleet autosweep on` (skip this with
`./install.sh --no-autosweep`). The timer is the systemd user unit
`fleet-sweep.timer`. It runs `fleet sweep` every 10 minutes, and it never
passes `--force`.

```bash
fleet sweep --dry-run          # print what the next pass would do; remove nothing
fleet sweep                    # one pass over every registered project
fleet sweep --project <name>   # one project only
fleet sweep --force            # also remove worktrees with uncommitted changes
fleet autosweep status         # the timer: its next run and the last result
fleet autosweep on 15          # run every 15 minutes instead of 10
fleet autosweep off            # stop the timer
```

## What it removes

The sweep goes through the registered projects one at a time. It never touches
a live lane. A lane is live when its record says `starting` or `running`, and
either the record changed in the last 15 minutes or the lane's systemd unit is
still active. A record that says `running` but has not changed for 15 minutes,
with no unit behind it, belongs to a lane that died.

### Part A: worktrees

The sweep looks at each git worktree of the project that lives under
`~/.fleet/worktrees/`. It skips any other worktree, and any worktree with a
detached HEAD. For each branch it asks GitHub for the pull request, because a
squash merge leaves no trace in git history.

| The branch | What the sweep does |
|---|---|
| a live lane uses it | keeps it |
| GitHub did not answer | keeps it |
| its pull request is open | keeps it |
| its pull request was closed without a merge | keeps it (but see part B) |
| its pull request was merged | removes the worktree and the local branch |
| no pull request, but already in `origin/<base>` | removes the worktree and the local branch |
| no pull request, not in `origin/<base>` | keeps it |

`<base>` is the project's base branch, `main` unless `projects.toml` says
otherwise. Two more rules apply before a worktree is removed:

- **Uncommitted changes keep it.** This counts tracked and untracked files
  alike. Files your `.gitignore` covers do not count. Only `fleet sweep
  --force` removes such a worktree, and it saves the changes first.
- **Commits that were never pushed are rescued first.** The sweep pushes them
  to `refs/fleet-salvage/<slug>` on `origin`, then removes the worktree.

### Part B: cards

The sweep then looks at the state records of the project's lanes that are not
live. It keeps a card when the lane's pull request is open, or when GitHub did
not answer. It archives the card in any of these cases:

- the lane's pull request was merged;
- the lane was killed with `fleet kill`;
- the record has not changed for 15 minutes (`GRACE`).

If the lane's worktree still exists, part B removes it before it archives the
card, with the same two rules: uncommitted changes keep both the worktree and
the card (unless `--force`), and unpushed commits are rescued first. Part B
does not delete the branch.

So the worktree of a lane whose pull request was closed, or that never opened
one, does not stay for ever. Part A keeps it, and part B removes it 15 minutes
after the lane's record last changed. The branch stays: in the project's
checkout, and on GitHub if it was pushed.

## Parameters

| Parameter | Value | Meaning |
|---|---|---|
| `GRACE` | 900 s (15 min) | How long a finished card stays on the board. Also how long a `running` record may go without a change before a lane with no unit counts as dead |
| `--force` | off | The only way to remove a worktree with uncommitted changes. The changes are saved first. The timer never passes it |
| autosweep | every 10 min | `fleet autosweep on [minutes]`, `off`, `status` |

## What is saved before anything is removed

- **Cards** move to `~/.fleet/state-archive/<YYYY-MM>/`.
- **Uncommitted changes**, when `--force` removes their worktree, are saved in
  the same folder first. `<slug>.dirt.txt` holds `git status` and the unstaged
  and staged diffs, cut at 200,000 bytes. `<slug>.untracked.tar` holds the
  untracked files.
- **Commits that were never pushed** go to `refs/fleet-salvage/<slug>` on
  `origin`. This ref does not show in the branch list. A later pass deletes it
  once its last commit is part of `origin/<base>`. After a squash merge that
  never happens, so delete the ref yourself when you no longer need it:
  `git push origin --delete refs/fleet-salvage/<slug>`. If the push to the
  salvage ref is refused, the sweep removes the worktree anyway, so this is a
  safety net and not a place to keep work.
- **Everything else** in a removed worktree is gone: ignored files, build
  output, installed dependencies.

## When a state record cannot be read

If a state record in `~/.fleet/state/` is not valid JSON, the sweep cannot
tell whether that lane is live. It then removes no worktree and archives no
card, in any project, and prints:

```text
  ABORT   1 unreadable state record(s): <name>.json
          refusing to remove anything - liveness cannot be established.
```

A record that is being written at that moment can look like this. So one
ABORT is normal, and the next pass usually reads the record without trouble.

A record that stays unreadable for 15 minutes (going by its file time) is not
being written. The sweep moves it to
`~/.fleet/state-archive/<YYYY-MM>/<name>.json.corrupt` and carries on with the
same pass. It keeps the file because it may be the only trace of what that
lane did.

If that move fails, the sweep aborts again and prints the reason:

```text
  quarantine  FAILED for <name>.json: <reason>
```

So an ABORT that repeats for more than 15 minutes means the record cannot be
moved. When the timer ran the sweep, its output is in
`journalctl --user -u fleet-sweep.service`.

## How to keep your work safe (agents, read this)

1. **Live lanes are never touched.** The sweep only acts on lanes that
   finished or died.
2. **Commit, push and open a pull request.** An open pull request keeps both
   your worktree and your card, however long it stays open.
3. **Do not leave work uncommitted.** Uncommitted changes keep the worktree
   only until someone runs `fleet sweep --force`, and nobody reviews a
   worktree. The salvage ref catches commits you did not push, but it is a
   safety net, not a plan: push, so your work is on a real branch with a real
   pull request.
4. **Put results where people read them.** Your card leaves the board about
   15 minutes after you finish, or at the next pass if your pull request was
   merged or your lane was killed. Put durable output in the pull request, the
   issue or your report, never only in the worktree.
5. **Preview before you worry.** `fleet sweep --dry-run` prints what the next
   pass would take.
6. **To recover work**, look in `~/.fleet/state-archive/` for the card and for
   the `.dirt.txt` and `.untracked.tar` files. Pushed work is still on its
   branch on GitHub. Commits that were never pushed are in the salvage ref:

   ```bash
   git fetch origin '+refs/fleet-salvage/*:refs/fleet-salvage/*'
   git switch -c rescue refs/fleet-salvage/<slug>
   ```
