# Dialogue Agent Tool Autonomy Implementation Plan

**Date:** 2026-07-18
**Status:** ready for implementation
**Spec:** `docs/superpowers/specs/2026-07-18-tool-result-purity-agent-autonomy-design.md`
**Mode:** `COMPACT_PLAN`
**Primary owner:** Agent runtime core
**Version impact:** patch
**Runtime refresh:** required before live acceptance

## 1. BRT Intent Lock

### Target

修复通用对话 Agent 被工具结果提示、证据收敛规则和推荐/避免工具状态共同驱动，进而重复调用代码图谱的问题。

### Desired behavior

- 工具只向对话模型返回执行结果、完成度、分页、错误和来源边界等事实。
- 对话模型自主决定继续调查、改用其他工具、询问用户或回答。
- 运行时只拥有协议、权限、工具可见性、取消、最大迭代和显式 lifecycle terminal 等硬边界。
- Team Agent 的任务、阶段、角色、依赖和 handoff 路由保留在团队编排域。

### Out of scope

- 不重写 Team workflow、Challenge Cup source-collection stage 状态机或其用户可见重试说明。
- 不新增 `RouteDecision`、`InvestigationIntent`、`ToolLoopGuard` action enum 或 evidence routing。
- 不新增未经日志分布证明的 per-turn/per-batch 工具调用配置。
- 不删除历史 API/UI 兼容字段；先停止其进入对话模型，再单独治理废弃字段。
- 不修改模型 provider、credentials、journal、SessionTurnItem 或前端布局。

### Success evidence

1. 任意通用 ToolMessage 不含继续、换工具、重试方式或总结命令。
2. 对话主循环不再依据 `no_new_evidence_steps`、`scope_frozen`、`feedback_loop_ready` 或 `recommended_tools` 提前结束或选择工具。
3. 委派证据返回主模型后，由主模型决定是否回答；runtime 不因“证据足够”结束 user turn。
4. `file_path + symbol` 精确检查不会静默退化成文件预览。
5. 现有权限、取消、协议错误、`max_iterations` 和显式 `turn_complete` 行为保持。
6. Team workflow 原始 `continuationHint` / `retryInstruction` 数据与对应测试不受通用对话投影改造影响。

## 2. Architecture

```text
Team workflow raw result
  -> Team task/stage orchestrator
       -> task state / retry / handoff

Tool executor raw result
  -> ToolExecutionFact
       -> ModelVisibleToolResult
            -> CanonicalToolResult
            -> ToolMessage
            -> provider replay
       -> RuntimeToolMetadata
            -> bounded logs
            -> UI/API compatibility facts
            -> observation only

TurnOutcome(tool_calls)
  -> authorization / visibility / cancellation / protocol checks
  -> execute tools
  -> factual ToolMessages
  -> model independently chooses the next action
```

### Ownership boundary

| Fact or decision | Canonical owner |
| --- | --- |
| 下一步调查、工具选择、证据充分性、回答时机 | 当前 dialogue model |
| 单次 invocation 是 tool calls、final answer、failed、cancelled | canonical `TurnOutcome` |
| 工具执行和结果绑定 | `ToolLifecycleBridge` |
| 工具授权与可见性 | existing tool authorization / visibility policy |
| user turn 最大迭代 | `RoundStateController.max_iterations` |
| 用户取消、provider 协议失败 | existing runtime lifecycle |
| 演化事务显式完成 | tool lifecycle `turn_complete` contract |
| Team task 的 queued/claimed/blocked/review/handoff/done | Team workflow orchestrator |

## 3. Current Evidence

| Current behavior | Evidence | Required change |
| --- | --- | --- |
| 代码图谱结果无条件推荐继续调用代码图谱 | `core/infrastructure/tool_result.py::_extract_continuation_hint` | 删除对话投影中的命令；不改成条件命令 |
| 文件读取、搜索、source collection compaction 会把 continuation 写进 content | `core/infrastructure/tool_result.py` compaction helpers | 只投影范围、数量、`hasMore`、cursor/offset 和 provenance facts |
| Tool lifecycle 把同一 facts 对象直接渲染进 ToolMessage | `core/orchestration/tool_lifecycle.py::handle_tool_result` | 使用独立 model-visible projector |
| 对话主循环两次调用 semantic convergence stop | `agent.py` 中 delegation 后和工具批次后 | 删除这两个执行闸门 |
| `TurnOutcomeController` 根据 scope/evidence/tool counts 强制收束 | `core/orchestration/turn_outcome.py::should_stop_for_convergence` | 删除 semantic stop；保留协议与硬 lifecycle |
| ToolExecutor 计算 recommended/avoid tools 并记录偏离 | `core/infrastructure/tool_executor.py` | 停止生成、注入和执行工具路径建议 |
| AgentSession 把“准备停止/范围冻结/推荐路径”写回模型上下文 | `core/infrastructure/agent_session.py` | 不再进入 dialogue model context；兼容字段暂留为空 |
| 有用委派可直接 `break_round` | `core/orchestration/delegation_governor.py` | 委派只返回证据，主模型继续裁决 |
| `inspect(file_path, symbol)` 优先命中文件并忽略 symbol | `core/code_context_graph/service.py::inspect_graph` | 建立精确组合目标契约 |

