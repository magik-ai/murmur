#!/usr/bin/env bash
# What policy.toml and projects.toml actually decide at spawn time: the head office gate, the
# commit identity a lane pushes under, and the port block a project hands its lanes.
#
# These three hunks are read once per spawn, deep inside cmd_spawn, where no other suite reaches
# them. The functions are pulled out of `bin/fleet` by name and run against a throwaway
# FLEET_CONFIG, so the test exercises the shipped code rather than a copy of it.
#
# Run:  bash tests/policy-test.sh [path/to/bin/fleet]
set -u
FLEET_BIN="${1:-$(cd "$(dirname "$0")/.." && pwd)/bin/fleet}"
case "$FLEET_BIN" in
  *bin/fleet) ;;
  *) echo "usage: bash tests/policy-test.sh <path to bin/fleet>   (got: $FLEET_BIN)" >&2; exit 2;;
esac
[ -r "$FLEET_BIN" ] || { echo "no such file: $FLEET_BIN" >&2; exit 2; }

P=0; F=0
ok(){ echo "  PASS  $1"; P=$((P+1)); }
no(){ echo "  FAIL  $1 -- got: ${2:-}"; F=$((F+1)); }
is(){ [ "$2" = "$3" ] && ok "$1" || no "$1" "$2"; }

PY=python3
export FLEET_CONFIG
ROOT=$(mktemp -d -t fleet-policy-test-XXXXXX)
trap 'rm -rf "$ROOT"' EXIT
FLEET_CONFIG="$ROOT/config"; mkdir -p "$FLEET_CONFIG"

# Pull the functions under test out of the shipped script by name.
eval "$(sed -n '/^_policy() {/,/^}$/p' "$FLEET_BIN")"
eval "$(sed -n '/^_hq_gate() {/,/^}$/p' "$FLEET_BIN")"
eval "$(sed -n '/^_commit_identity() {/,/^}$/p' "$FLEET_BIN")"
eval "$(sed -n '/^_proj() {/,/^}$/p' "$FLEET_BIN")"
eval "$(sed -n '/^_load_env_file() {/,/^}$/p' "$FLEET_BIN")"
eval "$(sed -n '/^_port_slot() {/,/^}$/p' "$FLEET_BIN")"
eval "$(sed -n '/^_hq_mail() {/,/^}$/p' "$FLEET_BIN")"

# A fake `hq` on PATH, so "is head office installed" is a property of this test, not of the box.
mkdir -p "$ROOT/hqbin"
printf '#!/bin/sh\nexit 0\n' > "$ROOT/hqbin/hq"; chmod +x "$ROOT/hqbin/hq"
PATH_WITH_HQ="$ROOT/hqbin:$PATH"
PATH_WITHOUT_HQ="$ROOT/emptybin"; mkdir -p "$PATH_WITHOUT_HQ"

echo "=== the head office gate ==="

: > "$FLEET_CONFIG/policy.toml"
out=$(PATH="$PATH_WITH_HQ" _hq_gate 2>"$ROOT/warn")
is "no [hq] table plus an hq binary keeps head office ON" "$out" "1"
grep -q "no \[hq\] table" "$ROOT/warn" \
  && ok "and says so once, naming the key to write" \
  || no "the absent table must warn" "$(cat "$ROOT/warn")"

printf '[hq]\nenabled = true\n' > "$FLEET_CONFIG/policy.toml"
out=$(PATH="$PATH_WITH_HQ" _hq_gate 2>"$ROOT/warn")
is "enabled = true is ON" "$out" "1"
is "and settles the warning" "$(cat "$ROOT/warn")" ""

printf '[hq]\nenabled = false\n' > "$FLEET_CONFIG/policy.toml"
out=$(PATH="$PATH_WITH_HQ" _hq_gate 2>"$ROOT/warn")
is "enabled = false is the one way OFF" "$out" "0"
is "and says nothing" "$(cat "$ROOT/warn")" ""

: > "$FLEET_CONFIG/policy.toml"
out=$(PATH="$PATH_WITHOUT_HQ" _hq_gate 2>"$ROOT/warn")
is "no hq binary is OFF whatever the file says" "$out" "0"
is "and never mentions head office to a farm that has none" "$(cat "$ROOT/warn")" ""

