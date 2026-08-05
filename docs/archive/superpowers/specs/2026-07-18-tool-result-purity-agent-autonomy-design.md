# Tool Result Purity And Agent Autonomy Design

**Date:** 2026-07-18
**Status:** draft
**Owner:** tool-loop-autonomy
**Claim:** `claim-158845bdab42`（初稿，completed）；`claim-563cf29627fe`（全局工具结果契约修订）
**Scope:** 对话 Agent 的工具结果双通道、批次执行、模型自主续查、运行时安全护栏，以及代码图谱结果契约
**Supersedes:** none
**Implementation link:** pending
**Validation:** 以 `log_info/conversation_20260718_001249__chat__分析一下如何修复这个bug.jsonl` 的 33 次代码图谱调用作为主回归基线
**Close condition:** 用户批准设计，并形成可直接执行的实现计划；本 spec 不修改运行时代码

## 1. Decision

Vibelution 将把“下一步是否继续调用工具”的控制权从单个工具结果文本归还给模型。运行时不根据证据内容生成继续、换工具或总结规则。

```text
LLM TurnOutcome(tool_calls)
  -> pre-execution budget check
  -> ToolLifecycleBridge.execute_tools
  -> ToolExecutionFact
       -> ModelVisibleToolResult -> standard ToolMessage
       -> RuntimeToolMetadata -> accounting / diagnostics
  -> LLM independently decides:
       continue with any authorized tool
       change approach
       ask the user
       answer
```

工具结果只表达事实，不再包含“优先继续使用某工具”一类命令式提示。模型可见结果与运行时元数据使用两个独立通道；`TurnOutcome` 继续作为单次模型调用的 canonical 终态。运行时只执行权限、预算、协议完整性、用户中断和显式 terminal contract 等硬边界，不创建第二个规划器。

复用决策为 `ADAPT`：

- 参考 Pi Agent 的标准 ToolResult 与 runtime-only terminal hint 分离；
- 参考 OpenCode 的模型自主循环、权限、最大步数和重复调用护栏；
- 参考 Hermes 的标准 tool message、预算与可中断循环；
- 参考 TRAE 的模型可见思考/完成工具和外层 `max_steps`；
- 不引入外部 Agent 编排依赖，复用现有 `ToolLifecycleBridge`、`RoundStateController`、`TurnOutcomeController` 和 canonical tool result。

## 2. Observed Failure

主回归日志：

`log_info/conversation_20260718_001249__chat__分析一下如何修复这个bug.jsonl`

该单个 turn 包含：

| Fact | Observed value |
| --- | ---: |
| LLM responses | 8 |
| All tool calls | 36 |
| `code_symbol_tool` calls | 33 |
| Consecutive late batches | five batches of 5 tool calls |

后半段多次重复检查相同目标，包括：

- `ResponseSurfaceController.record_token_usage`；
- `ConversationLogger.log_token_usage`；
- `Agent._invoke_llm`；
- `core/orchestration/response_surface.py`；
- `tools/conversation_log_tools.py`。

模型不是在一次异常后无限重试同一个请求，而是在每轮收到多个“继续使用代码图谱”的模型可见提示后，继续生成一组新的代码图谱调用。根因是工具结果持续给模型施加同方向命令，不是模型缺少一套外部路由规则。

## 3. Confirmed Root Causes

### 3.1 Tool result contains an unconditional command

`core/infrastructure/tool_result.py::_extract_continuation_hint` 对所有 `code_context_graph` 结果无条件返回：

```text
优先继续使用 code_symbol_tool 的 explore/inspect/references/impact/affected_tests 模式做结构化补读。
```

该提示与以下事实无关：

- 目标是否已经解析；
- 当前结果是否完整；
- 是否存在下一页；
- 是否产生新证据；
- 工具是否失败；
- 当前批次是否已经包含足够证据。

`render_tool_result_for_model` 又把该字段写入每个模型可见的 `[Tool Result Facts]`。并行批次有五个结果时，模型会看到五次相同方向性指令。

该问题不只存在于代码图谱。当前同一提取和压缩路径还会把以下内容转换或复制为模型可见的下一步指令：

- 文件读取结果中的 `[阅读导航]` 和 `[续读]`；
- 搜索结果的“优先缩小搜索范围”；
- 资料收集结果的“继续调用 source_collection_context_tool”；
- `retryInstruction`、`evidenceInstruction` 和分页参数混合形成的 continuation 文本。

