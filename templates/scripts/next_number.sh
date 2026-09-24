#!/usr/bin/env bash
# Print the next free number for each kind of numbered file, checking BOTH the
# main branch AND every open pull request.
#
# Why scan open pull requests: numbered files (decision records, database
# migrations, anything whose file name starts with NNNN) are claimed by
# creating a file, and a file on an unmerged branch is invisible to anyone who
# scans only main. Three parallel workers each scan main, each see the same
# highest number, and each take the next one. The collision shows up at merge
# time, when renumbering means rewriting cross-references in a hurry.
#
# So reserve your number at the START of a batch, before any code. Fetch first
# (git fetch origin), so the main branch you scan is current. If two workers
# still race, the one who merges second renumbers. A CI check should catch a
# duplicate number or a split migration history before it reaches main.
#
#   scripts/next_number.sh              # every kind: main plus every open PR
#   scripts/next_number.sh adr          # one kind
#   scripts/next_number.sh --main-only  # skip the pull request scan (faster)
#
# Scanning open pull requests is the default, because that scan prevents the
# collision. Use --main-only when you are offline or in a hurry, and expect to
# renumber if another lane took the same number today.
#
# The pull request scan needs the GitHub CLI (`gh`), signed in. Without it, the
# script scans main only and says so, because a silent fallback could hand out
# a number somebody else has already taken.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# ---------------------------------------------------------------------------
# EDIT THIS. One entry per kind of numbered file:
#     <kind>|<extended regular expression matching its paths>
# The number is read from the first four digits of the file name.
# The regex must match every place a number can be claimed, INCLUDING archives:
# an archived record still owns its number forever. If you scan only the live
# directory, the script works until you archive the highest-numbered record,
# and then it hands out a number that is already in use.
# ---------------------------------------------------------------------------
KINDS=(
  "adr|docs/(adr|archive/adr)/[0-9]{4}-"
  "migration|<path/to/migrations>/[0-9]{4}_"
)

BASE_REF="${BASE_REF:-origin/main}"

scan_prs=1
want="all"
for arg in "$@"; do
  case "$arg" in
    --main-only) scan_prs=0 ;;
    --all) scan_prs=1 ;;  # the default; accepted so a caller can say it explicitly
    --help | -h)
      sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) want="$arg" ;;
  esac
done

# A base branch that does not resolve would scan nothing and hand out 0001.
if ! git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
  echo "error: $BASE_REF not found. Run 'git fetch origin' first, or set BASE_REF (for example BASE_REF=origin/master)." >&2
  exit 1
fi

# The head of every open pull request, once for all kinds. A pull request from
# a fork is listed as owner:branch, the form the compare API expects for it.
# gh lists 30 pull requests unless told otherwise, hence the explicit limit.
heads=""
if [ "$scan_prs" = "1" ]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "note: no 'gh' found, scanning $BASE_REF only; an in-flight claim can be missed" >&2
    scan_prs=0
  elif ! heads=$(gh pr list --state open --limit 1000 \
      --json headRefName,headRepositoryOwner,isCrossRepository \
      -q '.[] | if .isCrossRepository then "\(.headRepositoryOwner.login):\(.headRefName)" else .headRefName end' \
      2>/dev/null); then
    echo "note: 'gh pr list' failed (not signed in, or no GitHub remote?), scanning $BASE_REF only; an in-flight claim can be missed" >&2
    scan_prs=0
  fi
fi

# Highest NNNN currently claimed for one path regex, on the base branch and,
# unless --main-only was passed, on every open pull request's changed files.
_max_number() {
  local path_re="$1"
  {
    git ls-tree -r "$BASE_REF" --name-only 2>/dev/null | grep -E "$path_re" || true
    if [ "$scan_prs" = "1" ]; then
      local head base
      for head in $heads; do
        base="${BASE_REF##*/}"
        # A fork's head is owner:branch, and then the base needs its owner too.
        case "$head" in *:*) base="{owner}:$base" ;; esac
        gh api "repos/{owner}/{repo}/compare/${base}...${head}" \
          -q '.files[].filename' 2>/dev/null | grep -E "$path_re" || true
      done
    fi
  } | sed 's#.*/##' | { grep -oE '^[0-9]{4}' || true; } | sort -n | tail -1
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
