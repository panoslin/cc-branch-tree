---
description: Soft-hide one or more conversations from /tree (reversible; the transcript is NOT deleted)
argument-hint: "<index | id-prefix | name> [more…]"
disable-model-invocation: true
allowed-tools: Bash(python3 *)
model: haiku
effort: low
---
Output the result below verbatim as your entire reply, nothing else:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" hide $ARGUMENTS`
