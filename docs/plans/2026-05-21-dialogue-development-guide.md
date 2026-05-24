# 对话开发指导文档

## 定位

对话线负责把 Vibelution 做成一个稳定、连续、可观察、可沉淀经验的 agent 对话工作台。

它的核心目标不是多一个聊天页面，而是让用户能在同一个会话里持续给任务、看 agent 思考、看工具调用、停止/继续运行、恢复历史上下文，并把有价值的对话经验以受控方式交给监督进化和无监督进化线。

结合 Agent Harness 论文综述，对话线应优先吸收三类机制：

- Shepherd 风格的 typed trace / fork / replay：每个对话 turn 都应留下可观察、可回放的运行证据。
- OpenClaw-RL 风格的 next-state signal：用户后续反应、工具输出、测试结果和环境状态都是行为质量信号。
- STT-Arena / SR2AM 风格的动态重规划证据：当任务目标、工具状态或工作区状态中途变化时，系统要记录 agent 是否识别、重规划并完成再验证。

这条线覆盖 Web Chat、终端工作台、会话持久化、实时运行状态、心智状态展示、消息清洗、文件上下文、对话经验候选采集和运行证据导出。

## 当前事实

- Web Chat 已接通真实 `/api/sessions` 和 `/api/sessions/{id}/messages`。
- 对话消息支持四段式展示：思考、心智模型、工具调用、回答。
- 后端 live payload 已拆分 `thought`、`content`、`mentalSnapshot`、`toolCalls`。
- 停止请求、stopping 状态、历史恢复、active task 续跑、max continuation 都已经有实现和测试。
- 右侧会话面板已有新建和删除会话能力。
- 非 assistant 消息已有正文渲染修复。
- 对话线现在同时牵涉 Web 前端、FastAPI session service、agent runtime 和终端工作台。
- 最新架构方向要求 `ChatTurn` 进入共享 `WorkRun(chat_turn)` 底座，而 `ChatSession` 仍只是持久对话容器。

## 职责边界

对话线负责：

- 用户消息提交、会话创建、删除、切换、恢复。
- assistant 回复的可见内容、思考、工具调用、心智模型分段展示。
- 运行中状态、停止、继续、busy 锁、错误可见性。
- 会话历史与当前 task goal 的连续性。
- 文件上下文在对话工作台中的阅读和引用。
- 每个 `ChatTurn` 的可观察运行证据：prompt、目标、工具调用、观察结果、stop reason、错误、测试结果、最终回复。
- next-state signal 采集：用户追问、纠错、接受、放弃、停止、继续、手动改写输出、工具错误、测试通过/失败。
- 把人工审核过的对话片段提供给数据集、监督线或 Gym。

对话线不负责：

- 判定某个候选是否应该晋升为 baseline。
- 自进化事务的 apply/rollback 语义。
- Gym proposal 的生命周期。
- LLM provider/profile 的配置治理。
- 冻结评测集、selection policy 或 accepted baseline 的修改。
- Reset、Config、Pet Space 的深度功能，只能保持入口一致。

## 共享底座边界

对话线必须遵守横向计划：[WorkRun Substrate And Chat Case Loop Implementation Plan](./2026-05-21-workrun-substrate-and-chat-case-loop.md)。

统一边界：

- `ChatSession` 是持久对话容器，不是 WorkRun。
- `ChatTurn` 是一次用户请求触发的执行单元，应该登记为 `WorkRun(chat_turn)`。
- 对话线不能自己定义一套全局 active run，也不能用 Chat running 状态阻断所有进化；是否并行由 `ResourceLease` 判断。
- raw chat transcript 不能直接进入训练或监督评测。
- 对话经验必须走 `Chat Segment -> Dataset Candidate -> Review -> Reviewed Chat Case -> Dataset/Bundle`，才能交给监督进化或 Gym。
- 对话线输出的是 evidence 和 candidate，不输出 PROMOTE / HOLD / ROLLBACK 决策。

对话线向共享底座提供：

- `chat_turn` 的 queued/running/stopping/completed/failed/stopped 快照。
- 当前 turn 的 resource leases，例如 `readonly_chat` 或 `worktree_write`。
- bounded event tail：用户输入、模型输出摘要、工具调用、工具观察、错误、停止、继续、完成。
- next-state signal：用户后续行为、工具结果、环境状态和验收结果。
- 可审核的 chat case candidate，不提供未审核训练样本。

## 论文启发到工程机制

- Shepherd：把对话 turn 视为 typed execution trace。短期目标是 artifact 级 replay，记录关键输入、输出和观察；长期可以支持 fork/replay live agent state。
- OpenClaw-RL：把用户后续消息、工具输出、终端/GUI 状态、测试结果都当作 next-state signal；信号分为 evaluative signal 和 directive signal。
- STT-Arena：增加动态任务证据，记录中途状态变化、工具状态变化、任务不可行、重新规划和 post-adaptation verification。
- SR2AM：保留轻量 planning / replanning 标记，区分 reactive execution、simulative planning 和 learned run control。
- MAVEN：对话片段进入 review 前应有明确中间表示，例如目标、上下文、失败类型、推荐标签和 reviewer note。

