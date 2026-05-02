# -*- coding: utf-8 -*-
"""
core/core_prompt/__init__.py - 核心提示词管理器（已废弃）

此模块已迁移到 `core/prompt_manager/prompt_manager.py`。
保留此文件作为兼容层，后续版本将删除。
"""

from core.prompt_manager.prompt_manager import (
    PromptManager,
    get_prompt_manager,
)
from core.prompt_manager.types import SystemPromptSection

# 兼容旧 API
CorePromptManager = PromptManager

__all__ = [
    "CorePromptManager",
    "PromptManager",
    "SystemPromptSection",
    "get_prompt_manager",
]
