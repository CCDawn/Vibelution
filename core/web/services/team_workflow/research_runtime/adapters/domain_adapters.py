"""Domain adapters: agent / human / system (spec 10.2-10.4).

All adapters use the stable actionId as idempotency identity, read back
inputs first, reserve budget before creating tasks, and produce verified
receipts only after domain read-back. Human adapters never reserve tokens.
"""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind

from ..action_registry import (
    AdapterPreflight,
    AdapterResult,
    VerifiedDomainResult,
)
from ..domain_ports import DomainPorts

DEFAULT_AGENT_ESTIMATE_TOKENS = 25_000


class AgentActionAdapter:
    action_kind = "start_agent_task"

    def __init__(self, ports: DomainPorts, *, estimate_tokens: int = DEFAULT_AGENT_ESTIMATE_TOKENS) -> None:
        self._ports = ports
        self._estimate_tokens = estimate_tokens

    def preflight(self, action: PendingAction) -> AdapterPreflight:
        verdict = self._ports.read_back_input(action)
        if not verdict.ok:
            return AdapterPreflight(ready=False, blockers=({"code": "input_readback_mismatch", "detail": verdict.detail},))
        return AdapterPreflight(ready=True)

    def execute(self, action: PendingAction) -> AdapterResult:
        if action.actor_kind != ActorKind.AGENT:
            return AdapterResult(
                action_id=action.action_id,
                outcome="failed",
                problem={"code": "actor_mismatch", "detail": "agent adapter got non-agent action"},
            )
        reservation = self._ports.reserve_budget(
            action=action, estimate_tokens=self._estimate_tokens
        )
        handle = self._ports.create_agent_task(action=action)
        refs = self._ports.execute_agent_turn(action=action, handle=handle)
        anchor = {
            "agentId": _agent_id(action),
            "roleKey": "",
            **handle.to_dict(),
            "actionId": action.action_id,
        }
        return AdapterResult(
            action_id=action.action_id,
            outcome="succeeded",
            materialized_refs=tuple(refs),
            anchor=anchor,
            usage={"estimate_tokens": self._estimate_tokens},
        )

    def verify(self, action: PendingAction, result: AdapterResult) -> VerifiedDomainResult:
        receipts: list[dict[str, Any]] = []
        for ref in result.materialized_refs:
            read_back = self._ports.read_back_artifact(str(ref.get("canonicalRef") or ""))
            if read_back is None:
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=result.anchor,
                    budget_receipt=None,
                    problem={
                        "code": "artifact_unreadable",
                        "detail": f"canonical ref 不可读: {ref.get('canonicalRef')}",
                    },
                )
            if read_back.content_hash != str(ref.get("sha256") or ""):
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=result.anchor,
                    budget_receipt=None,
                    problem={
                        "code": "artifact_hash_mismatch",
                        "detail": f"hash 不符: {read_back.canonical_ref}",
                    },
                )
            receipts.append(
                {
                    "artifactType": str(ref.get("kind") or read_back.canonical_ref),
                    "canonicalRef": read_back.canonical_ref,
                    "version": read_back.version,
                    "sha256": read_back.content_hash,
                    "domainRevision": read_back.domain_revision,
                }
            )
        return VerifiedDomainResult(
            action_id=action.action_id,
            outcome="succeeded",
            artifact_receipts=tuple(receipts),
            anchor=result.anchor,
            budget_receipt={
                "reservationId": f"res-{action.action_id}",
                "stageId": _stage_for(action.node_id),
                "reserved": {"estimatedTokens": self._estimate_tokens},
            },
        )


