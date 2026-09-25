# Tracker adapter: Notion

Notion is a database, not a tracker, so most of this adapter is a database
design. It suits a team that already plans in Notion. Notion's GitHub
integration can link pull requests to tasks and move their status, but only
through a database property you add yourself (see "Link the pull request").

The API calls below are Notion API endpoints on `https://api.notion.com`.

## Ids

Page ids are long UUIDs, useless in a branch name. Add a **Unique ID**
property to the database, with a prefix, so it produces values like `ENG-123`,
and use that id everywhere. Branch: `ENG-123-short-slug`. Pull request title:
`ENG-123: what the change does`.

### Setup: the database properties

Create these once, and treat the names as the contract.

| Property | Type | Holds |
|---|---|---|
| `Key` | Unique ID, with a prefix | `ENG-123` |
| `Status` | Status | Backlog, Todo, In Progress, In Review, Done |
| `Agent` | Select | one option per code name |
| `Pull request` | URL | the pull request link |
| `Branch` | Text | the branch name |
| `Owner next step` | Text | what the owner must do, when In Review |

If you use Notion's GitHub integration, also add a `GitHub Pull Requests`
property (see "Link the pull request").

## Take a task

One page update and one comment:

- `PATCH /v1/pages/<page_id>`, setting `Agent` to your code name and `Status`
  to In Progress.
- `POST /v1/comments`, with the page as the parent: "Taken by `<codename>` on
  `<date>`. Working: one line."

The owner stays in the `Assignee` people property, if you have one.

## Link the pull request

With Notion's GitHub integration, add a `GitHub Pull Requests` property to the
database. A pull request whose title contains the task's Unique ID (for
example `ENG-123`) is then linked to that task. In the property's settings,
you can also have the `Status` property change when the pull request is
opened, has a review requested, is approved, or is merged.

Without the integration, nothing links itself. When the pull request opens,
write both properties in one `PATCH`: `Pull request` gets the URL, and `Branch`
gets the branch name. Do it from a CI step that runs when a pull request opens,
with an internal integration token, so an agent that forgets cannot break the
link.

## Post evidence

Post the acceptance comment with `POST /v1/comments`: root cause in one
sentence, what the fix does, the regression test that guards it, the merged
pull request link.

Screenshots take more work. Before you build on file uploads through the API,
check what the current Notion API version supports. The route that always
works: put the image where the team can already open it, and link to it from
the comment.

## Move status

`PATCH /v1/pages/<page_id>` on the `Status` property. Keep the option names
exactly as listed above: everything else here matches on those names.

## Resting states

- **Done**: `Status` is Done, the acceptance comment is posted, and
  `Pull request` is filled in.
- **In Review**: `Status` is In Review, `Owner next step` is filled in, and the
  same sentence is repeated in the last comment, so it is visible on the page.
- **Backlog**: `Status` is Backlog, and the last comment says what landed, what
  did not, and what picking it up means.

A board view grouped by `Status` and filtered by `Agent` is your checklist
before signing off.

## Agent label

The `Agent` select property, with one option per code name. A select holds one
value, which matches the rule that one agent owns an issue at a time. When a
code name is missing, add it as a new option. Never reuse someone else's.

## Automation available

Notion's GitHub integration, described above. Database automations can edit a
property or send a notification when a page is added or a property changes.
Most automation types need a paid plan. Without the GitHub integration, use
CI as the automation: one script that updates the page when a pull request
opens and when it merges covers both moments that matter.

## Read-only access for headless workers

An internal integration with only the Read content and Read comments
capabilities, connected to the database. Send its token in the `Authorization`
header as `Bearer <token>`, together with a `Notion-Version` header. A worker
with that token can read the issue, and cannot change the database.
