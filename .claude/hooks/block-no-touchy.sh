#!/usr/bin/env bash
# PreToolUse guard: deny any Write/Edit/NotebookEdit targeting the no-touchy/ folder.
# Reads the hook payload on stdin, resolves the target path, and emits a deny
# decision if it falls inside <project>/no-touchy.

input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0

proj="${CLAUDE_PROJECT_DIR:-/home/schrock/src/stonks}"

# Resolve to an absolute path (relative paths are project-rooted).
case "$file" in
  /*) abs="$file" ;;
  *)  abs="$proj/$file" ;;
esac

# Canonicalize ../ and ./ without requiring the path to exist (realpath -m),
# falling back to a best-effort resolve via the parent dir if realpath is absent.
if abs_norm=$(realpath -m -- "$abs" 2>/dev/null); then
  abs="$abs_norm"
else
  dir=$(dirname "$abs")
  if base_dir=$(cd "$dir" 2>/dev/null && pwd); then
    abs="$base_dir/$(basename "$abs")"
  fi
fi

guard="$proj/no-touchy"
case "$abs" in
  "$guard" | "$guard"/*)
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "no-touchy/ is protected: edits and new files there are blocked by a PreToolUse hook."
      }
    }'
    ;;
esac
exit 0
