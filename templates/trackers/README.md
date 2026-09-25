# Tracker adapters

murmur does not care which tracker you use. It cares that five things happen on
every task, in the tool you already use. Each file here is one adapter: the
same five operations, written in the field names and commands of one tracker.

The rules these adapters serve are the "Tracker discipline" section of the law
file template, [`CLAUDE.md`](../CLAUDE.md#tracker-discipline), and the chapter
[Testing and evidence](../../docs/07-testing-and-evidence.md), which says what
counts as evidence.

## The five operations every adapter provides

1. **Take a task.** The work exists in the tracker before any code is written.
   Taking it leaves two visible marks: the agent's own label from an `Agent`
   label group, and a comment saying who took it and when. The owner stays the
   assignee, so the label is what shows who is working on it.
2. **Link the pull request.** When the pull request opens, the issue shows it.
   Either the tracker's own integration finds it by the id, or the agent adds
   the pull request URL to the issue.
3. **Post acceptance evidence.** When the work lands, a comment on the issue
   gives the root cause in one sentence, what the fix does, the regression
   test that guards it, and the link to the merged change. Screenshots are
   attached to the issue, not pasted in chat, so the whole team can open them.
4. **Move the status with the work.** In Progress when work starts, In Review
   when it waits on a person, Done on merge. A status updated only afterwards
   cannot be trusted while the work runs.
5. **Leave the issue in a resting state before signing off.** An issue with an
   agent's label rests in exactly one of three states. **Done**: merged,
   verified, and the acceptance comment posted. **In Review**: nothing is left
   for an agent, and the last comment names the owner's exact next step.
   **Backlog**: nobody is working on it, and the last comment says what landed,
   what did not, and what picking it up means. Nothing else counts as
   finished.

Issues are large. An issue is a chunk a person could own for a day or more,
never a micro-task. Big work gets a project with milestones, with one issue per
major chunk.

## The id goes into the branch name and the pull request title

Every adapter needs an id that a machine can find in plain text.

- Branch: `<id>-<short-slug>`, for example `ENG-123-trial-emails`. Some teams
  prefer `<agent>/<id>-<slug>`. Either works, as long as the id is intact.
- Pull request title: the id first, then the sentence, for example
  `ENG-123: send the trial email on the right day`.
- Commit messages may carry the id too, and some trackers act on it there.

This one convention lets an integration link a pull request to an issue
without anyone clicking anything. With no tracker, there are no ids, so the
pull request number is used instead.

## The adapters

| Adapter | Tracker | How the agent label works there |
|---|---|---|
| [`github-issues.md`](github-issues.md) | GitHub Issues | Repository labels named `agent:<codename>`, created once, applied per issue |
| [`linear.md`](linear.md) | Linear | A label group named `Agent`, one label per code name; Linear allows one label per group on an issue |
| [`jira.md`](jira.md) | Jira | Flat labels named `agent-<codename>`, or a single-select custom field named Agent |
| [`notion.md`](notion.md) | Notion | An `Agent` select property on the database, one option per code name |
| [`none.md`](none.md) | No tracker | Pull request labels named `agent:<codename>`; the pull request itself is the record |

## How to set one up

1. With the murmur plugin, run `/murmur:init`. It asks where work is tracked,
   and copies the matching adapter to `.claude/tracker.md` in your repository.
   Without the plugin, copy the adapter to `.claude/tracker.md` yourself.
2. Replace the placeholders: project key, label names, field names, base URL.
3. Delete the parts you will not use. An adapter that describes a step nobody
   performs teaches agents that steps are optional.

Once `/murmur:init` has run, the plugin's session hook tells every agent, at
the start of each session, that the tracker rules are in `.claude/tracker.md`.
`/murmur:doctor` warns when a tracker was chosen but that file is missing.
Without the file, an agent has to ask how to do each step, and that costs a
round trip on every task.

One file, one tracker. If two teams in one repository use different trackers,
settle that before you adopt murmur. Do not fork the file.
