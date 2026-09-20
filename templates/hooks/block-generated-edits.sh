#!/usr/bin/env bash
# PreToolUse guard: generated artifacts are never hand-edited.
#
# Why this exists. A generated file (an API schema, a generated client, a lock
# file, an inventory, a compiled catalog) is an OUTPUT. Editing it by hand
# produces a file that disagrees with its source, passes review because it looks
# plausible, and either breaks the next regeneration or, worse, encodes a
# contract nobody wrote. Asking agents nicely does not work: the edit is always
# one line and always urgent. So the harness refuses it.
#
# Exit 2 blocks the tool call and shows the message on stderr to the agent, so
# the remedy has to be in the message. An agent that is blocked without being
# told what to run instead will try the same edit a different way.
#
# The regeneration commands run through the shell and are NOT matched by this
# hook, so the escape hatch is always open and always the correct one.
#
# Install: see settings.json next to this file.
set -euo pipefail

# ---------------------------------------------------------------------------
# EDIT THIS LIST. One glob per line, repo-relative, each with a leading * so it
# matches whatever absolute prefix the tool passes. Add a path the day you add a
# generator, not the day after someone hand-edits its output.
# ---------------------------------------------------------------------------
GENERATED_GLOBS=(
  "*<path/to/api-schema.json>"
  "*<path/to/generated-client>/*"
  "*<path/to/generated-types>.ts"
  "*<path/to/generated-inventory>.md"
  "*<path/to/generated-catalog>.json"
)

# ---------------------------------------------------------------------------
# EDIT THIS TOO. The remedy, naming the exact command per artifact. Vague advice
# ("regenerate it") costs the agent a search and gets ignored.
# ---------------------------------------------------------------------------
REMEDY="Regenerate instead: <command for the schema and client>; <command for the types>; <command for the inventory>."

payload=$(cat)
file_path=$(printf '%s' "$payload" | python3 -c "import sys, json
try:
    print(json.load(sys.stdin).get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')" 2>/dev/null) || file_path=""

# No path in the payload means nothing to judge: never block on a parse failure.
[ -n "$file_path" ] || exit 0

for glob in "${GENERATED_GLOBS[@]}"; do
  # shellcheck disable=SC2254  # the glob is intentionally unquoted on the right
  case "$file_path" in
    $glob)
      echo "BLOCKED: $file_path is a generated artifact. Never hand-edit it." >&2
      echo "$REMEDY" >&2
      echo "If the generator's output is wrong, fix the generator or its input, in this same pull request." >&2
      exit 2
      ;;
  esac
done

exit 0
