#!/usr/bin/env bash
# Print the next free sequential number for each numbered artifact kind, checking
# BOTH the main branch AND every open pull request.
#
# Why the open-pull-request scan. Numbered artifacts (decision records, database
# migrations, anything whose file name starts NNNN) are claimed by creating a
# file, and a file on an unmerged branch is invisible to anyone scanning main.
# Three parallel workers each scan main, each see the same highest number, and
# each take the next one. The collision surfaces at merge time, when renumbering
# means rewriting cross-references: archaeology, done in a hurry, by whoever
# merged last.
#
# So: reserve your number at the START of a batch, before any code. If two
# workers still race, the loser renumbers, and a CI check should catch a
# duplicate number or a split migration history before it reaches main.
#
#   scripts/next_number.sh            # every kind, scanning main only (fast)
#   scripts/next_number.sh adr        # one kind
#   scripts/next_number.sh --all      # also scan every OPEN pull request (slower)
#
# The open-pull-request scan needs the `gh` command line tool, authenticated.
# Without it, the script still works against main and says so.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# ---------------------------------------------------------------------------
# EDIT THIS. One entry per numbered artifact kind:
#     <kind>|<extended regular expression matching its paths>
# The regex must match every place a number can be claimed, INCLUDING archives:
# an archived record still owns its number forever, and scanning only the live
# directory works right up until you archive the highest-numbered one, at which
# point the script starts handing out a number that is already in use.
# ---------------------------------------------------------------------------
KINDS=(
  "adr|docs/(adr|archive/adr)/[0-9]{4}-"
  "migration|<path/to/migrations>/[0-9]{4}_"
)

BASE_REF="${BASE_REF:-origin/main}"

scan_prs=0
want="all"
for arg in "$@"; do
  case "$arg" in
    --all) scan_prs=1 ;;
    --help | -h)
      sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) want="$arg" ;;
  esac
done

if [ "$scan_prs" = "1" ] && ! command -v gh >/dev/null 2>&1; then
  echo "note: no 'gh' found, scanning $BASE_REF only; an in-flight claim can be missed" >&2
  scan_prs=0
fi

# Highest NNNN currently claimed for one path regex, on the base branch and,
# with --all, on every open pull request's changed files.
_max_number() {
  local path_re="$1"
  {
    git ls-tree -r "$BASE_REF" --name-only 2>/dev/null | grep -E "$path_re" || true
    if [ "$scan_prs" = "1" ]; then
      local branch
      for branch in $(gh pr list --state open --json headRefName -q '.[].headRefName' 2>/dev/null); do
        gh api "repos/{owner}/{repo}/compare/${BASE_REF##*/}...${branch}" \
          -q '.files[].filename' 2>/dev/null | grep -E "$path_re" || true
      done
    fi
  } | { grep -oE '[0-9]{4}' || true; } | sort -n | tail -1
}

_next_of() {
  printf '%04d' "$((10#${1:-0} + 1))"
}

found=0
for entry in "${KINDS[@]}"; do
  kind="${entry%%|*}"
  path_re="${entry#*|}"
  if [ "$want" = "all" ] || [ "$want" = "$kind" ]; then
    found=1
    current=$(_max_number "$path_re")
    printf 'next %-12s %s   (highest seen: %s)\n' \
      "$kind:" "$(_next_of "$current")" "${current:-none}"
  fi
done

if [ "$found" = "0" ]; then
  echo "unknown kind: $want" >&2
  printf 'known kinds:' >&2
  for entry in "${KINDS[@]}"; do printf ' %s' "${entry%%|*}" >&2; done
  printf '\n' >&2
  exit 1
fi
