from types import SimpleNamespace

from core.infrastructure.feature_gate import (
    feature_config_snapshot,
    resolve_feature_decision,
)


def _config(*, mental_model: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        mental_model=SimpleNamespace(enabled=mental_model),
        context_compression=SimpleNamespace(enabled=False),
        pet=SimpleNamespace(enabled=False),
        memory=SimpleNamespace(
            semantic_memory_enabled=False,
            llm_extraction_enabled=False,
            llm_summary_enabled=False,
        ),
        supervised_evolution=SimpleNamespace(enabled=False),
        agent=SimpleNamespace(
            modes=SimpleNamespace(
                supervised_evolution_enabled=False,
                self_evolution_enabled=False,
            )
        ),
    )


def test_runtime_request_cannot_enable_operator_disabled_feature() -> None:
    decision = resolve_feature_decision(
        "mental_model",
        config=_config(mental_model=False),
        requested=True,
    )
    assert decision.configured_enabled is False
    assert decision.effective_enabled is False
    assert decision.reason == "operator_config_disabled"


def test_runtime_request_can_narrow_operator_enabled_feature() -> None:
    decision = resolve_feature_decision(
        "mental_model",
        config=_config(mental_model=True),
        requested=False,
    )
    assert decision.configured_enabled is True
    assert decision.effective_enabled is False
    assert decision.reason == "run_narrowed_disabled"


def test_snapshot_contains_safe_feature_provenance() -> None:
    snapshot = feature_config_snapshot(_config(mental_model=True))
    assert snapshot["source"] == "operator_config"
    assert len(snapshot["configRevision"]) == 12
    assert snapshot["features"]["mental_model"]["configuredEnabled"] is True
