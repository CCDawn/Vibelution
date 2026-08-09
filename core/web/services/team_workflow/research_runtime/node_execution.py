"""Durable NodeRun start and heartbeat transitions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from core.research.workflow.contracts import NodeExecutionEnvelope

from .node_execution_support import (
    NodeExecutionError,
    build_event,
    iso,
    latest_node_run,
    replace_by_id,
    utc_now,
)
from .store import WorkflowRunStore


def start_node_execution(
    store: WorkflowRunStore,
    *,
    run_id: str,
    node_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    lease_owner = str(payload.get("leaseOwner") or "").strip()
    if not idempotency_key or not lease_owner:
        raise NodeExecutionError(
            "start_execution requires idempotencyKey and leaseOwner",
            code="invalid_execution_start",
        )
    lease_seconds = max(1, int(payload.get("leaseSeconds") or 60))
    deadline_seconds = max(lease_seconds, int(payload.get("deadlineSeconds") or 1800))
    now = utc_now()

    def mutation(record: dict[str, Any]) -> dict[str, Any]:
        prior = next(
            (
                item
                for item in record.get("executionEnvelopes") or []
                if item.get("idempotencyKey") == idempotency_key
            ),
            None,
        )
        if prior:
            if prior.get("leaseOwner") != lease_owner or prior.get("nodeId") != node_id:
                raise NodeExecutionError(
                    "idempotencyKey conflicts with another execution",
                    code="idempotency_conflict",
                )
            return record

        node_run = dict(latest_node_run(record, node_id))
        if node_run.get("status") != "ready":
            raise NodeExecutionError(
                f"node must be ready, got {node_run.get('status')}",
                code="invalid_node_state",
            )
        if node_run.get("actorType") == "agent" and not node_run.get("agentId"):
            raise NodeExecutionError("agent node is unbound", code="agent_unbound")

        envelope = NodeExecutionEnvelope.from_dict(
            {
                "runId": run_id,
                "nodeRunId": node_run["nodeRunId"],
                "nodeId": node_id,
                "attempt": node_run["attempt"],
                "actorType": node_run["actorType"],
                "agentId": node_run.get("agentId") or "",
                "taskId": str(payload.get("taskId") or ""),
                "sessionId": str(payload.get("sessionId") or ""),
                "inputSnapshotHash": node_run["inputSnapshotHash"],
                "idempotencyKey": idempotency_key,
                "leaseOwner": lease_owner,
                "leaseExpiresAt": iso(now + timedelta(seconds=lease_seconds)),
                "heartbeatAt": iso(now),
                "deadlineAt": iso(now + timedelta(seconds=deadline_seconds)),
                "budgetReservationRef": str(
                    payload.get("budgetReservationRef")
                    or f"budget:{run_id}:{node_id}:a{node_run['attempt']}"
                ),
                "status": "running",
            }
        ).to_dict()
        node_run.update(
            {
                "status": "running",
                "startedAt": iso(now),
                "taskId": envelope["taskId"],
                "sessionId": envelope["sessionId"],
                "budgetLedgerRef": envelope["budgetReservationRef"],
                "modelRef": str(payload.get("modelRef") or ""),
                "modelPurpose": str(payload.get("modelPurpose") or ""),
                "estimatedCost": float(payload.get("estimatedCost") or 0),
                "escalationReason": str(payload.get("escalationReason") or ""),
            }
        )
        node_runs = list(record.get("nodeRuns") or [])
        replace_by_id(node_runs, "nodeRunId", node_run["nodeRunId"], node_run)
        leases = list(record.get("taskLeases") or [])
        leases.append(
            {
                key: envelope[key]
                for key in (
                    "runId",
                    "nodeRunId",
                    "attempt",
                    "idempotencyKey",
                    "leaseOwner",
                    "leaseExpiresAt",
                    "heartbeatAt",
                    "deadlineAt",
                    "status",
                )
            }
        )
        event = build_event(
            record,
            workflowId=record["workflowId"],
            workflowVersionId=record["workflowVersionId"],
            checkpointId=(record.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=node_id,
            nodeRunId=node_run["nodeRunId"],
            attempt=node_run["attempt"],
            type="LeaseAcquired",
            summary={
                "leaseOwner": lease_owner,
                "leaseExpiresAt": envelope["leaseExpiresAt"],
            },
        )
        return {
            **record,
            "status": "running",
            "nodeRuns": node_runs,
            "taskLeases": leases,
            "executionEnvelopes": [
                *(record.get("executionEnvelopes") or []),
                envelope,
            ],
            "events": [*(record.get("events") or []), event],
        }

    return store.mutate_run(run_id, mutation)


def heartbeat_node_execution(
    store: WorkflowRunStore,
    *,
    run_id: str,
    node_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    lease_owner = str(payload.get("leaseOwner") or "").strip()
    lease_seconds = max(1, int(payload.get("leaseSeconds") or 60))
    now = utc_now()

    def mutation(record: dict[str, Any]) -> dict[str, Any]:
        node_run = latest_node_run(record, node_id)
        leases = list(record.get("taskLeases") or [])
        lease = next(
            (
                dict(item)
                for item in reversed(leases)
                if item.get("nodeRunId") == node_run.get("nodeRunId")
                and item.get("status") == "running"
            ),
            None,
        )
        if not lease:
            raise NodeExecutionError("running lease not found", code="lease_not_found")
        if lease.get("leaseOwner") != lease_owner:
            raise NodeExecutionError(
                "lease owner mismatch", code="lease_owner_mismatch"
            )
        lease["heartbeatAt"] = iso(now)
        lease["leaseExpiresAt"] = iso(now + timedelta(seconds=lease_seconds))
        replace_by_id(leases, "idempotencyKey", lease["idempotencyKey"], lease)
        return {**record, "taskLeases": leases}

    return store.mutate_run(run_id, mutation)
