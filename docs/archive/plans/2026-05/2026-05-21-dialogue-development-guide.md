# 对话线开发与维护指南

> 负责人视角：本文档由 Vibelution 的对话线负责人维护。它描述对话线的职责边界、当前已落地机制、和后续可执行计划。本文档不是监督进化线或无监督进化线的决策规则。

## 1. 定位

对话线负责把 Vibelution 做成一个稳定、连续、可观察、可恢复、可沉淀经验的 agent 对话工作台。

它的核心目标不是多一个聊天页面，而是让用户能在同一个 `ChatSession` 里持续给任务、看 agent 的思考和工具调用、动态开关心智模型、停止/继续运行、恢复历史上下文，并把有价值的对话片段以受控方式交给 review case 流程。

结合 Agent Harness 论文综述，对话线持续吸收三类机制：

- Shepherd 风格的 typed trace / fork / replay：每个对话 `ChatTurn` 都应留下可观察、可诊断、可局部回放的运行证据。
- OpenClaw-RL 风格的 next-state signal：用户后续反应、工具输出、测试结果和环境状态都是行为质量信号。
- STT-Arena / SR2AM 风格的动态重规划证据：当任务目标、工具状态或工作区状态中途变化时，系统要记录 agent 是否识别、重规划并完成再验证。

## 2. 必须保持的职责边界

这些边界是对话线的硬约束：

- `ChatSession` 只是持久对话容器，不是 `WorkRun`。
- `ChatTurn` 才是一次用户请求触发的执行单元，并登记为 `WorkRun(chat_turn)`。
- raw chat transcript 不能直接进入训练、监督评测、Gym 或冻结验收集。
- 对话经验必须走 `Chat Segment -> Dataset Candidate -> Review -> Reviewed Chat Case -> Dataset/Bundle`。
- 对话线只能产出 candidate / evidence / signal，不决定 `PROMOTE` / `HOLD` / `ROLLBACK`。
- 对话线不修改 supervised selection policy、accepted baseline、frozen holdout、Gym proposal 生命周期或 self-evolution transaction 语义。
- 自进化、监督进化和对话共用同一个 agent 能力底座，但三者面对的目标不同；对话线只负责 dialogue track 适配与证据出口。

对话线负责：

- 会话创建、删除、切换、重命名、恢复和消息持久化。
- 用户消息提交、最新用户消息编辑重发、UTF-8 base64 兜底和编码污染拒绝。
- assistant 回复的回答、思考、心智模型、工具调用分段展示。
- 运行中状态、busy 锁、停止、继续、provider failure、continuation limit 和恢复提示。
- 每个 `ChatTurn` 的运行证据：目标、历史 seed、工具调用、观察、stop reason、错误、最终回复、状态快照。
- 对话专属 workspace 隔离和对话日志输出。
- chat review candidate 采集与 review 流程入口。

对话线不负责：

- 判定某个候选是否晋升为 baseline。
- 自进化事务的 apply / rollback / close 语义。
- Gym proposal 的生命周期。
- LLM provider/profile 的配置治理。
- Reset、Config、Pet Space 的深层功能，只保持入口和状态语义一致。

## 3. 当前已落地事实（2026-05-24）

### 3.1 ChatSession 与 ChatTurn

- Web Chat 已接通真实 `/api/sessions`、`/api/sessions/{id}/messages`、`/api/sessions/{id}/messages/edit-resubmit` 和会话 SSE。
- `ChatSession` 继续由 chat state 持久化，保存消息、active task、last turn status、workspace path 等。
- 每次提交或编辑重发都会创建新的 `SessionTurnControl` 和 `ChatTurn`，并写入 `WorkRun(chat_turn)`。
- 旧历史消息不能随意修改；当前实现只允许编辑最新一条用户消息并截断其后的消息重新运行。
- 非有效用户消息不会覆盖 prompt、active task 或历史 seed；“继续”会回到上一未完成任务目标。

### 3.2 WorkRun(chat_turn) 与 ResourceLease

