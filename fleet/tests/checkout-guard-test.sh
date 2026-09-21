#!/usr/bin/env bash
# Four cases. "It ran without erroring" proves none of them: a guard that never fast-forwards and a
# guard that overwrites everything both do that.
set -u
# the suite runs from anywhere; the library lives next to it
FLEET_HOME="${FLEET_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
export FLEET_HOME
B=/tmp/vg-$$; rm -rf "$B"; mkdir -p "$B/config"
export FLEET_CONFIG="$B/config" FLEET_STATE="$B/state"
mkdir -p "$FLEET_STATE"

git init -q --bare "$B/origin.git"
git clone -q "$B/origin.git" "$B/seed" 2>/dev/null
cd "$B/seed"; git config user.email t@t; git config user.name t
echo one > f; git add -A; git commit -qm one; git push -q origin HEAD:main
cd /

clone(){ git clone -q "$B/origin.git" "$B/$1" 2>/dev/null; git -C "$B/$1" config user.email t@t; git -C "$B/$1" config user.name t; }
clone behind; clone detached; clone dirty; clone current

# advance origin by one commit
cd "$B/seed"; git pull -q origin main; echo two > f2; git add -A; git commit -qm two; git push -q origin HEAD:main; cd /

git -C "$B/behind" fetch -q origin                      # on main, clean, behind
git -C "$B/detached" checkout -q --detach origin/main 2>/dev/null
git -C "$B/dirty" fetch -q origin; echo dirt > "$B/dirty/f"   # behind AND modified
git -C "$B/current" pull -q origin main                 # already current

cat > "$B/config/projects.toml" <<TOML
[behind]
repo = "x/behind"
path = "$B/behind"
branch = "main"
[detached]
repo = "x/detached"
path = "$B/detached"
branch = "main"
[dirty]
repo = "x/dirty"
path = "$B/dirty"
branch = "main"
[current]
repo = "x/current"
path = "$B/current"
branch = "main"
TOML

OUT=$(FLEET_HOME="$FLEET_HOME" python3 - <<'PY' 2>&1
import os, sys
sys.path.insert(0, os.environ["FLEET_HOME"])
from lib import ci
ci.sync_project_checkouts()
PY
)
echo "--- the guard's output ---"; echo "$OUT" | sed 's/^/    /'
echo "--- checks ---"
P=0; F=0
ok(){ echo "  PASS  $1"; P=$((P+1)); }
no(){ echo "  FAIL  $1 -- $2"; F=$((F+1)); }

[ "$(git -C "$B/behind" rev-list --count HEAD..origin/main)" = 0 ] \
  && ok "a clean behind checkout is fast-forwarded" \
  || no "behind checkout NOT fast-forwarded" "$(git -C "$B/behind" rev-list --count HEAD..origin/main) commits behind"

git -C "$B/detached" symbolic-ref -q HEAD >/dev/null \
  && no "a detached HEAD was silently moved - that overwrites somebody else's state" "HEAD became a branch" \
  || ok "a detached HEAD is left alone"
echo "$OUT" | grep -qi "DETACHED" && ok "the detached HEAD is reported LOUDLY" || no "the detached HEAD is silent" "no line"

[ "$(cat "$B/dirty/f")" = dirt ] && ok "a dirty checkout is left alone" || no "the dirty checkout was overwritten" "the file changed"
echo "$OUT" | grep -qi "tracked change" && ok "the dirty checkout is reported" || no "the dirty checkout is silent" "no line"

echo "$OUT" | grep -qi "fast-forwarded behind" && ok "the fast-forward is reported" || no "the fast-forward is silent" "no line"
echo "$OUT" | grep -qi "current" && no "an up-to-date checkout makes noise" "it should stay quiet" || ok "an up-to-date checkout stays quiet"

echo; echo "RESULT pass=$P fail=$F"
rm -rf "$B"
[ "$F" = 0 ]
