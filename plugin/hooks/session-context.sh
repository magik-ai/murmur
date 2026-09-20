#!/usr/bin/env bash
# SessionStart hook: put the team's laws in front of the agent before it acts.
#
# A plugin cannot ship a CLAUDE.md, so the short version of the law is injected
# here instead, at startup, resume, clear and compact.
#
# A repository can replace this text wholesale: write your own short version to
# ${CLAUDE_PROJECT_DIR}/.claude/team-laws.md and it is used verbatim.
set -euo pipefail

custom="${CLAUDE_PROJECT_DIR:-.}/.claude/team-laws.md"

if [ -f "$custom" ]; then
  context=$(cat "$custom")
else
  context=$(cat <<'LAWS'
# How this team works (short version)

The full text is the handbook in `docs/`. These are the lines that do not bend.

**Work shape.** One batch, one worktree, one branch, one pull request. A batch
is one coherent change, committed in reviewable slices.

**Nothing lands on the main branch directly.** Every change goes through a pull
request and the merge queue. A merge is a deployment, so merge only complete,
releasable states.

**Claim before you touch.** Before creating or pushing a work branch, claim it
where the team records claims. A refused claim means the branch is someone
else's: message its owner, never work around the claim. Never merge into,
rebase or push another agent's claimed branch.

**Identity is per session.** Your code name comes from the owner or from your
spawner, never from memory, a document or a neighbour. Without a name, ask for
one. Asking is the handshake that shows you know the protocol.

**Never bypass a required check with admin rights.** Not when it is urgent, not
when the check is wrong, not at 3am. Fix the check or ask the owner.

**Never merge red.** A green result on an earlier commit is not green. A locally
run pipeline is speed, not permission.

**Never switch off a shipped capability as a fix.** Hiding or removing a feature
is a product decision. Prove the diagnosis against the live flow first, and get
the owner's explicit approval for that exact outcome.

**The twice rule.** Make the same mistake twice and the correction is written
into the team's law or lessons file, in the same change that fixes the second
occurrence. A lesson that stays in chat is a lesson lost.

**Write to a person.** Meaning first, one idea per sentence, no names from the
code in the prose. Names, paths and links go in a block at the end.

Everywhere: chat, pull requests, issues, documents and product copy.
LAWS
)
fi

python3 -c "
import json, sys
print(json.dumps({'hookSpecificOutput': {
    'hookEventName': 'SessionStart',
    'additionalContext': sys.stdin.read(),
}}))
" <<EOF
$context
EOF
