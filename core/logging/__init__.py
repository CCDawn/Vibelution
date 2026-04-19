# Logging 模块 - 日志系统组件
from core.logging.logger import (
    DebugLogger, ConversationLogger, get_logger, get_conversation_logger,
    logger as debug_logger,      # 统一调试日志（等用于 debug）
)
from core.logging.unified_logger import (
    logger, UnifiedLogger         # 统一日志管理器（对话记录）
)
from core.logging.transcript_logger import (
    TranscriptLogger, get_transcript_logger
)
from core.logging.tool_tracker import (
    ToolTracker, get_tool_tracker
)
from core.logging.setup import (
    setup_logging,
    print_evolution_time,
)

# 向后兼容别名
from core.logging.logger import debug as console_logger