其中分页、重试能力和证据使用限制本身是合法事实，但不得以“调用哪个工具、下一步做什么”的命令形式进入每个 ToolMessage。

### 3.2 Current model-visible and orchestration facts share one envelope

`ToolResultFacts`、API payload 和 `render_tool_result_for_model` 当前共享 `continuation_hint`。这使以下不同职责进入同一个对象：

```text
工具执行事实
模型可读内容
UI 导航
证据去重元数据
运行时预算与诊断
```

只要该对象同时服务模型、UI 和编排器，就可能把内部控制信息重新投影回模型历史。需要显式拆分 model-visible result 与 orchestration-only metadata。

### 3.3 Current convergence state counts tool names, not evidence

`RoundStateController.note_response_tools` 把所有非 bookkeeping 工具视为 substantive：

```text
substantive tool call -> no_new_evidence_steps = 0
```

因此重复读取同一符号、同一文件或同一关系仍被视为新增证据。该状态可以用于诊断、预算统计和循环风险提示，但不得据此替模型选择下一工具或强制总结。

### 3.4 Code graph result does not expose completion facts

当前 `inspect` 结果缺少统一的：

```text
targetResolved
hasMore
nextCursor
evidenceDigest
```

模型只能从不完整文本猜测“目标是否已经找到、是否还有下一页”。应直接提供结构化完成事实，让高能力模型自行判断是否继续。

### 3.5 `inspect(file_path, symbol)` has an ambiguous target contract

`inspect_graph` 先处理 `file_path`，只有文件未命中时才处理 `symbol`。同时传入文件和符号时，符号可能被静默忽略，但结果仍为 `status=ok`。

这会让模型误以为已检查指定符号，实际只获得文件开头片段。

### 3.6 Snippets are bounded but pagination is not explicit

文件和符号 snippet 都限制为 900 字符。截断本身合理，但当前结果没有说明片段是否覆盖目标、是否还有可读取区间，以及下一步需要哪一个精确证据。模型只能通过再次切换 `inspect/search/references` 猜测。

## 4. Goals

1. 所有工具结果不再携带无条件的下一步命令，而不只是代码图谱。
2. 模型可见工具结果与运行时元数据使用两个独立通道。
3. 模型自主决定继续调查、换工具、询问用户或形成回答。
4. 运行时不得推断 `evidenceGap`、生成调查计划或根据内容强制总结。
5. 重复证据可以被识别和记录，但只作为诊断与循环风险信号。
6. 工具预算在执行前检查，不允许一个超预算并行批次先执行再止损。
7. 保留开放式 Agent 能力，不把对话强制改造成固定工作流。
8. 运行日志记录调用、证据新颖度、预算和硬阻止原因，不伪造模型的继续理由。

## 5. Non-goals

- 不替换 canonical `TurnOutcome` 或 LLM invocation chain。
- 不引入 LangGraph、Microsoft Agent Framework、Pydantic AI 或其他运行时依赖。
- 不在本阶段重写代码图谱索引器。
- 不解决 token usage 重复写入本身；该问题只是本回归日志的调查目标。
- 不以单纯降低 `max_iterations` 作为根治方案。
- 不要求普通写入型工具自动并行。
- 不改变 Agent 的工具授权边界。
- 不实现基于证据内容的路由状态机、规则表或隐藏工具策略。
- 不在模型回答后运行会重新开启工具链的 final-answer planner。

## 6. Source Of Truth

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh / invalidation |
| --- | --- | --- | --- | --- |
| 单次 LLM 调用终态 | `TurnOutcome` | canonical LLM invocation chain | Agent loop, journal, session projection | 每次 invocation 结束 |
| 工具原始执行事实 | `ToolExecutionFact` | `ToolLifecycleBridge` | model-visible projector、orchestration metadata projector、UI | 每个 tool call 完成 |
| 模型可见工具结果 | `ModelVisibleToolResult` -> `CanonicalToolResult` | tool result projector | ToolMessage、provider replay projection | 每个 tool call 完成 |
| 运行时工具元数据 | `RuntimeToolMetadata` | evidence projector | budget accounting、loop monitor、diagnostics | turn 结束清空 |
| 当前 turn 工具预算和证据历史 | `RoundStateController` | Agent runtime | pre-execution guard、diagnostics | turn 结束清空 |
| 代码图谱目标完成度 | code graph structured result | `core/code_context_graph/service.py` | model-visible projector、orchestration metadata projector | 每次图谱查询 |

