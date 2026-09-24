# Sharp edges

Seventeen things every farm operator should know. Each one is a real way this design can fail.
For each, this page explains the mechanism and the guard that already exists, because knowing
where the guard stops is the useful part.

A farm is the always-on Linux machine that runs the agents. A lane is one agent doing one task on
its own branch, in its own git worktree. The orchestrator is the agent or person who splits work
into lanes and spawns them with `fleet spawn`.

Read this once before you need it. Several of these edges destroy work, and they do it quietly.

---

## 1. `--force` on `clean` and `sweep` destroys work

**Mechanism.** `fleet clean` removes the worktrees and state records of finished lanes.
`fleet sweep` removes the worktrees of merged branches and archives the cards of finished lanes.
A removed worktree is gone, with its uncommitted changes and its untracked files. Without
`--force`, `clean` keeps any worktree with uncommitted changes or unpushed commits, and `sweep`
keeps any worktree with uncommitted changes. With `--force`, they remove it.

**The guard.**

- `clean --force` is refused unless you also pass `--by <codename>`, so a forced clean cannot
  reach another orchestrator's lanes.
- Without `--force`, `clean` keeps a worktree with unsaved work and tells you to run
  `fleet salvage <slug>` first. `<slug>` is the lane's unique id, printed by `fleet spawn`.
- With `--force`, `clean` still refuses a worktree with unsaved work: it prints what would be lost
  and asks you to run it again with `--yes`.
- `sweep` without `--force` never removes a worktree with uncommitted changes, and the sweep timer
  never passes `--force`.
- Before a forced removal, both commands save the changes in `~/.fleet/state-archive/<YYYY-MM>/`:
  `<slug>.dirt.txt` holds `git status` and the diffs, and `<slug>.untracked.tar` holds the
  untracked files.

**Where the guard stops.** The saved copy is a diff and a tar file, not your branch. After
`--force --yes` on a worktree with a day of uncommitted work, that is all you have left. Run
`fleet clean --dry-run` and `fleet sweep --dry-run` first: both print what the next run would
remove.

---

## 2. Only pushed work is safe

**Mechanism.** The sweep decides from GitHub, not from what you meant to do. A branch whose pull
request was merged is done, and its worktree goes. The card of a finished lane is archived after
15 minutes, and its worktree goes with it. Nothing on the farm's disk is a promise.

**The guard,** from the most protection to the least:

| State of the work | Protection |
|---|---|
| open pull request | worktree and card kept for as long as the pull request is open |
| pushed branch | the branch is on GitHub, so the worktree can go |
| committed, never pushed | the sweep pushes the commits to `refs/fleet-salvage/<slug>` before it removes the worktree |
| uncommitted changes, tracked or untracked | kept, and reported, until somebody runs `fleet sweep --force` (which saves them first) |
| files your `.gitignore` covers | none |

**Where the guard stops.** The salvage ref is a safety net, not a plan. It is hidden from the
branch list, and nobody reviews it. Recover it with
`git fetch origin '+refs/fleet-salvage/*:refs/fleet-salvage/*'`. Uncommitted changes are just as
invisible to a reviewer. The rule for agents is simple: commit, push, open a pull request, and put
durable output in the pull request or the issue, never only in the worktree. A finished card
leaves the board about fifteen minutes after the lane ends. [SWEEP.md](SWEEP.md) has the full
rules.

---

## 3. A lane is one pass, and `--restart` does nothing without the daemon

**Mechanism.** An engine reads its prompt once and exits. When it exits, the lane is over, whether
it delivered anything or not. `--restart until-merged` and `--after <lane>:pr-merged` do not
change that on their own. They are only written down: `--restart` in the lane's state record,
`--after` in `~/.fleet/pending/<lane>.json`. The supervisor daemon is what reads them.

**The guard.** `fleet daemon start` installs and enables the systemd user unit
`fleet-daemon.service`. systemd runs one instance of it, restarts it after a crash and starts it
again after a reboot. `fleet daemon status` shows whether it is active and its last log lines,
including the line it writes on every pass (once a minute). The daemon only acts on lanes that
carry a `--restart` policy and on lanes waiting behind `--after`, so it is safe to run next to
your own tooling.

