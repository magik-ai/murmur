# The dashboard as a product

Design record, 2026-09-21. The fleet dashboard today is a status page for one farm run by one
company. This record turns it into a product a stranger installs and understands in a minute:
what it shows, how it is organised, what it says when something is missing, and how the agents'
mail moves in next to the agents. The audit that produced the list of tailored spots is in the
murmur plan (`internal/research/report-dashboard.md`); the ten cases from other products are in
section 8.

## 1. Intent and boundaries

The dashboard is the place where a person running a farm answers five questions without a
terminal: what is running, what is waiting on me, is the machine healthy, what did the agents
say to each other, and what is misconfigured. It does not replace the CLI for spawning (money
and identity belong to a session that has a name) and it does not become a second store for
anything: every panel reads a source that exists without the dashboard.

In scope: a new information architecture, a static front end split into modules, new read
routes (health, projects, mail, agent log), two small write routes (message a lane, send mail),
honest empty and error states, light and dark, generic vocabulary throughout, and the removal of
every constant that names one farm. Out of scope: users and roles, spawn from the browser,
a farm-hosted mail store, i18n.

## 2. Information architecture

A left sidebar with seven entries, collapsing to icons under 900 px and to a top bar under 600.
The landing view is Overview. The header carries the product name (configurable), the capacity
pill (one word and the reason on hover), a project filter that applies to Agents and Queue, and
the theme switch.

| Entry | Answers | Source |
|---|---|---|
| Overview | what needs me now | every other route, summarised |
| Agents | who is running, on what, how far | `/api/fleet`, `/api/agent`, `/api/agent/log` |
| Mail | what the agents said | `/api/mail/*` (the head office) |
| Queue | what is being verified before merge | `/api/ci`, `/api/ci/log` |
| Projects | which repositories this farm serves | `/api/projects` |
| Accounts | how much subscription is left | `/api/accounts`, `/api/models` |
| System | is the machine healthy and complete | `/api/metrics`, `/api/health`, `/api/mode`, `/api/sweep` |

Overview is composed of small cards, each a summary with a link into its tab: agents by status
(running, waiting on a person, failed, done today), the queue head, the four health tiles, the
account with the least room left, the last five mail messages, and, while any prerequisite is
missing, a "finish setting up" checklist on top. When the farm is empty the whole page is that
checklist plus the three commands that produce the first agent.

Agents keeps the card grid and adds a table view (one row per lane, sortable), the filter chips
by spawner and status, and a detail drawer instead of a modal: brief, result, last 200 log lines
with a refresh, the pull request with its checks named by their real job names, cost and tokens,
and a text box "send a message to this lane" that writes the lane's checkpoint inbox.

Mail is three panes: mailboxes on the left with a count of messages newer than the reader's last
visit (kept in `localStorage`, never on the server), the selected thread in the middle, newest at
the bottom, a compose box under it with a recipient select ("all" pinned first) and a send button.
A "timeline" toggle replaces the thread with the whole office as one feed (mail, claims, sessions).
Sender names carry the same colour and glyph as their agent cards.

Queue is the existing CI panes with the vocabulary generalised: "change" for pull request where
the forge is not known, stage names from data, and a one-line explanation of why a farm verdict
can differ from the hosted one, shown once and dismissible.

Projects lists what `projects.toml` registers: name, repository, base branch, port block, lanes
open now, last activity, and an "add a project" form that runs `fleet add-project`.