## 4. Planned Impact Surface

### Critical path

| File | Planned responsibility |
| --- | --- |
| `core/infrastructure/tool_result.py` | 中性执行事实、模型投影、runtime/API 投影；移除模型可见命令式 hints |
| `core/orchestration/tool_lifecycle.py` | 只把 `ModelVisibleToolResult` 绑定到 canonical result 和 ToolMessage |
| `core/orchestration/turn_outcome.py` | 删除 semantic convergence stop，保留 canonical outcome、失败和 lifecycle terminal |
| `agent.py` | 删除 semantic stop 和 delegation `break_round` 的执行权 |
| `core/infrastructure/tool_executor.py` | 停止 `decide_next_tools`、recommended/avoid tools 和 tool-deviation 路由 |
| `core/infrastructure/agent_session.py` | 不再向 dialogue prompt 注入收束状态和工具路径 |
| `core/orchestration/delegation_governor.py` | 将委派结果降为主模型证据，不直接结束 user turn |
| `core/prompt_manager/prompt_manager.py` | prompt mode 不再依赖 `scope_frozen` / `convergence_state` 选择执行或停止语义 |
| `core/code_context_graph/service.py` | 精确目标、完成度、snippet coverage 和 typed error facts |
| `tools/python_intelligence_tools.py` | 保持 tool schema 与 code graph facts 一致 |

### Tests

| Test file | Contract |
| --- | --- |
| `tests/test_tool_result.py` | 双投影、命令清除、分页/provenance 保留 |
| `tests/test_tool_lifecycle.py` | canonical ToolResult 和 ToolMessage 只含模型事实 |
| `tests/test_agent_protocol.py` | 模型自治、硬边界保留、semantic stop 移除 |
| `tests/test_tool_executor.py` | 执行后不生成推荐/避免工具或 scope 路由 |
| `tests/test_agent_session_runtime.py` | dialogue context 不含准备停止、推荐路径或避免工具 |
| `tests/test_python_intelligence_tools.py` | code graph 精确目标与完成事实 |
| `tests/test_team_workflow_orchestration_service.py` | Team workflow 原始阶段/重试契约不回归 |

### Protected surfaces

- `core/web/services/team_workflow_orchestration_service.py`
- `core/web/services/team_workflow/`
- `web/src/routes/teams/source-collection/`
- provider protocol and replay modules
- operator configuration
- project-memory files until verified implementation closeout

## 5. Implementation Sequence

同一 owner 串行实施。各阶段共享 `tool_result.py`、`agent.py` 和 Agent session 状态，拆成并行任务会增加接口漂移和冲突，不建立 Team-style task graph。

### Phase 0 — Baseline and RED contracts

1. 从 `log_info/conversation_20260718_001249__chat__分析一下如何修复这个bug.jsonl` 提取一个脱敏 fixture，只保留：
   - invocation/batch 顺序；
   - tool name、mode、规范化 target；
   - result kind、status、`hasMore`；
   - 是否出现命令式 hint；
   - 不保留完整 prompt、文件内容或工具输出。
2. 在 `tests/test_tool_result.py` 增加失败测试：
   - code graph、file read、search、source collection 的 model projection 不含 `continuationHint`、`retryInstruction`、`继续调用`、`优先使用`；
   - pagination、range、typed error、provenance 仍存在；
   - source collection raw Team payload 仍保留其 domain fields。
3. 在 `tests/test_agent_protocol.py` 增加结构与行为测试：
   - dialogue loop 不调用 `should_stop_for_convergence`；
   - `no_new_evidence_steps` 增加不会直接 break；
   - final answer、failed/cancelled outcome、`max_iterations` 和 `turn_complete` 仍正确终止。
4. 在 `tests/test_tool_executor.py` / `tests/test_agent_session_runtime.py` 增加失败测试：
   - 工具执行后不会生成 recommended/avoid tool policy；
   - dialogue runtime context 不含工具路径或“准备停止”。

Stop condition: fixture 无法脱敏到不包含 prompt/源码时，不保存 fixture，改用手工最小合成 contract。

