# -*- coding: utf-8 -*-
"""
core/core_prompt/__init__.py - 核心提示词管理器（已废弃）

此模块已迁移到 `core/prompt_manager/prompt_manager.py`。
双轨加载逻辑、CorePromptManager 已整合进 PromptManager。
保留此文件作为兼容层，后续版本将删除。
"""

from core.prompt_manager.prompt_manager import (
    PromptManager,
    PromptComponent,
    get_prompt_manager,
)

# 兼容旧 API
CorePromptManager = PromptManager

__all__ = [
    "CorePromptManager",  # 向后兼容别名
    "PromptManager",
    "PromptComponent",
    "get_prompt_manager",
]
