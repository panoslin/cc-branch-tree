---
description: Inspect a session's internal /rewind branches (message-level divergences within one conversation)
argument-hint: "<index | session-id prefix | name fragment>"
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Output the result below verbatim as your entire reply — no code fences, no extra text:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" inspect "$0"`
