# The dashboard's three tabs

This design record describes the dashboard's three tabs, Board, Mail and Machine: what each one
is for, how it is laid out, and why. [`dashboard-product.md`](dashboard-product.md) holds what the
tabs share: the shell, the API rules, the panel states and the vocabulary. Three sections of the
Machine tab have records of their own: [`hosting.md`](hosting.md),
[`models-providers.md`](models-providers.md) and [`github-projects.md`](github-projects.md).

Words used below. A **farm** is an always-on Linux machine that runs coding agents. A **lane** is
one agent doing one task on its own branch. The **head office** is a private GitHub repository the
agents use for names, branch claims and messages.

The main requirement: a person from outside the project must be able to read the dashboard, and
run the farm from it, without a terminal and without being told how.

## 1. Requirements and decisions

| Requirement | Decision |
|---|---|
| Every tab has a job of its own. A page of summaries of the other tabs has none. | There is no Overview. The page opens on the Board. |
| The screen an operator keeps open all day shows the agents, the machine and the subscriptions together. | The Board: the agents, with a machine strip and an accounts strip above them, and nothing else. |
| Filtering must work with twenty code names. A row of twenty chips does not. | Two selects, "Started by" and "Status", and a search box. No chips. |
| Everything about the machine is in one place: power, services, machines, accounts, models, projects, health. | The Machine tab, with one section for each. |
| A switch is drawn only where pressing it can work. | A model that is not installed, or has no key, gets no switch. Adding an account is a real flow whose login state flips by itself. |
| The project registry has no purpose on its own. | Projects is a section of the Machine tab, not a tab. |
| The farm can be paused and resumed from the page, and the page itself runs on the farm. | The power actions act on the agents, never on the machine. The dashboard never stops itself. |
| Mail must not scroll as one long document, and every label must be plain words. | Mail is three fixed panes, each with its own scroll, and a fixed list of words (amendment 12). |
| Every tab reads as a product, not as console output. | Controls sit next to what they change, and every sentence is written for a stranger. |

## 2. Information architecture

Three tabs. The sidebar and the header are described in `dashboard-product.md` section 2.

| Tab | Job | Sections |
|---|---|---|
| Board | the screen you keep open | Setup checklist (only while something is unfinished), Machine strip, Accounts strip, Agents (cards or a table, two selects and a search box, a drawer for each lane) |
| Mail | talk to the agents | Conversations, the thread with its composer, Agents |
| Machine | set up and control the farm | Power, Services, Hosting, Accounts, Models, Projects, Health |

## 3. Board

**Setup checklist.** Drawn only while a prerequisite from `/api/health` is missing or failing. It
has no dismiss button: the only way to put it away is to fix what it names. When no agent has
ever run on the farm, the Board is the checklist plus the commands that produce the first agent:
`fleet add-project` when no project is registered, the spawn command with the first project's
name, and `fleet status`.

**Machine strip.** One row of tiles: Load, Memory free, Disk free, Graphics card and Temperature.
A graphics card sensor that is not set up says "Not configured"; a machine with no temperature
sensor fleet can read says "Not measured". One that is there but silent says "No answer".
Capacity and the sweep countdown are in the header, so they are not tiles.

**Accounts strip.** One row, one card per subscription, the Claude accounts and Codex together.
A card shows the name, the vendor's mark, every window as a bar with its percent, and when the
soonest window resets. A card whose account is out of room has a red border. Pressing a card
opens the Machine tab at Accounts.

**Agents.** The control bar has a "Started by" select (Anyone, then each spawner with a count), a
"Status" select (Any, then the five meanings with counts), a search box (lane, branch or change
number), the count of lanes shown, and a Cards or Table switch that this browser remembers. The
first 60 lanes are drawn, then a "Show the other N" button.

A card shows the code name's mark and the lane's name, a status pill, the project and the lane,
the start of the brief, the pull request's checks, the age, the cost, the tokens out, "change
open" when there is a pull request, and the engine's mark. A line is added when the lane's record
cannot be read, when its contract was not met, or when it dropped part of its scope. The table
has the columns Lane, Project, Status, Model, Started by, Started, Cost and Tokens out, and sorts
on any of them.

