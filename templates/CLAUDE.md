<!--
Template: the repository law file. Copy it to the root of your repository as
CLAUDE.md, or let /murmur:init write it. Replace every <PLACEHOLDER>, and name
your tracker in the "Tracker discipline" section. Delete what you do not run.
Keep only the rules you will enforce: a rule nobody enforces teaches agents
that rules are optional.
-->

You are working in `<ORG>/<REPO>`. The product is called **`<PRODUCT>`**.
Write the name exactly that way in anything a user reads.

This file says **how work happens** here. If the murmur plugin set up this
repository, the core rules are in `.murmur/contract.md`, and this file points
to it at the end. Every other document named below is optional:

- `ARCHITECTURE.md`, if you keep one, describes what is live on `main`.
- `AGENTS.md`, if you keep one, explains the product and its users to agents.
- `docs/adr/`, if you keep it, holds the technical decisions (ADRs,
  architecture decision records).

## Reading list

<!-- Only item 1 is required. DELETE every line whose document you do not keep.
     A reading list that names a missing file teaches the agent to skip the
     list. -->

At the start of a task, read these in order, and nothing else:

1. [`CLAUDE.md`](CLAUDE.md): the process law (this file), and
   `.murmur/contract.md` if the murmur plugin wrote one.
2. `ARCHITECTURE.md`, if you keep one: the architecture as it is deployed now.
3. `AGENTS.md`, if you keep one: the product, the customers, and orientation
   for agents.
4. `docs/INDEX.md`, if you keep one: it sends you to the reference for your
   task.
5. `<DOC>` before `<KIND OF WORK>`: one or two entries at most.

Load everything else only when you need it, through the index if you keep one.
Do not load old plans or archived design records at the start of a task. A
reading list that grows stops being read.

**Knowledge base:** `docs/knowledge/`, if you keep it, has one file per domain:
where the truth lives, the rules that must hold, measured numbers, how to
debug, and past defects. Before you work on a subject that has a file there,
read that file.

## Team

The people live in this table. Keep it short and current.

| Name | Role | Owns | Reviews |
|---|---|---|---|
| `<OWNER>` | product owner | what we build, product acceptance | anything a user sees |
| `<CTO>`, if you have one | technical owner | architecture, guidelines, infrastructure | changes to the architecture |
| `<CONDUCTOR>`, if you have one | release manager | the merge queue, CI health, deploys | holds the merge veto |
| `<NAME>` | `<ROLE>` | `<AREA>` | `<WHAT>` |

In this file, "the owner" means `<OWNER>` unless a rule says otherwise. Lane
assignments and merge coordination live in `docs/process/TEAM_LANES.md`, if
you keep one. A lane is one agent doing one task on its own branch.

## Communication rules

Every report, pull request body, issue and message an agent writes follows
four rules:

- **Use simple words.** A technical term is fine. A wall of code names is not.
- **Write as a person**, not as a machine printing its parameters.
- **Give enough context for a fast decision.** The reader did not watch you
  work. Say what a thing is before you refer to it.
- **Pick one house style rule that a machine can check**, and enforce it in CI.
  When existing text breaks it, fix the text instead of adding exceptions. Any
  rule you really enforce works. A rule nobody checks is not a rule.

### Writing to a person

Most readers here do not have the code in their head. A status, a report, an
issue description, a pull request body for someone who did not write the code:
each one must be understood on the first read. These are checks, not
preferences.

1. **Meaning first.** The first two or three sentences say what happened, what
   it means for the user, and what needs deciding. No preamble. Do not retell
   your process.
2. **One idea per sentence, about fifteen words.** No nested clauses, no
   semicolons, no chains of dashes or arrows.
3. **No names from the code in the prose**: no functions, events, flags, files,
   branches or hashes. They go at the end, in a block for engineers. In the
   text, use words: write "the server held the answer for ten seconds", not an
   event name.
4. **Explain every term the first time you use it**, in one phrase, or use an
   everyday word instead. The test: would a sharp friend who is not an engineer
   follow it?
5. **Round numbers, and compare them**: "it was ten seconds, now it is none".
   Milliseconds and percentiles go in a table for engineers. Use at most one
   number per sentence in the prose.
6. **No metaphors from this codebase.** A word like gate, seam or ledger means
   something only to someone who has read the code. Say what the mechanism
   does.
7. **Keep list items to one or two sentences. Keep tables to at most five
   columns and at most eight words per cell.**
8. **Length.** A chat status stays under 120 words. An issue description stays
   under half a screen, plus its block for engineers. Anything longer opens
   with a paragraph headed "In short".
9. **Every long text has the same shape**: what happened, what it means, what
   to decide or what happens next, the numbers in a small table, then the block
   for engineers with names, paths and links.
