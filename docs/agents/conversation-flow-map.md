# 对话链路地图

这份文档用于维护 Chat/Coding 从用户发送消息到模型内容返回 UI 的主链路。它不是重构方案，而是后续学习、诊断和小步优化时的共同地图。

## 范围

主路径：

`ChatCodingRoute` 乐观提交 -> FastAPI sessions route -> `session_service` 提交/调度/worker -> `agent.py` 单轮执行 -> `core.llm` invoke/stream -> UI capture -> turn journal/live output -> SSE -> 前端 active-turn layer -> `ConversationView`。

不覆盖：

- Chat room 多人轮次。
- Self-evolution 编排本身；只有它复用 hidden/direct session 时才回到本链路。
- provider adapter 内部细节；这里仅追到共享 `core.llm.invocation` 入口。

## 稳定入口

| 层 | 入口 | 职责 |
| --- | --- | --- |
| 前端提交 | `web/src/routes/ChatCodingRoute.tsx` | 发送 `POST /api/sessions/{sessionId}/messages`，带 `Prefer: respond-async`；先乐观更新 UI，再通过 stream/cache 校准。 |
| API route | `core/web/routes/sessions.py` | 拥有 `/api/sessions/{id}/messages` 和 `/api/sessions/{id}/events`。 |
| 提交 owner | `core/web/services/session_service.py::submit_session_message` | 校验输入，解析附件/引用，开启 turn，写初始 journal，发布首个 snapshot，并调度后台执行。 |
| worker owner | `core/web/services/session_service.py::_run_session_turn` | 解析 runtime/model/context，创建 chat agent，捕获 UI stream，运行 agent turn，并持久化终态结果。 |
| Agent turn | `agent.py::run_single_turn` | 执行一轮 agent thought/action loop，返回结构化 result dict。 |
| LLM 调用 | `agent.py::_invoke_llm` + `core/llm/invocation.py` | 统一经过 streaming/invoke helper，并携带 invocation metadata 与 prompt-cache partition。 |
| 事实源 | `core/chat/turn_journal.py` | append-only turn 事件日志，用于 replay、模型上下文和可见消息投影。 |
| 前端流式层 | `web/src/routes/sessionAssistantDeltaScheduler.ts` 和 `web/src/routes/chatActiveTurnLayer.ts` | 平滑消费 `assistant_delta`，在最终 `session_detail` 到来前维护 live assistant 响应。 |
| 最终渲染 | `web/src/components/conversation/ConversationView.tsx` | 优先渲染 native `codexTranscript`，只在需要时回退旧 timeline/response 投影。 |

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
| 最终 assistant 回复 | `turn_journal.jsonl` 里的 `assistant_message` event | 持久 `SessionDetail.messages`、`codexTranscript`、`timelineItems`、chat candidate capture。 |
| transport 顺序保护 | session ledger sequence 生成的 `ledgerSeq` | 前端 stale-event rejection 与 active-turn settlement。 |
| runtime 调试证据 | `logs/runtime_scenes/**`、`log_info/**`、work-run records | 诊断包；不能替代 journal。 |
| UI cache | React Query cache 与 `activeTurnLayersBySession` | 临时显示状态；必须通过 backend detail/journal 校准。 |

经验规则：`assistant_delta` 是 transport，不是事实源。`codexTranscript`、`timelineItems`、前端 display plan 都是投影。`turn_journal.jsonl` 才是 durable turn record。

## 投影边界

- `session_detail` 是校准 snapshot。它可以是 full/windowed，也可以在运行中包含 live overlay。
- `assistant_delta` 是低延迟流。它携带 text delta、thought delta、feedback events 和 native transcript snapshot。
- `codexTranscript` 是 native display projection。存在且有效时，`ConversationView` 应优先使用它，并抑制重复的 legacy process/response blocks。
- `timelineItems` 是兼容投影。它不应重复 native transcript 已经作为最终答案渲染的 assistant markdown。
- `chatActiveTurnLayer` 是前端 in-flight bridge。最终 `session_detail` settle 同一 `turnId` 后应被清理。

## 当前观察点

- `core/web/services/session_service.py` 是热文件，并且职责混合：submit、scheduler、worker、projection、SSE、diagnostics、persistence 都在同一个文件里。优化前优先补 characterization tests 和窄 helper。
- native transcript/delta 的近期历史在 `docs/superpowers/plans/2026-07-07-codex-native-transcript-chain.md` 和 `.docs/project-memory/lanes/chat-coding-surface.json`。
- 编辑 `session_service.py`、`tests`、`web/src/api/types.ts`、`web/src/routes/ChatCodingRoute.tsx` 或 `web/src/components/conversation/**` 前，先查 active claims 并串行化。
- 最新 `runtime_scenes` 可能只有 Launcher/browser 启动证据，没有真实 conversation events。缺少 conversation runtime evidence 时，应标记为 telemetry gap，而不是当作链路已覆盖。

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

1. 先完成或审阅当前 duplicate-projection fix，再在同一批热文件里启动新代码改动。
2. 已增加只读诊断脚本 `scripts/diagnose_session_turn.py`：输入 `sessionId` 和可选 `turnId`，输出 journal event order、terminal status、live checkpoint state、最近 runtime-scene/log 线索。
3. 已增加离线 runtime-scene probe `scripts/probe_conversation_runtime_scene.py`，把 `session.detail_snapshot.published`、`session.assistant_delta.published`、LLM status、tool events、terminal persistence 串进同一 synthetic evidence package。
4. 有诊断覆盖后，再拆 `session_service.py` 的稳定边界：submit/preflight、turn worker/context assembly、live output/SSE projection、final persistence。`turn_journal.py` API 保持共享边界。
5. 前端优化继续围绕 display contract：`ledgerSeq` 拒绝旧事件、active-turn settlement、native transcript suppression rules、snapshot/delta reconciliation。
