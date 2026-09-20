# Tracker adapter: Notion

Notion is a database, not a tracker, so this adapter is mostly a database
design. It suits a team that already plans in Notion. The gap to know before
choosing it: there is no pull request integration, so the link between an issue
and a PR is something your own automation writes.

## Ids

Page ids are UUIDs, useless in a branch name. Add a **unique ID** property to
the database (it produces values like `ENG-123`) and use that everywhere.
Whether that property type is available depends on your plan, so check first;
the fallback is a plain text `Key` property filled by hand. Branch:
`ENG-123-short-slug`. PR title: `ENG-123: what the change does`.

### Setup: the database properties

Create these once and treat the names as the contract.

| Property | Type | Holds |
|---|---|---|
| `Key` | unique id | `ENG-123` |
| `Status` | status | Backlog, Todo, In Progress, In Review, Done |
| `Agent` | select | one option per codename |
| `Pull request` | url | the PR link |
| `Branch` | text | the branch name |
| `Owner next step` | text | what the owner must do, when In Review |

## Take a task

One page update and one comment:

- `PATCH /v1/pages/<page_id>` setting `Agent` to your codename and `Status` to
  In Progress.
- `POST /v1/comments` with the page as parent: "Taken by `<codename>` on
  `<date>`. Working: one line."

The owner stays in the `Assignee` people property if you have one.

## Link the pull request

Nothing links itself here. When the PR opens, write both properties in one
`PATCH`: `Pull request` gets the URL, `Branch` gets the branch name. Do it from
a CI step on `pull_request: opened` with an internal integration token, so a
forgetful agent cannot break the chain.

## Post evidence

Post the acceptance comment with `POST /v1/comments`: root cause in one
sentence, what the fix does, the regression test that guards it, the merged
PR link.

Screenshots are awkward. What the API allows for uploading files has changed
more than once, so check what your workspace's API version supports before
building on it. The route that always works: host the image where the team can
already open it, and link it from the comment.

## Move status

`PATCH /v1/pages/<page_id>` on the `Status` property. Keep the option names
exactly as listed above: everything else here matches on those strings.

## Resting states

- **Done**: Status Done, acceptance comment posted, `Pull request` filled.
- **In Review**: Status In Review, `Owner next step` filled, and the same
  sentence repeated in the last comment so it is visible on the page.
- **Backlog**: Status Backlog, last comment saying what landed, what did not,
  and what picking it up means.

A board grouped by `Status` and filtered by `Agent` is your sign-off checklist.

## Agent label

The `Agent` select property, one option per codename. A select holds one value,
matching the rule that one agent owns an issue at a time. Add a codename as a
new option rather than reusing somebody else's.

## Automation available

Database automations can set a property or post a comment on a change, and what
they can trigger depends on your plan. With no pull request integration, treat
CI as the automation: one script patching the page on PR open and on merge
covers both moments that matter.

## Read-only access for headless workers

An internal integration with read content capability, shared into the database.
Send its token as a bearer header with a `Notion-Version` header. That worker
reads the issue and cannot damage the database.
