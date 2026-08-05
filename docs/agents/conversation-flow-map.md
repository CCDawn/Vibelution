# 对话链路地图

这份文档用于维护 Chat/Coding 从用户发送消息到模型内容返回 UI 的主链路。它不是重构方案，而是后续学习、诊断和小步优化时的共同地图。

## 范围

主路径：

`ChatCodingRoute` 乐观提交 -> FastAPI sessions route -> `session_service` 提交/调度/worker（实现 claim 见 `core/web/services/session/*`） -> `agent.py` 单轮执行 -> `core.llm` invoke/stream -> UI capture -> turn journal/live output -> SSE -> 前端 active-turn layer -> `ConversationView`。

结构拆分历史说明（非现行规范）：`docs/archive/plans/2026-06-07/2026-07-21-backend-structure-p0-completion.md`。Team 工作流产品面 claim 见 `core/web/services/team_workflow/README.md`（routes 经 `team_workflows/` 包 + `team_workflow_orchestration_service` facade）。

不覆盖：

- Chat room 多人轮次。
- Self-evolution 编排本身；只有它复用 hidden/direct session 时才回到本链路。
- provider adapter 内部细节；这里仅追到共享 `core.llm.invocation` 入口。

## 稳定入口

| 层 | 入口 | 职责 |
| --- | --- | --- |
| 前端提交 | `web/src/routes/ChatCodingRoute.tsx` | 发送 `POST /api/sessions/{sessionId}/messages`，带 `Prefer: respond-async`；先乐观更新 UI，再通过 stream/cache 校准。 |
| API route | `core/web/routes/sessions.py` | 拥有 `/api/sessions/{id}/messages` 和 `/api/sessions/{id}/events`。 |
| 提交 owner | `core/web/services/session/submit.py::submit_session_message`（facade re-export：`session_service`；见 `session/README.md`） | 校验输入，解析附件/引用，开启 turn，写初始 journal，发布首个 snapshot，并调度后台执行。 |
| 调度 owner | `core/web/services/session/schedule.py::_schedule_session_turn`（facade re-export） | 会话/Agent 并发队列、executor 提交与释放。 |
| worker owner | `core/web/services/session/worker.py::_run_session_turn`（facade re-export） | 解析 runtime/model/context，创建 chat agent，捕获 UI stream，运行 agent turn。 |
| capture owner | `core/web/services/session/stream_capture.py::_capture_session_ui_stream`（facade re-export） | UI thought/response/tool 批处理写入 live_output 与 journal 片段。 |
| persist owner | `core/web/services/session/persist.py::_persist_session_turn_result`（facade re-export） | 持久化最终 assistant / turn_*，清理 live output，发布终态 detail。 |
| Agent turn | `agent.py::run_single_turn` | 执行一轮 agent thought/action loop，返回结构化 result dict。 |
| LLM 调用 | `agent.py::_invoke_llm` + `core/llm/invocation.py` | 统一经过 streaming/invoke helper，并携带 invocation metadata 与 prompt-cache partition。 |
| 事实源 | `core/chat/turn_journal.py` | append-only turn 事件日志，用于 replay、模型上下文和可见消息投影。 |
| 前端流式层 | `web/src/routes/sessionAssistantDeltaScheduler.ts` 和 `web/src/routes/chatActiveTurnLayer.ts` | 平滑消费 `assistant_delta`，在最终 `session_detail` 到来前维护 live assistant 响应。 |
| 最终渲染 | `web/src/components/conversation/ConversationView.tsx` | 主路径 `package_cells`（`turnItems → codexTranscript.cells`）；无包时 `legacy` 走 content/timeline。 |

## 单轮时序

