# 可见上下文压缩居中提示设计

Date: 2026-07-05
Status: Draft approved for written spec review

## 已确认意图

用户希望 Vibelution 在上下文压缩发生时，像 Codex 一样在对话中出现居中的压缩提示。该提示应表达“上下文已压缩/未应用/失败”，但不能伪装成 Agent 的普通 assistant 回复。

确认选择：

- 采用 Codex 风格的居中时间线分隔提示。
- 压缩提示不是 assistant 气泡，不靠左、不靠右，不参与普通对话语义。
- 继续复用 conversation ledger 和 context compression checkpoint，不新建并行历史事实源。
- 模型上下文继续使用 checkpoint 投影压缩旧历史；原始 ledger 仍保留完整事件用于审计和恢复。
- 自动阈值压缩、工具请求压缩、provider context-length reactive 压缩使用同一可见 marker schema。

## 当前事实

当前系统已经具备 ledger-backed 压缩基础：

- `agent.py` 的 `_compress_messages()` 会触发上下文压缩，并调用 `append_context_compression_checkpoint()` 写入 checkpoint。
- `core/chat/context_compression_ledger.py` 负责构造 `context_compression_checkpoint.v1` payload，记录 `summary`、`level`、`reason`、`triggerSource`、`beforeTokens`、`afterTokens`、`savedTokens`、`effective`、covered event 范围和 tool-result replacement 信息。
- `conversation_model_messages_from_events()` 会通过 `apply_context_compression_checkpoints()` 过滤被 checkpoint 覆盖的历史事件，模型上下文不会继续吃完整旧历史。
- `conversation_visible_messages_from_events()` 当前直接回放原事件，因此可见历史仍保留原始消息。
- `turn_journal._checkpoint_message_from_event()` 当前把 `EVENT_COMPACTION_CHECKPOINT` 投影成普通 assistant message，内容为 `历史检查点：\n<summary>`。
- `web/src/api/types.ts` 的 `ConversationMessage.role` 目前只允许 `user | assistant`。
- `web/src/agent-thread/adapters.ts` 会把 assistant message 转换成普通 Agent message parts，因此 checkpoint 可见投影会被当作 assistant 内容显示。
- `core/web/services/runtime_service.py` 已能从 ledger 的 `context_compression_projection()` 派生运行时压缩摘要。

根本缺口不是“完全没有压缩事件”，而是 checkpoint 的可见投影层缺少一等 runtime marker 语义，导致压缩提示看起来像 Agent 自己说了一段“历史检查点”。

## 目标

1. 压缩发生时，在对话时间线中出现居中的 Codex 风格提示。
2. 提示是运行时/系统事件，不是 assistant 或 user 普通消息。
3. 提示能覆盖成功、低收益未应用、失败保留原上下文三种状态。
4. 模型上下文、可见时间线、原始 ledger 三个投影各守边界。
5. 复用当前 checkpoint payload 和 conversation ledger，不引入第二套历史压缩存储。
6. 为后续 UI、runtime summary 和测试提供稳定 schema。

## 非目标

- 不改变 GPT 上下文窗口配置；`40000` token limit 和 `80%` standard threshold 已由前序任务处理。
- 不删除、截断或重写原始 conversation ledger。
- 不把旧消息在 UI 中物理删除；是否折叠旧历史是可选呈现策略，不是本规格的第一交付。
- 不新增外部压缩服务或新的模型调用链。
- 不把压缩摘要暴露成普通聊天文本。
- 不在本规格阶段修改实现代码；实现前必须重新申请 `agent-runtime-core` 和/或 `chat-coding-surface` 的 hot-file claim。

## 设计总览

系统应继续把 conversation ledger 作为唯一 durable source。成功应用的压缩继续写 `compaction_checkpoint`；低收益未应用和失败保留可以扩展为同一 ledger 事件族，但不能写成 UI-only 状态。不同消费者通过不同投影读取 ledger：

