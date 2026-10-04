# Logging Module

**日志系统模块** - 统一日志与追踪

## Modules

| File | Description |
|------|-------------|
| `logger.py` | 调试日志 (DebugLogger) + 会话 JSONL (ConversationLogger) |
| `unified_logger.py` | 统一日志记录器（会话事件 + Markdown 实录） |
| `transcript_logger.py` | 转录日志（Markdown，写入 workspace home `logs/transcripts`） |
| `trace_context.py` | W3C `traceparent` 解析、请求级 span 与 `ContextVar` 关联上下文 |
| `safe_payload.py` | 工具参数的 keys/shape/length/hash 安全摘要 |
| `tool_tracker.py` | 工具调用追踪（analytics 统计；记录端已停用，类保留） |

## Usage

```python
from core.logging import debug                 # 调试日志（服务层推荐入口）
from core.logging import logger                # 会话事件日志（UnifiedLogger）
from core.logging.logger import ConversationLogger
```

## 落盘约定（统一）

- 会话 JSONL：项目根 `logs/conversations/conversation_*.jsonl`（结构化事件 + 服务层 debug 转发，`DEBUG` 级默认不落盘；设置环境变量 `VIBELUTION_LOG_LEVEL=DEBUG` 可开启 DEBUG 落盘，用于深度现场调试）
- Runtime scene 事件：`logs/runtime_scenes/`（UTC ISO 事件流）
- Transcript：workspace home `logs/transcripts/transcript_*.md`（人读展示，保留本地时间）
- 时间戳：机器可读事件统一 **UTC ISO**（`2026-08-12T01:30:00.123+00:00`）；UI/展示层保留本地时间
- `debug_*.log` 文件通道已停用（与 JSONL 重复），历史文件仍可经维护重置清理

## 关联与安全约定

- Web API middleware 接受合法 W3C `traceparent`；每个请求创建新的 server span，并在响应返回 `traceparent` 与 `X-Request-ID`。
- 作用域内的 conversation JSONL 和 runtime-scene 事件自动补充 `traceId`、`spanId`、可选 `parentSpanId` 与 `requestId`；调用方显式字段优先。
- 跨线程、executor、队列或进程的调度边界必须把这些字段显式写入调度 context，不能假设 `ContextVar` 自动传播。
- 工具参数不得原样写入 conversation JSONL 或 Markdown transcript；只保留参数名、类型/形状、长度和稳定 SHA-256 摘要。runtime-scene 的结构化参数继续执行递归敏感键脱敏和深度/数量/长度限制。
- 工具执行在 runtime scene 记录 `tool.execution.started` 与对应的 `completed` / `blocked` / `failed` 终态，保留 `toolCallId`、`toolName`、read-only/mutating 模式、耗时、业务结果、动作和受控 `errorType`；不记录参数、结果或异常消息。
- 不记录 secrets、完整 Prompt、完整 diff 或无界工具输出；新增事件应优先记录标识、阶段、结果、耗时、计数和 artifact 引用。

## Key Classes

- `DebugLogger` - 调试日志（UI 面板 + JSONL 转发；`DEBUG` 级仅 UI）
- `logger` - 统一日志管理器（会话事件记录）
- `TranscriptLogger` - 对话实录（Markdown）
- `ToolTracker` - 工具调用追踪（记录端停用）

## 功能

- 分级日志输出 (DEBUG, INFO, WARN, ERROR)
- Token 使用统计
- 工具调用追踪
- 对话历史转录
- LLM 请求/响应记录

## Transcript writer 生命周期

- Transcript 后台队列同时限制待写记录数（默认 512）和 UTF-8 正文大小（默认 8 MiB）；上限包括正在写入的记录。队列满或单条内容超限时立即拒收，并在 `TranscriptLogger.diagnostics()` 中累计 `dropped_writes` 与 `dropped_characters`，不记录被拒收正文。
- `flush(timeout=...)` 只等待调用时已接收的写入，且始终有超时；`UnifiedLogger.end_session()` 对 Transcript 结束标记最多等待 250 ms，写入失败或会话期间发生丢失时返回 `False`。
- 所有 producer 停止后，生命周期可调用 `shutdown_transcript_logger(deadline=time.monotonic() + budget)`。返回结果区分 `closed`、`drained`、`timed_out`、`pending_writes` 与写入/丢失计数；超时会保留 writer 实例以便再次调用关闭。
- 新生命周期调用 `begin_transcript_logger_lifecycle()`。它只操作已存在实例；如果前一个 writer 仍存活或仍有未退休记录，则返回 `opened: false`，不会并行启动第二个线程。未初始化时 begin/shutdown 都不会创建实例或 writer。
