#!/usr/bin/env bash
# Both directions. "A failed launch is called failed" is worthless on its own: a parser that calls
# everything failed passes it, and would bury every real result.
set -u
B=/tmp/vss-$$; rm -rf "$B"; mkdir -p "$B/state"
export FLEET_STATE="$B"
P=0; F=0
ok(){ echo "  PASS  $1"; P=$((P+1)); }
no(){ echo "  FAIL  $1 -- got: $2"; F=$((F+1)); }

run_parser() {  # $1=parser $2=slug $3=stdin content
  cat > "$B/state/$2.json" <<JSON
{"slug":"$2","project":"p","lane":"$2","engine":"codex","repo":"o/r",
 "worktree":"$B","status":"starting","started_at":1}
JSON
  printf '%s' "$3" | python3 "$(dirname $0)/../lib/$1" "$2" >/dev/null 2>&1
  python3 -c "import json;d=json.load(open('$B/state/$2.json'));print(d.get('status'),'|',(d.get('result_text') or '')[:60])"
}

echo "=== an engine that dies before its first turn ==="
for parser in parse_codex.py parse_stream.py parse_generic.py; do
  out=$(run_parser "$parser" "dead-${parser%%.*}" "")
  case "$out" in
    failed*) ok "$parser: empty stream -> failed ($(echo "$out" | cut -d'|' -f2 | head -c 46))";;
    *) no "$parser: empty stream must be failed" "$out";;
  esac
done

echo "=== a lane that DID work and simply opened no PR must stay 'ended' ==="
CODEX_EVENTS='{"type":"session.created","session_id":"s1"}
{"type":"turn.started"}
{"type":"item.completed","item":{"type":"agent_message","text":"did the work"}}
'
out=$(run_parser parse_codex.py worked-codex "$CODEX_EVENTS")
case "$out" in
  ended*|pr_open*|done_no_pr*) ok "parse_codex.py: a working lane still settles to $(echo "$out" | cut -d' ' -f1)";;
  failed*) no "parse_codex.py: a lane that produced turns was called failed" "$out";;
  *) no "parse_codex.py: unexpected" "$out";;
esac

echo "=== a generic engine that streams one event per line, its text under data ==="
# Grok Build's streaming-json. Its plain json is ONE pretty-printed object over many lines, which
# no single line parses, so every Grok lane read as "never started": the preset streams instead.
GROK_EVENTS='{"type":"text","data":"Reading the repository"}
{"type":"text","data":"Opened the pull request"}
{"type":"end","stopReason":"end_turn","usage":{"input_tokens":1200,"output_tokens":80}}
'
out=$(run_parser parse_generic.py worked-grok "$GROK_EVENTS")
case "$out" in
  ended*|pr_open*) ok "parse_generic.py: a streaming lane settles to $(echo "$out" | cut -d' ' -f1)";;
  *) no "parse_generic.py: a streaming lane must not be failed" "$out";;
esac
act=$(python3 -c "import json;print(json.load(open('$B/state/worked-grok.json')).get('last_activity'))")
[ "$act" = "Opened the pull request" ] && ok "parse_generic.py: the card shows the event's text, not its JSON" \
  || no "parse_generic.py: last activity should be the text under data" "$act"

echo
echo "RESULT pass=$P fail=$F"
rm -rf "$B"
[ "$F" = 0 ]
