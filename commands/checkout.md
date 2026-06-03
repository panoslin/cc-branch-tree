---
description: Copy a branch's in-session /resume command to the clipboard (paste here to switch); also prints the new-terminal command
argument-hint: "<index | session-id prefix | name fragment>"
disable-model-invocation: true
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Output the result below verbatim as your entire reply — no code fences, no backticks, no extra text:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" resume "$0"`