**Where the guard stops.** Nothing warns you at spawn time that the daemon is down. A lane with
`--after` is worse than inert: it creates no worktree and no card at all, so a farm with a stopped
daemon looks idle and correct while the gated lane waits for ever. Check `fleet daemon status`
before you rely on either flag. Lingering must also be on for your user (`loginctl enable-linger`),
or systemd stops the daemon when your last session ends. The farm installer turns it on.

---

## 4. Duplicate pull requests

**Mechanism.** The daemon asks two questions about each lane: did it deliver, and did it exit. If
either answer is wrong, it starts the lane again on a fresh branch, and the new lane opens a second
pull request for work that is already done. An answer can go wrong in four ways:

- the GitHub API is rate-limited and returns nothing;
- the lane opened its pull request seconds before it exited, and the API does not show it yet;
- the lane's unit has not finished starting, so the lane looks exited;
- a `pr-merged` lane has an open pull request that is not merged yet, so it looks "not
  delivered", although an agent cannot merge its own work.

**The guards,** all in the supervisor (`fleet/lib/supervisor.py`):

- **Unknown is not undelivered.** When GitHub cannot be reached, the delivery check answers
  "unknown", and the daemon leaves the lane alone until its next pass.
- **Start-up grace** (120 s): a record younger than this may belong to a lane that is still
  starting, so it does not count as exited.
- **Exit grace** (180 s): a lane that must open a pull request, and exited moments ago, may have
  opened one the API does not show yet. The window runs from the last update the lane itself
  wrote, which the daemon never changes, so it closes on its own.
- **An open pull request is waiting, not failing.** A `pr-merged` lane with an open pull request
  is never started again. A pull request closed without a merge leaves no open one, so a lane that
  really dropped its work is still started again.
- **A count per lane.** The daemon allows 10 attempts per lane, at least 600 s apart
  (`FLEET_RESPAWN_MAX` and `FLEET_RESPAWN_COOLDOWN` change this). It counts per lane, not per
  record, so the count survives the new record each respawn creates. It writes the count before
  it spawns, and when it cannot write it, it does not spawn.

**Where the guard stops.** The graces are time windows. A farm with a badly wrong clock, or a
GitHub API that takes longer than three minutes to show a new pull request, can still produce a
duplicate. If you see near-identical pull requests from one lane, stop the daemon first
(`fleet daemon stop`) and count them second.

---

## 5. Briefs with quotes or backslashes

**Mechanism.** A brief passes through several layers: your shell, perhaps the ssh shim (the small
script that runs `fleet` on the farm from your laptop), the `fleet` command, and finally the
engine's command line. Each layer has its own quoting rules. A brief that ends in a quote or a
backslash, or that contains a triple quote, is where they break. A spawn that fails halfway could
leave a worktree, a branch and hooks that no card describes.

**The guard.** `fleet spawn` never pastes the brief into generated code. It writes the brief to a
file, and the lane's launcher reads the prompt from a file when it starts. If a spawn fails after
it has created anything, it undoes all of it: the worktree, the branch, the hook directory, the
state record and the head office claim. The ssh shim in the setup guides quotes every argument
with `printf %q` for the same reason.

**Where the guard stops.** Quoting on your own command line is still yours to get right. For
anything long, structured or full of punctuation, do not fight it. Put the brief in a file on the
farm:

```bash
mkdir -p ~/.fleet/briefs
cat > ~/.fleet/briefs/<LANE>.md <<'BRIEF'
...anything, quotes and backslashes included...
BRIEF
fleet spawn --project <PROJECT> --lane <LANE> --brief-file ~/.fleet/briefs/<LANE>.md
```

A heredoc opened with `<<'BRIEF'` expands nothing, and with `--brief-file` the text never passes
through your shell's quoting.

---

## 6. The size limit of one argument

**Mechanism.** The prompt reaches the engine as a single command-line argument, and Linux limits
one argument to 131072 bytes (`MAX_ARG_STRLEN`). A longer one fails when the engine starts, after
the worktree, the state record and the unit already exist. The lane then looks as if it ran and
did nothing, and its logs say little.

