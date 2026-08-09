from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.models import AppConfig, ExternalAgentGatewayConfig
from config.operator_bootstrap import build_default_operator_config
from core.web.services.external_agent.service import build_default_service


def test_external_agent_gateway_config_is_disabled_and_read_only_by_default() -> None:
    config = AppConfig().external_agent_gateway

    assert config.enabled is False
    assert config.permission_ceiling == "read_only"
    assert config.runtime_permission_ceiling == "workspace_write"
    assert config.approval_persist_enabled is False
    assert config.allowed_agent_ids == []
    assert config.denied_agent_ids == []
    assert config.max_concurrent_tasks_per_agent == 1
    assert config.max_concurrent_tasks_per_owner == 4
    assert config.max_task_seconds == 1800
    assert config.lease_seconds == 30


def test_external_agent_gateway_config_validates_profiles_and_limits() -> None:
    configured = ExternalAgentGatewayConfig(
        enabled=True,
        permission_ceiling="workspace_write",
        allowed_agent_ids=[" coder ", "coder", "reviewer"],
        denied_agent_ids=["blocked"],
        max_concurrent_tasks_per_owner=8,
    )

    assert configured.allowed_agent_ids == ["coder", "reviewer"]
    assert configured.denied_agent_ids == ["blocked"]
    with pytest.raises(ValidationError):
        ExternalAgentGatewayConfig(permission_ceiling="auto_review")
    with pytest.raises(ValidationError):
        ExternalAgentGatewayConfig(lease_seconds=2)


def test_generated_operator_config_contains_fail_closed_gateway_section() -> None:
    payload = build_default_operator_config(include_unconfigured_providers=False)

    assert payload["external_agent_gateway"] == {
        "enabled": False,
        "permission_ceiling": "read_only",
        "runtime_permission_ceiling": "workspace_write",
        "approval_persist_enabled": False,
        "allowed_agent_ids": [],
        "denied_agent_ids": [],
        "max_concurrent_tasks_per_owner": 4,
        "max_concurrent_tasks_per_agent": 1,
        "max_task_seconds": 1800,
        "lease_seconds": 30,
    }


def test_default_service_consumes_operator_gateway_limits(
    monkeypatch, tmp_path
) -> None:
    config = AppConfig(
        external_agent_gateway=ExternalAgentGatewayConfig(
            enabled=True,
            permission_ceiling="workspace_write",
            runtime_permission_ceiling="full_access",
            approval_persist_enabled=True,
            allowed_agent_ids=["coder"],
            denied_agent_ids=["blocked"],
            max_concurrent_tasks_per_owner=7,
            max_concurrent_tasks_per_agent=2,
            max_task_seconds=600,
            lease_seconds=45,
        )
    )
    monkeypatch.setattr("config.settings.get_config", lambda: config)

    service = build_default_service(tmp_path)

    assert service.enabled is True
    assert service.operator_permission_ceiling == "workspace_write"
    assert service.runtime_permission_ceiling == "full_access"
    assert service.approval_persist_enabled is True
    assert service.allowed_agent_ids == frozenset({"coder"})
    assert service.denied_agent_ids == frozenset({"blocked"})
    assert service.max_concurrent_tasks_per_owner == 7
    assert service.max_concurrent_tasks_per_agent == 2
    assert service.max_task_seconds == 600
    assert service.lease_seconds == 45
