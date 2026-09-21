#!/usr/bin/env bash
# Marking a dead lane is only half. A check that flags everything would also "pass" that half and
# would slander every live lane on the farm, which is worse than the bug.
set -u
B=/tmp/vst-$$; rm -rf "$B"; mkdir -p "$B/state" "$B/config"
export FLEET_STATE="$B" FLEET_CONFIG="$B/config"
printf '[tp]\nrepo = "x/tp"\npath = "%s"\nbranch = "main"\n' "$B" > "$B/config/projects.toml"
NOW=$(date +%s)
P=0; F=0
ok(){ echo "  PASS  $1"; P=$((P+1)); }
no(){ echo "  FAIL  $1 -- $2"; F=$((F+1)); }

rec(){ # slug, updated_at
  cat > "$B/state/$1.json" <<JSON
{"slug":"$1","project":"tp","engine":"codex","status":"running","started_at":$2,
 "updated_at":$2,"last_activity":"working"}
JSON
[ -s "$B/state/$1.json" ] || { echo "ABORT fixture $1"; exit 9; }; }

# 1. fresh lane, no unit: must NOT be flagged (the age guard protects a lane mid-start)
rec fresh-lane "$NOW"
# 2. old lane, no unit: must be flagged
rec old-dead "$((NOW - 90000))"
# 3. old lane WITH a live unit: must NOT be flagged - this is the one that matters
systemd-run --user --unit=fleet-old-alive --quiet -- sleep 120 2>/dev/null
sleep 1
rec old-alive "$((NOW - 90000))"

OUT=$(${FLEET:-$(dirname $0)/../bin/fleet} status 2>/dev/null)

echo "$OUT" | grep -q "fresh-lane .*running  " && ok "a lane started moments ago is left alone" \
  || no "fresh lane was flagged" "$(echo "$OUT" | grep fresh-lane | head -c 90)"

echo "$OUT" | grep -q "old-dead .*running?" && ok "an old lane with no unit is marked dead?" \
  || no "the dead lane was NOT marked" "$(echo "$OUT" | grep old-dead | head -c 90)"

if echo "$OUT" | grep -q "old-alive .*running?"; then
  no "a lane with a LIVE systemd unit was called dead" "$(echo "$OUT" | grep old-alive | head -c 90)"
else
  ok "an old lane whose unit is still active is NOT accused"
fi

systemctl --user stop fleet-old-alive 2>/dev/null
echo; echo "RESULT pass=$P fail=$F"
rm -rf "$B"
[ "$F" = 0 ]
