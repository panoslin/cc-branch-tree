---
description: Restore conversations previously hidden from /tree (use "all" to restore everything)
argument-hint: "<index | a-b range | id-prefix | \"title substring\" | all> [more…]"
disable-model-invocation: true
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Output the result below verbatim as your entire reply, nothing else:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" unhide $ARGUMENTS`
