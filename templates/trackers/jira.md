# Tracker adapter: Jira

Jira has ids and workflows, and it is often the tracker the rest of your
company already uses. Two things need care: transitions (status is not a field
you set) and labels (they are flat, with no groups).

The API calls below are Jira Cloud REST API version 3 endpoints, on your site's
address (`https://<your-site>.atlassian.net`).

## Ids

`PROJ-123`. Branch: `PROJ-123-short-slug`. Pull request title:
`PROJ-123: what the change does`. If you use smart commits, put the key in
commit messages too.

## Take a task

Two writes through the REST API, plus the status change below:

- `PUT /rest/api/3/issue/PROJ-123` with
  `{"update": {"labels": [{"add": "agent-<codename>"}]}}`.
- `POST /rest/api/3/issue/PROJ-123/comment` with "Taken by `<codename>` on
  `<date>`. Working: one line."

The owner stays the assignee. If your project uses components for team
ownership, leave the components alone: they mean an area of the product, not
who is working on the issue now.

## Link the pull request

With the GitHub for Jira app installed, the key in the branch name, a commit
message or the pull request title is enough. The issue then shows a
development panel with the branch, the commits and the pull request.

Without the app, add the link yourself:
`POST /rest/api/3/issue/PROJ-123/remotelink` with
`{"object": {"url": "<pull request URL>", "title": "<title>"}}`. Do it when the
pull request opens, not at merge time, or the issue shows nothing for the whole
review.

## Post evidence

Comment through `POST /rest/api/3/issue/PROJ-123/comment`. In API version 3,
the comment body is Atlassian Document Format (a JSON structure), not
Markdown, so build the JSON instead of pasting text.

Screenshots upload with `POST /rest/api/3/issue/PROJ-123/attachments`, as
multipart form data, with the file in a field named `file` and the header
`X-Atlassian-Token: no-check`. Attach the file first, then refer to it in the
comment.

## Move status

Status changes are transitions. Read the transitions available from the
issue's current state with `GET /rest/api/3/issue/PROJ-123/transitions`, then
`POST` the chosen transition id to the same path. The ids differ between
workflows and projects, so read them at run time instead of hard-coding them.

If the transition has a screen with a required field (a resolution, for
example), send that field in the same call, or the transition is rejected.

## Resting states

Map them onto your workflow once, and write the mapping into this file:

- **Done**: a status in the Done category, acceptance comment posted.
- **In Review**: a status in the In Progress category that means "waiting on a
  person", with the owner's exact next step in the last comment.
- **Backlog**: a status in the To Do category, with a comment saying what
  landed, what did not, and what picking it up means.

If your workflow has no In Review status, add one. Do not reuse In Progress for
it: "in progress with nobody on it" is exactly the failure this rule prevents.

## Agent label

Jira labels are a flat list with no groups, so the prefix does the grouping:
`agent-winston`, `agent-rubicon`. Nothing limits an issue to one agent label,
so remove yours when you hand the work over. If you may edit the project's
fields, a cleaner option is a single-select custom field named Agent, which
holds one value. Whether you may add custom fields depends on your permissions.

## Automation available

Smart commits (`PROJ-123 #comment ...`, `#time 2h`, and a transition name such
as `#close`) work once they are enabled, but only when the committer's email
address matches a Jira user. Agent commits signed with their own address do
nothing unless that address belongs to a Jira user. Automation rules can
change an issue's status when a pull request opens or merges. Rules have usage
limits that depend on your plan, so check them before you build a busy rule.

## Read-only access for headless workers

Basic authentication with an account email and an API token. Read-only access
is a question of permissions, not of the token, so create a dedicated account
that has the Browse Projects permission and nothing that writes, and give that
account to the lanes.
