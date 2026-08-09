"""Persist an external Agent task failure into its Workflow NodeRun lineage."""

from __future__ import annotations

from typing import Any

from .node_execution_support import (
    build_event,
    iso,
    latest_node_run,
    replace_by_id,
    utc_now,
)
from .store import WorkflowRunStore


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
