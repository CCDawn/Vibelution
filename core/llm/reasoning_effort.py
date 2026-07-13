"""Helpers for GPT reasoning effort support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


GPT_REASONING_EFFORT_VALUES = ("low", "medium", "high")
KNOWN_REASONING_EFFORT_VALUES = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def normalize_reasoning_effort(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in KNOWN_REASONING_EFFORT_VALUES:
        return normalized
    return ""


@dataclass(frozen=True)
class ReasoningEffortResolution:
    requested: str
    effective: str
    adapter: str
    payload: dict[str, Any]


def resolve_reasoning_effort_request(profile: Any) -> ReasoningEffortResolution:
    requested = normalize_reasoning_effort(getattr(profile, "reasoning_effort", ""))
    adapter = str(getattr(profile, "reasoning_effort_adapter", "") or "none").strip().lower()
    mapping = dict(getattr(profile, "reasoning_effort_map", {}) or {})
    effective = str(mapping.get(requested) or requested).strip().lower()
    if not requested or adapter == "none":
        return ReasoningEffortResolution(requested, "", "none", {})
    if adapter == "reasoning_object":
        return ReasoningEffortResolution(requested, effective, adapter, {"reasoning": {"effort": effective}})
    if adapter == "reasoning_effort":
        return ReasoningEffortResolution(requested, effective, adapter, {"reasoning_effort": effective})
    if adapter == "thinking_toggle":
        return ReasoningEffortResolution(
            requested,
            effective,
            adapter,
            {"enable_thinking": effective not in {"off", "none"}},
        )
    raise ValueError(f"unsupported reasoning effort adapter: {adapter}")


def model_supports_gpt_reasoning_effort(
    *,
    model: Any,
    provider_kind: Any = "",
    transport: Any = "",
    compat_mode: Any = "",
    provider_api: Any = "",
) -> bool:
    """Return true for GPT models on Responses-capable OpenAI-style routes."""

    model_name = str(model or "").strip().lower()
    if not _model_has_gpt_reasoning_family(model_name):
        return False
    if str(transport or "").strip().lower() != "responses":
        return False

    provider_kind_value = str(provider_kind or "").strip().lower()
    compat_mode_value = str(compat_mode or "").strip().lower()
    provider_api_value = str(provider_api or "").strip().lower().replace("_", "-")
    return (
        provider_kind_value in {"openai", "openai_compatible", "relay", "azure"}
        or compat_mode_value in {"openai", "openai_compatible"}
        or provider_api_value in {"openai", "openai-responses", "responses"}
    )


def _model_has_gpt_reasoning_family(model_name: str) -> bool:
    parts = [part for part in model_name.replace("_", "-").split("/") if part]
    return any(part.startswith("gpt-5") for part in parts)


__all__ = [
    "GPT_REASONING_EFFORT_VALUES",
    "KNOWN_REASONING_EFFORT_VALUES",
    "ReasoningEffortResolution",
    "model_supports_gpt_reasoning_effort",
    "normalize_reasoning_effort",
    "resolve_reasoning_effort_request",
]