```text
conversation ledger
  -> model projection: checkpoint summary replaces covered historical events
  -> visible projection: centered compression marker appears at checkpoint position
  -> runtime summary: lastCompression and compression policy snapshot
```

核心变化是新增可见 marker 投影，而不是新增事实源。成功压缩的写入源仍是 `compaction_checkpoint`；marker 是派生视图。

## 用户可见行为

### 成功压缩

压缩成功且 `effective=true` 时，在对话时间线中插入居中提示：

```text
上下文已压缩
```

辅助信息可以用小号文本或 tooltip 展示：

```text
standard · 节省 12,340 tokens · 自动阈值
```

压缩摘要默认折叠。用户展开后可以看到 bounded summary，用于理解被压缩历史的主要内容。展开内容不是 assistant 回复。

### 低收益未应用

当压缩尝试完成但未达到收益阈值，提示为：

```text
压缩未应用 · 收益不足
```

辅助信息展示 `beforeTokens`、`afterTokens`、`effectivenessRatio` 和阈值。模型上下文不应切换到低收益 summary。

### 压缩失败

当压缩过程失败但原上下文保留，提示为：

```text
压缩失败 · 已保留原上下文
```

辅助信息只显示错误类别或短 reason，不显示完整 prompt、密钥、provider payload 或长错误堆栈。

### 当前轮保护

如果压缩发生在一轮回复中，当前 turn 的用户消息、正在生成的 assistant 输出和工具结果不能被 marker 或 checkpoint 吞掉。现有 `current_turn_id` 保护必须保留并覆盖新 marker 测试。

## Marker Schema

后端可见投影建议生成 `ConversationMessage` 兼容对象，或者在 AgentThread adapter 之前升级为更明确的 timeline item。无论实现路径如何，语义字段应稳定：

```json
{
  "id": "compression:<eventId>",
  "role": "system",
  "content": "",
  "timestamp": "<event timestamp>",
  "metadata": {
    "kind": "context_compression_marker",
    "eventId": "<ledger event id>",
    "turnId": "<turn id>",
    "status": "applied",
    "title": "上下文已压缩",
    "detail": "standard · 节省 12340 tokens · 自动阈值",
    "level": "standard",
    "triggerSource": "automatic_threshold",
    "beforeTokens": 39520,
    "afterTokens": 18400,
    "savedTokens": 21120,
    "effectivenessRatio": 0.53,
    "effectivenessThreshold": 0.0,
    "summaryHash": "<short hash>",
    "summaryAvailable": true,
    "summaryPreview": "<bounded summary when disclosure is allowed>",
    "schema": "context_compression_marker.v1"
  }
}
```

`status` 枚举：

- `applied`: 压缩已应用，模型上下文使用 checkpoint summary。
- `skipped_low_savings`: 压缩尝试完成但收益不足，模型上下文保留原历史。
- `failed_preserved`: 压缩失败，原上下文保留。

`summaryPreview` 是可选字段，只用于用户主动展开的 bounded disclosure。它不能进入 `content`，也不能被当作 assistant 回复。

如果实现阶段不希望扩展 `ConversationMessage.role`，可以在后端仍用 `role="assistant"` 兼容旧 API，但 AgentThread adapter 必须优先识别 `metadata.kind="context_compression_marker"` 并渲染为系统 marker，而不是 assistant 气泡。长期更干净的契约是允许 `system` 或 timeline-event 类型。

无论采用哪条兼容路径，model projection 必须显式排除 `metadata.kind="context_compression_marker"` 的可见 UI marker。模型只能看到 checkpoint summary 对应的压缩上下文，不能把居中提示文案当成一轮 assistant 或 system 对话重新输入。

## 后端投影设计

### 可复用模块

优先复用：

- `core/chat/context_compression_ledger.py`
- `core/chat/conversation_ledger.py`
- `core/chat/turn_journal.py`
- `core/web/services/session_service.py` 中 `_ledger_visible_messages_for_session()` 和 `_session_ledger_visible_messages()`
- `core/web/services/runtime_service.py` 中 context compression summary

不新增并行 ledger，不新增独立 compression marker JSONL。