**The lane drawer** opens from a card or a row and keeps the list on screen. It shows the lane's
facts (status, project, lane, engine and model, who started it, when, cost, tokens, restart
policy, branch, worktree), the change and its checks, the brief, the result, the last 200 lines
of the log with a Refresh button, "Message this lane", and "Ending this lane" (amendment 8).

## 4. Mail

The three panes hold themselves to the window with
`grid-template-columns: 280px minmax(0, 1fr) 260px`. Each pane scrolls on its own, and the page
under them never scrolls.

- **Left, "Conversations"**: a search box, then "Everyone" pinned first (the `all` conversation),
  then the others, newest first. Each row says when it was last active, with an unread count. The
  first 12 are listed, then "Show all N". What you have read is remembered in this browser, never
  on the server.
- **Middle, the thread**: a header with the name, its mark, when it was last seen, and the
  "Everything the office did" toggle. The toggle swaps the thread for the office's whole timeline:
  messages, branch claims and sessions. Messages run from oldest at the top to newest at the
  bottom, with a line between days. The last 100 are drawn, with a button for the earlier ones.
  The composer is pinned under the thread and always writes to the open conversation.
- **Right, "Agents"**: the agents that are here now, and a collapsed "Not heard from lately (N)".

The words on screen are conversation, message, sent as and last seen (amendment 12). A sender's
name carries the same mark and colour as its agent card.

## 5. No queue tab

This section number covered a tab for a verification queue, which the dashboard does not have. A
lane's pull request checks come from GitHub and show on its card (section 3).

## 6. Machine

The sections come in the order a person needs them: power, the services that do the work, the
machines, the accounts and models the agents spend, the projects they work in, and what is
missing.

**Power.** The five settings (Full, Shared, Background, Paused, Automatic) are switched from the
header on every tab. On a machine without a systemd slice the header has no power control, and
this section shows the five settings instead. Three actions change the whole farm: "Throttle the
farm and stop new agents", Drain and Resume (amendment 3). Each one asks first, and its confirm
says what it will do. The section says that the dashboard keeps running through all of them.

**Services.** One row per service, with its state, when it last changed, what it does, and Start,
Stop and Restart where `fleet` has the verb:

| Service | What is read | Commands |
|---|---|---|
| Agent runner | `fleet-daemon.service` | `fleet daemon start`, `fleet daemon stop` |
| Sweep timer | `fleet-sweep.timer` | `fleet autosweep on`, `fleet autosweep off` |
| This dashboard | `fleet-dashboard.service`, else its tmux session, and its listening socket | none: the row is read-only and shows `fleet dashboard restart` |

Restart is Stop and then Start.

**Hosting.** The machines this farm owns: your own machine over SSH, or a DigitalOcean Droplet.
See [`hosting.md`](hosting.md).

