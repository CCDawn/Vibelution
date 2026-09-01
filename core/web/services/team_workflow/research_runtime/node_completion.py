"""Artifact validation and atomic completion of a durable NodeRun."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from core.research.workflow.contracts import (
    ArtifactManifest,
    ContractValidationError,
)
from core.research.workflow.definition_registry import resolve_definition_for_run_record
from core.research.workflow.stage_one_completion import STAGE_ONE_CHECKPOINT_FIELD

from .artifact_quality_gate import ArtifactQualityError, validate_artifact_quality
from .artifact_reuse import ArtifactReuseError, validate_artifact_reuse
from .budget_lifecycle import BudgetLifecycleError, settle_budget_records
from .budget_overrun_reconciliation import (
    block_completed_node_for_budget_overrun,
    budget_overrun,
)
from .checkpoint_lifecycle import advance_checkpoint
from .node_execution_support import (
    NodeExecutionError,
    build_event,
    iso,
    latest_node_run,
    replace_by_id,
    utc_now,
)
from .stage_one_closeout import (
    build_stage_one_closeout_action,
    evaluate_stage_one_closeout,
)
from .store import WorkflowRunStore
from .successor_records import build_successor_records
from .task_bundle_lifecycle import complete_task_bundle_records


def _artifact_ref_snapshot_hash(refs: list[dict[str, Any]]) -> str:
    raw = json.dumps(
        refs,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _validate_completion(
    record: dict[str, Any],
    *,
    node_id: str,
    lease_owner: str,
    raw_manifests: object,
) -> tuple[dict[str, Any], dict[str, Any], list[ArtifactManifest]]:
    node_run = latest_node_run(record, node_id)
    if node_run.get("status") != "running":
        raise NodeExecutionError("node must be running", code="invalid_node_state")
    lease = next(
        (
            item
            for item in reversed(record.get("taskLeases") or [])
            if item.get("nodeRunId") == node_run.get("nodeRunId")
            and item.get("status") == "running"
        ),
        None,
    )
    if not lease:
        raise NodeExecutionError("running lease not found", code="lease_not_found")
    if lease.get("leaseOwner") != lease_owner:
        raise NodeExecutionError("lease owner mismatch", code="lease_owner_mismatch")
    if not isinstance(raw_manifests, list) or not raw_manifests:
        raise NodeExecutionError(
            "artifactManifests are required",
            code="required_artifact_missing",
        )
    try:
        manifests = [ArtifactManifest.from_dict(item) for item in raw_manifests]
    except (ContractValidationError, TypeError) as exc:
        raise NodeExecutionError(str(exc), code="invalid_artifact") from exc
    for manifest in manifests:
        if (
            manifest.producerNodeRunId != node_run["nodeRunId"]
            or manifest.producerAttempt != int(node_run["attempt"])
            or manifest.inputSnapshotHash != node_run["inputSnapshotHash"]
        ):
            raise NodeExecutionError(
                "artifact provenance does not match NodeRun",
                code="invalid_artifact",
            )
    return node_run, dict(lease), manifests


def complete_node_execution(
    store: WorkflowRunStore,
    *,
    checkpoint_path: str,
    run_id: str,
    node_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    lease_owner = str(payload.get("leaseOwner") or "").strip()
    if not idempotency_key or not lease_owner:
        raise NodeExecutionError(
            "complete_execution requires idempotencyKey and leaseOwner",
            code="invalid_execution_completion",
        )
    record = store.get_run(run_id)
    if record is None:
        raise NodeExecutionError("run not found", code="unknown_run")
    prior_receipt = next(
        (
            item
            for item in record.get("commandReceipts") or []
            if item.get("idempotencyKey") == idempotency_key
        ),
        None,
    )
    if prior_receipt:
        if prior_receipt.get("nodeId") != node_id:
            raise NodeExecutionError(
                "idempotencyKey conflicts with another completion",
                code="idempotency_conflict",
            )
        return record

    validated_node_run, lease, manifests = _validate_completion(
        record,
        node_id=node_id,
        lease_owner=lease_owner,
        raw_manifests=payload.get("artifactManifests"),
    )
    raw_artifact_payloads = payload.get("artifactPayloads") or {}
    if not isinstance(raw_artifact_payloads, dict):
        raise NodeExecutionError(
            "artifactPayloads must be an object",
            code="invalid_artifact_payloads",
        )
    manifest_ids = {item.artifactId for item in manifests}
    unknown_payload_ids = set(raw_artifact_payloads) - manifest_ids
    if unknown_payload_ids:
        raise NodeExecutionError(
            "artifactPayloads contains unknown artifact ids",
            code="invalid_artifact_payloads",
        )
    artifact_payloads = {
        artifact_id: dict(value)
        for artifact_id, value in raw_artifact_payloads.items()
        if isinstance(value, dict)
    }
    source_manifests = list(record.get("artifactManifests") or [])
    parent_run_id = str(record.get("parentRunId") or "")
    if parent_run_id:
        parent = store.get_run(parent_run_id)
        if parent is not None:
            source_manifests.extend(parent.get("artifactManifests") or [])
    try:
        reuse_records = validate_artifact_reuse(
            manifests,
            source_manifests=source_manifests,
        )
        quality_gate, quality_records = validate_artifact_quality(
            record,
            node_id=node_id,
            manifests=[item.to_dict() for item in manifests],
            payloads=artifact_payloads,
        )
    except (ArtifactQualityError, ArtifactReuseError) as exc:
        raise NodeExecutionError(
            str(exc),
            code=str(getattr(exc, "code", "quality_gate_failed")),
        ) from exc
    now = iso(utc_now())
    requested_reservation_id = str(
        validated_node_run.get("budgetLedgerRef") or ""
    )
    reservation_id = (
        requested_reservation_id
        if any(
            item.get("reservationId") == requested_reservation_id
            for item in record.get("budgetReservations") or []
        )
        else ""
    )
    budget_usage = payload.get("budgetUsage")
    if reservation_id and not isinstance(budget_usage, dict):
        raise NodeExecutionError(
            "Agent completion requires budgetUsage",
            code="budget_usage_required",
        )
    try:
        budget_ledgers, budget_reservations = (
            settle_budget_records(
                record,
                reservation_id=reservation_id,
                actual=budget_usage,
                settled_at=now,
            )
            if reservation_id
            else (
                list(record.get("budgetLedgers") or []),
                list(record.get("budgetReservations") or []),
            )
        )
    except BudgetLifecycleError as exc:
        raise NodeExecutionError(str(exc), code=exc.code) from exc
    settled_reservation = next(
        (
            dict(item)
            for item in budget_reservations
            if item.get("reservationId") == reservation_id
        ),
        None,
    )
    if reservation_id and budget_overrun(settled_reservation):
        return block_completed_node_for_budget_overrun(
            store,
            record=record,
            node_id=node_id,
            reservation_id=reservation_id,
            budget_ledgers=budget_ledgers,
            budget_reservations=budget_reservations,
        )

    # Fail-closed: drive this node with the definition pinned to the run's
    # version identity, never with whatever the current code builds.
    definition = resolve_definition_for_run_record(record)
    completed_ids = list(record.get("completedNodeIds") or [])
    for item in record.get("nodeRuns") or []:
        if item.get("status") == "succeeded" and item.get("nodeId") not in completed_ids:
            completed_ids.append(item["nodeId"])
    if node_id not in completed_ids:
        completed_ids.append(node_id)
    state_patch: dict[str, Any] = {
        "current_node_id": node_id,
        "completed_node_ids": completed_ids,
        # Last-value channel: ONLY this node's artifact ids.  Cumulative
        # artifact lineage authority stays on the run record's
        # ``artifactManifests``.
        "latest_node_artifact_refs": [item.artifactId for item in manifests],
        "artifacts": {
            item.artifactId.split(":", 1)[0]: item.contentHash for item in manifests
        },
    }
    if "iterationDecision" in quality_records:
        state_patch["iteration_decision"] = quality_records["iterationDecision"]
    if node_id == "controlled_run":
        state_patch["controlled_run_attempt"] = int(validated_node_run["attempt"])
    closeout_candidate = {
        **record,
        "artifactManifests": [
            *(dict(item) for item in record.get("artifactManifests") or []),
            *(item.to_dict() for item in manifests),
        ],
        "artifactPayloads": {
            **dict(record.get("artifactPayloads") or {}),
            **artifact_payloads,
        },
    }
    stage_one_closeout = evaluate_stage_one_closeout(
        closeout_candidate,
        node_id=node_id,
    )
    if stage_one_closeout is not None:
        state_patch[STAGE_ONE_CHECKPOINT_FIELD] = (
            stage_one_closeout.completion_state
            if stage_one_closeout.accepted
            else "STAGE1_PROGRAM_REVIEW_REQUIRED"
        )
    checkpoint_id, next_node_ids = advance_checkpoint(
        checkpoint_path,
        thread_id=record["threadId"],
        checkpoint_id=(record.get("langGraph") or {}).get("checkpointId") or "",
        completed_node_id=node_id,
        state_patch=state_patch,
        definition=definition,
    )
    if stage_one_closeout is not None and not stage_one_closeout.accepted:
        next_node_ids = []
    if stage_one_closeout is not None and stage_one_closeout.accepted and next_node_ids:
        raise NodeExecutionError(
            "accepted stage-one closeout scheduled a phase-two successor",
            code="stage_one_checkpoint_not_terminal",
        )
    stage_one_action = (
        build_stage_one_closeout_action(
            record=record,
            node_run=validated_node_run,
            idempotency_key=idempotency_key,
            completed_at=now,
            outcome=stage_one_closeout,
        )
        if stage_one_closeout is not None
        else None
    )

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        if any(
            item.get("idempotencyKey") == idempotency_key
            for item in current.get("commandReceipts") or []
        ):
            return current
        current_node_run = dict(latest_node_run(current, node_id))
        current_node_run.update(
            {
                "status": "succeeded",
                "finishedAt": now,
                "artifactRefs": [item.artifactId for item in manifests],
                "checkpointId": checkpoint_id,
            }
        )
        node_runs = list(current.get("nodeRuns") or [])
        replace_by_id(
            node_runs,
            "nodeRunId",
            current_node_run["nodeRunId"],
            current_node_run,
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
        outgoing_edge = next(
            (
                edge
                for edge in definition.edges
                if edge.fromNodeId == node_id and edge.toNodeId in next_node_ids
            ),
            None,
        )
        all_manifests = [
            *(dict(item) for item in current.get("artifactManifests") or []),
            *(item.to_dict() for item in manifests),
        ]
        if outgoing_edge is not None:
            existing_kinds = {item["kind"] for item in output_refs}
            for required_kind in outgoing_edge.requiredArtifactKinds:
                if required_kind in existing_kinds:
                    continue
                source = next(
                    (
                        item
                        for item in reversed(all_manifests)
                        if str(item.get("artifactId") or "").split(":", 1)[0]
                        == required_kind
                    ),
                    None,
                )
                if source is None:
                    raise NodeExecutionError(
                        f"outgoing handoff requires {required_kind}",
                        code="required_artifact_missing",
                    )
                output_refs.append(
                    {
                        "artifactId": source["artifactId"],
                        "kind": required_kind,
                        "version": source["schemaVersion"],
                        "contentHash": source["contentHash"],
                    }
                )
                existing_kinds.add(required_kind)
        successor_input_hash = _artifact_ref_snapshot_hash(output_refs)
        successor_runs, handoff, human_task = build_successor_records(
            current,
            definition=definition,
            from_node_id=node_id,
            from_node_run_id=current_node_run["nodeRunId"],
            next_node_ids=next_node_ids,
            checkpoint_id=checkpoint_id,
            input_hash=successor_input_hash,
            output_artifact_refs=output_refs,
            now=now,
            accepted_by="system",
        )
        node_runs.extend(successor_runs)
        leases = list(current.get("taskLeases") or [])
        replace_by_id(
            leases,
            "idempotencyKey",
            str(lease["idempotencyKey"]),
            {**lease, "status": "succeeded"},
        )
        handoffs = list(current.get("handoffs") or [])
        human_tasks = list(current.get("humanTasks") or [])
        if handoff is not None:
            handoffs.append(handoff)
        if human_task is not None:
            human_tasks.append(human_task)
        task_bundles = complete_task_bundle_records(
            current,
            node_run_id=str(current_node_run["nodeRunId"]),
            output_artifact_refs=[item.artifactId for item in manifests],
            completed_at=now,
        )
        transition_events: list[dict[str, Any]] = []
        for manifest in manifests:
            event_record = {
                **current,
                "events": [
                    *(current.get("events") or []),
                    *transition_events,
                ],
            }
            transition_events.append(
                build_event(
                    event_record,
                    workflowId=current["workflowId"],
                    workflowVersionId=current["workflowVersionId"],
                    checkpointId=checkpoint_id,
                    nodeId=node_id,
                    nodeRunId=current_node_run["nodeRunId"],
                    attempt=current_node_run["attempt"],
                    type="ArtifactProduced",
                    summary={
                        "artifactId": manifest.artifactId,
                        "contentHash": manifest.contentHash,
                    },
                    artifactRefs=[manifest.artifactId],
                )
            )
        for reuse_record in reuse_records:
            event_record = {
                **current,
                "events": [
                    *(current.get("events") or []),
                    *transition_events,
                ],
            }
            transition_events.append(
                build_event(
                    event_record,
                    workflowId=current["workflowId"],
                    workflowVersionId=current["workflowVersionId"],
                    checkpointId=checkpoint_id,
                    nodeId=node_id,
                    nodeRunId=current_node_run["nodeRunId"],
                    attempt=current_node_run["attempt"],
                    type="ArtifactReused",
                    summary=reuse_record,
                    artifactRefs=[reuse_record["artifactId"]],
                )
            )
        if quality_gate is not None:
            event_record = {
                **current,
                "events": [
                    *(current.get("events") or []),
                    *transition_events,
                ],
            }
            transition_events.append(
                build_event(
                    event_record,
                    workflowId=current["workflowId"],
                    workflowVersionId=current["workflowVersionId"],
                    checkpointId=checkpoint_id,
                    nodeId=node_id,
                    nodeRunId=current_node_run["nodeRunId"],
                    attempt=current_node_run["attempt"],
                    type="QualityGateEvaluated",
                    summary={
                        "qualityGateId": quality_gate["qualityGateId"],
                        "status": "passed",
                    },
                )
            )
        if reservation_id:
            event_record = {
                **current,
                "events": [
                    *(current.get("events") or []),
                    *transition_events,
                ],
            }
            transition_events.append(
                build_event(
                    event_record,
                    workflowId=current["workflowId"],
                    workflowVersionId=current["workflowVersionId"],
                    checkpointId=checkpoint_id,
                    nodeId=node_id,
                    nodeRunId=current_node_run["nodeRunId"],
                    attempt=current_node_run["attempt"],
                    type="BudgetSettled",
                    summary={
                        "reservationId": reservation_id,
                        "actual": budget_usage,
                    },
                )
            )
        receipt = {
            "receiptId": f"receipt-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": node_id,
            "nodeRunId": current_node_run["nodeRunId"],
            "command": "complete_execution",
            "idempotencyKey": idempotency_key,
            "status": "applied",
            "recordedAt": now,
        }
        event_record = {
            **current,
            "events": [
                *(current.get("events") or []),
                *transition_events,
            ],
        }
        transition_events.append(
            build_event(
                event_record,
                workflowId=current["workflowId"],
                workflowVersionId=current["workflowVersionId"],
                checkpointId=checkpoint_id,
                nodeId=node_id,
                nodeRunId=current_node_run["nodeRunId"],
                attempt=current_node_run["attempt"],
                type="NodeRunTransitioned",
                summary={"from": "running", "to": "succeeded"},
                artifactRefs=[item.artifactId for item in manifests],
            )
        )
        if stage_one_action is not None and stage_one_closeout is not None:
            event_record = {
                **current,
                "events": [
                    *(current.get("events") or []),
                    *transition_events,
                ],
            }
            transition_events.append(
                build_event(
                    event_record,
                    workflowId=current["workflowId"],
                    workflowVersionId=current["workflowVersionId"],
                    checkpointId=checkpoint_id,
                    nodeId=node_id,
                    nodeRunId=current_node_run["nodeRunId"],
                    attempt=current_node_run["attempt"],
                    type=(
                        "StageOneCloseoutCompleted"
                        if stage_one_closeout.accepted
                        else "StageOneProgramReviewRequired"
                    ),
                    summary={
                        "actionId": stage_one_action["actionId"],
                        "completionState": stage_one_closeout.completion_state,
                        "policySha256": stage_one_closeout.policy_sha256,
                    },
                    artifactRefs=list(stage_one_closeout.artifact_refs),
                )
            )
        iteration_decisions = list(current.get("iterationDecisions") or [])
        if "iterationDecision" in quality_records and not any(
            item.get("decisionId")
            == quality_records["iterationDecision"].get("decisionId")
            for item in iteration_decisions
        ):
            iteration_decisions.append(quality_records["iterationDecision"])
        governance_records = list(current.get("versionGovernanceRecords") or [])
        official_version = dict(current.get("officialVersion") or {})
        proposed_version = dict(current.get("proposedVersion") or {})
        promotion_proposals = list(current.get("promotionProposals") or [])
        official_candidate_ref = str(current.get("officialCandidateRef") or "")
        completion_kind = str(current.get("completionKind") or "")
        terminal_reason = str(current.get("terminalReason") or "")
        if stage_one_closeout is not None and stage_one_closeout.accepted:
            completion_kind = "stage_one_g1_accepted"
            terminal_reason = stage_one_closeout.completion_state
        if "versionGovernance" in quality_records:
            governance = dict(quality_records["versionGovernance"])
            governance_records.append(governance)
            governed_version = {
                "versionId": governance["versionId"],
                "candidateRef": governance["candidateRef"],
                "status": governance["status"],
                "operation": governance["operation"],
                "decisionId": governance["decisionId"],
                "governedAt": governance.get("governedAt") or now,
            }
            if governance["status"] == "official":
                official_version = governed_version
                official_candidate_ref = governance["candidateRef"]
                completion_kind = (
                    "rolled_back"
                    if governance["operation"] == "rollback"
                    else "stopped"
                )
                terminal_reason = str(governance.get("terminalReason") or "")
            else:
                proposed_version = governed_version
                proposal_id = f"proposal:{governed_version['versionId']}"
                if not any(
                    item.get("proposalId") == proposal_id
                    for item in promotion_proposals
                ):
                    promotion_proposals.append(
                        {
                            "proposalId": proposal_id,
                            "runId": run_id,
                            "decisionId": governance["decisionId"],
                            "operation": "promote",
                            "targetCandidateRef": governance["candidateRef"],
                            "versionId": governance["versionId"],
                            "status": "pending_human",
                            "createdAt": governance.get("governedAt") or now,
                        }
                    )
        return {
            **current,
            "status": (
                "waiting_human"
                if human_task is not None
                or (
                    stage_one_closeout is not None
                    and not stage_one_closeout.accepted
                )
                else "running"
                if next_node_ids
                else "succeeded"
            ),
            "runtimeCurrentNodeIds": next_node_ids,
            "completedNodeIds": completed_ids,
            "nodeRuns": node_runs,
            "taskLeases": leases,
            "artifactManifests": [
                *(current.get("artifactManifests") or []),
                *(item.to_dict() for item in manifests),
            ],
            "artifactPayloads": {
                **(current.get("artifactPayloads") or {}),
                **artifact_payloads,
            },
            "qualityGateEvaluations": [
                *(current.get("qualityGateEvaluations") or []),
                *([quality_gate] if quality_gate is not None else []),
            ],
            "hypothesisPortfolios": [
                *(current.get("hypothesisPortfolios") or []),
                *(
                    [quality_records["hypothesisPortfolio"]]
                    if "hypothesisPortfolio" in quality_records
                    else []
                ),
            ],
            "experimentCampaigns": [
                *(current.get("experimentCampaigns") or []),
                *(
                    [quality_records["experimentCampaign"]]
                    if "experimentCampaign" in quality_records
                    else []
                ),
            ],
            "competitionEvaluations": [
                *(current.get("competitionEvaluations") or []),
                *(
                    [quality_records["competitionEvaluation"]]
                    if "competitionEvaluation" in quality_records
                    else []
                ),
            ],
            "iterationDecisions": iteration_decisions,
            "versionGovernanceRecords": governance_records,
            "officialVersion": official_version,
            "proposedVersion": proposed_version,
            "promotionProposals": promotion_proposals,
            "officialCandidateRef": official_candidate_ref,
            "completionKind": completion_kind,
            "terminalReason": terminal_reason,
            **(
                {
                    "completionState": stage_one_closeout.completion_state,
                    "completedAt": now,
                }
                if stage_one_closeout is not None and stage_one_closeout.accepted
                else {}
            ),
            **(
                {
                    "stageOneCloseout": stage_one_closeout.to_dict(),
                    "systemActions": [
                        *(current.get("systemActions") or []),
                        stage_one_action,
                    ],
                }
                if stage_one_closeout is not None and stage_one_action is not None
                else {}
            ),
            "handoffs": handoffs,
            "humanTasks": human_tasks,
            "taskBundles": task_bundles,
            "budgetLedgers": budget_ledgers,
            "budgetReservations": budget_reservations,
            "commandReceipts": [*(current.get("commandReceipts") or []), receipt],
            "outbox": [
                *(current.get("outbox") or []),
                {
                    "outboxId": f"outbox-{uuid.uuid4().hex[:10]}",
                    "runId": run_id,
                    "nodeRunId": current_node_run["nodeRunId"],
                    "effectType": "node.completed",
                    "idempotencyKey": idempotency_key,
                    "receiptId": receipt["receiptId"],
                    "status": "delivered",
                    "recordedAt": now,
                },
            ],
            "events": [*(current.get("events") or []), *transition_events],
            "langGraph": {
                **(current.get("langGraph") or {}),
                "checkpointId": checkpoint_id,
                "completedNodeIds": completed_ids,
                **(
                    {"iterationDecision": quality_records["iterationDecision"]}
                    if "iterationDecision" in quality_records
                    else {}
                ),
                **(
                    {"controlledRunAttempt": int(validated_node_run["attempt"])}
                    if node_id == "controlled_run"
                    else {}
                ),
            },
        }

    return store.mutate_run(run_id, mutation)
