<!-- Sub-index. Same rule as the main index: every link text is a full claim. -->

# Infrastructure and the build host

The shared machine that runs the lanes, and the ways a careless command on it
reaches somebody else's work.

- [🔥 Long, parallel or noisy work goes to the build host, because the owner's laptop is where the owner works, and it froze under a fan-out](heavy-runs-belong-on-the-build-host.md)
- [💀 Processes are killed by port or by an identifier you recorded, never by a script name that other services share](kill-by-port-never-by-name.md)
- [🌙 A heartbeat scheduled inside a chat session stops when the session ends, so unattended work needs a collector on the build host](the-heartbeat-dies-with-the-session.md)
- [🔁 When several lanes need one new shared piece, that piece is built once before they start, or each lane invents its own](four-lanes-built-the-same-loading-ring.md)
