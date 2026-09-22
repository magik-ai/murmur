# Sharp edges

Twenty things every operator of a farm has to know. Each one is a real failure mode of this design,
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
The composer in the Mail tab says it on screen, under the Send button: "Sent as dashboard, not as
you." A sent message appears in the open thread at once as "sending" and settles to "sent" on the
server's answer, so you never press Send twice.

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

## 14. A big office is read one mailbox at a time, and the tab fills as it goes

**Mechanism.** An office holds one issue per name, and a name is never retired: a farm a few
months old has around a hundred mailboxes. Reading them is one call for the list and one call per
mailbox, so the first pass after a restart takes as long as a hundred calls take. It is not a
hundred every time: a mailbox nobody has written to since the last pass is skipped, so a settled
office costs one call a pass.

**The guard.** The list of mailboxes is published the moment it arrives and every thread as it
lands, so the tab fills in front of you instead of showing nothing until the last one is read.
The health table and the agent list are refreshed before the office, so a slow office never
delays them.

**Where the guard stops.** The office timeline is assembled by the dashboard from the threads it
has already read, the sessions `hq who` reports and the live branch claims. `hq feed` is NOT used
and must not be: it re-reads every mailbox for itself, which on the office of ninety nine took
eighty seven seconds, past any timeout a page can wait behind. At a terminal it is still the
right command; on the request path it is a route that answers an error.

---

## 15. Drain and Resume do far more than pause and unpause

**Mechanism.** The Power section of the Machine tab has two buttons whose names undersell them.
**Drain** runs `fleet game-mode on`, which salvages every live lane's work to git, stops the agent
runner so nothing respawns, kills the lanes to release their RAM, and stops the verification
database. **Resume** runs `fleet game-mode off`, which starts the agent runner again, and that
runner respawns every `until-pr` and `until-merged` lane from its brief. Resume can therefore put
a dozen agents back on the machine in a minute, spending subscription, from one click.

**The guard.** Neither acts on the press. Drain's confirmation lists by name the lanes it will
salvage and kill, and says that it stops the agent runner and the verification database. Resume's
confirmation says that the agent runner restarts and will respawn the restart-policy lanes. Both
run as jobs you can watch (edge 17), and the dashboard keeps running through both: it never stops
itself.

**Where the guard stops.** Salvage is not a merge. A verification run in flight loses its verdict
and has to be enqueued again, and a lane with no restart policy loses whatever salvage could not
push. If all you want is a quiet machine for the next twenty minutes, throttle instead (edge 16)
and leave the lanes alive.

---

## 16. Throttling caps the whole farm, not just new spawns