printf '[hq]\nenabled = true\n' > "$FLEET_CONFIG/policy.toml"
out=$(PATH="$PATH_WITHOUT_HQ" _hq_gate 2>/dev/null)
is "enabled = true cannot conjure a binary" "$out" "0"

# fleet run over ssh without a login shell (the laptop shim) may have no ~/.local/bin on PATH,
# where hq installs. bin/fleet puts it there itself, once.
SHIM_HOME="$ROOT/shimhome"; mkdir -p "$SHIM_HOME/.local/bin"
printf '#!/bin/sh\nexit 0\n' > "$SHIM_HOME/.local/bin/hq"; chmod +x "$SHIM_HOME/.local/bin/hq"
bare_path="$(dirname "$(command -v python3)"):/usr/bin:/bin"
found=$(HOME="$SHIM_HOME" PATH="$bare_path" FLEET_STATE="$ROOT/shimstate" \
  bash -c 'source "$1" help >/dev/null; command -v hq' _ "$FLEET_BIN")
is "fleet finds hq in ~/.local/bin when PATH leaves it out" "$found" "$SHIM_HOME/.local/bin/hq"
twice=$(HOME="$SHIM_HOME" PATH="$SHIM_HOME/.local/bin:$bare_path" FLEET_STATE="$ROOT/shimstate" \
  bash -c 'source "$1" help >/dev/null; printf %s "$PATH"' _ "$FLEET_BIN")
is "and adds nothing when PATH has it already" "$twice" "$SHIM_HOME/.local/bin:$bare_path"

echo "=== the head office push guard a lane gets ==="

# The claims hook cmd_spawn writes into a lane, taken out by its heredoc marker. hq here is a fake
# that writes down its arguments, so the case reads exactly what the hook asked it.
sed -n "/<<'HOOK_HQ'\$/,/^HOOK_HQ\$/p" "$FLEET_BIN" | sed '1d;$d' > "$ROOT/claims-hook"
chmod +x "$ROOT/claims-hook"
mkdir -p "$ROOT/hookbin" "$ROOT/hookrepo"
cat > "$ROOT/hookbin/hq" <<FAKE
#!/bin/sh
printf '%s|' "\$@" >> "$ROOT/hq-args"
echo >> "$ROOT/hq-args"
FAKE
chmod +x "$ROOT/hookbin/hq"
git -C "$ROOT/hookrepo" init -q
git -C "$ROOT/hookrepo" remote add origin https://example.invalid/acme/demo.git
printf 'refs/heads/-weird 1111 refs/heads/-weird 0000\nrefs/heads/fleet/lane-1 2222 refs/heads/fleet/lane-1 0000\n' \
  | (cd "$ROOT/hookrepo" && PATH="$ROOT/hookbin:$PATH" "$ROOT/claims-hook")
is "the guard lets a push through when hq allows it" "$?" "0"
# A branch name is not the lane's to choose: `refs/heads/-weird` is a legal ref, and without the
# separator hq reads it as an option, cannot parse its own arguments and lets the push through.
is "a branch that starts with a dash is checked behind a separator" \
  "$(sed -n 1p "$ROOT/hq-args" 2>/dev/null)" "check-push|--|https://example.invalid/acme/demo.git|-weird|"
is "and so is an ordinary branch" \
  "$(sed -n 2p "$ROOT/hq-args" 2>/dev/null)" "check-push|--|https://example.invalid/acme/demo.git|fleet/lane-1|"

# The name the guard checks under. A clone-wide `git config hq.agent` is shared by every worktree
# of the clone, so it must never override the caller's HQ_AGENT; the lane's own worktree value,
# which spawn writes with extensions.worktreeConfig on, wins over both (as in hq's own guard).
cat > "$ROOT/hookbin/hq" <<FAKE
#!/bin/sh
printf '%s\n' "\${HQ_AGENT:-(unset)}" >> "$ROOT/hq-agent"
FAKE
chmod +x "$ROOT/hookbin/hq"
push_one='refs/heads/fleet/lane-1 2222 refs/heads/fleet/lane-1 0000'
git -C "$ROOT/hookrepo" config hq.agent clone-wide
printf '%s\n' "$push_one" \
  | (cd "$ROOT/hookrepo" && HQ_AGENT=caller PATH="$ROOT/hookbin:$PATH" "$ROOT/claims-hook")
