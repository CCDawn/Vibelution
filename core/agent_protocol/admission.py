"""Fail-closed per-operation admission for resolved Agent protocol routes."""

from __future__ import annotations

from dataclasses import dataclass

from .models import ProtocolOperation, ResolvedAgentRoute, _fingerprint


class AgentProtocolAdmissionError(PermissionError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProtocolAdmissionRequest:
    principal_ref: str
    tenant_ref: str
    binding_id: str
    operation: ProtocolOperation
    policy_version: int
    authenticated: bool


@dataclass(frozen=True, slots=True)
class ProtocolAdmissionDecision:
    allowed: bool
    binding_id: str
    operation: ProtocolOperation
    policy_version: int
    principal_fingerprint: str
    tenant_fingerprint: str
    decision_fingerprint: str


def admit_protocol_operation(
    route: ResolvedAgentRoute,
    request: ProtocolAdmissionRequest,
) -> ProtocolAdmissionDecision:
    if not request.authenticated:
        raise AgentProtocolAdmissionError("principal_not_authenticated")
    if not request.principal_ref.strip() or not request.tenant_ref.strip():
        raise AgentProtocolAdmissionError("principal_scope_missing")
    if request.policy_version <= 0:
        raise AgentProtocolAdmissionError("policy_version_invalid")
    if request.binding_id != route.binding_id:
        raise AgentProtocolAdmissionError("binding_mismatch")
    if request.operation is not route.operation:
        raise AgentProtocolAdmissionError("operation_mismatch")
    principal_fingerprint = _fingerprint({"principalRef": request.principal_ref})
    tenant_fingerprint = _fingerprint({"tenantRef": request.tenant_ref})
    decision_fingerprint = _fingerprint(
        {
            "routeDecision": route.decision_fingerprint,
            "bindingId": request.binding_id,
            "operation": request.operation.value,
            "policyVersion": request.policy_version,
            "principal": principal_fingerprint,
            "tenant": tenant_fingerprint,
        }
    )
    return ProtocolAdmissionDecision(
        allowed=True,
        binding_id=request.binding_id,
        operation=request.operation,
        policy_version=request.policy_version,
        principal_fingerprint=principal_fingerprint,
        tenant_fingerprint=tenant_fingerprint,
        decision_fingerprint=decision_fingerprint,
    )


__all__ = [
    "AgentProtocolAdmissionError",
    "ProtocolAdmissionDecision",
    "ProtocolAdmissionRequest",
    "admit_protocol_operation",
]
