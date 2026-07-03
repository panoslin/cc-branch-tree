---
description: Full-text search across all conversations (AND keywords, case-insensitive; result indices work with /checkout and /hide)
argument-hint: "<keyword> [more…] [10d|3h|2w]"
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Output the result below to the user verbatim, inside ONE fenced code block, as your entire reply. Add nothing else: no summary, no analysis, no preamble, no follow-up question. Do not think.

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" search $ARGUMENTS`
