# -*- coding: utf-8 -*-
"""Bounded Prompt adapters derived from resolved LLM protocol facts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from core.prompt_manager.assembly_contract import (
    PromptCachePolicy,
    PromptStability,
    PromptTier,
    PromptTrust,
    estimate_prompt_tokens,
)
from core.prompt_manager.assembly_resolver import (
    PromptAssemblyBudgetError,
    PromptAssemblyContext,
)
from core.prompt_manager.types import SystemPromptSection


PROTOCOL_ADAPTER_MAX_TOKENS = 512


def build_protocol_adapter_section(
    route: Any,
    capabilities: Any,
) -> SystemPromptSection:
    """Return the required T1 adapter for one resolved protocol route."""

    protocol = _value(getattr(route, "protocol", None))
    policy = getattr(route, "policy", None)
    if not protocol or policy is None:
        raise ValueError("missing_resolved_protocol_route")

    tools_enabled = bool(
        getattr(policy, "allow_tools", False)
        and getattr(capabilities, "supports_tool_calling", False)
    )
    parallel_enabled = bool(
        tools_enabled
        and getattr(policy, "allow_parallel_tools", False)
        and getattr(capabilities, "supports_parallel_tool_calls", False)
    )
    system_policy = str(
        getattr(policy, "system_message_policy", "") or "preserve"
    ).strip()
    thinking_shape = str(
        getattr(policy, "thinking_param_shape", "") or "none"
    ).strip()
    lines = [
        "## 模型协议适配",
        f"- 协议: {protocol}",
        f"- 原生工具调用: {'可用' if tools_enabled else '不可用'}",
        f"- 并行工具调用: {'可用' if parallel_enabled else '不可用'}",
        f"- System message 策略: {system_policy}",
        (
            "- Assistant prefill: 可用"
            if bool(getattr(policy, "allow_assistant_prefill", True))
            else "- Assistant prefill: 禁止"
        ),
        (
            f"- Reasoning 传输: {thinking_shape}"
            if thinking_shape != "none"
            else "- Reasoning 传输: 无专用格式"
        ),
    ]
    if not tools_enabled:
        lines.append("- 本轮不要生成工具调用；可直接回答的问题继续纯对话。")
    content = "\n".join(lines)
    if estimate_prompt_tokens(content) > PROTOCOL_ADAPTER_MAX_TOKENS:
        raise PromptAssemblyBudgetError(
            f"protocol_adapter_over_budget:{protocol}"
        )

    return SystemPromptSection(
        name="PROTOCOL_ADAPTER",
        compute=lambda value=content: value,
        cache_break=False,
        cache_prefix=True,
        priority=14,
        description="由 resolved model protocol 和真实能力生成的短适配层",
        required=True,
        tier=PromptTier.PROTOCOL_ADAPTER,
        stability=PromptStability.PROTOCOL_STATIC,
        trust=PromptTrust.DERIVED_RUNTIME,
        cache_policy=PromptCachePolicy.CACHEABLE,
        budget_tokens=PROTOCOL_ADAPTER_MAX_TOKENS,
    )


def build_prompt_assembly_context(
    client: Any,
    *,
    context_window: int = 0,
    max_output_tokens: int = 0,
    allowed_tool_names: Iterable[str] = (),
    allowed_skill_names: Iterable[str] = (),
    allowed_agent_names: Iterable[str] = (),
    permission_fingerprint: str = "",
    enforce_core_floor: bool = True,
) -> PromptAssemblyContext:
    """Project a resolved client into the Prompt Assembly runtime contract."""

    route = getattr(client, "protocol_route", None)
    capabilities = getattr(client, "capabilities", None)
    policy = getattr(route, "policy", None)
    protocol = _value(getattr(route, "protocol", None))
    if route is None or capabilities is None or policy is None or not protocol:
        raise ValueError("missing_resolved_protocol_capabilities")

    resolved_spec = getattr(client, "resolved_spec", None)
    profile = getattr(client, "profile", None)
    resolved_window = max(
        0,
        int(
            context_window
            or getattr(resolved_spec, "context_window", 0)
            or 0
        ),
    )
    resolved_output = max(
        0,
        int(
            max_output_tokens
            or getattr(resolved_spec, "max_output_tokens", 0)
            or getattr(profile, "max_output_tokens", 0)
            or 0
        ),
    )
    tools_enabled = bool(
        getattr(policy, "allow_tools", False)
        and getattr(capabilities, "supports_tool_calling", False)
    )
    capability_names = {
        name
        for name, enabled in {
            "tool_calling": tools_enabled,
            "parallel_tool_calls": (
                tools_enabled
                and getattr(policy, "allow_parallel_tools", False)
                and getattr(capabilities, "supports_parallel_tool_calls", False)
            ),
            "system_messages": getattr(capabilities, "supports_system_messages", False),
            "json_mode": getattr(capabilities, "supports_json_mode", False),
            "thinking": getattr(capabilities, "supports_thinking", False),
            "reasoning_roundtrip": getattr(
                capabilities,
                "supports_reasoning_roundtrip",
                False,
            ),
            "prompt_cache": getattr(capabilities, "supports_prompt_cache", False),
        }.items()
        if enabled
    }
    allowed_tools = (
        _normalized_names(allowed_tool_names)
        if tools_enabled
        else ()
    )
    capability_fingerprint = _fingerprint(
        {
            "protocol": protocol,
            "capabilities": sorted(capability_names),
            "adapter": str(getattr(route, "adapter_id", "") or "").strip(),
        }
    )
    resolved_permission_fingerprint = (
        str(permission_fingerprint or "").strip()
        or _fingerprint({"tools": list(allowed_tools)})
    )
    return PromptAssemblyContext(
        context_window=resolved_window,
        max_output_tokens=resolved_output,
        capabilities=frozenset(capability_names),
        allowed_tools=allowed_tools,
        allowed_skills=_normalized_names(allowed_skill_names),
        allowed_agents=_normalized_names(allowed_agent_names),
        model_protocol=protocol,
        capability_fingerprint=capability_fingerprint,
        permission_fingerprint=resolved_permission_fingerprint,
        enforce_core_floor=bool(enforce_core_floor),
        assembly_mode="v2",
    )


def client_supports_tool_calling(client: Any) -> bool:
    route = getattr(client, "protocol_route", None)
    policy = getattr(route, "policy", None)
    capabilities = getattr(client, "capabilities", None)
    if policy is None or capabilities is None:
        return True
    return bool(
        getattr(policy, "allow_tools", False)
        and getattr(capabilities, "supports_tool_calling", False)
    )


def _normalized_names(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value or "").strip()
                for value in values
                if str(value or "").strip()
            }
        )
    )


def _value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "PROTOCOL_ADAPTER_MAX_TOKENS",
    "build_prompt_assembly_context",
    "build_protocol_adapter_section",
    "client_supports_tool_calling",
]
