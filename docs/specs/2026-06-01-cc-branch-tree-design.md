# cc-branch-tree — Design Spec

## TL;DR — 当前状态

> **阶段**：设计定稿（2026-06-01），进入实现。
> **目标**：一个 Claude Code 插件，把对话「分支树」总览出来，并能从任意节点一键在新终端窗口恢复（`claude --resume`）。
> **形态**：Python3 stdlib 引擎 + `/tree`（渲染）+ `/checkout`（开窗恢复）；跨全项目聚合；恢复粒度=整会话级。
> **不碰 Claude Code 本体**，只读 transcript + 调用既有 CLI。

---

## 1. 目标与非目标

**目标（MVP）**
- 跨 `~/.claude/projects/*/` 聚合所有会话，按项目分组渲染**分支树**（父子关系正确递归嵌套）。
- 每个节点展示：短 id、标题、消息数、空闲时长、git 分支、fork 关系。
- `/checkout <序号|id前缀|名字>` → 在新终端窗口执行 `cd <cwd> && claude --resume <id>`。

**非目标（MVP 不做，列入路线图）**
- 恢复到会话内**中间某条消息**（CLI 无此入口，仅整会话级）。
- 合并分支 / diff 分支 / 可视化 GUI / MCP 对话式导航 / 自有标签 sidecar。
- 修改或依赖 Claudian 等第三方层。

---

## 2. 已核实事实（实现基石，均经工具实测）

| # | 事实 | 证据 |
|---|---|---|
| F1 | transcript 路径 `~/.claude/projects/<enc(cwd)>/<session-id>.jsonl`，每行一个 JSON 对象 | 目录实测 |
| F2 | 目录名对 cwd 有损编码（非 ASCII→`-`）；**真实路径在每条消息的 `cwd` 字段** | `所有笔记`→`-----`，entry.cwd 实测 |
| F3 | 消息条目含 `uuid / parentUuid / sessionId / cwd / gitBranch / timestamp / isSidechain / message{role,content}`；另有 `custom-title`/`ai-title`/`file-history-snapshot`/`attachment` 等非消息类型 | 类型频次扫描 |
| F4 | `/branch`（v2.1.77 起由 `/fork` 改名，互为别名）= `claude --resume <id> --fork-session`：**复制父会话历史进新 session 文件，保留原 uuid** | web 文档 + 780 跨文件共享 uuid |
| F5 | **`forkedFrom = {sessionId, messageUuid}` 顶层字段；`forkedFrom.sessionId` = 直接父会话**（每次 fork 把继承条目统一重打成「直接来源」的戳，文件内恒定） | `test3.forkedFrom.sessionId = test2`（非根）实测 |
| F6 | 等价的**作者归属法**：`owner[uuid]` = 该 uuid「存在且非继承」的会话；子的直接父 = 子「最后一条继承消息」的 owner。与 F5 在所有实测样本 100% 一致 | test1→test2→test3 + #4 枢纽实测 |
| F7 | 恢复：`claude -r "<id\|name>" ["query"]` 按 id/名字恢复并可带初始 prompt；`--fork-session`、`--session-id`、`-n/--rename` 命名 | CLI reference |
| F8 | 无「直达会话内中间消息」的 CLI 入口（仅 `/rewind` 交互内回溯，原地改写） | CLI reference 无此 flag |
| F9 | 插件机制：`.claude-plugin/plugin.json`（必填 `name`）；`commands/*.md` 即 skill；`` !`cmd` `` 把 stdout 注入；`$ARGUMENTS/$0`；`disable-model-invocation`、`allowed-tools`；`${CLAUDE_PLUGIN_ROOT}/${CLAUDE_PLUGIN_DATA}` | plugins/skills reference |

**反面教训**：不要用朴素 uuid「集合包含」判父——对**同深度兄弟**会假阳性（小兄弟的 uuid 集合可完整包含另一兄弟的继承前缀）。详见对话中 `#start ⊂ $4 skill` 误报。

---

## 3. 架构

```
cc-branch-tree/
├── .claude-plugin/plugin.json   # 清单（name + commands 指向）
├── commands/
│   ├── tree.md                  # /tree   渲染分支树（确定性，!`cmd` 注入）
│   └── checkout.md              # /checkout <选择子>  开窗恢复（disable-model-invocation）
├── scripts/
│   ├── cc_tree.py               # 唯一引擎：scan/parse/build/render/resolve（Python3 stdlib）
│   └── launch.sh                # 终端启动器：tmux → iTerm → Terminal → 兜底打印
└── tests/                       # pytest（合成 fixture，不含隐私数据）
```

- **单一引擎** `cc_tree.py`，命令文件只负责「`!`调用 + 展示」。
- 子命令：`render`（输出文本树 + 写有序节点缓存）、`resume <selector> [--launch]`（解析选择子→开窗或打印命令）。

---

## 4. 数据模型与解析

每会话提取一条 `Session` 记录（流式逐行，跳过 `message.content` 重负载，仅首条 user 取预览）：