**The guard.** Above 120000 bytes, spawn writes the full prompt to
`~/.fleet/briefs/<slug>.prompt.md` and gives the engine a short prompt that tells it to read that
file first. The file lives in fleet's own state, outside the git worktree, so `git clean` cannot
delete it and `fleet salvage` cannot commit it. Spawn prints a note when this happens. Unread head
office mail, which rides along in the prompt, is cut to its last 24000 bytes.

**Where the guard stops.** A brief that large is usually a design problem: a lane whose
instructions do not fit in 120 KB is more than one lane. Split it.

---

## 7. The dashboard is one shared service on one port

**Mechanism.** The dashboard is one long-lived process, `server.py`, on port 7878
(`FLEET_DASH_PORT` changes it). Every agent and every person looking at the farm shares it. It
runs as the systemd user unit `fleet-dashboard.service` once `fleet dashboard enable` has
installed it; the farm installer does this. Without the unit, it runs in a detached tmux session
named `fleet-dashboard`. Either way its command line contains `server.py`, so `pkill -f server.py`
or `pkill -f python3` stops it. The unit starts it again after about five seconds. Under tmux it
stays down, and the farm looks dead from outside while every lane is working normally. The reflex
that follows, redeploying something that was never broken, does more harm than the outage.

**The guard.** `fleet dashboard start|stop|restart|status` is the interface. `start` changes
nothing when the dashboard is already up, and every `fleet spawn` starts it if it is down. Nothing
in `fleet` stops it by a pattern match. `fleet dashboard status` reports the address the server
is really listening on, not the one your shell would have used.

**Where the guard stops.** Nothing stops your shell. Never stop the dashboard with a pattern kill,
and never start a second copy by hand on the same port. When the page does not load, run
`fleet dashboard status` before you assume anything about the farm. A systemd unit you write
yourself is outside these commands: `fleet dashboard restart` does not reach it, and it does not
read `~/.config/fleet/env` unless you give it `EnvironmentFile=-%h/.config/fleet/env`. Use
`fleet dashboard enable` instead.

---

## 8. Dashboard mail is signed with one fixed name, not yours

**Mechanism.** The head office is a private GitHub repository that the agents use for names,
branch claims and messages, through the `hq` command. The dashboard sends every message as
`HQ_AGENT=<name> hq msg -- <to> <text>`, where `<name>` is `FLEET_DASH_HQ_AGENT`, `dashboard` by
default. Whoever sits at the browser, the message arrives under that one name.

**The guard.** `FLEET_DASH_HQ_AGENT` is a setting, so you can give the dashboard a name that
plainly means "someone at the board wrote this". With the default name, the Mail tab says so under
the Send button: "Sent as dashboard, not as you". A sent message shows in the thread at once as
"sending", then as sent when the server answers, and the Send button stays disabled in between.

**Where the guard stops.** The dashboard has no login. Two people at one board send under the
same name, and a reader cannot tell them apart later. If a message must be attributable to one
person, say who you are in the text, or send it from a terminal under your own code name.

---

## 9. Reading mail in the dashboard never marks it read

**Mechanism.** At a terminal, `hq inbox` marks mail as read: a cursor for one name on one machine
moves past it, and that mail does not show again for that name there. The dashboard never calls
`hq inbox`. It reads the head office's messages directly, in the background, every 45 seconds.
Opening the Mail tab, scrolling a thread or leaving the tab open changes nothing about what any
agent will find unread.

**The guard.** This makes the Mail tab the safe way to look at other agents' mail. Running
`hq inbox` under someone else's name takes their unread mail from them; the Mail tab cannot. At a
terminal, `hq inbox --peek` shows unread mail without moving the cursor.

**Where the guard stops.** The tab's own "new since I last looked" count lives in your browser's
local storage, not on the server. A private window or another browser keeps its own count, and
the count says nothing about what an agent has read.

---

## 10. A wide dashboard bind means the token guards reads too

**Mechanism.** Setting `FLEET_DASH_BIND` to anything but a loopback address such as `127.0.0.1`
opens the dashboard to a network. Then one bearer token is all that stands between that network
and everything the board shows: every lane's brief and result, the mail, the accounts and their
usage. On a loopback bind the token guards only the routes that change something. On a wider bind
it guards every data route too.

**The guard.** `fleet dashboard token` prints the token. Open the page once as
`http://<address>:7878/?token=<token>` and the browser tab keeps it. A write that the browser
marks as coming from another site is refused, whatever token it carries. Only the page itself and
a few routes that describe the dashboard, not the farm, stay open, so the page can load and ask
for the token.

