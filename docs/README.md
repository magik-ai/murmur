# Handbook

The handbook explains the method behind murmur: how to run several coding agents on one repository as a team. Read the chapters in order. Each one gives a rule, the reason for it (often a real incident) and a short list for adopting it in a day. Fill-in files for your own repository are in [`templates/`](../templates/).

- [00 Start here](00-start-here.md): the four roles, the law file, a plan for your first week, and the words this handbook uses.
- [01 Repo law](01-repo-law.md): how to write the file that says how work happens in your repository.
- [02 The golden workflow](02-golden-workflow.md): the ten steps one change passes through, from a fresh branch to a merge.
- [03 Parallel lanes](03-parallel-lanes.md): how several agents work at once without editing the same files. A lane is one agent doing one task on its own branch.
- [04 Orchestration](04-orchestration.md): the orchestrator, the agent that splits the work, decides who touches which files, and writes no product code.
- [05 Coordination and identity](05-coordination-and-identity.md): agent names, branch claims and messages through the head office, a private GitHub repository the agents share.
- [06 CI and merge](06-ci-and-merge.md): why two branches that each pass their checks can still break main together, how a merge queue helps, and what to do when main fails.
- [07 Testing and evidence](07-testing-and-evidence.md): where each test belongs, what a bug fix must include, and where the proof of finished work goes.
- [08 Knowledge and memory](08-knowledge-and-memory.md): where lessons, domain knowledge and agent notes are written, so nothing is learned twice.
- [09 Writing for humans](09-writing-for-humans.md): how agents write reports and questions that a busy person understands on the first read.
- [10 Unattended runs](10-unattended-runs.md): night mode, where an agent finishes open work while nobody watches and reports in the morning.
- [11 Safety hooks](11-safety-hooks.md): scripts that stop common mistakes before they happen, and the rules for secrets and production.
- [12 The machine](12-the-machine.md): for the person who chooses and pays for the farm, the always-on machine that runs agents. It covers whether you need one, what it costs and how to set it up.
- [Lessons from the field](lessons-from-the-field.md): ten real failures from running agents, each with what happened, why, and what to do.
