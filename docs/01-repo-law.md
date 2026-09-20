# Repo law

## One file that says how work happens

Every repository running this method has exactly one file that says how work
happens. Call it the law file. It sits at the repository root, and it is the
first thing every agent reads.

The law file is not documentation of the code. It says what a change must be
before it is allowed to land: what it contains, who checks it, what is
forbidden outright.

A complete example to copy is [`templates/CLAUDE.md`](../templates/CLAUDE.md).
This chapter explains the choices inside it.

## The boot contract

Open the law file with a numbered read order, and nothing else. Four or five
documents, each with one line saying what it is for: the law
itself, the architecture as it is actually deployed, a product briefing, an
index that routes to everything else, and at most one subject document covering
the work that keeps going wrong.

Then state the rule explicitly. Anything not on that list is loaded on demand
through the index. Historical plans and archived design records are never
loaded at the start of a task.

**The incident behind it.** A boot list that grows stops being read. Once the
opening instruction runs past a screen, agents skim it, and the rules near the
bottom become rules nobody follows. If you want a new document read at boot,
something else comes off the list.

## Law lives here, everything else links

Write each rule exactly once, in the law file, and have every other document
link to it.

A rule copied into two places will drift, and the copy that goes stale is the
one somebody follows by accident. If you catch yourself writing "as the law
file already says" followed by a paraphrase, keep only the link.

This is also why the law file should be shorter than you expect. It holds
rules, not explanations. Reasoning and per-subject detail live in linked
documents nobody reads until they need them.

## The core contract

Put it at the top of the process section, as a sentence an agent can check
itself against. One batch, one worktree, one branch, commits per reviewable
slice, one pull request, green checks, a squash merge through the queue, then
the worktree is removed.

Nothing lands on `main` directly.

The lane drives the batch end to end. It stops for exactly three things: a real
blocker, a check failing for a reason its own change did not cause, and an
action that needs explicit approval.

Then the veto. A `hold` label on a pull request always blocks the merge, no
matter how green everything looks. Anyone may add the hold label. Only the
owner removes it. The automation treats it as absolute rather than as a
warning.

## Commits

Fix a grammar and state it in one line: `Type: subject`, imperative,
capitalized type, no full stop at the end. A short closed list of types is
enough (`Feat`, `Fix`, `Docs`, `Build`, `Review`, `Cleanup`).

Then add the check that matters more. Before every commit and every push, print
the current branch and the short status.

**The incident behind it.** Work has landed on the wrong branch for want of a
two second check. An agent running for an hour holds a stale idea of where it
is, especially after a merge or a move between worktrees. Reading the branch
name back catches a mistake that is painful to unwind.

## Hard rules worth copying

These transfer to almost any stack:

- Everything committed is in one language. Name the single exception if you
  have one.
- Never commit build artifacts or plaintext secrets. Never print a secret
  value: compare hashes instead.
- Shared logic has one authoritative implementation. A second one lands only in
  the change that deletes the first, or with a dated ticket to kill it.
- A missing key disables a capability, it never prevents the system starting.
- Every bug-fix change carries the test that fails without the fix, and states
  the root cause in words.
- Never switch off a shipped user-facing capability as a "fix". Removing a
  feature is a product decision, and it needs the `<OWNER>`'s approval.
- Screenshots are evidence, never measurement. A golden-image test is the
  measuring instrument.
- The twice rule: the second time the same mistake happens, the correction
  enters the law file or the lessons file in the change that fixes it.
- Destructive actions and paid provisioning need approval scoped to the action.
  When a safety mechanism blocks you, assume it is right until proved wrong.

## Hard rules to replace with your own

The template closes its rules section with a marked block for stack-specific
law. Replace that block wholesale. Typical entries: the allowed direction of dependency between layers, enforced
by a linter rather than by review; the single sanctioned way to build interface
surfaces, and what ships with every visual change; what may change about
prices, keys, and payment paths, and whose approval it needs.

Each one passes the same test: can a machine check it? A rule nobody can check
is a preference, and preferences do not belong in a law file.

## Don'ts

One short paragraph of flat prohibitions, phrased so they can be quoted back.
Do not commit to `main`, reuse a merged branch, merge red checks, force-push
shared work, skip the commit hooks, bundle an unrelated refactor into a fix, or
leave a pull request you own unfinished.

The list repeats rules stated above, deliberately. It is what an agent scans
in the second before doing something risky.

## Freeze state

Put a line in the law file saying whether a feature freeze is on. Write it even
when the answer is no: no freeze is active unless the `<OWNER>` declares one
here, in this file. Freezes get announced in chat or in a plan document, and
then agents infer one from a stale note weeks later and quietly stop shipping.
The state of the freeze is only true where the law is.

## Naming

Two or three lines are enough. Numbered records get a fixed pattern, standard
documents keep their uppercase names, content files and directories are
kebab-case, code follows its language. Link out for anything longer.

## Adopt it in a day

1. Copy [`templates/CLAUDE.md`](../templates/CLAUDE.md) to your repository root
   and replace every placeholder.
2. Cut the boot read order to five entries, and write the sentence saying
   everything else is loaded on demand.
3. Delete every rule you are not willing to enforce. A law nobody enforces
   teaches agents that laws are optional.
4. Optional, when you already have a pile of documents: grep them for rules
   that repeat the law file, and replace each copy with a link.

The stack-specific block can wait for week two. Getting one honest law file in
place matters more than finishing it.
