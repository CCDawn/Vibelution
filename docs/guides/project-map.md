# 项目地图（速查导航）

**读者：项目作者与 coding Agent。**
**定位：三条主线的压缩速查 + 需求→文件索引 + 排障口诀。**
本页只导航、不发明规则；规则冲突时以根 `AGENTS.md` 与 `docs/standards/` 为准。

---

## 0. 三条主线（先记住这三句话）

1. **消息旅程**：输入 → HTTP 入口 → 接单写账本 → 排队 → worker/agent 循环（模型 ⇄ 工具）→ SSE 直播 → 落账本终态。
2. **Agent 组装**：档案（agents.json）+ 身份（三核心 + 角色模板，会话快照冻结）+ 能力（工具授权 / 记忆 / 委派）→ 每次会话组装成运行时实例。
3. **数据与记忆**：账本是唯一 transcript 权威（append-only JSONL）；SQLite 只存目录与控制面；记忆分五种各住各家；一切路径由 `vibelution_storage.py` 解析。

---

## 1. 数据布局

| 位置 | 角色 |
| --- | --- |
| `%LOCALAPPDATA%\Vibelution\projects\<projectId>\memory\` | 项目记忆（跨实例共享）：agent-registry、lanes、inbox |
| `...\projects\<projectId>\instances\<instanceId>\data\workspace\` | 实例工作区（每个 checkout 一个；instanceId = checkout 路径哈希） |
| `...\data\workspace\sessions\<token>\turn_journal.jsonl` | 会话账本（唯一 transcript；旁车 `.watermark` / `.lock`） |
| `...\data\workspace\chat\conversations.sqlite3` | SQLite 控制面（目录 / 控制信息，非 transcript） |
| `...\data\workspace\agents\{agentId}\events\episodic_events.jsonl` | 个人记忆 |
| 仓库内 `workspace\` | **迁移前旧位置**（`migrated: true` 后只读遗留；见到 `pre-sqlite.bak` 等文件属搬家痕迹） |

解析权威：[`vibelution_storage.py`](../../vibelution_storage.py)（项目身份 `.vibelution/project.json`；迁移标记 fail-closed）。
查本机实例路径：调用 `resolve_project_storage_paths(project_root).as_dict()`。

---

## 2. 一条消息的旅程（6 站）

| # | 站 | 关键位置 |
| --- | --- | --- |
| 1 | 前端收集提交 | `web/src/components/conversation/ConversationView.tsx` → `routes/chat/useChatComposerSubmit.ts` → `api/chat.ts::submitSessionMessage` |
| 2 | HTTP 入口 | `core/web/routes/sessions.py::session_submit_message`（202 accepted） |
| 3 | 接单登记 | `core/web/services/session/submit.py`（写 `turn_started` + `user_message`；发首条 live 状态） |
| 4 | 排单 | `session_turn_scheduler.py`（同会话串行、按 Agent 限并发） |
| 5 | 做菜 | `session/worker.py` → `core/orchestration/turn_runner.py` → `agent.py::_run_orchestrated_turn`（模型 ⇄ 工具循环；`turn_outcome.py` 决定停机） |
| 6 | 上菜记账 | `session/persist.py`（`assistant_message` + 终态事件）；直播走 `session/publish.py`（SSE） |

要点：账本是真相，SSE 只是直播；一轮结束必须落终态事件（`turn_completed` / `turn_failed` / `turn_interrupted`）。

---

## 3. Agent 组装（三层 + 上岗）

| 层 | 内容 | 位置 |
| --- | --- | --- |
| 档案 | Agent 记录 / ToolPolicy / MemoryPolicy（唯一可写权威） | 实例 workspace `agents/agents.json`（SQLite `agents` 表是只读投影） |
| 身份 | 三核心 `COMMON → SOUL → AGENTS`（fail-closed）+ 角色模板 → 会话快照冻结（稳定前缀利于 prompt cache） | `core/prompt_manager/core_prompt_sources.py`、`core/web/services/prompt_template_service.py` |
| 能力 | 工具：候选 → 授权（deny-first）→ 物化；记忆注入；委派多层闸门（默认禁） | `tools/Key_Tools.py`、`core/authorization/`、`core/orchestration/context_engine.py` |
| 上岗 | `get_agent` → 提示词快照 → `resolve_agent_llm`（解析不出即失败关闭）→ `AgentRuntime.__init__` | `session/worker.py`、`core/llm/agent_runtime.py`、`agent.py` |

要点：模型槽位六个（dialogue / mentalModel / summary / subagentPlanning / subagentExecution / vision）；禁止默认模型与默认窗口兜底。

---

## 4. 需求 → 文件 总表

| 需求 | 先打开 |
| --- | --- |
| 改输入框 / 快捷键 | `web/src/components/conversation/ConversationView.tsx`、`composerShortcuts.ts` |
| 改提交请求内容 | `routes/chat/useChatComposerSubmit.ts` → `api/chat.ts` |
| 改流式渲染 | `routes/sessionAssistantDeltaScheduler.ts`、`chatActiveTurnLayer.ts` |
| 改后端接收 / 校验 | `core/web/routes/sessions.py` |
| 改接单逻辑（附件 / 引用 / 去重） | `session/submit.py` |
| 改排队 / 并发 | `session_turn_scheduler.py` |
| 改单轮循环行为 | `agent.py::_run_orchestrated_turn`（热文件，窄改动） |
| 改系统提示词 / 章节 | `core/prompt_manager/`（机制地图见其 README） |
| 改 Agent 角色 / 职责 / 模型 / 工具 | 实例 workspace `agents/agents.json`（工作台配置面板） |
| 改工具授权规则 | `core/authorization/`（`tool_policy_evaluator.py` deny-first） |
| 查消息 / 历史问题 | 账本 `core/chat/turn_journal.py`（先读数据，再查代码） |
| 改会话列表 / 预览 / 血缘 | `core/chat/conversation_store/` + `session/directory_bridge.py` |
| 改记忆读写 | `agent_directory/episodic_memory.py`（个人）、`team_knowledge/`（团队） |
| 硬删除记忆 | 唯一入口 `memory_cleanup_service.py`（preview + 确认短语 `硬删除记忆`） |
| 改数据存放位置 | `vibelution_storage.py`（涉迁移，慎动） |
| 清理 / 归档数据 | `scripts/prune_*.py` / `cleanup_*.py` 系列 |
| 接入新模型厂商 | `core/llm/`（protocol_resolver + adapters） |
| 前端界面 / 组件 | VUI：`web/src/components/vui/README.md`（路由只 import `components/vui`） |

---

## 5. 排障口诀

- **消息 / 历史不对** → 先读该会话 `turn_journal.jsonl`；编辑 / 重生成不删旧行（`branch_rebase` + 活跃路径折叠），别把旧分支当 bug。
- **会话列表 / 排序不对** → 读 SQLite 目录（`conversation_store`）与 `directory_bridge` 的同步日志。
- **状态不刷新 / 卡在一半** → live_output 与 SSE（`session/publish.py`）；查终态事件是否落账（`POST_TERMINAL` 保护会拒绝终态后的模型可见写入）。
- **Agent 行为不对** → 先看三核心与角色模板；会话快照已冻结，改模板后需要新会话才生效。
- **模型 / 工具报错** → 按失败关闭清单排查：模型解析、上下文窗口探测、授权上下文缺失、硬删除确认。
- **数据在哪** → 跑 `resolve_project_storage_paths`（不要靠猜路径）。

---

## 6. 已知欠账追踪

| 项 | 状态 |
| --- | --- |
| 账本无物理归档（长会话文件只增，逻辑压缩只影响模型视野） | 已体检（2026-09）：只读工具 `scripts/report_session_ledgers.py` + 约束文档；机制化留待数据量/运维需求逼近 |
| 仓库内遗留 `workspace\` 旧文件未清（迁移已完成） | 已完成（2026-09-12）：清理 142 文件 / 36.3MB |
| "config revision" 两处同名（SQLite 表 vs JSONL 事件） | 已澄清（2026-09）：两侧 docstring 互指，compiled snapshot vs 发布事件 |
| 前端 `act` 测试失败（根因：外部 NODE_ENV=production 使 react 走生产构建，测试环境未固定） | 已修（2026-09）：vitest 配置双层钉 NODE_ENV=test；全量 731 文件 / 5242 测试在污染环境下全绿；并修复 2 个阻塞全量的既有 design 契约红灯 |
| 会话过程状态过细碎（6 条工程阶段） | 已收口：粗粒度 `working / thinking / queued` + 700ms 防抖 |
| 提示词链路 5 个僵尸机制 + 能力过滤双源 | 已清理：单一权威（capability_requirements + resolver） |
| `prompt_manager/README.md` 失实 | 已修（含机制地图） |

---

## 7. 权威与相关

- 权威顺序：根 `AGENTS.md` → `docs/standards/` → ADR / 模块 README → `docs/guides/`（本目录，路由）。
- 相关：[conversation-flow-map](../agents/conversation-flow-map.md)（对话链路图） · [agent-log-routing](agent-log-routing.md)（日志入口） · [tests/README](../../tests/README.md) · [web services 全量](../../core/web/services/README.md) · [prompt_manager 机制地图](../../core/prompt_manager/README.md)
