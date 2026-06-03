---
description: Print the copyable resume command for a branch (does not open a window)
argument-hint: "<index | session-id prefix | name fragment>"
disable-model-invocation: true
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Output the command below verbatim, inside ONE fenced code block, as your entire reply. Output nothing else: no explanation, no preamble, no follow-up.

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" resume "$0"`
