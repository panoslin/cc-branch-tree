#!/usr/bin/env bash
# Open `claude --resume <session-id>` in a NEW terminal window, in the session's
# project directory. Prefers tmux, then iTerm, then Terminal.app; otherwise prints
# the command for manual use. (Paths containing a double-quote are not supported.)
set -euo pipefail

CWD="${1:?usage: launch.sh <cwd> <session-id>}"
SID="${2:?usage: launch.sh <cwd> <session-id>}"
INNER="cd \"$CWD\" && claude --resume $SID"

if [ -n "${TMUX:-}" ]; then
  tmux new-window -n "br:${SID:0:6}" "$INNER; exec \$SHELL"
  echo "✓ opened branch ${SID:0:8} in a new tmux window"
  exit 0
fi

if command -v osascript >/dev/null 2>&1; then
  OSA_INNER=${INNER//\"/\\\"}
  if [ "${TERM_PROGRAM:-}" = "iTerm.app" ]; then
    osascript >/dev/null <<OSA
tell application "iTerm"
  create window with default profile
  tell current session of current window to write text "$OSA_INNER"
end tell
OSA
    echo "✓ opened branch ${SID:0:8} in a new iTerm window"
    exit 0
  fi
  osascript >/dev/null <<OSA
tell application "Terminal"
  activate
  do script "$OSA_INNER"
end tell
OSA
  echo "✓ opened branch ${SID:0:8} in a new Terminal window"
  exit 0
fi

echo "Auto-open is not supported on this platform yet. Run this manually:"
echo "  $INNER"
