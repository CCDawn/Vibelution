# 对话 Agent 剩余语义路由收口实施计划

**Date:** 2026-07-18
**Design:** `docs/superpowers/specs/2026-07-18-dialogue-agent-semantic-autonomy-completion-design.md`
**Mode:** `COMPACT_PLAN`
**Risk:** HIGH_RISK — Agent tool routing / delegation behavior

## 目标与范围

收口已合并自治改造的两个残留语义控制器：读取治理提前返回和通用对话自动委派；同时把工具结果双通道从“投影过滤”补齐为真实的 execution sidecar。

不改 Team workflow、provider 和前端；不引入新的 route state machine 或外部 planner。

## 推荐路径

### 1. 先锁定 RED 契约

- `tests/test_tool_executor.py`：预先记录的重复 read range 不得阻止底层 `read_file_tool` 执行；可断言 observation 已记录，但不含 suggestion/action。
- `tests/test_agent_protocol.py`：通用 dialogue 回合在首次模型 invocation 前不得调用 `spawn_agent_tool`；模型的正常工具调用和 final answer 流不变。
- `tests/test_tool_result.py`、`tests/test_tool_lifecycle.py`：同一个 `ToolExecutionFact` 分别产出 model projection 与 runtime metadata；metadata 不进入 ToolMessage/provider replay。
- 保留既有 Team 6 项保护契约。

### 2. 移除读取语义拦截

影响：`core/infrastructure/tool_executor.py`、`tools/Key_Tools.py`、`tools/shell_tools.py`、相关 tests。

- 删除 executor 在执行前调用 `_check_codex_style_reading_governance()` 的早退分支，以及只服务于其的 recommendation 文本。
- 继续保留 `record_read_range()` 作为 post-execution observation；需要时以 bounded telemetry 记录 duplicate count，不改变调用结果或工具可见性。
- 从 `read_file_tool`/`read_file` 文案与结果删除阅读导航；保留 file size、offset、range、remaining lines 和 truncation facts。

### 3. 移除通用对话自动委派

影响：`agent.py`、`core/orchestration/delegation_governor.py`、`core/infrastructure/tool_executor.py`、`tests/test_agent_protocol.py`。

- 删除每轮模型调用前的 `_maybe_delegate()` 调用、初始化/懒加载的 governor 注入及 generic `spawn_agent_tool` 内部短路路径。
- 将仍被 evolution lifecycle 使用的静态 goal helpers 迁至中性 lifecycle utility；不能以保留 governor 为理由继续保留目标分类/role inference。
- 保留 Team/operator 已拥有的显式子 Agent 路径；通用 dialogue 不产生替代性的自动委派。

### 4. 固化双通道类型边界

影响：`core/infrastructure/tool_result.py`、`core/orchestration/tool_lifecycle.py`、`agent.py` 的工具结果 observer、相关 tests。

- 引入/完成 `ToolExecutionFact`，使其不携带 legacy continuation/action 字段。
- 让 `ModelVisibleToolResult` 与 `RuntimeToolMetadata` 使用不同字段集合；model type 不保留空的 `continuation_hint` 成员。
- `ToolLifecycleBridge` 由同一个 execution fact 生成两条投影：ToolMessage 只接 model projection；runtime observer/telemetry 接 sidecar。
- legacy 文本过滤保留为 compatibility adapter，并以结构化工具结果迁移为删除条件；不把自然语言规则当成新的控制器。

## 实施顺序与依赖

单一 owner 串行执行：先 RED → 读取拦截 → 自动委派 → 双通道边界 → 回归。四步共享 `agent.py`、`tool_result.py` 和协议测试，不能并行拆分。

## 验证与成功证据

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_tool_result.py `
  tests\test_tool_lifecycle.py `
  tests\test_agent_protocol.py `
  tests\test_tool_executor.py `
  tests\test_agent_session_runtime.py `
  tests\test_team_workflow_orchestration_service.py -q

.\.venv\Scripts\python.exe -m compileall -q `
  agent.py core\infrastructure\tool_result.py `
  core\infrastructure\tool_executor.py `
  core\orchestration\tool_lifecycle.py `
  core\orchestration\delegation_governor.py

git diff --check
```

Launcher refresh is required before runtime/release verification. Log only bounded counts/statuses at the tool-lifecycle boundary; do not log raw tool output or infer a model rationale.

## 失败处理与回滚

- 若 Team protected tests 失败，停止并修复 Team/domain projection；不得恢复 dialogue routing。
- 若通用 dialogue 需要显式子 Agent 能力，新增一个由模型调用、权限治理的 capability 需要独立设计；本轮不以自动 governor 替代。
- 若 dual projection 改造影响 provider replay，先回滚该类型收口，保留已经验证的 facts-only ToolMessage 与无自动路由行为。