**Mechanism.** The power control's "Throttle the farm and stop new agents" runs `fleet mode
balanced`. That caps CPU and memory for **every** running agent, not only for the next one: a lane
in the middle of a build gets a third of the machine and takes correspondingly longer, and a lane
with a timeout of its own can hit it. The name reads like a spawn switch; the mechanism is a
machine-wide cap.

**The guard.** The confirmation names the CPU and memory caps it is about to apply and says that
the verification database is released. The change is live, needs no root and no restart, and
`fleet mode auto` (Automatic in the header) hands the machine back.

**Where the guard stops.** The four modes are the only lever there is. A flag that pauses spawns
while leaving running lanes at full speed is a separate, later change in `lib/mode.py`; until it
lands, "stop new agents" and "slow the running ones" are one switch, and the honest choice for a
farm you want to stop properly is Drain.

```bash
fleet mode              # what the farm is on now
fleet mode balanced     # what the Throttle button does
fleet mode auto         # give the machine back to the agents
```

---

## 17. A long action answers with a job, and a second press is refused

**Mechanism.** Drain, Resume, adding a project and enqueueing a verification can all take longer
than thirty seconds, which is longer than a page should hold a request open. Each answers
immediately with a job id recorded under `$FLEET_STATE/jobs`, and the page follows it by polling.
So a button that comes back at once has not finished: it has started.

**The guard.** The control that started a job stays disabled and shows the running job until it
ends, and the server refuses a second press of an action that is already running. A double click,
an impatient second click and a second browser tab all hit the same refusal, so the farm cannot be
drained twice.

**Where the guard stops.** The refusal is per action on this server, not per farm: nothing stops a
drain from the page while somebody runs `fleet game-mode on` in a terminal. And closing the tab
does not cancel anything. The job runs to its end and its record holds the result, so if you lose
the page, reopen it and read the job rather than pressing the button again.

---

## 18. The queue runner and the agent runner are two different services

**Mechanism.** `fleet daemon` is the supervisor that respawns `--restart` lanes. `fleet ci daemon`
is the worker that takes candidates off the verification queue and runs the tiers. They share a
word and nothing else. Starting `fleet daemon` because the queue is not moving changes nothing
about the queue, and stopping the one you did not mean to stop takes out the other half of the
farm quietly.

**The guard.** The Machine tab's Services section is one row per service with its own state and
its own buttons: agent runner (`fleet-daemon.service`), verification runner (`fleet-ci.service`),
sweep timer (`fleet-sweep.timer`) and the dashboard. The Queue tab's runner switch is
`fleet ci daemon start|stop` and only that. The states are read from a snapshot refreshed every 45
seconds, so opening a tab never runs a tool.

**The commands, so they are never confused:**

```bash
fleet daemon status        # lanes are not respawning
fleet ci daemon status     # the verification queue is not moving
```

**Where the guard stops.** The dashboard's own row is read-only, because a page cannot restart the
server that is drawing it; it shows the command instead. And a service that systemd reports as
active can still be wedged: active is not the same as working.

---

## 19. Enable and Test on an engine each spend a real request

**Mechanism.** In Machine, Engines, the enable switch runs `fleet models enable <id>` and Test runs
`fleet models test <id>`. Both send one real request to the provider, because an engine is only
routable when it passes a live health check: authentication and limits are things you cannot know
without asking. That request comes out of the same subscription window a lane would use, and on an
account near its limit it can be the request that trips it.

**The guard.** The buttons say so on screen before you press them, the table keeps the last test
result with the time it was taken (so you do not re-test to learn something already on the page),
and only an installed engine gets a switch at all: the rest show "not installed" with the install
hint and no button to press.

**Where the guard stops.** There is no dry run. Testing four engines is four requests, and a pass
means only that the provider answered once, a minute ago, not that it will answer during a
fourteen-hour night.

---

## 20. Provider keys never go through the page, and neither does spawning

**Mechanism.** A key typed into a web form is in the request, in anything between the browser and
the server, and in the browser's own memory and autofill. The dashboard therefore has no field for
a provider key and no route that accepts one. `fleet models auth <id>` reads the key from standard
input, never from a command line, so it stays out of your shell history too, and writes it to
`$FLEET_STATE/secrets/<id>.key` with mode 600.

```bash
fleet models auth <id> < ~/keys/<id>.key   # the key never reaches argv
fleet models enable <id>                   # now the live check can run
```

**The guard.** The same line is drawn around everything where money or identity is at stake:
spawning stays a command typed by a person under a codename, and `fleet dashboard stop`,
`fleet dashboard restart`, `fleet clean --force` and `fleet sweep --force` have no button either.
Adding an *account* is the one credential flow the page does help with, and it helps without
touching the credential: it prints the exact command to run in a terminal, then watches the
credentials file and flips the row to "logged in" by itself when the login lands.

**Where the guard stops.** None of this stops you. A key pasted onto a command line is in your
history, and a key pasted into a mail message is in the head office repository forever. The page
declining to take it is a guard on the page, not on the operator.

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
14. A hundred mailboxes is a hundred calls on the first pass. The dashboard builds the timeline
    itself; `hq feed` is for a terminal, never for a page.
15. Drain salvages, stops and kills every lane; Resume respawns them all and spends subscription.
16. Throttle slows the running agents too. There is no spawn-only pause yet.
17. A long action returns a job id, not a result, and refuses a second press while it runs.
18. `fleet daemon` respawns lanes; `fleet ci daemon` runs the verification queue. Different things.
19. Enabling or testing an engine spends one real request on that subscription.
20. Provider keys go in over stdin at a terminal, never through the page.
