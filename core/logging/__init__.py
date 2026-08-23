# Logging 模块 - 日志系统组件
# 向后兼容别名：部分基础设施模块仍使用 `from core.logging import debug`。
from core.logging.logger import (
    ConversationLogger,
    DebugLogger,
    debug,
    get_conversation_logger,
    get_logger,
)
from core.logging.logger import (
    debug as debug_logger,  # 统一调试日志（DebugLogger 实例）
)
from core.logging.pipeline_metrics import LoggingPipelineMetrics, pipeline_metrics
from core.logging.setup import (
    print_evolution_time,
    setup_logging,
)
from core.logging.tool_tracker import ToolTracker, get_tool_tracker
from core.logging.trace_context import (
    TraceContext,
    bind_trace_context,
    current_trace_fields,
    get_current_trace_context,
    merge_current_trace_fields,
    new_trace_context,
    parse_traceparent,
)
from core.logging.transcript_logger import TranscriptLogger, get_transcript_logger
from core.logging.unified_logger import (
    UnifiedLogger,
    logger,  # 统一日志管理器（会话事件记录）
)

__all__ = [
    "ConversationLogger",
    "DebugLogger",
    "LoggingPipelineMetrics",
    "ToolTracker",
    "TraceContext",
    "TranscriptLogger",
    "UnifiedLogger",
    "bind_trace_context",
    "current_trace_fields",
    "debug",
    "debug_logger",
    "get_conversation_logger",
    "get_current_trace_context",
    "get_logger",
    "get_tool_tracker",
    "get_transcript_logger",
    "logger",
    "merge_current_trace_fields",
    "new_trace_context",
    "parse_traceparent",
    "pipeline_metrics",
    "print_evolution_time",
    "setup_logging",
]