is "a clone-wide hq.agent never overrides the caller's HQ_AGENT" \
  "$(tail -n 1 "$ROOT/hq-agent" 2>/dev/null)" "caller"
git -C "$ROOT/hookrepo" config extensions.worktreeConfig true
git -C "$ROOT/hookrepo" config --worktree hq.agent lane-own
printf '%s\n' "$push_one" \
  | (cd "$ROOT/hookrepo" && HQ_AGENT=caller PATH="$ROOT/hookbin:$PATH" "$ROOT/claims-hook")
is "the lane's own worktree hq.agent wins" "$(tail -n 1 "$ROOT/hq-agent" 2>/dev/null)" "lane-own"

echo "=== the head office mail a lane starts with ==="

# hq answers an empty inbox with "inbox empty (nothing after <time>; ...)". Only the bare words
# were matched, so that line was folded into every lane's prompt as if it were mail.
mkdir -p "$ROOT/mailbin"
inbox_says() { printf '#!/bin/sh\ncat <<EOF\n%s\nEOF\n' "$1" > "$ROOT/mailbin/hq"; chmod +x "$ROOT/mailbin/hq"; }
inbox_says 'inbox empty (nothing after 2026-09-24T08:00:00Z; `hq inbox --recent 6` re-shows the last six hours without moving the cursor)'
is "an empty inbox puts no mail in the prompt" "$(PATH="$ROOT/mailbin:$PATH" _hq_mail vivaldi)" ""
inbox_says $'--- 2026-09-24T08:01:00Z\nThe schema lane merged; rebase before you touch migrations.'
is "real mail is kept, word for word" "$(PATH="$ROOT/mailbin:$PATH" _hq_mail vivaldi)" \
  $'--- 2026-09-24T08:01:00Z\nThe schema lane merged; rebase before you touch migrations.'

echo "=== the commit identity a lane pushes under ==="

: > "$FLEET_CONFIG/policy.toml"
IFS=$'\t' read -r author email <<< "$(_commit_identity vivaldi)"
is "no [identity] table still names the agent as author" "$author" "vivaldi (agent)"
is "and gives it an address git will accept" "$email" "vivaldi@agents.local"

printf '[identity]\nauthor_format = "{agent} (fleet)"\nemail_format = "you+{agent}@example.com"\n' \
  > "$FLEET_CONFIG/policy.toml"
IFS=$'\t' read -r author email <<< "$(_commit_identity vivaldi)"
is "a configured author format wins" "$author" "vivaldi (fleet)"
is "a configured email format wins" "$email" "you+vivaldi@example.com"

printf '[identity]\nauthor_format = "{agent} (fleet)"\n' > "$FLEET_CONFIG/policy.toml"
IFS=$'\t' read -r author email <<< "$(_commit_identity vivaldi)"
is "half a table keeps the default for the other half" "$email" "vivaldi@agents.local"

printf '[identity]\nauthor_format = "one {agent} and {agent}"\nemail_format = "{agent}@x.test"\n' \
  > "$FLEET_CONFIG/policy.toml"
IFS=$'\t' read -r author email <<< "$(_commit_identity vivaldi)"
is "every {agent} in a format is substituted" "$author" "one vivaldi and vivaldi"

echo "=== the per-project ports table ==="

cat > "$FLEET_CONFIG/projects.toml" <<'TOML'
[withports]
repo = "o/r"
path = "~/work/withports"
[withports.ports]
vite_base = 4000
api_base  = 9000
e2e_base  = 7000

[plain]
repo = "o/r"
path = "~/work/plain"
port_base = 5300
TOML
is "a [ports] table is read key by key" "$(_proj withports ports.vite_base)" "4000"
is "and for the API base too" "$(_proj withports ports.api_base)" "9000"
is "and the e2e base" "$(_proj withports ports.e2e_base)" "7000"
is "a project without the table reports nothing, so the caller can fall back" \
   "$(_proj plain ports.vite_base)" ""