1. 前端调用 `POST /api/sessions/{sessionId}/messages`，请求头包含 `Prefer: respond-async`。
2. `sessions.py` 将异步请求路由到 `submit_session_message_lightweight`，它再委托给 `submit_session_message`。
3. `submit_session_message` 解析 content、attachments、references、active task、skill slash command 和 leases；创建 `SessionTurnControl`，标记 session running，向 turn journal 写入 `turn_started` 与 `user_message`，设置 waiting live output，发布初始 `session_detail`，然后调度后台 context。
4. `_schedule_session_turn` 把 context 交给 session scheduler/executor。排队和出队状态也会发布 `session_detail`。
5. `_run_session_turn` 准备 workspace，同步 LLM key 环境，解析 Agent 模型槽位，绑定 prompt-cache partition，构建 Agent context packet，从 `turn_journal` 组装历史，记录 `turn_context`，并创建 runtime chat agent。
6. `_capture_session_ui_stream` 包装 UI hooks 和 event-bus callbacks：`stream_response`、`stream_thought`、mental state、tool start/result/error、LLM status。
7. `_run_session_continuation_loop` 调用 `run_existing_agent_single_turn`，最终进入 `SelfEvolvingAgent.run_single_turn`。
8. `agent.py::_invoke_llm` 能 stream 时经过 `core.llm.invocation.stream_llm`，否则经过 `invoke_llm`。stream chunk 会推到 `ui.stream_response` 与 `ui.stream_thought`。
9. UI capture 层批处理文本，向 `turn_journal` 写入 `assistant_delta_committed`、`tool_call_started`、`tool_result`，更新 `SessionLiveOutputState`，并发布 `assistant_delta` SSE。
10. `_persist_session_turn_result` 格式化最终可见回复，持久化 `assistant_message` 和 `turn_completed` / `turn_failed` / `turn_interrupted`，记录 work-run/runtime 证据，清理 live output，并发布最终 `session_detail`。
11. `ChatCodingRoute` 消费 `session_initial`、`assistant_delta` 和节流后的 `session_detail`。delta 更新 active-turn layer；最终 detail 如果包含同一 `turnId` 的持久 assistant message，就清掉 live overlay。

## 事实源

| 事实 | canonical source | 派生面 |
| --- | --- | --- |
| session 索引/状态壳 | `workspace/chat/chat_state.json`，通过 `session_service` 写入 | session list/detail summary、active phase、last error、active task。 |
| turn transcript/replay 事实 | `turn_journal.jsonl`，通过 `core/chat/turn_journal.py` | model-visible messages、`SessionDetail.messages`、native transcript/timeline 投影。 |
| 运行中 assistant text/thought/tools | `SessionLiveOutputState` 和可选 live-output checkpoint | `assistant_delta` SSE、live overlay message、active-turn layer。 |
| 最终 assistant 回复 | `turn_journal.jsonl` 里的 `assistant_item_committed` / final answer | 持久 `SessionDetail.messages.turnItems`；`content` 为兼容镜像；`codexTranscript` 由 items 单向派生。 |
| transport 顺序保护 | session ledger sequence 生成的 `ledgerSeq` | 前端 stale-event rejection 与 active-turn settlement。 |
| runtime 调试证据 | `logs/runtime_scenes/**`、`log_info/**`、work-run records | 诊断包；不能替代 journal。 |
| UI cache | React Query cache 与 `activeTurnLayersBySession` | 临时显示状态；必须通过 backend detail/journal 校准。 |

经验规则：

- `turn_journal.jsonl` 是 durable turn record。
- **`SessionTurnItem[]`（`message.turnItems`）是 UI 主包 / 单一投影源。**
- `assistant_delta` 是 transport，不是事实源；流式时按 item 身份更新 active-turn 草稿包。
- `codexTranscript` 是 cells 渲染适配层，由 `turnItems` 单向派生，不得成为第二写入者。
- `content` / `timelineItems` 是**故意保留的兼容面**，不是第二写入者：
  - **新/正常 settle**：后端投影尽量产出 `turnItems`（含 content→`final_answer` 边界合成），前端走 `package_cells`。
  - **无 `turnItems` 的旧会话 / 缓存快照**：前端 **故意** 走 `legacy`（`content` + `timelineItems`），不在客户端合成包，以免破坏历史折叠 UX。
  - 有包时 `content`/`timeline` 不得与 package 抢 final 所有权（答案行由 cells 拥有）。
- `assistantDisplayPlan.renderMode`：`package_cells`（主路径）/ `native_transcript`（有 native cells 但无 package 时的过渡）/ `legacy`（无包：content/timeline）。

## 投影边界

