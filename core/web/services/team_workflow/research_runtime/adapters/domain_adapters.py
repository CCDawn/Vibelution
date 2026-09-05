"""Domain adapters: agent / human / system (spec 10.2-10.4).

All adapters use the stable actionId as idempotency identity, read back
inputs first, reserve budget before creating tasks, and produce verified
receipts only after domain read-back. Human adapters never reserve tokens.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind

from ..action_registry import (
    AdapterPreflight,
    AdapterResult,
    VerifiedDomainResult,
)
from ..budget_authority_adapter import DEFAULT_AGENT_NODE_RESERVE_TOKENS
from ..domain_ports import AgentTurnResult, DomainPorts

# The construction default is the conservative contract fallback, never a flat
# small constant: production ports derive the real estimate from the explicit
# budget contract (task budgetRequest > frozen stage budget > this fallback).
DEFAULT_AGENT_ESTIMATE_TOKENS = DEFAULT_AGENT_NODE_RESERVE_TOKENS


def _artifact_identity_problem(ref: Mapping[str, Any], read_back: Any) -> dict[str, str] | None:
    if read_back.content_hash != str(ref.get("sha256") or ""):
        return {"code": "artifact_hash_mismatch", "detail": f"hash 不符: {read_back.canonical_ref}"}
    expected_version = str(ref.get("version") or "").strip()
    if expected_version and expected_version != str(read_back.version or "").strip():
        return {"code": "artifact_version_mismatch", "detail": f"version 不符: {read_back.canonical_ref}"}
    return None


def _missing_artifact_problem(required: tuple[str, ...], receipts: list[dict[str, Any]]) -> dict[str, str] | None:
    present_kinds = {str(item.get("artifactType") or "").split(":", 1)[0] for item in receipts}
    missing = [kind for kind in required if kind not in present_kinds]
    return {"code": "required_artifact_missing", "detail": f"missing kinds: {missing}"} if missing else None


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
        binding = self._ports.resolve_binding(action)
        reservation = self._ports.reserve_budget(
            action=action, estimate_tokens=self._estimate_tokens
        )
        handle = self._ports.create_agent_task(action=action)
        executed = self._ports.execute_agent_turn(action=action, handle=handle)
        usage: dict[str, Any] = {"estimate_tokens": self._estimate_tokens}
        if isinstance(executed, AgentTurnResult):
            refs = list(executed.materialized_refs)
            handle = executed.handle
            if executed.usage:
                usage = dict(executed.usage)
        else:
            refs = executed
        anchor = {
            **binding.to_dict(),
            **handle.to_dict(),
            "actionId": action.action_id,
            "reservationId": str(reservation.get("reservationId") or ""),
        }
        # Keep the node root and candidate child anchors in one formal Ledger
        # anchor. The scalar columns project the root only; child identities are
        # never flattened into the root compatibility fields.
        if handle.scoped_handles:
            root_session_id = str(handle.root_session_id or "").strip()
            if not root_session_id or handle.session_id != root_session_id:
                raise RuntimeError("candidate fan-out requires a canonical root session")
            selection_ids = {item.selection_id for item in handle.scoped_handles}
            if len(selection_ids) != 1:
                raise RuntimeError("candidate fan-out spans multiple selections")
            for item in handle.scoped_handles:
                if (
                    item.parent_session_id != root_session_id
                    or item.root_session_id != root_session_id
                ):
                    raise RuntimeError(
                        "candidate session lineage does not match the node root"
                    )
            anchor["schemaVersion"] = 3
            anchor["sessionId"] = root_session_id
            anchor["sessionAttempt"] = (
                handle.root_session_attempt or handle.session_attempt
            )
            anchor["taskId"] = None
            anchor["turnId"] = None
            anchor["rootSession"] = handle.to_dict()["rootSession"]
            anchor["scopedSessions"] = [
                item.to_dict() for item in handle.scoped_handles
            ]
        return AdapterResult(
            action_id=action.action_id,
            outcome="succeeded",
            materialized_refs=tuple(refs),
            anchor=anchor,
            usage=usage,
            reserved=dict(reservation),
        )

    def verify(self, action: PendingAction, result: AdapterResult) -> VerifiedDomainResult:
        if result.observation_only:
            return VerifiedDomainResult(
                action_id=action.action_id,
                outcome="succeeded",
                artifact_receipts=(),
                anchor=None,
                budget_receipt=None,
            )
        required = self._ports.required_artifact_kinds(action)
        if required and not result.materialized_refs:
            return VerifiedDomainResult(
                action_id=action.action_id,
                outcome="blocked",
                artifact_receipts=(),
                anchor=result.anchor,
                budget_receipt=None,
                problem={
                    "code": "required_artifact_missing",
                    "detail": f"{action.node_id} requires {list(required)}",
                },
            )
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
            if not str(read_back.content_hash or "").strip() or not str(
                read_back.domain_revision or ""
            ).strip():
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=result.anchor,
                    budget_receipt=None,
                    problem={
                        "code": "artifact_incomplete_readback",
                        "detail": f"empty hash/revision: {read_back.canonical_ref}",
                    },
                )
            identity_problem = _artifact_identity_problem(ref, read_back)
            if identity_problem:
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=result.anchor,
                    budget_receipt=None,
                    problem=identity_problem,
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
        missing_problem = _missing_artifact_problem(required, receipts)
        if missing_problem:
            return VerifiedDomainResult(
                action_id=action.action_id,
                outcome="blocked",
                artifact_receipts=(),
                anchor=result.anchor,
                budget_receipt=None,
                problem=missing_problem,
            )
        if action.node_id == "source_finding":
            from ..artifact_readback_registry import (
                load_source_finding_receipt_payload,
                parse_canonical_ref,
            )
            from ..human_gate_artifacts import canonical_sha256

            source_receipt = next(
                (
                    item
                    for item in receipts
                    if str(item.get("artifactType") or "").split(":", 1)[0]
                    == "source_candidate_batch"
                ),
                None,
            )
            parsed = parse_canonical_ref(
                str((source_receipt or {}).get("canonicalRef") or "")
            )
            canonical_source_ref = isinstance(parsed, dict) and parsed.get("legacy") != "1"
            receipt_payload = (
                load_source_finding_receipt_payload(
                    team_id=str(parsed.get("teamId") or ""),
                    authority_run_id=str(parsed.get("authorityRunId") or ""),
                    candidate_content_hash=str(parsed.get("contentHash") or ""),
                )
                if canonical_source_ref
                else None
            )
            if canonical_source_ref and receipt_payload is None:
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=result.anchor,
                    budget_receipt=None,
                    problem={
                        "code": "source_search_receipt_missing",
                        "detail": (
                            "source_finding requires four-perspective canonical search "
                            "receipts and receipt-bound candidates"
                        ),
                    },
                )
            if source_receipt is not None and receipt_payload is not None:
                source_receipt["searchReceiptSha256"] = canonical_sha256(
                    receipt_payload
                )
                source_receipt["searchEventIds"] = [
                    str(event_id)
                    for item in list(receipt_payload.get("searchTrace") or [])
                    if isinstance(item, dict)
                    for event_id in list(item.get("eventIds") or [])
                    if str(event_id or "").strip()
                ]
        reserved = result.reserved or {}
        reservation_id = str(
            reserved.get("reservationId")
            or (result.anchor or {}).get("reservationId")
            or f"res-{action.action_id}"
        )
        return VerifiedDomainResult(
            action_id=action.action_id,
            outcome="succeeded",
            artifact_receipts=tuple(receipts),
            anchor=result.anchor,
            budget_receipt={
                "reservationId": reservation_id,
                "stageId": str(
                    reserved.get("stageId") or _stage_for(action.node_id)
                ),
                "reserved": dict(
                    reserved.get("reserved") or {"estimatedTokens": self._estimate_tokens}
                ),
            },
        )


class HumanActionAdapter:
    action_kind = "human_task"

    def __init__(self, ports: DomainPorts, *, node_id: str | None = None) -> None:
        self._ports = ports
        if node_id:
            # 精确 kind 契约：`human_task:{node_id}`，registry 精确匹配。
            self.action_kind = f"human_task:{node_id}"

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

    def __init__(self, ports: DomainPorts, *, node_id: str | None = None) -> None:
        self._ports = ports
        if node_id:
            # 精确 kind 契约：`system_action:{node_id}`，registry 精确匹配。
            self.action_kind = f"system_action:{node_id}"

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
            reserved=dict(reservation),
        )

    def verify(self, action: PendingAction, result: AdapterResult) -> VerifiedDomainResult:
        runner_id = str((result.usage or {}).get("compute") or "").strip()
        if not runner_id:
            return VerifiedDomainResult(
                action_id=action.action_id,
                outcome="blocked",
                artifact_receipts=(),
                anchor=result.anchor,
                budget_receipt=None,
                problem={
                    "code": "system_runner_missing",
                    "detail": f"{action.node_id} requires a non-empty runnerId",
                },
            )
        required = self._ports.required_artifact_kinds(action)
        if required and not result.materialized_refs:
            return VerifiedDomainResult(
                action_id=action.action_id,
                outcome="blocked",
                artifact_receipts=(),
                anchor=result.anchor,
                budget_receipt=None,
                problem={
                    "code": "required_artifact_missing",
                    "detail": f"{action.node_id} requires {list(required)}",
                },
            )
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
            if not str(read_back.content_hash or "").strip() or not str(
                read_back.domain_revision or ""
            ).strip():
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=result.anchor,
                    budget_receipt=None,
                    problem={
                        "code": "artifact_incomplete_readback",
                        "detail": f"empty hash/revision: {read_back.canonical_ref}",
                    },
                )
            identity_problem = _artifact_identity_problem(ref, read_back)
            if identity_problem:
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=result.anchor,
                    budget_receipt=None,
                    problem=identity_problem,
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
        missing_problem = _missing_artifact_problem(required, receipts)
        if missing_problem:
            return VerifiedDomainResult(
                action_id=action.action_id,
                outcome="blocked",
                artifact_receipts=(),
                anchor=result.anchor,
                budget_receipt=None,
                problem=missing_problem,
            )
        reserved = result.reserved or {}
        reservation_id = str(reserved.get("reservationId") or f"res-{action.action_id}")
        return VerifiedDomainResult(
            action_id=action.action_id,
            outcome="succeeded",
            artifact_receipts=tuple(receipts),
            anchor=result.anchor,
            budget_receipt={
                "reservationId": reservation_id,
                "stageId": str(reserved.get("stageId") or _stage_for(action.node_id)),
                "reserved": dict(reserved.get("reserved") or {"estimatedTokens": 0}),
            },
        )


_STAGE_BY_NODE: dict[str, str] = {
    "problem_understanding": "problem_understanding",
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


def register_default_adapters(registry: Any, ports: DomainPorts) -> Any:
    from core.research.workflow.definition import (
        build_challenge_cup_workflow_definition,
    )
    from core.research.workflow.models import ActorKind
    from core.research.workflow.knowledge_sideflow_definition import (
        build_knowledge_sideflow_workflow_definition,
    )

    from ..action_registry import ActionRegistry

    if not isinstance(registry, ActionRegistry):
        registry = ActionRegistry()
    registry.register(AgentActionAdapter(ports))
    definitions = (
        build_challenge_cup_workflow_definition(),
        build_knowledge_sideflow_workflow_definition(),
    )
    for definition in definitions:
        for node in definition.nodes:
            if node.actorKind == ActorKind.HUMAN:
                registry.register(HumanActionAdapter(ports, node_id=node.nodeId))
            elif node.actorKind == ActorKind.SYSTEM:
                registry.register(SystemActionAdapter(ports, node_id=node.nodeId))
    return registry