## 关键文件

后端：

- `core/web/routes/sessions.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `core/web/services/runtime_scene_service.py`
- `core/web/services/chat_review_service.py`
- `core/chat/chat_session_manager.py`
- `core/ui/chat_state.py`
- `core/ui/workbench.py`
- `core/ui/cli_ui.py`
- `core/orchestration/agent_modes.py`
- `core/runtime_manager/work_run_store.py`，如共享底座已引入
- `core/runtime_manager/work_run_leases.py`，如共享 lease policy 已引入

前端：

- `web/src/routes/ChatCodingRoute.tsx`
- `web/src/routes/ChatCodingRoute.module.css`
- `web/src/components/conversation/ConversationView.tsx`
- `web/src/components/conversation/ConversationView.module.css`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/store/chatWorkbenchStore.ts`
- `web/src/i18n/dictionary.ts`

测试：

- `tests/test_web_app.py`
- `tests/test_workbench.py`
- `tests/test_cli_ui.py`
- `tests/test_conversation_logger.py`
- `tests/test_chat_dataset_capture.py`
- `web/src/api/client.test.ts`

## 开发原则

1. 会话连续性优先于 UI 表现。
   如果历史恢复、active task、mental snapshot、read files 任一丢失，先修数据链，不先调样式。

2. 可见内容必须清洗协议残片。
   `state`、`invoke`、`parameter`、DSML 残片、半截标签不能进入回答区或 active task 摘要。

3. 停止必须是真停止。
   Web stop 不能只写一个 UI 状态；必须传递到当前 turn control 和子进程等待循环。

4. 对话页只展示对话该展示的东西。
   不要把 Git、Config、Evolution、Reset 的深层控制面塞回 Chat 主区域；它们应留在顶栏或对应页面。

5. 多轮推进要有上限。
   `max_continuation_turns` 的目的不是削弱能力，而是避免同一用户消息无限自转。

6. 每个有价值 turn 都要留下证据。
   证据不等于训练样本；证据要先进入 candidate/review 流程。

7. 用户后续行为是质量信号。
   追问、纠错、停止、继续、接受和放弃都应被结构化记录，供监督线和无监督线分析。

8. 动态变化必须显式记录。
   当工具状态、文件状态、任务目标或用户约束发生变化时，要记录 agent 是否检测到变化、是否重规划、是否完成二次验证。

## 优先任务

### 任务 1：稳定会话恢复

目标：刷新页面、重启服务、打开旧会话后，用户能看到同一条 active task、最近消息、文件上下文和心智状态。

重点检查：

- `SessionService` 是否从 chat state 恢复最近消息。
- `MentalModel` seed 是否包含历史摘要。
- `readFiles`、`previewTabs`、`activePreviewPath` 是否只在用户明确打开文件时恢复。
- stale running/stopping 会话是否能给出可见恢复提示。
- 恢复后的 `ChatTurn` 是否能和最新 `WorkRun(chat_turn)` 快照对应。

建议测试：

```powershell
pytest tests/test_web_app.py -k "session or continuation or mental or stop" -v
```

### 任务 2：稳定运行中视图

目标：运行中时，用户能看懂 agent 在做什么，而不是只看到 loading 或半截协议文本。

重点检查：

- live payload 的 `thought/content/toolCalls/mentalSnapshot` 分流。
- `ConversationView` 的四段式折叠逻辑。
- SSE 或轮询刷新不会覆盖用户输入草稿。
- 回到底部按钮和滚动锁定是否稳定。
- 工具调用、观察结果和错误是否能进入 bounded trace，而不是只进入可见文本。

建议测试：

```powershell
pytest tests/test_web_app.py -k "live or events or toolCalls or visible" -v
cd web; npm test -- --run client
```

### 任务 3：稳定停止和继续

目标：用户点停止后，后台不会继续跑；用户发送“继续”后，能接上上一轮任务目标。

重点检查：

- `SessionTurnControl` 与 result stop flag 必须同时参与可见停止提示。
- 子 agent 进程树必须能被取消。
- `recent_blockers` 不应被子 agent 空结果污染。
- 继续时应保留上一 active task goal，而不是把“继续”本身当成目标。
- stop/continue 应进入 next-state signal，供后续诊断和 case review 使用。

建议测试：

```powershell
pytest tests/test_web_app.py -k "stop or continue or blocker or subagent" -v
```

### 任务 4：把 ChatTurn 登记为 WorkRun

