# 全局 Token 使用量统计设计

## 意图

为 Vibelution 添加一个全局 Token 使用量统计能力，统计口径参考 Codex，但事实源只来自 Vibelution 自己的 LLM 调用链路。用户最终应该能看到“本次调用、当前会话累计、全局累计”的 Token 使用情况，并且能区分真实上游返回、估算、缺失三类来源。

本机 Codex 只读证据：

- Codex 会在 session JSONL 中记录 `event_msg`，其中 `payload.type` 为 `token_count`。
- 每条事件包含 `last_token_usage`，表示最近一次模型调用消耗。
- 每条事件包含 `total_token_usage`，表示当前会话累计消耗。
- usage 字段包括 `input_tokens`、`cached_input_tokens`、`output_tokens`、`reasoning_output_tokens`、`total_tokens`。
- 事件还带有 `model_context_window` 和可选 `rate_limits`。

Vibelution 应复刻这种统计语义，而不是读取或合并 Codex 私有数据文件。

## 目标

- 所有 Vibelution LLM 调用完成后，都通过一个规范化 usage 事件进入全局账本。
- 提供 Codex 风格的 `last`、`session total`、`global total` 统计。
- 保留缓存统计：缓存命中输入、非缓存输入、cache creation/write token、cache hit rate。
- 区分 `provider_usage`、`estimated`、`missing`、`not_called`，避免把估算值伪装成真实值。
- 支持按今日、最近 7 天、全部时间、模型、provider、session、agent/runtime scope 聚合。
- 兼容现有对话页 session usage/cache usage 展示，不把当前 UI runtime state 当作全局事实源。

## 非目标

- 不把 Codex App、Codex CLI 或外部 `.codex` 的 Token 使用量合并进 Vibelution。
- 第一版不做费用或账单估算。
- 第一版不要求接入 provider rate limit 统计。
- 第一版不重做整个对话页 token/compression UI，只补全全局统计入口和必要展示。
- 不把 `ui_runtime_state.json` 作为全局统计的 canonical source。

## 事实源

| 事实 | Canonical source | Writer | Readers / derived surfaces | Refresh / invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| 单次 LLM 调用 usage | 新的 Vibelution usage ledger event | provider response 之后的统一 usage 记录链路 | 聚合服务、runtime scenes、chat/session projection | append-only event；按时间和 scope 查询聚合 | 现有 round/UI total 保持为运行态派生展示 |
| 最近一次调用 usage | 对应 scope 的最新 ledger event | 同上 | Chat UI、runtime UI、全局统计 panel | 查询最新 event | 尽量替换 UI-state-only fallback |
| 当前会话累计 | ledger 按 session/conversation/thread 聚合 | 聚合服务 | Session detail、Chat route、diagnostics | 从 ledger 重新计算 | 现有 message metadata aggregate 作为兼容/fallback |
| 全局累计 | ledger 跨 Vibelution scope 聚合 | 聚合服务 | 全局统计 API/UI | 从 ledger 重新计算，可加只读缓存 | 目前没有旧全局源 |
| usage 来源状态 | ledger `source` 字段 | usage normalizer / recorder | UI badge、diagnostics、tests | 每条 event 持久保存 | 保留现有 missing/estimated 语义 |

## 事件模型

每条账本记录应该小、可追加、可恢复，并且不能保存 prompt、response、工具输出、secret 或完整 provider payload。

必需字段：

- `eventId`
- `recordedAt`
- `source`: `provider_usage`、`estimated`、`missing`、`not_called`
- `scopeKind`: `chat_session`、`agent_round`、`team_workflow`、`evolution`、`tool`、`unknown`
- `sessionId`、`conversationId`、`turnId`、`agentId`、`teamId`，有则记录
- `provider`、`model`、`profileId`，有则记录
- `inputTokens`
- `outputTokens`
- `totalTokens`
- `cachedInputTokens`
- `cacheReadInputTokens`
- `cacheCreationInputTokens`
- `uncachedInputTokens`
- `reasoningOutputTokens`，provider 暴露时记录，否则为 `0`
- `contextWindow`，已知时记录
- `latencyMs`，已知时记录

可选诊断字段：

- `usageSchemaVersion`
- `transport`
- `promptCacheScope`
- `promptCachePartitionHash`
- `runtimeSceneId`
- `providerUsageKeys`：只保存 raw usage 的 key 名称列表，不保存 raw value

## 记录链路

第一版应复用现有 usage normalizer，不新增平行 parser。

当前可复用入口：

- `core/llm/usage.py` 已经把 provider payload 规范化为 `UsageStats`。
- `core/llm/types.py` 定义了 `UsageStats`。
- `core/orchestration/response_surface.py` 已经把 per-turn usage 写给 round state、logger、pet 和 UI。
- `core/web/services/session_service.py` 已经能规范化 assistant message 的 `llmUsage` 并生成 session cache usage。
- `core/web/services/runtime_service.py` 已经能从 runtime state 投影当前 token/cache usage。

推荐链路：

