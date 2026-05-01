"""
日志模块 - 统一管理 Agent 运行时的调试日志和对话记录

从 agent.py 中提取的日志组件，提供：
- DebugLogger: 基于 Rich 的 Claude Code 级调试输出
- ConversationLogger: 实时对话记录到 JSON 文件

注意：
- 统一的日志接口请使用 core.unified_logger.UnifiedLogger
- 此模块保留 DebugLogger 和 ConversationLogger 独立功能

使用方式:
    # 统一日志（推荐）
    from core.unified_logger import logger
    logger.log_llm_request(messages)

    # 调试日志
    from core.logger import debug
    debug.info("信息")
    debug.tool_start("read_file", {"path": "test.py"})

    # 向后兼容的 ConversationLogger
    from core.logger import conversation_logger
    conversation_logger.log_llm_response("response content")
"""

from __future__ import annotations

import os
import threading
import json
from datetime import datetime
from typing import Optional, Dict, Any, Callable

# ============================================================================
# UI 桥接 — 延迟获取 UIManager（打破循环导入）
# ============================================================================

def _get_ui():
    """获取 UI 实例（每次调用时解析，打破循环导入）"""
    try:
        from core.ui.cli_ui import get_ui
        return get_ui()
    except ImportError:
        return None


# ============================================================================
# 共享的 Token Console
# ============================================================================

_token_console = None


def _get_token_console():
    """获取共享的 Token Console（与 UIManager Live 共享同一 Console 实例）"""
    global _token_console
    if _token_console is None:
        from rich.console import Console
        ui = _get_ui()
        if ui is not None:
            _token_console = ui.console
        else:
            _token_console = Console(force_terminal=True)
    return _token_console


def reset_token_console():
    """重置 token console 实例（在 Live 重启时调用）"""
    global _token_console
    _token_console = None


# ============================================================================
# DebugLogger - 统一调试日志系统
# ============================================================================

