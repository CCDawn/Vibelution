# -*- coding: utf-8 -*-
"""系统提示词组装器 — 章节计算、排序、拼接、前缀分割"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

from core.prompt_manager.types import (
    SystemPrompt,
    SystemPromptSection,
    as_system_prompt,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
)
from core.prompt_manager.section_cache import SystemPromptCache


def get_system_prompt(
    sections: List[SystemPromptSection],
    cache: SystemPromptCache,
) -> SystemPrompt:
    """组装 SystemPrompt。

    流程：
    1. 按 priority 排序
    2. 计算每个章节内容 —— 静态章节走缓存，动态章节每轮重算
    3. 在最后一个静态章节之后插入边界标记
    4. 返回 SystemPrompt 元组

    Args:
        sections: 已筛选的章节列表。
        cache: 章节级缓存实例。

    Returns:
        组装完成的 SystemPrompt。
    """
    sorted_sections = sorted(sections, key=lambda s: s.priority)

    parts: List[str] = []
    found_boundary = False

    for section in sorted_sections:
        if section.cache_break:
            # 动态章节：每轮重算，不读缓存
            content = section.compute()
            # 在第一个动态章节前插入边界标记
            if not found_boundary and content:
                parts.append(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
                found_boundary = True
        else:
            # 静态章节：优先从缓存读取
            if cache.has(section.name):
                content = cache.get(section.name)
            else:
                content = section.compute()
                cache.set(section.name, content)

        if content:
            parts.append(content)

    # 可用章节提示（精简为一行，跳过空章节）
    available = _build_available_sections(sorted_sections)
    if available:
        parts.insert(0, available)

    return as_system_prompt(parts)


def split_sys_prompt_prefix(sp: SystemPrompt):
    """按边界标记分割 SystemPrompt 为 (static_parts, dynamic_parts)。

    用于 API 缓存优化：静态前缀可标记为 global 缓存，动态后缀不缓存。
    """
    boundary_idx = -1
    for i, s in enumerate(sp):
        if s == SYSTEM_PROMPT_DYNAMIC_BOUNDARY:
            boundary_idx = i
            break

    if boundary_idx == -1:
        return (tuple(sp), ())

    static = tuple(s for i, s in enumerate(sp) if i < boundary_idx)
    dynamic = tuple(
        s for i, s in enumerate(sp)
        if i > boundary_idx and s != SYSTEM_PROMPT_DYNAMIC_BOUNDARY
    )
    return (static, dynamic)


def to_string(sp: SystemPrompt) -> str:
    """将 SystemPrompt 拼接为单一字符串（跳过边界标记）。"""
    return "\n\n".join(s for s in sp if s != SYSTEM_PROMPT_DYNAMIC_BOUNDARY)


def _build_available_sections(sections: List[SystemPromptSection]) -> str:
    """生成可用章节提示（精简为一行，跳过无内容空章节）。"""
    # 只列出有实际内容或非空的章节
    active = [s for s in sections if not s.is_empty]
    if not active:
        return ""

    required_names = "、".join(s.name for s in active if s.required)
    optional_names = "、".join(s.name for s in active if not s.required)

    parts = ["## 提示词组件\n"]
    if required_names:
        parts.append(f"- 必选: {required_names}\n")
    if optional_names:
        parts.append(f"- 可选: {optional_names}\n")
        parts.append("- 使用 `<active_components>` 标签按需激活可选组件\n")

    return "".join(parts)
