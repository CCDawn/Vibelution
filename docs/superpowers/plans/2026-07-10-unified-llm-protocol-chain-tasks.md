# 统一 LLM 协议链任务图

Date: 2026-07-10
Status: task splitting complete, implementation not started
Decision: SPLIT
Accepted design: `docs/superpowers/specs/2026-07-10-unified-llm-protocol-chain-design.md`
Accepted plan: `docs/superpowers/plans/2026-07-10-unified-llm-protocol-chain.md`
Reuse decision: ADAPT Hermes route and protocol patterns; do not copy its Agent loop

## 上下文边界

首轮只实现 Chat Completions 与 Responses 的标准链路。Anthropic Messages 和 Gemini 仅保留协议枚举及路由表达能力，不实现、不启用，必须先完成独立的 transport/auth/replay 子设计。

关键目标：

```text
commentary/progress -> tool call -> tool result -> model continuation -> one final answer
```

全局保护边界：

- 不修改工具业务逻辑、审批策略或历史 journal 文件。
- 不把 OpenAI 字典、React DTO 或 `AIMessage` 当作统一协议真相。
- 不记录 prompt、完整参数、provider payload 或 opaque replay data。
- 不在同一未审查切片中同时改变路由、Agent 状态机、Journal DTO 和 React 所有权。
- 不直接在根 `main` 开发；每个实现任务在独立 worktree 和 claim 中执行。
- 共享 `client.py`、`streaming.py`、`agent.py`、Journal 和前端 DTO 的任务按依赖顺序串行合并。

## 任务图

关键路径：

```text
Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6 -> Task 7 -> Task 8 -> Task 9
```

并行性：

- Task 1 与 Task 2 文件面独立，可在不同 worktree 准备，但 Task 1 必须在 Task 8 前落地。
- Task 4 与 Task 5 都修改 `core/llm/client.py` 和 `core/llm/streaming.py`，不得并行合并。
- Task 7 与 Task 8 是共享 DTO/projection 串行工作，Task 7 后端契约先稳定，Task 8 再接入 React。
- Task 9 必须最后执行，避免辅助路径和 fallback 固化未稳定接口。

可选路径：

- Optional O1: 在 Task 3 契约稳定后，单独进入 `ccdawn-planning`，设计 Anthropic/Gemini transport、认证、依赖、replay persistence 与启用门禁。它不阻塞首轮 Chat/Responses 交付。

## Task 1: 消除同轮 live overlay 与最终回答重复

- Goal: 同一 turn 已有 committed assistant answer 时只显示最终回答；未完成 overlay 仍可恢复显示。
- Inputs: `2026-07-10-assistant-message-consolidation.md`。
- Outputs: 稳定的前端同轮身份合并前置行为。
- Files: `web/src/components/conversation/useAgentMessageTimelineProjection.ts`、对应测试文件。
- Boundary: 不修改 backend journal、`session_service.py`、文本内容或工具/推理行。
- Reuse: 复用 `conversationMessageTurnId`、`isSameConversationTurn` 和现有 projection pipeline。
- Dependencies: 无；Task 8 的强制前置。
- Criticality: critical。
- Development Mode: BDD_TDD。
- BDD/TDD Anchor: Given 同轮 stale overlay 与 committed answer，When timeline projection，Then 只保留 committed answer；Given 只有未完成 overlay，Then overlay 保持可见。先让重复场景失败。
- Verification: `npm --prefix web test -- src/components/conversation/useAgentMessageTimelineProjection.test.ts`；相邻 timeline/native transcript 测试；`npm --prefix web run build`。
- Review Gate: 身份合并不得依赖文本相等，不得删除 commentary/tool/reasoning。
- Risk: 误删中断恢复草稿或不同 turn 的相同文本。

## Task 2: 固化 WireProtocol 与 invocation route

- Goal: 每次 invocation 根据 effective model 得到不可变、可解释、不会污染配置的 route。
- Inputs: 已批准的路由优先级与 OpenCode provider-model 规则。
- Outputs: `WireProtocol`、迁移别名、`ResolvedProtocolRoute`、route source scope、configured/runtime endpoint。
- Files: `core/llm/protocols.py`、`core/llm/protocol_resolver.py`、`core/llm/invocation_context.py`、`config/models.py`、`tests/test_llm_protocol_resolver.py`。
- Boundary: 不修改 payload、stream decoder、Agent、Journal 或 React。
- Reuse: ADAPT Hermes 的 provider+effective-model 规则；保留 Vibelution 现有 resolver/config ownership。
- Dependencies: 无。
- Criticality: critical, high risk。
- Development Mode: BDD_TDD。
- BDD/TDD Anchor: Given model-explicit、OpenCode mixed-model、provider API、profile default 和 declared Chat fallback 冲突，When resolve，Then 严格按既定优先级选择并记录 `source_scope`；Given model switch/fallback，Then 新建 route 且不覆盖 configured endpoint。先添加失败矩阵。
- Verification: `py -3 -m pytest tests/test_llm_protocol_resolver.py -q`。
- Review Gate: 已知但未安装 adapter 的 native route 必须 preflight hard-fail，禁止静默降级到 Chat。
- Risk: profile 默认值重新压过 effective-model 规则，或 runtime URL 被写回 operator config。