- `core/runtime_manager/work_run_store.py` 已提供共享 `WorkRunStore`，按 run kind 保存 active/latest 快照，并记录 `work_run.snapshot.persisted` 生命周期事件。
- `session_service.py` 已为 chat turn 持久化 `runKind=chat_turn`、`track=dialogue`、`sessionId`、`runId`、`status/currentPhase`、`leases`、`summary/error`、`startedAt/updatedAt/finishedAt`。
- `runtime_service.py` 的 `/api/runtime/summary` 已暴露 `workRuns.active/latest.chat_turn`，并同时聚合 self/supervised/supervised_worktree work runs。
- `core/runtime_manager/work_run_leases.py` 已定义 lease policy：默认只读 chat 使用 `readonly_chat`，写入型 chat 使用 `worktree_write` 和 `memory_write`。
- 对话启动会检查 active self/supervised run 的 lease 冲突；self/supervised 也会检查 active chat write lease。

### 3.3 Stop / Continue / 恢复

- Web stop 会调用 `request_stop_session_turn()`，向当前 `SessionTurnControl` 写 stop request，持久化 interrupted snapshot，并释放 running 标记。
- 如果内存中的 turn controller 丢失，但 active `WorkRun(chat_turn)` 还存在，会通过 `_restore_missing_session_turn_control()` 复用原 active run identity，不生成新 turn。
- 关闭工作台前，`runtime_service._stop_active_chat_turns_before_shutdown()` 会先停止 active chat turn 并保存 partial surface。
- continuation loop 已有 `max_continuation_turns` 上限、provider failure circuit breaker 和 continuation limit 结果。
- “继续”不是新的任务目标；它会解析上一 active task goal 并构造续跑 prompt。

### 3.4 Typed Trace 与日志

- 每个 turn 会记录 `conversation.turn.started/scheduled/worker_started/ui_capture_started/agent_created/history_seeded/agent_turn_started/agent_turn_returned/terminal_result/result_persisted/worker_finished` 等 runtime scene 生命周期事件。
- turn lifecycle 会写入 runtime scene 子日志：`conversations/<session>-turns.jsonl`。
- 每个 session 拥有独立可读日志：`workspace/sessions/<session>/logs/conversation.jsonl` 和 `conversation.md`。
- 日志记录安全字段、状态、计数、路径引用、错误类型、工具摘要和 active task，不应记录 secrets、完整 prompts、大段文件或无界模型输出。
- 当前 typed trace 已覆盖多数组件事件；统一 `next_state_signal` store 已落地，作为对话线向监督/无监督线提供的安全证据引用。

### 3.5 Session Workspace 隔离

- 每个会话都有独立区域：`workspace/sessions/<safe-session-token>/`。
- 会话 workspace 下创建 `artifacts`、`tmp`、`mental_model`、`notes`、`logs`、`memory`。
- `_session_tool_workspace_override()` 会把 mental model、shell tools、memory tools、task planner 的写入重定向到当前 session workspace，避免污染全局 workspace。
- `tests/test_session_workspace_isolation.py` 已覆盖路径安全、metadata backfill、工具写入隔离和 conversation log 输出。

### 3.6 心智模型开关

- 前端左侧心智卡片保存“下轮是否启用心智模型”的开关，并随发送和编辑重发 payload 传 `mentalModelEnabled`。
- `core/web/routes/sessions.py` 把 `mentalModelEnabled` 传给 `session_service.py`。
- `_run_session_turn()` 使用 `mental_model_enabled_override()`，并在 agent 支持时调用 `set_mental_model_enabled_override()`。
- 关闭时仍保留 thought，但不会生成或持久化 mental snapshot；开启时才捕获 live mental state 并构造 `mentalSnapshot`。
- 测试已覆盖全局关闭、per-turn override、禁用时省略 mental snapshot、启用时保留 mental snapshot。

### 3.7 Review Case 流程

- `core/web/services/chat_review_service.py` 已提供 review queue、positive/negative/discard 决策、bulk discard、负例学习提示校验。
- `core/evaluation/chat_case_lifecycle.py` 明确 `rawChatDirectTrainingAllowed=False`、`candidateStage=pending_review`、`reviewedCaseStage=reviewed_chat_case`。
- 正例目标为 `chat_reviewed_multiturn`，负例目标为 `chat_negative_multiturn`。
- allowed downstream uses 当前为 `supervised_evaluation`、`gym_candidate_case`、`future_training_export`。
- `tests/test_chat_dataset_capture.py` 和 `tests/test_web_app.py` 已覆盖候选采集、安全路径、positive/negative/discard、dataset metadata、reviewRequired、non-holdout 边界和 evolution workbench 展示。