System groups everything about the machine: health tiles, sensors with their state (present,
absent by choice, present but not answering), the power mode control only when a systemd slice
exists to cap, the sweep timer, versions, the bind and token facts ("reads are open on loopback,
this page holds the write token"), and the prerequisites table from `/api/health`.

## 3. The API

Existing routes keep their shapes. New or changed:

| Route | Method | Returns | Access |
|---|---|---|---|
| `/api/config` | GET | `{title, features: {hq, slice, gpu, cpu_temp, ci_daemon, forge}, version}` | open |
| `/api/health` | GET | `{checks: [{id, label, state: ok|missing|error|off, detail, fix}]}` for gh, tmux, systemd user manager, linger, hq, claude, codex, nvidia-smi, temperature sensor, ci daemon, sweep timer, office reachable | read |
| `/api/projects` | GET | `[{name, repo, path, base_branch, ports: {web, api, e2e}, lanes_open, last_activity}]` | read |
| `/api/projects` | POST `{name, repo, port_base?}` | runs `fleet add-project`, returns the new row or `{error}` | mutate |
| `/api/agent/log?slug&tail=200` | GET | `{slug, lines: [...], truncated}` from the lane's log, path confined to `$FLEET_STATE/logs` | read |
| `/api/agent/msg` | POST `{slug, text}` | runs `fleet msg <slug> <text>`, returns `{ok}` | mutate |
| `/api/mail/boxes` | GET | `[{name, number, last_at, count_24h}]` from the office's `inbox` issues | read |
| `/api/mail/thread?box&since` | GET | `[{sender, at, text}]` parsed from the issue's comments, `since` ISO, never through `hq inbox` | read |
| `/api/mail/feed?hours=24` | GET | `[{at, kind: mail|claim|session, text}]` from `hq feed` | read |
| `/api/mail/who` | GET | `[{name, task, since}]` from `hq who` | read |
| `/api/mail/send` | POST `{to, text}` | `HQ_AGENT=<dashboard identity> hq msg <to> <text>`; `to` must be a known box or `all` | mutate |
| `/static/*` | GET | the front end files, path confined to `dashboard/static` | open |

Every mail route is served from a snapshot refreshed by a background thread every 45 seconds,
never on the request path, with the last good value kept when GitHub fails; a `stale_since`
field says when the snapshot last succeeded. The dashboard signs mail as the identity in
`FLEET_DASH_HQ_AGENT` (default `dashboard`), never as a name taken from the request. When `hq` is
not installed or has no config, every mail route answers `{unavailable: "<one sentence>", fix:
"<command>"}` with status 200, and the tab shows that sentence, not an error.

Write routes keep the token and cross-site rules. Read routes keep the loopback rule. `/api/config`
joins the open paths because the page needs the title and the feature flags before it can decide
what to draw.

## 4. Front end structure

No build step, no framework, no dependency. `index.html` is a shell of under a hundred lines:
the sidebar, the header, one `<main>`, the theme tokens and the module script tag.

```
dashboard/static/app.css            tokens, layout, components; one file, sectioned
dashboard/static/app.js             router, tick loop, view registry
dashboard/static/core/api.js        fetch with token, access model, error normalisation
dashboard/static/core/ui.js         h(), list diffing by key, drawer, toast, empty state, error state
dashboard/static/core/fmt.js        ago, duration, bytes, numbers with tabular digits
dashboard/static/core/identity.js   glyph and colour per code name, from /api/identities
dashboard/static/views/overview.js
dashboard/static/views/agents.js
dashboard/static/views/mail.js
dashboard/static/views/queue.js
dashboard/static/views/projects.js
dashboard/static/views/accounts.js
dashboard/static/views/system.js
```

Rendering rule: a view renders into its own root and updates in place by key, so a 3-second tick
never flickers, never loses a scroll position, never closes a drawer. A view that has never
received data shows a skeleton with the same layout; a view whose fetch failed shows the last
data with a "stale since" line, and an error card only when there was never any data.

## 5. States

Every panel has four states written down before it is built: loading, empty, error, ready.
Empty states say what the thing is and the one command that fills it. Error states name the
missing tool and the command that installs it, and never a stack trace. The rules:

- "gh is not installed, so pull request checks are unavailable. Install: sudo apt install gh"
  replaces three grey dots.
- "No GPU sensor (FLEET_NVIDIA_SMI unset). Power mode has no signal and stays on full" replaces a
  tile that silently disappears.
- "No head office configured. Run: hq init --repo <owner>/<office>" replaces an empty mail tab.
- "No projects yet. Register one: fleet add-project --name <n> --repo <owner>/<repo>" on Projects.
- "No agents yet" on Agents with the spawn command filled in with the first project's name.

## 6. Vocabulary and constants that become data

| Was | Becomes |
|---|---|
| CI lights hardcoded to backend, frontend, docker | job names from the check rollup, first four, tooltip with the rest |
| `CI_DEFAULT_STAGES` | `ci_stages` per project in `projects.toml`, default empty |
| two inline vendor logos | glyph per engine from `/api/models`, text fallback |
| `/fable/i` limit window | every window the API returns, labelled by its own name |
| 22 animal emoji and 12 colours in the page | served by `/api/identities` from `lib/identity.py`, overridable in `policy.toml [identity.glyphs]` |
| "spawn one from the orchestrator" | the spawn command, with the real project name |
| tractor and desktop icons, "your PC" | "Full", "Shared", "Background", "Paused", with one line each on what they do to the CPU share |
| "Fleet" title and tractor favicon | `FLEET_DASH_TITLE` (default "murmur") and a neutral glyph |
| catalog notes "QUOTA EXHAUSTED 08.08" | removed from the example catalog; a catalog note is the operator's, not shipped |
| `~/work/fleet` as `FLEET_HOME` default in `lib/models.py` | the checkout that `bin/fleet` resolves, passed down |
| RTX 5070 Ti and Ryzen numbers in defaults and the example | sensible generic defaults with a comment saying to measure |

`lib/ci.py`'s product-named databases and gates are out of this record: farm CI is a separate
extraction (murmur task 23) and the Queue tab shows whatever that module reports.

## 7. Delivery

Three lanes on disjoint paths, then a review, then assembly.

- **server**: `dashboard/server.py`, `dashboard/test_server.py`, `lib/identity.py`,
  `lib/metrics.py` defaults, `lib/models.py`, `config/*.example.toml`, `docs/OPERATIONS.md`
  dashboard section. Delivers every route in section 3 with tests that run without a farm
  (fixtures under a temporary `FLEET_STATE`, a fake `gh` and a fake `hq` on PATH).
- **ui**: `dashboard/index.html`, `dashboard/static/**`, `dashboard/test_stub_server.py`,
  `dashboard/test_ui.mjs`, `dashboard/test_browser.sh` and the `.mjs` browser checks. Builds
  against the stub server, which it extends to serve every route in section 3 with realistic
  fixtures including the four states.
- **docs**: `docs/QUICKSTART.md` step 9, `docs/sharp-edges.md`, `README.md` dashboard paragraph,
  and murmur `docs/12-the-machine.md` "Reaching the dashboard".

Acceptance: `python3 dashboard/test_server.py` green; `node dashboard/test_ui.mjs` green; the
browser check opens every tab against the stub in all four states and takes a screenshot of each,
and a person who has never seen the farm can say what every tab is for from the screenshot alone.

## 8. What other products taught us

Filled in from the packaging research (see the murmur plan, `internal/research/report-dashboard-packaging.md`).
