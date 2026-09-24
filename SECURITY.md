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

- a website, or another machine on your network, read or change the farm
  dashboard without its token;
- request data reach a shell or a program's arguments in a way that runs a
  command nobody asked for;
- a secret (a token, a key, a login) end up in a log, a dashboard page or a
  pull request;
- the installer or the plugin download and run something other than what its
  documentation says.

## What murmur does not protect against

murmur is a way to organise agents. It is not a sandbox. Please keep these
limits in mind:

- **Agents run with your permissions.** Every agent on a farm runs as the same
  Unix user, with that user's files, keys and logins. A worktree keeps agents
  out of each other's way; it does not lock them in.
- **The head office trusts names.** `hq` records the name an agent gives. An
  agent that wants to can use another agent's name or read another agent's
  mail. `hq` prevents accidents between cooperating agents, not attacks.
- **The farm's machine key opens the machines it creates.** The key the farm
  uses for DigitalOcean Droplets it creates is stored in the farm user's home,
  so every agent on the farm can read it.

So run only agents and tasks you trust on a farm, and give the farm's GitHub
login access only to the repositories it needs.

## Supported versions

murmur is young and has no stable release yet. Fixes go into the `main` branch.
Please check that the problem still exists on the latest `main` before you report it.