### 3.8 Next-state signal 证据链

- `core/evaluation/chat_next_state_signals.py` 已提供统一信号仓库，默认写入 `workspace/evaluation/chat_next_state_signals.jsonl`。
- 信号字段包括 `signalId`、`sessionId`、`turnId`、`source`、`kind`、`polarity`、`mode`、`relatedEventCode`、`createdAt`、`summary` 和安全裁剪后的 `metadata`。
- 当前 Web Chat 已覆盖用户纠错/编辑重发、provider failure、tool error、stop、continue、turn circuit breaker 等关键信号：
  - 编辑重发写 `kind=assistant_output_edited`，`relatedEventCode=conversation.message_edited_resubmitted`。
  - 停止写 `kind=user_stops`，继续写 `kind=user_continues`。
  - 普通 provider failure 写 `kind=provider_failure`，`relatedEventCode=conversation.turn_error`。
  - turn circuit breaker 写 `kind=provider_failure`，`relatedEventCode=conversation.turn_circuit_breaker`，metadata 保留 continuation turn 等安全字段。
  - 工具错误写 `kind=tool_error`，`relatedEventCode=conversation.tool_error`，metadata 保留工具名和错误摘要。
- `ChatDatasetCaptureService.capture_candidate()` 可携带规范化后的 `next_state_signals` 引用；这些引用是 candidate evidence，不是训练样本本体。
- `SessionDetail.nextStateSignals` 暴露最近 5 条安全摘要，`ConversationView` 在消息框外用可收缩面板展示，不写入 `messages`。
- 回归测试覆盖 repository round-trip、dataset capture 引用、session detail 安全摘要、provider failure、tool error、stop、continue、编辑重发和 circuit breaker。

## 4. 当前文档与实现差距

旧版指南方向正确，但已经落后于实现：

- 旧文档把 `ChatTurn` 登记为 `WorkRun(chat_turn)`、resource lease、runtime summary 聚合作为后续任务；当前这些已经实现，应改为维护和加固项。
- 旧文档没有把 session workspace 隔离列为核心事实；当前这是防止对话污染全局 workspace 的关键机制。
- 旧文档对 chat review lifecycle 描述偏抽象；当前 positive/negative/discard、dataset metadata 和 downstream uses 已形成公开契约。
- 旧文档把 next-state signal 作为缺口；当前统一仓库、Web Chat 关键信号、dataset capture 引用和前端摘要展示已经落地，应改为维护和扩展项。
- 终端 workbench 的 chat review 菜单仍显示 `approved/rejected` 计数，并调用旧的 approve/reject API 语义；当前服务层已转为 `positive/negative/discard`，这是 UI/术语一致性风险。
- 前端已有 `workRuns` 类型与 active work indicator，但还没有独立 `workRuns` query key；目前主要依赖 runtime summary 同步。若后续 UI 要细粒度订阅 work runs，需要补 frontend sync contract。

## 5. 可执行计划

### P0：守住 ChatTurn WorkRun 与停止/恢复正确性

目标：用户点停止必须真正停止当前 turn；关闭前后端时必须保存 partial surface；恢复时不能生成假 turn 或丢 active task。

影响文件：

- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `core/runtime_manager/work_run_store.py`
- `core/runtime_manager/work_run_leases.py`
- `tests/test_web_app.py`
- `tests/test_work_run_store.py`
- `tests/test_work_run_leases.py`

风险：

- controller 丢失时误创建新 turn，导致旧 active WorkRun 泄漏。
- stop 后后台 continuation loop 继续跑，污染后续消息。
- shutdown 时只关闭进程，不先落 partial assistant output。
- provider failure 或 continuation limit 被当成普通完成，导致用户误以为任务完成。

测试锚点：

```powershell
pytest tests/test_web_app.py -k "runtime_shutdown_stops_active_chat_turn or turn_control or stop or continue or continuation or provider" -v
pytest tests/test_work_run_store.py tests/test_work_run_leases.py -v
```

验收：

- active `workRuns.active.chat_turn` 在停止后清空。
- latest `workRuns.latest.chat_turn` 保留 stopped/failed/completed 状态和摘要。
- “继续”接续上一任务目标，而不是把“继续”当成目标。
- runtime scene 能解释 turn 是 completed、stopped、failed 还是 paused by continuation limit。

