# cc-branch-tree

A Claude Code plugin that visualizes your conversation **fork tree** across all projects and lets you jump to any branch — like `git branch` + `checkout` for Claude Code sessions. No Claude Code internals are modified; it reads the session transcripts and shells out to the standard CLI.

> **Status**: v0.2.0. See [docs/specs](docs/specs/) and [CHANGELOG.md](CHANGELOG.md).

## Commands

| Command | What it does |
|---|---|
| `/tree [10d\|3h\|2w\|30m] [all] [project]` | Render all sessions grouped by project, **most-recent first**, with true parent→child fork nesting. Optional time window (e.g. `10d` = active within 10 days), `all` to also show command-runner sessions, and/or a project-name filter. |
| `/checkout <index \| id-prefix \| name>` | Copy an **in-session `/resume <id>`** to the clipboard (paste into the prompt to switch to that branch in place; works across projects by id). Also prints a `cd … && claude --resume` command for opening it in a new terminal. |
| `/hide <index \| id-prefix \| name> …` | Soft-hide one or more conversations (and their sub-branches) from `/tree`. Reversible — the transcript is never deleted. Then re-renders the tree. |
| `/unhide <id \| name \| all> …` | Restore hidden conversations (cascades to sub-branches). Then re-renders the tree. |
| `/inspect <index \| id-prefix \| name>` | Drill into one session's internal `/rewind` branches — the message-level `parentUuid` divergences — marking the live path vs other paths and hiding trivial single-message edits. |

Each `/tree` row: `[index]  session-id  time  ⏎tree-prefix full-name  ⑂N-branches`. Columns are aligned; the full name is shown untruncated. Command-runner sessions (whose first message is a slash command) are auto-hidden by default — use `/tree all` to show them.

## How it works

Claude Code stores each session as JSONL at `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`. A `/branch` (`/fork`) copies the parent's history into a new session file and stamps inherited entries with `forkedFrom.sessionId` = the **immediate parent**. The engine reads these files, rebuilds the fork forest, recovers real project paths from each entry's `cwd` (the folder name is lossy), and resolves a node to a resume target. Hidden sessions and the last view (time window/filter) are persisted as small sidecars under `${CLAUDE_PLUGIN_DATA}`.

## Install

**Persistent (recommended)** — symlink into the user skills dir so it auto-loads every session as `cc-branch-tree@skills-dir` (no `--plugin-dir`, edits stay live):

```bash
ln -s /Volumes/PanosT9/Projects/cc-branch-tree ~/.claude/skills/cc-branch-tree
```

**Per-session (dev):** `claude --plugin-dir /Volumes/PanosT9/Projects/cc-branch-tree`

Either way, restart the session to pick up changes to command (`.md`) files; `scripts/cc_tree.py` changes take effect on the next command call. Parsed sessions are cached by `(mtime, size)` in `parse_cache.json`, so repeat renders only re-read changed transcripts.

## Layout

```
.claude-plugin/plugin.json   manifest
commands/                    /tree, /checkout, /hide, /unhide (markdown skills, pinned to haiku + low effort)
scripts/cc_tree.py           parser, fork-tree builder, renderer, resolver (Python 3 stdlib, zero deps)
scripts/launch.sh            new-terminal launcher (tmux / iTerm / Terminal)
tests/                       unittest suite + synthetic fixtures
docs/specs, docs/plans       design spec & implementation plan
```

## Requirements

- Python 3.8+ (standard library only)
- macOS for clipboard (`pbcopy`) and new-terminal launch; Linux clipboard via `wl-copy`/`xclip`
- Claude Code v2.1.x
