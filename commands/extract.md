---
description: Extract an abandoned branch (a [ref] from the last /inspect) as markdown — printed and copied to the clipboard
argument-hint: "<branch ref from /inspect, e.g. 1a>"
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Output the result below verbatim as your entire reply — no code fences, no extra text:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" extract "$0"`
