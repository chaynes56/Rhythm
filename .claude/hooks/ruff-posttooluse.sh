#!/usr/bin/env bash
#
# PostToolUse hook for Claude Code: run `ruff check` on edited Python files.
#
# Claude Code pipes a JSON payload to this script on stdin, e.g.:
#   { "tool_name": "Edit", "tool_input": { "file_path": "/path/to/file.py" }, ... }
#
# Exit codes (PostToolUse semantics):
#   0  -> success / nothing to do (silent)
#   2  -> ruff found problems; stderr is fed back to Claude so it can fix them
#
# Any other non-zero exit just shows stderr to you (the user), not to Claude.

set -uo pipefail

# --- 1. Read the whole stdin payload -----------------------------------------
payload="$(cat)"

# --- 2. Extract tool_input.file_path -----------------------------------------
# Prefer jq; fall back to python3 if jq isn't installed.
if command -v jq >/dev/null 2>&1; then
  file_path="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')"
elif command -v python3 >/dev/null 2>&1; then
  file_path="$(printf '%s' "$payload" | python3 -c \
    'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')"
else
  echo "ruff hook: neither jq nor python3 found; cannot parse hook input." >&2
  exit 0   # misconfiguration on our side — don't block the edit
fi

# --- 3. Bail out quietly when there's nothing to lint ------------------------
[ -n "$file_path" ]      || exit 0          # no path in payload
case "$file_path" in *.py) ;; *) exit 0 ;; esac   # not a Python file
[ -f "$file_path" ]      || exit 0          # file no longer exists

# --- 4. Make sure ruff is actually available ---------------------------------
# Edit RUFF below if ruff lives in a venv, e.g. RUFF="uv run ruff"
RUFF="ruff"
if ! command -v "$RUFF" >/dev/null 2>&1; then
  echo "ruff hook: '$RUFF' not found on PATH; skipping lint of $file_path." >&2
  exit 0   # don't punish the edit for a tooling gap
fi

# --- 5. Lint. If ruff complains, surface it to Claude via exit 2 -------------
if ! output="$("$RUFF" check "$file_path" 2>&1)"; then
  echo "ruff found issues in $file_path:" >&2
  echo "$output" >&2
  exit 2
fi

exit 0
