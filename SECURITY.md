# Security policy

murmur runs coding agents on your machine and pushes code with your GitHub
credentials. We take security problems in it seriously.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Report it privately on GitHub instead:

1. Open <https://github.com/magik-ai/murmur/security/advisories/new>.
2. Describe the problem, how to reproduce it, and what an attacker could do with it.

Only the maintainers can see the report. We will reply there, keep you informed
while we work on a fix, and credit you in the release notes unless you prefer
otherwise.

## What counts as a security problem

For example, anything that lets:

- an agent act outside its own worktree or its task's files;
- an agent claim or push a branch under a name it does not own;
- an agent read another agent's mail;
- someone use the farm dashboard without its token, or from another website;
- a secret (a token, a key, a login) end up in a log, a dashboard page or a
  pull request.

## Supported versions

murmur is young and has no stable release yet. Fixes go into the `main` branch.
Please check that the problem still exists on the latest `main` before you report it.