1. Provider response 或 streaming completion 暴露 usage metadata。
2. 现有 normalizer 把 provider payload 转成 Vibelution usage 字段。
3. response/session 记录链路为这次完成的模型调用写入一条 ledger event。
4. 现有 UI state 和 message metadata 继续接收 per-turn usage，作为兼容展示。
5. 聚合服务从 ledger 计算 Codex 风格 summary。

## Codex 风格 Summary

后端 summary payload 推荐形态：

```json
{
  "lastTokenUsage": {
    "inputTokens": 0,
    "cachedInputTokens": 0,
    "outputTokens": 0,
    "reasoningOutputTokens": 0,
    "totalTokens": 0,
    "source": "provider_usage"
  },
  "sessionTokenUsage": {
    "inputTokens": 0,
    "cachedInputTokens": 0,
    "outputTokens": 0,
    "reasoningOutputTokens": 0,
    "totalTokens": 0,
    "observedCallCount": 0,
    "estimatedCallCount": 0
  },
  "globalTokenUsage": {
    "today": {},
    "last7Days": {},
    "allTime": {}
  },
  "modelContextWindow": 0,
  "updatedAt": ""
}
```

rollup object 应保留：

- `inputTokens`
- `cachedInputTokens`
- `uncachedInputTokens`
- `outputTokens`
- `reasoningOutputTokens`
- `totalTokens`
- `cacheHitRate`
- `observedCallCount`
- `estimatedCallCount`
- `missingCallCount`

## 存储和保留

第一版推荐使用 Vibelution 项目自有的 JSONL 或 SQLite usage ledger，并放在现有 runtime/user-data 存储约定之下。实现计划阶段必须先检查项目已有持久化 helper，再决定最终路径和格式。

存储要求：

- 正常写入是 append-only。
- event 记录有界，不保存 prompt/response 内容。
- 支持 runtime 路径并发写入。
- 足够高效地聚合今日和全部时间统计。
- 单条坏记录不能破坏整个聚合。

如果 Vibelution 已有适合此 runtime surface 的数据库 helper，优先 SQLite。只有在明确处理锁、并发和 rollup 性能之后，才选择 JSONL。

## API 设计

新增只读后端 API，用于读取 Token 使用量 summary。

最小查询 scope：

- `scope=global`
- `scope=session&sessionId=...`
- `scope=agent&agentId=...`
- `scope=model&provider=...&model=...`

最小时间窗口：

- `today`
- `last7Days`
- `allTime`

API 不得暴露 raw prompt、response、provider secret 或完整 provider usage payload。

## UI 设计

UI 应保持紧凑、可扫读、偏运维工具感：

- 全局 Token summary 放在现有 chat/coding token status 附近，或放入 diagnostics drawer 的稳定入口。
- 一级数字显示 `In`、`Cached`、`Out`、`Total`。
- 明确显示 source：provider-observed、estimated、missing。
- 默认优先展示今日和全部时间；model/provider breakdown 放进 details panel。
- 保留现有 session cache/compression 展示，全局统计在视觉层级上低于当前对话状态。

第一版避免做大型 analytics dashboard。用户要的是全局 Token 统计，不是账单分析系统。

## 错误处理

- provider usage 存在时，记录 `source=provider_usage`。
- usage 缺失但 Vibelution 能估算 input/output 时，记录 `source=estimated`。
- 没有模型调用时，只在有诊断价值时记录 `source=not_called`，且不计入 token total。
- ledger 写入失败不能单独导致用户的 LLM 响应失败，但必须记录有界错误日志。
- 历史坏记录应被跳过并计入 diagnostics count，不能让 summary endpoint 整体失败。

## 测试策略

后端 focused tests：

- provider usage 在一次完成的 LLM 调用后只追加一条 event。
- cached input 和 uncached input 能被保留。
- missing usage 会被标记为 estimated 或 missing，不会混入 provider-observed totals。
- session/global rollup 符合 Codex 风格 `last` 和 `total` 语义。
- 坏 ledger 记录不会破坏聚合。

前端 focused tests：

- 全局 Token summary 能渲染 observed totals。
- estimated/missing source 状态可见。
- 现有 session cache usage 展示不回归。

验证命令：

- Python focused tests 覆盖 usage recording 和 aggregation。
- 相关 web tests 覆盖 token status UI。
- 如果改动包含前端 DTO/UI，运行 `npm --prefix web run build`。

## 日志决策

为 ledger 写入失败和聚合读取失败添加有界 runtime-scene logging。不要记录 raw provider usage payload、prompt、response text 或 secret。成功写入本身可以通过 ledger 计数证明，常规成功路径不需要逐条 runtime log。

## 开放实现决策

- 最终 storage path 和格式必须跟随 Vibelution 已有 runtime persistence 约定。
- `reasoningOutputTokens` 需要扩展 normalizer，因为当前 `UsageStats` 没有直接字段。
- API 文件和 TypeScript DTO 落点需要 serialized claim，因为 `web/src/api/types.ts`、`core/web/services/session_service.py`、`core/web/services/runtime_service.py` 都是共享 hot surface。

## 已批准口径

截至 2026-07-05，已对齐的用户口径：

- “全局”指 Vibelution 全局 usage。
- Codex 作为统计方法参考，不作为 Vibelution 的数据源。
- 第一版以 provider-observed normalized usage 作为事实源；估算和缺失必须显式标记。
