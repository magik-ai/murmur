# Sharp edges

Thirteen things every operator of a farm has to know. Each one is a real failure mode of this design,
not a hypothetical: the mechanism is explained, and so is the guard that already exists, because
knowing where the guard stops is the useful part.

Read this once before you need it. Several of these destroy work, and the destruction is quiet.

---

## 1. `--force` on `clean` and `sweep` destroys work, by design

**Mechanism.** `fleet clean` removes finished lanes' worktrees; `fleet sweep` does the same for
merged branches and reaps their dashboard cards. A removed worktree is gone: its uncommitted
changes, its untracked files, its stash. Without `--force` both commands refuse anything that
holds work existing nowhere else. With `--force` they do exactly what you asked.

**The guard.**

- `clean --force` is refused outright unless it is scoped with `--by <codename>`, so a forced
  cleanup cannot reach across into another orchestrator's lanes.
- A worktree with unsaved work is kept and the command points at `fleet salvage <slug>` instead.
- If you force it anyway, the first attempt still refuses: it prints what would be lost and
  requires a second run with `--yes`. Only then does it snapshot the worktree and remove it.
- `sweep` without `--force` never touches a dirty tree at all, and the timer runs it without
  `--force`.
- Every destructive path writes an autopsy (git status plus the head of the diff) into
  `~/.fleet/state-archive/` before removing anything.

**Where the guard stops.** The autopsy is a text snapshot, not your branch. `--force --yes` on a
tree with a day of uncommitted work leaves you a diff file and nothing else. Run
`fleet sweep --dry-run` and `fleet clean --dry-run` first: both print exactly what the next pass
would take.

---

## 2. Only pushed work is safe

**Mechanism.** The janitor decides from GitHub, not from your intentions. A branch whose pull
request is merged is done, and its worktree is removed. A card that is terminal and old is reaped.
Nothing on the machine is a promise.

**The guard,** in descending order of how much it protects:

| State of the work | Protection |
|---|---|
| open pull request | worktree and card kept indefinitely |
| pushed branch, no PR | the branch is on the remote, so the worktree is disposable |
| committed, never pushed | the sweep pushes the commits to `refs/fleet-salvage/<slug>` before removing the tree |
| tracked changes, uncommitted | kept, and reported, until somebody runs `fleet sweep --force` (which snapshots the dirt first) |
| untracked scratch files | none at all |

Untracked files protect nothing on purpose: every agent leaves untracked noise, so it cannot be a
keep signal.

**Where the guard stops.** The salvage ref is a safety net, not a plan. It is a hidden ref that a
later pass drops once the same work lands on the base branch, and nobody reviews a hidden ref.
Recover one with `git fetch origin '+refs/fleet-salvage/*:refs/fleet-salvage/*'`. The rule for
agents is simpler: commit, push, open a pull request, and put durable output in the PR or the
issue, never only in the worktree. A finished card disappears from the board about fifteen minutes
after the lane ends (`GRACE`).

---

## 3. A lane is one pass, and `--restart` is inert without the daemon

**Mechanism.** An engine invocation reads its prompt once and exits. When it exits, the lane is
over, whether or not it delivered anything. `--restart until-merged` and `--after <lane>:pr-merged`
do not change that by themselves: they are **recorded metadata** on the lane's state record. The
thing that reads them is the supervisor daemon.

**The guard.** `fleet daemon start` installs a systemd user unit. systemd guarantees one instance,
restarts it after a crash, and brings it back after a reboot, which a background shell watcher
never did. `fleet daemon status` shows its heartbeats. The daemon only ever acts on lanes that
carry a `--restart` policy, so it is safe to run next to your own tooling.

**Where the guard stops.** Nothing warns you at spawn time that the daemon is down. A `--after`
lane is worse than inert: it creates no worktree and no card at all, so a farm with a stopped
daemon looks idle and correct while the gated lane waits forever. Check `fleet daemon status`
before relying on either flag, and remember that linger has to be enabled or the daemon dies with
your ssh session.

---

## 4. Duplicate pull request storms