## Task 3: 建立 semantic request、canonical event 与 replay 边界

- Goal: provider adapter 接收语义 IR，并通过带复合身份的 canonical event/outcome 交付结果。
- Inputs: Task 2 immutable route。
- Outputs: semantic message parts、`ProviderReplayState`、canonical call/result/event/outcome、adapter registry 基础契约。
- Files: `core/llm/semantic_messages.py`、`core/llm/provider_replay_state.py`、`core/llm/wire/types.py`、`core/llm/wire/base.py`、`core/llm/wire/registry.py`、`core/llm/types.py`、相关新测试。
- Boundary: 不实现 Responses/Chat wire decoding，不改变 Agent completion，不写 Journal/DTO。
- Reuse: 将现有 model messages 作为迁移输入；`message_to_openai_dict` 不得进入通用 IR。
- Dependencies: Task 2。
- Criticality: critical, high risk。
- Development Mode: BDD_TDD。
- BDD/TDD Anchor: Given text/image/tool call/tool result/reasoning replay parts，When adapter dispatch，Then 保留语义和复合身份；Given replay state issuer/endpoint/model 不匹配，Then send 前拒绝且不泄漏 opaque data。先增加 contract/rejection 测试。
- Verification: `py -3 -m pytest tests/test_llm_semantic_messages.py tests/test_llm_provider_replay_state.py tests/test_llm_client.py -q`。
- Review Gate: 辅助调用必须获得明确 invocation scope；无 chat session 时使用受控 synthetic scope，不能留空后依赖文本去重。
- Risk: OpenAI shape 继续渗透通用层，或 replay blob 进入日志/DTO。

## Task 4: 实现 Responses 标准链路

- Goal: Responses stream 与 non-stream 都生成相同 canonical items/outcome，并正确区分 commentary、reasoning、tool 与 final answer。
- Inputs: Task 3 adapter/event contracts。
- Outputs: Responses request encoder、stream/non-stream decoder、tool result encoder、fixture coverage。
- Files: `core/llm/wire/responses.py`、`core/llm/payload_builder.py`、`core/llm/payload_validator.py`、`core/llm/streaming.py`、`core/llm/client.py`、Responses 相关测试。
- Boundary: 不改变 Chat semantics、Agent tool execution、Journal 或 React。
- Reuse: ADAPT Hermes 的 `response.output_item.done` 重建与 phase-aware routing；复制实质代码时补 MIT attribution。
- Dependencies: Task 3。
- Criticality: critical, high risk。
- Development Mode: BDD_TDD。
- BDD/TDD Anchor: Given commentary -> function call -> result continuation -> final，When decode，Then commentary 不完成 turn 且 final 只出现一次；Given terminal `output=null`，Then 从 completed items 重建；Given incomplete/cancelled，Then 不返回 success。先增加 provider fixture 失败测试。
- Verification: `py -3 -m pytest tests/test_llm_wire_responses.py tests/test_llm_client.py tests/test_llm_payload_builder.py tests/test_llm_payload_validator.py -q`。
- Review Gate: terminal semantics 只来自 Responses terminal event，call ID 跨 continuation 保持一致。
- Risk: terminal object 空 output 导致丢消息，或 commentary 被投影成 final answer。

## Task 5: 实现 Chat Completions 标准链路

