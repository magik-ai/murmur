# Projects from your GitHub

This design record explains the Projects section of the dashboard's Machine tab: how the page
shows the farm's GitHub connection, how you import a repository as a project, and the routes
behind both.

Words used below. A **farm** is an always-on Linux machine that runs coding agents. A **lane** is
one agent doing one task on its own branch. A **project** is a repository registered in the farm's
`projects.toml`; a lane can only be opened in a registered project. The **head office** is a
private GitHub repository the agents use for names, branch claims and messages.

## 1. The problem

Three bare fields (a name, `owner/repo` and a port number) are not enough to register a project.
A person needs answers that those fields cannot give:

- Is this farm signed in to GitHub at all, as whom, and with which rights? Without that, a person
  finds out when a clone fails inside a job.
- Which repositories can this login reach? A person should not have to know and type the exact
  `owner/repo`.
- Can the agents push there? A read-only repository must be caught before the clone, not when the
  first lane fails at its first push.
- Which ports does the project get? Most people should never see the port number.

## 2. The pattern

Hosting products that start from a repository, such as Vercel, Netlify, Railway and Coolify, do
the same four things. They show the GitHub connection and whose it is. They list the repositories
that connection can reach, with an owner switcher and a search box. They ask for the few settings
that matter, with good defaults. They check, then import.

This record applies that pattern to a farm that reaches GitHub through the `gh` login the
installer sets up. There is no GitHub App, no OAuth app of our own, and no token through the page.

**One login, many agents.** Every agent on the farm, the head office and the dashboard act as the
same account: the account `gh` is signed in as. They share that account's GitHub API allowance of
5,000 calls an hour. Everything below is built to spend almost none of it.

## 3. The GitHub connection

A strip at the top of the Projects section. Each state is one line, in words about what the
agents can do, with the technical detail in the tooltip:

- **Connected**: "Signed in as @login. Agents can copy, push and change CI files in every
  repository this account can reach." The tooltip lists the scopes. A second line says whether
  this login can write to the head office that `hq` is configured with, for example "This login
  can write to the head office acme/office." Actions: Re-check, and a "Switch account" link.
