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
is "the legacy port_base spelling is still readable" "$(_proj plain port_base)" "5300"
is "an unregistered project is empty, not an error" "$(_proj nosuch ports.vite_base)" ""
is "a sub-table itself never prints as a value" "$(_proj withports ports)" ""

echo "=== the shipped example registry ==="

# install.sh copies config/projects.example.toml to ~/.config/fleet/projects.toml verbatim, and
# the README, `fleet help` and install.sh all end by telling a new operator to register `myproj`.
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

# ---- the codex engine: FLEET_CODEX_BIN / FLEET_CODEX_MODEL (env file) pick the binary and model
codex_lines="$(grep -E '^CODEX_(BIN|DEFAULT_MODEL)=' "$FLEET_BIN")"
got=$(unset CODEX_BIN CODEX_DEFAULT_MODEL FLEET_CODEX_BIN FLEET_CODEX_MODEL; eval "$codex_lines"; echo "$CODEX_BIN|$CODEX_DEFAULT_MODEL")
is "codex: nothing set keeps the system binary and the shipped model" "$got" "/usr/bin/codex|gpt-5.6-sol"
got=$(unset CODEX_BIN CODEX_DEFAULT_MODEL; FLEET_CODEX_BIN=/opt/codex/bin/codex FLEET_CODEX_MODEL=gpt-6-sol; eval "$codex_lines"; echo "$CODEX_BIN|$CODEX_DEFAULT_MODEL")
is "codex: the env file's FLEET_CODEX_BIN and FLEET_CODEX_MODEL are used" "$got" "/opt/codex/bin/codex|gpt-6-sol"
got=$(CODEX_BIN=/explicit/codex; FLEET_CODEX_BIN=/opt/codex/bin/codex; eval "$codex_lines"; echo "$CODEX_BIN")
is "codex: an explicit CODEX_BIN still wins" "$got" "/explicit/codex"

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

echo "RESULT pass=$P fail=$F"

[ "$F" = 0 ]