class HumanActionAdapter:
    action_kind = "human_task"

    def __init__(self, ports: DomainPorts) -> None:
        self._ports = ports

    def preflight(self, action: PendingAction) -> AdapterPreflight:
        return AdapterPreflight(ready=True)

    def execute(self, action: PendingAction) -> AdapterResult:
        handle = self._ports.create_human_task(action=action)
        return AdapterResult(
            action_id=action.action_id,
            outcome="succeeded",
            materialized_refs=(),
            anchor={"humanTaskId": handle.task_id, "actionId": action.action_id},
        )

    def verify(self, action: PendingAction, result: AdapterResult) -> VerifiedDomainResult:
        return VerifiedDomainResult(
            action_id=action.action_id,
            outcome="succeeded",
            artifact_receipts=(),
            anchor=result.anchor,
            budget_receipt=None,
        )


class SystemActionAdapter:
    action_kind = "system_action"

    def __init__(self, ports: DomainPorts) -> None:
        self._ports = ports

    def preflight(self, action: PendingAction) -> AdapterPreflight:
        verdict = self._ports.read_back_input(action)
        if not verdict.ok:
            return AdapterPreflight(ready=False, blockers=({"code": "input_readback_mismatch", "detail": verdict.detail},))
        return AdapterPreflight(ready=True)

    def execute(self, action: PendingAction) -> AdapterResult:
        reservation = self._ports.reserve_budget(action=action, estimate_tokens=0)
        refs, anchor = self._ports.execute_system_action(action=action)
        return AdapterResult(
            action_id=action.action_id,
            outcome="succeeded",
            materialized_refs=tuple(refs),
            anchor={"systemActionId": str(anchor.get("systemActionId") or action.action_id), "actionId": action.action_id},
            usage={"compute": str(anchor.get("runnerId") or "")},
        )

    def verify(self, action: PendingAction, result: AdapterResult) -> VerifiedDomainResult:
        receipts: list[dict[str, Any]] = []
        for ref in result.materialized_refs:
            read_back = self._ports.read_back_artifact(str(ref.get("canonicalRef") or ""))
            if read_back is None:
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=result.anchor,
                    budget_receipt=None,
                    problem={"code": "artifact_unreadable", "detail": str(ref.get("canonicalRef"))},
                )
            receipts.append(
                {
                    "artifactType": str(ref.get("kind") or read_back.canonical_ref),
                    "canonicalRef": read_back.canonical_ref,
                    "version": read_back.version,
                    "sha256": read_back.content_hash,
                    "domainRevision": read_back.domain_revision,
                }
            )
        return VerifiedDomainResult(
            action_id=action.action_id,
            outcome="succeeded",
            artifact_receipts=tuple(receipts),
            anchor=result.anchor,
            budget_receipt={
                "reservationId": f"res-{action.action_id}",
                "stageId": _stage_for(action.node_id),
                "reserved": {"estimatedTokens": 0},
            },
        )


def _agent_id(action: PendingAction) -> str:
    return f"agent-{action.node_id}"


_STAGE_BY_NODE: dict[str, str] = {
    "source_finding": "knowledge_collection",
    "source_extraction": "knowledge_collection",
    "evidence_relations": "knowledge_collection",
    "knowledge_ingestion": "knowledge_collection",
    "knowledge_handoff": "knowledge_collection",
    "hypothesis_design": "experiment_design",
    "protocol_design": "experiment_design",
    "protocol_review": "experiment_design",
    "protocol_freeze": "experiment_design",
    "smoke_gate": "experiment_design",
    "controlled_run": "execution_iteration",
    "result_evaluation": "execution_iteration",
    "iteration_decision": "execution_iteration",
    "version_governance": "execution_iteration",
    "candidate_promotion": "execution_iteration",
    "result_package": "execution_iteration",
}


def _stage_for(node_id: str) -> str:
    return _STAGE_BY_NODE.get(node_id, "execution_iteration")


def register_default_adapters(registry: Any, ports: DomainPorts) -> None:
    from ..action_registry import ActionRegistry

    if not isinstance(registry, ActionRegistry):
        registry = ActionRegistry()
    registry.register(AgentActionAdapter(ports))
    registry.register(HumanActionAdapter(ports))
    registry.register(SystemActionAdapter(ports))
    return registry
