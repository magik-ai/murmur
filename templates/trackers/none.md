# Tracker adapter: no tracker

You can run murmur with no tracker at all. The pull request becomes the
record: it shows who took the work, the evidence, and the resting state. This
suits a small team that ships fast. It stops working as soon as you need to
track work that has no code yet.

## Ids

There is no separate id. The pull request number is the id, so the work gets a
pull request early, and the branch is named after the work (`fix-slow-login`).

An agent that wants an id before writing any code opens a **draft pull request
first**, on an empty commit: `git commit --allow-empty`, push, then
`gh pr create --draft`. The draft's number is the id for the batch, and the
pull request can take comments from the first minute.

## Take a task

The pull request body opens with the line a tracker comment would carry:
`Taken by <codename> on <date>. Working: <one line>.`

Add the agent label (see "Agent label" below), and claim the branch wherever
your team records claims. With no tracker, that claim is the only thing that
stops two agents from starting the same work.

## Link the pull request

There is nothing to link: the pull request is the record. It still has to be
found, so post its URL to the team's channel or board when it opens. A pull
request nobody knows about stays invisible until it merges.

## Post evidence

The acceptance evidence lives in the pull request body, under a fixed heading:

```markdown
## Acceptance
Root cause: <one sentence>.
Fix: <what it does>.
Regression test: <path, and what it asserts; it fails without the fix>.
Checked: <click path and the result>.
Not verified: <what you could not check>.
```

Update that section as the work lands, instead of spreading the answer across
review comments. Screenshots can be dragged into a pull request comment on the
web, which uploads them. Link them from the Acceptance section, so they are not
lost in the thread.

## Move status

The pull request's own state is the status.

| Work state | Pull request state |
|---|---|
| In progress | draft |
| In review | ready for review |
| Done | merged |
| Parked | open, with the `hold` label and a comment giving the reason |

## Resting states

Before signing off, make sure every pull request with your agent label rests
in one of three states.

- **Done**: merged, with the Acceptance section filled in.
- **In Review**: ready for review, and the body has a line
  `Owner next step: <the exact thing the owner must do>`.
- **Backlog**: labelled `hold`, or closed, with a comment saying what landed,
  what did not, and what picking it up means. Never leave a pull request you
  own without a word.

## Agent label

Pull request labels named `agent:<codename>`, in one colour, created once per
repository. The prefix is the group, and
`gh pr list --label "agent:<codename>" --state open` is your checklist before
signing off.

Do not list by author: agents often share one GitHub account, so an author
filter matches everybody.

## Automation available

A CI check on the pull request body does the tracker's job of keeping
discipline. It fails a pull request that is not a draft when its body has no
"Taken by" line or no `## Acceptance` section, or when it has the `hold`
label. It is about twenty lines of script, and it is the only enforcement this
mode has.

## Read-only access for headless workers

A fine-grained personal access token for the repository, with read-only access
to Pull requests and Contents. With it,
`gh pr view <number> --json title,body,labels,comments` gives a worker the
whole record: the text a tracker adapter would otherwise read from an issue.
