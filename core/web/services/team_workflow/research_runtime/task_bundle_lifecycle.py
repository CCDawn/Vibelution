"""Durable bounded ResearchTaskBundle lifecycle for Agent NodeRuns."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import Any

from core.research.workflow.contracts import ResearchTaskBundle
from core.research.workflow.models import WorkflowNodeSpec

from .node_execution_support import build_event, iso, replace_by_id, utc_now
from .store import WorkflowRunStore


class TaskBundleError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def task_bundle_id(node_run_id: str) -> str:
    return f"bundle-{hashlib.sha256(node_run_id.encode()).hexdigest()[:16]}"


def ensure_task_bundle_capacity(
    record: dict[str, Any],
    *,
    node_run_id: str,
) -> None:
    bundle_id = task_bundle_id(node_run_id)
    if any(
        item.get("bundleId") == bundle_id
        for item in record.get("taskBundles") or []
    ):
        return
    policy = dict((record.get("inputSnapshot") or {}).get("budgetPolicy") or {})
    max_parallel_tasks = int(policy.get("maxParallelTasks") or 0)
    active_subtasks = sum(
        1
        for current_bundle in record.get("taskBundles") or []
        for subtask in current_bundle.get("subtasks") or []
        if subtask.get("status") in {"pending", "running"}
    )
    if max_parallel_tasks < 1 or active_subtasks + 1 > max_parallel_tasks:
        raise TaskBundleError(
            "budgetPolicy.maxParallelTasks must allow this task bundle",
            code="parallel_budget_exhausted",
        )


def create_agent_task_bundle(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_run: dict[str, Any],
    node_spec: WorkflowNodeSpec,
    model_route: dict[str, Any],
    budget_reservation_ref: str,
    idempotency_key: str,
    deadline_seconds: int,
) -> dict[str, Any]:
    bundle_id = task_bundle_id(str(node_run["nodeRunId"]))
    existing = next(
        (
            dict(item)
            for item in record.get("taskBundles") or []
            if item.get("bundleId") == bundle_id
        ),
        None,
    )
    if existing is not None:
        if existing.get("idempotencyKey") != idempotency_key:
            raise TaskBundleError(
                "NodeRun already has a task bundle with another idempotencyKey",
                code="task_bundle_idempotency_conflict",
            )
        return existing
    ensure_task_bundle_capacity(record, node_run_id=str(node_run["nodeRunId"]))
    now = utc_now()
    objective = str(
        ((record.get("inputSnapshot") or {}).get("researchObjectiveContract") or {}).get(
            "question"
        )
        or node_spec.label
    )
    raw_bundle = {
        "bundleId": bundle_id,
        "runId": record["runId"],
        "parentNodeRunId": node_run["nodeRunId"],
        "objective": objective,
        "inputArtifactRefs": list(node_run.get("artifactRefs") or []),
        "subtasks": [
            {
                "subtaskId": f"subtask-{node_run['nodeRunId']}",
                "role": node_spec.primaryRoleKey,
                "acceptanceContract": {
                    "artifactKinds": list(node_spec.producesArtifactKinds),
                    "inputSnapshotHash": node_run["inputSnapshotHash"],
                },
                "budgetReservationRef": budget_reservation_ref,
                "deadlineAt": iso(now + timedelta(seconds=deadline_seconds)),
                "status": "pending",
                "taskId": "",
                "sessionId": "",
                "outputArtifactRefs": [],
            }
        ],
        "maxConcurrency": 1,
        "aggregationContract": {
            "mode": "all_required",
            "requiredArtifactKinds": list(node_spec.producesArtifactKinds),
        },
        "status": "pending",
    }
    bundle = {
        **ResearchTaskBundle.from_dict(raw_bundle).to_dict(),
        "nodeId": node_run["nodeId"],
        "modelRoutingDecisionId": model_route["decisionId"],
        "idempotencyKey": idempotency_key,
        "createdAt": iso(now),
        "cancelReason": "",
    }

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        bundles = list(current.get("taskBundles") or [])
        prior = next(
            (item for item in bundles if item.get("bundleId") == bundle_id),
            None,
        )
        if prior is not None:
            if prior.get("idempotencyKey") != idempotency_key:
                raise TaskBundleError(
                    "NodeRun task bundle changed before commit",
                    code="task_bundle_idempotency_conflict",
                )
            return current
        return {
            **current,
            "taskBundles": [*bundles, bundle],
            "modelRoutingDecisions": [
                *(current.get("modelRoutingDecisions") or []),
                model_route,
            ],
        }

    persisted = store.mutate_run(str(record["runId"]), mutation)
    return next(
        item for item in persisted.get("taskBundles") or [] if item["bundleId"] == bundle_id
    )


def bind_agent_task_bundle(
    store: WorkflowRunStore,
    *,
    run_id: str,
    bundle_id: str,
    task_id: str,
    session_id: str,
    turn_id: str,
) -> dict[str, Any]:
    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        bundles = list(current.get("taskBundles") or [])
        bundle = next(
            (dict(item) for item in bundles if item.get("bundleId") == bundle_id),
            None,
        )
        if bundle is None:
            raise TaskBundleError("task bundle not found", code="unknown_task_bundle")
        subtask = dict(bundle["subtasks"][0])
        if subtask.get("taskId"):
            if (
                subtask.get("taskId") == task_id
                and subtask.get("sessionId") == session_id
            ):
                return current
            raise TaskBundleError(
                "task bundle is already bound to another task",
                code="task_bundle_binding_conflict",
            )
        subtask.update(
            {
                "status": "running",
                "taskId": task_id,
                "sessionId": session_id,
                "turnId": turn_id,
            }
        )
        bundle.update({"status": "running", "subtasks": [subtask]})
        replace_by_id(bundles, "bundleId", bundle_id, bundle)
        return {**current, "taskBundles": bundles}

    persisted = store.mutate_run(run_id, mutation)
    return next(
        item for item in persisted.get("taskBundles") or [] if item["bundleId"] == bundle_id
    )


def complete_task_bundle_records(
    record: dict[str, Any],
    *,
    node_run_id: str,
    output_artifact_refs: list[str],
    completed_at: str,
) -> list[dict[str, Any]]:
    bundles = list(record.get("taskBundles") or [])
    bundle = next(
        (
            dict(item)
            for item in bundles
            if item.get("parentNodeRunId") == node_run_id
        ),
        None,
    )
    if bundle is None:
        return bundles
    if bundle.get("status") == "succeeded":
        return bundles
    if bundle.get("status") != "running":
        raise TaskBundleError(
            f"task bundle must be running, got {bundle.get('status')}",
            code="invalid_task_bundle_state",
        )
    bundle.update(
        {
            "status": "succeeded",
            "completedAt": completed_at,
            "subtasks": [
                {
                    **item,
                    "status": "succeeded",
                    "outputArtifactRefs": list(output_artifact_refs),
                }
                if item.get("status") == "running"
                else item
                for item in bundle.get("subtasks") or []
            ],
        }
    )
    replace_by_id(bundles, "bundleId", str(bundle["bundleId"]), bundle)
    return bundles


def cancel_task_bundle(
    store: WorkflowRunStore,
    *,
    run_id: str,
    bundle_id: str,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    if not reason.strip() or not idempotency_key.strip():
        raise TaskBundleError(
            "bundle cancellation requires reason and idempotencyKey",
            code="invalid_task_bundle_cancel",
        )
    record = store.get_run(run_id)
    if record is None:
        raise TaskBundleError(f"Unknown runId: {run_id}", code="unknown_run")
    bundle = next(
        (
            dict(item)
            for item in record.get("taskBundles") or []
            if item.get("bundleId") == bundle_id
        ),
        None,
    )
    if bundle is None:
        raise TaskBundleError("task bundle not found", code="unknown_task_bundle")
    prior_receipt = next(
        (
            item
            for item in record.get("commandReceipts") or []
            if item.get("command") == "cancel_task_bundle"
            and item.get("idempotencyKey") == idempotency_key
        ),
        None,
    )
    if prior_receipt is not None:
        return record

    stop_results: list[dict[str, Any]] = []
    from core.web.services.session_service import request_stop_session_turn

    for subtask in bundle.get("subtasks") or []:
        session_id = str(subtask.get("sessionId") or "")
        turn_id = str(subtask.get("turnId") or "")
        if subtask.get("status") == "running" and session_id:
            stop_results.append(
                request_stop_session_turn(session_id, expected_turn_id=turn_id)
            )
    now = iso(utc_now())

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        if any(
            item.get("command") == "cancel_task_bundle"
            and item.get("idempotencyKey") == idempotency_key
            for item in current.get("commandReceipts") or []
        ):
            return current
        bundles = list(current.get("taskBundles") or [])
        current_bundle = next(
            (dict(item) for item in bundles if item.get("bundleId") == bundle_id),
            None,
        )
        if current_bundle is None:
            raise TaskBundleError("task bundle not found", code="unknown_task_bundle")
        current_bundle.update(
            {
                "status": "cancelled",
                "cancelReason": reason,
                "cancelledAt": now,
                "subtasks": [
                    {**item, "status": "cancelled"}
                    if item.get("status") in {"pending", "running"}
                    else item
                    for item in current_bundle.get("subtasks") or []
                ],
            }
        )
        replace_by_id(bundles, "bundleId", bundle_id, current_bundle)
        node_runs = list(current.get("nodeRuns") or [])
        node_run = next(
            (
                dict(item)
                for item in node_runs
                if item.get("nodeRunId") == current_bundle["parentNodeRunId"]
            ),
            None,
        )
        if node_run is not None and node_run.get("status") == "running":
            node_run.update(
                {
                    "status": "cancelled",
                    "finishedAt": now,
                    "failureCode": "task_bundle_cancelled",
                    "failureSummary": reason,
                }
            )
            replace_by_id(node_runs, "nodeRunId", node_run["nodeRunId"], node_run)
        receipt = {
            "receiptId": f"receipt-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": current_bundle["nodeId"],
            "nodeRunId": current_bundle["parentNodeRunId"],
            "command": "cancel_task_bundle",
            "idempotencyKey": idempotency_key,
            "status": "applied",
            "recordedAt": now,
            "stopResults": stop_results,
        }
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=current_bundle["nodeId"],
            nodeRunId=current_bundle["parentNodeRunId"],
            type="TaskBundleCancelled",
            summary={"bundleId": bundle_id, "reason": reason},
        )
        return {
            **current,
            "status": "blocked",
            "blockedReason": "task_bundle_cancelled",
            "taskBundles": bundles,
            "nodeRuns": node_runs,
            "commandReceipts": [
                *(current.get("commandReceipts") or []),
                receipt,
            ],
            "events": [*(current.get("events") or []), event],
        }

    return store.mutate_run(run_id, mutation)


def reconcile_expired_task_bundles(
    store: WorkflowRunStore,
    *,
    run_id: str,
) -> dict[str, Any]:
    record = store.get_run(run_id)
    if record is None:
        raise TaskBundleError(f"Unknown runId: {run_id}", code="unknown_run")
    now = iso(utc_now())
    expired = [
        dict(bundle)
        for bundle in record.get("taskBundles") or []
        if bundle.get("status") in {"pending", "running"}
        and any(
            str(subtask.get("deadlineAt") or "") < now
            for subtask in bundle.get("subtasks") or []
            if subtask.get("status") in {"pending", "running"}
        )
    ]
    for bundle in expired:
        record = cancel_task_bundle(
            store,
            run_id=run_id,
            bundle_id=str(bundle["bundleId"]),
            reason="task bundle deadline exceeded",
            idempotency_key=(
                f"expire:{bundle['bundleId']}:"
                f"{bundle['subtasks'][0].get('deadlineAt') or ''}"
            ),
        )
    return record
