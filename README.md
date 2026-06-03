# cc-branch-tree

A Claude Code plugin that visualizes your conversation **fork tree** across all projects and lets you resume any branch in a new terminal window — like `git branch` + `checkout` for Claude Code sessions.

> **Status**: in development (MVP). See [docs/specs/2026-06-01-cc-branch-tree-design.md](docs/specs/2026-06-01-cc-branch-tree-design.md).

## What it does

- `/tree [filter]` — render all sessions grouped by project, with true parent→child fork nesting, titles, message counts, and idle time.
- `/checkout <index | id-prefix | name>` — print the copyable resume command (`cd <cwd> && claude --resume <session-id>`) for the chosen node. (A one-click window opener, `scripts/launch.sh`, still ships — call `cc_tree.py resume <sel> --launch` if you prefer auto-open.)

## How it works (no Claude Code internals are modified)

Claude Code stores each session as JSONL at `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`. A `/branch` (`/fork`) copies the parent's history into a new session file and stamps inherited entries with `forkedFrom.sessionId` = the **immediate parent**. The engine reads these files, rebuilds the fork forest, and shells out to the standard `claude --resume` CLI.

## Install (development)

```bash
claude --plugin-dir /Volumes/PanosT9/Projects/cc-branch-tree
```

## Layout

```
.claude-plugin/plugin.json   plugin manifest
commands/                    /tree, /checkout (markdown skills)
scripts/cc_tree.py           parser + tree builder + resolver (Python 3 stdlib)
scripts/launch.sh            terminal launcher (tmux / iTerm / Terminal)
tests/                       pytest with synthetic fixtures
docs/specs/                  design spec
```

## Requirements

- macOS (launcher); Linux/WSL planned
- Python 3.8+
- Claude Code v2.1.x