### P0：防止 raw chat 绕过 review 进入评测或训练

目标：对话线只产出 candidate/evidence，所有下游使用都必须经过 review lifecycle。

影响文件：

- `core/evaluation/chat_case_lifecycle.py`
- `core/evaluation/chat_dataset_capture.py`
- `core/evaluation/dataset_registry.py`
- `core/web/services/chat_review_service.py`
- `core/web/services/evolution_service.py`
- `tests/test_chat_dataset_capture.py`
- `tests/test_dataset_registry.py`
- `tests/test_web_app.py`

风险：

- 新增 dataset 时忘记 `review_required=True` 或 `holdout_allowed=False`。
- 将 pending candidate 当作 supervised positive case。
- negative case 被丢弃，无法沉淀失败模式。

测试锚点：

```powershell
pytest tests/test_chat_dataset_capture.py -v
pytest tests/test_dataset_registry.py -k "chat_reviewed or review" -v
pytest tests/test_web_app.py -k "chat_review or dataset" -v
```

验收：

- `rawChatDirectTrainingAllowed` 恒为 `false`。
- `chat_reviewed_multiturn` 标记 `reviewRequired=True`、`sourceTrack=dialogue`、`holdoutAllowed=False`。
- pending、positive、negative、discard 状态清晰可见且不会混入错误数据集。

### P1：加固统一 next-state signal 契约与消费边界

目标：维护已落地的 typed signal 仓库，把用户后续行为、工具/测试结果、停止/继续、编辑重发、provider failure 和验证结果作为 evidence/candidate 引用提供给监督线和无监督线，但不让对话线做最终决策。

当前契约：

- `signalId`
- `sessionId`
- `turnId`
- `source`: `user` / `tool` / `runtime` / `verification` / `review`
- `kind`: `user_accepts` / `user_corrects` / `user_reasks` / `user_stops` / `user_continues` / `assistant_output_edited` / `tool_error` / `verification_passed` / `verification_failed` / `provider_failure`
- `polarity`: `positive` / `negative` / `neutral`
- `mode`: `evaluative` / `directive`
- `relatedEventCode`
- `createdAt`
- `summary`
- `metadata`: 安全裁剪字段，不能保存完整 prompt、大段输出或 secrets

影响文件：

- `core/evaluation/chat_next_state_signals.py`
- `core/web/services/session_service.py`
- `core/evaluation/chat_dataset_capture.py`
- `web/src/components/conversation/ConversationView.tsx`
- `web/src/api/types.ts`
- `tests/test_web_app.py`
- `tests/test_chat_next_state_signals.py`
- `tests/test_chat_dataset_capture.py`

风险：

- 信号过于宽泛，变成另一份聊天 transcript。
- 信号被监督线误读为 decision。
- 记录用户原文过多，带来隐私和日志膨胀。

测试锚点：

```powershell
pytest tests/test_chat_next_state_signals.py tests/test_chat_dataset_capture.py tests/test_web_app.py -k "next_state or signal or circuit_breaker or tool_error" -q
pytest tests/test_web_app.py -k "message_edit or stop or continue or provider" -v
```

验收：

- 停止、继续、编辑重发、provider failure、tool error 和 turn circuit breaker 能生成结构化 signal。
- signal 只记录摘要、类型和关联 ID，不记录完整 prompt 或大段输出。
- review candidate 可以引用 signal summary，但不能直接把 signal 当训练样本。
- 后续若接入测试/验证工具，应补 `verification_passed` / `verification_failed` 的实际 emission 点和回归测试。

### P1：统一终端 review UI 术语

目标：终端工作台的 chat review 菜单与 Web/API 生命周期保持一致，避免 reviewer 看到 `approved/rejected` 旧语义。

影响文件：

- `core/ui/workbench.py`
- `core/evaluation/chat_dataset_capture.py`
- `core/evaluation/chat_review_queue.py`
- `tests/test_workbench.py`
- `tests/test_chat_dataset_capture.py`

风险：

- 旧 `reject_chat_candidate()` 兼容 API 被误认为 negative，但当前语义更接近 discard。
- 终端显示 approved/rejected，Web 显示 positive/negative/discard，导致人工 review 结果错判。

测试锚点：