10. **Read it back as the reader before you send it.** If a sentence needs
    knowledge of the code to understand, rewrite it in words or move it to the
    block for engineers.

Everything committed here is in English, including these reports.

## Design principles

**KISS and DRY, in balance.** Keep every design as simple as it can be (KISS:
keep it simple). Give shared logic one authoritative home (DRY: do not repeat
yourself; see the second-implementation law below). When the two pull in
different directions, choose the simpler design: a small, visible duplication
is better than a clever abstraction. Extract shared code when the second
*real* user of it arrives, not before.

## Architecture governance

### The pattern catalog

`docs/architecture/PATTERNS.md`, if you keep one, is the closed list of the
mechanisms this repository already uses. Look at the repository first, and
reuse a pattern from the list.

- A reasonable extension of an approved mechanism, of the same complexity, goes
  ahead without approval.
- If an urgent extension may or may not fit, record it in
  `docs/architecture/PATTERN_FLAGS.md`, if you keep one, and go ahead.
  `<CTO>`, if you have one, reviews it later. The flags file lets urgent work
  continue without anyone quietly ignoring the catalog.
- A clearly new way for components to communicate, a new architectural
  mechanism, or a real increase in complexity needs approval from `<CTO>`, if
  you have one. It lands as a catalog entry plus an ADR.
- **Waiver:** until `<VERSION>`, the owner waives this approval. Record the case
  in the flags file and go ahead. The review happens later instead of blocking
  the work. Say here when the waiver ends.

### Owner gate: product and visual review

This review happens in parallel and never blocks a merge. A pull request with
a change users can see carries the `design-review` label and this line in its
body: `Review with <OWNER>`. The label stays until the owner has looked. The
owner reviews a picture or a live link, never a diff.

### Testing standard

`docs/TESTING.md`, if you keep one, is the testing contract, and the test suite
enforces it. Put each check at the lowest level that proves it. Use real
collaborators. Use fakes only at true boundaries, such as an outside provider
or the network, and assert on those fakes. Service and flow tests make up most
of the suite. End-to-end journeys are a thin layer on top. Every feature gets a
pass for edge cases. Every widget gets a pass for missing states, and each of
its states is designed, tested, or explicitly waived.

### Freeze state

No feature freeze is active unless the owner declares one here, in this file,
and not in another document. Never assume a freeze because a plan mentions one.

## 0. Core contract

- One batch, one worktree, one branch, commits per slice, one pull request,
  green CI, a squash merge through the merge queue, then remove the worktree.
  A batch is one coherent change. A worktree is a separate working copy of the
  repository, made with `git worktree add`.
- Nothing lands directly on `main`.
- The lane (the agent doing the task) drives the batch until its pull request
  is ready to merge. Stop before that only for a real blocker, for red CI that
  the batch did not cause, or for an action that needs explicit approval.
- The owner decides what merges. After the owner's yes, the conductor (or the
  orchestrator, if there is no conductor) merges it. A lane never merges.
- The `hold` label is the veto: it always blocks a merge. Anyone may add the
  `hold` label. Only the owner removes it.

## 1. Repo and contract map

Development setup and everyday commands are in `README.md`. Build artifacts are
never committed.

```text
<PATH>/        <what lives here>
<PATH>/        <what lives here>
docs/          laws, references, archive
infra/         infrastructure and deploy config
.github/       CI, preview, deploy
```

Name the wire contract here: the versioned API, its field casing, its error and
pagination shapes, and the rule that generated clients and schemas are always
regenerated, never edited by hand. Name the main domain nouns and how they
nest, in one line, so no agent invents a second vocabulary.

## Big work protocol

A new project, a large refactor or a large push to finish something does not
start with code. It starts with three things, in this order:

1. **The tracker.** The work gets a project with milestones, and large,
   coherent issues: one per major chunk. The tracker is updated as the work
   moves.
2. **Design doc.** Before implementation, a design record lands in
   `docs/design/<slug>.md`, if you keep that directory. It states the intent,
   the boundaries, the mechanism, the risks, and what is explicitly out of
   scope. Decisions that shape the architecture also get an ADR.
3. **Design doc review.** The doc is reviewed before any code is written. An
   independent reviewer (not the author) looks for everything wrong with it.
   `<CTO>`, if you have one, reviews anything that shapes the architecture. The
   owner reviews anything that shapes the product. The findings are resolved
   in the doc. Only then do lanes start.

Small batches (a fix, one screen, one contract change) skip this protocol and
go straight to the Golden Workflow.

## Tracker discipline

