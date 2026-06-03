---
description: Print the copyable resume command for a branch (does not open a window)
argument-hint: "<index | session-id prefix | name fragment>"
disable-model-invocation: true
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Your entire reply must be exactly the line below, copied verbatim. Do NOT wrap it in a code block or backticks, do NOT add surrounding quotes, and do NOT add any words before or after — output only the raw shell command on a single line so it can be pasted and run directly:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" resume "$0"`
