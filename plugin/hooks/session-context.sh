#!/usr/bin/env bash
# SessionStart hook: put the team's laws in front of the agent before it acts.
#
# A plugin cannot ship a CLAUDE.md, so the short version of the law is injected
# here instead, at startup, resume, clear, compact and fork.
#
# A repository can replace this text completely: write your own short version to
# ${CLAUDE_PROJECT_DIR}/.claude/team-laws.md and it is used word for word.
set -euo pipefail

custom="${CLAUDE_PROJECT_DIR:-.}/.claude/team-laws.md"

if [ -f "$custom" ]; then
  context=$(cat "$custom")
else
  context=$(cat <<'LAWS'
# How this team works (short version)

The full text is the murmur handbook:
https://github.com/magik-ai/murmur/tree/main/docs. These rules have no exceptions.

**Work shape.** One batch, one worktree, one branch, one pull request. A batch
is one coherent change, committed in reviewable slices.

**Nothing lands on the main branch directly.** Every change goes through a pull
request, and through the merge queue where the repository has one. A merge is a
deployment, so merge only complete, releasable states.

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
occurrence. A lesson that stays in chat is lost.

**Write to a person.** Meaning first, one idea per sentence, no names from the
code in the prose. Names, paths and links go in a block at the end.

Everywhere: chat, pull requests, issues, documents and product copy.
LAWS
)
fi

# Second block: what this repository answered at init. Skills and docs speak of
# <OWNER>, <TRACKER> and <FARM>; this block says what those words mean here.
config="${CLAUDE_PROJECT_DIR:-.}/.murmur/config.toml"
repo_block=$(python3 - "$config" <<'REPO'
import sys, pathlib
path = pathlib.Path(sys.argv[1])
if not path.is_file():
    print("\n**This repository has not run murmur init yet.** Run `/murmur:init` to"
          " answer seven questions and write the contract. Until then <OWNER> means"
          " the person who gave you your name, <TRACKER> means the pull request, and"
          " there is no <FARM>.")
    sys.exit(0)
try:
    import tomllib
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
except Exception as exc:  # a parse or read failure is reported, never a crashed session
    print(f"\n**Note:** `.murmur/config.toml` could not be read ({exc}). Run `/murmur:doctor`.")
    sys.exit(0)
tracker = cfg.get("tracker", "github-issues")
farm = cfg.get("farm", "not-yet")
coord = cfg.get("coordination", "this-machine")
never = cfg.get("never_without_owner", [])
lines = ["", "# This repository (from `.murmur/config.toml`)", ""]
lines.append(f"- Repository `{cfg.get('repo', '?')}`, work starts from and merges into"
             f" `{cfg.get('base_branch', 'main')}`.")
lines.append("- <OWNER> is the person who runs this repository: the human who gave you"
             " your name this session. The contract is `.murmur/contract.md`.")
if tracker == "none":
    lines.append("- <TRACKER>: there is none. The pull request is the record; how it is"
                 " kept is in `.claude/tracker.md`.")
else:
    lines.append(f"- <TRACKER> is {tracker}. Taking a task, linking the pull request,"
                 " posting evidence and the three resting states: `.claude/tracker.md`.")
if farm == "yes":
    lines.append("- <FARM>: yes, a separate machine runs agents. Heavy work goes there,"
                 " never on the machine hosting this session.")
else:
    lines.append("- <FARM>: none yet. Every worker runs on this machine, so keep the"
                 " number of parallel lanes small.")
if coord == "private-github-repo":
    lines.append("- Branch claims live in a private GitHub repository through the `hq`"
                 " command. Claim before you push; a refused claim is someone else's branch.")
else:
    lines.append("- Branch claims: this machine only. One session works on one branch at"
                 " a time, and the branch name is the claim.")
if never:
    lines.append("- Never without <OWNER>: " + ", ".join(str(n) for n in never) + ".")
print("\n".join(lines))
REPO
)

python3 -c "
import json, sys
print(json.dumps({'hookSpecificOutput': {
    'hookEventName': 'SessionStart',
    'additionalContext': sys.stdin.read(),
}}))
" <<EOF
$context
$repo_block
EOF