| 字段 | 来源 | 用途 |
|---|---|---|
| `sid` | 文件名 | 节点主键 / `claude --resume` 入参 |
| `cwd` | 首个带 cwd 的条目 | 还原真实项目名 + resume 的 `cd` 目标（F2） |
| `git_branch` | 首条 | 展示 |
| `parent` | `forkedFrom.sessionId`（F5），缺失时用作者归属（F6） | 建边 |
| `fork_point_msgs` | 继承的消息数（在父时间线的位置） | 展示「forked after N msgs」 |
| `label` | `custom-title` → `ai-title` → 首条 user 预览 | 节点标题 |
| `created/last` | 首/尾 timestamp | 排序 / 空闲时长 |
| `msgs` | `user/assistant` 且 `isSidechain=false` 计数 | 规模 |

---

## 5. 建树算法（核心）

```
# 1) 解析所有会话 -> {sid: Session}，并构建全局 owner 索引（用于 F6 兜底/校验）
owner[uuid] = sid  for each uuid in (session.all_uuids - session.inherited_uuids)

# 2) 定直接父（F5 主 + F6 兜底/校验）
def immediate_parent(s):
    p = s.forkedFrom_sessionId            # 主：直接父（文件内恒定）
    if p is None and s.inherited_in_order:   # 兜底：forkedFrom 缺失（老 transcript）
        p = owner.get(s.inherited_in_order[-1])
    return p if p in sessions else None    # 父文件不存在 -> 视为根（标注 orphan）

# 3) 建森林：edge child -> immediate_parent；无父者为根
# 4) 按项目(cwd)分组，组内按 created 排序，递归渲染
```

**禁用**：朴素 `child.uuids ⊆ candidate.uuids` 判父（同深度兄弟假阳性）。
**校验**（测试用）：F5 与 F6 结果应一致；不一致则记日志、以 F6（作者归属）为准并标注。

---

## 6. 渲染（`/tree`）

- 按 `📁 <真实cwd>` 分组；组内根会话按 `created` 升序；递归缩进展示父子。
- 行格式：`[idx] <sid8> · <label> · <msgs>msg · <idle> · <git>  (↳forked after N msgs)`。
- `[idx]` 为顺序序号，渲染时把有序 `(idx→sid,cwd)` 写入 `${CLAUDE_PLUGIN_DATA}/last_tree.json` 供 `/checkout` 用。
- 可选过滤：`/tree <项目名子串>` 只渲染匹配项目。

---

## 7. 恢复 / 开窗（`/checkout`）

- 选择子解析顺序：纯数字→`last_tree.json` 序号；否则 sid 前缀；否则 label 子串。
- 解析得 `(sid, cwd)` → `launch.sh` 在**新窗口**执行 `cd "<cwd>" && claude --resume <sid>`。
  - `$TMUX` 非空 → `tmux new-window`
  - `TERM_PROGRAM=iTerm.app` → osascript 开 iTerm 窗口
  - 否则 → osascript 开 Terminal.app；失败则打印命令供手动复制
- `cd` 到真实 cwd 确保跨项目定位正确（F2/F7）。

---

## 8. 缓存与性能

- 跨全项目可能上百会话、含 20MB+ 文件。增量缓存 `${CLAUDE_PLUGIN_DATA}/index.json`：记录每文件 `(mtime, Session 记录)`，仅重解析 mtime 变化者。
- owner 索引仅在需要 F6 兜底时构建；MVP 默认走 F5（无需全量 owner），保持单遍轻量。

---

## 9. 限制与边界（明确告知用户）

1. 恢复=整会话级；无法直达会话内中间消息（F8）。
2. 恢复在**原生终端**新窗口，独立于 Obsidian/Claudian。
3. `launch.sh` 当前 macOS；Linux/WSL 待补（路线图）。
4. 父会话文件被删 → 该支显示为根并标 `(parent missing)`。
5. 会话内 `parentUuid` 扇出（`/rewind` 歧路）为 v1.1 下钻视图，MVP 不入恢复。

---

## 10. MVP 范围与路线图

- **v0.1（本期）**：`/tree` 跨项目分组分支树 + `/checkout` 开窗恢复；F5 主 + F6 兜底建树；pytest 覆盖。
- **v1.1**：mtime 增量缓存；会话内 `parentUuid` 分叉下钻；Linux/WSL 启动器；`/tree <过滤>`。
- **v1.2**：搜索；自有标签/备注 sidecar；fork 深度「级联」视图。
- **v2**：MCP server（list_branches/get_tree/resume 工具，对话式导航）；Mermaid/HTML 可视化；发布 marketplace。

---

## 11. 测试策略

- 合成 fixture（**不含隐私**），覆盖：单根、单层 fork、三级嵌套链、同深度兄弟（防包含法假阳性回归）、forkedFrom 缺失（走 F6）、isSidechain 过滤、有损 cwd、title 优先级、orphan 父。
- 断言：`immediate_parent`、森林结构、渲染序号映射、选择子解析。
- 目标覆盖率 ≥ 80%（用户规则）。

---

← 返回 [README](../../README.md)