`ModelVisibleToolResult` 不得包含 digest、novelty、预算、内部重复计数或任何下一步 action。运行时元数据不得被反向投影成模型指令。

## 7. Data Contracts

### 7.1 Two-channel result boundary

每次工具执行先把 executor raw result 规范化成一个中性 `ToolExecutionFact`，然后由两个单向 projector 分流：

```text
executor raw result
  -> ToolExecutionFact
       -> ModelVisibleToolResult
            -> CanonicalToolResult / ToolMessage / provider replay
       -> RuntimeToolMetadata
            -> BudgetGuard / LoopMonitor / diagnostics
```

`ToolExecutionFact` 复用并收敛现有 `ToolResultEnvelope` 的 transport、semantic、content、truncation、range 和 failure facts，但不再拥有 `continuation_hint`。它是进程内投影源，不把完整 raw result 持久化。

禁止路径：

```text
RuntimeToolMetadata -> provider replay payload
rendered ToolMessage -> runtime metadata reverse parsing
UI navigation text -> model-visible continuation instruction
runtime observation -> forced tool choice / forced synthesis
```

UI 可以同时展示两个通道的安全投影用于诊断，但不得把 UI 文案当作 canonical 控制状态。

### 7.2 ModelVisibleToolResult

```python
@dataclass(frozen=True)
class ModelVisibleToolResult:
    tool_name: str
    tool_call_id: str
    content: str
    transport_status: str
    semantic_status: str
    result_kind: str
    truncated: bool
    error_code: str
    error_summary: str
    target: dict[str, object]
    pagination: dict[str, object]
    provenance: dict[str, object]
```

允许模型看到：

| Category | Examples |
| --- | --- |
| 执行事实 | `transportStatus`、`semanticStatus`、`timedOut`、`errorCode` |
| 结果内容 | 有界文本、结构化记录、命中的文件或符号 |
| 完成度 | `targetResolved`、`truncated`、`complete` |
| 分页事实 | `hasMore`、opaque `nextCursor`、已返回数量 |
| 来源与使用边界 | `sourceId`、`evidenceQuality=preview_only`、`allowedUse=discovery_only` |

禁止模型看到：

| Category | Forbidden examples |
| --- | --- |
| 下一步工具命令 | “继续调用 X”“优先使用 Y”“设置 refresh=true 重试” |
| 内部控制 | 强制继续、强制换工具、强制总结、allowed/blocked tool delta |
| 内部收敛 | `evidenceDigest`、`novelty`、重复次数、预算余额 |
| provider 控制 | 强制 `tool_choice`、内部 fallback、replay bookkeeping |

证据限制应表达为结构化 provenance facts，而不是自由文本命令。例如：

```json
{
  "provenance": {
    "evidenceQuality": "preview_only",
    "allowedUse": "discovery_only",
    "supportsQuotation": false
  }
}
```

这保留“摘要不能当全文证据”的安全语义，同时避免把工具结果变成编排 prompt。

### 7.3 RuntimeToolMetadata

在 canonical execution fact 上投影结构化、非模型可见字段：

```python
@dataclass(frozen=True)
class RuntimeToolMetadata:
    tool_name: str
    tool_call_id: str
    semantic_status: str
    target_kind: str
    target_id: str
    target_resolved: bool | None
    has_more: bool | None
    next_cursor: str
    evidence_ids: tuple[str, ...]
    evidence_digest: str
    truncated: bool
    error_code: str
```

规则：

- `evidence_digest` 由稳定结构字段生成，不使用完整原始输出；
- 代码图谱优先使用 resolved file/symbol/relation IDs；
- 非结构化工具回退到经过规范化和截断的内容摘要 hash；
- digest 只用于同一 turn 的重复识别，不作为跨版本持久身份；
- 不记录 credentials、完整 prompt、完整文件内容或完整工具输出。

### 7.4 ToolBatchEvidenceObservation