### Phase 1 — Split tool result projection

1. 在 `core/infrastructure/tool_result.py` 建立：

```python
@dataclass(frozen=True)
class ToolExecutionFact:
    content: str
    result_kind: str
    transport_status: str
    semantic_status: str
    truncated: bool
    original_length: int
    range_info: dict[str, object]
    pagination: dict[str, object]
    provenance: dict[str, object]
    error: dict[str, object]


@dataclass(frozen=True)
class ModelVisibleToolResult:
    tool_name: str
    content: str
    result_kind: str
    transport_status: str
    semantic_status: str
    truncated: bool
    range_info: dict[str, object]
    pagination: dict[str, object]
    provenance: dict[str, object]
    error: dict[str, object]


@dataclass(frozen=True)
class RuntimeToolMetadata:
    tool_name: str
    result_kind: str
    semantic_status: str
    original_length: int
    legacy_hint_stripped: bool
```

2. `package_tool_result()` 暂时保留兼容入口，但内部委托给 neutral normalization；旧 `ToolResultEnvelope` 可保留 alias 一个迁移周期。
3. compaction helpers 不再把以下字段写进 model content：
   - `continuationHint`
   - `recordContinuationHint`
   - `retryInstruction`
   - `nextAction`
   - `instructions`
   - `guidance`
4. 把合法语义转换为事实：
   - 阅读导航 → `rangeInfo` / pagination；
   - 重试能力 → `retryable`、`errorCode`、`retryState`；
   - preview 使用限制 → `provenance.allowedUse=discovery_only`；
   - source collection 页信息 → page counts、offsets 和 `hasMore`。
5. `render_tool_result_for_model()` 只接受 `ModelVisibleToolResult`。
6. `tool_result_facts_payload()` 继续服务 API/runtime compatibility，但不得被 `ToolLifecycleBridge` 当作模型投影。
7. `ToolLifecycleBridge.handle_tool_result()`：
   - canonical output 与 ToolMessage 使用 model-visible projection；
   - runtime scene 使用 metadata projection；
   - 不从渲染文本反向提取状态。

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_tool_result.py tests\test_tool_lifecycle.py -q
```

Expected: projection contracts pass；Team raw payload fields remain unchanged。

### Phase 2 — Remove semantic routing authority from dialogue runtime

1. 删除 `TurnOutcomeController.should_stop_for_convergence()` 及 `agent.py` 两个调用点。
2. 保留：
   - `decide_llm_iteration()`；
   - `should_stop_after_llm_failure()`；
   - `handle_lifecycle_action()`；
   - `finalize_round()` 对 `max_iterations` incomplete 的处理。
3. `RoundStateController.no_new_evidence_steps`、tool-only counts 暂时只作为 telemetry；不得触发 break、工具屏蔽或强制总结。
4. `ToolExecutor`：
   - 删除 runtime 对 `decide_next_tools()` 的调用；
   - 停止 `set_tool_decision()` 和 `_track_tool_decision_alignment()`；
   - 保留 read range、symbol、search、validation、mutation 和 cancellation 事实记录。
5. `AgentSession.build_runtime_state_context()` 不再向 dialogue model 输出：
   - `准备停止` / `范围已冻结`；
   - 推荐路径；
   - 推荐工具 / 避免工具；
   - tool deviation。
6. `PromptManager._infer_prompt_mode()` 不再从 `scope_frozen` / `convergence_state` 推断 execute/stop；只使用显式事务、修改、验证、委派或用户任务事实决定需要的上下文 section。
7. `DelegationGovernor`：
   - 有用委派结果继续写成 bounded evidence message；
   - `break_round=False`；
   - 不调用 `note_scope_completion()`；
   - Team workflow 自己的 task completion 不受影响。
8. `tool_recommender.py`、`reading_strategy.py`、`tool_intents.py` 暂不删除；本轮先证明 dialogue runtime 无 consumer。后续 cleanup 再删除 dead modules、UI labels 和专属测试。

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agent_protocol.py tests\test_tool_executor.py tests\test_agent_session_runtime.py tests\test_prompt_manager.py -q
```

Expected: dialogue model owns semantic continuation；hard lifecycle behavior remains。

### Phase 3 — Make code graph results factual and unambiguous

1. `inspect(file_path, symbol)` 必须只在该文件内解析 symbol。
2. 未命中返回：

```json
{
  "status": "error",
  "error": "symbol_not_found_in_file",
  "requestedTarget": {"filePath": "...", "symbol": "..."},
  "targetResolved": false
}
```

3. 成功结果提供：
   - `requestedTarget`
   - `resolvedTarget`
   - `targetResolved`
   - `returnedCount`
   - `totalCount`
   - `hasMore`
   - snippet `startLine` / `endLine` / `complete`
