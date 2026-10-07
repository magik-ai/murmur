<!-- murmur:farm -->
## The farm

Agents for this repository run on a farm: a separate, always-on machine. The
`fleet` command starts and tracks them. On a laptop, `fleet` is a small script
that runs each command on the farm over ssh. This repository is the farm
project `<PROJECT>`.

**Check the farm before every spawn, in every session.** Run these four
commands in order, and stop at the first one that fails:

1. `command -v fleet` finds the command.
2. `fleet capacity` answers `OK` or `BLOCK`. Any other answer, or an ssh
   error, means this computer cannot reach the farm.
3. `fleet projects` lists `<PROJECT>`.
4. `fleet accounts pick` prints an account name. It exits 1 when no account
   has room.

If all four pass, start lanes on the farm with
`fleet spawn --project <PROJECT> ...`, as the orchestrate skill says. A
`BLOCK` means wait or spawn fewer, never `--force`.

If any check fails, do not spawn anything, and do not switch to local
subagents on your own. Tell <OWNER> which check failed, with its output and
the fix:

- no `fleet`: follow step 9 of murmur's INSTALL.md on this computer
  (https://github.com/magik-ai/murmur/blob/main/INSTALL.md), or put
  `~/.local/bin` on the `PATH` if the script is there;
- no answer from the farm: ssh to the farm must work with no prompt. This
  prints the ssh host the `fleet` script uses, for `ssh <host> true`:
  `sed -n 's/^exec ssh \(.* \)*\([^ ]*\) ".*"$/\2/p' ~/.local/bin/fleet`;
- no project:
  `fleet add-project --name <PROJECT> --repo <ORG>/<REPO> --branch <BASE>`;
- no account with room: wait until one has room.

Run lanes on this computer only when <OWNER> says so.
<!-- /murmur:farm -->
