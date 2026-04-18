# -*- coding: utf-8 -*-
"""
core/capabilities/prompt_builder.py - 提示词构建器（已废弃）

此文件已迁移到 `core/capabilities/prompt_manager.py`。
保留此文件作为兼容层，后续版本将删除。
"""

# 向后兼容：从新模块重新导出
from core.capabilities.prompt_manager import (
    build_system_prompt,
    build_simple_system_prompt,
    get_prompt_manager,
    PromptManager,
    PromptComponent,
)

__all__ = [
    "build_system_prompt",
    "build_simple_system_prompt",
    "get_prompt_manager",
    "PromptManager",
    "PromptComponent",
]
