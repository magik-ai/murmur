#!/usr/bin/env bash
# PreToolUse guard: files that are generated are never hand-edited.
#
# The list of protected paths belongs to the repository, not to this plugin.
# Put one glob per line in ${CLAUDE_PROJECT_DIR}/.claude/generated-files.txt.
# Everything up to the first space is the glob; the rest of the line, if any,
# is the command that regenerates the file and is shown to the agent.
# Lines starting with # and blank lines are ignored.
# No list, no guard: the hook exits 0 and says nothing.
#
# Exit 2 blocks the edit and feeds the reason back to the agent. Regeneration
# scripts run through Bash and are not touched by this hook.
set -euo pipefail

list="${CLAUDE_PROJECT_DIR:-.}/.claude/generated-files.txt"
[ -f "$list" ] || exit 0

payload=$(cat)
path=$(printf '%s' "$payload" | python3 -c "
import sys, json
try:
    t = json.load(sys.stdin).get('tool_input', {})
    print(t.get('file_path') or t.get('notebook_path') or '')
except Exception:
    print('')
" 2>/dev/null) || path=""
[ -n "$path" ] || exit 0

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|'#'*) continue ;; esac
  glob=${line%% *}
  if [ "$glob" = "$line" ]; then
    how=""
  else
    how=${line#* }
    while [ "${how# }" != "$how" ]; do how=${how# }; done
  fi
  # A glob that does not start at the filesystem root matches any prefix, so
  # a repository-relative entry works whatever the checkout is called.
  case "$glob" in /*|\**) pattern="$glob" ;; *) pattern="*$glob" ;; esac
  # shellcheck disable=SC2254
  case "$path" in
    $pattern)
      echo "BLOCKED: $path is generated, never hand-edit it." >&2
      if [ -n "$how" ]; then echo "Regenerate instead: $how" >&2; fi
      exit 2
      ;;
  esac
done < "$list"

exit 0
