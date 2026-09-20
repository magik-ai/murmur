# Tracker adapter: GitHub Issues

Everything lives in the repository that holds the code, with the permissions
your agents already have. The cost is that an issue has only two native states,
open and closed, so status is carried by labels or by a Projects board.

## Ids

The issue number, written `#123`. Branch: `123-short-slug`. PR title:
`#123: what the change does`. Put `Closes #123` in the PR body too, because the
body reference is what GitHub acts on, and a title is not a guaranteed link.

## Take a task

```bash
gh issue edit 123 --add-label "agent:<codename>" --add-label "status:in-progress"
gh issue comment 123 --body "Taken by <codename> on <date>. Working: <one line>."
```

The owner stays the assignee, so the `agent:` label is the only honest answer
to "who is on this". Create the label once with
`gh label create "agent:<codename>" --color 0E8A16`.

## Link the pull request

```bash
gh pr create --title "#123: <subject>" --body "Closes #123

<acceptance guide>"
```

GitHub then shows the PR in the issue timeline and closes the issue when the PR
merges into the default branch. To close it by hand after the acceptance
comment instead, write `Refs #123`.

## Post evidence

`gh issue comment 123 --body "$(cat evidence.md)"`, carrying the root cause in
one sentence, what the fix does, the regression test that guards it, and the
merged PR link.

Screenshots are the weak spot: GitHub has no documented API for uploading an
image into a comment. Either drag the file into the comment box in the web
interface, or commit it under `docs/evidence/` in the same PR and link its raw
URL.

## Move status

Without a board, use `status:in-progress`, `status:in-review`,
`status:backlog`, and closed for done. Swap them in one command so an issue
never carries two.

With GitHub Projects (optional), add a single-select `Status` field and move
the card with `gh project item-edit --id <item> --field-id <status>
--single-select-option-id <opt>`. Projects also ships workflows that can move
an item when a linked PR opens or merges. Which ones exist depends on the
project, so check yours before relying on one.

## Resting states

- **Done**: closed by the merged PR, acceptance comment posted.
- **In Review**: open, `status:in-review`, last comment naming the owner's
  exact next step.
- **Backlog**: open, `status:backlog`, last comment saying what landed, what
  did not, and what picking it up means.

## Agent label

Repository labels named `agent:<codename>`, all one colour so they read as a
group. GitHub labels have no real grouping, so the prefix is the group and
`gh label list --search "agent:"` is the roster. Nothing stops two agent labels
on one issue, so removing yours when you hand work over is on you.

## Automation available

Closing keywords, Projects workflows, and GitHub Actions. An Action on
`pull_request` can refuse a PR whose body has no issue reference, which is the
cheapest way to stop untracked work.

## Read-only access for headless workers

A fine-grained token scoped to the repository with Issues: read and Contents:
read. Export it as `GH_TOKEN`, and
`gh issue view 123 --json title,body,labels,comments` works with no write path.
Public repositories read without a token, at a lower rate limit.
