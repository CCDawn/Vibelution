# -*- coding: utf-8 -*-
"""系统提示词组装器 — 章节计算、排序、拼接、前缀分割"""

from __future__ import annotations

import time
from typing import Optional, List, Dict, Any

from core.prompt_manager.assembly_contract import (
    PromptAssemblyManifest,
    PromptCachePolicy,
    PromptDecision,
    PromptPlacement,
    PromptSegment,
    PromptStability,
    PromptTier,
    PromptTrust,
)
from core.prompt_manager.assembly_resolver import (
    PromptAssemblyContext,
    PromptSectionResolver,
)
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
    assembly_context: PromptAssemblyContext | None = None,
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
            tier=section.tier,
            stability=section.stability,
            trust=section.trust,
            cache_policy=section.cache_policy,
            budget_tokens=section.budget_tokens,
            capability_requirements=section.capability_requirements,
        )
        results.append(rendered)

        if content:
            if not section.cache_break or section.cache_prefix:
                prefix_parts.append(content)
            else:
                dynamic_parts.append(content)

    # 可用章节提示：基于本次真实渲染结果 + 注册表
    available = _build_available_sections(
        results,
        all_sections or sections,
        capabilities=(
            assembly_context.capabilities
            if assembly_context is not None
            else None
        ),
    )
    if available:
        dynamic_parts.insert(0, available)

    prefix_results = [
        result
        for result in results
        if result.content and (not result.cache_break or result.cache_prefix)
    ]
    dynamic_results = [
        result
        for result in results
        if result.content and result.cache_break and not result.cache_prefix
    ]
    omitted_results = [result for result in results if not result.content]
    manifest_segments = [_segment_from_render_result(result) for result in prefix_results]
    if available:
        manifest_segments.append(
            PromptSegment.from_content(
                key="AVAILABLE_SECTIONS",
                content=available,
                tier=PromptTier.TURN_CONTEXT,
                placement=PromptPlacement.BEFORE_CURRENT_USER,
                stability=PromptStability.TURN_DYNAMIC,
                trust=PromptTrust.DERIVED_RUNTIME,
                source="prompt_manager.builder",
                cache_policy=PromptCachePolicy.NEVER_CACHE,
                decision=PromptDecision.FULL,
                decision_reason="rendered_section_index",
            )
        )
    manifest_segments.extend(_segment_from_render_result(result) for result in dynamic_results)
    manifest_segments.extend(_segment_from_render_result(result) for result in omitted_results)
    if assembly_context is None:
        assembly_manifest = PromptAssemblyManifest.from_segments(manifest_segments)
    else:
        resolution = PromptSectionResolver().resolve(
            manifest_segments,
            assembly_context,
        )
        manifest_segments = list(resolution.segments)
        assembly_manifest = resolution.manifest
        prefix_parts = [
            segment.content
            for segment in manifest_segments
            if segment.content
            and segment.placement == PromptPlacement.SYSTEM_PREFIX
            and segment.decision
            not in {PromptDecision.OMITTED, PromptDecision.BLOCKED}
        ]
        dynamic_parts = [
            segment.content
            for segment in manifest_segments
            if segment.content
            and segment.placement == PromptPlacement.BEFORE_CURRENT_USER
            and segment.decision
            not in {PromptDecision.OMITTED, PromptDecision.BLOCKED}
        ]

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
        assembly_manifest=assembly_manifest,
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
    *,
    capabilities: frozenset[str] | None = None,
) -> str:
    """生成章节索引：优先展示本次真实启用结果，再展示可选能力。"""
    eligible_results = [
        result
        for result in results
        if capabilities is None
        or set(result.capability_requirements).issubset(capabilities)
    ]
    eligible_sections = [
        section
        for section in sections
        if capabilities is None
        or set(section.capability_requirements).issubset(capabilities)
    ]
    active = [r for r in eligible_results if not r.is_empty]
    if not active and not eligible_sections:
        return ""

    enabled_names = "、".join(r.name for r in active)
    required_names = "、".join(r.name for r in active if r.required)
    optional_names = "、".join(r.name for r in active if not r.required)

    registered_optional = [
        s.name for s in eligible_sections
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
    return "".join(parts)


def _segment_from_render_result(result: SectionRenderResult) -> PromptSegment:
    is_core = result.name in {"COMMON", "SOUL", "AGENTS"}
    is_protocol_adapter = result.name == "PROTOCOL_ADAPTER"
    is_prefix = (
        result.tier
        in {
            PromptTier.STABLE_CORE,
            PromptTier.PROTOCOL_ADAPTER,
            PromptTier.SESSION_SNAPSHOT,
        }
        if result.tier is not None
        else not result.cache_break or result.cache_prefix
    )
    if result.tier is not None:
        tier = result.tier
        stability = result.stability or PromptStability.TURN_DYNAMIC
        trust = result.trust or PromptTrust.DERIVED_RUNTIME
    elif is_core:
        tier = PromptTier.STABLE_CORE
        stability = PromptStability.PROJECT_STATIC
        trust = PromptTrust.PROTECTED_CORE
    elif is_protocol_adapter:
        tier = PromptTier.PROTOCOL_ADAPTER
        stability = PromptStability.PROTOCOL_STATIC
        trust = PromptTrust.DERIVED_RUNTIME
    elif is_prefix:
        tier = PromptTier.SESSION_SNAPSHOT
        stability = PromptStability.SESSION_STATIC
        trust = PromptTrust.OPERATOR_CONTROLLED
    else:
        tier = PromptTier.TURN_CONTEXT
        stability = PromptStability.TURN_DYNAMIC
        trust = PromptTrust.DERIVED_RUNTIME
    decision = PromptDecision.FULL if result.content else PromptDecision.OMITTED
    return PromptSegment.from_content(
        key=result.name,
        content=result.content or "",
        tier=tier,
        placement=(
            PromptPlacement.SYSTEM_PREFIX
            if is_prefix
            else PromptPlacement.BEFORE_CURRENT_USER
        ),
        stability=stability,
        trust=trust,
        source=f"prompt_manager.section.{result.name.lower()}",
        required=result.required,
        budget_tokens=result.budget_tokens,
        cache_policy=result.cache_policy or (
            PromptCachePolicy.CACHEABLE
            if is_prefix
            else PromptCachePolicy.NEVER_CACHE
        ),
        capability_requirements=result.capability_requirements,
        decision=decision,
        decision_reason="rendered" if result.content else "empty",
        cache_hit=result.source == "cache",
    )
