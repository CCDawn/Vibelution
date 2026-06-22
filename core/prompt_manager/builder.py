# -*- coding: utf-8 -*-
"""系统提示词组装器 — 章节计算、排序、拼接、前缀分割"""

from __future__ import annotations

import time
from typing import Optional, List, Dict, Any

from core.prompt_manager.types import (
    SystemPrompt,
    SystemPromptSection,
    SectionRenderResult,
    PromptBuildResult,
    as_system_prompt,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
)
from core.prompt_manager.section_cache import SystemPromptCache


def get_system_prompt(
    sections: List[SystemPromptSection],
    cache: SystemPromptCache,
    all_sections: Optional[List[SystemPromptSection]] = None,
) -> PromptBuildResult:
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
    prefix_parts: List[str] = []
    dynamic_parts: List[str] = []
    results: List[SectionRenderResult] = []

    for section in sections:
        started = time.perf_counter()
        source = "computed"
        if section.cache_break:
            # 动态章节：每轮重算，不读缓存
            content = section.compute()
        else:
            # 静态章节：优先从缓存读取
            if cache.has(section.name):
                content = cache.get(section.name)
                source = "cache"
            else:
                content = section.compute()
                cache.set(section.name, content)
        duration_ms = (time.perf_counter() - started) * 1000

        rendered = SectionRenderResult(
            name=section.name,
            priority=section.priority,
            required=section.required,
            cache_break=section.cache_break,
            cache_prefix=section.cache_prefix,
            description=section.description,
            content=content,
            is_empty=not bool(content),
            source=source,
            duration_ms=duration_ms,
        )
        results.append(rendered)

        if content:
            if not section.cache_break or section.cache_prefix:
                prefix_parts.append(content)
            else:
                dynamic_parts.append(content)

    # 可用章节提示：基于本次真实渲染结果 + 注册表
    available = _build_available_sections(results, all_sections or sections)
    if available:
        dynamic_parts.insert(0, available)

    parts: List[str] = []
    parts.extend(prefix_parts)
    if dynamic_parts:
        parts.append(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
        parts.extend(dynamic_parts)

    join_started = time.perf_counter()
    prompt = as_system_prompt(parts)
    join_duration_ms = (time.perf_counter() - join_started) * 1000

    return PromptBuildResult(
        prompt=prompt,
        section_results=tuple(results),
        available_sections_text=available,
        join_duration_ms=join_duration_ms,
    )


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


def _build_available_sections(
    results: List[SectionRenderResult],
    sections: List[SystemPromptSection],
) -> str:
    """生成章节索引：优先展示本次真实启用结果，再展示可选能力。"""
    active = [r for r in results if not r.is_empty]
    if not active and not sections:
        return ""

    enabled_names = "、".join(r.name for r in active)
    required_names = "、".join(r.name for r in active if r.required)
    optional_names = "、".join(r.name for r in active if not r.required)

    registered_optional = [
        s.name for s in sections
        if not s.required and s.name not in {r.name for r in active}
    ]
    registered_optional_names = "、".join(registered_optional)

    parts = ["## 提示词组件\n"]
    if enabled_names:
        parts.append(f"- 已启用: {enabled_names}\n")
    if required_names:
        parts.append(f"- 必选: {required_names}\n")
    if optional_names:
        parts.append(f"- 当前可选: {optional_names}\n")
    if registered_optional_names:
        parts.append(f"- 其他可选: {registered_optional_names}\n")
    if optional_names or registered_optional_names:
        parts.append("- 使用 `<active_components>` 标签按需激活可选组件\n")

    return "".join(parts)
