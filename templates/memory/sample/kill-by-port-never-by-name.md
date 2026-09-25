---
name: kill-by-port-never-by-name
description: "Killing a leftover test process by matching its script name on the shared build host also killed the live team dashboard, which ran the same script on another port. Target a port or an identifier you recorded yourself, never a name that other services share."
metadata:
  type: reference
---

**The fact:** on the shared build host, a process name is not an identity. Common script
names, and the interpreters that run them, are also used by other people's live
services on the same machine. Matching the full command line feels more precise, but it
is actually less selective, because it catches every copy of a widely used entry point.

**Why it matters:** on 2026-02-19 I started a second copy of the team dashboard to take
a screenshot of a change. Then I cleaned up by killing everything that matched the
server script. That pattern also matched the dashboard everyone else was using, and the
owner found it dead a few minutes later.

**How to apply:** kill by port, or by an identifier you recorded when you started the
process. Better still, do not run a second copy of a shared service on a shared machine:
serve the page locally instead. After any cleanup on a shared host, check that the
shared services still answer, rather than assuming your command was narrow.

Related: [[heavy-runs-belong-on-the-build-host]], [[the-heartbeat-dies-with-the-session]].