is "a plain port_base, as add-project writes it, is readable" "$(_proj plain port_base)" "5300"
is "an unregistered project is empty, not an error" "$(_proj nosuch ports.vite_base)" ""
is "a sub-table itself never prints as a value" "$(_proj withports ports)" ""

echo "=== the port slot a new lane gets ==="

# A lane takes base + slot for its dev server, API and e2e ports. The slot is the lowest one no
# running lane holds. It used to be the count of running lanes: with lanes on slots 0 and 1, the
# first ending made the count 1, and the next lane took slot 1, the ports of the one still running.
SLOTS="$ROOT/slots"; mkdir -p "$SLOTS/state"
lane_at() { # name status vite api e2e
  printf '{"slug": "%s", "status": "%s", "ports": {"vite": %s, "uvicorn": %s, "e2e": %s}}' \
    "$1" "$2" "$3" "$4" "$5" > "$SLOTS/state/$1.json"
}
slot() { FLEET_STATE="$SLOTS" _port_slot 5200 8100 6100; }
is "no running lane: slot 0" "$(slot)" "0"
lane_at a running 5200 8100 6100
lane_at b running 5201 8101 6101
is "two running lanes: the next is slot 2" "$(slot)" "2"
lane_at a pr_open 5200 8100 6100
is "the first lane ended: its slot is free again, not the second lane's" "$(slot)" "0"
lane_at c starting 5200 8100 6100
lane_at d running 5202 9000 7000
is "a port another project's lane holds is skipped too" "$(slot)" "3"
printf '[broken' > "$SLOTS/state/torn.json"
is "an unreadable record does not stop the pick" "$(slot)" "3"
FLEET_STATE="$SLOTS" _port_slot x 8100 6100 >/dev/null 2>&1
is "a port base that is not a number is refused" "$?" "2"

echo "=== the shipped example registry ==="

# install.sh copies config/projects.example.toml to ~/.config/fleet/projects.toml verbatim, and
# the README and both installers end by telling a new operator to register `myproj`.
# A live placeholder table under that name made the first command of a fresh install fail.
EXAMPLE="$(dirname "$FLEET_BIN")/../config/projects.example.toml"
FRESH="$ROOT/fresh"; mkdir -p "$FRESH/config" "$FRESH/state" "$FRESH/checkout"
cp "$EXAMPLE" "$FRESH/config/projects.toml"
git -C "$FRESH/checkout" init -q 2>/dev/null   # already cloned, so add-project clones nothing
out=$(FLEET_CONFIG="$FRESH/config" FLEET_STATE="$FRESH/state" \
      "$FLEET_BIN" add-project --name myproj --repo your-org/your-repo \
      --path "$FRESH/checkout" 2>&1)
rc=$?
is "'fleet add-project --name myproj' succeeds on a fresh install" "$rc" "0"
case "$out" in *"registered project 'myproj'"*) ok "and says it registered the project";;
  *) no "add-project must register myproj" "$out";; esac
listed=$(FLEET_CONFIG="$FRESH/config" FLEET_STATE="$FRESH/state" "$FLEET_BIN" projects 2>&1)
is "and 'fleet projects' then lists exactly it" "$listed" "myproj"

echo "=== a policy file that does not parse ==="

# Silence here would be the worst answer: every gate downstream takes its own default, so a
# typo in policy.toml spawns a lane with no head office, the fallback identity and limits the
# operator never wrote.
BROKEN="$ROOT/broken"; mkdir -p "$BROKEN/config" "$BROKEN/state"
printf '[limits\nram_min_gb = \n' > "$BROKEN/config/policy.toml"
out=$(FLEET_CONFIG="$BROKEN/config" FLEET_STATE="$BROKEN/state" \
      "$FLEET_BIN" spawn --project p --lane l --task t 2>&1)
rc=$?
is "a corrupt policy.toml refuses the spawn" "$rc" "2"
case "$out" in "REFUSING to spawn: invalid policy file"*) ok "with one line naming the file";;
  *) no "the refusal must name the file, once" "$out";; esac