```python
@dataclass(frozen=True)
class ToolBatchEvidenceObservation:
    batch_id: str
    call_count: int
    tool_names: tuple[str, ...]
    new_evidence_ids: tuple[str, ...]
    repeated_evidence_ids: tuple[str, ...]
    failed_call_ids: tuple[str, ...]
    unresolved_targets: tuple[str, ...]
    has_more_targets: tuple[str, ...]
    novelty: Literal["new", "partial", "duplicate", "none"]
```

一个并行批次只归约一次。该对象是观察记录，不包含 action、推荐工具、证据缺口或下一轮预算，也不能改变下一次模型调用。

### 7.5 Existing runtime guard facts

初始实现复用现有 `RoundStateController.max_iterations`、工具授权/可见性、取消信号、provider 协议校验和显式 lifecycle action。不得为了本设计再创建一个拥有 action 枚举、证据规则或工具选择权的 `ToolLoopGuard` 状态机。

运行时可以记录 `calls_used`、批次大小、精确重复次数、权限等待、取消和协议错误等事实；这些事实只回答“资源或协议是否仍允许执行”，不回答“下一步应该做什么”。

## 8. Agent Autonomy Boundary

模型收到标准 ToolMessage 后，自主决定：

- 是否已有足够证据；
- 是否继续使用同一工具；
- 是否使用其他已授权工具；
- 是否调整调查方向；
- 是否询问用户；
- 是否直接回答。

运行时不得：

- 根据 `novelty`、`hasMore`、`targetResolved` 或错误类型替模型生成下一步；
- 推断和持久化 `InvestigationIntent`、`evidenceGap` 或 `expectedEvidence`；
- 因认为证据足够而隐藏工具、设置 `tool_choice=none` 或强制总结；
- 因发现重复证据而强制换工具；
- 对模型最终回答运行会重新开启工具链的 planner/checker。

运行时只可以：

- 在执行前拒绝未授权、越界、超出硬预算或协议无效的调用；
- 响应用户取消、中断和显式权限决策；
- 执行工具声明的明确 terminal contract；
- 记录重复调用与重复证据，用于诊断、评估和后续模型/提示优化；
- 在达到硬上限时结束执行并暴露 typed incomplete/budget fact，不替模型编造完成结论。

## 9. Tool Availability And Provider Policy

下一次模型调用可见的工具集合只由稳定能力、用户授权、当前 Agent 模式和安全策略决定，不由上一批工具内容动态路由。

如果 provider 使用强制 `tool_choice`，工具批次完成后必须重置为 `auto`。除用户选择、固定 Agent 模式、权限、安全策略或显式 terminal contract 外，运行时不得动态隐藏工具或强制文本回答。

### 9.1 Conversation Agent 与 Team Agent 的状态机边界

对话 Agent 与团队 Agent 的状态机服务不同对象：

| Surface | 决策 owner | 适合显式状态机的内容 | 不应由状态机决定的内容 |
| --- | --- | --- | --- |
| 通用对话 Agent | 当前模型 | idle、invoking、executing tools、waiting permission、interrupted、completed 等协议与生命周期状态 | 下一步查什么、选哪个工具、证据是否足够、何时总结 |
| Team Agent / supervisor | 团队编排器或 task graph | queued、ready、claimed、running、blocked、review、handoff、done、failed 等任务和协作状态 | 替每个成员模型完成其领域推理 |

团队路由的对象是任务、角色、依赖、所有权和交接；对话 Agent 推理的对象是当前问题、证据和工具选择。前者需要确定性协调，后者需要保留模型自治。不得把团队 Agent 的 stage gate、角色切换、handoff 或 task routing 下沉成单个对话 Agent 的认知路线。

例外是客服流程、审批、KYC 等本质上要求确定步骤和合规迁移的系统。它们属于 workflow Agent，即使界面表现为对话，也不应作为通用高能力对话 Agent 的架构模板。

## 10. Global Tool Result And Code Graph Contract

### 10.1 Global mandatory result rules

所有工具遵守：

1. ToolMessage 只包含 `ModelVisibleToolResult`。
2. 不得出现命令式 `continuationHint`、`retryInstruction` 或工具选择建议。
3. 分页统一投影成 `hasMore + nextCursor + returnedCount`。
4. 重试统一投影成 `retryable + errorCode + retryState`，不指定下一步调用。
5. 证据使用限制统一投影成 provenance facts。
6. `RuntimeToolMetadata` 使用 sidecar/state channel，不进入 ToolMessage content 或 provider replay。
7. 工具可声明显式 terminal contract；除此之外是否结束 user turn 由模型或用户决定。

