<!--
Template: the repository law file. Copy to the root of your repo as CLAUDE.md.
Replace every <PLACEHOLDER>. Delete what you do not run; keep what you will enforce.
A law nobody enforces teaches agents that laws are optional.
-->

You are operating in `<ORG>/<REPO>`. The product is **<PRODUCT>**; use that form
in product prose.

This file is the single source of truth for **how work happens**. Every other
document named below is optional. `ARCHITECTURE.md`, if you keep one, describes
what is live on `main`. `AGENTS.md`, if you keep one, gives product and agent
orientation. `docs/adr/`, if you keep one, records technical decisions.

## TL;DR: boot contract

<!-- Only line 1 is required. DELETE any line here whose document you do not
     actually keep. A boot list that names a missing file breaks on the first
     read, and an agent that cannot find item 2 stops trusting items 3 to 5. -->

Read these in order, and nothing else at boot:

1. [`CLAUDE.md`](CLAUDE.md): process law.
2. `ARCHITECTURE.md`, if you keep one: current deployed architecture.
3. `AGENTS.md`, if you keep one: product, customer, and agent orientation.
4. `docs/INDEX.md`, if you keep one: route to the task-specific reference.
5. `<DOC>` before `<KIND OF WORK>`: one or two entries at most.

Anything else is loaded on demand, through the index if you keep one. Do not
load historical plans or archived design records at boot. A boot contract that
grows stops being read.

**Knowledge base:** per-domain orientation (truth maps, invariants, measured
numbers, debug method, defect history) lives in `docs/knowledge/`, if you keep
one. Before working a subject that has a file there, read it first.

## Team

Law lives in one file; people live in this table. Keep it short and current.

| Name | Role | Owns | Reviews |
|---|---|---|---|
| `<OWNER>` | product owner | what we build, product acceptance | anything user visible |
| `<CTO>`, if you have one | technical owner | architecture, guidelines, infrastructure | architecture-shaped changes |
| `<CONDUCTOR>`, if you have one | release manager | the queue, CI health, deploys | holds the merge veto |
| `<NAME>` | `<ROLE>` | `<AREA>` | `<WHAT>` |

"Owner" in this file means `<OWNER>` unless stated otherwise. Lane assignments
and merge coordination live in `docs/process/TEAM_LANES.md`, if you keep one.

## Communication rules

Every report, PR body, issue, and message an agent writes follows four rules:

- **Speak simple.** A term of art is fine, a wall of codenames is not.
- **Speak as a person**, not a parameter-spilling machine.
- **Always give enough context to make a fast decision.** The reader was not
  watching you work; say what a thing is before referring to it.
- **Pick one house style rule a machine can check**, enforce it in CI, and
  sweep the copy instead of adding exceptions. Any rule you will actually
  enforce works; a rule nobody checks is not a rule.

### Writing to a person

Most readers here are not holding the code in their head. A status, a report, an
issue description, a PR body for a non-author: all of it has to land the first
time. These are checks, not preferences.

1. **Meaning first.** The opening two or three sentences say what happened, what
   it means for the user, and what needs deciding. No preamble, no retelling of
   your process.
2. **One idea per sentence, about fifteen words.** No nested clauses, no
   semicolons, no chains of dashes or arrows.
3. **No names from the code in the prose**: functions, events, flags, files,
   branches, hashes. They live at the end, in a block for engineers. In the text
   use words: write "the server held the answer for ten seconds", not an event
   name.
4. **Every term is explained on first use**, in one phrase, or replaced by an
   everyday word. The test: would a sharp friend outside engineering follow it?
5. **Numbers rounded and compared**: "it was ten seconds, now it is none".
   Milliseconds and percentiles belong in a table for engineers. At most one
   figure per sentence in the prose.
6. **No metaphors from this codebase.** A word like gate, seam or ledger means
   something only to whoever read the code. Say what the mechanism does.
7. **Lists are one or two sentences per item. Tables are at most five columns,
   at most eight words per cell.**
8. **Length.** A chat status stays under 120 words. An issue description stays
   under half a screen plus its block for engineers. Anything longer opens with
   a paragraph headed "In short".
