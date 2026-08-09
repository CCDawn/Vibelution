"""Persist an external Agent task failure into its Workflow NodeRun lineage."""

from __future__ import annotations

import uuid
from typing import Any

from .node_execution_support import (
    build_event,
    iso,
    latest_node_run,
    replace_by_id,
    utc_now,
)
from .store import WorkflowRunStore

RECOVERABLE_EXTERNAL_RECONCILIATION_FAILURES = frozenset(
    {
        "external_task_completion_invalid",
        "agent_usage_missing",
        "agent_usage_invalid",
    }
)
_RECOVERY_VERSION = "v2"


def is_recoverable_external_reconciliation_failure(
    node_run: dict[str, Any],
) -> bool:
    return (
        node_run.get("status") == "blocked"
        and bool(node_run.get("taskId"))
        and node_run.get("failureCode")
        in RECOVERABLE_EXTERNAL_RECONCILIATION_FAILURES
    )


def reopen_external_agent_reconciliation_failure(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_run: dict[str, Any],
) -> dict[str, Any]:
    """Reopen one internal reconciliation failure without rerunning its Agent task."""
    recovery_key = (
        f"external-agent-reconciliation-recovery:{_RECOVERY_VERSION}:"
        f"{node_run['nodeRunId']}"
    )
    now = iso(utc_now())

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        current_node_run = next(
            (
                dict(item)
                for item in current.get("nodeRuns") or []
                if item.get("nodeRunId") == node_run.get("nodeRunId")
            ),
            None,
        )
        if current_node_run is None or not is_recoverable_external_reconciliation_failure(
            current_node_run
        ):
            return current
        if any(
            item.get("idempotencyKey") == recovery_key
            for item in current.get("commandReceipts") or []
        ):
            return current
        node_run_id = str(current_node_run["nodeRunId"])
        has_partial_completion = (
            bool(current_node_run.get("artifactRefs"))
            or any(
                item.get("producerNodeRunId") == node_run_id
                for item in current.get("artifactManifests") or []
            )
            or any(
                item.get("fromNodeRunId") == node_run_id
                for item in current.get("handoffs") or []
            )
            or any(
                item.get("nodeRunId") == node_run_id
                and item.get("command") == "complete_execution"
                for item in current.get("commandReceipts") or []
            )
        )
        if has_partial_completion:
            return current

        current_node_run.update(
            {
                "status": "running",
                "finishedAt": "",
                "failureCode": "",
                "failureSummary": "",
            }
        )
        node_runs = [dict(item) for item in current.get("nodeRuns") or []]
        replace_by_id(node_runs, "nodeRunId", node_run_id, current_node_run)
        leases = [dict(item) for item in current.get("taskLeases") or []]
        for lease in leases:
            if lease.get("nodeRunId") == node_run_id and lease.get("status") == "failed":
                lease["status"] = "running"
        bundles = [dict(item) for item in current.get("taskBundles") or []]
        for bundle in bundles:
            if bundle.get("parentNodeRunId") != node_run_id or bundle.get("status") != "failed":
                continue
            bundle.update(
                {
                    "status": "running",
                    "failureCode": "",
                    "failureSummary": "",
                    "subtasks": [
                        {**item, "status": "running"}
                        if item.get("status") == "failed"
                        else item
                        for item in bundle.get("subtasks") or []
                    ],
                }
            )
        receipt = {
            "receiptId": f"receipt-{uuid.uuid4().hex[:10]}",
            "runId": current["runId"],
            "nodeId": current_node_run["nodeId"],
            "nodeRunId": node_run_id,
            "command": "retry_external_agent_reconciliation",
            "idempotencyKey": recovery_key,
            "status": "applied",
            "recordedAt": now,
        }
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId") or "",
            nodeId=current_node_run["nodeId"],
            nodeRunId=node_run_id,
            attempt=current_node_run["attempt"],
            type="ExternalAgentTaskReconciliationRetried",
            summary={
                "from": "blocked",
                "to": "running",
                "recoveryVersion": _RECOVERY_VERSION,
            },
        )
        return {
            **current,
            "status": "running",
            "blockedReason": "",
            "runtimeCurrentNodeIds": [current_node_run["nodeId"]],
            "nodeRuns": node_runs,
            "taskLeases": leases,
            "taskBundles": bundles,
            "commandReceipts": [*(current.get("commandReceipts") or []), receipt],
            "events": [*(current.get("events") or []), event],
        }

    return store.mutate_run(str(record["runId"]), mutation)


def block_external_agent_node_run(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    node_run: dict[str, Any],
    failure_code: str,
    failure_summary: str,
) -> dict[str, Any]:
    now = iso(utc_now())

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        current_node_run = dict(latest_node_run(current, str(node_run["nodeId"])))
        if current_node_run.get("status") != "running":
            return current
        current_node_run.update(
            {
                "status": "blocked",
                "finishedAt": now,
                "failureCode": failure_code,
                "failureSummary": failure_summary,
            }
        )
        node_runs = [dict(item) for item in current.get("nodeRuns") or []]
        replace_by_id(
            node_runs,
            "nodeRunId",
            str(current_node_run["nodeRunId"]),
            current_node_run,
        )
        leases = [dict(item) for item in current.get("taskLeases") or []]
        for lease in leases:
            if (
                lease.get("nodeRunId") == current_node_run["nodeRunId"]
                and lease.get("status") == "running"
            ):
                lease["status"] = "failed"
        bundles = [dict(item) for item in current.get("taskBundles") or []]
        for bundle in bundles:
            if bundle.get("parentNodeRunId") != current_node_run["nodeRunId"]:
                continue
            bundle["status"] = "failed"
            bundle["failureCode"] = failure_code
            bundle["failureSummary"] = failure_summary
            bundle["subtasks"] = [
                {**item, "status": "failed"}
                if item.get("status") in {"pending", "running"}
                else item
                for item in bundle.get("subtasks") or []
            ]
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=(current.get("langGraph") or {}).get("checkpointId")
            or "",
            nodeId=current_node_run["nodeId"],
            nodeRunId=current_node_run["nodeRunId"],
            attempt=current_node_run["attempt"],
            type="ExternalAgentTaskReconciled",
            summary={
                "status": "blocked",
                "failureCode": failure_code,
                "failureSummary": failure_summary,
            },
        )
        return {
            **current,
            "status": "blocked",
            "blockedReason": failure_code,
            "runtimeCurrentNodeIds": [current_node_run["nodeId"]],
            "nodeRuns": node_runs,
            "taskLeases": leases,
            "taskBundles": bundles,
            "events": [*(current.get("events") or []), event],
        }

    return store.mutate_run(str(record["runId"]), mutation)
