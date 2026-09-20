# Tracker adapter: no tracker

A team can run this kit with no tracker at all. The pull request becomes the
record: it carries who took the work, the evidence, and the resting state. It
suits a small team shipping fast, and stops working as soon as you need to
track work that has no code yet.

## Ids

There is no separate id. The pull request number is the id, so the work gets a
PR early and the branch is named after the work (`fix-slow-login`).

An agent wanting an id before writing code opens a **draft PR first** on an
empty commit (`git commit --allow-empty`, push, `gh pr create --draft`). That
draft number is the id for the batch, and the PR can be commented on from the
first minute.

## Take a task

The PR body opens with the line the tracker comment would carry:
`Taken by <codename> on <date>. Working: <one line>.`

Add the agent label (below) and claim the branch wherever your team records
claims. Without a tracker, that claim is the only thing stopping two agents
from starting the same work.

## Link the pull request

Nothing to link: the pull request is the record. It still has to be findable,
so post the PR URL to the team's channel or board when it opens. A PR nobody
knows about is invisible until it merges.

## Post evidence

The acceptance evidence lives in the PR body under a fixed heading:

```markdown
## Acceptance
Root cause: <one sentence>.
Fix: <what it does>.
Regression test: <path and what it asserts, failing without the fix>.
Checked: <click path and the result>.
Not verified: <what you could not check>.
```

Edit that section as the work lands, rather than scattering the answer across
review comments. Screenshots drag into a PR comment and upload there; link
them from the Acceptance section so the thread does not swallow them.

## Move status

The PR's own state is the status.

| Work state | Pull request state |
|---|---|
| In progress | draft |
| In review | ready for review |
| Done | merged |
| Parked | `hold` label, open, with a reason comment |

## Resting states

Before signing off, every PR with your agent label rests in one of three.

- **Done**: merged, with the Acceptance section filled in.
- **In Review**: ready for review, and the body has a line
  `Owner next step: <the exact thing the owner must do>`.
- **Backlog**: labelled `hold` or closed, with a comment saying what landed,
  what did not, and what picking it up means. Never leave an owned PR silent.

## Agent label

Pull request labels named `agent:<codename>`, in one colour, created once per
repository. The prefix is the group, and `gh pr list --label
"agent:<codename>" --state open` is your sign-off checklist.

Do not list by author: agents often share one host account, so the author
filter matches everybody.

## Automation available

A CI check on the PR body replaces the tracker's discipline: refuse a non-draft
PR whose body has no "Taken by" line, no `## Acceptance` section, or a `hold`
label. Twenty lines of script, and the only enforcement this mode has.

## Read-only access for headless workers

A repository token with Pull requests: read and Contents: read.
`gh pr view <n> --json title,body,labels,comments` gives a worker the whole
record, the text a tracker adapter would otherwise fetch from an issue.
