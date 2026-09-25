"""Session recovery operator-config contracts (schema, gate, flags, editor)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from config.models import AppConfig, SessionRecoveryConfig
from config.operator_bootstrap import build_default_operator_config
from core.infrastructure.feature_gate import resolve_feature_decision
from core.session_recovery_flags import (
    is_session_recovery_enabled,
    session_recovery_enabled_override,
    session_recovery_max_auto_retries,
)
from core.web.services import config_editor_schema


# ---------------------------------------------------------------------------
# Schema: defaults and bounds
# ---------------------------------------------------------------------------


def test_session_recovery_config_defaults() -> None:
    config = SessionRecoveryConfig()
    assert config.enabled is True
    assert config.max_auto_retries == 2

    app = AppConfig()
    assert app.session_recovery.enabled is True
    assert app.session_recovery.max_auto_retries == 2


@pytest.mark.parametrize("value", [0, 1, 5])
def test_session_recovery_max_auto_retries_accepts_in_range(value: int) -> None:
    assert SessionRecoveryConfig(max_auto_retries=value).max_auto_retries == value


@pytest.mark.parametrize("value", [-1, 6, 99])
def test_session_recovery_max_auto_retries_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValidationError):
        SessionRecoveryConfig(max_auto_retries=value)


# ---------------------------------------------------------------------------
# Feature gate semantics (fail-open default, explicit false, narrowing)
# ---------------------------------------------------------------------------


def test_gate_defaults_to_enabled_without_section() -> None:
    assert resolve_feature_decision("session_recovery", config={}).effective_enabled is True


def test_gate_explicit_false_disables_and_blocks_force_enable() -> None:
    off = resolve_feature_decision(
        "session_recovery",
        config={"session_recovery": {"enabled": False}},
        requested=True,
    )
    assert off.configured_enabled is False
    assert off.effective_enabled is False


def test_gate_request_only_narrows() -> None:
    decision = resolve_feature_decision(
        "session_recovery",
        config={"session_recovery": {"enabled": True}},
        requested=False,
    )
    assert decision.configured_enabled is True
    assert decision.effective_enabled is False
    assert decision.reason == "run_narrowed_disabled"


# ---------------------------------------------------------------------------
# Flags module: enabled gate + ContextVar override
# ---------------------------------------------------------------------------


def test_is_session_recovery_enabled_reads_public_payload() -> None:
    assert is_session_recovery_enabled({}) is True
    assert is_session_recovery_enabled({"session_recovery": {"enabled": True}}) is True
    assert is_session_recovery_enabled({"session_recovery": {"enabled": False}}) is False


def test_session_recovery_enabled_override_narrows_and_restores() -> None:
    payload = {"session_recovery": {"enabled": True}}
    assert is_session_recovery_enabled(payload) is True

    with session_recovery_enabled_override(False):
        assert is_session_recovery_enabled(payload) is False
        # Override may not force-enable an operator-disabled feature.
        assert is_session_recovery_enabled({"session_recovery": {"enabled": False}}) is False

    assert is_session_recovery_enabled(payload) is True


# ---------------------------------------------------------------------------
# Flags module: max_auto_retries defensive read
# ---------------------------------------------------------------------------


def test_max_auto_retries_reads_public_payload_and_object_config() -> None:
    payload = {"session_recovery": {"enabled": True, "max_auto_retries": 3}}
    assert session_recovery_max_auto_retries(payload) == 3

    app = AppConfig()
    app.session_recovery.max_auto_retries = 4
    assert session_recovery_max_auto_retries(app) == 4

    namespace = SimpleNamespace(
        session_recovery=SimpleNamespace(max_auto_retries=1)
    )
    assert session_recovery_max_auto_retries(namespace) == 1


def test_max_auto_retries_falls_back_to_default_when_missing() -> None:
    assert session_recovery_max_auto_retries({}) == 2
    assert session_recovery_max_auto_retries({"session_recovery": {}}) == 2
    assert session_recovery_max_auto_retries({"session_recovery": None}) == 2
    assert session_recovery_max_auto_retries(SimpleNamespace()) == 2


def test_max_auto_retries_clamps_and_coerces() -> None:
    payload = {"session_recovery": {"max_auto_retries": 99}}
    assert session_recovery_max_auto_retries(payload) == 5
    assert session_recovery_max_auto_retries(
        {"session_recovery": {"max_auto_retries": -3}}
    ) == 0
    assert session_recovery_max_auto_retries(
        {"session_recovery": {"max_auto_retries": "4"}}
    ) == 4
    assert session_recovery_max_auto_retries(
        {"session_recovery": {"max_auto_retries": "not-a-number"}}
    ) == 2


# ---------------------------------------------------------------------------
# Bootstrap + config editor SSOT surfaces
# ---------------------------------------------------------------------------


def test_default_operator_config_includes_session_recovery() -> None:
    payload = build_default_operator_config()
    assert payload["session_recovery"] == {"enabled": True, "max_auto_retries": 2}


def test_editor_schema_exposes_session_recovery_section() -> None:
    assert ("session-recovery", "session_recovery") in config_editor_schema.EDITOR_SECTION_SPECS

    payload = {
        "session_recovery": {"enabled": True, "max_auto_retries": 2},
    }
    sections = config_editor_schema.build_editor_sections(payload, "zh")
    section = next(item for item in sections if item["id"] == "session-recovery")
    assert section["title"] == "重启恢复"
    assert section["fieldCount"] == 2

    meta = config_editor_schema.build_editor_meta(payload, "zh")
    assert meta["session_recovery.enabled"]["label"] == "启用重启自动恢复"
    assert meta["session_recovery.enabled"]["kind"] == "boolean"
    retries = meta["session_recovery.max_auto_retries"]
    assert retries["label"] == "自动重发上限"
    assert retries["kind"] == "number"
    assert retries["minimum"] == 0.0
    assert retries["maximum"] == 5.0

    meta_en = config_editor_schema.build_editor_meta(payload, "en")
    assert meta_en["session_recovery.enabled"]["label"] == "Enable Restart Recovery"
    assert meta_en["session_recovery.max_auto_retries"]["label"] == "Max Auto Retries"
