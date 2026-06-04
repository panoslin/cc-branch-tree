# Changelog

## Unreleased (v1.1 work)

- **`/inspect <selector>`**: drill into one session's internal `/rewind` branches (message-level `parentUuid` tree). The continued path is detected by most-recent subtree activity (robust to compaction); abandoned branches must contain human input — pure retry/error fragments and tiny edits are filtered and counted separately. Previews prefer the user's own words; branches get `[ref]` labels.
- **`/extract <ref>`**: closes the loop — exports an abandoned branch (from the last `/inspect`) as markdown with full message text, printed and copied to the clipboard for reuse in the current conversation.
- **Incremental parse cache**: `load_sessions()` skips transcripts unchanged since last run via an `(mtime, size)` cache (`parse_cache.json`); warm renders ~16× faster. `CC_NO_CACHE=1` disables.
- **Persistent install**: documented skills-dir symlink (`~/.claude/skills/cc-branch-tree` → repo) so the plugin loads every session without `--plugin-dir`.
- 35 `unittest` cases.

## v0.2.0 — 2026-06-03

Cross-project navigation, filtering, soft-delete, and clipboard-based in-session resume.

- **`/tree`**: cross-project aggregation grouped by real project path; **recency sort** (most-recent first); **time-window filter** (`10d`/`3h`/`2w`/`30m`); **full session names** (no truncation) with aligned `index / id / time` columns and `⑂N` branch counts; proper `├─/└─/│` connectors.
- **Fork tree**: built from `forkedFrom.sessionId` (immediate parent); correct multi-level nesting; never uses naive uuid-containment (which false-positives on same-depth siblings).
- **`/checkout`**: copies an in-session `/resume <id>` to the clipboard (paste to switch branches in place, across projects); also prints a `cd … && claude --resume` new-terminal command. `pbcopy`/`wl-copy`/`xclip`.
- **`/hide` / `/unhide`**: reversible soft-delete (sidecar `hidden.json`, transcript untouched); **cascades to sub-branches**; both re-render the tree afterward, reusing the last view (filter/window).
- **Auto-hide command-runner sessions** (first message is a slash command) by default; `/tree all` shows them.
- Labels: latest custom/ai title wins; command-runner sessions labeled by command name; caveat/wrapper text stripped from previews.
- Display commands pinned to `model: haiku` + `effort: low` for fast, verbatim output.
- 31 `unittest` cases; synthetic fixtures (no private data).

## v0.1.0 — 2026-06-01

Initial MVP: `/tree` (fork tree) + `/checkout` (resume), Python stdlib engine, design spec + plan.
