# Tracker adapter: Linear

Linear already has what the five operations need: real issue ids, workflow
states that match the three resting states, label groups that allow one label
per issue, and a GitHub integration that links pull requests by issue id.

The API calls below are Linear GraphQL operations, sent to
`https://api.linear.app/graphql`.

## Ids

`KEY-123`, where `KEY` is the team key, for example `ENG-123`. Branch:
`key-123-short-slug`. The "Copy git branch name" action on an issue gives you a
ready-made name that contains the id. Pull request title:
`KEY-123: what the change does`.

## Take a task

Three marks, one step each:

- Add your label from the `Agent` group: `issueUpdate`, field
  `addedLabelIds`. Do not use the field `labelIds` for this: it replaces all
  of the issue's labels.
- Post a comment: "Taken by `<codename>` on `<date>`. Working: one line."
  (`commentCreate`, fields `issueId` and `body`).
- Move the state to In Progress (see "Move status" below).

The owner stays the assignee. Do not reassign the issue to a bot user: the
label shows which agent has the work, and the assignee stays a person.

## Link the pull request

With the GitHub integration installed, Linear links the pull request when the
branch name or the pull request title contains the issue id, or when the
description says `Fixes KEY-123`. There is nothing to do by hand. Without the
integration, attach the pull request URL yourself with `attachmentCreate`
(fields `issueId`, `url`, `title`).

## Post evidence

The acceptance comment is a normal comment: root cause in one sentence, what
the fix does, the regression test that guards it, the merged pull request link.

For a screenshot that already has a public URL, put the image link in the
comment's Markdown: Linear copies the image into its own storage. To upload a
file from disk, call the `fileUpload` mutation to get an `uploadUrl` and an
`assetUrl`. Send the file to the `uploadUrl` with a PUT request, using the
headers the mutation returned. Then put the `assetUrl` in the comment's
Markdown. Either way, the image stays with the issue where the whole team can
open it, which a chat paste does not.

## Move status

Each team has its own workflow states, so read them once (the `workflowStates`
query) and store their ids. A common set: Backlog, Todo, In Progress, In
Review, Done. Move an issue with `issueUpdate`, field `stateId`.

The GitHub integration can also move the state for you. By default, an issue
goes to In Progress when its pull request opens, and to Done when it merges.
You can change which state each pull request event sets. Turn this on: then an
agent that forgets to move the state still leaves it right.

## Resting states

They map one to one onto workflow states:

- **Done**: merged and verified, acceptance comment posted.
- **In Review**: nothing is left for an agent, and the last comment names the
  owner's exact next step.
- **Backlog**: nobody is working on it, and the last comment says what landed,
  what did not, and what picking it up means.

Before signing off, list your own issues (filter by your Agent label and the
In Progress state), and leave each one in one of the three.

## Agent label

A label group named `Agent`, with one label per code name. Linear allows only
one label from a group on an issue, so an issue carries one agent at a time,
which is exactly the rule. When a code name is missing from the group, add it.
Never reuse someone else's.

## Automation available

The GitHub integration (linking and state changes), issue templates, and
cycles, which move unfinished issues to the next cycle. Project-level status
updates stay with the owner: agents write in issues, never in a project
update.

## Read-only access for headless workers

A personal API key, sent in the `Authorization` header without a `Bearer`
prefix. When you create the key, you can limit it to the Read permission and to
the teams the workers need. Keep the split simple: the orchestrator holds a key
that can write, and the lanes hold a read-only key.
