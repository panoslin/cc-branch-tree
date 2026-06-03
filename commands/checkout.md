---
description: Copy a branch's resume command to the clipboard (and print it); does not open a window
argument-hint: "<index | session-id prefix | name fragment>"
disable-model-invocation: true
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Output the result below verbatim as your entire reply — no code fences, no backticks, no extra text:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" resume "$0"`
