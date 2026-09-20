# Tracker adapter: Linear

Linear gives you everything the five operations need without inventing
conventions: real issue keys, workflow states that already match the three
resting states, label groups that hold one value at a time, and a GitHub
integration that links pull requests by branch name.

## Ids

`KEY-123`, where `KEY` is the team key. Branch: `key-123-short-slug` (the
issue's own "copy branch name" produces one, usually
`<user>/key-123-slug`, and the integration matches either). PR title:
`KEY-123: what the change does`.

## Take a task

Three marks, in one step each:

- Add your label from the `Agent` group (`issueUpdate`, field `labelIds`).
- Post a comment: "Taken by `<codename>` on `<date>`. Working: one line."
  (`commentCreate`, fields `issueId` and `body`).
- Move the state to In Progress (below).

The owner stays the assignee. Do not reassign the issue to a bot user: the
label is where agent ownership lives, and assignee remains a person.

## Link the pull request

The GitHub integration links the PR automatically when the branch name or the
PR title contains the id, and writes the link into the issue as an attachment.
Nothing to do by hand once the integration is installed. If it is not, add the
PR URL with `attachmentCreate` (fields `issueId`, `url`, `title`).

## Post evidence

The acceptance comment is a normal comment: root cause in one sentence, what
the fix does, the regression test that guards it, the merged PR link.

Screenshots go up through the API in three steps: call the `fileUpload`
mutation to get an `uploadUrl` and an `assetUrl`, PUT the bytes to the
`uploadUrl` with the same content type, then embed the `assetUrl` in the
comment markdown. That host is durable and visible to the whole team, which a
chat paste is not.

## Move status

Each team has its own workflow states, so read them once
(`team.states`) and store the ids. Typical set: Backlog, Todo, In Progress, In
Review, Done. Move with `issueUpdate`, field `stateId`.

The GitHub integration can move the state for you on PR open and PR merge.
Turn it on and let it, then an agent that forgets is still correct. Which
automations your workspace offers can vary, so check your plan.

## Resting states

They map one to one onto workflow states:

- **Done**: merged and verified, acceptance comment posted.
- **In Review**: nothing left for an agent, and the last comment names the
  owner's exact next step.
- **Backlog**: not being worked, and the last comment says what landed, what
  did not, and what picking it up means.

Before signing off, list your own issues (filter by your Agent label and state
In Progress) and leave each one in one of the three.

## Agent label

A label group named `Agent`, with one label per codename. A group behaves as a
single choice, so an issue can carry only one agent at a time, which is exactly
the rule. Add a codename to the group when it is missing rather than reusing
somebody else's.

## Automation available

The GitHub integration (branch and PR linking, state moves), issue templates,
and cycle rollover. Project-level status updates stay owner-only: agents write
into issues, never into a project update.

## Read-only access for headless workers

A personal API key sent as the `Authorization` header against the GraphQL
endpoint. A personal key acts as the person who made it, so it is read-only
only by discipline. If you need enforced read-only, an OAuth application with a
read scope is the route, and what your workspace may install depends on your
plan. Practical split: the orchestrator holds a writing key, lanes hold a key
they only read with.
