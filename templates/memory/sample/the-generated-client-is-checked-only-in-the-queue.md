---
name: the-generated-client-is-checked-only-in-the-queue
description: "In this repository the typed client for the booking interface is regenerated from the server contract, and the check that it matches runs only in the merge queue build. An out-of-date client passes every branch check and fails at the last moment."
metadata:
  type: reference
---

**The fact:** a change to an endpoint, even a one-line comment, feeds three generated
files. Two of them are server-side contract files, and the branch checks compare those.
The third is the typed client that the front end imports. It is regenerated and
compared only in the merge queue build, which runs on the main branch plus the
candidate. Nothing on the branch ever looks at it.

**Why it matters:** the failure arrives after review is finished, on a pull request whose
own checks are green, and the message points at a step that does not exist in the branch
run. The first time this happened, it took two rounds of confusion before anyone read
the right log.

**How to apply:** when you touch an endpoint's signature, parameters, responses or even
its description, regenerate all three files in the same commit, and commit the
generated files with the change. After the queue throws a pull request out, read the
failing step in the queue build, not in the branch build.

Related: [[the-queue-throws-out-the-whole-batch]], [[every-shard-red-means-look-at-the-calendar]].