```powershell
pytest tests/test_workbench.py -k "chat_dataset or review" -v
pytest tests/test_chat_dataset_capture.py -v
```

验收：

- 终端显示 pending/positive/negative/discard。
- negative review 要求至少有 reason、error type、correct principle 或 ideal behavior。
- discard 明确只进入 audit log，不进入正负例数据集。

### P1：加固心智模型动态开关的前端契约

目标：保证左侧心智卡片控制的是“下一轮” payload，不影响已完成消息，也不在发送框占空间。

影响文件：

- `web/src/routes/ChatCodingRoute.tsx`
- `web/src/routes/ChatCodingRoute.module.css`
- `web/src/components/conversation/ConversationView.tsx`
- `web/src/api/client.test.ts`
- `tests/test_web_app.py`

风险：

- localStorage 状态和实际 payload 不一致。
- 编辑重发漏传 `mentalModelEnabled`。
- 禁用心智模型时仍从 live capture 注入 mental snapshot。

测试锚点：

```powershell
pytest tests/test_web_app.py -k "mental_model or mentalModelEnabled" -v
cd web; npm test -- --run ChatCodingRoute ConversationView client
```

验收：

- 发送和编辑重发都携带当前开关值。
- 禁用时 assistant message 无 `mentalSnapshot`。
- 开启后下一轮恢复 mental capture，不影响历史消息。

### P2：细化 WorkRun 前端同步

目标：当 UI 需要独立展示或订阅 work run 状态时，把 `workRuns` 从 runtime summary 附属字段提升为稳定前端查询契约。

影响文件：

- `web/src/api/queryKeys.ts`
- `web/src/api/types.ts`
- `web/src/app/systemStatus.ts`
- `web/src/routes/ChatCodingRoute.tsx`
- `web/src/routes/EvolutionRoute.tsx`
- `web/src/api/client.test.ts`

风险：

- runtime summary 和独立 workRuns query 双源漂移。
- SSE invalidation 范围过宽导致 UI 闪烁或草稿被覆盖。

测试锚点：

```powershell
cd web; npm test -- --run systemStatus client ChatCodingRoute
cd web; npm run build
pytest tests/test_web_app.py -k "runtime_summary or session or evolution" -v
```

验收：

- query key 语义稳定。
- session SSE 只更新当前 active session。
- runtime summary 仍是全局壳层的兼容入口。

## 6. 关键文件索引

后端：

- `core/web/routes/sessions.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `core/web/services/runtime_scene_service.py`
- `core/web/services/chat_review_service.py`
- `core/runtime_manager/work_run_store.py`
- `core/runtime_manager/work_run_leases.py`
- `core/evaluation/chat_case_lifecycle.py`
- `core/evaluation/chat_dataset_capture.py`
- `core/evaluation/chat_segmenter.py`
- `core/evaluation/dataset_registry.py`
- `core/chat/chat_session_manager.py`
- `core/ui/chat_state.py`
- `core/ui/workbench.py`
- `core/ui/cli_ui.py`
- `core/orchestration/agent_modes.py`

前端：

- `web/src/routes/ChatCodingRoute.tsx`
- `web/src/routes/ChatCodingRoute.module.css`
- `web/src/components/conversation/ConversationView.tsx`
- `web/src/components/conversation/ConversationView.module.css`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/api/queryKeys.ts`
- `web/src/store/chatWorkbenchStore.ts`
- `web/src/app/systemStatus.ts`
- `web/src/i18n/dictionary.ts`

测试：

- `tests/test_web_app.py`
- `tests/test_chat_dataset_capture.py`
- `tests/test_session_workspace_isolation.py`
- `tests/test_work_run_store.py`
- `tests/test_work_run_leases.py`
- `tests/test_dataset_registry.py`
- `tests/test_workbench.py`
- `tests/test_cli_ui.py`
- `tests/test_conversation_logger.py`
- `web/src/api/client.test.ts`
- `web/src/app/systemStatus.test.ts`

## 7. 开发原则

