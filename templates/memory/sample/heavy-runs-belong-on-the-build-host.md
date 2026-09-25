---
name: heavy-runs-belong-on-the-build-host
description: "The owner's laptop froze on 2026-02-14 while one session ran five research helpers that each started more. The owner's decision: heavy, parallel or long work runs on the shared build host, and the laptop session stays small."
metadata:
  type: feedback
---

**What happened (2026-02-14, on the owner's laptop):** I started five research helpers
at once to survey competitors' booking flows, and each of them started more. About twenty
processes were searching the web and reading the repository at the same time, next to a
review helper. The machine locked up for several minutes. The owner's words afterwards:
put the big things on the build host, do not overload the laptop, keep the chat light.

**Why it matters:** local helpers all run on the laptop, and the owner works and gives
demos on that laptop. The build host exists for exactly this kind of work, and a crash
there costs nobody anything.

**How to apply:** parallel research, adversarial reviews, full test suites and anything
long go to the build host as lanes. Keep local helpers to one small, bounded job at
most, and only when the host cannot be reached. Push before handing work over, because
the lanes fetch from the remote and a reboot wipes scratch directories.

Related: [[kill-by-port-never-by-name]], [[the-heartbeat-dies-with-the-session]].
