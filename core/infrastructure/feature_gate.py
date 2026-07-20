"""Trusted, fail-closed feature enablement decisions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class FeatureDecision:
    feature: str
    configured_enabled: bool
    effective_enabled: bool
    source: str
    reason: str
    config_revision: str
    run_requested: bool | None = None
    managed_denied: bool = False

    def log_fields(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "configuredEnabled": self.configured_enabled,
            "effectiveEnabled": self.effective_enabled,
            "featureSource": self.source,
            "featureDecisionReason": self.reason,
            "configRevision": self.config_revision,
            "runRequested": self.run_requested,
            "managedDenied": self.managed_denied,
        }


def _value(source: Any, path: str, default: bool = False) -> bool:
    current = source
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return default
    return bool(current)


def _feature_values(config: Any) -> dict[str, bool]:
    return {
        "mental_model": _value(config, "mental_model.enabled"),
        "context_compression": _value(config, "context_compression.enabled"),
        "pet": _value(config, "pet.enabled"),
        "semantic_memory": _value(config, "memory.semantic_memory_enabled"),
        "memory_extraction": _value(config, "memory.llm_extraction_enabled"),
        "memory_summary": _value(config, "memory.llm_summary_enabled"),
        "supervised_evolution": (
            _value(config, "supervised_evolution.enabled")
            and _value(config, "agent.modes.supervised_evolution_enabled")
        ),
        "self_evolution": _value(config, "agent.modes.self_evolution_enabled"),
    }


def _config_revision(values: dict[str, bool]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def resolve_feature_decision(
    feature: str,
    *,
    config: Any | None = None,
    requested: bool | None = None,
    managed_denied: bool = False,
) -> FeatureDecision:
    if config is None:
        from config.settings import get_config

        config = get_config()
    values = _feature_values(config)
    if feature not in values:
        raise ValueError(f"Unknown trusted feature: {feature}")

    configured = values[feature]
    effective = configured and requested is not False and not managed_denied
    if managed_denied:
        reason = "managed_policy_denied"
    elif not configured:
        reason = "operator_config_disabled"
    elif requested is False:
        reason = "run_narrowed_disabled"
    else:
        reason = "operator_config_enabled"
    return FeatureDecision(
        feature=feature,
        configured_enabled=configured,
        effective_enabled=effective,
        source="operator_config",
        reason=reason,
        config_revision=_config_revision(values),
        run_requested=requested,
        managed_denied=managed_denied,
    )


def feature_config_snapshot(config: Any | None = None) -> dict[str, Any]:
    if config is None:
        from config.settings import get_config

        config = get_config()
    values = _feature_values(config)
    return {
        "configRevision": _config_revision(values),
        "source": "operator_config",
        "features": {
            name: {
                "configuredEnabled": enabled,
                "effectiveEnabled": enabled,
            }
            for name, enabled in values.items()
        },
    }
