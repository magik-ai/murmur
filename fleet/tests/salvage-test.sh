#!/usr/bin/env bash
# Destructive-path regression suite in a throwaway git world. It exercises the candidate path
# passed on argv and never touches the farm's real state, projects, services, or remotes.
set -u

FLEET=${1:-$(dirname "$0")/../bin/fleet}
FLEET=$(readlink -f "$FLEET")
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export FLEET_STATE="$TMP/fleet" FLEET_CONFIG="$TMP/config"
mkdir -p "$FLEET_STATE/state" "$FLEET_CONFIG" "$TMP/bin"
export PATH="$TMP/bin:$PATH"
ok=1
chk() {
  if eval "$2"; then
    echo "  PASS $1"
  else
    echo "  FAIL $1"
    ok=0
  fi
}

cat > "$TMP/bin/systemctl" <<'SH'
#!/bin/sh
case "$*" in
  *" is-active "*) echo inactive; exit 3 ;;
esac
exit 0
SH
cat > "$TMP/bin/tmux" <<'SH'
#!/bin/sh
exit 1
SH
cat > "$TMP/bin/gh" <<SH
#!/bin/sh
[ -f "$TMP/gh-fail" ] && exit 1
printf '[]\n'
SH
chmod +x "$TMP/bin/systemctl" "$TMP/bin/tmux" "$TMP/bin/gh"

git init -q --bare "$TMP/origin.git"
git clone -q "$TMP/origin.git" "$TMP/proj"
git -C "$TMP/proj" config user.email t@t
git -C "$TMP/proj" config user.name test
git -C "$TMP/proj" commit -q --allow-empty -m init
git -C "$TMP/proj" branch -M main
git -C "$TMP/proj" push -q origin main
printf '[testproj]\nrepo = "x/y"\npath = "%s"\nbranch = "main"\n' \
  "$TMP/proj" > "$FLEET_CONFIG/projects.toml"
WTROOT="$FLEET_STATE/worktrees/testproj"
mkdir -p "$WTROOT"

mkrec() { # slug worktree branch status [owner] [started_at]
  python3 - "$1" "$2" "$3" "$4" "${5:-}" "${6:-}" <<PY
import json, os, sys, time
slug, wt, branch, status, owner, started = sys.argv[1:]
record = {
    "slug": slug, "project": "testproj", "worktree": wt, "branch": branch,
    "status": status, "spawned_by": owner,
    "started_at": int(started or time.time()), "updated_at": int(started or time.time()),
}
json.dump(record, open(os.path.join(os.environ["FLEET_STATE"], "state", slug + ".json"), "w"))
PY
}

mkwt() { # slug branch [path]
  local slug="$1" branch="$2" wt="${3:-$WTROOT/$1}"
  git -C "$TMP/proj" worktree add -q -b "$branch" "$wt" main >/dev/null 2>&1
}

echo "== registry is atomic, idempotent, and diagnoses corruption =="
mkdir -p "$TMP/add-config"
ADD1=$(FLEET_CONFIG="$TMP/add-config" "$FLEET" add-project --name testproj \
  --repo x/y --path "$TMP/proj" 2>&1)
ADD2=$(FLEET_CONFIG="$TMP/add-config" "$FLEET" add-project --name testproj \
  --repo x/y --path "$TMP/proj" 2>&1)
chk "add-project can be repeated without duplicate tables" \
  '[ "$(grep -c "testproj" "$TMP/add-config/projects.toml")" -eq 1 ] &&
   echo "$ADD2" | grep -q "already registered"'
mkdir -p "$TMP/bad-config"
printf '[broken\n' > "$TMP/bad-config/projects.toml"
BAD=$(FLEET_CONFIG="$TMP/bad-config" "$FLEET" projects 2>&1)
BAD_RC=$?
chk "invalid registry is reported instead of looking unregistered" \
  '[ "$BAD_RC" -ne 0 ] && echo "$BAD" | grep -q "invalid project registry"'

echo "== gentle clean protects unpushed work and accepts the candidate path =="
mkwt lane-a-111 fleet/lane-a-111
(cd "$WTROOT/lane-a-111" && echo work > f.txt &&
  git add -A && git commit -q -m "lane a work")
mkrec lane-a-111 "$WTROOT/lane-a-111" fleet/lane-a-111 failed mine

mkwt lane-b-222 fleet/lane-b-222
git -C "$WTROOT/lane-b-222" push -q -u origin fleet/lane-b-222 2>/dev/null
mkrec lane-b-222 "$WTROOT/lane-b-222" fleet/lane-b-222 ended mine