现有字段迁移：

| Current source | Replacement |
| --- | --- |
| `[阅读导航]` / `[续读]` | `pagination` 或 `rangeInfo` facts |
| 搜索“优先缩小范围” | 删除；保留命中数、截断和查询范围事实 |
| source collection “继续调用…” | opaque `nextCursor` 和 page counts |
| `retryInstruction` | `retryable`、`errorCode`、`retryState` |
| `evidenceInstruction` | structured `provenance` / `allowedUse` |
| `continuationHint` | model-facing contract 中删除 |

兼容迁移期间可以读取 legacy hint 并投影为结构化事实，但 legacy hint 必须在进入 `render_tool_result_for_model` 前被移除。确认无 API/UI consumer 后，再从 envelope 和 payload schema 删除该字段。

### 10.2 Explicit code graph target semantics

`inspect` 的目标规则改为：

- 仅 `file_path`：检查文件；
- 仅 `symbol/query`：检查符号；
- `file_path + symbol`：检查该文件内的指定符号，不得静默降级成文件检查；
- 符号不存在：返回 `status=error`、`error=symbol_not_found_in_file`；
- 每个成功结果都返回 `requestedTarget`、`resolvedTarget` 和 `targetResolved=true`。

### 10.3 Explicit code graph continuation facts

代码图谱结果增加：

```json
{
  "targetResolved": true,
  "hasMore": false,
  "nextCursor": null,
  "snippet": {
    "startLine": 2936,
    "endLine": 2958,
    "complete": true
  }
}
```

文件开头的 900 字符预览必须标记为 `complete=false`；它不能假装是指定行或符号证据。只有存在确定下一页时才设置 `hasMore=true` 和 `nextCursor`。

### 10.4 No imperative continuation hint

删除所有工具的模型可见 `continuationHint`，代码图谱不得例外。分页导航可以作为事实存在：

```json
{
  "hasMore": true,
  "nextCursor": "opaque-cursor"
}
```

是否使用该 cursor 由模型决定。相同规则也适用于文件读取、搜索和资料收集工具。

## 11. Budget Guard

预算检查发生在 `ToolLifecycleBridge.execute_tools` 之前。

初始保护契约：

- `agent.max_iterations` 继续作为 user turn 的硬循环预算；
- 工具授权、可见性、取消和 provider 协议校验继续在执行前生效；
- 相同 `tool_name + normalized args` 的精确重复调用计入 loop-risk 观察；是否升级为用户确认由独立安全阈值决定，不自动换工具或总结；
- evidence novelty 不作为执行许可条件；
- 首轮不增加未经测量的 `max_tool_calls_per_turn`、`max_tool_calls_per_batch` 或新 operator config；
- 硬预算只限制资源消耗，不评价模型调查策略；如果未来需要新增预算字段，必须先由正常日志分布证明阈值和兼容边界。

默认数值必须根据现有正常日志分布确定。本设计不预设一个未经测量的全局低上限；主回归的成功条件依赖语义收敛，而不是把 33 改成另一个任意常数。

## 12. Planned Impact Surface

| File / module | Planned change |
| --- | --- |
| `core/infrastructure/tool_result.py` | 将现有 envelope 收敛为中性 `ToolExecutionFact`；建立 model-visible / orchestration 双 projector；删除所有模型可见命令式 hint；提取结构化完成度、分页、provenance 和 evidence metadata |
| `core/orchestration/tool_lifecycle.py` | 分别回写模型结果和 orchestration sidecar；返回批次执行事实；不再由每个结果推动继续 |
| `core/orchestration/round_state.py` | 保存 turn-scoped digest、批次 novelty、预算和 loop-risk observation，不保存下一步 decision |
| `core/orchestration/turn_outcome.py` | 删除 `should_stop_for_convergence` 语义停机规则；保留 canonical outcome、失败、硬预算和显式 lifecycle terminal owner |
| `core/llm/invocation.py` | 工具批次后恢复 provider `tool_choice=auto`；阻止 orchestration metadata 进入 provider replay |
| `core/code_context_graph/service.py` | 补齐目标语义、完成度、cursor 和 snippet coverage |
| `core/infrastructure/tool_executor.py` | 停止生成 `decide_next_tools`、recommended/avoid tools 和 scope-freeze 路由；保留执行、授权和事实型观测 |
| `core/infrastructure/agent_session.py` | 推荐/避免工具、收束状态不再进入对话模型上下文；旧字段先保留为空值兼容 UI/API |
| `core/orchestration/delegation_governor.py` | 委派结果作为证据返回主模型，不因“证据足够”直接结束 user turn |
| `agent.py` | 删除对 `should_stop_for_convergence` 和 delegation `break_round` 的对话链执行权；不增加路由 reducer |

