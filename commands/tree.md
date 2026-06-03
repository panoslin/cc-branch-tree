---
description: Show the conversation fork tree across all projects (recent-first; optional time window + project filter)
argument-hint: "[10d|3h|2w|30m] [all] [project]"
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Output the tree below to the user verbatim, inside ONE fenced code block, as your entire reply. Add nothing else: no summary, no analysis, no preamble, no follow-up question. Do not think.

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" render $ARGUMENTS`
