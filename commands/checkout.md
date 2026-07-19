---
description: Copy a branch's new-terminal `cd … && claude --resume` command to the clipboard (works across projects); also prints the in-session /resume shortcut
argument-hint: "<index | session-id prefix | name fragment>"
disable-model-invocation: true
allowed-tools: Bash(python3 *)
effort: low
---
Output the result below verbatim as your entire reply — no code fences, no backticks, no extra text:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" resume "$0"`
