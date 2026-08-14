from __future__ import annotations

from config.models import ExternalAgentGatewayConfig
from core.agent_protocol import ProtocolDirection, ProtocolFamily, ProtocolOperation
from core.web.services.external_agent.protocol_routing import (
    build_managed_mcp_adapter,
    build_managed_mcp_binding,
)


def test_managed_mcp_adapter_is_a_compatibility_projection_not_a_second_store() -> None:
    adapter = build_managed_mcp_adapter()

    assert adapter.family is ProtocolFamily.MCP
    assert adapter.direction is ProtocolDirection.INBOUND
    assert adapter.supported_operations == (
        ProtocolOperation.CANCEL,
        ProtocolOperation.DISCOVER,
        ProtocolOperation.GET_TASK,
        ProtocolOperation.INVOKE,
    )
    assert not hasattr(adapter, "task_store")
    assert adapter.authority_ref == "external_agent.service"


def test_managed_mcp_binding_projects_existing_operator_ceiling_fail_closed() -> None:
    disabled = build_managed_mcp_binding(
        agent_id="coder",
        gateway=ExternalAgentGatewayConfig(enabled=False),
    )
    assert disabled.enabled is False

    enabled = build_managed_mcp_binding(
        agent_id="coder",
        gateway=ExternalAgentGatewayConfig(
            enabled=True,
            permission_ceiling="workspace_write",
            allowed_agent_ids=["coder"],
        ),
    )
    assert enabled.enabled is True
    assert enabled.policy_ref == "external-agent:workspace_write"
    assert enabled.allowed_operations == (
        ProtocolOperation.CANCEL,
        ProtocolOperation.DISCOVER,
        ProtocolOperation.GET_TASK,
        ProtocolOperation.INVOKE,
    )


def test_managed_mcp_binding_does_not_enable_denied_or_unlisted_agent() -> None:
    gateway = ExternalAgentGatewayConfig(
        enabled=True,
        allowed_agent_ids=["reviewer"],
        denied_agent_ids=["blocked"],
    )

    assert build_managed_mcp_binding(agent_id="coder", gateway=gateway).enabled is False
    assert build_managed_mcp_binding(agent_id="blocked", gateway=gateway).enabled is False