**Where the guard stops.** The token is one shared secret, not a login. Anyone who has the link
sees everything the board sees, and there is no read-only token. Prefer a private network or an
ssh tunnel to a public bind. `FLEET_DASH_BIND=tailscale` binds only the machine's Tailscale
address, and `ssh -N -L 7878:127.0.0.1:7878 <farm>` reaches a loopback dashboard from your
laptop. Treat the token like a password once you widen the bind.

---

## 11. Dashboard mail is up to 45 seconds behind

**Mechanism.** Every mail route answers from a snapshot that a background thread refreshes every
45 seconds, so opening the Mail tab never waits on GitHub. A message an agent sent from a terminal
moments ago may not show yet. When GitHub cannot be reached, the tab keeps the last good snapshot.

**The guard.** The delay is bounded and visible. When a panel on screen shows a kept copy instead
of a fresh answer, the header says `Stale since <time>`. A message you send from the dashboard
makes it read the office again at once.

**Where the guard stops.** 45 seconds is long enough that a fast exchange at the terminal looks
out of order or incomplete on the board. For anything you steer in real time, `hq inbox --peek`
or `hq feed` at a terminal is faster.

---

## 12. A big office is read one mailbox at a time

**Mechanism.** The head office holds one GitHub issue per name, and `hq` never closes one, so the
number of mailboxes only grows. Reading the office takes one call for the list and one call per
mailbox. So the first pass after the dashboard starts takes as long as a hundred calls on an office
of a hundred names. Later passes skip every mailbox nobody has written to since the last pass, so
a quiet office costs about one call a pass. The dashboard reads at most 100 mailbox issues.

**The guard.** The list of mailboxes appears as soon as it arrives, and each thread as it is
read, so the tab fills in front of you instead of staying empty until the last one. The health
panel is refreshed before the office, so a slow office never delays it.

**Where the guard stops.** The dashboard builds the office timeline itself, from the threads it
has already read, the sessions `hq who` reports and the current branch claims. It never runs
`hq feed`, and it must not: that command reads every mailbox again on its own, which on a big
office takes longer than a page can wait. At a terminal, `hq feed` is still the right command.

---

## 13. Drain and Resume do more than pause and unpause

**Mechanism.** The Power section of the Machine tab has two buttons whose names undersell them.
**Drain** runs `fleet game-mode on`. It salvages every live lane (commits its uncommitted work and
pushes its branch), stops the agent runner (`fleet-daemon.service`) so that nothing is started
again, and kills the lanes to free their memory. **Resume** runs `fleet game-mode off`. It starts
the agent runner again, and the runner starts every lane that has a restart policy and has not
delivered, from its brief. So one click on Resume can put many agents back on the machine within
a minute or two, spending subscription.

**The guard.** Neither button acts on the first press. Drain's confirmation names the lanes it
will salvage and stop. Resume's confirmation says that the agent runner starts again and will
respawn the lanes with a restart policy, spending subscription. Both run as jobs you can watch
(edge 15). The dashboard keeps running through both: it never stops itself.

**Where the guard stops.** Salvage is not a merge. A lane with no restart policy is not started
again, and it loses whatever salvage could not push. If you only want a quiet machine for a
while, throttle instead (edge 14) and leave the lanes alive.

---

## 14. Throttling slows every running agent, not just new spawns

