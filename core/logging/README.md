# Logging Module

**日志系统模块** - 统一日志与追踪

## Modules

| File | Description |
|------|-------------|
| `logger.py` | 调试日志 (DebugLogger) + 会话 JSONL (ConversationLogger) |
| `unified_logger.py` | 统一日志记录器（会话事件 + Markdown 实录） |
| `transcript_logger.py` | 转录日志（Markdown，写入 workspace home `logs/transcripts`） |
| `tool_tracker.py` | 工具调用追踪（analytics 统计；记录端已停用，类保留） |

## Usage

```python
from core.logging import debug                 # 调试日志（服务层推荐入口）
from core.logging import logger                # 会话事件日志（UnifiedLogger）
from core.logging.logger import ConversationLogger
```

## 落盘约定（统一）

- 会话 JSONL：项目根 `logs/conversations/conversation_*.jsonl`（结构化事件 + 服务层 debug 转发，`DEBUG` 级不落盘）
- Runtime scene 事件：`logs/runtime_scenes/`（UTC ISO 事件流）
- Transcript：workspace home `logs/transcripts/transcript_*.md`（人读展示，保留本地时间）
- 时间戳：机器可读事件统一 **UTC ISO**（`2026-08-12T01:30:00.123+00:00`）；UI/展示层保留本地时间
- `debug_*.log` 文件通道已停用（与 JSONL 重复），历史文件仍可经维护重置清理

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
