# Tracker adapter: Jira

Jira has the ids and the workflow, and it is the tracker most likely to be
imposed on you by the rest of the company. The two things to get right are
transitions (status is not a field you set) and labels (they are flat, with no
groups).

## Ids

`PROJ-123`. Branch: `PROJ-123-short-slug`. PR title:
`PROJ-123: what the change does`. Put the key in commit messages too if you use
smart commits.

## Take a task

Two writes against the REST API, plus the status move below:

- `PUT /rest/api/3/issue/PROJ-123` with
  `{"update": {"labels": [{"add": "agent-<codename>"}]}}`.
- `POST /rest/api/3/issue/PROJ-123/comment` with "Taken by `<codename>` on
  `<date>`. Working: one line."

The owner stays the assignee. If your project uses components for team
ownership, leave components alone: they mean area, not who is working now.

## Link the pull request

With the GitHub for Jira app installed, the key in the branch name, the commit
message or the PR title is enough. The issue then shows a development panel
with the branch, the commits and the PR.

Without the app, write the link yourself:
`POST /rest/api/3/issue/PROJ-123/remotelink` with the PR URL and a title. Do it
when the PR opens, not at merge time, or the issue is silent for the whole
review.

## Post evidence

Comment through `POST /rest/api/3/issue/PROJ-123/comment`. On Jira Cloud the
body is Atlassian Document Format, not markdown, so build the JSON rather than
pasting text and hoping.

Screenshots upload cleanly: `POST /rest/api/3/issue/PROJ-123/attachments` as
multipart, with the header `X-Atlassian-Token: no-check`. Attach the file
first, then reference it in the comment.

## Move status

Status changes are transitions. Read the ones available from the issue's
current state with `GET /rest/api/3/issue/PROJ-123/transitions`, then
`POST` the chosen transition id. Ids differ per workflow and per project, so
read them at run time instead of hardcoding.

If a required field (a resolution, for example) is part of the transition
screen, send it in the same call or the transition is rejected.

## Resting states

Map them onto your workflow once, and write the mapping into this file:

- **Done**: the workflow's done category, acceptance comment posted.
- **In Review**: a state in the in-progress category that means waiting on a
  person, with the owner's exact next step in the last comment.
- **Backlog**: the to-do category, with a comment saying what landed, what did
  not, and what picking it up means.

If your workflow has no In Review state, add one. Do not overload In Progress,
because "in progress with nobody on it" is the failure this rule exists to end.

## Agent label

Jira labels are a flat list with no groups, so the prefix carries the grouping:
`agent-winston`, `agent-rubicon`. Nothing enforces one label per issue, so
remove yours when you hand work over. A cleaner option, if you can edit the
project's fields, is a single-select custom field named Agent, which enforces
one value; whether you may add custom fields depends on your permissions and
your plan.

## Automation available

Smart commits (`PROJ-123 #comment ...`, `#time 2h`, `#close`) work when the app
is installed and the commit author's account is linked. Automation rules can
transition an issue when a PR opens or merges. Rule execution limits vary, so
check your plan before building a busy rule.

## Read-only access for headless workers

Basic auth with an account email plus an API token. Read-only is a permission
scheme question, not a token question, so make a dedicated account that has
Browse Projects and nothing that writes, and give lanes that account.
