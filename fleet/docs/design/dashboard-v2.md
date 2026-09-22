# Dashboard v2: the owner's review, and what changes

Design record, 2026-09-22. The first product version of the dashboard went live on the
reference farm on 2026-09-21 and the owner used it for a day. His review, in one line: it still
looks like something an agent configured for itself; a person from outside cannot read it or
run anything from it. This record turns each of his points into a decision, then into a build
plan. It supersedes the information architecture of `dashboard-product.md`; everything else in
that record (states, vocabulary, API conventions, no framework) stands.

## 1. What the owner said, and the decision for each

| He said | What it means | Decision |
|---|---|---|
| Overview is about nothing; nothing can be read off it | A summary page of summaries has no job when the farm is one screen | Remove it. The landing view is the Board (below) |
| The old dashboard (agents, machine status, account status on one screen) must stay the main view, redesigned if you like | The one screen an operator keeps open all day | Board = agents grid + machine strip + accounts strip, nothing else |
| Filtering by chips is strange; give two dropdowns, agent and status | Chips for 20 spawners do not scale | Two selects (started by, status) plus a text search; chips go |
| Move machine things into one place: setup of the machine, of accounts, of engines, turning the farm on and off | The operator wants a control room, not a status page | Machine tab with sections: Power, Services, Accounts, Engines, Projects, Health, Settings |
| Accounts: I press Kimi and it says no. No UX around adding; a stub | Cards showed catalog entries as if they were switchable; add returned an ssh line and stopped | Engines: only installed engines get a switch; the rest show "not installed" and the install hint, no button. Accounts: a real add flow with a login state that flips by itself |
| No idea what Projects is for | A registry table with no purpose on its own | Fold into Machine as a section (register, remove, ports) |
| Turning the farm on and off from the UI, knowing the UI lives on the farm | Pause and resume the agents, not the machine | Power: pause spawns, drain (salvage and stop lanes), resume; service start and stop for daemon, CI runner, sweep; the dashboard itself never stops itself |
| Mail: scrolling scrolls everything, blocks must be fixed, I do not understand what is happening | The page scrolled as one document; the "who is in the office" list was endless | Mail becomes a fixed three-pane app: conversations (scroll), thread (scroll), composer (pinned); people in a collapsible side panel with a count; plain words on every label |
| Queue looks awful, cannot configure or see anything; open cards are giant columns with black bubbles | The card layout with the "not covered here" blob and stage chips | Queue becomes a table with a detail panel: one row per run, stages as a compact strip, detail with stage tabs and a real log viewer; the uncovered list behind a count; controls: enqueue, cancel, runner on and off |
| Every tab: components, native feel, usability, clarity, settings and control in place | Product, not console output | Every tab has a control bar, a settings drawer where settings exist, and copy a stranger reads |

Contested decision, mine: the plan review runs on Claude Opus on the farm, not Codex, because
the Codex subscription is out of room today (100% of the weekly window). Recorded for the owner.

## 2. Information architecture

Four tabs. The sidebar stays; the header keeps the product name, capacity pill, freshness label,
search and theme.

