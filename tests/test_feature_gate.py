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
        supervised_evolution=SimpleNamespace(
            enabled=False,
            mental_model_enabled=False,
        ),
        agent=SimpleNamespace(
            modes=SimpleNamespace(
                supervised_evolution_enabled=False,
                self_evolution_enabled=False,
            )
        ),
    )


def test_mental_model_turn_request_outranks_operator_default_off() -> None:
    """Chat 心智开关优先：全局默认关时，下轮显式开仍注入。"""
    decision = resolve_feature_decision(
        "mental_model",
        config=_config(mental_model=False),
        requested=True,
    )
    assert decision.configured_enabled is False
    assert decision.effective_enabled is True
    assert decision.source == "turn_request"
    assert decision.reason == "turn_requested_enabled"


def test_mental_model_without_turn_request_uses_operator_default() -> None:
    off = resolve_feature_decision(
        "mental_model",
        config=_config(mental_model=False),
        requested=None,
    )
    assert off.effective_enabled is False
    assert off.source == "operator_config"
    assert off.reason == "operator_config_disabled"

    on = resolve_feature_decision(
        "mental_model",
        config=_config(mental_model=True),
        requested=None,
    )
    assert on.effective_enabled is True
    assert on.source == "operator_config"
    assert on.reason == "operator_config_enabled"


def test_runtime_request_can_narrow_operator_enabled_feature() -> None:
    decision = resolve_feature_decision(
        "mental_model",
        config=_config(mental_model=True),
        requested=False,
    )
    assert decision.configured_enabled is True
    assert decision.effective_enabled is False
    assert decision.source == "turn_request"
    assert decision.reason == "run_narrowed_disabled"


def test_non_turn_priority_feature_stays_fail_closed() -> None:
    """监督等可信能力仍 fail-closed：run 请求不能强开 operator 关项。"""
    decision = resolve_feature_decision(
        "context_compression",
        config=_config(mental_model=False),
        requested=True,
    )
    assert decision.configured_enabled is False
    assert decision.effective_enabled is False
    assert decision.reason == "operator_config_disabled"


def test_snapshot_contains_safe_feature_provenance() -> None:
    snapshot = feature_config_snapshot(_config(mental_model=True))
    assert snapshot["source"] == "operator_config"
    assert len(snapshot["configRevision"]) == 12
    assert snapshot["features"]["mental_model"]["configuredEnabled"] is True
    assert snapshot["features"]["mental_model"]["featureSource"] == "operator_config"
    assert snapshot["features"]["mental_model"]["featureDecisionReason"] == "operator_config_enabled"


def test_supervised_mental_model_requires_every_operator_gate() -> None:
    config = _config(mental_model=True)
    config.supervised_evolution.enabled = True
    config.agent.modes.supervised_evolution_enabled = True

    decision = resolve_feature_decision(
        "supervised_mental_model",
        config=config,
        requested=True,
    )

    assert decision.configured_enabled is False
    assert decision.effective_enabled is False
    assert decision.reason == "operator_config_disabled"


def test_supervised_mental_model_can_be_narrowed_per_run() -> None:
    config = _config(mental_model=True)
    config.supervised_evolution.enabled = True
    config.supervised_evolution.mental_model_enabled = True
    config.agent.modes.supervised_evolution_enabled = True

    decision = resolve_feature_decision(
        "supervised_mental_model",
        config=config,
        requested=False,
    )

    assert decision.configured_enabled is True
    assert decision.effective_enabled is False
    assert decision.reason == "run_narrowed_disabled"


def test_string_false_does_not_enable_operator_features() -> None:
    decision = resolve_feature_decision(
        "runtime_status",
        config={"runtime_status": {"enabled": "false"}},
    )
    assert decision.configured_enabled is False
    assert decision.effective_enabled is False
    assert decision.reason == "operator_config_disabled"

    bytes_off = resolve_feature_decision(
        "runtime_status",
        config={"runtime_status": {"enabled": b"off"}},
    )
    assert bytes_off.configured_enabled is False
    assert bytes_off.effective_enabled is False

    json_off = resolve_feature_decision(
        "runtime_status",
        config='{"runtime_status": {"enabled": false}}',
    )
    assert json_off.configured_enabled is False
    assert json_off.effective_enabled is False

    compression = resolve_feature_decision(
        "context_compression",
        config={"context_compression": {"enabled": "true"}},
    )
    assert compression.configured_enabled is True
    assert compression.effective_enabled is True


def test_string_requested_flags_are_coerced() -> None:
    enabled = resolve_feature_decision(
        "mental_model",
        config=_config(mental_model=False),
        requested="true",
    )
    assert enabled.effective_enabled is True
    assert enabled.source == "turn_request"
    assert enabled.run_requested is True

    bytes_on = resolve_feature_decision(
        "mental_model",
        config=_config(mental_model=False),
        requested=b"on",
    )
    assert bytes_on.effective_enabled is True

    narrowed = resolve_feature_decision(
        "runtime_status",
        config={"runtime_status": {"enabled": True}},
        requested="false",
    )
    assert narrowed.configured_enabled is True
    assert narrowed.effective_enabled is False
    assert narrowed.reason == "run_narrowed_disabled"
    assert narrowed.run_requested is False

    denied = resolve_feature_decision(
        "runtime_status",
        config={"runtime_status": {"enabled": True}},
        managed_denied="false",
    )
    assert denied.effective_enabled is True
    assert denied.managed_denied is False