预计测试：

```text
tests/test_tool_result.py
tests/test_python_intelligence_tools.py
tests/test_agent_protocol.py
tests/test_llm_canonical_invocation.py
tests/test_tool_executor.py
tests/test_source_collection_tools.py
```

## 13. Observability

新增 bounded runtime-scene events：

```text
tool.batch.preflight_checked
tool.batch.evidence_observed
tool.batch.loop_risk_observed
```

允许字段：

```text
sessionId
turnId
invocationId
iteration
batchId
callCount
toolNameCounts
newEvidenceCount
repeatedEvidenceCount
unresolvedTargetCount
novelty
reasonCode
remainingToolBudget
```

禁止字段：

```text
full prompt
full tool output
full file content
credentials
raw provider payload
raw evidence text
```

日志必须能够重建工具调用和硬护栏行为，但不得声称知道模型“为什么继续”。模型理由只来自其原生 reasoning/trace 能力，不能由 runtime reducer 代写。

## 14. Rollout And Rollback

阶段：

1. 先停止所有 legacy continuation hint 进入对话模型消息；团队工作流原始 payload 与阶段状态保持不变。
2. 删除对话主循环的 semantic convergence stop 和推荐/避免工具注入；保留现有硬边界。
3. 记录批次大小、精确重复和 evidence novelty，用正常会话建立分布基线，但不改变模型行为。
4. 确认通用 UI/API 无 consumer 后，从通用 tool-result envelope 和 payload schema 删除 legacy hint 字段；团队域字段按其 own contract 单独治理。

回滚：

- 回滚对话模型投影和 semantic-control cutover，但不恢复代码图谱的无条件命令式 hint；
- canonical tool result、TurnOutcome 和 journal 不回滚；
- 不恢复任何模型可见的命令式 continuation hint；
- 如果自治 cutover 暴露协议或权限问题，只修复对应硬边界；不得用证据路由状态机补偿。

## 15. Verification Matrix

| Case | Expected result |
| --- | --- |
| 任意工具返回命令式 legacy hint | hint 不进入 ToolMessage；可推导的分页、重试、provenance facts 仍保留 |
| ToolMessage / provider replay | 不包含 digest、novelty、预算、runtime action 或动态工具可见性 |
| 文件读取 `[阅读导航]` / `[续读]` | 转成 range/pagination facts，不作为行动命令 |
| source collection 有下一页 | 返回 opaque cursor 和 page counts，不返回“继续调用工具” |
| evidence preview 不能用于引用 | 返回 structured provenance，保留安全边界但不携带工具命令 |
| 精确 symbol 命中且 `hasMore=false` | 模型看到完成事实；工具集合保持不变，模型自行决定回答或继续 |
| 同一 evidence digest 再次出现 | 记录为重复证据；不自动换工具、隐藏工具或强制总结 |
| `file_path + symbol` | 解析文件内 symbol；不得返回文件开头作为 symbol 成功 |
| `target_not_indexed` 且索引不需要刷新 | 只返回 typed error facts；不附带下一工具建议 |
| `hasMore=true` | 返回 cursor 和 completion facts；模型自主决定是否续读 |
| 模型连续选择不同调查工具 | 只要授权和预算允许，运行时不根据证据策略阻止 |
| 并行批次超过剩余预算 | 执行前整批阻止；无部分副作用 |
| terminal tool / final answer | 不额外调用一轮模型 |
| 强制 tool choice 的 provider | 工具结果后重置为 `auto`，不由 runtime 强制进入总结轮 |
| 模型直接形成最终回答 | 不运行 final-answer planner，不重新开放工具链 |
| 33-call 主回归 fixture | 删除命令式 hints 后不再由结果文本重复诱导代码图谱调用 |
| 正常多文件调查 | 在权限和预算内保持完整自主工具能力 |

