# cc-branch-tree MVP Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax. TDD with stdlib `unittest`. Frequent commits.

**Goal:** Ship a Claude Code plugin that renders the cross-project conversation fork tree (`/tree`) and resumes any node in a new terminal window (`/checkout`).

**Architecture:** One zero-dependency Python engine (`scripts/cc_tree.py`) parses `~/.claude/projects/*/*.jsonl`, builds the fork forest via `forkedFrom.sessionId` (immediate parent, F5) with authorship cross-check (F6), renders text + writes an index cache, and resolves a node selector to `(sid, cwd)`. Two markdown command-skills call it; `launch.sh` opens the resume in a new window.

**Tech Stack:** Python 3.8+ (stdlib only), bash + osascript/tmux, Claude Code plugin (commands/`!`-injection).

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/cc_tree.py` | parse → Session; owner index; `immediate_parent`; `build_forest`; `render`+index cache; `resolve`; CLI `render`/`resume` |
| `scripts/launch.sh` | open `cd <cwd> && claude --resume <sid>` in tmux/iTerm/Terminal |
| `.claude-plugin/plugin.json` | manifest (`name`, `commands`) |
| `commands/tree.md` | `/tree [filter]` — `!`-inject `cc_tree.py render` |
| `commands/checkout.md` | `/checkout <sel>` — `!`-inject `cc_tree.py resume "$0" --launch`; `disable-model-invocation` |
| `tests/fixtures/projects/**` | synthetic JSONL (no private data) |
| `tests/test_engine.py` | unittest suite |

**Testability:** engine reads `CC_PROJECTS_DIR` (fallback `~/.claude/projects`) and `CLAUDE_PLUGIN_DATA` (fallback `~/.cache/cc-branch-tree`) so tests point at fixtures + a temp data dir.

---

## Fixtures (the verified shapes, synthetic)

`proj1/root.jsonl` — root, msgs a1,a2, `custom-title`=Root Session.
`proj1/child.jsonl` — `forkedFrom.sessionId=root` on a1,a2; own b1; `ai-title`=Child Branch.
`proj1/grand.jsonl` — `forkedFrom.sessionId=child` on a1,a2,b1 (re-stamped to immediate parent per F5); own c1.
`proj1/sib.jsonl` — `forkedFrom.sessionId=root` on a1,a2 (same depth as child); own d1. **Must NOT nest under child/grand** (containment-trap regression).
`proj2/solo.jsonl` — independent root, different project.
`proj1/orphan.jsonl` — `forkedFrom.sessionId=ghost` (missing file); own e1 → treated as root.

---

## Tasks

### Task 1 — Parsing
**Files:** Create `scripts/cc_tree.py`, `tests/test_engine.py`, fixtures.
- [ ] Write fixtures listed above.
- [ ] Test: `parse_transcript(root)` → `label=="Root Session"`, `msgs==2`, `forked_from_sid is None`, `cwd=="/work/proj1"`, `git_branch=="main"`.
- [ ] Test: `parse_transcript(child)` → `forked_from_sid=="root"`, `{a1,a2}⊆inherited_uuids`, `msgs==3`, `label=="Child Branch"`.
- [ ] Implement `Session`, `parse_transcript`, helpers `_title_text`, `_msg_preview`. Run unittest → PASS. Commit.

### Task 2 — Forest + parentage (F5 primary, F6 cross-check, no containment)
- [ ] Test: `build_forest` → `children[root]=={child,sib}`, `children[child]=={grand}`, `roots` contains `root, solo, orphan`.
- [ ] Test (containment trap): `immediate_parent(sib)=="root"` not `child`, even though `sib.inherited ⊆ grand.all_uuids`.
- [ ] Test (authorship invariant F6): for every session with `forked_from_sid`, `owner[last inherited uuid] == forked_from_sid`.
- [ ] Test (orphan): `immediate_parent(orphan) is None` (ghost parent missing).
- [ ] Implement `build_owner_index`, `immediate_parent` (F5; F6 fallback only when `forked_from_sid is None`), `build_forest`, `fork_depth`. Run → PASS. Commit.

### Task 3 — Render + index cache + resolve
- [ ] Test: `render` groups by project, returns `(text, ordered)`; indices are stable depth-first; `grand` is indented under `child` under `root`.
- [ ] Test: `write_last_tree`/`resolve("0")` → root; `resolve("chi")` prefix and `resolve("Child")` label → child sid; bad selector → None.
- [ ] Implement `_idle`, `render`, `_emit`, `write_last_tree`, `load_last_tree`, `resolve`. Run → PASS. Commit.

### Task 4 — CLI + launcher
- [ ] Implement `cmd_render(filter)`, `cmd_resume(args)`, `main`; `resume` without `--launch` prints `cd "<cwd>" && claude --resume <sid>`.
- [ ] Test: `main(["","resume","0"])` (no --launch) prints the resume command for root (capture stdout).
- [ ] Write `scripts/launch.sh` (tmux → iTerm → Terminal → print fallback); `chmod +x`. Commit.

### Task 5 — Plugin wiring
- [ ] Write `.claude-plugin/plugin.json`, `commands/tree.md`, `commands/checkout.md`.
- [ ] Manual: `claude --plugin-dir <repo>` then `/tree`; smoke-test `cc_tree.py render` against real `~/.claude/projects` (expect the live `test1→test2→test3` chain nested). Commit.

---

## Self-review (spec coverage)
Covers spec §4 (parse), §5 (algorithm incl. no-containment + F6), §6 (render+index), §7 (resolve+launch), §11 (test matrix incl. containment-trap, orphan, sidechain via msgs filter). Caching (§8) deferred to v1.1 per spec. No placeholders; types (`Session`, `forked_from_sid`, `inherited_in_order`) consistent across tasks.
