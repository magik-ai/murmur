---
name: the-heartbeat-dies-with-the-session
description: "Night of 2026-03-11: five lanes finished and pushed on the build host, but the half-hourly heartbeat that was supposed to collect them never fired, because such timers live inside an open chat session. Nothing was assembled until morning."
metadata:
  type: project
---

**What happened (2026-03-11, an unattended night on the calendar sync work):** I started
five lanes, wrote the plan file, armed background watchers and a half-hourly heartbeat,
then ended my turn and the window closed. Every lane finished and pushed within the hour.
The heartbeat never ran, because these timers only fire while the session that created
them is open and idle, and background watchers die with it too. In the morning the
integration branch still sat at the previous evening's commit, and assembling it by hand
took about two hours.

**Why it matters:** the build host keeps working without anyone watching, but nobody
collects the results, and collection is where the value is: merging the branches, fixing
the tests the lanes broke in each other's areas, and getting a preview in front of the
owner.

**How to apply:** put the collector on the build host itself, as a lane whose job is to
wait for the named branches, assemble, test and report. Say plainly which mechanism is
holding an unattended run and that closing the window stops it.

Related: [[four-lanes-built-the-same-loading-ring]], [[heavy-runs-belong-on-the-build-host]].
