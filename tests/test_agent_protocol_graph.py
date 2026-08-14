from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.agent_protocol import (
    AgentProtocolAdmissionError,
    AgentProtocolBinding,
    AgentProtocolGraphBuilder,
    AgentProtocolGraphError,
    AgentRouteRequest,
    EndpointObservation,
    ProtocolAdapterDefinition,
    ProtocolDirection,
    ProtocolFamily,
    ProtocolOperation,
    ProtocolTransport,
    ProtocolAdmissionRequest,
    RemoteIdentityRef,
    admit_protocol_operation,
)


NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _adapter(
    adapter_id: str = "mcp-local",
    *,
    family: ProtocolFamily = ProtocolFamily.MCP,
    direction: ProtocolDirection = ProtocolDirection.INBOUND,
    operations: tuple[ProtocolOperation, ...] = (
        ProtocolOperation.DISCOVER,
        ProtocolOperation.INVOKE,
        ProtocolOperation.GET_TASK,
        ProtocolOperation.CANCEL,
    ),
) -> ProtocolAdapterDefinition:
    return ProtocolAdapterDefinition(
        adapter_id=adapter_id,
        family=family,
        protocol_version="2025-06-18",
        transport=ProtocolTransport.STDIO,
        direction=direction,
        supported_operations=operations,
        credential_ref="secret://mcp/local",
    )


def _binding(
    binding_id: str = "coder-mcp-in",
    *,
    adapter_id: str = "mcp-local",
    family: ProtocolFamily = ProtocolFamily.MCP,
    operations: tuple[ProtocolOperation, ...] = (
        ProtocolOperation.DISCOVER,
        ProtocolOperation.INVOKE,
        ProtocolOperation.GET_TASK,
    ),
) -> AgentProtocolBinding:
    return AgentProtocolBinding(
        binding_id=binding_id,
        agent_id="coder",
        adapter_id=adapter_id,
        family=family,
        direction=ProtocolDirection.INBOUND,
        allowed_operations=operations,
        model_route_ref="model-route:primary",
        enabled=True,
    )


def _observation(
    binding_id: str = "coder-mcp-in",
    *,
    operations: tuple[ProtocolOperation, ...] = (
        ProtocolOperation.DISCOVER,
        ProtocolOperation.INVOKE,
        ProtocolOperation.GET_TASK,
    ),
    expires_at: datetime | None = None,
) -> EndpointObservation:
    return EndpointObservation(
        binding_id=binding_id,
        observed_operations=operations,
        observed_at=NOW,
        expires_at=expires_at or NOW + timedelta(minutes=5),
        endpoint_ref="endpoint://loopback/managed-agent",
    )


def test_one_agent_can_have_multiple_protocol_bindings_without_overwrite() -> None:
    graph = AgentProtocolGraphBuilder(now=NOW).build(
        declared_agent_operations={
            "coder": (
                ProtocolOperation.DISCOVER,
                ProtocolOperation.INVOKE,
                ProtocolOperation.GET_TASK,
            )
        },
        adapters=(
            _adapter(),
            _adapter(
                "a2a-out",
                family=ProtocolFamily.A2A,
                direction=ProtocolDirection.OUTBOUND,
                operations=(ProtocolOperation.DISCOVER, ProtocolOperation.INVOKE),
            ),
        ),
        bindings=(
            _binding(),
            AgentProtocolBinding(
                binding_id="coder-a2a-out",
                agent_id="coder",
                adapter_id="a2a-out",
                family=ProtocolFamily.A2A,
                direction=ProtocolDirection.OUTBOUND,
                allowed_operations=(
                    ProtocolOperation.DISCOVER,
                    ProtocolOperation.INVOKE,
                ),
                model_route_ref="model-route:primary",
            ),
        ),
        observations=(_observation(), _observation("coder-a2a-out")),
    )

    assert tuple(route.binding_id for route in graph.routes) == (
        "coder-a2a-out",
        "coder-mcp-in",
    )
    assert graph.fingerprint.startswith("sha256:")


@pytest.mark.parametrize(
    "bindings, issue_code",
    [
        ((_binding(), _binding()), "duplicate_binding_id"),
        (
            (
                _binding(),
                _binding("coder-mcp-in-2"),
            ),
            "duplicate_agent_adapter_direction",
        ),
    ],
)
def test_duplicate_binding_identity_fails_closed(bindings, issue_code) -> None:
    with pytest.raises(AgentProtocolGraphError) as exc:
        AgentProtocolGraphBuilder(now=NOW).build(
            declared_agent_operations={"coder": (ProtocolOperation.INVOKE,)},
            adapters=(_adapter(),),
            bindings=bindings,
            observations=(),
        )

    assert issue_code in {issue.code for issue in exc.value.issues}


def test_model_wire_protocol_name_is_not_accepted_as_agent_protocol_family() -> None:
    with pytest.raises(ValueError):
        ProtocolFamily("responses")


def test_observation_cannot_escalate_declared_or_binding_capabilities() -> None:
    graph = AgentProtocolGraphBuilder(now=NOW).build(
        declared_agent_operations={"coder": (ProtocolOperation.DISCOVER,)},
        adapters=(_adapter(),),
        bindings=(_binding(operations=(ProtocolOperation.DISCOVER,)),),
        observations=(
            _observation(
                operations=(ProtocolOperation.DISCOVER, ProtocolOperation.CANCEL)
            ),
        ),
    )

    assert graph.routes[0].effective_operations == (ProtocolOperation.DISCOVER,)