9. **Every long text has the same shape**: what happened, what it means, what to
   decide or what comes next, the numbers in a small table, then the block for
   engineers with names, paths and links.
10. **Read it back as the reader before sending.** If a sentence needs knowledge
    of the code to parse, rewrite it in words or move it to the engineering
    block.

Everything committed here stays English, including these reports.

## Design principles

**KISS and DRY, in balance.** Keep every design as simple as it can be while
giving shared logic one authoritative home (the second-implementation law
below). When the two pull apart, prefer the simpler design and accept a small,
visible duplication over a clever abstraction; extract on the second *real*
consumer, not before.

## Architecture governance

### The pattern catalog

`docs/architecture/PATTERNS.md`, if you keep one, is the closed catalog of
mechanisms this repository already uses. First inspect the repository and reuse
a registered pattern.

- A reasonable extension of an approved mechanism, in the same complexity class,
  proceeds without approval.
- If an urgent extension may or may not fit, record it in
  `docs/architecture/PATTERN_FLAGS.md`, if you keep one, and proceed. `<CTO>`,
  if you have one, reviews asynchronously. The flags file is the pressure valve
  that keeps the catalog honest instead of ignored.
- A definite new communication pattern, architectural mechanism, or complexity
  increase needs approval from `<CTO>`, if you have one, landing as a catalog
  entry plus an ADR.
- **Waiver:** until `<VERSION>` an owner waiver is in effect. Record the case in
  the flags file and proceed; the review happens asynchronously instead of
  blocking. State here when the waiver ends.

### Owner gate: product and visual review

Async, never blocks a merge. A PR with a user-visible change carries the
`design-review` label and a PR-body line `Review with <OWNER>`. The label stays
until the owner looks. The owner reviews a picture or a live link, never a diff.

### Testing standard

`docs/TESTING.md`, if you keep one, is the executable contract. Put each check
at the lowest tier that proves it. Use real collaborators and fake only true
provider or transport boundaries, asserting on those fakes. Service and flow
tests are the mass; end-to-end journeys are the thin tip. Every feature gets an edge-case pass;
every widget gets a missing-state pass with all states designed, tested, or
explicitly waived.

### Freeze state

No feature freeze is active unless the owner declares one here, in this file,
not in a side document. Never infer a freeze from a plan.

## 0. Core contract

- One batch, one worktree, one branch, commits per slice, one PR, green CI,
  squash merge through the queue, then remove the worktree.
- Nothing lands directly on `main`.
- The agent drives the batch end to end. Stop only for a real blocker, red CI
  not caused by the batch, or an action requiring explicit approval.
- The `hold` label is the veto: it must always block a merge. Anyone may add
  the hold label. Only the owner removes it.

## 1. Repo and contract map

Development setup and everyday commands: `README.md`. Build artifacts stay
uncommitted.

```text
<PATH>/        <what lives here>
<PATH>/        <what lives here>
docs/          laws, references, archive
infra/         infrastructure and deploy config
.github/       CI, preview, deploy
```

Name the wire contract here: the versioned API surface, its field casing, its
error and pagination shapes, and the rule that generated clients and schemas are
generated, never hand-edited. Name the canonical domain hierarchy in one line,
so no agent invents a second vocabulary.

## Big work protocol

A new project, a large refactor, or a large completion push does not start with
code. It starts with three artifacts, in order:

1. **The tracker.** The work gets a project with milestones and large, coherent
   issues: one per major chunk. The tracker is updated as work moves.
2. **Design doc.** Before implementation, a design record lands in
   `docs/design/<slug>.md`, if you keep such a directory: the intent, the
   boundaries, the mechanism, the risks, and what is explicitly out of scope.
   Architecture-shaped decisions also get their ADR.
3. **Design doc review.** The doc is reviewed before code: an independent
   reviewer (not the author) attacks it, `<CTO>`, if you have one, reviews
   anything architecture-shaped, and the owner reviews anything product-shaped.
   Findings are resolved in the doc. Only then do lanes spawn.

Small batches (a fix, one screen, one contract change) skip this protocol and go
straight to the Golden Workflow.

## Tracker discipline

`<TRACKER>` (Linear, GitHub Projects, Jira, whatever you run) is the project
view over the repository. Repository-scoped bugs and tech debt may stay in
GitHub issues; the tracker is where the work itself is tracked.