**Mechanism.** The respawn loop asks two questions: did this lane deliver, and did it exit. Get
either answer wrong and the supervisor mints a fresh branch and a fresh pull request for work that
is already done. Lanes have cut ten near-identical pull requests this way in one night. The four
ways the answer goes wrong are all real: the GitHub API is rate-limited and returns nothing; the
lane opened its PR seconds before exiting and the API cannot see it yet; the unit has not finished
booting so the lane looks exited; and `pr-merged` reads an open, unmerged PR as "not delivered"
even though an agent cannot merge its own work.

**The guards,** all five in the supervisor:

- **Unknown is not undelivered.** Every delivery check returns three values, not two. When GitHub
  cannot be reached the lane is left alone until the next tick. A blind supervisor that assumed
  "no" is exactly how it duplicates every lane it governs.
- **Bootstrap grace** (120s): a record younger than that may still be coming up, so it is not an
  exited lane.
- **Teardown grace** (180s): a pull-request lane that exited moments ago may have opened a PR the
  API has not published yet. The window is keyed on a field the daemon never rewrites, so it
  closes on its own.
- **The open-PR wait:** a `pr-merged` lane with an open pull request is waiting for review, not
  failing. It is never respawned. A PR closed unmerged leaves no open PR, so a genuinely dropped
  lane still respawns.
- **A per-lane ledger** holds the attempt count and the cooldown (default 10 attempts, 600s
  apart). It is keyed on the lane, not the record, so it survives the child record a respawn
  mints, it is written before the spawn rather than after, and a write it cannot vouch for
  cancels the spawn.

**Where the guard stops.** The graces are time windows, so a farm with a badly wrong clock, or an
API outage longer than your patience, still gets it wrong eventually. If you see near-identical
pull requests from one lane, stop the daemon first and count them second.

---

## 5. Briefs with quotes, backslashes or more than 120 KB

**Mechanism.** A brief crosses several boundaries: your shell, possibly an ssh shim, the fleet CLI,
and finally the engine's command line. Each boundary has its own quoting rules. A brief that ends
in a double quote or a backslash, or that contains a triple quote, has broken spawn in the past,
and the failure landed after the worktree, the branch and the hooks already existed, leaving an
orphan that no card described.

**The guard.** Brief text is no longer spliced into generated source: it is written to a file under
`~/.fleet/briefs/`, passed by path and environment variable, and the state record's summary is read
back from that file. A spawn that fails after creating anything rolls back through an `EXIT` trap:
the worktree, the branch, the hook directory, the record and the claim all go away rather than
becoming a phantom lane. The ssh shim in the docs quotes every argument with `printf %q` for the
same reason.

**Where the guard stops.** Shell quoting is still yours to get right at the point where you type
the command. For anything long, structured or punctuation-heavy, do not fight it:

```bash
cat > ~/.fleet/briefs/<LANE>.md <<'BRIEF'
...whatever you like, quotes and backslashes included...
BRIEF
fleet spawn --project <PROJECT> --lane <LANE> --brief-file ~/.fleet/briefs/<LANE>.md
```

A heredoc quoted with `<<'BRIEF'` performs no expansion at all, and `--brief-file` never touches a
command line.

---

## 6. The argv size limit

**Mechanism.** The prompt is handed to the engine as a single argument, and Linux caps one argument
at `MAX_ARG_STRLEN`, 131072 bytes. Exceeding it fails at `exec`, after the worktree, the state
record and the unit exist. The lane then looks like it ran and did nothing, which is the most
expensive shape of failure: it costs you the time to read logs that say nothing.

**The guard.** Above 120000 bytes the spawn spills the full prompt to
`~/.fleet/briefs/<slug>.prompt.md` and hands the engine a short pointer telling it to read that
file first. The spill lives in fleet-owned state, outside the git worktree, so `git clean` cannot
remove it and `fleet salvage` cannot commit it into the lane's branch. The spawn prints a note
saying it happened.

