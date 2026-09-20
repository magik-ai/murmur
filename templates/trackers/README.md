# Tracker adapters

This kit does not care which tracker you run. It cares that five things happen
on every task, in whatever tool you already pay for. Each file here is one
adapter: the same five operations, written in the field names and commands of
one tracker.

The law these adapters serve is the "Tracker discipline" section of
`templates/CLAUDE.md`, and the evidence rule in `docs/07-testing-and-evidence.md`.

## The five operations every adapter must provide

1. **Take a task.** The work exists in the tracker before code starts. Taking
   it means two visible marks: the agent's own label from an `Agent` label
   group, and a comment naming who took it and when. The owner stays the
   assignee, so the label is the only honest answer to "who is on this".
2. **Link the pull request.** When the PR opens, the issue shows it. Either the
   tracker's own integration finds it by the id, or the adapter writes the PR
   URL onto the issue by hand.
3. **Post acceptance evidence.** When the work lands, a comment on the issue
   carries the root cause in one sentence, what the fix does, the regression
   test that guards it, and the link to the merged change. Screenshots attach
   to the issue, not to chat, so the whole team can open them.
4. **Move status with the work.** In Progress when work starts, In Review when
   it waits on a person, Done on merge. A status that is updated afterwards is
   a status nobody trusts while the work is running.
5. **Leave the issue in a resting state before signing off.** An issue carrying
   an agent's label rests in exactly one of three states: **Done** (merged,
   verified, acceptance comment posted), **In Review** (nothing left for an
   agent, and the last comment names the owner's exact next step), or
   **Backlog** (not being worked, and the last comment says what landed, what
   did not, and what picking it up means). Nothing else counts as finished.

Granularity is large. An issue is a chunk a person could own for a day or more,
never a micro-task. Big work gets a project with milestones, and each major
chunk is one issue.

## The id goes into the branch name and the PR title

Every adapter needs an id a machine can find in plain text.

- Branch: `<id>-<short-slug>`, for example `ALL-123-trial-emails`. Some teams
  prefer `<agent>/<id>-<slug>`; either works as long as the id is intact.
- PR title: the id first, then the sentence, for example
  `ALL-123: a late trial email tells the truth`.
- Commit messages may carry it too, and some trackers act on it there.

That one convention is what lets an integration link a PR to an issue without
anyone clicking anything. A tracker without ids (the tracker-less mode) uses
the PR number instead.

## The adapters

| Adapter | Tracker | How the "agent label" idea maps |
|---|---|---|
| `github-issues.md` | GitHub Issues | Repository labels named `agent:<codename>`, created once, applied per issue |
| `linear.md` | Linear | A label group named `Agent`, one label per codename, exclusive by construction |
| `jira.md` | Jira | Flat labels prefixed `agent-<codename>`, or a single-select custom field named Agent |
| `notion.md` | Notion | An `Agent` select property on the database, one option per codename |
| `none.md` | No tracker | A pull request label group `agent:<codename>`; the PR itself is the record |

## How a team picks one

1. Open the adapter that matches the tracker you already run.
2. Copy that file into your repository as `.claude/tracker.md`.
3. Replace the placeholders: project key, label names, field names, base URL.
4. Delete the parts you will not run. An adapter that describes a step nobody
   performs teaches agents that steps are optional.

The plugin's session context hook and the `orchestrate` skill read
`.claude/tracker.md` and follow it, so the five operations happen in your tool
without anyone pasting instructions into a prompt. If the file is missing, an
agent has to ask, and asking costs a round trip on every task.

One file, one tracker. If two teams in one repository run different trackers,
that is a decision to make before adopting the kit, not a file to fork.
