"""Fork a bounded evidence-remediation child after extraction retries exhaust."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from core.research.workflow.contracts import WorkflowRunInputSnapshot
from core.research.workflow.definition_registry import resolve_definition_for_run_record

from .budget_lifecycle import build_initial_budget_ledgers, remaining_budget_policy
from .checkpoint_lifecycle import fork_checkpoint_at_node
from .human_gate_artifacts import canonical_sha256
from .node_execution_support import build_event, iso, latest_node_run, utc_now
from .retry_policy import retry_is_available, retry_kind_for
from .store import WorkflowRunStore
from .successor_records import build_node_run

_COMMAND = "fork_evidence_remediation"
_NODE_ID = "source_extraction"
_PREDECESSOR_NODE_ID = "source_finding"
_FAILURE_CODES = {"external_task_needs_review"}
_RESOLUTION_KINDS = {"add_budget", "reduce_scope"}
_ADDITIONAL_BUDGET_KEYS = {
    "tokens",
    "toolCalls",
    "wallClockSeconds",
    "computeUnits",
}


class EvidenceRemediationForkError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _unique_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})


def _approved_budget(value: Any, *, resolution_kind: str) -> dict[str, int]:
    if not isinstance(value, dict):
        value = {}
    unknown = set(value) - _ADDITIONAL_BUDGET_KEYS
    if unknown:
        raise EvidenceRemediationForkError(
            f"additionalBudget contains unsupported counters: {', '.join(sorted(unknown))}",
            code="invalid_evidence_remediation_budget",
        )
    if any(
        isinstance(amount, bool) or not isinstance(amount, int) or amount < 0
        for amount in value.values()
    ):
        raise EvidenceRemediationForkError(
            "additionalBudget values must be non-negative integers",
            code="invalid_evidence_remediation_budget",
        )
    normalized = {key: int(value.get(key) or 0) for key in sorted(value)}
    has_increment = any(normalized.values())
    if resolution_kind == "add_budget" and not has_increment:
        raise EvidenceRemediationForkError(
            "add_budget requires a positive additionalBudget",
            code="invalid_evidence_remediation_budget",
        )
    if resolution_kind == "reduce_scope" and has_increment:
        raise EvidenceRemediationForkError(
            "reduce_scope cannot silently add budget",
            code="invalid_evidence_remediation_budget",
        )
    return normalized


def _contract(
    parent: dict[str, Any],
    latest: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    resolution_kind = str(payload.get("resolutionKind") or "").strip()
    operator_reason = str(payload.get("operatorReason") or "").strip()
    evidence_gap_ids = _unique_ids(payload.get("evidenceGapCandidateIds"))
    scope_ids = _unique_ids(payload.get("scopeCandidateIds"))
    if resolution_kind not in _RESOLUTION_KINDS:
        raise EvidenceRemediationForkError(
            "resolutionKind must be add_budget or reduce_scope",
            code="invalid_evidence_remediation",
        )
    if not operator_reason:
        raise EvidenceRemediationForkError(
            "operatorReason is required",
            code="invalid_evidence_remediation",
        )
    if not evidence_gap_ids or not scope_ids:
        raise EvidenceRemediationForkError(
            "evidenceGapCandidateIds and scopeCandidateIds are required",
            code="invalid_evidence_remediation",
        )
    durable_gap_ids = _unique_ids(
        (latest.get("failureContext") or {}).get("evidenceGapCandidateIds")
    )
    if not durable_gap_ids or evidence_gap_ids != durable_gap_ids:
        raise EvidenceRemediationForkError(
            "evidenceGapCandidateIds must exactly match the durable failure context",
            code="invalid_evidence_remediation",
        )
    if not set(scope_ids).issubset(evidence_gap_ids):
        raise EvidenceRemediationForkError(
            "scopeCandidateIds must be a subset of evidenceGapCandidateIds",
            code="invalid_evidence_remediation",
        )
    if resolution_kind == "add_budget" and scope_ids != evidence_gap_ids:
        raise EvidenceRemediationForkError(
            "add_budget must preserve the complete evidence-gap scope",
            code="invalid_evidence_remediation",
        )
    if resolution_kind == "reduce_scope" and len(scope_ids) >= len(evidence_gap_ids):
        raise EvidenceRemediationForkError(
            "reduce_scope must strictly reduce the durable evidence-gap scope",
            code="invalid_evidence_remediation",
        )
    additional_budget = _approved_budget(
        payload.get("additionalBudget"),
        resolution_kind=resolution_kind,
    )
    return {
        "schemaVersion": 1,
        "parentRunId": str(parent["runId"]),
        "sourceNodeId": _NODE_ID,
        "resolutionKind": resolution_kind,
        "evidenceGapCandidateIds": evidence_gap_ids,
        "scopeCandidateIds": scope_ids,
        "requiredExistingLocatorFetch": True,
        "additionalBudget": additional_budget,
        "operatorReason": operator_reason,
    }


def _child_run_id(parent_run_id: str, idempotency_key: str) -> str:
    identity = f"{parent_run_id}:{_COMMAND}:{idempotency_key}".encode()
    return f"run-{hashlib.sha256(identity).hexdigest()[:12]}"


def _require_available(parent: dict[str, Any]) -> dict[str, Any]:
    if str(parent.get("status") or "") != "blocked":
        raise EvidenceRemediationForkError(
            "evidence remediation requires a blocked parent Run",
            code="evidence_remediation_not_available",
        )
    latest = dict(latest_node_run(parent, _NODE_ID))
    if (
        str(latest.get("status") or "") != "blocked"
        or str(latest.get("failureCode") or "") not in _FAILURE_CODES
        or retry_kind_for(latest) != "business_retry"
    ):
        raise EvidenceRemediationForkError(
            "latest source_extraction attempt is not an evidence-quality block",
            code="evidence_remediation_not_available",
        )
    retry_available, _ = retry_is_available(parent, _NODE_ID, latest)
    if retry_available:
        raise EvidenceRemediationForkError(
            "ordinary retry budget must be exhausted before remediation fork",
            code="evidence_remediation_not_available",
        )
    if not str(parent.get("sourceCollectionRunId") or "").strip():
        raise EvidenceRemediationForkError(
            "sourceCollectionRunId is required for evidence remediation",
            code="evidence_remediation_not_available",
        )
    return latest


def _input_snapshot(
    parent: dict[str, Any],
    *,
    contract: dict[str, Any],
    created_at: str,
) -> WorkflowRunInputSnapshot:
    budget_policy = remaining_budget_policy(
        parent,
        stage_additions={
            "knowledge_collection": dict(contract["additionalBudget"]),
        },
    )
    raw = {
        **dict(parent.get("inputSnapshot") or {}),
        "budgetPolicy": budget_policy,
        "evidenceRemediationContract": contract,
        "createdAt": created_at,
    }
    raw.pop("snapshotHash", None)
    return WorkflowRunInputSnapshot.from_dict(raw)


def fork_evidence_remediation(
    store: WorkflowRunStore,
    checkpoint_path: str,
    *,
    parent: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    if not idempotency_key:
        raise EvidenceRemediationForkError(
            "idempotencyKey is required",
            code="invalid_evidence_remediation",
        )
    parent_run_id = str(parent["runId"])
    child_run_id = _child_run_id(parent_run_id, idempotency_key)
    payload_hash = canonical_sha256(payload)
    prior_receipt = next(
        (
            item
            for item in parent.get("commandReceipts") or []
            if item.get("idempotencyKey") == idempotency_key
        ),
        None,
    )
    if prior_receipt is not None:
        if (
            prior_receipt.get("command") != _COMMAND
            or prior_receipt.get("payloadHash") != payload_hash
            or prior_receipt.get("childRunId") != child_run_id
        ):
            raise EvidenceRemediationForkError(
                "idempotencyKey conflicts with another command",
                code="idempotency_conflict",
            )
        return parent

    latest = _require_available(parent)
    contract = _contract(parent, latest, payload)
    source_checkpoint_id = str(
        (parent.get("langGraph") or {}).get("checkpointId") or ""
    )
    if not source_checkpoint_id:
        raise EvidenceRemediationForkError(
            "source checkpoint is required",
            code="checkpoint_missing",
        )
    created_at = iso(utc_now())
    child_snapshot = _input_snapshot(
        parent,
        contract=contract,
        created_at=created_at,
    )
    child_thread_id = f"thread-{child_run_id}"
    # Fail-closed: fork on the parent's pinned graph; the child record copies
    # the parent's workflowVersionId/structureHash below.
    definition = resolve_definition_for_run_record(parent)
    child_checkpoint_id = fork_checkpoint_at_node(
        checkpoint_path,
        source_thread_id=str(parent["threadId"]),
        source_checkpoint_id=source_checkpoint_id,
        child_thread_id=child_thread_id,
        predecessor_node_id=_PREDECESSOR_NODE_ID,
        resume_node_id=_NODE_ID,
        state_patch={
            "current_node_id": _PREDECESSOR_NODE_ID,
            "evidence_remediation_contract": contract,
        },
        definition=definition,
    )
    node_spec = next(item for item in definition.nodes if item.nodeId == _NODE_ID)
    binding = next(
        (
            item
            for item in parent.get("bindingSnapshots") or []
            if item.get("nodeId") == _NODE_ID
        ),
        {},
    )
    node_run = build_node_run(
        run_id=child_run_id,
        node_id=_NODE_ID,
        actor_type=node_spec.actorKind.value,
        agent_id=str(binding.get("agentId") or ""),
        input_hash=child_snapshot.snapshotHash,
        checkpoint_id=child_checkpoint_id,
    )
    node_run["supersedesNodeRunId"] = str(latest.get("nodeRunId") or "")
    parent_node_by_run_id = {
        str(item.get("nodeRunId") or ""): str(item.get("nodeId") or "")
        for item in parent.get("nodeRuns") or []
    }
    inherited_manifests = [
        dict(item)
        for item in parent.get("artifactManifests") or []
        if parent_node_by_run_id.get(str(item.get("producerNodeRunId") or ""))
        == _PREDECESSOR_NODE_ID
    ]
    inherited_refs = [
        str(item.get("artifactId") or "")
        for item in inherited_manifests
        if str(item.get("artifactId") or "")
    ]
    existing_child = store.get_run(child_run_id)
    if existing_child is not None:
        if (
            existing_child.get("parentRunId") != parent_run_id
            or existing_child.get("evidenceRemediationContract") != contract
        ):
            raise EvidenceRemediationForkError(
                "deterministic evidence remediation child identity collision",
                code="idempotency_conflict",
            )
    else:
        store.create_run(
            {
                "runId": child_run_id,
                "workflowId": parent["workflowId"],
                "workflowVersionId": parent["workflowVersionId"],
                "structureHash": parent["structureHash"],
                "teamId": parent["teamId"],
                "projectId": parent["projectId"],
                "questionId": parent.get("questionId") or "",
                "threadId": child_thread_id,
                "status": "queued",
                "inputSnapshot": child_snapshot.to_dict(),
                "bindingSnapshots": list(parent.get("bindingSnapshots") or []),
                "runtimeCurrentNodeIds": [_NODE_ID],
                "completedNodeIds": [_PREDECESSOR_NODE_ID],
                "nodeRuns": [node_run],
                "artifactManifests": [],
                "artifactPayloads": {},
                "inheritedArtifactRefs": inherited_refs,
                "events": [
                    {
                        "eventId": f"evt-{uuid.uuid4().hex[:10]}",
                        "sequence": 1,
                        "occurredAt": created_at,
                        "workflowId": parent["workflowId"],
                        "workflowVersionId": parent["workflowVersionId"],
                        "runId": child_run_id,
                        "threadId": child_thread_id,
                        "checkpointId": child_checkpoint_id,
                        "nodeId": _NODE_ID,
                        "nodeRunId": node_run["nodeRunId"],
                        "attempt": 1,
                        "type": "RunForked",
                        "summary": {
                            "parentRunId": parent_run_id,
                            "reason": "evidence_remediation",
                            "resolutionKind": contract["resolutionKind"],
                            "candidateCount": len(contract["scopeCandidateIds"]),
                        },
                    }
                ],
                "humanTasks": [],
                "handoffs": [],
                "sessionBindings": {},
                "iterationDecisions": [],
                "taskLeases": [],
                "commandReceipts": [],
                "outbox": [],
                "taskBundles": [],
                "budgetLedgers": build_initial_budget_ledgers(
                    run_id=child_run_id,
                    budget_policy=child_snapshot.budgetPolicy,
                    created_at=created_at,
                ),
                "budgetReservations": [],
                "sourceCollectionRunId": str(parent["sourceCollectionRunId"]),
                "evidenceRemediationContract": contract,
                "officialCandidateRef": str(parent.get("officialCandidateRef") or ""),
                "baselineCandidateRef": str(parent.get("baselineCandidateRef") or ""),
                "childRunIds": [],
                "parentRunId": parent_run_id,
                "supersedesRunId": parent_run_id,
                "forkedFromRunId": parent_run_id,
                "forkedFromNodeId": _NODE_ID,
                "forkedFromCheckpointId": source_checkpoint_id,
                "forkCommand": _COMMAND,
                "forkIdempotencyKey": idempotency_key,
                "completionKind": "",
                "terminalReason": "",
                "createdAt": created_at,
                "langGraph": {
                    "engine": "challenge_cup_graph",
                    "checkpointId": child_checkpoint_id,
                    "completedNodeIds": [_PREDECESSOR_NODE_ID],
                    "startNodeId": _NODE_ID,
                    "inheritedFromParent": True,
                    "sourceCheckpointId": source_checkpoint_id,
                },
            }
        )

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        children = list(current.get("childRunIds") or [])
        if child_run_id not in children:
            children.append(child_run_id)
        receipt = {
            "receiptId": f"receipt-{uuid.uuid4().hex[:10]}",
            "runId": parent_run_id,
            "nodeId": _NODE_ID,
            "nodeRunId": str(latest.get("nodeRunId") or ""),
            "command": _COMMAND,
            "idempotencyKey": idempotency_key,
            "payloadHash": payload_hash,
            "childRunId": child_run_id,
            "status": "applied",
            "recordedAt": created_at,
        }
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=source_checkpoint_id,
            nodeId=_NODE_ID,
            nodeRunId=str(latest.get("nodeRunId") or ""),
            attempt=int(latest.get("attempt") or 1),
            type="RunSuperseded",
            summary={
                "childRunId": child_run_id,
                "reason": "evidence_remediation",
                "resolutionKind": contract["resolutionKind"],
            },
        )
        return {
            **current,
            "status": "superseded",
            "blockedReason": "",
            "runtimeCurrentNodeIds": [],
            "childRunIds": children,
            "supersededByRunId": child_run_id,
            "completionKind": "branched_revision",
            "terminalReason": "evidence_remediation",
            "commandReceipts": [*(current.get("commandReceipts") or []), receipt],
            "events": [*(current.get("events") or []), event],
        }

    return store.mutate_run(parent_run_id, mutation)