**Where the guard stops.** The limit is per argument, so a brief safely under it can still be
oversized once the system framing is prepended. And a brief that large is usually a design problem:
a lane whose instructions do not fit in 120 KB is more than one lane. Split it.

---

## 7. The dashboard is a shared service on a fixed port

**Mechanism.** The dashboard is one long-lived process on port 7878, running inside a detached tmux
session, and it is shared by every agent and every human looking at the farm. Its command line is
literally `python3 server.py`. That means `pkill -f server.py`, `pkill -f python3`, or a tmux-wide
kill takes the board down for everyone, and the farm then looks dead from outside while every lane
is in fact working normally. This has happened, and the reflex it triggers (redeploy something that
was never broken) is worse than the outage.

**The guard.** `fleet dashboard start|stop|status` is the interface: start is idempotent and says
so when it is already running, and the first `fleet spawn` starts it for you. Nothing in the tool
kills it by pattern.

**Where the guard stops.** Nothing stops your shell. Never kill it by pattern, never run a second
copy by hand on the same port, and when the page is unreachable check
`fleet dashboard status` before assuming anything about the farm (it reports the socket the
server is really listening on, not what your shell would have used). On a single-machine
install, `./install.sh --local` records a loopback bind in `~/.config/fleet/env`, which
`fleet dashboard` reads, so the port is not offered to the network at all.

---

## 8. Farm CI is never a merge authority

**Mechanism.** `fleet ci` runs the project's own gates on the farm's cores, against the speculative
merge commit (`main` plus the candidate), which is a stronger check than a branch-green run. It is
fast and it is useful, and it publishes **no** statuses to GitHub. A farm-green therefore resolves
no protected context. Treating it as permission to merge means merging on a verdict no protected
branch ever saw, produced by a runner whose tool versions are yours, not the project's.

**The guard.**

- Verdicts are explicit about their own coverage: `passed_partial` exists so that "green" can never
  quietly mean "green except the parts we skipped", and the uncovered gate names are in the record.
- A verdict goes **stale** when the base moves. The record then says which base it was verified
  against and demands a re-enqueue. A stale green is not a green.
- A gate may not vouch for itself: every claimed gate has to resolve to a real command, a named
  builtin or a named dependency step, and the test suite fails if a claim resolves to nothing.
- `conflict` means the candidate does not merge into the current base and nothing was run at all.

**Where the guard stops.** None of it is enforced at the point of merge, because GitHub does not
know the farm exists. If the farm and the hosted run ever disagree for the same commit, the hosted
verdict wins and the divergence is worth chasing: it has produced real defects in the past, but the
first two times it produced a missing tool on the farm and a CPU quota that changed test sharding.
Making farm CI a delivery path is a separate, deliberate decision, and it needs published statuses
and exactly one writer per context name, never hosted and farm at once.

---

## 9. The dashboard signs mail as one fixed identity, not you

**Mechanism.** Every message the dashboard sends goes out as `HQ_AGENT=<FLEET_DASH_HQ_AGENT> hq msg
<to> <text>`. `FLEET_DASH_HQ_AGENT` defaults to `dashboard`. Whoever is sitting at the browser,
the message lands in the office from that one name, never from the person who typed it.

**The guard.** `FLEET_DASH_HQ_AGENT` is a setting, so a farm can give its dashboard a name that
reads plainly as "someone at the board wrote this", and that sender carries the same colour and
glyph in the thread as any other mailbox, so a reader never mistakes it for an agent's own voice.

**Where the guard stops.** There is no login on the dashboard. Two people sharing one board send
under the same name, and a reader of the thread cannot tell them apart afterwards. If a message
needs to be attributable to one person, say who you are inside the text, or send it from a
terminal under your own codename instead of the compose box.

---

## 10. Reading mail in the dashboard never moves anyone's inbox cursor

**Mechanism.** `hq inbox` at a terminal marks mail read: a cursor keyed to one name on one machine
moves past it, and the same mail will not show again to that name there. The dashboard's mail
routes never call `hq inbox`. They read the office's raw comments directly on a 45-second
snapshot, so opening the Mail tab, scrolling a thread, or leaving it open on a screen changes
nothing about what any agent will later find unread.

