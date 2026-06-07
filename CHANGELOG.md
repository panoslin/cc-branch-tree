# Changelog

## Unreleased (v1.1 work)

- **Fork labels use the fork's own first message**: a forked session without a title is now labeled by the first message *typed in it* (entries without a `forkedFrom` stamp), not the inherited first message — forks of the same parent no longer all show identical labels. Cache schema versioned (`_v`) so stale cached labels are discarded.
- **Incremental parse cache**: `load_sessions()` skips transcripts unchanged since last run via an `(mtime, size)` cache (`parse_cache.json`); warm renders ~16× faster. `CC_NO_CACHE=1` disables.
- **Persistent install**: documented skills-dir symlink (`~/.claude/skills/cc-branch-tree` → repo) so the plugin loads every session without `--plugin-dir`.
- `/inspect` + `/extract` (in-session `/rewind` drill-down and branch export) were built and then **removed** as not pulling their weight; the engine is back to tree/checkout/hide/unhide only.
- 33 `unittest` cases.

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
