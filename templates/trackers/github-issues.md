# Tracker adapter: GitHub Issues

Everything lives in the repository that holds the code, and your agents already
have the permissions they need. The cost: an issue has only two states, open
and closed, so labels or a GitHub Projects board carry the status.

## Ids

The issue number, written `#123`. Branch: `123-short-slug`. Pull request
title: `#123: what the change does`. Also put `Closes #123` in the pull request
body: GitHub acts on a closing keyword in the body, and a number in the title
is not a reliable link.

## Take a task

```bash
gh issue edit 123 --add-label "agent:<codename>" --add-label "status:in-progress"
gh issue comment 123 --body "Taken by <codename> on <date>. Working: <one line>."
```

The owner stays the assignee, so the `agent:` label is what shows who is
working on the issue. Create each agent label once:

```bash
gh label create "agent:<codename>" --color 0E8A16
```

## Link the pull request

```bash
gh pr create --title "#123: <subject>" --body "Closes #123

<acceptance guide>"
```

GitHub then shows the pull request in the issue's timeline, and closes the
issue when the pull request merges into the default branch. If you would rather
close the issue by hand after the acceptance comment, write `Refs #123`
instead: it adds a reference to the issue's timeline without closing it.

## Post evidence

```bash
gh issue comment 123 --body-file evidence.md
```

The comment gives the root cause in one sentence, what the fix does, the
regression test that guards it, and the link to the merged pull request.

Screenshots are the weak spot: GitHub has no documented API for uploading an
image into a comment. Recent versions of `gh` can attach one
(`gh issue comment 123 --attach <file>`; check `gh issue comment --help` for
yours). Otherwise, drag the file into the comment box on the web, or commit it
under `docs/evidence/` in the same pull request and link to it.

## Move status

Without a board, use the labels `status:in-progress`, `status:in-review` and
`status:backlog`, and closed for done. Swap them in one command, so an issue
never carries two:

```bash
gh issue edit 123 --remove-label "status:in-progress" --add-label "status:in-review"
```

With GitHub Projects (optional), add a single-select `Status` field, and move
the issue's item:

```bash
gh project item-edit --id <item-id> --project-id <project-id> \
  --field-id <status-field-id> --single-select-option-id <option-id>
```

Projects also has built-in workflows. By default, closing an issue or merging a
pull request sets its status to Done. Check your project's workflow settings
before you rely on any other automation.

## Resting states

- **Done**: closed by the merged pull request, acceptance comment posted.
- **In Review**: open, `status:in-review`, and the last comment names the
  owner's exact next step.
- **Backlog**: open, `status:backlog`, and the last comment says what landed,
  what did not, and what picking it up means.

## Agent label

Repository labels named `agent:<codename>`, all in one colour so they read as
a group. GitHub labels have no real groups, so the prefix is the group, and
`gh label list --search "agent:"` lists them. Nothing stops an issue from
carrying two agent labels, so remove yours when you hand the work over.

## Automation available

Closing keywords, Projects workflows, and GitHub Actions. A workflow on the
`pull_request` event can fail a required check when the pull request body has
no issue reference. That is the cheapest way to stop untracked work.

## Read-only access for headless workers

A fine-grained personal access token for the repository, with read-only access
to Issues and Contents. Export it as `GH_TOKEN`. Then
`gh issue view 123 --json title,body,labels,comments` works, and the worker
cannot write anything.