is "and says it once, not once per key" "$(printf '%s' "$out" | wc -l | tr -d ' ')" "0"

echo "=== fleet spawn --after keeps every value as data ==="

# A gated spawn writes a pending spec for the daemon and stops. That spec used to be Python source
# with the values pasted in, so a double quote in a lane name or in --issues ran the rest of the
# value as code. The payload below would create INJECTED in the working directory.
GATE="$ROOT/gate"; mkdir -p "$GATE/config" "$GATE/state" "$GATE/work"
GATE_BIN="$(cd "$(dirname "$FLEET_BIN")" && pwd)/$(basename "$FLEET_BIN")"
gate_spawn() {
  (cd "$GATE/work" && FLEET_CONFIG="$GATE/config" FLEET_STATE="$GATE/state" \
    "$GATE_BIN" spawn --project demo --engine codex --after first --task t "$@" 2>&1)
}
payload='" + __import__("os").popen("touch INJECTED").read() + "'
out=$(gate_spawn --lane "a$payload")
is "a lane name with a quote in it is refused" "$?" "1"
case "$out" in *"is not a plain name"*) ok "and the refusal says what a name may hold";;
  *) no "the refusal must say what a name may hold" "$out";; esac
is "and nothing is queued for the daemon" "$(ls "$GATE/state/pending" 2>/dev/null | wc -l | tr -d ' ')" "0"
for bad in "--project ../demo" "--by two words" "--effort high;id" "--account ." "--model x;id"; do
  out=$(gate_spawn --lane refused ${bad%% *} "${bad#* }")
  rc=$?
  is "spawn $bad is refused" "$rc" "1"
done
out=$(gate_spawn --lane gated --by ada --issues "x$payload" --done-when "file:say \"hi\".md")
is "a quote in a value that is not a name still queues the lane" "$?" "0"
[ -e "$GATE/work/INJECTED" ] && no "no value is run as Python" "INJECTED was created" \
  || ok "no value is run as Python"
spec_value() { $PY -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' \
  "$GATE/state/pending/gated.json" "$1" 2>/dev/null || echo "(no pending spec)"; }
is "the pending spec keeps --issues exactly as given" "$(spec_value issues)" "x$payload"
is "and --done-when" "$(spec_value done_when)" 'file:say "hi".md'
is "and the names" "$(spec_value lane)/$(spec_value project)/$(spec_value by)" "gated/demo/ada"

echo
# ---- the env file: FLEET_* keys reach the CLI, explicit exports win, non-FLEET keys are ignored
printf 'FLEET_LHM_URL=http://sensor.local:8085/data.json\nFLEET_FARM_ALIAS="farm"\nFLEET_DASH_BIND=0.0.0.0\nPATH=/nowhere\n# comment\nnot a pair\n' > "$FLEET_CONFIG/env"
saved_path="$PATH"
unset FLEET_LHM_URL FLEET_FARM_ALIAS; export FLEET_DASH_BIND=127.0.0.1
_load_env_file
is "env file: an unset FLEET_ key is taken" "${FLEET_LHM_URL:-}" "http://sensor.local:8085/data.json"
is "env file: quotes around a value are stripped" "${FLEET_FARM_ALIAS:-}" "farm"
is "env file: an explicit export is not overridden" "${FLEET_DASH_BIND:-}" "127.0.0.1"
case "$PATH" in /nowhere) no "env file: a non-FLEET key is ignored" "$PATH";; *) ok "env file: a non-FLEET key is ignored";; esac
PATH="$saved_path"; unset FLEET_LHM_URL FLEET_FARM_ALIAS FLEET_DASH_BIND
rm -f "$FLEET_CONFIG/env"

# ---- the engine CLIs: FLEET_CLAUDE_BIN / FLEET_CODEX_BIN (env file), then ~/.local/bin, where
# both official installers put them, then PATH (an npm install), then a fixed path. The Python
# checks (lib/model_presets.py engine_bin) must find the same file, or the dashboard says an engine
# is installed while its lanes cannot start.
engine_lines="$(sed -n '/^_engine_bin() {/,/^}$/p' "$FLEET_BIN"
                grep -E '^(CLAUDE_BIN|CODEX_BIN|CODEX_DEFAULT_MODEL)=' "$FLEET_BIN")"