class DebugLogger:
    """
    统一调试日志系统 - 基于 rich 的 Claude Code 级输出

    特性：
    - 带时间戳的格式化输出
    - 分类标签便于识别
    - 错误时自动附带上下文和堆栈
    - 线程安全
    - 可控制详细程度
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self.verbose = True
        self.show_timestamps = True
        self._indent_level = 0
        self._indent_char = "  "

    def _timestamp(self) -> str:
        """获取带毫秒的时间戳"""
        now = datetime.now()
        return now.strftime("%H:%M:%S.%f")[:-3]

    def _indent(self) -> str:
        """获取当前缩进"""
        return self._indent_char * self._indent_level

    def _format(self, tag: str, msg: str) -> str:
        """格式化日志消息"""
        parts = []
        if self.show_timestamps:
            parts.append(f"[{self._timestamp()}]")
        parts.append(f"[{tag}]")
        parts.append(f"{self._indent()}{msg}")
        return " ".join(parts)

    def _ui_or_none(self):
        """获取 UI 实例，未就绪时返回 None"""
        return _get_ui()

    def debug(self, msg: str, tag: str = "DEBUG"):
        """调试信息"""
        if self.verbose and (ui := self._ui_or_none()):
            ui.add_log(msg, "DEBUG")

    def info(self, msg: str, tag: str = "INFO"):
        """一般信息"""
        if ui := self._ui_or_none():
            ui.add_log(msg, "INFO")

    def success(self, msg: str, tag: str = "OK"):
        """成功信息"""
        if ui := self._ui_or_none():
            ui.add_log(msg, "SUCCESS")

    def warning(self, msg: str, tag: str = "WARN"):
        """警告信息"""
        if ui := self._ui_or_none():
            ui.print_warning(msg)

    def error(self, msg: str, tag: str = "ERROR", exc_info: Optional[str] = None):
        """错误信息"""
        if ui := self._ui_or_none():
            ui.print_error(msg, exc_info)

    def system(self, msg: str, tag: str = "SYS"):
        """系统信息"""
        if ui := self._ui_or_none():
            ui.add_log(msg, "SYS")

    def tool(self, name: str, status: str, details: str = ""):
        """工具执行日志"""
        if ui := self._ui_or_none():
            ui.add_log(f"Tool: {name} {status} {details}", "TOOL")

    def llm(self, msg: str, details: str = ""):
        """LLM 调用日志"""
        if ui := self._ui_or_none():
            ui.add_log(f"{msg} {details}", "LLM")

    def llm_response(self, content: str, prefix: str = "LLM 回复"):
        """打印 LLM 响应摘要到日志面板"""
        ui = _get_ui()
        if ui is None:
            return
        preview = content[:80] if content else ""
        ui.add_log(f"{prefix}: {preview}...", "LLM")

    def llm_thinking(self, content: str):
        """打印 LLM 的思考过程 — 完整写入内容区"""
        ui = _get_ui()
        if ui is None:
            return

        ui.add_content("")
        ui.add_content("[dim]--- Thinking ---[/dim]")

        import re
        cleaned = re.sub(r'</?thinking[^>]*>', '', content, flags=re.IGNORECASE).strip()
        for line in cleaned.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            ui.add_content(f"  {stripped[:120]}" + ("..." if len(stripped) > 120 else ""))

        ui.add_content("")

    def llm_thinking_log(self, content: str):
        """打印 LLM 思考摘要 — 仅写入日志面板"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_log(f"Thinking: {content[:60]}...", "THINK")

    def tool_start(self, tool_name: str, args: dict):
        """打印工具开始调用 — 内容区 + 日志区"""
        ui = _get_ui()
        if ui is None:
            return
        ui.print_tool_start(tool_name, args)
        ui.print_tool_start_log(tool_name, args)

    def tool_result(self, tool_name: str, result: str, success: bool = True):
        """打印工具执行结果 — 内容区 + 日志区"""
        ui = _get_ui()
        if ui is None:
            return
        ui.print_tool_result(tool_name, result, success)
        ui.print_tool_result_log(tool_name, success)

    def session_start(self, model: str, generation: int = 1):
        """开始会话 — 打印头部信息到控制台"""
        ui = _get_ui()
        if ui:
            ui.print_header(model, generation)

    def session_start_log(self, model: str, generation: int = 1):
        """开始会话 — 仅写入日志面板"""
        ui = _get_ui()
        if ui:
            ui.update_status("AWAKENING", generation=generation)

    def turn_end(self, turn_num: int, tool_count: int = 0):
        """结束一轮对话"""
        ui = _get_ui()
        if ui:
            ui.add_log(f"Turn {turn_num} complete | Tools: {tool_count}", "TURN")

    def section(self, title: str):
        """分节标题"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(f"\n[dim]--- {title} ---[/dim]")

    def divider(self, char: str = "-", length: int = 60):
        """分隔线"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(char * length)

    def kv(self, key: str, value: str):
        """键值对输出"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(f"  [dim]{key}[/dim]: {value}")

    def banner(self, title: str):
        """横幅"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(f"\n[dim]{chr(9472) * 50}[/dim]")
        ui.add_content(f"[bold]  {title}[/bold]")
        ui.add_content(f"[dim]{chr(9472) * 50}[/dim]\n")

    def indent(self):
        """增加缩进"""
        self._indent_level += 1

    def dedent(self):
        """减少缩进"""
        self._indent_level = max(0, self._indent_level - 1)

    def turn_start(self, turn_num: int, context: str = ""):
        """开始新的轮次"""
        ui = _get_ui()
        if ui is None:
            return
        ui.add_content(f"\n[dim]-- Turn {turn_num} --[/dim]")
        if context:
            ui.add_content(f"  {context}")
        ui.add_content("")


# 全局 DebugLogger 实例
debug = DebugLogger()

# 统一导出：from core.logging import logger
# 等价于 from core.logging.logger import debug
# 方便所有模块统一导入：logger.info(...) / logger.debug(...) / logger.error(...)
logger = debug


# ============================================================================
# ConversationLogger - 实时对话记录器
# ============================================================================