**Accounts.** A table with the account (its name, a room pill and the vendor's mark), its login
state (amendment 13), its windows as bars, when it was last read, and Remove. The heading has two
buttons, "Refresh now" and "Add an account". Adding is a dialog in the drawer:

1. Pick the engine: Claude or Codex.
2. Name it. Codex is one shared login for the whole farm, so its name is always `codex`.
3. Run the command the farm gives, in a terminal on your own machine, and follow its steps.
4. Wait for the login. The dialog reads the login state every two seconds and flips to "Logged
   in" by itself.

Remove asks first, then moves the account's folder to `~/.fleet/dead-account-backups/`. Nothing is
deleted. The default account and Codex cannot be removed.

**Models.** The providers the agents are spawned with, and the models switched on for each. See
section 11 and [`models-providers.md`](models-providers.md).

**Projects.** The repositories a lane may be opened in, and the GitHub login the agents act as.
See [`github-projects.md`](github-projects.md) and amendment 14.

**Health.** Drawn only when the farm sets `FLEET_DASH_HEALTH=on`, because its tiles read hardware
sensors that most machines do not have. It shows the sensor tiles and the prerequisites table from
`/api/health` (Tool, State, What it means, Fix). The tab's count of missing or failing
prerequisites is shown only while this section is. The Board's setup checklist does not depend on
this setting.

There is no Settings section. The dashboard's settings are environment variables:
`FLEET_DASH_TITLE`, `FLEET_DASH_HQ_AGENT`, `FLEET_DASH_BIND`, `FLEET_DASH_PORT`,
`FLEET_DASH_TOKEN` and `FLEET_DASH_HEALTH`. The page never shows the token (amendment 4).

## 7. Server routes

The routes these tabs use beyond those in `dashboard-product.md` section 3, and what runs behind
each:

| Route | What runs |
|---|---|
| `POST /api/agents/kill {slug, retire}` | `fleet kill [--retire] <slug>`; the answer carries the lane's restart policy and a sentence on what the press did |
| `GET /api/services` | nothing: the services snapshot (amendment 5) |
| `POST /api/services {service, action}` | `fleet daemon start` or `stop`, `fleet autosweep on` or `off`; a restart is the stop and then the start; the dashboard's own row is refused |
| `GET /api/power/preview?action=` | nothing: what throttle, drain or resume will do, with the lanes a drain would stop, read from state files |
| `POST /api/power {action}` | `throttle` runs `fleet mode balanced` and answers at once; `drain` runs `fleet game-mode on` and `resume` runs `fleet game-mode off`, each as a job |
| `GET /api/accounts/login-state` | nothing: each account's credentials file and the last usage snapshot, never the vendor |
| `POST /api/accounts/refresh` | wakes the account reader; refused for 60 seconds after a press |
| `POST /api/accounts/add {name, engine}` | creates the account's folder and answers the login command with its steps; for Codex, which is one shared login, it creates nothing and answers the command that logs it in again |
| `POST /api/accounts/remove {name}` | moves the account's folder to `dead-account-backups` |
| `GET /api/projects/next-port` | nothing: the next free port block |
| `POST /api/projects/remove {name}` | a guarded rewrite of `projects.toml`, because `fleet` has no verb for it (amendment 14) |
| `GET /api/engines` | nothing: the model catalog, and whether each command is installed |
| `GET /api/jobs`, `GET /api/jobs/<id>` | nothing: the long actions in flight, and one action's record (amendment 7) |

Every write is behind the token and the cross-site refusal. Every command is an argv list, never a
shell string. `hq` parses its arguments with argparse, so `hq msg` gets `--` before its positional
arguments. `fleet` reads its arguments with a case loop and gets no `--`.

## 8. Acceptance

A person who has never seen the farm must be able to:

- open the Board and say who is running, whether the machine is healthy, and whether any account
  is out of room;
- open Mail, find a conversation and reply, without being told how;
- open Machine, add an account, switch a model on, pause the farm and resume it.

Amendment 19 says how this is checked.

## 9. Amendments

These numbered rules refine sections 2 to 8. Code and tests cite them by number ("amendment 7"),
so the numbers do not change.

1. **The Board** is four things, in this order: the setup checklist (only while a prerequisite is
   missing or failing), the machine strip, the accounts strip, and the agents at full width. When
   no agent has ever run, the checklist and the commands that start the first agent are the whole
   page, with the spawn command filled in with the first registered project's name.
2. **The header** is described in `dashboard-product.md` section 2. Its power setting is a
   control, not a word: a select with Full, Shared, Background, Paused and Automatic. It is drawn
   only on a machine with a systemd slice to cap, and it is switched off on a read-only page.
3. **Power actions are labelled as what they do.** No command only stops new spawns. So the
   button is "Throttle the farm and stop new agents" (`fleet mode balanced`), and its confirm
   names the CPU and memory caps from the farm's own power profile. Drain runs
   `fleet game-mode on`. Its confirm lists by name the lanes it will salvage and stop, and says
   that it stops the agent runner and that a lane with no restart policy loses whatever salvage
   could not push. Resume runs `fleet game-mode off`. Its confirm says that the agent runner
   starts again and respawns every until-pr and until-merged lane, which spends subscription.
4. **The token never appears on the page.** The page cannot rotate it either.
   `fleet dashboard token` prints it, and `fleet dashboard restart` restarts the server.
5. **Services come from the snapshot.** `GET /api/services` is served from the 45 second
   refresher: `systemctl --user is-active` for `fleet-daemon.service` and `fleet-sweep.timer`,
   and the dashboard's own row from its user unit, its tmux session and its listening socket,
   the way `run.sh status` reads them. No GET runs a tool.
6. **Routes.** Section 7 lists every route these tabs use and what runs behind each.
7. **Long actions are jobs.** Each write names its own timeout. An action that can take more than
   thirty seconds (drain, resume, registering a project) answers at once with a job id. The
   record lives under `$FLEET_STATE/jobs`, and the page polls `GET /api/jobs/<id>`. The control
   that started it stays disabled while the job runs, and a second press is refused with 409.
   Actions that share a resource share a key, so Drain and Resume can never run at once. A
   finished record is kept for a day.
8. **Stop versus Retire** comes from the lane's restart field. With a restart policy, the drawer
   offers "Stop this pass", whose confirm says the runner will start the lane again under a new
   name, and "Retire this lane", which ends it for good. With no policy it offers only "Stop this
   lane". The worktree and the branch stay either way.
9. **Not used.** This number covered the runner of a verification queue, which the dashboard does
   not have.
10. **Not used.** This number covered that queue's logs.
11. **Mail send feedback.** A sent message appears in the open conversation at once as "sending".
    It becomes "sent, it will show here at the next refresh" when the server answers 200, and the
    server wakes its refresher, so that takes seconds. A failure leaves the text in the composer.
12. **Mail labels, in full:** "Conversations" over the left pane; "Everyone" first, with "every
    agent on this farm" under it; "Unread since you last looked" as the unread count's title;
    "Show all N"; "Agents" over the right pane, with "Here now" and "Not heard from lately (N)";
    "Last seen 10m ago"; the composer label `Message to <name>`; "Sent as dashboard, not as you"
    beside Send; "Everything the office did" for the timeline toggle; "The office last answered
    10m ago" for an old snapshot. Never on screen: mailbox, box, feed, hq, issue, thread id.
13. **Login states**: Logged in, Waiting for the first login, Token expired
    (`fleet accounts keepalive` refreshes a Claude login; Codex is logged in again), Rate limited
    (the farm cannot tell how much room is left), and Cannot tell. Each comes with the sentence the
    server writes. The table shows when each account was last read. "Refresh now" is disabled for
    sixty seconds after a press.
14. **Removing a project** is refused while the project has open lanes, and the refusal says how
    many. It edits only the registry, and keeps a copy of the old file next to it. The checkout and
    the worktrees stay. The answer names the dev server port block that becomes free. Adding a
    project defaults its port base to the next free block above the highest one registered.
15. **Models.** Switching a model on runs its Test, and the buttons say what Test does: for Claude
    Code and Codex it checks the CLI (and Codex's login) and sends no request, and for an added
    engine it sends one short prompt. A provider key is given on the command line
    (`fleet models auth <id>`, which reads the key from stdin), never in a web form. Spawning stays
    out of the browser: money and identity belong to a session that has a name. These also stay in
    the terminal: `fleet dashboard stop` and `restart`, `fleet clean --force` and
    `fleet sweep --force`.
16. **A read-only page.** When the page holds no write token, every control is drawn switched off,
    and one line on every tab gives the reason from `/api/access`. A read-only dashboard is a
    legitimate way to run it, and it must not look broken.
17. **Small screens.** Under 1100 px, the Mail tab's Agents pane becomes a button with a count in
    the thread header, and slides over the thread when pressed. Under 800 px, the conversation
    list becomes a select above the thread.
18. **Old addresses still work.** `#/overview` and `#/agents` open the Board, `#/projects` and
    `#/accounts` open those sections of the Machine tab, and `#/system` opens the Machine tab. The
    jump palette offers the three tabs, every agent, every project and every conversation.
19. **Acceptance checks.** The screenshot checks cover every tab in every stub state, at a desktop
    width and a phone width. The hostile checks cover every control in the read-only state. And a
    person who has not seen the farm answers, from the Board alone and in under two minutes: who
    is running, is the machine healthy, and is any account out of room.

## 10. Where each tab's code lives

| Part | Files, under `fleet/dashboard/` |
|---|---|
| Shell | `index.html`, `static/app.js`, `static/app.css`, `static/core/` |
| Board | `static/views/board.js`, `static/views/agents.js` |
| Mail | `static/views/mail.js` |
| Machine | `static/views/machine.js` and `static/machine.css`; its Hosting, Models and Projects sections in `static/views/hosting.js`, `models.js` and `projects.js`, each with its own stylesheet |
| Server | `server.py`, `github_access.py` |
| Stub and checks | `test_stub_server.py`, `stub_github.py`, `stub_models.py`, `test_ui.mjs`, `test_browser.sh` (which runs every `test_hostile*.mjs` and `test_screens*.mjs`), `test_server.py`, `test_github_access.py` |

A section with a file of its own keeps its code there. `machine.js` exports the few helpers the
section files share (`sectionHead`, `stepHead`, `commandRow`, `copyCommand`, `detailRow`,
`farmAlias`, `readOnlyLine`, `blocked`), so two people can change two sections without editing
the same file.

## 11. Models

The Machine tab's Models section lists providers. A provider is an agent CLI and the way it is
paid for, and the models it offers are switched on in its drawer.
[`models-providers.md`](models-providers.md) section 2 describes the table and the drawer. This
section covers adding and removing a provider.

The shipped example catalog carries no dated notes. A note about what a plan is doing today
belongs in the farm's own catalog.

**Adding.** "Add a provider" opens a dialog in the drawer, with numbered steps:

1. **Pick a service** from the presets. murmur ships two, Claude Code and Codex. Each card says in
   one line how it is paid for, with a pill for whether running it headless is permitted (read
   from its `tos` sentence). A service already in the catalog shows "already added" and cannot be
   picked. When every shipped preset is already there, the dialog says so: another engine is a
   contribution.
2. **Name it**: an id for the catalog, filled in from the preset. A "Which model" select appears
   when the preset lists variants.
3. **Access.** A subscription preset shows the login command to run in a terminal on your own
   machine, with its steps (Codex logs in through an SSH tunnel to port 1455). A key preset shows
   `fleet models auth <id>` and "Paste the key when it asks", and says that a key never goes
   through this page. A local preset shows its install and pull commands.
4. **Register it.** `POST /api/models/add` writes the entry to the farm's catalog, creating
   `~/.config/fleet/models.toml` from the shipped example on the first write. The dialog then
   runs Test itself when the row can be tested, watches for the answer, and offers Switch on.

**Removing.** Only an entry this farm added (`source = "added"`) can be removed. A shipped entry
can only be switched off. Remove asks first, then deletes the entry, its runtime state and its
stored key.

**Presets** live in `fleet/lib/model_presets.py`, one dict per service. Every preset has the same
fields: id, label, color, kind (subscription, key or local), engine, bin, install_hint, pull_hint,
auth_env, run (a command template), health (the test prompt), tos, access, variants and docs.
`GET /api/models/presets` serves them, each with `added` set when the catalog already has it.
Adding an engine means adding one dict there; [`CONTRIBUTING.md`](../../../CONTRIBUTING.md) says
which fields and which test to extend.

**Routes.**

- `GET /api/models/presets`
- `POST /api/models/add {preset, id, variant?, bin?, run?, auth_env?, label?}`
- `POST /api/models/remove {id}`
- `POST /api/models {action, id}`, where the action is `enable`, `disable` or `test`

Every write is behind the token and the cross-site refusal. The catalog is written by a guarded
TOML writer that escapes values. A key never arrives in a request body. A body with a field named
like a key, secret, token, credential or password is refused, and so is a command line with a key
written into it. Both refusals name `fleet models auth <id>`.

`GET /api/engines` is what the page reads as the models table: the catalog, with each row's
`access`, `status` (`on`, `off`, `needs_key`, `not_installed` or `failing`), `source`, `variant`,
and whether its command is installed. `GET /api/models` is the catalog alone.