- **Taking a task means the task exists in the tracker.** If the work was born
  in chat, create the issue before starting. Status moves **with** the work: In
  Progress when it starts, the PR linked when it opens, Done on merge.
- **Who is on it is visible on the issue.** The owner stays the assignee; the
  agent driving the work carries its own label from an `Agent` label group (one
  label per codename; add a codename when it is missing). Taking a task means
  the agent label on the issue plus a comment naming who took it and when.
- **Three resting states.** An issue carrying an agent's label stays that
  agent's until it rests in exactly one of three states: **Done** (merged,
  verified, acceptance comment posted), **In Review** (nothing left for an
  agent; the owner's exact next step named in the last comment), or **Backlog**
  (not being worked; the last comment says what landed, what did not, and what
  picking it up means). Before signing off, an agent leaves every issue with its
  label in one of those three. The rule exists because an audit found issues
  sitting In Progress for weeks with no branch, no PR and no comment.
- **Granularity is large.** An issue is a chunk a person could own for a day or
  more, never a micro-task.
- **The issue is where the work is written down**, not chat: a short comment
  whenever something material changes (a finding, a blocker, a scope shift), and
  the acceptance evidence when it lands (root cause, fix, regression test, PR
  link). Screenshots upload as tracker attachments so the whole team can open
  them.
- **Project-level status updates are owner-only.** Agents write into issues.
- **The tracker id goes into the branch name and the PR title**, so the
  integration links the two.
- **Everything written in the tracker is English**, in the simple English of the
  writing rules above.
- Do not mass-create or migrate issues. The backlog grows from the owner's
  signal, not from an import.

## 2. Golden Workflow: 10 gates

1. Branch from fresh `main` in a dedicated worktree. Never reuse a merged
   branch.
2. Implement one coherent batch and commit each reviewable slice.
3. Keep docs current, in the same PR, for whichever of these you keep: a key
   API or data contract, or a major architecture decision, updates
   `ARCHITECTURE.md` plus an ADR; adding, moving or retiring a document updates
   `docs/INDEX.md`. **Before merge, check `docs/knowledge/`**: if the batch
   changes how a subsystem actually behaves (mechanism, capacity, cost, timing,
   procedure), the matching domain file is updated in this PR.
4. Add a `RELEASE_NOTES.d/<category>-<slug>.md` note for user-visible impact;
   otherwise state "no user-visible change" in the PR.
5. Run the affected lint, tests, build, and contract checks locally.
6. Merge `origin/main` while developing when it moves; rerun affected checks.
7. Open the PR using `.github/PULL_REQUEST_TEMPLATE.md`: the only PR template.
8. Run an adversarial review pass (a second agent, ideally a different model or
   vendor) on the exact head commit. It ends in one line, `VERDICT <sha> CLEAN`
   or `VERDICT <sha> RED`. Use the deeper pass for auth, security, migrations,
   durability, or encrypted user content.
9. Fix every in-scope finding in the same PR. File a scoped issue for real
   out-of-scope work.
10. Green checks qualify a change for merging; only the owner's explicit signal
    merges it, and auto-merge is armed only after that signal. Never bypass a
    required gate with an admin override. Confirm the host reports the PR
    merged before cleanup.

## 3. Commits

`Type: subject`, imperative, with a capitalized type and no trailing period.
Types: `Feat:`, `Fix:`, `Review:`, `Docs:`, `Build:`, `Cleanup:`.
Immediately before every commit or push, verify the current branch and
`git status --short`. (Pushes have landed on the wrong branch for want of one
two-second check.)

## 4. Worktrees and parallel work

- One batch, one worktree, one branch, one PR. Each worktree gets its own
  environment; installs are path-pinned, so a copied environment silently
  imports a neighbour's code. After merge, remove the worktree and branch.
  Never continue work by rebasing a merged branch.
- Lanes own disjoint paths; never edit outside your manifest. Shared
  append-only files are collision sources: split them before parallel edits (one
  file per change beats one shared list).
- Reserve ADR and migration numbers at batch start, scanning `main` and every
  open PR, not just your own tree.
- When two parents touched one file, diff the merge against both parents and
  confirm each named change survived: a clean auto-merge can still lose work.
- Grouped lanes assemble into one integration PR. A conflict at assembly time is
  the collision detector doing its job, not an accident.
- The merge queue serializes `main`; it does not replace lane isolation.

Incidents behind these rules live in `docs/GOTCHAS.md`.

## 5. CI, protection, deploy

- CI must execute what production runs. Renaming a required job changes its
  check context and requires an atomic branch-protection update. Inspect the
  live protection state before changing it; never trust an old snippet.
- A merge to `main` is a production deployment within minutes; merge only
  complete, releasable states. Migrations run before the new code boots; the app
  verifies the schema at boot and dies loudly rather than migrating itself.
- A self-hosted or local CI run is an **accelerator, never a merge authority**.
  The hosted, protected checks are the authority, and the queue builds
  `main` plus the candidate: two separately green branches are not a green
  merge. If a local verdict ever disagrees with the hosted one for the same
  commit, the hosted verdict wins and the divergence is reported loudly.
- There are no releases: every merge ships. Never bump a version or cut a
  release.

## 6. Hard rules

- Everything committed to the repo is English. Name the one exception here if
  you have one (for example machine-checked translation catalogs).
- Never commit build artifacts or plaintext secrets. Deployment secrets go only
  through the encrypted secret path. Rotate immediately after exposure. Never
  echo a secret value: compare hashes.
- One migration per schema-changing batch; migrations are expand and contract,
  and backward-compatible with the currently deployed code.
- **The second-implementation law (DRY):** shared logic has one authoritative
  implementation. A second implementation of an existing capability lands only
  in the same PR as the deletion of the first, or with a dated kill ticket.
- Capabilities are key-gated: a missing key disables the capability, never
  prevents boot.
- Sensitive user content is encrypted at rest; structural metadata stays
  plaintext only by explicit contract.
- New and migrated behavior is N-replica-correct. Never use process-local
  correctness for sockets, tasks, locks, schedulers, or ownership.
- **Never switch off a shipped user-facing capability as a "fix".** Hiding or
  removing a feature is a product decision, not a bug fix. The diagnosis must
  first be proven against the live flow (reproduce the failure, trace the real
  data path end to end), and the disable itself needs the owner's explicit
  approval of that exact outcome. Rewriting a test to pin the feature's absence
  makes the suite blind to the regression. A misdiagnosis that turns off a
  working feature is a top-severity incident; ours cost a day and a post-mortem.
- Every bug-fix PR contains the regression test that fails without the fix, and
  states the root cause.
- Screenshots and design canvases are evidence, never measurement sources. A
  golden-image test is the visual-regression instrument.
- **The twice rule:** when an agent makes the same mistake twice, the correction
  enters this file or `docs/GOTCHAS.md` in the PR that fixes the second
  occurrence. A lesson that stays in chat is a lesson lost.
- No speculative abstractions, flags, or compatibility shims.
- Comments answer "why", not "what", and do not narrate the current task.
- Destructive actions and paid provisioning need explicit, action-scoped
  approval. Production is read-only by default. When a safety mechanism blocks
  you, assume it is right until you have proved otherwise.

<!-- your stack-specific laws here: layer arrows (the allowed dependency
     direction between layers, lint-enforced), design system (the only way UI may
     be built, and the story or snapshot that ships with every visual change),
     money (what may change about prices, keys, enforcement or checkout, and
     whose explicit approval it needs), language ratchets (for example: every new
     file in a converted directory uses the target language) -->

## 7. Don'ts

Do not commit to `main`, reuse merged branches, merge red CI, force-push shared
work, skip the commit hooks, amend after a failed hook when no new commit
exists, bundle an unrelated refactor into a fix, bump a version, or leave an
owned PR unfinished.

## 8. Naming

ADRs: `NNNN-type-kebab-title.md`. Standard docs keep their established uppercase
form; content files and directories are kebab-case; code follows its language.
Full conventions live in `docs/process/NAMING.md`, if you keep one.

## 9. Gotchas

Debugging war stories are deliberately out of boot context. Read and extend
`docs/GOTCHAS.md` when a symptom is surprising; format:
**symptom -> cause -> prevention**.
