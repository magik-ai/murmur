---
name: heavy-runs-belong-on-the-build-host
description: "The owner's laptop froze on 2026-02-14 while one session ran five research helpers that each fanned out further. His ruling: heavy, parallel or long work runs on the shared build host, and the laptop session stays small."
metadata:
  type: feedback
---

**What happened (2026-02-14, on the owner's laptop):** I started five research helpers
at once to survey competitor booking flows, and each of them started more. Roughly twenty
processes were sweeping the web and reading the repository at the same time, next to a
review helper. The machine locked up for several minutes. His words afterwards: put the
big things on the build host, do not burn the laptop, keep the chat light.

**Why it matters:** local helpers all run on the laptop, and the laptop is the machine he
works and demos on. The build host exists for exactly this, and a crash there costs
nobody anything.

**How to apply:** parallel research, adversarial reviews, full test suites and anything
long go to the build host as lanes. Keep local helpers to at most one small, bounded job,
and only when the host is unreachable. Push before handing work over, because the lanes
fetch from the remote and a reboot wipes scratch directories.

Related: [[kill-by-port-never-by-name]], [[the-heartbeat-dies-with-the-session]].