OUT=$("$FLEET" clean --project testproj 2>&1)
echo "$OUT" | sed 's/^/    /'
chk "lane-a KEPT (unpushed protected)" \
  '[ -d "$WTROOT/lane-a-111" ] && [ -f "$FLEET_STATE/state/lane-a-111.json" ]'
chk "lane-b removed (safe)" '[ ! -d "$WTROOT/lane-b-222" ]'
chk "clean explained the keep" 'echo "$OUT" | grep -q "KEEP lane-a-111.*unpushed"'

OUT=$("$FLEET" salvage lane-a-111 2>&1)
chk "salvage pushes protected commits" \
  'git -C "$TMP/proj" ls-remote --heads origin fleet/lane-a-111 | grep -q lane-a'
"$FLEET" clean --project testproj >/dev/null 2>&1
chk "clean removes a lane after successful salvage" '[ ! -d "$WTROOT/lane-a-111" ]'

echo "== force cleanup is scoped, confirmed, and snapshotted =="
mkwt force-dirty fleet/force-dirty
echo dirty > "$WTROOT/force-dirty/dirty.txt"
mkrec force-dirty "$WTROOT/force-dirty" fleet/force-dirty failed mine
OUT=$("$FLEET" clean --force --by mine 2>&1)
chk "force refuses unsaved work without --yes" \
  '[ -d "$WTROOT/force-dirty" ] && echo "$OUT" | grep -q -- "--yes"'
"$FLEET" clean --force --by mine --yes >/dev/null 2>&1
FORCE_SNAP=$(find "$FLEET_STATE/state-archive" -name force-dirty.dirt.txt -print -quit 2>/dev/null)
chk "confirmed force snapshots dirt before removal" \
  '[ ! -d "$WTROOT/force-dirty" ] && [ -n "$FORCE_SNAP" ] &&
   grep -q dirty.txt "$FORCE_SNAP"'

for row in own-live other-live own-done other-done; do
  mkwt "$row" "fleet/$row"
  git -C "$WTROOT/$row" push -q -u origin "fleet/$row" 2>/dev/null
done
mkrec own-live "$WTROOT/own-live" fleet/own-live running mine
mkrec other-live "$WTROOT/other-live" fleet/other-live running theirs
mkrec own-done "$WTROOT/own-done" fleet/own-done ended mine
mkrec other-done "$WTROOT/other-done" fleet/other-done ended theirs
"$FLEET" clean --force --by mine --yes >/dev/null 2>&1
chk "--by scopes both running and terminal cleanup to its owner" \
  '[ ! -d "$WTROOT/own-live" ] && [ ! -d "$WTROOT/own-done" ] &&
   [ -d "$WTROOT/other-live" ] && [ -d "$WTROOT/other-done" ]'

echo "== clean rejects ambiguous flags and unsafe record paths =="
OUT=$("$FLEET" clean --all 2>&1)
RC=$?
chk "unknown clean flags fail instead of widening scope" \
  '[ "$RC" -ne 0 ] && echo "$OUT" | grep -q "unknown" &&
   [ -d "$WTROOT/other-done" ]'
OUT=$("$FLEET" clean --project testproj --dry-run 2>&1)
chk "clean dry-run previews without deleting" \
  '[ -d "$WTROOT/other-done" ] && echo "$OUT" | grep -q "would clean"'

mkdir -p "$TMP/cwd-victim/testproj"
echo irreplaceable > "$TMP/cwd-victim/testproj/important.txt"
mkrec shifted "" "" ended mine
OUT=$(cd "$TMP/cwd-victim" && "$FLEET" clean --project testproj 2>&1)
chk "missing worktree field cannot shift project into relative rm target" \
  '[ -f "$TMP/cwd-victim/testproj/important.txt" ] &&
   [ -f "$FLEET_STATE/state/shifted.json" ] &&
   echo "$OUT" | grep -q "missing worktree"'

SPACE_WT="$WTROOT/lane with space"
mkwt space-lane fleet/space-lane "$SPACE_WT"
git -C "$SPACE_WT" push -q -u origin fleet/space-lane 2>/dev/null
mkrec space-lane "$SPACE_WT" fleet/space-lane ended mine
"$FLEET" clean --project testproj >/dev/null 2>&1
chk "worktree paths containing spaces are not field-shifted" '[ ! -d "$SPACE_WT" ]'

echo "== inspection and salvage fail closed =="
mkwt corrupt fleet/corrupt
git -C "$WTROOT/corrupt" push -q -u origin fleet/corrupt 2>/dev/null
echo modified >> "$WTROOT/corrupt/README.md"
mkrec corrupt "$WTROOT/corrupt" fleet/corrupt failed mine
CORRUPT_INDEX=$(git -C "$WTROOT/corrupt" rev-parse --git-path index)
printf broken-index > "$CORRUPT_INDEX"
OUT=$("$FLEET" salvage corrupt 2>&1)
RC=$?
chk "salvage refuses an unreadable index and never claims safety" \
  '[ "$RC" -ne 0 ] && echo "$OUT" | grep -q "cannot inspect" &&
   ! echo "$OUT" | grep -q "safe to \`fleet clean\`"'
