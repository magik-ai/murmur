# Verifying the harness

Everything here is runnable. If you change the fleet CLI, the supervisor, the CI runner or the
dashboard, run the suite that covers it before you believe you are done — and when you add a check,
break the thing it guards on purpose and require RED first. A check that cannot fail looks exactly
like a check that is passing, and this repo has produced that shape more than once.

## The argument trap — read this before running anything

Six suites take a path argument and default to `~/work/fleet`. Four want `lib/supervisor.py`, two
want `bin/fleet`. Pass the wrong one and you run `python3` over a bash script; pass none from a
worktree and you silently test a **different checkout**. That cost five separate false readings in
one night. They abort loudly now, but pass the argument anyway:

```bash
cd ~/work/fleet            # or your worktree

python3 tests/ci-test.py           bin/fleet          # the CI runner: gates, tiers, verdicts (~8 min)
python3 tests/group-test.py        bin/fleet          # fleet group: territories, assemble
python3 tests/supervisor-test.py   lib/supervisor.py  # respawn policy, cooldown, give-up cap
python3 tests/train-test.py        lib/supervisor.py  # --after gates and the fire ledger
python3 tests/blind-test.py        lib/supervisor.py  # delivery detection without a PR
python3 tests/scope-test.py        lib/supervisor.py  # scope drop and outcome policy
python3 tests/events-test.py                          # the durable event journal
bash    tests/policy-test.sh       bin/fleet          # hq gate, commit identity, per-project ports
bash    tests/salvage-test.sh      bin/fleet          # sweep: what it removes and refuses to
bash    tests/silent-start-test.sh                    # a lane that never started is `failed`
bash    tests/stale-status-test.sh                    # a lane killed by a reboot is not `running`
bash    tests/checkout-guard-test.sh                  # fast-forward when safe, shout when not
python3 tests/accounts-test.py                        # account pick + rotation rules, on fixtures
python3 tests/codex-usage-test.py                     # codex usage parsing (both windows + null)
python3 tests/sensors-test.py                         # optional GPU/CPU sensors; `auto` degrades, warns once
```

Dashboard:

```bash
node    dashboard/test_ui.mjs                  # rendered-HTML contract, no browser
python3 -m unittest dashboard/test_server.py   # API routes, log-path containment
bash    dashboard/test_browser.sh              # real Chromium: verdict colours + render guard
```

`test_browser.sh` starts its own stub server carrying every verdict state, including the ones the
live queue rarely holds — `ejected`, `cancelled`, `blocked`. "I could not find one to look at" is
not evidence that a state renders correctly.

Chromium needs the unpacked system libraries the CI sandbox binds for its tiers, or it exits 127 on
`libnspr4` and the failure reads as a broken page:

```bash
export LD_LIBRARY_PATH="$HOME/.local/pwdeps/root/usr/lib/x86_64-linux-gnu"
```

## Is the farm still in sync with the project?

```bash
python3 tests/gate-coverage.py     # hosted gates, reproduced, and the real gaps
```

Run it after any upstream CI change. The tier command tables are hand-maintained against a moving
project: gates get renamed, scripts get deleted, and the farm keeps calling them. That produces a
RED the candidate's code cannot cause — the worst failure this system has, because people stop
reading the tier. Two whole tiers were in that state on 05.08.

Before trusting the answer, make sure the project checkout is on `main` and current:

```bash
cd ~/work/<PROJECT> && git rev-parse --abbrev-ref HEAD && git rev-list --count HEAD..origin/main
```

A branch name and `0`. Anything else and you are reading someone else's tree, or a stale one — read
main as main instead: `git show origin/main:path`.

## Health of the running system

```bash
fleet status                 # lanes; `running?` with "dead?" means the record outlived its process
fleet ci status              # queue, verdicts, uncovered gates per candidate
fleet accounts               # subscription limits + reset countdowns
fleet accounts keepalive     # refresh any token near expiry (the timer runs this)
systemctl --user is-active fleet-ci fleet-daemon fleet-dashboard
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7878/
```
