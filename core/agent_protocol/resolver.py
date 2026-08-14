"""Deterministic EffectiveAgentGraph construction."""

from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    AgentProtocolBinding,
    AgentProtocolGraphError,
    AgentRouteIssue,
    EffectiveAgentGraph,
    EffectiveAgentRoute,
    EndpointObservation,
    ProtocolAdapterDefinition,
    ProtocolDirection,
    ProtocolOperation,
    _fingerprint,
)


class AgentProtocolGraphBuilder:
    def __init__(self, *, now: datetime | None = None) -> None:
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

    def build(
        self,
        *,
        declared_agent_operations: dict[str, tuple[ProtocolOperation, ...]],
        adapters: tuple[ProtocolAdapterDefinition, ...],
        bindings: tuple[AgentProtocolBinding, ...],
        observations: tuple[EndpointObservation, ...],
    ) -> EffectiveAgentGraph:
        issues: list[AgentRouteIssue] = []
        adapter_by_id: dict[str, ProtocolAdapterDefinition] = {}
        for adapter in adapters:
            if adapter.adapter_id in adapter_by_id:
                issues.append(
                    AgentRouteIssue(
                        "duplicate_adapter_id", "Adapter id must be unique", adapter.adapter_id
                    )
                )
            adapter_by_id[adapter.adapter_id] = adapter

        binding_by_id: dict[str, AgentProtocolBinding] = {}
        binding_keys: set[tuple[str, str, ProtocolDirection]] = set()
        for binding in bindings:
            if binding.binding_id in binding_by_id:
                issues.append(
                    AgentRouteIssue(
                        "duplicate_binding_id", "Binding id must be unique", binding.binding_id
                    )
                )
            binding_by_id[binding.binding_id] = binding
            key = (binding.agent_id, binding.adapter_id, binding.direction)
            if key in binding_keys:
                issues.append(
                    AgentRouteIssue(
                        "duplicate_agent_adapter_direction",
                        "Agent, adapter, and direction identify at most one binding",
                        binding.binding_id,
                    )
                )
            binding_keys.add(key)

        observation_by_binding: dict[str, EndpointObservation] = {}
        for observation in observations:
            if observation.binding_id in observation_by_binding:
                issues.append(
                    AgentRouteIssue(
                        "duplicate_endpoint_observation",
                        "Only one current endpoint observation is accepted per binding",
                        observation.binding_id,
                    )
                )
            observation_by_binding[observation.binding_id] = observation

        routes: list[EffectiveAgentRoute] = []
        for binding in sorted(bindings, key=lambda item: item.binding_id):
            adapter = adapter_by_id.get(binding.adapter_id)
            if adapter is None:
                issues.append(
                    AgentRouteIssue(
                        "adapter_not_found", "Binding references an unknown adapter", binding.binding_id
                    )
                )
                continue
            if binding.family is not adapter.family:
                issues.append(
                    AgentRouteIssue(
                        "protocol_family_mismatch",
                        "Binding and adapter protocol families differ",
                        binding.binding_id,
                    )
                )
                continue
            if binding.direction is not adapter.direction:
                issues.append(
                    AgentRouteIssue(
                        "protocol_direction_mismatch",
                        "Binding and adapter directions differ",
                        binding.binding_id,
                    )
                )
                continue
            declared = set(declared_agent_operations.get(binding.agent_id, ()))
            if not declared:
                issues.append(
                    AgentRouteIssue(
                        "agent_capabilities_missing",
                        "Agent has no declared protocol capabilities",
                        binding.agent_id,
                    )
                )
                continue
            observed = observation_by_binding.get(binding.binding_id)
            observed_operations: set[ProtocolOperation] = set()
            endpoint_ref: str | None = None
            if observed is not None and observed.expires_at > self.now:
                observed_operations.update(observed.observed_operations)
                endpoint_ref = observed.endpoint_ref
            effective = declared.intersection(
                binding.allowed_operations,
                adapter.supported_operations,
                observed_operations,
            )
            if not binding.enabled or not adapter.enabled:
                effective.clear()
            effective_operations = tuple(sorted(effective, key=lambda item: item.value))
            route_payload = {
                "bindingId": binding.binding_id,
                "agentId": binding.agent_id,
                "adapterId": adapter.adapter_id,
                "family": adapter.family.value,
                "direction": adapter.direction.value,
                "protocolVersion": adapter.protocol_version,
                "transport": adapter.transport.value,
                "operations": [item.value for item in effective_operations],
                "modelRouteRef": binding.model_route_ref,
                "policyRef": binding.policy_ref,
                "endpointRef": endpoint_ref,
            }
            routes.append(
                EffectiveAgentRoute(
                    binding_id=binding.binding_id,
                    agent_id=binding.agent_id,
                    adapter_id=adapter.adapter_id,
                    family=adapter.family,
                    direction=adapter.direction,
                    protocol_version=adapter.protocol_version,
                    transport=adapter.transport,
                    effective_operations=effective_operations,
                    model_route_ref=binding.model_route_ref,
                    policy_ref=binding.policy_ref,
                    endpoint_ref=endpoint_ref,
                    route_fingerprint=_fingerprint(route_payload),
                )
            )

        if issues:
            ordered = tuple(sorted(issues, key=lambda item: (item.code, item.subject_ref)))
            raise AgentProtocolGraphError(ordered)
        graph_payload = [route.route_fingerprint for route in routes]
        return EffectiveAgentGraph(tuple(routes), _fingerprint(graph_payload))


__all__ = ["AgentProtocolGraphBuilder"]
