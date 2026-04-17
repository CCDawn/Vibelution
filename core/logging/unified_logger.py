# -*- coding: utf-8 -*-
"""
统一日志管理器 - 合并 ConversationLogger 和 TranscriptLogger

提供统一的日志接口，同时输出到两个日志系统：
- JSON 统计日志 (ConversationLogger)
- Markdown 对话实录 (TranscriptLogger)

使用方式：
    from core.unified_logger import logger

    # 记录 LLM 请求（同时写入两个日志系统）
    logger.log_llm_request(messages, model="gpt-4")

    # 记录 LLM 响应
    logger.log_llm_response(response)

    # 记录工具调用
    logger.log_tool_call("read_file", {"path": "test.py"}, result="content")
"""

import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

# 导入 ConversationLogger (在 logger.py 中)
from .logger import ConversationLogger
from .transcript_logger import TranscriptLogger


class UnifiedLogger:
    """
    统一日志管理器

    同时调用 ConversationLogger 和 TranscriptLogger，提供统一的日志接口。
    这样可以减少 agent.py 中的重复调用，同时保持两个日志系统的独立功能。
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

        # 初始化两个日志器
        self._conversation = ConversationLogger()
        self._transcript = TranscriptLogger()

        # 同步状态
        self._current_turn = 0
        self._current_generation = 1
        self._system_prompt_written = False

    @property
    def conversation(self) -> ConversationLogger:
        """获取 ConversationLogger 实例（用于需要 JSON 日志的场景）"""
        return self._conversation

    @property
    def transcript(self) -> TranscriptLogger:
        """获取 TranscriptLogger 实例（用于需要 Markdown 日志的场景）"""
        return self._transcript

    def _sync_turn(self, turn: int):
        """同步轮次状态"""
        self._current_turn = turn
        self._conversation._turn_count = turn

    def _sync_generation(self, generation: int):
        """同步世代状态"""
        self._current_generation = generation

    # ==================== 世代管理 ====================

    def start_generation(self, generation: int, system_prompt: str = None):
        """开始新的世代（同时初始化两个日志系统）"""
        self._current_generation = generation
        self._current_turn = 0
        self._system_prompt_written = False

        # TranscriptLogger: 创建新文件
        self._transcript.start_generation(generation, system_prompt)

        # ConversationLogger: 开始新会话
        self._conversation.new_session()

        # 如果有 System Prompt，写入
        if system_prompt:
            self.write_system_prompt(system_prompt)

    def write_system_prompt(self, system_prompt: str):
        """写入 System Prompt"""
        if self._system_prompt_written:
            return
        self._system_prompt_written = True

        # TranscriptLogger: 写入 Markdown
        self._transcript.write_system_prompt(system_prompt)

    # ==================== 对话轮次 ====================

    def start_turn(self, turn: int, timestamp: str = None):
        """开始新的对话轮次"""
        self._sync_turn(turn)

        # TranscriptLogger: 写入轮次标题
        self._transcript.start_turn(turn, timestamp)

    def log_user_input(self, content: str):
        """记录用户输入（宿主指令）"""
        # ConversationLogger: JSON 日志
        self._conversation.log_user_input(content)

        # TranscriptLogger: Markdown 格式
        self._transcript.write_user_input(content)

    # ==================== LLM 交互 ====================

    def log_llm_request(self, messages: list, model: str = None):
        """记录发送给 LLM 的请求"""
        # ConversationLogger: JSON 日志
        self._conversation.log_llm_request(messages, model=model)

    def log_llm_response(self, content: str, raw_response: str = None):
        """记录 LLM 的响应"""
        # ConversationLogger: JSON 日志
        self._conversation.log_llm_response(content, raw_response)

        # TranscriptLogger: Markdown 格式
        self._transcript.write_llm_response(content)

    def log_llm_thinking(self, thinking: str):
        """记录 LLM 的思考过程"""
        # TranscriptLogger: Markdown 格式（带折叠）
        self._transcript.write_llm_response("", thinking)

    def log_llm_intent(self, intent: str, content_preview: str = None):
        """记录 LLM 的意图/思考"""
        # ConversationLogger: JSON 日志
        self._conversation.log_llm_intent(intent, content_preview)

    # ==================== 工具调用 ====================

    def log_tool_call(
        self,
        tool_name: str,
        args: dict,
        result: str = None,
        status: str = "success"
    ):
        """记录工具调用"""
        # ConversationLogger: JSON 日志
        self._conversation.log_tool_call(tool_name, args, result, status)

        # TranscriptLogger: Markdown 格式
        self._transcript.write_tool_call(tool_name, args, result, status)

    # ==================== 特殊事件 ====================

    def log_compression(self, before_tokens: int, after_tokens: int, saved_tokens: int):
        """记录上下文压缩"""
        # ConversationLogger: JSON 日志
        self._conversation.log_compression(before_tokens, after_tokens, saved_tokens)

    def log_action(self, action: str, details: dict = None):
        """记录特殊动作（restart/hibernated/skip 等）"""
        # ConversationLogger: JSON 日志
        self._conversation.log_action(action, details)

        # TranscriptLogger: Markdown 格式
        self._transcript.write_action(action, details)

    def log_error(self, error_type: str, error_msg: str, traceback: str = None):
        """记录错误"""
        # ConversationLogger: JSON 日志
        self._conversation.log_error(error_type, error_msg, traceback)

    # ==================== 会话管理 ====================

    def end_session(self, summary: dict = None):
        """结束会话"""
        # ConversationLogger: JSON 日志
        self._conversation.end_session(summary)

    # ==================== 便捷属性（向后兼容） ====================

    @property
    def _turn_count(self) -> int:
        """获取当前轮次（向后兼容）"""
        return self._conversation._turn_count

    @_turn_count.setter
    def _turn_count(self, value: int):
        """设置当前轮次（向后兼容）"""
        self._conversation._turn_count = value


# 全局统一日志管理器实例
logger = UnifiedLogger()


def get_logger() -> UnifiedLogger:
    """获取全局 UnifiedLogger 实例"""
    return logger


# 向后兼容：保留原有的 conversation_logger 引用
def get_conversation_logger() -> ConversationLogger:
    """获取 ConversationLogger 实例（向后兼容）"""
    return logger.conversation


def get_transcript_logger() -> TranscriptLogger:
    """获取 TranscriptLogger 实例（向后兼容）"""
    return logger.transcript