主回归验收不能只断言“少于 33 次”。它必须同时证明：

1. 最终回答仍包含修复问题所需的关键证据；
2. 重复 evidence IDs 被识别；
3. ToolMessage 中不存在继续、换工具或总结命令；
4. 没有 runtime 组件根据 evidence novelty 替模型决定下一步。

## 16. Implementation Sequence

模式：`COMPACT_PLAN`，一个 owner 串行实施，不拆独立任务图。实现模式为 `BDD_TDD`，先用主回归和边界 fixture 固化失败行为。

1. 先增加全局结果边界失败测试和 33-call 归约 fixture。
2. 在 `tool_result.py` 建立双 projector，阻止所有 legacy hint 进入模型消息，并保留结构化分页、重试和 provenance facts。
3. 在 `ToolLifecycleBridge` / Agent loop 接入 runtime sidecar，不增加批次路由或新 guard 状态机。
4. 删除 `should_stop_for_convergence`、delegation `break_round` 和 recommended/avoid tool 对对话链的执行权；兼容字段先保留为空。
5. 扩展 `RoundStateController`，使 evidence novelty 可被真实观察，不再由工具名称推断，但不产生行动决策。
6. 修正 code graph 的组合目标和 snippet completion contract。
7. 验证工具批次后 provider `tool_choice` 恢复为 `auto`，且 orchestration metadata 不进入 provider replay。
8. 先运行正常会话和回归 fixture 观察调用分布，再做 Launcher runtime acceptance；不新增 rollout config。

共享 `agent.py`、LLM invocation 和 config surface 的修改必须先复查 active claim。实现轮需要独立 task worktree 和新的窄 claim。

## 17. Rejected Alternatives

- **只增加最大调用次数：** 只能止损，不能解释已有证据是否足够，也不能消除工具结果对模型的重复诱导。
- **把通用 continuation hint 改成条件 hint：** 仍由单个工具拥有链路规划权，并行批次仍可能产生多个互相竞争的方向信号。
- **只在代码图谱删除 hint：** 文件读取、搜索和资料收集仍会通过同一结果封装路径重新引入命令式控制信息。
- **把所有 evidence instruction 直接删除：** 会丢失“preview 不能作为引用”等必要来源边界；正确做法是投影成 structured provenance facts。
- **实现 `RouteDecision` / 条件路由状态机：** 会把高能力模型降级为规则执行器，并在 runtime 中创建第二个规划 owner。
- **根据 evidence novelty 动态隐藏工具：** 重复证据不等于工具无用，静态规则无法理解模型正在验证、交叉检查还是探索替代假设。
- **运行 final-answer check 并自动 replan：** 会在模型已经决定回答后重新开启隐藏循环，破坏清晰的终止所有权。
- **完全不保留 runtime guard：** 模型自主不等于无限资源或绕过权限；预算、授权、协议和用户取消仍必须由宿主执行。

## 18. Completion Criteria

设计实现完成的条件：

- 任意模型可见工具结果中都不存在命令式继续、重试或工具选择指令；
- `ModelVisibleToolResult` 与 `RuntimeToolMetadata` 有独立 projector，且后者不进入 ToolMessage 或 provider replay；
- 分页、重试能力和 evidence policy 仍以结构化事实保留；
- 不存在 `RouteDecision`、`InvestigationIntent`、证据路由规则或 final-answer replanner；
- `no_new_evidence_steps` 由真实 evidence novelty 驱动，但只用于观察和风险信号；
- 模型在稳定授权工具集合内自主继续、切换、询问或回答；
- runtime 只执行预算、权限、协议、用户取消和显式 terminal contract；
- 主回归不再形成 33 次代码图谱调用；
- 正常并行只读调查仍可完成；
- runtime scene 能重建工具序列、证据重复、预算和硬护栏事件，但不伪造模型理由；
- focused tests、相关 Agent protocol tests 和 canonical invocation tests 通过；
- Launcher 刷新后的一个普通短对话和一个代码调查对话完成 runtime acceptance；
- version impact 评估为 patch，除非新增配置被认定为稳定公共配置 API。
