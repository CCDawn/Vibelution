"""Immutable, provider-neutral contracts for Agent protocol routing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ProtocolFamily(str, Enum):
    MCP = "mcp"
    A2A = "a2a"
    AG_UI = "ag_ui"
    LOCAL = "local"


class ProtocolDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    BIDIRECTIONAL = "bidirectional"


class ProtocolTransport(str, Enum):
    IN_PROCESS = "in_process"
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"
    WEBSOCKET = "websocket"


class ProtocolOperation(str, Enum):
    DESCRIBE = "describe"
    DISCOVER = "discover"
    INVOKE = "invoke"
    STREAM = "stream"
    GET_TASK = "get_task"
    CANCEL = "cancel"
    SUBSCRIBE = "subscribe"
    CLOSE = "close"


def _normalized_operations(
    values: tuple[ProtocolOperation, ...],
) -> tuple[ProtocolOperation, ...]:
    return tuple(sorted(set(values), key=lambda item: item.value))


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class AgentRouteIssue:
    code: str
    message: str
    subject_ref: str = ""


class AgentProtocolGraphError(ValueError):
    def __init__(self, issues: tuple[AgentRouteIssue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{item.code}: {item.message}" for item in issues))


@dataclass(frozen=True, slots=True)
class ProtocolAdapterDefinition:
    adapter_id: str
    family: ProtocolFamily
    protocol_version: str
    transport: ProtocolTransport
    direction: ProtocolDirection
    supported_operations: tuple[ProtocolOperation, ...]
    credential_ref: str | None = None
    enabled: bool = True
    authority_ref: str = "agent_protocol.adapter_registry"

    def __post_init__(self) -> None:
        if not self.adapter_id.strip():
            raise ValueError("adapter_id is required")
        if not self.protocol_version.strip():
            raise ValueError("protocol_version is required")
        if self.credential_ref is not None:
            normalized = self.credential_ref.strip()
            if not normalized or "://" not in normalized:
                raise ValueError("credential_ref must be an opaque reference, not a value")
            object.__setattr__(self, "credential_ref", normalized)
        object.__setattr__(
            self, "supported_operations", _normalized_operations(self.supported_operations)
        )

    def public_projection(self) -> dict[str, Any]:
        return {
            "adapterId": self.adapter_id,
            "family": self.family.value,
            "protocolVersion": self.protocol_version,
            "transport": self.transport.value,
            "direction": self.direction.value,
            "supportedOperations": [item.value for item in self.supported_operations],
            "credentialRef": self.credential_ref,
            "enabled": self.enabled,
            "authorityRef": self.authority_ref,
        }


@dataclass(frozen=True, slots=True)
class AgentProtocolBinding:
    binding_id: str
    agent_id: str
    adapter_id: str
    family: ProtocolFamily
    direction: ProtocolDirection
    allowed_operations: tuple[ProtocolOperation, ...]
    model_route_ref: str | None = None
    policy_ref: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        for name in ("binding_id", "agent_id", "adapter_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        object.__setattr__(
            self, "allowed_operations", _normalized_operations(self.allowed_operations)
        )


@dataclass(frozen=True, slots=True)
class EndpointObservation:
    binding_id: str
    observed_operations: tuple[ProtocolOperation, ...]
    observed_at: datetime
    expires_at: datetime
    endpoint_ref: str

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("observation timestamps must be timezone-aware")
        if not self.endpoint_ref.strip():
            raise ValueError("endpoint_ref is required")
        object.__setattr__(
            self, "observed_operations", _normalized_operations(self.observed_operations)
        )


@dataclass(frozen=True, slots=True)
class EffectiveAgentRoute:
    binding_id: str
    agent_id: str
    adapter_id: str
    family: ProtocolFamily
    direction: ProtocolDirection
    protocol_version: str
    transport: ProtocolTransport
    effective_operations: tuple[ProtocolOperation, ...]
    model_route_ref: str | None
    policy_ref: str | None
    endpoint_ref: str | None
    route_fingerprint: str


@dataclass(frozen=True, slots=True)
class AgentRouteRequest:
    agent_id: str
    family: ProtocolFamily
    direction: ProtocolDirection
    operation: ProtocolOperation
    operator_allowed_operations: tuple[ProtocolOperation, ...] | None = None
    caller_granted_operations: tuple[ProtocolOperation, ...] | None = None


@dataclass(frozen=True, slots=True)
class ResolvedAgentRoute:
    route: EffectiveAgentRoute
    operation: ProtocolOperation
    decision_fingerprint: str

    @property
    def binding_id(self) -> str:
        return self.route.binding_id


@dataclass(frozen=True, slots=True)
class EffectiveAgentGraph:
    routes: tuple[EffectiveAgentRoute, ...]
    fingerprint: str

    def resolve(self, request: AgentRouteRequest) -> ResolvedAgentRoute:
        candidates = tuple(
            route
            for route in self.routes
            if route.agent_id == request.agent_id
            and route.family is request.family
            and route.direction is request.direction
        )
        allowed = {request.operation}
        if request.operator_allowed_operations is not None:
            allowed.intersection_update(request.operator_allowed_operations)
        if request.caller_granted_operations is not None:
            allowed.intersection_update(request.caller_granted_operations)
        candidates = tuple(
            route
            for route in candidates
            if request.operation in route.effective_operations and request.operation in allowed
        )
        if len(candidates) != 1:
            code = "operation_not_available" if not candidates else "ambiguous_route"
            raise AgentProtocolGraphError(
                (
                    AgentRouteIssue(
                        code=code,
                        message="Agent protocol route did not resolve to exactly one candidate",
                        subject_ref=request.agent_id,
                    ),
                )
            )
        route = candidates[0]
        decision_fingerprint = _fingerprint(
            {
                "graph": self.fingerprint,
                "route": route.route_fingerprint,
                "operation": request.operation.value,
                "operator": None
                if request.operator_allowed_operations is None
                else sorted(item.value for item in request.operator_allowed_operations),
                "caller": None
                if request.caller_granted_operations is None
                else sorted(item.value for item in request.caller_granted_operations),
            }
        )
        return ResolvedAgentRoute(route, request.operation, decision_fingerprint)


@dataclass(frozen=True, slots=True)
class RemoteIdentityRef:
    binding_id: str
    remote_id: str = field(repr=False)
    principal_ref: str = field(default="", repr=False)
    tenant_ref: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.binding_id.strip() or not self.remote_id.strip():
            raise ValueError("binding_id and remote_id are required")

    @property
    def opaque_id(self) -> str:
        return _fingerprint(
            {
                "bindingId": self.binding_id,
                "remoteId": self.remote_id,
                "principalRef": self.principal_ref,
                "tenantRef": self.tenant_ref,
            }
        )


__all__ = [
    "AgentProtocolBinding",
    "AgentProtocolGraphError",
    "AgentRouteIssue",
    "AgentRouteRequest",
    "EffectiveAgentGraph",
    "EffectiveAgentRoute",
    "EndpointObservation",
    "ProtocolAdapterDefinition",
    "ProtocolDirection",
    "ProtocolFamily",
    "ProtocolOperation",
    "ProtocolTransport",
    "RemoteIdentityRef",
    "ResolvedAgentRoute",
    "_fingerprint",
]