- **A scope is missing**: a warning that says what the agents cannot do ("Agents cannot change
  CI workflow files"), and a button that copies
  `ssh -t <farm> gh auth refresh -h github.com -s workflow`.
- **Git does not use the login**: a warning, and a button that copies
  `ssh -t <farm> gh auth setup-git`.
- **Two identities**: `GH_TOKEN` or `GITHUB_TOKEN` is set in `~/.config/fleet/env`. The farm's
  systemd services load that file and the lanes do not, so the farm would act as two accounts. The
  warning names the file and the line to remove.
- **Not connected** (gh reports no account at all): "GitHub is not connected on this farm." and a
  Connect GitHub button. The dialog first says "Every agent on this farm will act as this
  account." Then it gives `ssh -t <farm> gh auth login -h github.com -p https --web -s workflow`
  to run in your own terminal, and tells you to answer Yes when gh asks to authenticate Git with
  your GitHub credentials (`gh auth setup-git` is the fallback). `-s` adds to gh's own default
  scopes (repo, read:org, gist). The state flips by itself (section 6).
- **Connected, and you want another account**: there is no Connect button. The "Switch account"
  link first explains that every agent and the head office will act as the new account. Then it
  shows `gh auth switch`, and the login command for an account gh does not know yet.
- **No gh on this farm** and **no answer from gh** are states of their own, never drawn as "not
  connected".

The login happens in your own terminal, through GitHub's device flow, so the page never sees a
token. The required scopes are `repo` and `workflow`.

## 4. Import a repository

The section's "Import a repository" button opens a dialog in the drawer. It has numbered steps,
like "Add a machine" in the Hosting section and "Add a provider" in the Models section:

1. **Choose.** An owner select (you first, then every other owner in your repository list), a
   search box, and the repositories sorted by last push. At most eight rows are visible, and the
   list scrolls inside the dialog. Each row is one line: the name, a private or public tag, your
   role as a pill (Admin; Write, which includes maintain; Read, which includes triage), when it
   was last pushed ("pushed 3 days ago"), and an Import button. The button is switched off, and
   says why, for a repository you can only read ("Read only: agents need write"), an archived one
   ("Archived"), or one that is already a project ("Already a project"). Under the list, "Not in the list? Paste its address"
   takes `owner/repo`, a `https://github.com/...` address or `git@github.com:owner/repo.git`. One
   line names the common reason a repository is missing: "An organization can hide its private
   repositories until it approves the GitHub CLI app, or until you authorize it for single
   sign-on". It links to
   `https://github.com/settings/connections/applications/178c6fc778ccc68e1d6a`.
2. **Configure.** The project name is filled in from the repository name, cut to 40 characters
   (the registry's limit), and checked when you go on. Under it: "Copied to ~/work/name on this
   farm", with the name you typed. The base branch select offers the default branch, then the
   protected branches, then "Type another name". A repository worked by agents has hundreds of
   branches, so the full list is never drawn. The ports are one sentence ("Ports 5300 to 5399, the
   next free block.") with a Change link that shows the number field.
3. **Check.** On request, the server runs a checklist. Each line is a pill and a sentence:
   - signed in;
   - your role allows a push. The pill is the account's role, not a guarantee: the first push is
     the final proof, and the sentence says so;
   - git on this farm reaches the repository with your login, proved with `git ls-remote`, which
     costs no API call. A public repository answers anybody, so for one the check is that git
     hands GitHub your gh login;
   - the token can change workflow files (a warning, not a stop);
   - the repository is not archived;
   - the base branch exists;
   - when `~/work/<name>` already exists, its `origin` is this repository. A different one fails.
     For an SSH remote, `ssh -T git@github.com` names the account the farm's key belongs to, and
     an account other than the `gh` login is a warning.

   Import is switched on when no line fails.
4. **Import.** The clone runs as a job. The dialog shows it running and closes to the table, where
   the new row appears when the clone ends.

A token typed or pasted by mistake into any field of the dialog is refused before any request is
sent.

## 5. The table

Six columns. Every cell is one line, cut with an ellipsis, with the full text in the tooltip:

| Column | Shows |
|---|---|
| Project | the name; the tooltip adds the ports, the folder, the base branch and the open lanes |
| Repository | a link to GitHub, with a private or public tag |
| Your access | Admin, Write, Read or No access |
| Base branch | the branch the project's lanes start from |
| Lanes open | how many lanes are open in the project now |
| Actions | a GitHub button that opens the repository, and Remove |

Remove asks first. Its confirm says that the folder on the farm and the repository on GitHub both
stay, and which port block becomes free. It is refused while a lane is open in the project.

**No access** comes only from a definite answer. A registered repository that is missing from the
list gets one `repos/<owner>/<name>` call, and a 404 or 403 there means No access. A listing that
failed or was cut short changes nothing. A No access row gives the two ways out in its tooltip:
grant this account access on GitHub, or remove the project. The strip counts such rows.

Two empty states: when GitHub is not connected, "Connect GitHub first" with the Connect button;
when it is connected and there is no project yet, "Import your first repository" with the Import
button.

## 6. Routes

Read, from a snapshot a background thread keeps (no GET runs a tool):

| Route | Answer |
|---|---|
| `GET /api/github` | `{at, stale_since, error, pending, checking, login_state, login, account_read, scopes, missing_scopes, git_uses_login, two_identities, office: {repo, writable, detail}, owners, rate_remaining, commands: {login, refresh_scopes, setup_git, switch}}` |

`login_state` is `connected`, `not_connected`, `no_gh` or `no_answer`. `pending` is true only
until the first pass has answered.
`checking` is true while any pass runs or waits to run: a page that pressed Re-check reads until
it clears.
`account_read` is false until GitHub has answered about the signed-in account: until then, what it
may do is not known.
`missing_scopes` lists only the required scopes (`repo`, `workflow`) the token lacks. `owners`
comes from the repository list, so there is no separate call for organizations. `two_identities`
is `null`, or `{file, line, variable}` for the line to remove.

**What the snapshot costs.** A pass runs every five minutes and makes these calls:

- `gh auth status --active -h github.com`: only the active account, because the plain command
  asks GitHub about every account gh knows;
- `gh api -i user`;
- the repository list,
  `user/repos?affiliation=owner,collaborator,organization_member&sort=pushed&per_page=100`,
  following `Link: rel="next"` up to five pages;
- one `repos/<owner>/<name>` call for the head office when it is not in the list, and one for
  each registered repository the list does not have. That is at most 20 a pass, and a definite
  answer is kept for an hour unless gh's login file changes or someone presses Re-check.

The `X-RateLimit-Remaining` header of the first `-i` call decides the rest. Under 1,000, the pass
keeps its last good answer and sets `stale_since` instead of spending more.

Between passes, the server checks every two seconds whether gh's own `hosts.yml` has a new
modification time. That is a local file, so the check costs no GitHub call, and a change runs one
pass at once. That is how the Connect dialog's state flips by itself: while it waits, the dialog
re-reads `GET /api/github` every 3 seconds. Otherwise the page reads it when the Machine tab opens
and then once a minute.

**What the snapshot keeps.** The scopes are read from the `X-OAuth-Scopes` header, whatever its
case. An absent header means a fine-grained or app token (`scopes: null`), and the page says "The
scopes cannot be read for this kind of token; the access check still applies." A header that is
present and empty means a classic token with no scopes (`[]`, so `repo` is missing). Only parsed
values reach the snapshot or its `error`. Raw header text never does, because headers can carry
an `X-GitHub-SSO` address. No code here runs `gh auth token`, `git credential fill` or anything
with `--show-token`, because each of them prints the token. The fake `gh` in the tests fails the
test if it is asked to.

`GET /api/projects` rows gain `visibility`, `permission` (`admin`, `write`, `read`, `no_access`,
or `null` when not connected or not known yet) and `html_url`, from the same snapshot.

Write, behind the token and the cross-site refusal:

| Route | Does |
|---|---|
| `POST /api/github/check` | one pass now, in the background: `202 {ok, checking: true, retry_after, detail}`; one at a time (409 while a pass runs), and within 60 seconds of the last it answers 429 with `retry_after`, like the accounts refresh |
| `POST /api/github/repos {owner?, q?}` | the repositories from the snapshot's list, filtered in memory by owner login and by a case-insensitive name substring: `{repos: [{full_name, owner, name, private, archived, fork, default_branch, permission, pushed_at, description, registered}], truncated, pending, at, error, sso_help}` |
| `POST /api/github/branches {repo}` | `{repo, default_branch, protected: [name...]}` from `repos/<r>` and `repos/<r>/branches?protected=true&per_page=100` |
| `POST /api/github/access {repo, branch, name}` | the checks of section 4, step 3: `{repo, branch, name, checks: [{id, state, sentence, fix}], importable}`, where `state` is `ok`, `warn` or `fail`, and the ids are `signed_in`, `role`, `git_login`, `workflow_scope`, `not_archived`, `base_branch` and `folder` |
| `POST /api/projects {name, repo, branch?, port_base?}` | as in `dashboard-product.md` section 3, plus `branch`, passed to `fleet add-project --branch` once it passes the input rules below and `git ls-remote` finds it |

These are POST routes behind the token because only a page that can import needs them. `check`,
`branches` and `access` call GitHub or git when pressed; `repos` only filters the snapshot in
memory. Every call is an argv list with a timeout, and every GitHub call goes through REST
(`gh api`). The Board's check reader (`gh pr view`) and the mail reader (`gh issue list`) go
through GitHub's GraphQL API; this record adds no GraphQL call.

**Input rules.** `repo` is reduced from an address only when the host is exactly `github.com`
(`https://github.com/o/r`, with or without `.git` and a trailing slash, or
`git@github.com:o/r.git`), and the result must pass the registry's repository pattern. `branch`
must pass `git check-ref-format --branch`, must not start with `-`, and must exist: it is the
default branch, or `git ls-remote` finds it. Inside an API path, the owner and the name are each
encoded with `quote(safe="")`. `owner` and `q` only filter the list in memory and never reach an
argv.

## 7. Where the code lives

The JSON of section 6 is the contract between the server and the page. Each side keeps its code
in files of its own, so the Projects section can change without touching the rest of the
dashboard:

- **Server.** `fleet/dashboard/github_access.py` holds the snapshot, the `hosts.yml` watcher and
  the routes' bodies. `server.py` uses it in a few places only: one `/api/github` branch at the
  top of the GET chain and one at the top of the POST chain, one call that adds the three fields
  to the `/api/projects` rows, the branch checks of `POST /api/projects`, and one line that starts
  the refresher next to the others.
  `fleet/dashboard/test_github_access.py` tests it with a fake `gh` (it answers `auth status`,
  `api -i user` with rate headers, the paged list, `repos/<r>` and
  `repos/<r>/branches?protected=true`, and fails the test on `auth token` or `--show-token`), a
  fake `git` for `ls-remote` and `config`, and a fake `ssh` for `-T`. It also checks that the
  routes table in section 6 matches what the server sends, key for key.
- **Page.** The Projects section is `fleet/dashboard/static/views/projects.js`. It is a section of
  the Machine tab, not a tab of its own: `machine.js` imports it, calls it once, and exports the
  helpers both files need. Its styles are `fleet/dashboard/static/projects.css`, linked from
  `fleet/dashboard/index.html`. `fleet/dashboard/stub_github.py` serves the routes of section 6
  to the browser checks, in the stub's five states and in every strip state
  (`test_stub_server.py` hands those routes to it). The browser checks are
  `fleet/dashboard/test_hostile_projects.mjs` and `fleet/dashboard/test_screens_projects.mjs`.

Out of scope: a GitHub App; creating a repository from the page; a deploy key per project;
stopping `fleet spawn` from opening a lane in a No access project; GitLab and Bitbucket.

## 8. What this design guards against

- **Spending the shared allowance.** Nothing asks GitHub on a page read: a pass every five
  minutes, a local file watch for new logins, and a 60 second rest between presses of Re-check.
- **Running dry.** The snapshot stops spending under 1,000 calls left, and keeps its last answer.
- **Leaking a token.** Scopes are parsed from the header whatever its case, raw headers are never
  kept, no code runs a command that prints a token, and a token pasted into the page is refused.
- **Two accounts at once.** A `GH_TOKEN` or `GITHUB_TOKEN` in fleet's env file is a warning that
  names the line.
- **A login git does not use.** The proof is `git ls-remote` of the repository itself.
- **Hostile input.** `branch` and pasted addresses follow the input rules of section 6.
- **Misleading pills.** A role pill says it is the account's role, not a promise, and No access
  comes only from a definite answer.
- **A folder that is already there.** An existing `~/work/<name>`, and an SSH remote in it, are
  checked before the clone.
- **Unclear words.** Every state is a sentence about what the agents can do, and the table has six
  columns of one line each.
