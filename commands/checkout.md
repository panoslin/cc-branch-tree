---
description: Resume a branch session in a new terminal window (cd into its project, then claude --resume)
argument-hint: "<index | session-id prefix | name fragment>"
disable-model-invocation: true
allowed-tools: Bash(python3 *), Bash(bash *)
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cc_tree.py" resume "$0" --launch`
