# -*- coding: utf-8 -*-
"""Agent-scoped LLM slot resolution.

This module keeps Agent llmBindings as the source of truth and returns a
runtime config where the selected slot is mapped onto the existing primary
profile contract.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from config import AppConfig
from config.models import LLMProfile, PromptCacheConfig

from .discovery import discover_model
from .reasoning_effort import model_supports_gpt_reasoning_effort, normalize_reasoning_effort
from .types import LLMCapabilities, ResolvedModelSpec


DEFAULT_AGENT_LLM_SLOT = "dialogue"
AGENT_LLM_SLOT_DIALOGUE = DEFAULT_AGENT_LLM_SLOT
AGENT_LLM_SLOT_MENTAL_MODEL = "mentalModel"
AGENT_LLM_SLOT_SUMMARY = "summary"
AGENT_LLM_SLOT_SUBAGENT_PLANNING = "subagentPlanning"
AGENT_LLM_SLOT_SUBAGENT_EXECUTION = "subagentExecution"
AGENT_LLM_SLOT_VISION = "vision"
AGENT_LLM_SLOTS = (
    AGENT_LLM_SLOT_DIALOGUE,
    AGENT_LLM_SLOT_MENTAL_MODEL,
    AGENT_LLM_SLOT_SUMMARY,
    AGENT_LLM_SLOT_SUBAGENT_PLANNING,
    AGENT_LLM_SLOT_SUBAGENT_EXECUTION,
    AGENT_LLM_SLOT_VISION,
)
DEFAULT_RUNTIME_PROFILE_ID = "primary"


@dataclass(frozen=True)
class ResolvedAgentLlm:
    agent_id: str = ""
    slot: str = DEFAULT_AGENT_LLM_SLOT
    requested_slot: str = DEFAULT_AGENT_LLM_SLOT
    model_id: str = ""
    runtime_profile_id: str = DEFAULT_RUNTIME_PROFILE_ID
    provider_id: str = ""
    provider_kind: str = ""
    model: str = ""
    source: str = "agent_llm_bindings"
    fallback_chain: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    capabilities: LLMCapabilities | None = None
    resolved_spec: ResolvedModelSpec | None = None
    config: AppConfig | None = field(default=None, repr=False, compare=False)

    def log_fields(self) -> dict[str, Any]:
        return {
            "agentId": self.agent_id,
            "llmSlot": self.slot,
            "requestedLlmSlot": self.requested_slot,
            "llmModelId": self.model_id,
            "runtimeProfileId": self.runtime_profile_id,
            "providerId": self.provider_id,
            "providerKind": self.provider_kind,
            "model": self.model,
            "llmBindingSource": self.source,
            "llmFallbackChain": list(self.fallback_chain),
            "llmWarnings": list(self.warnings),
            **capability_log_fields(self.capabilities),
        }


class AgentLlmResolutionError(ValueError):
    """Raised when an Agent LLM slot cannot be resolved."""


def normalize_agent_llm_slot(slot: Any) -> str:
    normalized = str(slot or "").strip() or DEFAULT_AGENT_LLM_SLOT
    return normalized if normalized in AGENT_LLM_SLOTS else DEFAULT_AGENT_LLM_SLOT


def normalize_agent_llm_bindings(value: Any) -> dict[str, dict[str, str]]:
    raw = value if isinstance(value, dict) else {}
    normalized: dict[str, dict[str, str]] = {}
    for slot in AGENT_LLM_SLOTS:
        item = raw.get(slot) if isinstance(raw.get(slot), dict) else {}
        model_id = str(item.get("modelId") or item.get("model_id") or "").strip()
        if model_id:
            normalized[slot] = {"modelId": model_id}
    return normalized


def agent_llm_model_id(
    agent: dict[str, Any] | None,
    slot: str,
    *,
    fallback_to_dialogue: bool = False,
) -> str:
    if not isinstance(agent, dict):
        return ""
    bindings = normalize_agent_llm_bindings(agent.get("llmBindings"))
    normalized_slot = normalize_agent_llm_slot(slot)
    model_id = str(bindings.get(normalized_slot, {}).get("modelId") or "").strip()
    if model_id or not fallback_to_dialogue or normalized_slot == DEFAULT_AGENT_LLM_SLOT:
        return model_id
    return str(bindings.get(DEFAULT_AGENT_LLM_SLOT, {}).get("modelId") or "").strip()


def agent_dialogue_model_id(agent: dict[str, Any] | None) -> str:
    return agent_llm_model_id(agent, DEFAULT_AGENT_LLM_SLOT)


def resolve_agent_llm(
    agent: dict[str, Any] | None,
    slot: str = DEFAULT_AGENT_LLM_SLOT,
    *,
    config: AppConfig,
    runtime_profile_id: str = DEFAULT_RUNTIME_PROFILE_ID,
    fallback_to_dialogue: bool | None = None,
) -> ResolvedAgentLlm:
    requested_slot = normalize_agent_llm_slot(slot)
    should_fallback = requested_slot != DEFAULT_AGENT_LLM_SLOT if fallback_to_dialogue is None else bool(fallback_to_dialogue)
    effective_slot = requested_slot
    bindings = normalize_agent_llm_bindings((agent or {}).get("llmBindings") if isinstance(agent, dict) else {})
    model_id = str(bindings.get(effective_slot, {}).get("modelId") or "").strip()
    fallback_chain: list[str] = []
    warnings: list[str] = []
    if not model_id and should_fallback and requested_slot != DEFAULT_AGENT_LLM_SLOT:
        fallback_chain.append(f"{requested_slot}->{DEFAULT_AGENT_LLM_SLOT}")
        effective_slot = DEFAULT_AGENT_LLM_SLOT
        model_id = str(bindings.get(DEFAULT_AGENT_LLM_SLOT, {}).get("modelId") or "").strip()
        if model_id:
            warnings.append(f"slot `{requested_slot}` missing; fell back to dialogue")
    if not model_id:
        raise AgentLlmResolutionError(f"Agent {requested_slot} LLM binding is required.")

    runtime_config = config_for_agent_llm_model(
        config,
        model_id=model_id,
        runtime_profile_id=runtime_profile_id,
        slot=effective_slot,
    )
    profile = runtime_config.llm.get_profile(profile_id=runtime_profile_id)
    provider = runtime_config.llm.get_provider(profile.provider_id)
    _apply_agent_reasoning_effort_override(agent, effective_slot, profile, provider)
    spec = discover_model(runtime_config, runtime_profile_id)
    return ResolvedAgentLlm(
        agent_id=str((agent or {}).get("agentId") or "").strip() if isinstance(agent, dict) else "",
        slot=effective_slot,
        requested_slot=requested_slot,
        model_id=model_id,
        runtime_profile_id=runtime_profile_id,
        provider_id=profile.provider_id,
        provider_kind=provider.kind,
        model=profile.model,
        source="agent_llm_bindings",
        fallback_chain=fallback_chain,
        warnings=warnings,
        capabilities=spec.capabilities,
        resolved_spec=spec,
        config=runtime_config,
    )


def config_for_agent_llm_model(
    config: AppConfig,
    *,
    model_id: str,
    runtime_profile_id: str = DEFAULT_RUNTIME_PROFILE_ID,
    slot: str = DEFAULT_AGENT_LLM_SLOT,
) -> AppConfig:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        raise AgentLlmResolutionError(f"Agent {slot} LLM binding is required.")
    runtime_config = copy.deepcopy(config)
    model_library = getattr(runtime_config.llm, "model_library", {}) or {}
    entry = model_library.get(normalized_model_id) if isinstance(model_library, dict) else None
    if not isinstance(entry, dict):
        raise AgentLlmResolutionError(f"Agent {slot} model not found in model library: {normalized_model_id}")
    model_name = str(entry.get("model") or "").strip()
    provider_id = str(entry.get("provider_id") or "").strip()
    if not model_name or not provider_id:
        raise AgentLlmResolutionError(f"Agent {slot} model is incomplete: {normalized_model_id}")
    if runtime_config.llm.providers.get(provider_id) is None:
        raise AgentLlmResolutionError(f"Agent {slot} model provider not found: {provider_id}")

    current_primary = copy.deepcopy(runtime_config.llm.get_profile(role=runtime_profile_id))
    selected = LLMProfile(
        **{
            **current_primary.model_dump(),
            **{
                key: entry[key]
                for key in (
                    "transport",
                    "contract",
                    "protocol",
                    "compat",
                    "reasoning_state_field",
                    "strict_compatibility",
                    "temperature",
                    "max_output_tokens",
                    "timeout",
                    "connect_timeout",
                    "streaming",
                    "tool_calling_mode",
                    "discovery_enabled",
                    "prompt_cache",
                    "thinking_type",
                    "thinking_display",
                    "reasoning_effort",
                    "supports_image_input",
                )
                if key in entry
            },
            "profile_id": runtime_profile_id,
            "provider_id": provider_id,
            "model": model_name,
            "api_key_env": str(entry.get("api_key_env") or "").strip(),
            "prompt_cache": entry.get("prompt_cache") if "prompt_cache" in entry else PromptCacheConfig(),
        }
    )
    runtime_config.llm.profiles[runtime_profile_id] = selected
    return runtime_config


def _apply_agent_reasoning_effort_override(
    agent: dict[str, Any] | None,
    slot: str,
    profile: LLMProfile,
    provider: Any,
) -> None:
    if not isinstance(agent, dict):
        return
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    effort_by_slot = metadata.get("llmReasoningEffort") if isinstance(metadata, dict) else {}
    if not isinstance(effort_by_slot, dict):
        return
    effort = normalize_reasoning_effort(effort_by_slot.get(slot))
    if not effort:
        return
    if not model_supports_gpt_reasoning_effort(
        model=profile.model,
        provider_kind=getattr(provider, "kind", ""),
        transport=profile.transport,
        compat_mode=getattr(provider, "compat_mode", ""),
        provider_api=getattr(provider, "api", ""),
    ):
        return
    profile.reasoning_effort = effort


def capability_log_fields(capabilities: LLMCapabilities | None) -> dict[str, Any]:
    if capabilities is None:
        return {}
    return {
        "supportsStreaming": bool(capabilities.supports_streaming),
        "supportsToolCalling": bool(capabilities.supports_tool_calling),
        "supportsImageInput": bool(capabilities.supports_image_input),
        "supportsPromptCache": bool(capabilities.supports_prompt_cache),
        "supportsThinking": bool(capabilities.supports_thinking),
        "supportsReasoningRoundtrip": bool(capabilities.supports_reasoning_roundtrip),
        "supportsExplicitToolChoice": bool(capabilities.supports_explicit_tool_choice),
        "supportsStreamUsage": bool(capabilities.supports_stream_usage),
        "supportsResponsesTransport": bool(capabilities.supports_responses_transport),
        "supportsStructuredContent": bool(capabilities.supports_structured_content),
    }


__all__ = [
    "AGENT_LLM_SLOT_DIALOGUE",
    "AGENT_LLM_SLOT_MENTAL_MODEL",
    "AGENT_LLM_SLOT_SUMMARY",
    "AGENT_LLM_SLOT_SUBAGENT_EXECUTION",
    "AGENT_LLM_SLOT_SUBAGENT_PLANNING",
    "AGENT_LLM_SLOT_VISION",
    "AGENT_LLM_SLOTS",
    "AgentLlmResolutionError",
    "ResolvedAgentLlm",
    "agent_dialogue_model_id",
    "agent_llm_model_id",
    "capability_log_fields",
    "config_for_agent_llm_model",
    "normalize_agent_llm_bindings",
    "normalize_agent_llm_slot",
    "resolve_agent_llm",
]