**The guard.** This is a fix, not a new risk: before the dashboard, the only way to glance at mail
from outside your own session was `hq inbox`, and running that under the wrong name silently
stole that name's unread mail. The Mail tab is the safe way to look now.

**Where the guard stops.** The tab's own "new since I last looked" count lives in the browser's
local storage, not on the server. It resets in a private window or a different browser, and it
says nothing about what an agent itself has or has not read.

---

## 11. A wide dashboard bind means the token also starts guarding reads

**Mechanism.** `FLEET_DASH_BIND` set past `127.0.0.1` opens the dashboard to a network, and the
one bearer token becomes the only thing standing between that network and everything the board
can show: every lane's brief and result, the whole mail archive, account and cost figures. On
loopback the token only ever guarded the two write routes; widen the bind and it starts guarding
every read too.

**The guard.** The token is required on every route once the bind is not loopback, `fleet
dashboard token` prints it on demand, and a cross-site request is refused whatever token it
carries.

**Where the guard stops.** The token is one shared secret, not a login: anyone holding the link
sees everything the board sees, and there is no way to hand out a read-only copy. Prefer
Tailscale or an ssh tunnel over a public bind, and treat the token like a password once you widen
it.

---

## 12. Mail in the dashboard is 45 seconds behind the office, by design

**Mechanism.** Every mail route is served from a snapshot a background thread refreshes every 45
seconds; opening the Mail tab never talks to GitHub on the request path. A message sent moments
ago by an agent at the terminal may not appear yet, and the last good snapshot is kept and shown,
with a "stale since" time, when GitHub itself is briefly unreachable.

**The guard.** The delay is bounded and visible: the freshness label on the tab says Live or
Stale with a time, so the lag is never silently mistaken for "nothing was said."

**Where the guard stops.** 45 seconds is long enough that a fast back-and-forth in the terminal
looks out of order or incomplete if you are only watching the dashboard. For anything you are
actively steering in real time, `hq inbox --peek` or `hq feed` at a terminal is still faster than
the tab.

---

## 13. A dashboard started by your own systemd unit needs its own `EnvironmentFile`

**Mechanism.** `fleet dashboard start|stop|restart` reads `~/.config/fleet/env` itself. A systemd
unit that runs `dashboard/server.py` directly, outside those commands, does not read that file on
its own, so a bind, a title or a token set through `fleet dashboard` never reaches a unit you
built by hand.

**The guard.** Give such a unit `EnvironmentFile=-%h/.config/fleet/env` in a drop-in, the same fix
[`docs/MIGRATION.md`](MIGRATION.md) already gives for a hand-rolled daemon unit. Then a change made
through `fleet dashboard` takes effect the next time the unit starts, instead of silently never.

**Where the guard stops.** `fleet dashboard restart` still does not reach a unit outside this
repository's control, environment file or not: restart that unit yourself once the file is in
place. `docs/MIGRATION.md` has the full walkthrough.

---

## The short version

1. `--force` means "yes, destroy it". `--dry-run` first, always.
2. Pushed and in a pull request, or it does not exist.
3. `--restart` and `--after` do nothing without `fleet daemon`.
4. Duplicate pull requests come from a supervisor that guessed. If you see them, stop the daemon.
5. Long or punctuation-heavy briefs go in a file, not on a command line.
6. Over 120 KB the prompt is spilled to a file. A brief that large is probably two lanes.
7. Never kill the dashboard by pattern.
8. The farm can tell you a candidate is broken. Only the hosted run can tell you it is mergeable.
9. Dashboard mail always arrives from "dashboard", never from the person who typed it.
10. The Mail tab never marks anything read; `hq inbox` at a terminal still does.
11. Widen the dashboard's bind and the token starts guarding reads too, not just writes.
12. Dashboard mail runs 45 seconds behind the office. Trust the freshness label, not silence.
13. A dashboard run by your own systemd unit needs `EnvironmentFile` or it never sees the config.
