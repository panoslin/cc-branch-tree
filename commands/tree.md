---
description: Browse the conversation fork tree across all projects (grouped by project, nested by fork)
argument-hint: "[project filter]"
allowed-tools: Bash(python3 *)
---
Conversation fork tree — each `[n]` is the index used by `/checkout`. Indentation shows fork parent → child.

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" render $ARGUMENTS`

To resume any node into a new terminal window, run `/checkout <index | id-prefix | name fragment>`.