**Tracker:** `<TRACKER>`. How to take a task, link a pull request and post
evidence there is in `.claude/tracker.md`, if you keep one. With no tracker,
the pull request is the record, and that file says how the rules below apply
to it. A separate tracker gives the project view over this repository: the work
itself is tracked there, while bugs and tech debt that belong to this
repository may stay in its GitHub issues.

- **Taking a task means the task exists in the tracker.** If the work started
  in chat, create the issue before you start. The status moves **with** the
  work: In Progress when it starts, the pull request linked when it opens, Done
  on merge.
- **The issue shows who is on it.** The owner stays the assignee. The agent
  doing the work adds its own label from an `Agent` label group: one label per
  code name, and you add a code name when it is missing. Taking a task means
  the agent label on the issue, plus a comment saying who took it and when.
- **Three resting states.** An issue with an agent's label stays that agent's
  until it rests in exactly one of three states. **Done**: merged, verified,
  and the acceptance comment posted. **In Review**: nothing is left for an
  agent, and the last comment names the owner's exact next step. **Backlog**:
  nobody is working on it, and the last comment says what landed, what did
  not, and what picking it up means. Before signing off, an agent leaves every
  issue with its label in one of these three states. This rule prevents issues
  that sit In Progress for weeks with no branch, no pull request and no
  comment.
- **Issues are large.** An issue is a chunk of work a person could own for a
  day or more, never a micro-task.
- **The issue is where the work is written down**, not chat. Add a short
  comment whenever something important changes (a finding, a blocker, a change
  of scope). When the work lands, add the acceptance evidence: root cause, fix,
  regression test, pull request link. Upload screenshots as tracker
  attachments, so the whole team can open them.
- **Only the owner posts project-level status updates.** Agents write in
  issues.
- **The tracker id goes into the branch name and the pull request title**, so
  the integration can link the two.
- **Everything written in the tracker is in English**, in the simple English of
  the writing rules above.
- Do not create or migrate issues in bulk. The backlog grows when the owner
  asks for work, not from an import.

## 2. Golden Workflow: 10 gates

1. If the team records branch claims, claim the branch first. Branch from a
   fresh `main` in a new worktree. Never reuse a merged branch.
2. Build one coherent batch, and commit each reviewable slice.
3. Keep the docs current in the same pull request, for whichever of these you
   keep. A change to a key API or data contract, or a major architecture
   decision, updates `ARCHITECTURE.md` and adds an ADR. Adding, moving or
   retiring a document updates `docs/INDEX.md`. **Before merge, check
   `docs/knowledge/`**: if the batch changes how a subsystem really behaves
   (mechanism, capacity, cost, timing, procedure), update the matching domain
   file in this pull request.
4. If users will notice the change, add a note in
   `RELEASE_NOTES.d/<category>-<slug>.md`. Otherwise, write "no user-visible
   change" in the pull request.
5. Run the affected lint, tests, build and contract checks locally.
6. When `main` moves while you work, merge `origin/main` into your branch and
   rerun the affected checks.
7. Open the pull request with `.github/PULL_REQUEST_TEMPLATE.md`, the only pull
   request template.
8. Run an adversarial review of the exact head commit: a second agent whose job
   is to find what is wrong, ideally a different model or vendor. It ends with
   one line, `VERDICT <sha> CLEAN` or `VERDICT <sha> RED`. Use the deeper
   review for auth, security, migrations, durability, or encrypted user
   content.
9. Fix every in-scope finding in the same pull request. File a scoped issue for
   real out-of-scope work.
10. Green checks make a change eligible to merge. Only the owner's yes decides
    it. After that yes, the conductor (or the orchestrator, if there is no
    conductor) turns on auto-merge. A lane never does. Never bypass a required
    check with an admin override. Before cleanup, confirm that GitHub reports
    the pull request as merged.

## 3. Commits

Write commit messages as `Type: subject`, in the imperative, with a capitalized
type and no full stop at the end. Types: `Feat:`, `Fix:`, `Review:`, `Docs:`,
`Build:`, `Cleanup:`. Right before every commit or push, check the current
branch and `git status --short`. This two-second check stops pushes to the
wrong branch.

## 4. Worktrees and parallel work

- One batch, one worktree, one branch, one pull request. Each worktree gets its
  own environment. Installed dependencies are tied to their path, so a copied
  environment silently imports a neighbour's code. After merge, remove the
  worktree and the branch. Never continue work by rebasing a merged branch.
- Lanes own separate paths. Never edit outside your manifest (the list of paths
  your lane may touch). Shared files that only grow, such as lists and
  inventories, cause collisions: split them before parallel work. One file per
  change is better than one shared list.
- Reserve ADR and migration numbers at the start of a batch. Scan `main` and
  every open pull request, not just your own tree. `scripts/next_number.sh`,
  if you copied it from the murmur templates, does this scan.