### 新的投影职责

建议在 `turn_journal.py` 或一个窄 helper 中新增 `context_compression_marker_message_from_event(event)`，替代当前 `_checkpoint_message_from_event()` 的 assistant 文本输出。

该 helper 只负责把 durable checkpoint payload 转成可见 marker payload：

- 从 `effective`、`summaryWritten`、错误字段推导 marker status。
- 从 `triggerSource` 转成人类可读短标签。
- 保留 token 数、level、summary hash、covered range 元数据。
- 不把完整 summary 直接塞进 `content`。
- 不改变模型 projection 逻辑。

### 失败和低收益事件

当前 `append_context_compression_checkpoint()` 要求 `summary_text` 非空才写 checkpoint。实现阶段需要确认低收益和失败路径是否已有 durable event。如果没有，应增加一个同源的 compression attempt event 或允许 checkpoint payload 表达未应用/失败状态。

推荐顺序：

1. 成功应用仍写 `compaction_checkpoint`。
2. 低收益未应用写 `compaction_checkpoint` 或 `context_compression_attempt`，但 `effective=false`，且 model projection 不覆盖历史。
3. 压缩失败写 `context_compression_attempt`，`status=failed_preserved`，不参与 model projection 覆盖。

若新增 event type，应保持它是 conversation ledger 事件，并由 visible projection 渲染 marker；不要写 UI-only state。

## 前端居中提示设计

### AgentThread 数据模型

`web/src/agent-thread/types.ts` 当前只有 `AgentMessageRole = "user" | "assistant"`。实现可以采用两步迁移：

第一步兼容：

- 保持 `ConversationMessage` API 不大改。
- adapter 在 `conversationMessageToAgentMessage()` 前识别 `metadata.kind === "context_compression_marker"`。
- 生成 `AgentMessage` 时加入 `metadata.kind`，并让 view 按 marker 样式渲染整条消息。

第二步清理：

- 增加 `AgentTimelineMarker` 或把 `AgentMessageRole` 扩为 `"user" | "assistant" | "system"`。
- 将 compression marker 作为独立 timeline item，不再依赖 assistant message 兼容形态。

第一步是本功能的建议最小实现，因为它降低 DTO 波及面；第二步可作为后续契约清理。

### 视觉样式

居中提示应表现为时间线分隔：

- 容器占据一整行，水平居中。
- 主文本短、低噪声、非气泡形态。
- 使用细线、轻量边框或小号 pill，但不要像普通聊天消息。
- 不显示 avatar、role label、assistant bubble、user bubble、tool card。
- 展开摘要时使用轻量 disclosure，不做嵌套卡片墙。
- 移动端保持居中，文本可换行，不遮挡上下消息。

示例结构：

```text
──────── 上下文已压缩 ────────
standard · 节省 21,120 tokens · 自动阈值
```

失败状态可以用警告色轻微强调，但不应变成醒目的错误弹窗，除非压缩失败导致当前请求不可继续。

## 错误处理

压缩 marker 不应制造新的失败路径：

- marker 投影失败时，保底返回一个短系统提示，不影响原消息显示。
- summary 缺失但 event 存在时，显示状态和 token 元数据，不显示空展开区。
- 旧 ledger 中已经存在的 `历史检查点` assistant 文本需要兼容迁移；新投影应识别旧 `compaction_checkpoint` event 并渲染为 marker。
- 如果某些历史 session 只有 assistant 文本而没有 event metadata，不做自动猜测迁移，避免误判普通消息。

## 日志与证据

该功能影响 runtime behavior 和可见 UI，需要日志与测试决策：

- 成功压缩继续保留现有 `agent.context_compression_*` 日志。
- 低收益未应用和失败保留路径应有 bounded runtime-scene evidence，记录 status、reason、token counts、triggerSource、sessionId、turnId。
- 不记录完整 summary、完整 prompt、密钥、provider payload 或长模型输出。
- UI marker 不需要单独写日志；它由 ledger event 派生。

## 测试计划

### 后端测试

