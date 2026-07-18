# 对话 Agent 剩余语义路由收口设计

**Date:** 2026-07-18
**Status:** ready for implementation
**Supersedes:** 补充 `2026-07-18-tool-result-purity-agent-autonomy-design.md` 的未完成边界

## 1. 决策

通用对话 Agent 的下一步认知动作完全由模型决定。运行时不得依据已读范围、重复证据、用户目标分类、迭代次数或委派历史，抢先阻止一次合法工具调用、自动派发子 Agent，或把工作转向某条预设路线。

运行时仍拥有且只拥有以下硬边界：工具授权/可见性、参数 schema、文件大小与输出资源上限、取消、provider 协议、`max_iterations`，以及工具声明的显式 terminal lifecycle contract。

## 2. 所有权边界

| 决策或事实 | Owner |
| --- | --- |
| 是否再次读取同一区间、换工具、继续调查、提问或回答 | 当前 dialogue model |
| 文件大小、路径/权限、参数格式、取消、预算、协议完整性 | runtime/tool contract |
| 通用对话中的子 Agent 自动派发 | 不存在 |
| Team 的角色、任务、依赖、handoff 和自动派发 | Team workflow / Team Agent domain |
| 显式 Team/操作员工作流发起的子 Agent | Team/operator orchestration |

本轮不把 `spawn_agent_tool` 暴露为通用 dialogue model 的普通工具，也不以新的“delegate recommendation”替代旧 governor。用户或 Team 明确进入的团队工作流继续使用既有 Team 编排入口。

## 3. 数据流

```text
tool raw result
  -> ToolExecutionFact (neutral, process-local)
       -> ModelVisibleToolResult -> ToolMessage / provider replay
       -> RuntimeToolMetadata -> bounded telemetry / UI diagnostics

dialogue model tool call
  -> authorization + schema + resource + cancellation + protocol checks
  -> execute exactly the authorized call
  -> factual result
  -> next model invocation
```

`ModelVisibleToolResult` 不含 `continuation_hint`、`retryInstruction`、`replacement`、`recovery`、推荐工具或任何运行时 action。`RuntimeToolMetadata` 不得序列化到 ToolMessage 或 provider replay。

在兼容迁移期，legacy 非结构化结果可经投影适配；适配器只作为边界兜底。工具源码不得再主动生成“下一步调用/阅读导航/重试方式”文本。后续以 typed fields 取代依赖自然语言正则的过滤。

## 4. 读取与委派

### 读取

- `read_file_tool` 保留分页、offset、显示区间、剩余行数和文件大小等事实。
- 删除 `ToolExecutor._check_codex_style_reading_governance()` 的提前返回；重复读取仍记为 observation，但必须实际执行已授权调用。
- `max_lines=0` 的全文件读取由文件工具既有 `MAX_FILE_SIZE` 与结果截断边界保护；不再以“先定位再精读”的运行时建议替模型决定。
- `tools.shell_tools.read_file()` 不再输出 `[阅读导航]` 或建议语句。

### 委派

- 从通用 `Agent` 主循环删除 `_maybe_delegate()` 的预模型调用与 `DelegationGovernor` 自动派发路径。
- `DelegationGovernor` 的自动目标分类、证据充分性、cooldown 和角色推断不再属于 dialogue runtime；只有仍被 Team/operator 路径使用的能力可保留，否则删除。
- evolution 的显式 lifecycle 判定与 Team 任务状态不得被误删；若现有静态 helper 仍有生命周期用途，应移至中性 lifecycle utility，而不是保留自动委派器。

## 5. 兼容与非目标

- `AgentSession` 的历史 UI/API 字段保持空值兼容，不重新写入 route decision。
- Team source-collection、research stage 与原始 `continuationHint`/`retryInstruction` payload 不改。
- 不新增动态工具隐藏、证据评分、重复读取惩罚、委派状态机或 final-answer replanner。
- 不改变 provider、凭据、前端布局和 operator config。

## 6. 成功证据

1. 重复 read 调用会执行并返回事实；runtime 至多记录 observation，不输出/执行换工具建议。
2. 通用 dialogue 轮次不会在模型调用前自动派发子 Agent。
3. ToolMessage/provider replay 只接收 `ModelVisibleToolResult`；runtime sidecar 有独立消费者且不能反向进入模型消息。
4. 文件读取、参数错误、代码图谱和 Team 原始工作流的事实/权限/终态契约保持。
5. 停止只来自模型 final answer、用户取消、硬预算、协议失败或显式 terminal contract。

## 7. 风险与回滚

主要风险是移除自动委派后，原先依赖它的通用对话任务不再隐式并行。这是有意的产品语义变化；Team 工作流不受影响。回滚只允许恢复显式 Team/operator delegation path，不能恢复基于 evidence 的 dialogue 自动派发或阅读拦截。