目标：每次用户请求都能在 runtime summary 中作为 `WorkRun(chat_turn)` 被观察，并能与会话消息关联。

重点检查：

- 每个 turn 有稳定 `runId`、`sessionId`、`turnId` 或等价关联键。
- queued/running/stopping/completed/failed/stopped 状态会写入共享 WorkRun store。
- `active/latest` 只在 `chat_turn` kind 内生效。
- read-only chat 和 coding chat 的 resource leases 能被区分。
- 完成后保留 latest snapshot 和 bounded event tail。

建议测试：

```powershell
pytest tests/test_web_app.py -k "chat_turn or runtime_summary or session" -v
pytest tests/test_work_run_store.py -v
pytest tests/test_work_run_leases.py -v
```

### 任务 5：采集 next-state signal

目标：把用户后续行为和工具/环境反馈结构化，作为监督评测与无监督诊断的输入。

建议先支持这些信号：

- `user_accepts`：用户继续推进或明确接受。
- `user_corrects`：用户指出错误或给出修正。
- `user_reasks`：用户重复同类请求或追问未解决问题。
- `user_stops` / `user_continues`：用户中断或要求续跑。
- `tool_error`：工具调用失败、超时、返回异常。
- `verification_passed` / `verification_failed`：测试、构建或手工验收结果。
- `assistant_output_edited`：用户手动改写或忽略输出。

要求：

- 信号要带来源 turn、时间、可选 tool/event 关联。
- 信号要区分 evaluative 和 directive。
- 信号本身不能直接变成训练样本。

建议测试：

```powershell
pytest tests/test_web_app.py -k "signal or session or chat_review" -v
pytest tests/test_chat_dataset_capture.py -v
```

### 任务 6：把对话经验交给进化线

目标：人工审核过的多轮对话片段能进入 `chat_reviewed_multiturn` 候选数据集，但不能直接污染冻结验收集。

重点检查：

- `core/web/services/chat_review_service.py`
- `tests/test_chat_dataset_capture.py`
- `core/evaluation/dataset_registry.py`

要求：

- 每条片段必须有来源会话、来源 turn、review 状态和采样边界。
- 未审核片段不能被当成监督正样本。
- 对话线只提供候选数据，不决定 PROMOTE。
- negative reviewed case 也要保留，作为反例和失败模式来源。

建议测试：

```powershell
pytest tests/test_chat_dataset_capture.py -v
pytest tests/test_dataset_registry.py -k "chat_reviewed or review" -v
```

## 与监督进化线的接口

对话线向监督线提供：

- 人工审核过的多轮对话样本。
- 用户最终接受的 assistant 回复版本。
- 工具调用轨迹与任务完成结果。
- next-state signal 摘要。
- 动态变化和重规划证据。

对话线不能直接修改：

- `workspace/supervised_evolution/decisions`
- `workspace/supervised_evolution/policy`
- `core/evaluation/selection_policy.py`
- frozen holdout / `V_ref` 标准

## 与无监督进化线的接口

对话线向无监督线提供：

- 当前会话目标。
- 最近失败/停止/恢复证据。
- 用户对 agent 行为的纠正。
- 可作为自我诊断输入的 runtime scene 日志。
- trace-driven failure pattern 和 next-state signal。

对话线不能直接做：

- 自进化事务开账或关账。
- 自进化历史删除。
- 自进化运行的 start/pause/resume/stop 控制语义。
- 将自进化建议直接写回对话系统 prompt 或 runtime policy。

## 验收清单

- 用户能创建、删除、切换会话。
- 旧会话恢复后，不丢最近消息和任务目标。
- assistant 消息不显示协议残片。
- 工具调用跟随消息显示，不串到别轮。
- stop 后后台真正停止。
- continue 后接续上一任务，而不是开始无意义新任务。
- 每个 ChatTurn 可在 WorkRun summary 中定位。
- 每个高价值 turn 至少保留 bounded trace。
- 用户纠错、停止、继续、工具失败和验证结果可作为 next-state signal 查询。
- reviewed chat case 和 raw chat transcript 有明确边界。
- Web 和终端的对话语义不互相冲突。

## 推荐验证

```powershell
pytest tests/test_web_app.py -k "session or message or stop or continuation or mental or tool or chat_turn" -v
pytest tests/test_workbench.py -k "chat or tool" -v
pytest tests/test_cli_ui.py -v
pytest tests/test_chat_dataset_capture.py -v
pytest tests/test_work_run_store.py tests/test_work_run_leases.py -v
cd web; npm test -- --run client
cd web; npm run build
```

## 提交说明

对话线提交建议使用：

- `fix(chat): ...`
- `feat(chat): ...`
- `refactor(chat): ...`
- `test(chat): ...`

每次提交只覆盖一个行为目标。不要把 Evolution、Config、Reset 的无关改动混进对话线提交。
