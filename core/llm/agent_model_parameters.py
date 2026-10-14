"""Pure helpers for Agent-scoped, model-keyed runtime parameters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


AGENT_MODEL_PARAMETERS_METADATA_KEY = "llmModelParameters"
LEGACY_REASONING_EFFORT_METADATA_KEY = "llmReasoningEffort"
_DIALOGUE_SLOT = "dialogue"


class AgentModelParametersError(ValueError):
    """Raised when a model-scoped Agent parameter is invalid."""


def _positive_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        normalized = int(value.strip())
    else:
        return 0
    return normalized if normalized > 0 else 0


def _normalized_effort(value: Any) -> str:
    return str(value or "").strip().lower()


def resolve_agent_model_parameters(
    agent: Mapping[str, Any] | None,
    model_ref: str,
) -> dict[str, Any]:
    """Resolve one Agent's entry for a canonical ``modelRef``.

    ``has_reasoning_effort`` distinguishes an explicitly cleared value from a
    missing value, so an explicit empty string can restore the model default
    without falling through to the legacy per-slot setting.
    """
    normalized_ref = str(model_ref or "").strip()
    metadata = agent.get("metadata") if isinstance(agent, Mapping) else None
    metadata = metadata if isinstance(metadata, Mapping) else {}
    parameters_by_model = metadata.get(AGENT_MODEL_PARAMETERS_METADATA_KEY)
    parameters_by_model = parameters_by_model if isinstance(parameters_by_model, Mapping) else {}
    raw_entry = parameters_by_model.get(normalized_ref)
    has_entry = isinstance(raw_entry, Mapping)
    entry = raw_entry if has_entry else {}
    legacy_by_slot = metadata.get(LEGACY_REASONING_EFFORT_METADATA_KEY)
    legacy_by_slot = legacy_by_slot if isinstance(legacy_by_slot, Mapping) else {}
    return {
        "model_ref": normalized_ref,
        "context_window": _positive_int(entry.get("contextWindow")),
        "reasoning_effort": _normalized_effort(entry.get("reasoningEffort")),
        "has_entry": has_entry,
        "has_context_window": has_entry and "contextWindow" in entry,
        "has_reasoning_effort": has_entry and "reasoningEffort" in entry,
        "legacy_reasoning_effort": _normalized_effort(legacy_by_slot.get(_DIALOGUE_SLOT)),
    }


def resolve_agent_model_context_window(
    agent: Mapping[str, Any] | None,
    model_ref: str,
    declared_context_window: Any,
    *,
    declared_source: str = "model_library",
) -> dict[str, Any]:
    """Return an effective context limit bounded by the model declaration."""
    declared = _positive_int(declared_context_window)
    parameters = resolve_agent_model_parameters(agent, model_ref)
    configured = parameters["context_window"]
    if declared <= 0:
        return {
            "limit": 0,
            "max_limit": 0,
            "model_ref": parameters["model_ref"],
            "source": "missing",
            "has_override": parameters["has_context_window"],
        }
    if configured > 0:
        return {
            "limit": min(configured, declared),
            "max_limit": declared,
            "model_ref": parameters["model_ref"],
            "source": "agent_model_parameters",
            "has_override": True,
        }
    return {
        "limit": declared,
        "max_limit": declared,
        "model_ref": parameters["model_ref"],
        "source": str(declared_source or "model_library"),
        "has_override": False,
    }


def validate_agent_model_parameters(
    *,
    context_window: Any,
    reasoning_effort: Any,
    max_context_window: Any,
    supported_reasoning_efforts: Sequence[Any] = (),
) -> dict[str, Any]:
    """Validate and normalize values received by the Agent parameter writer."""
    if isinstance(context_window, bool) or not isinstance(context_window, int):
        raise AgentModelParametersError("contextWindow must be a positive integer.")
    if isinstance(max_context_window, bool) or not isinstance(max_context_window, int):
        maximum = _positive_int(max_context_window)
    else:
        maximum = max_context_window
    normalized_context = context_window
    if normalized_context <= 0:
        raise AgentModelParametersError("contextWindow must be a positive integer.")
    if maximum <= 0:
        raise AgentModelParametersError("The model has no declared max context window.")
    if normalized_context > maximum:
        raise AgentModelParametersError("contextWindow cannot exceed the model's declared max context window.")

    normalized_effort = _normalized_effort(reasoning_effort)
    supported = {
        _normalized_effort(value)
        for value in supported_reasoning_efforts
        if _normalized_effort(value)
    }
    if normalized_effort and normalized_effort not in supported:
        raise AgentModelParametersError("The selected reasoning effort is not supported by this model.")
    return {
        "contextWindow": normalized_context,
        "reasoningEffort": normalized_effort,
    }


def merge_agent_model_parameter_entry(
    metadata: Mapping[str, Any] | None,
    model_ref: str,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy metadata and replace only the selected canonical model entry."""
    normalized_ref = str(model_ref or "").strip()
    if not normalized_ref:
        raise AgentModelParametersError("modelRef is required.")
    result = dict(metadata) if isinstance(metadata, Mapping) else {}
    current_by_model = result.get(AGENT_MODEL_PARAMETERS_METADATA_KEY)
    current_by_model = dict(current_by_model) if isinstance(current_by_model, Mapping) else {}
    current_entry = current_by_model.get(normalized_ref)
    merged_entry = dict(current_entry) if isinstance(current_entry, Mapping) else {}
    if "contextWindow" in values:
        merged_entry["contextWindow"] = _positive_int(values.get("contextWindow"))
    if "reasoningEffort" in values:
        merged_entry["reasoningEffort"] = _normalized_effort(values.get("reasoningEffort"))
    current_by_model[normalized_ref] = merged_entry
    result[AGENT_MODEL_PARAMETERS_METADATA_KEY] = current_by_model
    return result


def sync_dialogue_reasoning_effort_to_model(
    metadata: Mapping[str, Any] | None,
    model_ref: str,
    reasoning_effort: Any,
) -> dict[str, Any]:
    """Keep the Agent editor's legacy dialogue control aligned to its model."""
    return merge_agent_model_parameter_entry(
        metadata,
        model_ref,
        {"reasoningEffort": _normalized_effort(reasoning_effort)},
    )


__all__ = [
    "AGENT_MODEL_PARAMETERS_METADATA_KEY",
    "AgentModelParametersError",
    "LEGACY_REASONING_EFFORT_METADATA_KEY",
    "merge_agent_model_parameter_entry",
    "resolve_agent_model_context_window",
    "resolve_agent_model_parameters",
    "sync_dialogue_reasoning_effort_to_model",
    "validate_agent_model_parameters",
]