PY_ABS="$(command -v python3)"
LIB_DIR="$(cd "$(dirname "$FLEET_BIN")/../lib" && pwd)"
ENG="$ROOT/engines"; mkdir -p "$ENG/home/.local/bin" "$ENG/npm" "$ENG/empty"
for tool in "$ENG/npm/claude" "$ENG/npm/codex"; do
  printf '#!/bin/sh\nexit 0\n' > "$tool"; chmod +x "$tool"
done
engines() { # [VAR=value ...]: what bash and Python each pick, with only those set
  (unset CLAUDE_BIN CODEX_BIN CODEX_DEFAULT_MODEL FLEET_CLAUDE_BIN FLEET_CODEX_BIN FLEET_CODEX_MODEL
   [ $# -gt 0 ] && export "$@"
   eval "$engine_lines"
   py=$("$PY_ABS" -c 'import sys; sys.path.insert(0, sys.argv[1]); import model_presets as P
print(P.engine_bin("claude") + "|" + P.engine_bin("codex"))' "$LIB_DIR")
   echo "$CLAUDE_BIN|$CODEX_BIN|$CODEX_DEFAULT_MODEL|python:$py")
}
H="$ENG/home"
is "engines: found nowhere, fleet names where the installers put claude and /usr/bin/codex" \
  "$(engines HOME="$H" PATH="$ENG/empty")" \
  "$H/.local/bin/claude|/usr/bin/codex|gpt-5.6-sol|python:$H/.local/bin/claude|/usr/bin/codex"
is "engines: an npm install on PATH is found" \
  "$(engines HOME="$H" PATH="$ENG/npm")" \
  "$ENG/npm/claude|$ENG/npm/codex|gpt-5.6-sol|python:$ENG/npm/claude|$ENG/npm/codex"
cp "$ENG/npm/claude" "$ENG/npm/codex" "$H/.local/bin/"
is "engines: ~/.local/bin, where the official installers put them, comes before PATH" \
  "$(engines HOME="$H" PATH="$ENG/npm")" \
  "$H/.local/bin/claude|$H/.local/bin/codex|gpt-5.6-sol|python:$H/.local/bin/claude|$H/.local/bin/codex"
is "engines: the env file's FLEET_CLAUDE_BIN, FLEET_CODEX_BIN and FLEET_CODEX_MODEL win" \
  "$(engines HOME="$H" PATH="$ENG/npm" FLEET_CLAUDE_BIN=/opt/claude FLEET_CODEX_BIN=/opt/codex FLEET_CODEX_MODEL=gpt-6-sol)" \
  "/opt/claude|/opt/codex|gpt-6-sol|python:/opt/claude|/opt/codex"
is "engines: an explicit CLAUDE_BIN or CODEX_BIN still wins over the env file" \
  "$(engines HOME="$H" PATH="$ENG/npm" CLAUDE_BIN=/x/claude CODEX_BIN=/x/codex FLEET_CLAUDE_BIN=/opt/claude FLEET_CODEX_BIN=/opt/codex)" \
  "/x/claude|/x/codex|gpt-5.6-sol|python:/x/claude|/x/codex"

echo "=== fleet kill rewrites the lane record whole ==="
# The dashboard reads a lane's record while `fleet kill` marks it killed. A bare truncate and
# write would let that read see half a file; the mark is written to a temporary file and swapped
# in with os.replace, which shows as a new inode. systemctl and tmux are fakes, so no unit on this
# box is touched.
KILL_STATE="$ROOT/kill-state"; mkdir -p "$KILL_STATE/state" "$ROOT/killbin"
printf '#!/bin/sh\nexit 0\n' > "$ROOT/killbin/systemctl"; chmod +x "$ROOT/killbin/systemctl"
cp "$ROOT/killbin/systemctl" "$ROOT/killbin/tmux"
record="$KILL_STATE/state/demo-lane-1.json"
printf '{"slug": "demo-lane-1", "project": "demo", "lane": "lane", "status": "running"}' > "$record"
before=$(stat -c %i "$record")
out=$(FLEET_STATE="$KILL_STATE" PATH="$ROOT/killbin:$PATH" "$FLEET_BIN" kill demo-lane-1 2>&1)
is "kill: the command says it killed the lane" "$out" "killed demo-lane-1"
[ "$(stat -c %i "$record")" != "$before" ] && ok "kill: the record is a new file, swapped in whole" \
  || no "kill: the record was rewritten in place" "inode $before"
is "kill: and it says killed, keeping its other fields" \
  "$($PY -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], d["lane"])' "$record")" "killed lane"
is "kill: no temporary file is left behind" "$(ls "$KILL_STATE/state" | grep -c '\.tmp$')" "0"

echo "=== fleet drain and fleet resume ==="
# The documented names for freeing the machine, with the old game-mode name kept as an alias.
# systemctl is a fake that writes down what it was asked, so no unit on this box is touched.
DRAIN_STATE="$ROOT/drain-state"; mkdir -p "$DRAIN_STATE/state" "$ROOT/drainbin"
printf '#!/bin/sh\necho "$*" >> "%s/systemctl.log"\n[ "$2" = is-active ] && echo inactive\nexit 0\n' \
  "$ROOT" > "$ROOT/drainbin/systemctl"; chmod +x "$ROOT/drainbin/systemctl"
drain(){ FLEET_STATE="$DRAIN_STATE" PATH="$ROOT/drainbin:$PATH" "$FLEET_BIN" "$@" 2>&1; }
out=$(drain drain)
grep -qx -- "--user stop fleet-daemon.service" "$ROOT/systemctl.log" \
  && ok "drain: fleet drain stops the daemon" || no "drain: the daemon was not stopped" "$(cat "$ROOT/systemctl.log")"
case "$out" in *"Start it again with: fleet resume"*) ok "drain: and names fleet resume as the way back";;
  *) no "drain: the way back is not fleet resume" "$out";; esac