- `session_detail` 是校准 snapshot（full/windowed）。window 可瘦诊断字段，但 **final_answer 全文与 turnItems 语义不可丢**。
- `assistant_delta` 携带 text delta、feedback、**完整 turnItems 快照**与可选 transcript；active-turn 在存在 turnItems 时只认该包。
- `session_live_overlay`（detail 重连/校准桥）也必须挂 **同一 turnItems 包**；answer cells 由包派生，不得只剩 content/timeline 第二轨。
- journal 已有 tool/process items 但尚无 final_answer 时，后端 projection 用 live content **桥接 provisional final_answer** 到同一包（不覆盖已 committed 终稿）。
- `ConversationView` 主路径：`turnItems → codexTranscript.cells → package_cells 单轨渲染`。response 区块与 timeline 答案行仅 `legacy` 模式使用。
- `timelineItems` 在 package 模式下剥离 `assistant_text`，只保留过程行（若 cells 未覆盖 process）。
- `chatActiveTurnLayer` 是 in-flight bridge；`session_detail` settle 同一 `turnId` 且已 committed final 后必须清理。同 turn 的 live overlay 在 projection 中并入 active-turn / committed，不双行绘制。
- **Legacy 冻结策略（故意保留）**：
  1. 无 `turnItems` 的旧会话仍走 **content / timeline**——这是兼容路径，不是遗漏删除。
  2. 新/正常 settle 的 detail、window 与 live overlay 必须带 `turnItems`（后端 fallback：content→`final_answer`）。
  3. 前端无包时 `renderMode=legacy`，仅覆盖过程-only、status placeholder、或尚未升级的缓存快照。
  4. **禁止**客户端随意合成 `turnItems` 包；合成只允许在后端 projection 边界。
  5. 确认无流量后再考虑删除纯 process 的 legacy 死分支（见优化队列）。

## 当前观察点

- 编辑 `session/projection.py`、`chatTurnProtocol.ts`、`assistantDisplayPlan.ts`、`ConversationView.tsx` 或 chat active-turn 前，先查 active claims 并串行化。
- native transcript / delta 历史材料在 `docs/archive/superpowers/plans/2026-07-07-codex-native-transcript-chain.md`；**现行权威以本文件 + SessionTurnItem 包为准**，历史计划不得覆盖。
- 最新 `runtime_scenes` 可能只有 Launcher/browser 启动证据；缺 conversation runtime evidence 时标 telemetry gap，不当作链路已覆盖。

## 只读诊断命令

用 `sessionId` 和可选 `turnId` 串起 journal、live checkpoint 和 runtime-scene 线索：

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_session_turn.py --project-root . --session-id <sessionId> --turn-id <turnId>
```

报告里的 `journal` 显示事件顺序、最新 sequence、终态事件和 JSONL 解码问题；`liveOutput` 显示运行中 checkpoint 的 stage、turn 匹配和内容长度；`runtimeEvidence.matches` 显示匹配到的 runtime-scene JSONL 事件码、路径和裁剪字段。这个命令只读文件，不 import `session_service.py`，适合在热区重构或 active claim 存在时先做链路定位。

需要一个不调用真实模型、不启动 Launcher 的证据链样本时，可以生成离线 runtime-scene probe：

```powershell
.\.venv\Scripts\python.exe scripts\probe_conversation_runtime_scene.py --project-root .
```

它会写入一个 synthetic package：`logs/runtime_scenes/probe_conversation_runtime_scene/events/conversation.jsonl`，并创建同一 `sessionId/turnId` 的 journal/live checkpoint，再调用诊断命令读回。probe 中真实已有的事件码保留原名，例如 `session.detail_snapshot.published` 和 `session.assistant_delta.published`；尚未作为生产 runtime 事件独立落盘的 LLM/tool/terminal 步骤使用 `conversation_probe.*` 前缀，避免把样本当成生产日志。

## 优化队列

1. ~~SessionTurnItem 包主路径（A/B/C）~~：后端 detail/window 产出 turnItems；流式 active-turn 认包；ConversationView `package_cells`；legacy 冻结为无包 fallback。
2. 只读诊断：`scripts/diagnose_session_turn.py`、`scripts/probe_conversation_runtime_scene.py`（已有）。
3. 后续可选：进一步收缩 `session_service` facade 边界；确认无流量后删除纯 process 的 legacy 死分支。