4. 文件头部预览必须标记 `complete=false`，不得表示指定 symbol 已被检查。
5. `target_not_indexed` 返回 index freshness、`retryable` 和 `refreshAvailable` facts，不返回“请调用 index/refresh”命令。
6. 首轮不引入复杂 opaque cursor 协议。只有当前模式已经能提供稳定下一页时才返回 offset/cursor；否则返回 `hasMore=false` 或要求调用方收窄查询，不伪造不可执行分页。

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_python_intelligence_tools.py tests\test_tool_executor.py -q
```

Expected: exact target and completion facts are deterministic；无工具选择文本。

### Phase 4 — Integration, compatibility, and runtime acceptance

1. 运行 focused suite：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_tool_result.py `
  tests\test_tool_lifecycle.py `
  tests\test_agent_protocol.py `
  tests\test_tool_executor.py `
  tests\test_agent_session_runtime.py `
  tests\test_prompt_manager.py `
  tests\test_python_intelligence_tools.py `
  tests\test_team_workflow_orchestration_service.py -q
```

2. 运行语法和 diff gate：

```powershell
.\.venv\Scripts\python.exe -m py_compile `
  core\infrastructure\tool_result.py `
  core\orchestration\tool_lifecycle.py `
  core\orchestration\turn_outcome.py `
  core\infrastructure\tool_executor.py `
  core\infrastructure\agent_session.py `
  core\orchestration\delegation_governor.py `
  core\prompt_manager\prompt_manager.py `
  core\code_context_graph\service.py `
  tools\python_intelligence_tools.py `
  agent.py

git diff --check
```

3. Runtime scenes 只增加 bounded facts：
   - tool name；
   - result kind；
   - semantic status；
   - truncated；
   - `legacyHintStripped`；
   - batch call count；
   - exact repeat count。

不得记录 full prompt、full result、源码、credentials 或推断出来的“模型继续原因”。

4. Launcher 刷新后验证：
   - 普通短问答不调用工具；
   - 一次文件读取后模型能直接回答；
   - 一次多文件调查允许模型自主继续；
   - code graph 精确 symbol 调查不会被无条件 hint 诱导；
   - Team source-collection stage 仍能按自己的 task state 完成。

5. 主回归不是只看“少于 33 次”，还要证明：
   - ToolMessage 没有命令式 hint；
   - 没有 semantic runtime break；
   - 最终回答保留关键证据；
   - 停止来自模型 final answer、用户取消、硬预算或显式 terminal contract。

## 6. Rollback

实施顺序本身就是回滚边界：

1. projection split；
2. dialogue semantic-control cutover；
3. code graph contract；
4. diagnostics。

如果 Phase 2 产生回归，可只回滚 semantic-control cutover，保留纯净 ToolMessage 和 code graph 事实。不得恢复代码图谱无条件 continuation hint。

Team workflow regression 必须通过恢复其 domain projection 解决，不能把 Team routing instruction 重新注入通用 dialogue ToolMessage。

## 7. Stop Conditions

遇到以下任一情况停止实施并报告，不扩大范围：

1. active claim 覆盖 critical-path 文件。
2. Team workflow 只有依赖通用 ToolMessage 命令才能推进，且没有自己的 stage/task state owner。
3. 去除 semantic stop 会绕过权限、用户取消、provider protocol 或显式 transaction close。
4. code graph 分页需要持久 cursor store 或公共 API 迁移。
5. 需要修改 provider、credentials、journal、Session DTO 或前端才能完成核心契约。
6. Launcher active-work guard 阻止刷新。

## 8. Deferred Cleanup

核心行为稳定后再单独审查：

- 删除无 runtime consumer 的 `tool_recommender.py`；
- 删除仅用于推荐路径的 `reading_strategy.py` / `tool_intents.py`；
- 移除 `AgentSession`、CLI UI 和 API type 中的空 compatibility 字段；
- 根据真实日志决定是否需要独立工具调用资源预算；
- 将 Team task routing contract 单独整理为 team orchestration spec。

这些项目不阻塞本轮模型自治修复。

## 9. Completion Contract

- spec 与 plan 不含 dialogue semantic route state machine。
- ToolMessage 与 provider replay 只有 factual model projection。
- Team task routing 与 dialogue tool result projection 不混用。
- canonical `TurnOutcome` 仍是 invocation 终态 owner。
- 现有 hard lifecycle gates 全部有回归测试。
- focused suite、syntax、diff check 和 Launcher runtime acceptance 有新鲜证据。
- version impact 记录为 patch；不从任务分支修改版本文件。