OUT=$("$FLEET" clean --project testproj 2>&1)
chk "clean keeps a worktree when git status fails" \
  '[ -f "$WTROOT/corrupt/README.md" ] && echo "$OUT" | grep -q "cannot inspect"'

mkwt missing-git fleet/missing-git
git -C "$WTROOT/missing-git" push -q -u origin fleet/missing-git 2>/dev/null
echo untracked > "$WTROOT/missing-git/new.txt"
mkrec missing-git "$WTROOT/missing-git" fleet/missing-git failed mine
mv "$WTROOT/missing-git/.git" "$WTROOT/missing-git/.git.saved"
OUT=$("$FLEET" clean --project testproj 2>&1)
chk "clean keeps a worktree whose .git link is missing" \
  '[ -f "$WTROOT/missing-git/new.txt" ] && echo "$OUT" | grep -q "missing .git"'

mkwt empty-record fleet/empty-record
echo rescued > "$WTROOT/empty-record/rescue.txt"
: > "$FLEET_STATE/state/empty-record.json"
OUT=$("$FLEET" salvage empty-record 2>&1)
chk "salvage recovers a worktree by convention from an empty record" \
  'git -C "$TMP/proj" ls-remote --heads origin fleet/empty-record |
   grep -q empty-record && echo "$OUT" | grep -q "record unreadable"'
OUT=$("$FLEET" tail empty-record 2>&1)
RC=$?
chk "tail degrades cleanly on an empty record" \
  '[ "$RC" -eq 0 ] && echo "$OUT" | grep -q "record unreadable" &&
   ! echo "$OUT" | grep -q Traceback'

echo "== stale active records are recoverable =="
mkwt stale-active fleet/stale-active
git -C "$WTROOT/stale-active" push -q -u origin fleet/stale-active 2>/dev/null
mkrec stale-active "$WTROOT/stale-active" fleet/stale-active running mine 1
"$FLEET" clean --project testproj >/dev/null 2>&1
chk "inactive old running record is no longer immortal" \
  '[ ! -d "$WTROOT/stale-active" ] && [ ! -f "$FLEET_STATE/state/stale-active.json" ]'

echo "== sweep fails closed, has a pure dry-run, and preserves complete autopsies =="
SWEEP_STATE="$TMP/sweep-state"
mkdir -p "$SWEEP_STATE/state" "$SWEEP_STATE/worktrees/testproj"
rm -rf "$SWEEP_STATE/state-archive"
FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj --dry-run >/dev/null 2>&1
chk "sweep dry-run creates no archive directory" '[ ! -e "$SWEEP_STATE/state-archive" ]'

HUMAN_ROOT="$TMP/human-owned"
HUMAN_WT="$HUMAN_ROOT/plain-lane"
mkdir -p "$HUMAN_ROOT"
git -C "$TMP/proj" worktree add -q -b human/plain-lane "$HUMAN_WT" main
FLEET_STATE="$SWEEP_STATE" mkrec human-owned "$HUMAN_WT" human/plain-lane ended mine 1
OUT=$(FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj 2>&1)
chk "plain sweep keeps a registered worktree outside the fleet root" \
  '[ -d "$HUMAN_WT" ] &&
   [ -f "$SWEEP_STATE/state/human-owned.json" ] &&
   echo "$OUT" | grep -q "keep record human-owned.*worktree is not fleet-owned"'

SWEEP_ROOT="$SWEEP_STATE/worktrees/testproj"
git -C "$TMP/proj" worktree add -q -b fleet/gh-unknown "$SWEEP_ROOT/gh-unknown" main
git -C "$SWEEP_ROOT/gh-unknown" push -q -u origin fleet/gh-unknown 2>/dev/null
FLEET_STATE="$SWEEP_STATE" mkrec gh-unknown "$SWEEP_ROOT/gh-unknown" \
  fleet/gh-unknown ended mine 1
touch "$TMP/gh-fail"
OUT=$(FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj 2>&1)
rm "$TMP/gh-fail"
chk "GitHub failure is UNKNOWN and protects an open-or-unknown lane" \
  '[ -d "$SWEEP_ROOT/gh-unknown" ] && echo "$OUT" | grep -q "GitHub state is UNKNOWN"'