: > "$ROOT/systemctl.log"; out=$(drain resume)
is "drain: fleet resume starts the daemon" "$(cat "$ROOT/systemctl.log")" "--user start fleet-daemon.service"
out=$(drain drain status)
case "$out" in "daemon: inactive"*"live lanes: 0"*) ok "drain: fleet drain status reports the daemon and the lanes";;
  *) no "drain: fleet drain status" "$out";; esac
: > "$ROOT/systemctl.log"; out=$(drain game-mode off)
is "drain: the old name, fleet game-mode off, still resumes" "$(cat "$ROOT/systemctl.log")" "--user start fleet-daemon.service"
out=$(drain drain now); rc=$?
[ "$rc" != 0 ] && ok "drain: an unknown word is refused, not taken as a drain" || no "drain: fleet drain now ran" "$out"
out=$(drain help)
case "$out" in *"fleet drain [status]"*"fleet resume"*) ok "drain: fleet help lists drain and resume";;
  *) no "drain: fleet help does not list drain and resume" "$out";; esac
case "$out" in *gaming*|*playing*|*game-mode*) no "drain: fleet help still talks about games" "$out";;
  *) ok "drain: and says nothing about games";; esac

echo "=== fleet help ==="
out=$(drain help)
is "help: fleet kill is listed once" "$(printf '%s\n' "$out" | grep -c '^  fleet kill ')" "1"
case "$out" in *JANITOR*|*"READ THIS"*|*"Build tooling"*|*"whole rig"*) no "help: it still shouts" "$out";;
  *) ok "help: it does not shout";; esac
missing=""
for c in $(sed -n '/^case "\${1:-help}" in/,/^  help|/p' "$FLEET_BIN" | grep -o '^  [a-z-]*' | tr -d ' '); do
  case "$c" in help|game-mode) continue;; esac
  printf '%s\n' "$out" | grep -q "^  fleet $c\b" || missing="$missing $c"
done
is "help: every command the dispatcher knows is listed" "$missing" ""

echo "RESULT pass=$P fail=$F"

[ "$F" = 0 ]