| Tab | Job | Sections |
|---|---|---|
| Board | the screen you keep open | Agents (grid or table, two selects and search, drawer), Machine strip (load, memory, disk, GPU, temperature, capacity, power mode), Accounts strip (each subscription's windows as bars) |
| Mail | talk to the agents | Conversations, Thread, Composer, People |
| Queue | what is being verified | Runs table, Detail panel, Controls |
| Machine | set up and control the farm | Power, Services, Accounts, Engines, Projects, Health, Settings |

## 3. Board

Agents. Control bar: select "Started by" (all plus each spawner with counts), select "Status"
(all plus the five meanings with counts), search box (lane, branch, PR number), view toggle cards
or table, sort in table. The card keeps: mark and name, project and lane and engine, status pill,
brief excerpt (two lines, markdown stripped), checks strip, cost and tokens, age, "has a change
open" link. The drawer stays as it is (brief, result, checks, log, message the lane) and gains
Stop (fleet kill) and Retire (fleet kill --retire) with confirmation.

Machine strip: one row of tiles under the header, the same tiles as today's System top row, plus
the power mode as a word with a link to Machine. Accounts strip: one row, one compact card per
subscription: name, session and weekly bars, reset countdown, red when out of room; the codex
account in the same row. Click opens Machine, Accounts section.

## 4. Mail

Layout: `grid-template-columns: 280px 1fr 260px` on desktop, each column its own scroll area,
the page never scrolls. Left: "Conversations", "Everyone" pinned first (that is the `all` box),
then boxes newest first, unread badge, search box, "show all". Middle: thread header (name, mark,
last seen), messages newest at the bottom with day separators, the composer pinned to the
bottom with the recipient select prefilled to the open conversation and a hint "sent as
dashboard". Right: "People" with live sessions first and stale ones under a collapsed "not heard
from lately (N)". Timeline is a toggle in the thread header. Words: conversation, message, sent
as, last seen. No jargon on screen.

## 5. Queue

Layout: a table (PR, branch, state, stages strip, started, took, verdict) with three groups as
row bands (Running, Waiting, Recent), sortable, filter by state and project. Clicking a row
opens a detail panel on the right (not a card in the grid): summary facts, a tab per stage with
its log (monospace, scrollable, wrapped, with a copy button), the failed tests as a list, the
"not covered here" gates as a count with an expandable list, verdicts and their disagreement
explained in one sentence. Controls bar: "Verify a change" (PR number, project) posting
`fleet ci enqueue`, Cancel on a running or waiting row, Runner on or off (`fleet ci daemon`),
and the explanation moved to a "?" tooltip. Empty state keeps the sentence and the count.

## 6. Machine

Power. The four modes plus Automatic as today, and three actions: Pause spawns (mode balanced or
hard per current setting), Drain (`fleet game-mode on`: salvage and stop lanes), Resume
(`fleet game-mode off`). Each shows what it will do before the confirm, and the dashboard says
plainly it keeps running through all of them.

Services. One row per service (agent runner, verification runner, sweep timer, dashboard) with
state, last change, and Start, Stop, Restart where fleet has the verb (`fleet daemon`, `fleet ci
daemon`, `fleet autosweep`); the dashboard row is read-only with the restart command shown.

Accounts. Table: name, engine, login state (logged in, waiting for login, expired), session and
weekly windows, last read. Add: form (name, engine) then a step-by-step panel: the exact command
to run, a "waiting for the login" state that polls the credentials file and flips to "logged in"
on its own, Done. Remove with confirmation (moves to backup, says where). Refresh now.

Engines. Table: engine, installed (yes or no, with the path or the install hint), enabled switch
(only when installed), last test result, Test. No switch on an uninstalled engine, and no
"prepared, do not enable" copy from one farm's notes in the catalog.

Projects. Table: name, repository, base branch, ports, open lanes; Add (name, repository, port
base), Remove with confirmation (registry only, worktrees untouched).

Health. Today's prerequisites table with the fix commands, sensors with their state.

Settings. Product name, mail identity, bind and port, token (rotate button that mints a new
token and shows it once), sweep interval, respawn limits: read from where they live, written
where fleet has a writer, read-only with the file path otherwise.

## 7. Server routes to add

| Route | Backing verb |
|---|---|
| POST /api/agents/kill {slug, retire} | `fleet kill [--retire] <slug>` |
| GET /api/services, POST /api/services {service, action} | `systemctl --user` status and `fleet daemon`, `fleet ci daemon`, `fleet autosweep` |
| POST /api/power {action: pause, drain, resume} | `fleet mode`, `fleet game-mode on, off` |
| POST /api/ci/enqueue {project, pr}, POST /api/ci/cancel {id} | `fleet ci enqueue`, `fleet ci cancel` |
| GET /api/accounts/login-state | credentials file presence and age per account |
| POST /api/projects/remove {name} | registry edit through `fleet` if it has a verb, else a guarded edit of projects.toml |
| GET /api/engines | catalog plus installed check per engine |
| POST /api/settings/token-rotate | rewrite dash-token, return it once |

All writes behind the token and the cross-site refusal, argv lists only, `--` before positionals
where the CLI parses options.

## 8. Build plan

Three lanes on the farm, disjoint paths, then an adversarial review on the farm, then an
end-to-end run on the Mac harness (extended with the new routes) and a live check.

- server: routes in section 7, tests.
- ui: Board, Mail, Queue, Machine, the removal of Overview, Projects, Accounts, System as tabs,
  stub fixtures, contract and hostile and screenshot checks.
- docs: QUICKSTART step 9, README paragraphs, this record's copy into the murmur handbook, the
  machine chapter.

Acceptance: a person who has never seen the farm opens the Board and can say who is running, is
the machine healthy, is any account out of room; opens Mail and can find a conversation and
reply without being told how; opens Queue and can read why a run failed and start a new one;
opens Machine and can add an account, switch an engine, pause the farm and resume it.

## 9. Amendments after the farm review (2026-09-22, review on PR #15, verdict RED)

Where this section conflicts with sections 2 to 8, this section wins.

1. **Board keeps the queue.** Board = setup checklist (only while a prerequisite is missing or no
   agent has ever run; then it is the whole page, with the spawn command filled with the first
   registered project's name), the machine strip, the accounts strip, then a two-pane canvas:
   agents on the left, the verification queue on the right (running and waiting rows only, plus a
   count of recent runs linking to the Queue tab), one draggable splitter whose position lives in
   localStorage, stacking to one column under 1100 px.
2. **Header keeps** the product name, capacity pill, project filter, freshness label, jump
   palette, theme switch, and the power mode as a four-state control (Full, Shared, Background,
   Paused, plus Automatic), not a word. The sweep countdown moves into the machine strip.
3. **Power actions, honestly labelled.** There is no spawn-only verb. The button is "Throttle the
   farm and stop new agents" (`fleet mode balanced`) and its confirm names the CPU and memory caps
   and that the verification database is released. Drain runs `fleet game-mode on`; its confirm
   lists by name the lanes it will salvage and kill and says it stops the agent runner and the
   verification database, a run in flight loses its verdict, a lane with no restart policy loses
   whatever salvage could not push. Resume runs `fleet game-mode off`; its confirm says the agent
   runner restarts and will respawn every until-pr and until-merged lane, spending subscription.
   A spawn-independent pause flag in lib/mode.py is a later, separate change.
4. **Token rotation is out.** Settings shows the token as present or absent, never its value, and
   the two commands (`fleet dashboard token`, `fleet dashboard restart`).
5. **Services come from the snapshot.** GET /api/services is served from the 45 second refresher:
   `systemctl --user is-active` for fleet-daemon.service, fleet-ci.service, fleet-sweep.timer, and
   the dashboard's own state from its tmux session and listening socket as run.sh status does.
   /api/ci's per-request is-active call moves into the same snapshot. No GET runs a tool.
6. **Routes: already served versus to add.** Already served and needing UI only: POST
   /api/accounts/add (returns the ssh command and the steps; codex has its own branch), POST
   /api/accounts/remove (moves to dead-account-backups), POST /api/mode, POST /api/models
   (enable, disable, test), POST /api/projects, GET /api/ci/log (256 KB tail, truncated flag).
   To add: POST /api/agents/kill {slug, retire}; GET and POST /api/services; POST /api/power
   {action: throttle, drain, resume}; POST /api/ci/enqueue {project, pr}; POST /api/ci/cancel
   {id}; GET /api/accounts/login-state; POST /api/projects/remove; GET /api/jobs/<id>.
7. **Long actions are jobs.** Each write names its own timeout. Any action that can exceed thirty
   seconds (drain, resume, add project, enqueue) answers at once with a job id recorded under
   $FLEET_STATE/jobs, is polled by GET /api/jobs/<id>, the control that started it stays disabled
   showing the running job, and a second press of a running action is refused.
8. **Stop versus Retire** are drawn from the lane's restart field: with a restart policy, Stop is
   "Stop this pass" and its confirm says the runner will respawn it under a new name, Retire ends
   it; with no policy only Stop is shown.
9. **The queue runner** is `fleet ci daemon start|stop`, never `fleet daemon` (the agent runner);
   the existing banner in queue.js that says "fleet daemon start" is wrong and is fixed.
10. **Stage logs**: monospace, soft-wrapped with a wrap toggle, scrolled to the bottom on open, a
    find box that highlights and steps through matches, a copy button, and the line "showing the
    last 256 KB of this stage, the whole log is `fleet ci log <id>`" whenever truncated is set; the
    panel keeps its scroll position across the tick.
11. **Mail send feedback.** On send the message appears in the open thread at once as "sending",
    becomes "sent, it will show here at the next refresh" on the 200, and the server wakes the
    refresher so that is seconds. A failure leaves the text in the composer.
12. **Mail labels, in full:** "Conversations" over the left pane; "Everyone" first with "every
    agent on this farm" under it; badge title "Unread since you last looked"; "Show all N";
    "People" over the right pane with "Here now" and "Not heard from lately (N)"; "Last seen 4 min
    ago"; composer label "Message to <name>"; "Sent as dashboard, not as you" under Send;
    "Everything the office did" for the timeline toggle; "The office last answered N minutes
    ago" for a stale snapshot. Never: mailbox, box, feed, hq, issue, thread id.
13. **Login states**: logged in, waiting for the first login, token expired (the keepalive timer
    usually fixes this), rate-limited so the farm cannot tell, each with the sentence
    claude_accounts.py already writes. The table shows when it was last read; "Refresh now" is
    disabled for sixty seconds after a press.
14. **Projects remove** refuses while the project has open lanes and says how many; edits only the
    registry; the confirm names the port block that becomes free. Add defaults the port base to
    the next free block above the highest registered one.
15. **Engines**: Enable and Test each send one real request to the provider and the button says
    so. Provider keys stay on the command line (`fleet models auth <id>`, key on stdin), never a
    web form. Spawning stays out of the browser: money and identity belong to a session that has
    a name. Also out: fleet dashboard stop and restart, fleet clean --force, fleet sweep --force.
16. **Read-only page.** Every control renders disabled with the sentence from /api/access when the
    page holds no write token. A read-only dashboard is legitimate and must not look broken.
17. **Small screens.** Under 1100 px the People pane collapses to a count in the thread header;
    under 800 px the conversation list becomes a select above the thread; the queue detail panel
    becomes a full-width sheet under 1000 px.
18. **Routes and bookmarks.** #/overview, #/projects, #/accounts and #/system redirect to their new
    homes; the palette is rebuilt from the four tabs. docs/OPERATIONS.md joins the docs lane.
19. **Acceptance**: the screenshot check extended to the four tabs in all states, the hostile
    check for every new control in the read-only state, the end-to-end harness extended with the
    new routes, and one timed run: a person who has not seen the farm answers who is running, is
    the machine healthy, is any account out of room, and where did this run fail, in under two
    minutes, from the Board and the Queue alone.

## 10. Lane split for the build (all on the farm, disjoint paths)

- **server**: fleet/dashboard/server.py, fleet/dashboard/test_server.py, fleet/docs/OPERATIONS.md
  (route table). Routes of amendment 6 "to add", jobs of amendment 7, services snapshot of
  amendment 5, mail wake of amendment 11 (server half).
- **ui-board-mail**: fleet/dashboard/index.html, static/app.js, static/app.css, static/core/**,
  static/views/board.js (new), static/views/mail.js, static/views/agents.js (folded into board or
  kept as the agents pane module), test_ui.mjs, test_browser.sh (which runs every test_hostile*.mjs
  and test_screens*.mjs by glob), test_hostile.mjs, test_screens.mjs. Removes overview.js,
  projects.js, accounts.js, system.js. Registers views "queue" and "machine" from their files
  with the existing view contract, and links static/queue.css and static/machine.css from
  index.html from the start.
- **ui-queue-machine**: static/views/queue.js, static/views/machine.js (new), static/queue.css,
  static/machine.css, test_stub_server.py (adds every route of amendment 6, jobs, services,
  login-state, projects remove, with fixtures in all states), test_hostile_queue_machine.mjs,
  test_screens_queue_machine.mjs. Does not edit core/**, app.js, app.css or index.html; a helper it
  needs is defined in its own file.
- **docs**: fleet/docs/QUICKSTART.md, fleet/docs/sharp-edges.md, fleet/README.md, README.md,
  docs/12-the-machine.md, docs/06-ci-and-merge.md.

## 11. Models, not Engines (owner review 2026-09-22, evening)

The owner: "not Engines but Models; make adding popular services and models understandable so
everything can be done there; right now nothing is clear and it is a visual mess." Decisions:

**The word.** The section and every label say "Models". A row is a model the agents can be
spawned with. "Engine" survives only as the internal launcher kind (claude, codex, generic) and
never on screen.

**The table.** One row per catalog entry, six columns, nothing else: Model (label, id under it
in mono, provider glyph from `color`), Runs as (the command, or "not installed" with the pill),
Access (how it is paid for: "your Claude subscription", "your ChatGPT subscription", "API key",
read from the catalog's `access` field, falling back to a sentence derived from `auth_env` and
`tos`), Status (one pill: On, Off, Needs a key, Not installed, Failing; the health detail as the
pill's title and as a muted line under it when failing), Last test (age), Actions (Switch on or
off when installed and keyed, Test, Remove for a model the operator added; nothing for a
shipped one that is not installed except the install hint in the Runs as cell). The role and the
quality notes leave the table: they are in the row's detail drawer, opened by clicking the name.
No dated notes, no "PREPARED, do not enable" copy: the shipped catalog carries none, and a
farm's own catalog is the operator's to write.

**Adding.** A button "Add a model" opens a dialog in the drawer with numbered steps:
1. Pick a service from presets (cards: Claude Code, Codex, Gemini CLI, Qwen Code, Kimi Code,
   OpenCode, Aider, Ollama local, Custom command). Each card says in one line how it is paid
   for and whether it is safe to run headless (from `tos`). A preset already in the catalog is
   shown as "already added" and not choosable.
2. Name it (an id, prefilled from the preset, editable for Custom) and pick the model variant
   where the preset lists any (for example gemini-2.5-pro).
3. Access. Subscription presets: the login command to run in a terminal (as accounts do). Key
   presets: the exact command `fleet models auth <id>` with "paste the key when it asks", and
   the sentence that a key never goes through this page. Local presets: the install and pull
   commands.
4. Register: POST /api/models/add writes the entry to the farm's catalog (creating
   `~/.config/fleet/models.toml` from the example on first write), then the dialog runs Test and
   shows the result, then Switch on. The dialog polls the row until the test answers.
Remove: only for entries the operator added (a `source = "added"` field); shipped entries can
only be switched off. Remove asks, then deletes the entry and its stored key.

**Presets** live in the server (`fleet/lib/model_presets.py`), one dict per service with id,
label, colour, kind (subscription | key | local), bin, install_hint, auth_env, run template,
health prompt, tos sentence, variants, docs URL. GET /api/models/presets serves them. The
shipped example catalog keeps claude and codex only; the rest are presets a person adds.

**Routes.** GET /api/models/presets; POST /api/models/add {preset, id, variant?, bin?, run?,
auth_env?} (Custom needs bin and run); POST /api/models/remove {id}; POST /api/models
{action: enable|disable|test, id} as today. All writes behind the token and the cross-site
refusal; the catalog is rewritten through a guarded TOML writer that escapes values; a key
never arrives in a request body (a body carrying `key` is refused with the sentence).

**GET /api/engines** keeps its route for one release with the same fields plus `access`,
`status`, `source`, `variant`; the page reads it as the models table. `/api/models` (the bare
listing) stays.