def test_expired_observation_fails_closed_for_routing() -> None:
    graph = AgentProtocolGraphBuilder(now=NOW).build(
        declared_agent_operations={"coder": (ProtocolOperation.INVOKE,)},
        adapters=(_adapter(),),
        bindings=(_binding(operations=(ProtocolOperation.INVOKE,)),),
        observations=(
            _observation(
                operations=(ProtocolOperation.INVOKE,),
                expires_at=NOW - timedelta(seconds=1),
            ),
        ),
    )

    assert graph.routes[0].effective_operations == ()
    with pytest.raises(AgentProtocolGraphError) as exc:
        graph.resolve(
            AgentRouteRequest(
                agent_id="coder",
                family=ProtocolFamily.MCP,
                direction=ProtocolDirection.INBOUND,
                operation=ProtocolOperation.INVOKE,
            )
        )
    assert {issue.code for issue in exc.value.issues} == {"operation_not_available"}


def test_binding_family_must_match_adapter_family() -> None:
    with pytest.raises(AgentProtocolGraphError) as exc:
        AgentProtocolGraphBuilder(now=NOW).build(
            declared_agent_operations={"coder": (ProtocolOperation.INVOKE,)},
            adapters=(_adapter(),),
            bindings=(_binding(family=ProtocolFamily.A2A),),
            observations=(),
        )
    assert "protocol_family_mismatch" in {issue.code for issue in exc.value.issues}


def test_secret_values_are_rejected_but_credential_refs_are_safe_to_project() -> None:
    with pytest.raises(ValueError):
        ProtocolAdapterDefinition(
            adapter_id="unsafe",
            family=ProtocolFamily.MCP,
            protocol_version="2025-06-18",
            transport=ProtocolTransport.HTTP,
            direction=ProtocolDirection.INBOUND,
            supported_operations=(ProtocolOperation.INVOKE,),
            credential_ref="sk-live-secret-value",
        )

    adapter = _adapter()
    assert adapter.public_projection()["credentialRef"] == "secret://mcp/local"
    assert "secretValue" not in adapter.public_projection()


def test_remote_identity_is_scoped_by_binding_and_deterministic() -> None:
    first = RemoteIdentityRef(binding_id="coder-mcp-in", remote_id="remote-42")
    second = RemoteIdentityRef(binding_id="coder-a2a-out", remote_id="remote-42")

    assert first.opaque_id != second.opaque_id
    assert first.opaque_id == RemoteIdentityRef(
        binding_id="coder-mcp-in", remote_id="remote-42"
    ).opaque_id
    assert "remote-42" not in first.opaque_id
    assert "remote-42" not in repr(first)

    third = RemoteIdentityRef(
        binding_id="coder-mcp-in", remote_id="remote-42", principal_ref="principal-b"
    )
    assert first.opaque_id != third.opaque_id


def test_resolution_applies_operator_and_caller_capability_intersection() -> None:
    graph = AgentProtocolGraphBuilder(now=NOW).build(
        declared_agent_operations={
            "coder": (ProtocolOperation.DISCOVER, ProtocolOperation.INVOKE)
        },
        adapters=(_adapter(),),
        bindings=(_binding(),),
        observations=(_observation(),),
    )

    route = graph.resolve(
        AgentRouteRequest(
            agent_id="coder",
            family=ProtocolFamily.MCP,
            direction=ProtocolDirection.INBOUND,
            operation=ProtocolOperation.DISCOVER,
            operator_allowed_operations=(
                ProtocolOperation.DISCOVER,
                ProtocolOperation.INVOKE,
            ),
            caller_granted_operations=(ProtocolOperation.DISCOVER,),
        )
    )
    assert route.operation is ProtocolOperation.DISCOVER

    with pytest.raises(AgentProtocolGraphError):
        graph.resolve(
            AgentRouteRequest(
                agent_id="coder",
                family=ProtocolFamily.MCP,
                direction=ProtocolDirection.INBOUND,
                operation=ProtocolOperation.INVOKE,
                operator_allowed_operations=(ProtocolOperation.INVOKE,),
                caller_granted_operations=(ProtocolOperation.DISCOVER,),
            )
        )


def test_admission_binds_authenticated_principal_tenant_route_and_policy_version() -> None:
    graph = AgentProtocolGraphBuilder(now=NOW).build(
        declared_agent_operations={"coder": (ProtocolOperation.INVOKE,)},
        adapters=(_adapter(),),
        bindings=(_binding(operations=(ProtocolOperation.INVOKE,)),),
        observations=(_observation(operations=(ProtocolOperation.INVOKE,)),),
    )
    route = graph.resolve(
        AgentRouteRequest(
            agent_id="coder",
            family=ProtocolFamily.MCP,
            direction=ProtocolDirection.INBOUND,
            operation=ProtocolOperation.INVOKE,
        )
    )
    decision = admit_protocol_operation(
        route,
        ProtocolAdmissionRequest(
            principal_ref="principal://local/mcp-host",
            tenant_ref="tenant://project/current",
            binding_id="coder-mcp-in",
            operation=ProtocolOperation.INVOKE,
            policy_version=3,
            authenticated=True,
        ),
    )
    assert decision.allowed is True
    assert decision.decision_fingerprint.startswith("sha256:")
    assert "principal://" not in repr(decision)

    with pytest.raises(AgentProtocolAdmissionError):
        admit_protocol_operation(
            route,
            ProtocolAdmissionRequest(
                principal_ref="principal://remote/untrusted",
                tenant_ref="tenant://project/current",
                binding_id="other-binding",
                operation=ProtocolOperation.INVOKE,
                policy_version=3,
                authenticated=False,
            ),
        )