class ConversationLogger:
    """
    实时对话记录器 - 将 LLM 对话记录到文件

    特性：
    - 实时写入文件，不丢失任何记录
    - 按会话组织，方便调试和回溯
    - 包含完整的消息内容、工具调用、Token 用量等
    - 线程安全
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "log_info"
        )
        self._ensure_log_dir()
        self._current_session_file = None
        self._turn_count = 0

    def _ensure_log_dir(self):
        """确保日志目录存在"""
        os.makedirs(self._log_dir, exist_ok=True)

    def _get_session_file(self) -> str:
        """获取当前会话的日志文件路径"""
        if self._current_session_file is None:
            self._current_session_file = os.path.join(
                self._log_dir, f"conversation_{self._session_id}.jsonl"
            )
        return self._current_session_file

    def _timestamp(self) -> str:
        """获取 ISO 格式的时间戳"""
        return datetime.now().isoformat(timespec="milliseconds")

    def _write(self, record: dict):
        """写入单条记录到文件（实时刷出）"""
        try:
            with open(self._get_session_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            print(f"[ConversationLogger] 写入失败: {e}")

    def start_session(self, metadata: dict = None):
        """记录会话开始"""
        record = {
            "type": "session_start",
            "timestamp": self._timestamp(),
            "session_id": self._session_id,
            "metadata": metadata or {},
        }
        self._write(record)

    def log_user_input(self, content: str):
        """记录用户输入"""
        self._turn_count += 1
        record = {
            "type": "user_input",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "content": content[:500] if len(content) > 500 else content,
            "content_length": len(content),
        }
        self._write(record)

    def log_llm_request(self, messages: list, model: str = None):
        """记录发送给 LLM 的请求，同时实时显示输入 token 数"""
        msg_summaries = []
        total_input_tokens = 0

        # 尝试用 tiktoken 计算 token 数
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            try:
                enc = tiktoken.get_encoding("cl100k_base")
            except Exception:
                enc = None

        for msg in messages:
            msg_type = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                content_preview = content[:200] + "..." if len(content) > 200 else content
                if enc:
                    total_input_tokens += len(enc.encode(content))
            else:
                content_preview = str(content)[:200]
            msg_summaries.append({
                "type": msg_type,
                "content_preview": content_preview,
                "content_length": len(content) if isinstance(content, str) else 0,
            })

        # 通过 UI 显示 token 数
        ui = _get_ui()
        if ui:
            ui.add_log(f"TOKEN 输入: {total_input_tokens} | 消息: {len(messages)} | 模型: {model or '?'}", "TOKEN")

        record = {
            "type": "llm_request",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "message_count": len(messages),
            "messages": msg_summaries,
            "model": model,
            "input_tokens": total_input_tokens,
        }
        self._write(record)

    def log_llm_response(self, response_content: str, raw_response: str = None):
        """记录 LLM 的原始响应"""
        record = {
            "type": "llm_response",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "content": response_content,
            "content_length": len(response_content) if response_content else 0,
            "raw_length": len(raw_response) if raw_response else 0,
        }
        self._write(record)

    def log_tool_call(
        self,
        tool_name: str,
        tool_args: dict,
        tool_result: str = None,
        status: str = "success"
    ):
        """记录工具调用"""
        record = {
            "type": "tool_call",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_result_preview": (
                tool_result[:500] if tool_result and len(tool_result) > 500 else tool_result
            ),
            "tool_result_length": len(tool_result) if tool_result else 0,
            "status": status,
        }
        self._write(record)

    def log_llm_intent(self, intent: str, content_preview: str = None):
        """记录 LLM 的意图/思考"""
        record = {
            "type": "llm_intent",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "intent": intent,
            "content_preview": (
                content_preview[:300] if content_preview and len(content_preview) > 300
                else content_preview
            ),
        }
        self._write(record)

    def log_compression(self, before_tokens: int, after_tokens: int, saved_tokens: int):
        """记录上下文压缩"""
        record = {
            "type": "compression",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "saved_tokens": saved_tokens,
            "ratio": f"{(saved_tokens / before_tokens * 100):.1f}%" if before_tokens > 0 else "0%",
        }
        self._write(record)

    def log_action(self, action: str, details: dict = None):
        """记录特殊动作（restart/hibernated/skip 等）"""
        record = {
            "type": "action",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "action": action,
            "details": details or {},
        }
        self._write(record)

    def log_error(self, error_type: str, error_msg: str, traceback: str = None):
        """记录错误"""
        record = {
            "type": "error",
            "turn": self._turn_count,
            "timestamp": self._timestamp(),
            "error_type": error_type,
            "error_msg": error_msg,
            "traceback": (
                traceback[:1000] if traceback and len(traceback) > 1000 else traceback
            ),
        }
        self._write(record)

    def end_session(self, summary: dict = None):
        """记录会话结束"""
        record = {
            "type": "session_end",
            "timestamp": self._timestamp(),
            "session_id": self._session_id,
            "total_turns": self._turn_count,
            "summary": summary or {},
        }
        self._write(record)

    def new_session(self):
        """开始新的会话（生成新的 session_id）"""
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_session_file = None
        self._turn_count = 0

    @property
    def _current_turn(self) -> int:
        """获取当前轮次编号"""
        return self._turn_count


# 全局 ConversationLogger 实例
conversation_logger = ConversationLogger()


# ============================================================================
# 便捷函数
# ============================================================================

def get_logger() -> DebugLogger:
    """获取调试日志实例"""
    return debug


def get_conversation_logger() -> ConversationLogger:
    """获取对话记录器实例"""
    return conversation_logger