- Goal: Chat stream/non-stream 通过同一 canonical contract，pre-tool text 根据 terminal reason 正确重分类或晋升。
- Inputs: Task 4 已稳定的 shared client/stream ownership。
- Outputs: Chat adapter、interim text promotion、tool accumulation、OpenAI-only message projection。
- Files: `core/llm/wire/chat_completions.py`、`core/llm/message_projector.py`、`core/llm/streaming.py`、`core/llm/client.py`、Chat/turn assembler 测试。
- Boundary: 不修改 Agent、Journal、React；不得改变 Responses 已通过的行为。
- Reuse: 迁移现有 LiteLLM/OpenAI delta accumulator；`message_to_openai_dict` 仅归 Chat adapter。
- Dependencies: Task 4，因共享文件必须串行。
- Criticality: critical, high risk。
- Development Mode: BDD_TDD。
- BDD/TDD Anchor: Given tools enabled 且先收到文本，When finish reason=`tool_calls`，Then 文本转 commentary；When successful no-tool terminal，Then 同 identity 下一 revision 晋升一次为 answer；When cancel/fail，Then 不晋升。先添加 stream/non-stream parity 和 cancellation 失败测试。
- Verification: `py -3 -m pytest tests/test_llm_wire_chat_completions.py tests/test_llm_turn_assembler.py tests/test_llm_client.py -q`。
- Review Gate: React/Agent 不得根据到达顺序重新猜测 interim text channel。
- Risk: 流式草稿过早完成 turn，或 reclassification 生成两个可见 item。

## Task 6: 迁移 Agent tool loop 与 completion ownership

- Goal: Agent 只从 `TurnOutcome` 决定执行工具、继续模型或完成，并且每个工具结果只编码一次。
- Inputs: Task 4/5 两个 adapter 的统一 outcome。
- Outputs: outcome-driven state machine、唯一 `CanonicalToolResult` ownership、兼容 `AIMessage` projection。
- Files: `agent.py`、`core/orchestration/response_processor.py`、`core/orchestration/turn_outcome.py`、`core/orchestration/round_state.py`、`core/orchestration/tool_lifecycle.py`、`core/chat/model_messages.py`、相关测试。
- Boundary: 不改变工具业务实现、审批、Journal schema 或 React。
- Reuse: 保留现有 tool executor；`ToolLifecycleBridge` 产生 canonical result，wire adapter 单独负责编码。
- Dependencies: Task 5。
- Criticality: critical, high risk。
- Development Mode: BDD_TDD。
- BDD/TDD Anchor: Given commentary 和 pending tool calls，When iteration terminal，Then Agent 执行工具并继续而不完成；Given tool result，Then continuation 中只有一个 matching provider result；Given final outcome，Then 必须有 terminal evidence 且 pending calls 为空。先让旧 visible-text completion 路径失败。
- Verification: `py -3 -m pytest tests/test_agent_protocol.py tests/test_model_messages.py tests/test_tool_pairing_validator.py -q`。
- Review Gate: 删除或隔离 `AIMessage.content/tool_calls` 的 completion ownership，保留兼容 projection 但不可反向控制状态机。
- Risk: 工具结果重复 append、call ID 丢失或 commentary 提前结束 iteration。

## Task 7: 建立 canonical journal 与 SessionTurnItem v2

- Goal: backend 以 canonical identity/channel/status 写入 journal，并向 session API 发布显式 v2 items。
- Inputs: Task 6 稳定的 event/outcome/tool lifecycle。
- Outputs: `assistant_item_committed`、legacy read-only replay、SessionTurnItem v2、确定写入顺序。
- Files: `core/chat/turn_journal.py`、`core/web/services/session_service.py`、backend journal/session projection 测试。
- Boundary: 不迁移历史 journal，不修改 React，不用文本相等做身份。
- Reuse: 保留现有 eventId/sequence/terminal protection 和 stable item ID 基础。
- Dependencies: Task 6。
- Criticality: critical, high risk。
- Development Mode: BDD_TDD。
- BDD/TDD Anchor: Given provisional item、reclassification、tool lifecycle 和 terminal outcome，When journal/project，Then 按 live -> item commit/revision -> tools -> terminal -> single assistant message 顺序；Given legacy delta event，Then 可读但新 writer 不再产出。先添加 replay/order/schema 失败测试。
- Verification: `py -3 -m pytest tests/test_session_turn_journal.py tests/test_session_codex_transcript_projection.py tests/test_session_service.py -q`。
- Review Gate: commentary/reasoning 不进入 final answer history，opaque replay 不进入 journal DTO。
- Risk: 新旧 writer 双写形成第二 canonical owner，或 reconnect 重复 final item。

## Task 8: 切换 React 到 turnItems v2 所有权