更新或新增：

- `tests/test_conversation_ledger.py`
- `tests/test_session_context_pipeline.py`
- `tests/test_agent_protocol.py`
- `tests/test_web_runtime_routes.py`

覆盖：

- `compaction_checkpoint` 在 visible messages 中投影为 `metadata.kind=context_compression_marker`。
- marker 不作为 assistant 普通内容进入 model messages。
- 成功应用 checkpoint 时，model projection 仍过滤 covered historical events。
- 当前 turn 不被 checkpoint 覆盖。
- 旧 checkpoint event 仍能投影为 marker。
- 低收益/失败状态不会覆盖 model history。
- runtime summary 仍优先使用 ledger compression projection。

### 前端测试

更新或新增：

- `web/src/agent-thread/agentThreadAdapters.test.ts`
- `web/src/agent-thread/AgentThreadView.test.tsx`
- 相关 Conversation/Chat route layout tests，取决于实际渲染入口。

覆盖：

- `context_compression_marker` 不渲染为 assistant 气泡。
- marker 在时间线中居中。
- marker 不显示 role label、avatar 或 tool card。
- applied、skipped_low_savings、failed_preserved 三种状态文案正确。
- 摘要详情默认折叠，展开后仍不形成嵌套卡片。
- 窄屏下文本不溢出、不遮挡相邻消息。

### 构建与回归

实现阶段至少运行：

- Python focused tests for conversation ledger/session context/runtime summary.
- Frontend focused Vitest for AgentThread/Conversation route.
- `npm --prefix web run build`。
- `git diff --check`。

如果实际改动触及 running UI 或 backend runtime contracts，最终报告需要明确 Launcher refresh decision。

## 源事实表

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh or invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| 压缩是否发生 | conversation ledger event | `agent.py` / compression tool path | model projection, visible marker, runtime summary | append event 后 session ledger cache invalidation | 不新增 UI-only 状态 |
| 压缩摘要 | checkpoint payload summary | compression pipeline | model context, optional marker disclosure | ledger reload | 不把 summary 写成 assistant 文本 |
| 可见提示 | derived marker projection | no direct writer | AgentThread / Conversation UI | derived from ledger events | 替代 `_checkpoint_message_from_event()` 的普通 assistant 文案 |
| 运行时统计 | ledger projection plus runtime state fallback | runtime service | runtime summary UI | active session projection refresh | fallback 仅用于无 ledger 的旧状态 |

## 实现边界与 claim 计划

本规格文档是 doc-only work，当前 claim 范围只覆盖：

- `docs/superpowers/specs/2026-07-05-visible-context-compression-marker-design.md`

后续实现前必须重新 guard check/claim，预计范围：

- `agent.py`
- `core/chat/context_compression_ledger.py`
- `core/chat/conversation_ledger.py`
- `core/chat/turn_journal.py`
- `core/web/services/session_service.py`
- `core/web/services/runtime_service.py`
- `web/src/api/types.ts`
- `web/src/agent-thread/**`
- 相关 Python 和 Vitest 测试

如果 active claims 仍占用 `agent-runtime-core` 或 `chat-coding-surface`，实现必须等待、转交或在明确授权下 force claim；不能在 doc-only claim 下改代码。

## 验收标准

实现完成后，用户应看到：

- 压缩发生时，对话中间出现 Codex 风格居中提示。
- 提示不是 assistant 气泡，不带 assistant role label。
- 成功、低收益未应用、失败保留都有明确文案。
- 模型上下文仍通过 checkpoint summary 压缩旧历史，不吃 UI marker 文案。
- 原始 ledger 可审计，当前 turn 不丢失。
- runtime summary 仍能显示最近一次压缩和策略信息。

## 下一阶段

用户审阅本规格后，进入 implementation plan。计划应按 TDD 拆成三段：

1. 后端 marker projection 和低收益/失败状态表达。
2. AgentThread 居中 marker 渲染与 DTO 兼容。
3. 集成验证、runtime summary 回归和 Launcher refresh decision。
