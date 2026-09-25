# Repo law

Every repository that uses this method has one law file: the file that says how
work happens. It is the first thing every agent reads.

- **With the murmur plugin**, the core rules live in `.murmur/contract.md`.
  `/murmur:init` writes it from your answers. It also makes `CLAUDE.md` point to
  it, and `AGENTS.md` too if you keep one. Your other rules stay in `CLAUDE.md`.
- **Without the plugin**, write the rules in `CLAUDE.md` at the repository root.
  Claude Code reads that file at the start of every session. If you also use
  Codex, which reads `AGENTS.md`, make `AGENTS.md` point to `CLAUDE.md`.

The law file does not document the code. It says what a change must be before it
may land: what it contains, who checks it, and what is forbidden. A complete
example to copy is [`templates/CLAUDE.md`](../templates/CLAUDE.md). This chapter
explains the choices in it.

## Keep the reading list short

The template opens with a numbered reading list: what to read at the start of
every task, and nothing else. Keep it to five entries or fewer, each with one
line saying what it is for:

1. the law file itself;
2. the architecture as it is deployed;
3. a product briefing;
4. an index to everything else;
5. one or two documents for the kind of work that keeps going wrong.

Only the law file is required. Delete any line whose document you do not keep:
a list that names a missing file teaches the agent to skip the list. Then say
plainly that everything else is read only when needed, through the index. Old
plans and archived design records are never read at the start.

**What goes wrong without it.** A reading list that grows stops being read.
Once it runs past a screen, agents skim it, and the rules near the bottom stop
being followed. To add a document, take another one off.

## Write each rule once

Write each rule once, in the law file, and link to it from everywhere else. A
rule copied into two places drifts, and somebody follows the stale copy by
accident. If you catch yourself writing "as the law file says" and then a
paraphrase, keep only the link.

So the law file holds rules, not explanations. Reasons and detail live in
linked documents that people read when they need them.

One exception: the template repeats the writing rules from
[writing for humans](09-writing-for-humans.md), because an agent reads the law
file before it follows any link.

## The core contract

Put this at the top of the process section, as sentences an agent can check
itself against:

- One batch (one coherent change), one worktree (a separate working copy), one
  branch, a commit per reviewable slice, one pull request, green checks, a
  squash merge through the merge queue, then the worktree is removed.
- Nothing lands on `main` directly.
- The lane (the agent doing the task) drives the batch until its pull request
  is ready to merge. It stops before that for three things only: a real
  blocker, a check failing for a reason its own change did not cause, and an
  action that needs explicit approval.
- The owner decides what merges. After the owner's yes, the conductor (or the
  orchestrator, if there is no conductor) merges it. Lanes never merge.
- The `hold` label is the veto: a pull request with it never merges, however
  green its checks. Anyone may add the label. Only the owner removes it.

GitHub does not stop a merge because of a label, so enforce the veto with a
small required check that fails while the label is present.
[`templates/github/hold-check.yml`](../templates/github/hold-check.yml) is one;
[CI and merge](06-ci-and-merge.md#the-hold-label-is-the-veto) explains it.

## Commits

State one commit format in one line: `Type: subject`, with a capitalized type,
an imperative subject and no full stop at the end. A short, fixed list of types
is enough: `Feat`, `Fix`, `Docs`, `Build`, `Review`, `Cleanup`.

The check that matters more: before every commit and every push, print the
current branch and the short status.

```bash
git branch --show-current
git status --short
```

**What goes wrong without it.** After an hour of work, especially after a merge
or a move between worktrees, an agent has an old idea of where it is. Its next
commit lands on the wrong branch. Reading the branch name back takes two
seconds. Undoing the mistake takes much longer.

## Hard rules worth copying

These work in almost any stack:

- Everything committed is in one language. Name the single exception, if any.
- Never commit build artifacts or plaintext secrets. Never print a secret
  value: compare hashes instead.
- Shared logic has one authoritative implementation. A second one lands only in
  the change that deletes the first, or with a dated ticket to remove it.
- A missing key turns off one capability. It never stops the system starting.
- Every bug-fix change carries the test that fails without the fix, and states
  the root cause in words.
- Never switch off a shipped, user-facing capability as a "fix". Removing a
  feature is a product decision, and it needs the owner's approval.
- Screenshots are evidence, never measurement. A golden-image test, which
  compares the screen with a stored reference image, does the measuring.
- The twice rule: the second time the same mistake happens, the correction goes
  into the law file or the lessons file (`docs/GOTCHAS.md`), in the change that
  fixes it.
- Destructive actions and paid provisioning need approval for that exact
  action. When a safety mechanism blocks you, assume it is right until you have
  proved otherwise.

## Rules to replace with your own

The template ends its rules with a marked block for your stack. Replace it
entirely. Typical entries:

- which layers may depend on which, enforced by a linter rather than by review;
- the only allowed way to build the user interface, and what ships with every
  visual change;
- what may change about prices, keys and payments, and whose approval that
  needs.

Each rule must pass one test: can a machine check it? A rule nobody can check
is a preference, and preferences do not belong in a law file.

## Don'ts

Close with one short paragraph of flat prohibitions that can be quoted back.
For example: do not commit to `main`, reuse a merged branch, merge red checks,
force-push shared work, skip the commit hooks, bundle an unrelated refactor into
a fix, or leave a pull request you own unfinished.

This repeats rules from above, and that is intended: it is what an agent scans
in the second before it does something risky.

## Freeze state

Add a line saying whether a feature freeze is on, even when the answer is no:
"No feature freeze is active unless the owner declares one here, in this file."

**What goes wrong without it.** A freeze is announced in chat or in a plan.
Weeks later an agent finds the stale note, assumes the freeze still holds, and
quietly stops shipping. Only the law file decides whether a freeze is on.

## Naming

Two or three lines are enough. Numbered records follow a fixed pattern (the
template uses `NNNN-type-kebab-title.md` for decision records). Standard
documents keep their usual uppercase names, other files and directories are
kebab-case, and code follows its language. Link out for anything longer.

## Adopt it in a day

1. Start from the template. Without the plugin, copy
   [`templates/CLAUDE.md`](../templates/CLAUDE.md) to your repository root.
   With the murmur plugin, run `/murmur:init`. It writes `.murmur/contract.md`
   with the template's core sections (core contract, the ten gates, commits,
   don'ts) filled in from your answers. If you have no `CLAUDE.md`, it also
   writes one from the template. If you have one, it adds a four-line pointer
   to the contract at its end. It adds the same pointer to `AGENTS.md`, if you
   keep one. If a rule then appears in both files, keep it in the contract and
   delete it from `CLAUDE.md`.
2. Replace every placeholder that is left.
3. Cut the reading list to five entries or fewer, and add the sentence saying
   everything else is read on demand.
4. Delete every rule you are not willing to enforce. A law nobody enforces
   teaches agents that laws are optional.
5. Optional, if you already have many documents: search them for rules that
   repeat the law file, and replace each copy with a link.

The stack-specific block can wait for week two. A short law file you enforce
matters more than a complete one.