- Goal: React 按 canonical item identity/revision 渲染 reasoning、commentary、tool 和 answer，最终回答只显示一次。
- Inputs: Task 1 projection prerequisite；Task 7 SessionTurnItem v2。
- Outputs: v2 SSE routing、active layer/revision consolidation、derived `codexTranscript`。
- Files: `web/src/api/types/chat.ts`、`web/src/routes/chatSessionStreamProtocol.ts`、`chatTurnProtocol.ts`、`chatActiveTurnLayer.ts`、`sessionAssistantDeltaScheduler.ts`、`chatStreamApplyController.ts`、conversation projection/transcript surfaces 及测试。
- Boundary: 不反向生成 provider history，不按文本去重，不改 backend schema。
- Reuse: 复用现有 SSE router、scheduler、apply controller、VUI/codex transcript projection。
- Dependencies: Task 1、Task 7。
- Criticality: critical, high risk。
- Development Mode: BDD_TDD。
- BDD/TDD Anchor: Given provisional revision 后收到 final/reclassified revision，When SSE replay/reconnect，Then 同 identity 替换且只显示一个 primary answer；Given commentary/tool/reasoning，Then 保持独立过程行；Given interrupted draft，Then 仍可见。先添加 AMD395 与 reconnect fixture。
- Verification: focused route/projection Vitest suites；`npm --prefix web run build`。
- Review Gate: `turnItems` 是唯一 authoritative source，`codexTranscript` 只能派生。
- Risk: active layer 与 journal projection 再次双写，或 revision 顺序错误导致闪烁/重复。

## Task 9: fallback、辅助调用、日志与运行时闭环

- Goal: 所有已知 model call surface 使用同一 resolver/registry，fallback 新建 invocation，日志能解释链路且保持有界。
- Inputs: Task 2 至 Task 8 完成并合并。
- Outputs: auxiliary-path audit/fixes、fallback reconstruction、item/terminal aggregate logs、Launcher runtime evidence。
- Files: `core/llm/client.py`、`core/llm/protocol_resolver.py`、`agent.py`、`core/research/agent_runner.py`、self-evolution/Git/config probe services、必要测试与 runtime-scene logging owner。
- Boundary: 不扩大 provider 列表，不启用 Anthropic/Gemini，不记录原始模型或工具数据。
- Reuse: 所有路径必须复用 `get_llm_client -> route -> registry -> adapter -> outcome`。
- Dependencies: Task 8。
- Criticality: critical, high risk。
- Development Mode: BDD_TDD。
- BDD/TDD Anchor: Given route/provider failure，When fallback，Then 创建 fresh route/adapter/invocation/runtime endpoint；Given auxiliary call，Then 经过同一 registry；Given delta flood，Then runtime log 只在 item/terminal 决策聚合。先添加 fallback/aux/log bound 测试。
- Verification: backend focused suites、frontend focused suites、`npm --prefix web run build`；Launcher refresh 后执行 Chat/Responses stream/non-stream、tool continuation、model switch、fallback、cancel、reconnect 和 auxiliary smoke matrix。
- Review Gate: runtime-scene evidence必须能按 invocation 解释 continued/tool/final/failed，且没有 raw payload。
- Risk: 辅助路径保留旧协议分支、fallback 复用 stale route，或日志量失控。

## 拆分自审

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 覆盖方案 | PASS | 路由、semantic IR、Responses、Chat、Agent、Journal/DTO、React、aux/runtime 均有唯一任务 |
| 依赖清晰 | PASS | 共享 client/stream、Agent、DTO/projection 均串行，Task 1 明确为 Task 8 前置 |
| 粒度合适 | PASS | 每个任务只有一个可审阅产物，测试随所属行为进入同一任务 |
| 验证可行 | PASS | 每个 critical task 有 Given/When/Then、先失败测试和聚焦命令 |
| 保护边界 | PASS | 每张任务卡列出 owner surface、禁止触碰面与回归风险 |
| 复用边界 | PASS | Hermes 仅 ADAPT 路由/协议模式，现有 Vibelution owners 保持主导 |

## Workflow Ledger

- Current Stage: TASK_SPLITTING
- Split Decision: SPLIT
- Task Graph: Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5 -> Task 6 -> Task 7 -> Task 8 -> Task 9
- Current Task: Task 1, BDD_TDD
- Decisions: initial delivery only Chat Completions + Responses; native Anthropic/Gemini routed to separate planning; shared hot files serialized
- Claim Evidence: current active claims cover only Logs route and Challenge Cup design, with no overlap at split time
- Validation Evidence: task-graph structural review only; no implementation validation command run
- Unresolved Risks: claims must be rechecked immediately before each task; Task 4/5 and Task 7/8 cannot overlap
- Recommended Next Stage: `ccdawn-bdd-tdd-development` for Task 1
- Route Out: Task 1 BDD_TDD development; return to planning if provider transport scope expands
- Stop Condition: claim overlap, assistant consolidation already implemented differently, route/interface ambiguity, missing failing anchor, or request to enable Anthropic/Gemini

下一步建议: 为 Task 1 创建独立 worktree 和 claim，按既有 assistant-message consolidation 计划先写失败测试，再做最小身份合并修复。