**Mechanism.** The Power button "Throttle the farm and stop new agents" runs `fleet mode balanced`
(Background, in the header's power switch). It stops new spawns, and it also caps all running
agents together at about 35% of the machine's CPU and 40% of its memory. A lane in the middle of
a build slows down, and a lane with a timeout of its own can hit it. The label reads like a
switch for new spawns, but the mechanism is a cap on the whole farm.

**The guard.** The confirmation names the CPU and memory caps before you press. The change applies
live, with no root and no restart, and `fleet mode auto` (Automatic in the header) gives the
machine back.

**Where the guard stops.** The power modes are the only lever there is. None of them stops new
spawns and leaves running agents at full speed. If you want the farm to stop properly, drain it.

```bash
fleet mode              # the current mode
fleet mode balanced     # what the Throttle button does
fleet mode auto         # give the machine back to the agents
```

---

## 15. A long action answers with a job, and a second press is refused

**Mechanism.** Drain, Resume, adding a project and creating or destroying a machine can take
longer than a page should wait for one answer. Each one answers at once with a job id, recorded
under `~/.fleet/jobs/`, and the page follows the job. So a button that comes back at once has not
finished: it has started.

**The guard.** The button that started a job stays disabled and shows the job until it ends. The
server refuses to start an action that is already running: a double click, an impatient second
click and a second browser tab all get the same refusal. The three power actions share one lock,
so Resume is refused while Drain runs.

**Where the guard stops.** The lock lives in the dashboard, not on the farm: nothing stops a Drain
from the page while someone runs `fleet game-mode on` in a terminal. Closing the tab cancels
nothing. The job runs to its end and its record keeps the result for a day, so if you lose the
page, reopen it and read the job instead of pressing the button again.

---

## 16. Switching on or testing a model sends a real request

**Mechanism.** In the Models section of the Machine tab, **Switch on** does what
`fleet models enable <id>` does, and **Test** does what `fleet models test <id>` does. Both send
one real request to the provider, because the only way to know that the login works and the
account has room is to ask. That request comes out of the same subscription a lane would use. On
an account near its limit, it can be the request that trips it.

**The guard.** Each button's tooltip says so before you press it. The table shows when each model
was last tested, so you do not test again to learn what the page already shows. A model whose command is
not installed gets no button at all, only a note to install it. A model with no key yet gets a
button that copies the `fleet models auth <id>` command.

**Where the guard stops.** There is no dry run. Testing four models is four requests. A pass means
only that the provider answered once, a minute ago, not that it will answer all night.

---

## 17. Provider keys never go through the page, and neither does spawning

**Mechanism.** A key typed into a web form sits in the request, in anything between the browser
and the server, and in the browser's memory and autofill. So the dashboard has no field for a
provider key, and its model and hosting routes refuse any request with a field whose name looks
like a credential. `fleet models auth <id>` reads the key from standard input, never from the
command line, so it stays out of your shell history too. It writes the key to
`~/.fleet/secrets/<id>.key` with mode 600.

```bash
fleet models auth <id> < ~/keys/<id>.key   # the key never appears on a command line
fleet models enable <id>                   # now the live check can run
```

**The guard.** The same line is drawn around spawning: a lane starts when a person or an
orchestrator runs `fleet spawn` under a code name, never from the page. `fleet dashboard stop`,
`fleet dashboard restart`, `fleet clean --force` and `fleet sweep --force` have no button either.
Where the page does help with a login, such as adding a Claude account, it never touches the
credential. It prints the command to run in a terminal, then watches for the login and marks the
row logged in by itself when it lands.

**Where the guard stops.** None of this stops you. A key pasted into a command line is in your
shell history, and a key pasted into a mail message is in the head office repository for good. The
page refusing a key protects the page, not the operator.

---

## The short version

1. `--force` means "yes, destroy it". Run `--dry-run` first, every time.
2. Pushed and in a pull request, or it is not safe.
3. `--restart` and `--after` do nothing without `fleet daemon`.
4. Duplicate pull requests come from a daemon that guessed. If you see them, stop the daemon.
5. Long or punctuation-heavy briefs go in a file, not on a command line.
6. Over 120 KB the prompt moves to a file. A brief that large is probably two lanes.
7. Never stop the dashboard with a pattern kill.
8. Dashboard mail arrives under one fixed name, never the name of the person who typed it.
9. The Mail tab never marks anything read; `hq inbox` at a terminal does.
10. Widen the dashboard's bind and the token guards reads too, not only writes.
11. Dashboard mail runs up to 45 seconds behind the office. Trust `Stale since`, not silence.
12. The first pass over a big office costs one call per mailbox. The dashboard builds the timeline
    itself; `hq feed` is for a terminal.
13. Drain salvages and kills every live lane; Resume respawns lanes and spends subscription.
14. Throttle slows the running agents too, not only new spawns.
15. A long action returns a job, not a result, and refuses a second press while it runs.
16. Switching on or testing a model spends one real request.
17. Provider keys go in over standard input at a terminal, never through the page.
