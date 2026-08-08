"""Trusted feature enablement decisions.

Most features stay fail-closed on operator config. Per-turn chat toggles
(``mental_model``) treat an explicit turn request as higher priority than the
operator default: global config is the default when the turn does not say.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

# Explicit session/turn UI request outranks operator default for these features.
# Other trusted features remain fail-closed (request cannot force-enable).
_TURN_PRIORITY_FEATURES = frozenset({"mental_model"})


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
            if part not in current:
                return default
            current = current.get(part)
        else:
            if not hasattr(current, part):
                return default
            current = getattr(current, part, None)
        if current is None:
            return default
    return bool(current)


def _feature_values(config: Any) -> dict[str, bool]:
    return {
        "mental_model": _value(config, "mental_model.enabled"),
        # Default-on turn runtime status (budget/progress inject + rail).
        "runtime_status": _value(config, "runtime_status.enabled", default=True),
        "context_compression": _value(config, "context_compression.enabled"),
        "pet": _value(config, "pet.enabled"),
        "semantic_memory": _value(config, "memory.semantic_memory_enabled"),
        "memory_extraction": _value(config, "memory.llm_extraction_enabled"),
        "memory_summary": _value(config, "memory.llm_summary_enabled"),
        "supervised_evolution": (
            _value(config, "supervised_evolution.enabled")
            and _value(config, "agent.modes.supervised_evolution_enabled")
        ),
        "supervised_mental_model": (
            _value(config, "supervised_evolution.enabled")
            and _value(config, "supervised_evolution.mental_model_enabled")
            and _value(config, "mental_model.enabled")
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
    revision = _config_revision(values)

    if managed_denied:
        return FeatureDecision(
            feature=feature,
            configured_enabled=configured,
            effective_enabled=False,
            source="operator_config",
            reason="managed_policy_denied",
            config_revision=revision,
            run_requested=requested,
            managed_denied=True,
        )

    # Chat/session per-turn toggle: explicit request wins over operator default.
    if feature in _TURN_PRIORITY_FEATURES and requested is not None:
        if requested is True:
            return FeatureDecision(
                feature=feature,
                configured_enabled=configured,
                effective_enabled=True,
                source="turn_request",
                reason="turn_requested_enabled",
                config_revision=revision,
                run_requested=True,
                managed_denied=False,
            )
        return FeatureDecision(
            feature=feature,
            configured_enabled=configured,
            effective_enabled=False,
            source="turn_request",
            reason="run_narrowed_disabled",
            config_revision=revision,
            run_requested=False,
            managed_denied=False,
        )

    # Fail-closed / default path for operator-owned features (and turn-priority
    # features when the turn did not express a preference).
    effective = bool(configured) and requested is not False
    if not configured:
        reason = "operator_config_disabled"
    elif requested is False:
        reason = "run_narrowed_disabled"
        effective = False
    else:
        reason = "operator_config_enabled"
    return FeatureDecision(
        feature=feature,
        configured_enabled=configured,
        effective_enabled=effective,
        source="operator_config",
        reason=reason,
        config_revision=revision,
        run_requested=requested,
        managed_denied=False,
    )


def feature_config_snapshot(config: Any | None = None) -> dict[str, Any]:
    if config is None:
        from config.settings import get_config

        config = get_config()
    values = _feature_values(config)
    decisions = {
        name: resolve_feature_decision(name, config=config)
        for name in values
    }
    return {
        "configRevision": _config_revision(values),
        "source": "operator_config",
        "features": {
            name: {
                "configuredEnabled": decision.configured_enabled,
                "effectiveEnabled": decision.effective_enabled,
                "featureSource": decision.source,
                "featureDecisionReason": decision.reason,
            }
            for name, decision in decisions.items()
        },
    }