git -C "$TMP/proj" worktree add -q -b fleet/sweep-corrupt "$SWEEP_ROOT/sweep-corrupt" main
echo modified >> "$SWEEP_ROOT/sweep-corrupt/README.md"
SWEEP_INDEX=$(git -C "$SWEEP_ROOT/sweep-corrupt" rev-parse --git-path index)
printf corrupt > "$SWEEP_INDEX"
OUT=$(FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj 2>&1)
chk "sweep keeps a worktree when dirt inspection fails" \
  '[ -f "$SWEEP_ROOT/sweep-corrupt/README.md" ] &&
   echo "$OUT" | grep -q "cannot inspect"'

git -C "$TMP/proj" worktree add -q -b fleet/autopsy "$SWEEP_ROOT/autopsy" main
echo staged-content > "$SWEEP_ROOT/autopsy/staged.txt"
git -C "$SWEEP_ROOT/autopsy" add staged.txt
echo untracked-content > "$SWEEP_ROOT/autopsy/untracked.txt"
FLEET_STATE="$SWEEP_STATE" mkrec autopsy "$SWEEP_ROOT/autopsy" fleet/autopsy ended mine 1
OUT=$(FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj 2>&1)
chk "long-dead pass cannot override the dirty-worktree keep" \
  '[ -f "$SWEEP_ROOT/autopsy/staged.txt" ] &&
   [ -f "$SWEEP_ROOT/autopsy/untracked.txt" ]'
FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj --force >/dev/null 2>&1
AUTOPSY_TXT=$(find "$SWEEP_STATE/state-archive" -name autopsy.dirt.txt -print -quit 2>/dev/null)
AUTOPSY_TAR=$(find "$SWEEP_STATE/state-archive" -name autopsy.untracked.tar -print -quit 2>/dev/null)
chk "forced sweep snapshots staged and untracked content before removal" \
  '[ ! -d "$SWEEP_ROOT/autopsy" ] && [ -n "$AUTOPSY_TXT" ] &&
   grep -q staged-content "$AUTOPSY_TXT" && [ -n "$AUTOPSY_TAR" ] &&
   tar -tf "$AUTOPSY_TAR" | grep -q untracked.txt'

git -C "$TMP/proj" worktree add -q -b fleet/sweep-stale "$SWEEP_ROOT/sweep-stale" main
git -C "$SWEEP_ROOT/sweep-stale" push -q -u origin fleet/sweep-stale 2>/dev/null
FLEET_STATE="$SWEEP_STATE" mkrec sweep-stale "$SWEEP_ROOT/sweep-stale" \
  fleet/sweep-stale running mine 1
FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj >/dev/null 2>&1
chk "sweep reaps an inactive old running record" \
  '[ ! -d "$SWEEP_ROOT/sweep-stale" ] &&
   [ ! -f "$SWEEP_STATE/state/sweep-stale.json" ]'


# A torn record blocks the whole project, and nothing else moves it, so one truncated file used to
# wedge the janitor permanently. It is retired only after it has stayed unparseable past GRACE -
# a record written a second ago may simply be mid-write.
git -C "$TMP/proj" worktree add -q -b fleet/blocked "$SWEEP_ROOT/blocked" main
git -C "$SWEEP_ROOT/blocked" commit -q --allow-empty -m blocked-work
git -C "$TMP/proj" merge -q fleet/blocked 2>/dev/null
git -C "$TMP/proj" push -q origin main 2>/dev/null
FLEET_STATE="$SWEEP_STATE" mkrec blocked "$SWEEP_ROOT/blocked" fleet/blocked ended mine 1

printf '{"slug":"fresh-tear","proj' > "$SWEEP_STATE/state/fresh-tear.json"
FRESH_OUT=$(FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj --force 2>&1)
chk "a record torn just now still aborts the pass and deletes nothing" \
  '[ -d "$SWEEP_ROOT/blocked" ] && printf "%s" "$FRESH_OUT" | grep -q ABORT'

touch -d "3 hours ago" "$SWEEP_STATE/state/fresh-tear.json"
FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj --force >/dev/null 2>&1
QUAR=$(find "$SWEEP_STATE/state-archive" -name 'fresh-tear.json.corrupt' -print -quit 2>/dev/null)
chk "a record torn for longer than GRACE is archived, not deleted" \
  '[ -n "$QUAR" ] && [ ! -f "$SWEEP_STATE/state/fresh-tear.json" ]'

SECOND=$(FLEET_STATE="$SWEEP_STATE" "$FLEET" sweep --project testproj --force 2>&1)
chk "the janitor is unwedged on the next pass and clears the backlog" \
  '! printf "%s" "$SECOND" | grep -q ABORT && [ ! -d "$SWEEP_ROOT/blocked" ]'

echo
[ "$ok" = 1 ] && echo "RESULT: ALL PASS" || echo "RESULT: FAILURES"
[ "$ok" = 1 ]