- When two parents changed one file, diff the merge against both parents and
  confirm that each named change survived. A clean automatic merge can still
  lose work.
- Grouped lanes are assembled into one integration pull request. A conflict
  during assembly means the collision check did its job. It is not an
  accident.
- The merge queue puts changes into `main` one after another, in order. It does
  not replace lane isolation.

The incidents behind these rules are in `docs/GOTCHAS.md`.

## 5. CI, protection, deploy

- CI must run what production runs. Renaming a required job changes the name
  of its check, so update branch protection in the same step. Look at the live
  protection settings before you change them. Never trust an old snippet.
- A merge to `main` is a production deploy within minutes, so merge only
  complete, releasable states. Migrations run before the new code starts. The
  app checks the schema when it starts, and stops with a clear error when the
  schema is wrong. It never migrates itself.
- A self-hosted or local CI run makes checking faster. It is **never a merge
  authority**: the hosted, protected checks decide. The merge queue tests
  `main` plus the candidate together, because two branches that are green on
  their own are not a green merge. If a local result ever disagrees with the
  hosted result for the same commit, the hosted result wins, and you report the
  difference clearly.
- There are no releases: every merge ships. Never bump a version or cut a
  release.

## 6. Hard rules

- Everything committed to the repository is in English. If there is an
  exception, name it here (for example, translation catalogs that a machine
  checks).
- Never commit build artifacts or plaintext secrets. Deployment secrets go only
  through the encrypted secret path. Rotate a secret immediately after it is
  exposed. Never print a secret value: compare hashes instead.
- One migration per batch that changes the schema. Migrations follow expand and
  contract: add the new shape first, remove the old one later. Every migration
  stays compatible with the code that is deployed now.
- **The second-implementation law (DRY):** shared logic has one authoritative
  implementation. A second implementation of an existing capability lands only
  in the same pull request that deletes the first one, or with a dated ticket
  to delete it.
- Capabilities depend on keys: a missing key turns the capability off, and
  never stops the app from starting.
- Sensitive user content is encrypted at rest. Structural metadata stays in
  plain text only where a written contract says so.
- New and migrated behavior must be correct when several replicas (copies of
  the service) run at once. Never rely on correctness inside one process for
  sockets, tasks, locks, schedulers or ownership.
- **Never switch off a shipped user-facing capability as a "fix".** Hiding or
  removing a feature is a product decision, not a bug fix. First prove the
  diagnosis against the live flow: reproduce the failure, and trace the real
  data path from end to end. Then the owner must explicitly approve that exact
  outcome. Rewriting a test to expect the feature's absence hides the
  regression from the test suite. A wrong diagnosis that turns off a working
  feature is a top-severity incident.
- Every bug-fix pull request contains the regression test that fails without
  the fix, and states the root cause.
- Screenshots and design canvases are evidence, never a source of
  measurements. A golden-image test (one that compares the screen with a saved
  reference image) is the tool for visual regressions.
- **The twice rule:** when an agent makes the same mistake twice, the
  correction goes into this file or `docs/GOTCHAS.md`, in the pull request that
  fixes the second occurrence. A lesson that stays in chat is lost.
- No speculative abstractions, flags or compatibility shims.
- Comments answer "why", not "what", and do not narrate the current task.
- Destructive actions and paid provisioning need explicit approval for that
  one action. Production is read-only by default. When a safety mechanism
  blocks you, assume it is right until you have proved otherwise.

<!-- Add your stack-specific laws here. For example: layer arrows (the allowed
     direction of dependencies between layers, enforced by a linter); the
     design system (the only way to build UI, and the story or snapshot that
     ships with every visual change); money (what may change about prices,
     keys, enforcement or checkout, and whose explicit approval it needs);
     language ratchets (for example: every new file in a converted directory
     uses the target language). -->

## 7. Don'ts

Do not commit to `main`, reuse merged branches, merge red CI, force-push shared
work, skip the commit hooks, bundle an unrelated refactor into a fix, bump a
version, or leave a pull request you own unfinished. Do not amend after a
failed commit hook: that commit was never made, so the amend would change the
previous commit.

## 8. Naming

ADRs are named `NNNN-type-kebab-title.md`. Standard documents keep their usual
uppercase names, such as `README.md`. Content files and directories use
kebab-case. Code follows the conventions of its language. The full conventions
are in `docs/process/NAMING.md`, if you keep one.

## 9. Gotchas

Debugging stories are kept out of the reading list. When a symptom surprises
you, read `docs/GOTCHAS.md` and add to it. Each entry reads
**symptom -> cause -> prevention**.
