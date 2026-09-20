# Start here

## The thesis

Running one coding agent is easy to manage. You type a prompt, you watch it
work, you read the diff. Running ten of them at once is not the same job made
bigger. It is a different job. You are running a team now, and a team needs
the things teams have always needed.

The moment a second agent starts touching the same repository, you need
everything a team of humans needs. You need to know who owns which piece of
work, so two agents do not edit the same file at the same time and silently
erase each other's changes. You need a place where the state of the work lives
that is not one person's head, because no single agent (and no single human
watching them) can hold the whole picture in working memory. You need a review
step that is not the same mind that wrote the code, because a writer checking
its own work misses what it was already blind to. You need a merge process
that treats "my branch passed its own tests" as necessary and nowhere near
sufficient, because two green branches can still break each other the moment
they land together.

This handbook is the organizational layer. It is not a wrapper around a model
and it is not a smarter prompt. It is a set of roles, rules, and a small number
of tools that make many agents behave like a team instead of like ten people
shouting into the same room. None of it requires a specific vendor's agent.
Most of it is just discipline that happens to be enforced by a script instead
of by memory, because memory is the first thing that fails under load.

This handbook assumes GitHub for issues, pull requests and the merge queue.
Another host works, but you will need to map the steps onto it yourself.

## The four roles

Every session working in a shared repository plays exactly one of these roles
at a time. Naming the role tells you what you may and may not do.

**Owner.** The person whose product this is. Makes decisions only they can
make: what ships, what a feature should feel like, when a risky change is
allowed to go out. Does not have to read every diff. Should never open a pull
request just to see what changed; a decision this role needs should reach them
as a plain-English question with a recommendation attached, not as a wall of
code.

**Orchestrator.** Does not write product code. Its job is to guard scope so no
two lanes edit the same file, sequence the handful of shared files that every
lane wants to touch, verify a lane's claim before repeating it to the owner,
and keep a shared board honest. If an orchestrator catches itself editing
application code, either the task was small enough to do directly (and did not
need an orchestrator at all) or it has drifted out of its role.

**Lane.** One agent, one unit of work, start to finish: implementation,
self-review, opening the change for review, responding to feedback, and seeing
it merged. A lane owns a slice of the codebase for the life of its task and
touches nothing outside that slice. Wanting to "fix something nearby while I'm
here" is a sign to stop, not an invitation.

**Conductor (or release manager).** Owns the queue: what gets merged, in what
order, and what gets held back. Holds the single veto that can stop a merge
regardless of how green everything looks. Does not implement features and does
not resolve product questions; it enforces the gate.

A team may also name extra approvers, for example a technical owner who signs
off on architecture decisions. Those people are approvers on top of the four
roles, not a fifth role.

## Law lives in one file

Every project running this method has exactly one file that states how work
happens: what a change must include before it merges, what the review steps
are, what is forbidden. Call it the project's law file. Every other document,
including this handbook, links to it instead of restating it.

The reason is simple: a rule copied into two places will drift, and the copy
that goes stale is the one somebody follows by accident. If you find yourself
about to write "as the law file already says" followed by a paraphrase, stop
and link instead. A rule that exists in one place can be trusted the moment you
find it. A rule that exists in three places can be trusted in none of them.

The repository law template repeats the writing rules on purpose, because an
agent reads that file at boot before it can follow a link.

## Week one, in order

Adopt this method gradually. Trying to install all of it on day one produces a
pile of unread rules that nobody follows. One layer a day works better.

1. **Day 1: repo law and a pull request template.** Write the one law file.
   Put a template on every pull request so a reviewer (human or agent) always
   finds the same shape: what changed, why, how it was checked.
2. **Day 2: worktree discipline and a tracker.** One task, one isolated working
   copy, one branch. Every task exists as a ticket in a shared tracker before
   work starts on it, so "what is anyone doing right now" has an answer that
   is not "ask around."
3. **Day 3: review by someone who did not write it.** Every change gets looked
   at by a different mind, human or agent, before it merges. This is the
   single highest-leverage rule in the whole method.
4. **Day 4: a lessons file and the twice rule.** The first time something goes
   wrong, fix it. The second time the same mistake happens, the fix is not
   just code: it is an entry in a lessons file or a line in the law file, so a
   third occurrence becomes structurally harder.
5. **Day 5: first unattended run.** Let one agent complete one small, well
   scoped task from ticket to merged change without a human watching every
   step. Small on purpose. This is the rehearsal for everything longer that
   follows.

## What to read next

Read the golden workflow chapter for the gate-by-gate shape of a single
change. Read the parallel lanes chapter before running more than one agent at
once. Read the coordination and identity chapter before two agents need to
know about each other at all.

## Words this handbook uses

Seven words carry a specific meaning here. Every other chapter uses them as
defined below.

**Gate.** One numbered step in the workflow a change passes through, from
branching to merging. The full list is in
[the golden workflow chapter](02-golden-workflow.md).

**Review verdict.** The one-line answer an adversarial reviewer gives about
one exact commit: `VERDICT <sha> CLEAN` or `VERDICT <sha> RED`. The commit
hash is part of the verdict, because a verdict about an older commit says
nothing about this one.

**Turnstile.** The check in front of a merge queue that refuses an entry whose
own branch run is not green on that exact commit.

**Lane.** One agent doing one unit of work, start to finish, inside a fixed
list of paths it is allowed to touch.

**Spine file.** A file that most changes want to touch, such as a composition
root, a generated interface, or a shared registry. One lane holds it at a
time.

**Head office.** The small shared store that answers who is running, who holds
which branch, and what mail is waiting. It lives in a repository of its own.

**Farm.** A machine you own that runs headless agents. It is optional, and
every rule here works without one.
