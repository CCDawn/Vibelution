"""Lease-expiry reconciliation and retry attempt creation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from .node_execution_support import (
    NodeExecutionError,
    build_event,
    iso,
    latest_node_run,
    replace_by_id,
    utc_now,
)
from .store import WorkflowRunStore


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NodeExecutionError("invalid observedAt", code="invalid_observed_at") from exc


def reconcile_expired_execution(
    store: WorkflowRunStore,
    *,
    run_id: str,
    node_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    observed_at = _parse_time(str(payload.get("observedAt") or iso(utc_now())))

    def mutation(record: dict[str, Any]) -> dict[str, Any]:
        node_run = dict(latest_node_run(record, node_id))
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
        if observed_at <= _parse_time(str(lease.get("leaseExpiresAt") or "")):
            return record
        lease["status"] = "stuck"
        node_run.update(
            {
                "status": "blocked",
                "failureCode": "lease_expired",
                "failureSummary": "worker heartbeat expired; receipt reconciliation required",
                "finishedAt": iso(observed_at),
            }
        )
        node_runs = list(record.get("nodeRuns") or [])
        replace_by_id(node_runs, "nodeRunId", node_run["nodeRunId"], node_run)
        replace_by_id(leases, "idempotencyKey", lease["idempotencyKey"], lease)
        events = list(record.get("events") or [])
        events.append(
            build_event(
                record,
                workflowId=record["workflowId"],
                workflowVersionId=record["workflowVersionId"],
                checkpointId=(record.get("langGraph") or {}).get("checkpointId") or "",
                nodeId=node_id,
                nodeRunId=node_run["nodeRunId"],
                attempt=node_run["attempt"],
                type="LeaseExpired",
                summary={"leaseOwner": lease["leaseOwner"]},
            )
        )
        return {
            **record,
            "status": "blocked",
            "blockedReason": "lease_expired",
            "runtimeCurrentNodeIds": [node_id],
            "nodeRuns": node_runs,
            "taskLeases": leases,
            "events": events,
        }

    return store.mutate_run(run_id, mutation)


def retry_node_execution(
    store: WorkflowRunStore,
    *,
    run_id: str,
    node_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    if not idempotency_key:
        raise NodeExecutionError(
            "retry_execution requires idempotencyKey",
            code="invalid_retry",
        )
    now = iso(utc_now())

    def mutation(record: dict[str, Any]) -> dict[str, Any]:
        prior = next(
            (
                item
                for item in record.get("commandReceipts") or []
                if item.get("idempotencyKey") == idempotency_key
            ),
            None,
        )
        if prior:
            if prior.get("nodeId") != node_id or prior.get("command") != "retry_execution":
                raise NodeExecutionError(
                    "idempotencyKey conflicts with another command",
                    code="idempotency_conflict",
                )
            return record
        prior_run = latest_node_run(record, node_id)
        if prior_run.get("status") not in {"failed", "blocked"}:
            raise NodeExecutionError(
                "only failed or blocked NodeRun can be retried",
                code="invalid_node_state",
            )
        max_retries = int(
            ((record.get("inputSnapshot") or {}).get("budgetPolicy") or {}).get(
                "maxRetries", 0
            )
        )
        attempt = int(prior_run.get("attempt") or 0) + 1
        if attempt - 1 > max_retries:
            raise NodeExecutionError(
                "retry budget exhausted",
                code="retry_budget_exhausted",
            )
        next_run = {
            **prior_run,
            "nodeRunId": f"nr-{run_id}-{node_id}-a{attempt}",
            "attempt": attempt,
            "status": "ready",
            "taskId": "",
            "sessionId": "",
            "idempotencyKey": f"{run_id}:{node_id}:{attempt}",
            "artifactRefs": [],
            "startedAt": "",
            "finishedAt": "",
            "failureCode": "",
            "failureSummary": "",
            "supersedesNodeRunId": prior_run["nodeRunId"],
        }
        receipt = {
            "receiptId": f"receipt-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": node_id,
            "nodeRunId": next_run["nodeRunId"],
            "command": "retry_execution",
            "idempotencyKey": idempotency_key,
            "status": "applied",
            "recordedAt": now,
        }
        events = list(record.get("events") or [])
        events.append(
            build_event(
                record,
                workflowId=record["workflowId"],
                workflowVersionId=record["workflowVersionId"],
                checkpointId=(record.get("langGraph") or {}).get("checkpointId") or "",
                nodeId=node_id,
                nodeRunId=next_run["nodeRunId"],
                attempt=attempt,
                type="NodeRunTransitioned",
                summary={"from": prior_run["status"], "to": "ready", "retry": True},
            )
        )
        return {
            **record,
            "status": "queued",
            "blockedReason": "",
            "runtimeCurrentNodeIds": [node_id],
            "nodeRuns": [*(record.get("nodeRuns") or []), next_run],
            "commandReceipts": [*(record.get("commandReceipts") or []), receipt],
            "events": events,
        }

    return store.mutate_run(run_id, mutation)
