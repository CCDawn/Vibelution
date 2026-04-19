# Logging Module

**日志系统模块** - 统一日志与追踪

## Modules

| File | Description |
|------|-------------|
| `logger.py` | 调试日志 (DebugLogger) |
| `unified_logger.py` | 统一日志记录器 |
| `transcript_logger.py` | 转录日志 |
| `tool_tracker.py` | 工具调用追踪 |

## Usage

```python
from core.logging.logger import DebugLogger, debug
from core.logging.unified_logger import logger
from core.logging.tool_tracker import ToolTracker
```

## Key Classes

- `DebugLogger` - 调试日志输出
- `logger` - 统一日志记录器
- `TranscriptLogger` - 对话转录
- `ToolTracker` - 工具调用追踪

## 功能

- 分级日志输出 (DEBUG, INFO, WARN, ERROR)
- Token 使用统计
- 工具调用追踪
- 对话历史转录
- LLM 请求/响应记录
