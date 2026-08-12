"""Atomic accept transition for durable HumanTask workflow gates."""

from __future__ import annotations

import uuid
from typing import Any

from core.research.workflow.definition import build_challenge_cup_workflow_definition

from .checkpoint_lifecycle import advance_checkpoint
from .human_gate_artifacts import build_human_gate_artifacts, canonical_sha256
from .human_task_fork_resolution import resolve_with_child_fork
from .node_execution_support import build_event, iso, replace_by_id, utc_now
from .store import WorkflowRunStore
from .successor_records import build_successor_records


class HumanTaskResolutionError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _smoke_release_context(
    record: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    action = next(
        (
            dict(item)
            for item in reversed(record.get("systemActions") or [])
            if item.get("nodeId") == "smoke_gate"
            and item.get("command") == "run_smoke"
            and item.get("status") == "succeeded"
            and (item.get("observation") or {}).get("status") == "passed"
        ),
        None,
    )
    if action is None:
        raise HumanTaskResolutionError(
            "Smoke release requires a passed real Smoke observation",
            code="smoke_evidence_missing",
        )
    artifact_ref = str(action.get("artifactRef") or "")
    if not artifact_ref or not any(
        item.get("artifactId") == artifact_ref
        for item in record.get("artifactManifests") or []
    ):
        raise HumanTaskResolutionError(
            "Smoke observation ArtifactManifest is missing",
            code="smoke_evidence_missing",
        )
    observation = dict(action.get("observation") or {})
    return artifact_ref, {
        "systemActionId": action["actionId"],
        "planId": observation.get("planId"),
        "smokeRunId": observation.get("smokeRunId"),
        "smokeStatus": observation.get("status"),
        "smokeObservationRef": artifact_ref,
    }


def _find_by_id(
    items: list[dict[str, Any]],
    key: str,
    value: str,
    *,
    code: str,
) -> dict[str, Any]:
    found = next((item for item in items if str(item.get(key) or "") == value), None)
    if found is None:
        raise HumanTaskResolutionError(
            f"record not found: {key}={value}",
            code=code,
        )
    return dict(found)


def _idempotent_replay(
    record: dict[str, Any],
    *,
    task_id: str,
    decision: str,
    idempotency_key: str,
) -> bool:
    task = next(
        (
            item
            for item in record.get("humanTasks") or []
            if str(item.get("taskId") or "") == task_id
        ),
        None,
    )
    if not task:
        return False
    return bool(
        task.get("status") == f"resolved_{decision}"
        and task.get("decision") == decision
        and task.get("idempotencyKey") == idempotency_key
    )


def resolve_human_task(
    store: WorkflowRunStore,
    checkpoint_path: str,
    *,
    run_id: str,
    task_id: str,
    decision: str,
    resolved_by: str,
    idempotency_key: str,
) -> dict[str, Any]:
    if decision not in {"accept", "reject", "revise"}:
        raise HumanTaskResolutionError(
            f"unsupported human decision: {decision}",
            code="invalid_human_decision",
        )
    if not idempotency_key.strip():
        raise HumanTaskResolutionError(
            "idempotencyKey is required",
            code="missing_idempotency_key",
        )
    record = store.get_run(run_id)
    if record is None:
        raise HumanTaskResolutionError(f"Unknown runId: {run_id}", code="unknown_run")
    if _idempotent_replay(
        record,
        task_id=task_id,
        decision=decision,
        idempotency_key=idempotency_key,
    ):
        return record

    task = _find_by_id(
        list(record.get("humanTasks") or []),
        "taskId",
        task_id,
        code="unknown_human_task",
    )
    if task.get("runId") != run_id:
        raise HumanTaskResolutionError(
            f"HumanTask does not belong to run: {task_id}",
            code="human_task_run_mismatch",
        )
    if task.get("status") != "pending":
        raise HumanTaskResolutionError(
            "Human task already resolved",
            code="human_task_resolved",
        )
    definition = build_challenge_cup_workflow_definition()
    node_id = str(task.get("nodeId") or "")
    node_spec = next(
        (item for item in definition.nodes if item.nodeId == node_id),
        None,
    )
    if node_spec is None or node_spec.actorKind.value != "human":
        raise HumanTaskResolutionError(
            f"HumanTask references invalid human node: {node_id}",
            code="invalid_human_task_node",
        )
    node_run = _find_by_id(
        list(record.get("nodeRuns") or []),
        "nodeRunId",
        str(task.get("nodeRunId") or ""),
        code="human_node_run_not_found",
    )
    if node_run.get("status") != "waiting_human":
        raise HumanTaskResolutionError(
            "Human NodeRun must be waiting_human",
            code="invalid_human_node_state",
        )
    inbound_handoff = _find_by_id(
        list(record.get("handoffs") or []),
        "handoffId",
        str(task.get("handoffId") or ""),
        code="human_handoff_not_found",
    )
    if inbound_handoff.get("status") != "waiting_human":
        raise HumanTaskResolutionError(
            "Inbound handoff must be waiting_human",
            code="invalid_handoff_state",
        )
    source_artifact_ids = [
        str(item.get("artifactId") or "")
        for item in inbound_handoff.get("outputArtifactRefs") or []
        if str(item.get("artifactId") or "")
    ]
    if not source_artifact_ids:
        raise HumanTaskResolutionError(
            "Human gate requires upstream ArtifactManifest references",
            code="required_artifact_missing",
        )

    gate_context: dict[str, Any] = {}
    if node_id == "smoke_gate" and decision == "accept":
        smoke_artifact_ref, gate_context = _smoke_release_context(record)
        source_artifact_ids.append(smoke_artifact_ref)
    if node_id == "candidate_promotion" and decision == "accept":
        proposed = dict(record.get("proposedVersion") or {})
        if not (
            proposed.get("status") == "proposed"
            and proposed.get("versionId")
            and proposed.get("candidateRef")
        ):
            raise HumanTaskResolutionError(
                "candidate promotion requires a governed proposed version",
                code="promotion_proposal_missing",
            )
        gate_context = {
            "proposalId": f"proposal:{proposed['versionId']}",
            "versionId": proposed["versionId"],
            "candidateRef": proposed["candidateRef"],
            "operation": "promote",
        }

    operator = resolved_by.strip() or "operator"
    if decision in {"reject", "revise"}:
        try:
            return resolve_with_child_fork(
                store,
                checkpoint_path,
                record=record,
                task=task,
                node_run=node_run,
                inbound_handoff=inbound_handoff,
                decision=decision,
                resolved_by=operator,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            raise HumanTaskResolutionError(
                str(exc),
                code="human_task_fork_failed",
            ) from exc

    now = iso(utc_now())
    manifests, artifact_payloads = build_human_gate_artifacts(
        record=record,
        node_spec=node_spec,
        node_run=node_run,
        task=task,
        source_artifact_ids=source_artifact_ids,
        decision=decision,
        resolved_by=operator,
        created_at=now,
        gate_context=gate_context,
    )
    if node_id == "smoke_gate" and decision == "accept":
        # Human owns release only; System run_smoke already wrote smoke_evidence.
        from .workflow_artifact_store import put_workflow_artifact

        release_payload = next(
            (
                payload
                for artifact_id, payload in artifact_payloads.items()
                if str(artifact_id).startswith("smoke_release:")
            ),
            None,
        )
        if isinstance(release_payload, dict) and release_payload:
            put_workflow_artifact(
                str(record["teamId"]),
                kind="smoke_release",
                workflow_run_id=str(record["runId"]),
                source_collection_run_id=str(
                    (record.get("inputSnapshot") or {}).get("sourceCollectionRunId")
                    or record["runId"]
                ),
                payload={
                    "teamId": str(record["teamId"]),
                    "workflowRunId": str(record["runId"]),
                    "sourceCollectionRunId": str(
                        (record.get("inputSnapshot") or {}).get("sourceCollectionRunId")
                        or record["runId"]
                    ),
                    **release_payload,
                },
                artifact_identity=str(
                    task.get("taskId")
                    or node_run.get("nodeRunId")
                    or f"{node_id}:{decision}"
                ),
            )
    completed_ids = [
        *[item for item in record.get("completedNodeIds") or [] if item != node_id],
        node_id,
    ]
    checkpoint_id, next_node_ids = advance_checkpoint(
        checkpoint_path,
        thread_id=str(record["threadId"]),
        checkpoint_id=str(task.get("checkpointId") or node_run.get("checkpointId") or ""),
        completed_node_id=node_id,
        state_patch={
            "current_node_id": node_id,
            "completed_node_ids": completed_ids,
            "artifact_refs": [item.artifactId for item in manifests],
        },
    )
    output_refs = [
        {
            "artifactId": item.artifactId,
            "kind": item.artifactId.split(":", 1)[0],
            "version": item.schemaVersion,
            "contentHash": item.contentHash,
        }
        for item in manifests
    ]
    next_input_hash = canonical_sha256(output_refs)

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        if _idempotent_replay(
            current,
            task_id=task_id,
            decision=decision,
            idempotency_key=idempotency_key,
        ):
            return current
        current_task = _find_by_id(
            list(current.get("humanTasks") or []),
            "taskId",
            task_id,
            code="unknown_human_task",
        )
        if current_task.get("status") != "pending":
            raise HumanTaskResolutionError(
                "Human task already resolved",
                code="human_task_resolved",
            )
        current_node_run = _find_by_id(
            list(current.get("nodeRuns") or []),
            "nodeRunId",
            node_run["nodeRunId"],
            code="human_node_run_not_found",
        )
        current_node_run.update(
            {
                "status": "succeeded",
                "artifactRefs": [item.artifactId for item in manifests],
                "checkpointId": checkpoint_id,
                "finishedAt": now,
            }
        )
        node_runs = list(current.get("nodeRuns") or [])
        replace_by_id(
            node_runs,
            "nodeRunId",
            current_node_run["nodeRunId"],
            current_node_run,
        )
        successor_runs, outgoing_handoff, next_human_task = build_successor_records(
            current,
            definition=definition,
            from_node_id=node_id,
            from_node_run_id=current_node_run["nodeRunId"],
            next_node_ids=next_node_ids,
            checkpoint_id=checkpoint_id,
            input_hash=next_input_hash,
            output_artifact_refs=output_refs,
            now=now,
            accepted_by=operator,
        )
        node_runs.extend(successor_runs)

        resolved_task = {
            **current_task,
            "status": "resolved_accept",
            "decision": decision,
            "resolvedBy": operator,
            "resolvedAt": now,
            "checkpointId": checkpoint_id,
            "idempotencyKey": idempotency_key,
        }
        human_tasks = list(current.get("humanTasks") or [])
        replace_by_id(human_tasks, "taskId", task_id, resolved_task)
        if next_human_task is not None:
            human_tasks.append(next_human_task)

        accepted_inbound = {
            **inbound_handoff,
            "status": "accepted",
            "acceptedAt": now,
            "acceptedBy": operator,
        }
        handoffs = list(current.get("handoffs") or [])
        replace_by_id(
            handoffs,
            "handoffId",
            inbound_handoff["handoffId"],
            accepted_inbound,
        )
        if outgoing_handoff is not None:
            handoffs.append(outgoing_handoff)

        receipt = {
            "receiptId": f"receipt-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": node_id,
            "nodeRunId": current_node_run["nodeRunId"],
            "command": "resolve_human_task",
            "idempotencyKey": idempotency_key,
            "status": "applied",
            "recordedAt": now,
        }
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=checkpoint_id,
            nodeId=node_id,
            nodeRunId=current_node_run["nodeRunId"],
            attempt=current_node_run["attempt"],
            type="HumanDecisionRecorded",
            summary={"taskId": task_id, "decision": decision},
            artifactRefs=[item.artifactId for item in manifests],
        )
        official_version = dict(current.get("officialVersion") or {})
        proposed_version = dict(current.get("proposedVersion") or {})
        official_candidate_ref = str(current.get("officialCandidateRef") or "")
        completion_kind = str(current.get("completionKind") or "")
        promotion_proposals = list(current.get("promotionProposals") or [])
        if node_id == "candidate_promotion":
            official_version = {
                **proposed_version,
                "status": "official",
                "confirmedAt": now,
                "confirmedBy": operator,
            }
            official_candidate_ref = str(proposed_version["candidateRef"])
            completion_kind = "promoted"
            proposal_id = f"proposal:{proposed_version['versionId']}"
            promotion_proposals = [
                (
                    {
                        **item,
                        "status": "accepted",
                        "acceptedAt": now,
                        "acceptedBy": operator,
                    }
                    if item.get("proposalId") == proposal_id
                    else item
                )
                for item in promotion_proposals
            ]
        return {
            **current,
            "status": (
                "waiting_human"
                if next_human_task is not None
                else "running"
                if next_node_ids
                else "succeeded"
            ),
            "runtimeCurrentNodeIds": next_node_ids,
            "completedNodeIds": completed_ids,
            "nodeRuns": node_runs,
            "humanTasks": human_tasks,
            "handoffs": handoffs,
            "officialVersion": official_version,
            "proposedVersion": (
                {} if node_id == "candidate_promotion" else proposed_version
            ),
            "officialCandidateRef": official_candidate_ref,
            "completionKind": completion_kind,
            "promotionProposals": promotion_proposals,
            "artifactManifests": [
                *(current.get("artifactManifests") or []),
                *(item.to_dict() for item in manifests),
            ],
            "artifactPayloads": {
                **(current.get("artifactPayloads") or {}),
                **artifact_payloads,
            },
            "commandReceipts": [
                *(current.get("commandReceipts") or []),
                receipt,
            ],
            "events": [*(current.get("events") or []), event],
            "langGraph": {
                **(current.get("langGraph") or {}),
                "checkpointId": checkpoint_id,
                "completedNodeIds": completed_ids,
            },
        }

    return store.mutate_run(run_id, mutation)