1. 会话连续性优先于 UI 表现。历史恢复、active task、mental snapshot、read files、workspace metadata 任一丢失，都先修数据链。
2. 可见内容必须清洗协议残片。`state`、`invoke`、`parameter`、DSML 残片、半截标签不能进入回答区或 active task 摘要。
3. 停止必须是真停止。Web stop 必须传递到 turn control、continuation loop、agent interrupt checker 和 shutdown partial persistence。
4. 对话页只展示对话该展示的东西。不要把 Git、Config、Evolution、Reset 的深层控制面塞回 Chat 主区域。
5. 多轮推进要有上限。`max_continuation_turns` 是防止同一用户消息无限自转的安全阀。
6. 每个有价值 turn 都要留下证据。证据不等于训练样本；证据必须先进入 candidate/review 流程。
7. 用户后续行为是质量信号。追问、纠错、停止、继续、接受、放弃和编辑重发都应结构化记录。
8. 动态变化必须显式记录。工具状态、文件状态、任务目标或用户约束变化时，要记录 agent 是否检测到变化、是否重规划、是否完成二次验证。
9. 对话 workspace 必须隔离。agent 在对话中产生的文件、心智模型、memory/task 临时状态默认写入当前 session workspace。
10. 对话线只交证据，不做进化决策。所有 PROMOTE/HOLD/ROLLBACK 仍归监督/Gym 决策边界。

## 8. 与监督进化线的接口

对话线可以提供：

- 人工审核过的多轮对话正例和负例。
- 用户最终接受或修正后的 assistant 回复证据。
- 工具调用轨迹、任务完成结果、provider failure 和停止/恢复事件摘要。
- next-state signal 摘要。
- 动态变化与重规划证据。

对话线不能直接修改：

- `workspace/supervised_evolution/decisions`
- `workspace/supervised_evolution/policy`
- `core/evaluation/selection_policy.py`
- frozen holdout / `V_ref` 标准
- Gym proposal 的 accept/reject/promote 结论

## 9. 与无监督进化线的接口

对话线可以提供：

- 当前会话目标和最新 active task。
- 最近失败、停止、恢复、provider failure、continuation limit 证据。
- 用户对 agent 行为的纠正。
- 可作为自我诊断输入的 runtime scene 日志。
- trace-driven failure pattern 和 next-state signal。

对话线不能直接做：

- 自进化事务开账或关账。
- 自进化历史删除。
- 自进化运行的 start/pause/resume/stop 控制语义。
- 将自进化建议直接写回对话系统 prompt 或 runtime policy。

## 10. 推荐验证套件

对话主链：

```powershell
pytest tests/test_web_app.py -k "session or message or stop or continuation or mental or tool or chat_turn" -v
pytest tests/test_session_workspace_isolation.py -v
```

WorkRun 与 lease：

```powershell
pytest tests/test_work_run_store.py tests/test_work_run_leases.py -v
pytest tests/test_web_app.py -k "work_run or runtime_summary or lease" -v
```

Review case：

```powershell
pytest tests/test_chat_dataset_capture.py -v
pytest tests/test_dataset_registry.py -k "chat_reviewed or review" -v
pytest tests/test_web_app.py -k "chat_review or dataset" -v
```

Next-state signal：

```powershell
pytest tests/test_chat_next_state_signals.py tests/test_chat_dataset_capture.py tests/test_web_app.py -k "next_state or signal or circuit_breaker or tool_error" -q
```

终端与前端：

```powershell
pytest tests/test_workbench.py -k "chat or review or tool" -v
pytest tests/test_cli_ui.py -v
cd web; npm test -- --run client systemStatus ChatCodingRoute ConversationView
cd web; npm run build
```

## 11. 当前优先级摘要

1. P0：持续保护 `ChatTurn -> WorkRun(chat_turn)`、stop/continue/recovery、shutdown partial persistence。
2. P0：持续保护 raw chat 不绕过 review，reviewed chat case 才能进入 supervised/Gym 数据入口。
3. P1：持续加固统一 `next_state_signal` 契约、消费者摘要展示和验证类 signal emission。
4. P1：统一终端 review UI 的 positive/negative/discard 术语。
5. P1：补强心智模型动态开关的前端 payload 测试。
6. P2：需要更细粒度 UI 时，再添加独立 WorkRun query/sync contract。

## 12. 提交说明

对话线提交建议使用：

- `fix(chat): ...`
- `feat(chat): ...`
- `refactor(chat): ...`
- `test(chat): ...`
- `docs(chat): ...`

每次提交只覆盖一个行为目标。不要把 Evolution、Config、Reset 的无关改动混进对话线提交。
