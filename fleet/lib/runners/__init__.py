"""Runners: one lane's engine, moved off this farm into a provider's sandbox.

`base.py` holds the interface and everything the three providers share (the bootstrap, the
small remote scripts, the env file). `railway.py`, `vercel.py` and `do_agents.py` are the
adapters. `run_remote.py` is what a runner lane's unit actually runs, and `cli.py` is
`fleet runner test|reap`.

Every module here runs as a plain script too, so `python3 lib/runners/run_remote.py ...` works
without the package being importable. Nothing here imports anything outside the standard
library and `lib/scrub.py`.
"""
