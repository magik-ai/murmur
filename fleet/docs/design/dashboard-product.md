# The dashboard as a product

This design record explains the parts of the fleet dashboard that every tab shares: what the
dashboard is for, how the page is laid out, how the server answers, how the front end is built,
what a panel says when something is missing, and which values come from data. The dashboard has
three tabs, Board, Mail and Machine. [`dashboard-v2.md`](dashboard-v2.md) describes each tab.

Words used below. A **farm** is an always-on Linux machine that runs coding agents. A **lane** is
one agent doing one task on its own branch. The **head office** is a private GitHub repository the
agents use for names, branch claims and messages; `hq` is its command line tool. The
[glossary](../../../docs/00-start-here.md#words-this-handbook-uses) has the rest.

## 1. Intent and boundaries

A person running a farm must be able to answer five questions without a terminal:

- What is running?
- What is waiting on me?
- Is the machine healthy?
- What did the agents say to each other?
- What is missing or misconfigured?

The page is for someone who has just installed murmur, not only for the person who built the
farm. So nothing on it may assume one farm's machines, projects or vocabulary.

Two limits hold everywhere:

- The dashboard does not spawn agents. Spawning spends money and needs an identity, and both
  belong to a named session in a terminal.
- The dashboard is not a second store. Every panel reads a source that exists without it: lane
  records, the project registry, the head office, systemd, the account files.

Out of scope: users and roles, spawning from the browser, a mail store on the farm, and
translations.

## 2. Information architecture

A left sidebar holds the product name and the three tabs. It collapses to icons under 900 px and
moves to a bar across the top under 600 px. The page opens on the Board.

The header is the same on every tab. From left to right:

- the farm's state: Farm on, Farm paused or Farm off, with the reason on hover;
- a capacity pill, only when there is no room for another agent;
- the sweep countdown;
- a freshness note, only when something on screen is an old answer;
- the project filter, which narrows the Board's agents;
- the power setting, only on a machine with a systemd slice to cap;
- Search, which opens the jump palette (Cmd+K or Ctrl+K);
- the theme switch: system, light or dark.

| Tab | Answers | Main routes it reads |
|---|---|---|
| Board | who is running, on what and how far; is the machine healthy; how much subscription is left | `/api/fleet`, `/api/agent`, `/api/agent/log`, `/api/metrics`, `/api/accounts`, `/api/health`, `/api/projects` |
| Mail | what the agents said to each other | `/api/mail/boxes`, `/api/mail/thread`, `/api/mail/feed`, `/api/mail/who` |
| Machine | is the farm set up and complete, and how do I change it | `/api/mode`, `/api/services`, `/api/hosts`, `/api/machines`, `/api/accounts`, `/api/accounts/login-state`, `/api/engines`, `/api/projects`, `/api/projects/next-port`, `/api/github`, `/api/health`, `/api/metrics` |

Every tab also reads `/api/config`, `/api/access`, `/api/identities`, `/api/health`,
`/api/metrics`, `/api/mode`, `/api/mail/boxes`, `/api/version`, `/api/sweep` and `/api/services`,
because the header and the jump palette need them.

## 3. The API

The server is `fleet/dashboard/server.py`, with `github_access.py` beside it and helpers from
`fleet/lib/`. It uses only Python's standard library, and every answer is JSON. The route table in
[`OPERATIONS.md`](../OPERATIONS.md) lists every route. This section holds the rules all routes
share, and the routes the shared parts of the page read.

**Access.** There are three levels:

- *open*: served without a token on any bind. These are the page, its files under `/static/`,
  `/api/access`, `/api/version` and `/api/config`. The page needs them before it can do anything,
  and the token arrives in the page's own address.
- *read*: open while the server is bound to loopback (the default, `127.0.0.1`). Once
  `FLEET_DASH_BIND` is wider, a read needs the bearer token too.
- *write*: every POST needs the bearer token, on any bind. A request whose `Origin` or
  `Sec-Fetch-Site` header says it came from another site is refused, whatever token it carries.

On a loopback bind, a request is refused at every level unless its `Host` header is `localhost`
or a loopback address. So a website cannot reach the board through DNS rebinding.

**No read runs a tool.** A GET is answered from memory. Background threads read the machine and
the head office on their own clock and keep snapshots. The page asks again every 3 seconds, so a
tool call on a read path would run 1,200 times an hour for each open page. A snapshot answer
carries `at`, `stale_since`, `error` and `pending`. `pending` is true until the first pass has
run. A failed pass keeps the last good values, and `stale_since` says since when they are old.

| Route | Method | Answers | Access |
|---|---|---|---|
| `/api/config` | GET | `{title, version, features: {hq, slice, gpu, cpu_temp, forge, health_panel}, hq_agent, hosting, farm_alias, pending}`: the page's name and which optional parts this farm has | open |
| `/api/health` | GET | `{at, stale_since, error, pending, checks: [{id, label, state, detail, fix}]}`, where `state` is `ok`, `missing`, `error` or `off`; one check each, in this order, for gh, tmux, the systemd user manager, linger, hq, claude, codex, the GPU sensor, the CPU temperature sensor, the sweep timer, and whether the head office answers | read |
| `/api/projects` | GET | `[{name, repo, path, base_branch, ports: {web, api, e2e}, lanes_open, last_activity, visibility, permission, html_url}]` from `projects.toml` and the lane records; the last three come from the GitHub snapshot ([`github-projects.md`](github-projects.md) section 6) | read |
| `/api/projects` | POST `{name, repo, branch?, port_base?}` | runs `fleet add-project` as a job, because it clones the repository: `202 {job, name, repo, port_base, sentence}` | write |
| `/api/agent/log?slug&tail=200` | GET | `{slug, file, lines: [...], truncated, missing}`: the lane's log as readable lines, at most 2000, with the path confined to `$FLEET_STATE/logs` | read |
| `/api/agent/msg` | POST `{slug, text}` | runs `fleet msg <slug> <text>`, which the lane reads at its next checkpoint: `{ok, slug, detail}` | write |
| `/api/mail/boxes` | GET | `{..., boxes: [{name, number, numbers, updated_at, last_at, count_24h}]}` from the head office's `inbox` issues, one row per name | read |
| `/api/mail/thread?box&since` | GET | `{..., box, messages: [{sender, at, text, created_at}], window_hours}`, read from the issue's comments; `since` is ISO 8601 | read |
| `/api/mail/feed?hours=24` | GET | `{..., events: [{at, at_label, kind, text}], hours}`, where `kind` is `mail`, `claim` or `session`: branch claims first, then newest first, assembled here from the threads, `hq who` and `hq claims`, never by running `hq feed` | read |
| `/api/mail/who` | GET | `{..., sessions: [{name, state, age_hours, since, task}]}` from `hq who`, where `state` is `live` or `stale` | read |
| `/api/mail/send` | POST `{to, text}` | runs `hq msg -- <to> <text>` with `HQ_AGENT` set to the dashboard's own name; `to` must be a known conversation or `all` | write |
| `/static/*` | GET | the front end files, with the path confined to `dashboard/static` | open |

In the mail rows, `...` stands for the four snapshot fields.

The mail routes read a snapshot of the head office that the server refreshes every 45 seconds.
When GitHub fails, the last good snapshot stays and `stale_since` says since when. A mailbox
whose issue has not changed since the last pass is not read again. After a send, the server wakes
its refresher, so the message shows in seconds instead of at the next pass.

The dashboard signs mail as `FLEET_DASH_HQ_AGENT` (default `dashboard`), never as a name taken
from the request. Sending to a name that has no mailbox would create one, so `to` must already
exist, and a send before the first read of the office is refused with 503. When `hq` is not
installed, has no office configured, or `gh` is missing, every mail route answers
`{unavailable: "<one sentence>", fix: "<command>"}` with status 200. The Mail tab then shows that
sentence and that command, not an error.

## 4. Front end structure

No build step, no framework and no JavaScript dependency. `index.html` is a shell of under a
hundred lines: the sidebar, the header, one `<main>`, the drawer, the jump palette, a short inline
script that applies the stored theme before the first paint, and the module script tag.

```text
dashboard/static/app.css             tokens, layout, components; one file, in sections
dashboard/static/app.js              router, 3 second tick, view registry, header, jump palette
dashboard/static/core/api.js         fetch with the token, the access model, errors as sentences
dashboard/static/core/ui.js          h(), update in place by key, drawer, toast, panel states
dashboard/static/core/fmt.js         times, durations, sizes, money and numbers, one way each
dashboard/static/core/identity.js    glyph and colour per code name, from /api/identities
dashboard/static/views/board.js      the Board tab
dashboard/static/views/agents.js     the Board's agents pane and the lane drawer
dashboard/static/views/mail.js       the Mail tab
dashboard/static/views/machine.js    the Machine tab: Power, Services, Accounts, Health
dashboard/static/views/hosting.js    its Hosting section (hosting.md)
dashboard/static/views/models.js     its Models section (models-providers.md)
dashboard/static/views/projects.js   its Projects section (github-projects.md)
```

The Machine tab and its sections have stylesheets of their own next to `app.css`:
`machine.css`, `hosting.css`, `models.css` and `projects.css`.

**Rendering rule.** A view renders into its own root and updates in place by key. So the 3 second
tick never flickers, never moves a scroll position, never closes a drawer and never wipes
half-typed text. A panel that has never had an answer shows a skeleton in the same layout. A panel
whose request failed keeps the last answer, with a line that says when it was from. It shows an
error card only when there was never an answer.

## 5. States

Every panel has four states, decided in one place (`panel()` in `core/ui.js`): loading, empty,
error and ready. A snapshot that says `pending` is drawn as loading, never as an error. An old
answer is still drawn, with one line that says when it was true.

- **Empty** says what the thing is, and gives the command that fills it.
- **Error** names the missing tool and the command that installs it. Never a stack trace.

Examples of what the page says:

- The Health table's row for gh, when gh is missing: "pull request checks and the head office both
  read through gh", with the fix "install the GitHub CLI: https://cli.github.com".
- A graphics card sensor that is not set up is a tile that says "Not configured" and "Power mode
  has no signal from it and stays on full". It is never a tile that silently disappears.
- Mail with no head office: "No head office configured, so there is no agent mail to show.", with
  the command `hq init --repo <owner>/<office>`.
- A farm where no agent has ever run: the Board becomes the setup checklist plus the commands that
  produce the first agent. The spawn command carries the first registered project's name.
- A Machine section whose server is older than the page: "The page and the server are different
  versions", with `fleet update && fleet dashboard restart`.

## 6. Vocabulary and data, not constants

Nothing on the page is written for one farm. Where a value differs between farms, it comes from
data:

| What | Where it comes from |
|---|---|
| Check names on a lane's change | every check in the pull request's check rollup, under its own name; the first four are drawn, the rest are in the tooltip |
| Engine marks | a mark for `claude` and `codex`; any other engine is named in words |
| Subscription windows | every window the account reader returns, labelled by its own name |
| Code-name glyphs and colours | `/api/identities`, from `fleet/lib/identity.py`; a farm sets its own in `policy.toml` under `[identity]` (`glyphs`, `colours`) |
| The first spawn command | written with the first registered project's real name |
| Power settings | the words Full, Shared, Background, Paused and Automatic, each with one line on what it does to the agents' share of the machine |
| Product name | `FLEET_DASH_TITLE`, default `murmur`; the tab icon is the murmur mark |
| Notes in the model catalog | none in the shipped example; a note about what a plan is doing today belongs in the farm's own `models.toml` |
| Where fleet is installed | the checkout the code runs from, or the `FLEET_HOME` that `bin/fleet` passes down |
| Machine limits | generic starting points in `fleet/lib/metrics.py`, with a comment that says to measure your own machine and set them in `policy.toml` |

## 7. Where the code lives and how it is checked

- **Server**: `fleet/dashboard/server.py`, with `fleet/dashboard/github_access.py` for the GitHub
  routes. `test_server.py` and `test_github_access.py` test them without a farm, with temporary
  state directories and fake `gh`, `hq`, `git`, `systemctl` and other tools on `PATH`.
- **Page**: `fleet/dashboard/index.html` and `fleet/dashboard/static/`. It is built and checked
  against a stub server, `test_stub_server.py` (with `stub_github.py` and `stub_models.py`). The
  stub serves every route the page reads, in five states: ready, empty, error, loading and quiet.
- **Checks**: `test_ui.mjs` checks the page's shape, every module and every route shape without a
  browser. `test_browser.sh` runs every `test_hostile*.mjs` and `test_screens*.mjs` in a real
  browser. The screenshot checks open every tab in every stub state, at a desktop width and a
  phone width.

```bash
cd fleet
python3 dashboard/test_server.py
python3 dashboard/test_github_access.py
node dashboard/test_ui.mjs
dashboard/test_browser.sh
```

The bar for the screenshots: a person who has never seen the farm can say what each tab is for
from its screenshot alone.

## 8. Design rules

These rules came from looking at similar tools: deployment dashboards, monitoring pages, issue
trackers and other coding-agent runners.

- **One constant shell.** The sidebar and the header are the same on every tab, so a tab switch
  never feels like a new app.
- **A flat list of agents.** A farm is one pool, so the agents are one list with a project
  filter, not a tree of projects.
- **Five status meanings only**: Running, Waiting on a person, Failed, Done and Paused. Every raw
  status maps to one of them. A status is a neutral pill with a coloured dot, never a coloured
  row. The colours are defined in OKLCH, a perceptually even colour space, with an sRGB fallback,
  so every state reads equally strong.
- **Say when an answer is old.** The header says nothing while every panel is fresh. When
  something on screen is an old answer, it says "Stale since" and the time. A panel that shows a
  kept copy says so in one line.
- **Skeletons, not spinners.** Value changes animate in under 300 ms. Lists update in place by
  key.
- **A first run is a checklist** with the exact commands, not an empty table. Every panel has its
  own empty state.
- **Talking to a running agent happens on the agent**, in a composer in its drawer. The office's
  mail is a separate list-and-thread view. The two look different, so a live instruction is never
  confused with the mail log.
- **Cost and tokens are shown per agent**: on its card, in the table and in its drawer.
- **A jump palette** (Cmd+K or Ctrl+K) goes to a tab, an agent, a project or a conversation.
