"""Compatibility projection from the managed MCP gateway into Agent routing.

The existing external_agent service remains the sole task-lifecycle authority.
This module creates immutable routing metadata only.
"""

from __future__ import annotations

from config.models import ExternalAgentGatewayConfig
from core.agent_protocol import (
    AgentProtocolBinding,
    ProtocolAdapterDefinition,
    ProtocolDirection,
    ProtocolFamily,
    ProtocolOperation,
    ProtocolTransport,
)


_MANAGED_MCP_OPERATIONS = (
    ProtocolOperation.CANCEL,
    ProtocolOperation.DISCOVER,
    ProtocolOperation.GET_TASK,
    ProtocolOperation.INVOKE,
)


def build_managed_mcp_adapter() -> ProtocolAdapterDefinition:
    return ProtocolAdapterDefinition(
        adapter_id="managed-mcp-gateway",
        family=ProtocolFamily.MCP,
        protocol_version="2025-06-18+vibelution-managed-agent-v1",
        transport=ProtocolTransport.STDIO,
        direction=ProtocolDirection.INBOUND,
        supported_operations=_MANAGED_MCP_OPERATIONS,
        authority_ref="external_agent.service",
    )


def build_managed_mcp_binding(
    *, agent_id: str, gateway: ExternalAgentGatewayConfig
) -> AgentProtocolBinding:
    normalized_agent_id = str(agent_id or "").strip()
    explicitly_allowed = (
        not gateway.allowed_agent_ids or normalized_agent_id in gateway.allowed_agent_ids
    )
    enabled = bool(
        gateway.enabled
        and normalized_agent_id
        and explicitly_allowed
        and normalized_agent_id not in gateway.denied_agent_ids
    )
    return AgentProtocolBinding(
        binding_id=f"{normalized_agent_id}:managed-mcp:inbound",
        agent_id=normalized_agent_id,
        adapter_id="managed-mcp-gateway",
        family=ProtocolFamily.MCP,
        direction=ProtocolDirection.INBOUND,
        allowed_operations=_MANAGED_MCP_OPERATIONS,
        policy_ref=f"external-agent:{gateway.permission_ceiling}",
        enabled=enabled,
    )


__all__ = ["build_managed_mcp_adapter", "build_managed_mcp_binding"]
