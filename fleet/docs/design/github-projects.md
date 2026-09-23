# Projects from your GitHub

Design record, 2026-09-23. The owner, looking at the Projects section of the Machine tab ("The
repositories a lane may be opened in.", then three bare fields: a name, `owner/repo`, a port
number): "make a proper flow for connecting your GitHub, proper access and the rest; what is
this nonsense".

## 1. What is wrong today

- Nothing says whether this farm is signed in to GitHub at all, as whom, or with which rights.
  A person finds out when a clone fails inside a job.
- A person must already know the exact `owner/repo` spelling and type it. Nothing lists the
  repositories they have.
- Nothing checks access before the clone: a read-only repository is registered, and the first
  lane fails at its first push.
- The port block is a raw number field that most people should never see.

## 2. The pattern

Every product that starts from a repository does the same four things (Vercel "Import Git
Repository", Railway "Deploy from GitHub repo", Netlify, Coolify): show the GitHub connection
and whose it is; list the repositories that connection can reach, with an owner switcher and a
search box; configure the few things that matter with good defaults; check, then import. This
record applies that pattern to a farm that talks to GitHub through the `gh` login the installer
already makes. No GitHub App, no OAuth app of our own, no token through the page.

**One login, many agents.** Every agent on the farm, the head office and the dashboard act as
the one account `gh` is signed in as, and they share its GitHub API allowance (5,000 calls an
hour, already spent to zero by polling once). Everything below is built to spend almost none of
it.

## 3. The GitHub connection

A strip at the top of the Projects section. Each state is one line, in words about what agents
can do, with the technical detail in the tooltip:

- **Connected**: "Signed in as @login. Agents can copy, push and change CI files in every
  repository this account can reach." Tooltip: the scopes. A second line: "This login can write
  to the head office <owner/office>" (or cannot, with the reason), reusing the head office check
  the dashboard already has. Actions: Re-check.
- **A scope is missing**: warning, what agents cannot do in words ("Agents cannot change CI
  workflow files"), and a Copy button for `ssh -t <farm> gh auth refresh -h github.com -s
  workflow`.
- **Git does not use the login**: warning, Copy for `ssh -t <farm> gh auth setup-git`.
- **Two identities**: `GH_TOKEN` or `GITHUB_TOKEN` is set in `~/.config/fleet/env`: the daemon,
  the sweep and the queue runner load that file and the dashboard and the lanes do not, so the
  farm would act as two accounts. A warning names the file and the line to remove.
- **Not connected** (gh reports no account at all): "GitHub is not connected on this farm" and a
  Connect GitHub button. The dialog says first "Every agent on this farm will act as this
  account", then: copy `ssh -t <farm> gh auth login -h github.com -p https --web -s
  workflow` and answer Yes when it asks to authenticate Git with your GitHub credentials
  (`gh auth setup-git` is the fallback). `-s` adds to gh's own defaults (repo, read:org, gist).
  The state flips by itself (section 6: the server notices the login from a local file, not by
  asking GitHub).
- **Connected, and someone wants another account**: no Connect button. A "Switch account" link
  explains first that every agent and the head office will act as the new account, then shows
  `gh auth switch`.
- **No gh on this farm** and **no answer** are their own states, never drawn as "not
  connected".

The login itself happens in the person's terminal, by GitHub's own device flow; the page never
sees a token. Required scopes: `repo` and `workflow`; `read:org` lists organization
repositories.

## 4. Import a repository

The section's head button "Import a repository" opens a dialog in the same numbered-step pattern
as Add a machine and Add a model:

1. **Choose.** An owner select (built from the owners in the repository list: you first, then
   each organization), a search box, and the repositories sorted by last push, at most eight
   rows visible with the list scrolling inside the dialog. Each row is one line: name, a Private
   or Public pill, your role as a pill (Admin; Write, which includes maintain; Read, which
   includes triage), "pushed 3 days ago", and an Import button. A row you can only read, an
   archived row, or a repository already registered says why on its disabled button ("Read
   only: agents need write", "Archived", "Already a project"). Under the list: "Not in the list?
   Paste its address" (accepts `owner/repo`, a `https://github.com/...` URL or
   `git@github.com:owner/repo.git`) and one line for the common cause: "An organization can hide
   its private repositories until it approves the GitHub CLI app, or until you authorize it for
   single sign-on" with a link to
   `https://github.com/settings/connections/applications/178c6fc778ccc68e1d6a`.
2. **Configure.** Project name, prefilled from the repository name (cut to 40 characters, the
   registry's limit) and validated; "Copied to ~/work/<name> on this farm"; base branch: the
   default branch, then the protected branches, then "type another name" (repositories worked by
   agents have hundreds of branches, so the full list is never drawn); ports as a sentence
   ("Ports 5300 to 5302, the next free block") with a Change link that reveals the number field.
3. **Check.** A checklist, each line a pill and a sentence, run by the server on request:
   signed in; your role allows a push (the pill is the account's role, not a guarantee: the
   first push is the final proof, and the sentence says so); git on this farm uses your login,
   proved with `git ls-remote` of this repository (costs no API call); the token can change
   workflow files (a warning, not a stop); the repository is not archived; the base branch
   exists; and when `~/work/<name>` already exists, its `origin` is this repository (a different
   one fails; an SSH remote is checked with `ssh -T git@github.com`, which names the account the
   farm's key belongs to, and a different account from the `gh` login is a warning). Import is
   enabled when nothing fails.
4. **Import.** The clone runs as a job (it already does); the dialog shows it running and
   closes to the table, where the new row appears when the clone ends.

## 5. The table

Six columns, every cell one line, cut with an ellipsis and the full text in the tooltip (the
owner's table rule): Project (its ports in the tooltip), Repository (a link to GitHub, with a
Private or Public pill), Your access (Admin, Write, Read, or No access), Base branch, Lanes open,
Actions (Open on GitHub, Remove). Remove's confirmation says the folder on the farm and the
repository on GitHub both stay.

**No access** comes only from a definite answer: a registered repository missing from the list
gets one `repos/<owner>/<name>` call, and a 404 or 403 there is No access; a listing that failed
or was cut short changes nothing. A No access row says the two ways out in its tooltip: grant
this account access on GitHub, or Remove the project. The strip counts such rows.

Empty states: not connected ("Connect GitHub first", with the Connect button) and connected with
no project ("Import your first repository", with the Import button).

## 6. Routes

Read, from a snapshot a background thread keeps (no GET runs a tool):

| Route | Answer |
|---|---|
| `GET /api/github` | `{at, stale_since, error, pending, login_state, login, scopes, missing_scopes, git_uses_login, two_identities, office: {repo, writable, detail}, owners, rate_remaining, commands: {login, refresh_scopes, setup_git, switch}}` |

`login_state` is `connected`, `not_connected`, `no_gh` or `no_answer`. `missing_scopes` lists
only the required scopes (`repo`, `workflow`) the token lacks. `owners` comes from the
repository list, so there is no separate organizations call.

**What the snapshot costs.** A pass runs every five minutes and makes three kinds of call:
`gh auth status --active -h github.com` (only the active account; the plain command asks GitHub
about every account gh knows), `gh api -i user`, and the repository list
`user/repos?affiliation=owner,collaborator,organization_member&sort=pushed&per_page=100`,
following `Link: rel="next"` up to five pages. The `X-RateLimit-Remaining` header of the first
`-i` call decides the rest: under 1,000, the pass keeps its last good answer and sets
`stale_since` instead of spending more. Between passes the server watches the modification time
of gh's own `hosts.yml` (a local file, no GitHub call, the way account logins are watched) and
runs one pass when it changes: that is how the Connect dialog's state flips by itself, while the
page re-reads `GET /api/github` every 3 seconds.

**What the snapshot keeps.** The scopes are read from the `X-OAuth-Scopes` header, whatever its
case: absent means a fine-grained or app token (`scopes: null`, and the page says "scopes cannot
be read for this kind of token; the access check still applies"); present and empty means a
classic token with no scopes (`[]`, repo missing). Only parsed values reach the snapshot or its
`error`; raw header text never does (headers can carry an `X-GitHub-SSO` URL). No code here ever
runs `gh auth token`, `git credential fill` or anything with `--show-token`: each prints the
token. The fake `gh` in the tests fails the test if it is asked to.

`GET /api/projects` rows gain `visibility`, `permission` (`admin`, `write`, `read`, `no_access`,
or `null` when not connected) and `html_url`, from the same snapshot.

Write, behind the token and the cross-site refusal:

| Route | Does |
|---|---|
| `POST /api/github/check` | one pass now; one at a time, and within 60 seconds of the last it answers 429 with `retry_after`, like the accounts refresh |
| `POST /api/github/repos {owner?, q?}` | the repositories from the snapshot's list, filtered in memory (owner login, case-insensitive name substring): `{repos: [{full_name, owner, name, private, archived, fork, default_branch, permission, pushed_at, description, registered}], truncated}` |
| `POST /api/github/branches {repo}` | `{default_branch, protected: [name...]}` from `repos/<r>` and `repos/<r>/branches?protected=true` |
| `POST /api/github/access {repo, branch, name}` | `{checks: [{id, state: ok|warn|fail, sentence, fix}]}` |
| `POST /api/projects {name, repo, branch?, port_base?}` | as today, plus `branch` passed to `fleet add-project --branch` |

These are POST because they call GitHub or git, and only a page that can import needs them.
Every call is an argv list with a timeout, through REST (`gh api`). (Other parts of the
dashboard, the queue's pull request reader and the mail reader, still use GraphQL; this record
adds none.)

**Input rules.** `repo` is reduced from a URL only when the host is exactly `github.com`
(`https://github.com/o/r`, with or without `.git` and a trailing slash, or `git@github.com:o/r.git`)
and then must pass the registry's existing repository pattern. `branch` must pass `git
check-ref-format --branch`, must not start with `-`, and must be the default branch, a protected
branch or a name `git ls-remote` finds; inside an API path it is encoded with `quote(safe="")`.
`owner` and `q` only filter the list in memory and never reach an argv.

## 7. Delivery

Two lanes, the JSON of section 6 as their contract. Other lanes are changing `server.py`,
`machine.js` and the stub at the same time, so each lane keeps its code in files of its own:

- **github-server**: `fleet/dashboard/github_access.py` (new: the snapshot, the watcher, the
  routes' bodies), `fleet/dashboard/test_github_access.py` (new, with a fake `gh` that answers
  `auth status`, `api -i user` with rate headers, the paged list, `repos/<r>`,
  `repos/<r>/branches?protected=true`, and refuses `auth token` and `--show-token`, plus fake
  `git` for `ls-remote` and `config`, and a fake `ssh` for `-T`), and in `server.py` only: one
  import, one `startswith("/api/github")` branch at the top of the GET chain and of the POST
  chain, one call that adds the three fields to `/api/projects` rows, one start line next to the
  other refreshers. `fleet/docs/OPERATIONS.md`: the routes.
- **github-ui**: the Projects section moves from `machine.js` to
  `fleet/dashboard/static/views/projects.js` (new; `machine.js` keeps one import and one call,
  and exports the helpers both need), `fleet/dashboard/static/projects.css`,
  `fleet/dashboard/index.html` (the link), `fleet/dashboard/stub_github.py` (new: the routes of
  section 6 in five states; `test_stub_server.py` gains one dispatch line),
  `fleet/dashboard/test_hostile_projects.mjs`, `fleet/dashboard/test_screens_projects.mjs`.

Out of scope: a GitHub App; creating a repository from the page; per-project deploy keys;
refusing new lanes in a No access project (a follow-up in `fleet spawn`); GitLab and Bitbucket.

## 8. Review

An independent reviewer returned RED with twelve findings; all are folded in above: no polling
of GitHub (the local file watcher and a 60 second cooldown), a cheaper snapshot that stops under
1,000 calls left, the scopes header read case-insensitively with raw headers never kept, the
multi-account warning, the git proof by `ls-remote`, input rules for `branch` and URLs, role
pills that say what they are, No access only from a definite answer, an existing folder or SSH
remote checked, the head office and two-identity lines, plain words and six columns, and each
lane's code in files of its own.
