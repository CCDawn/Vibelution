"""Resolve reject/revise HumanTasks by forking a recoverable child Run."""

from __future__ import annotations

import uuid
from typing import Any

from .node_execution_support import build_event, iso, replace_by_id, utc_now
from .run_fork import create_human_gate_child_run
from .store import WorkflowRunStore


def resolve_with_child_fork(
    store: WorkflowRunStore,
    checkpoint_path: str,
    *,
    record: dict[str, Any],
    task: dict[str, Any],
    node_run: dict[str, Any],
    inbound_handoff: dict[str, Any],
    decision: str,
    resolved_by: str,
    idempotency_key: str,
) -> dict[str, Any]:
    child = create_human_gate_child_run(
        store,
        checkpoint_path,
        parent=record,
        task=task,
        decision=decision,
        idempotency_key=idempotency_key,
        resolved_by=resolved_by,
    )
    now = iso(utc_now())
    task_id = str(task["taskId"])
    run_id = str(record["runId"])

    def mutation(current: dict[str, Any]) -> dict[str, Any]:
        current_task = next(
            (
                dict(item)
                for item in current.get("humanTasks") or []
                if item.get("taskId") == task_id
            ),
            None,
        )
        if current_task is None:
            raise ValueError(f"HumanTask disappeared during fork: {task_id}")
        if (
            current_task.get("status") == f"resolved_{decision}"
            and current_task.get("idempotencyKey") == idempotency_key
            and current_task.get("childRunId") == child["runId"]
        ):
            return current
        if current_task.get("status") != "pending":
            raise ValueError("HumanTask changed before fork transaction committed")

        resolved_task = {
            **current_task,
            "status": f"resolved_{decision}",
            "decision": decision,
            "resolvedBy": resolved_by,
            "resolvedAt": now,
            "idempotencyKey": idempotency_key,
            "childRunId": child["runId"],
        }
        human_tasks = list(current.get("humanTasks") or [])
        replace_by_id(human_tasks, "taskId", task_id, resolved_task)

        blocked_node_run = {
            **node_run,
            "status": "blocked",
            "finishedAt": now,
            "failureCode": f"human_{decision}",
            "failureSummary": f"Human gate requested {decision}",
        }
        node_runs = list(current.get("nodeRuns") or [])
        replace_by_id(
            node_runs,
            "nodeRunId",
            str(node_run["nodeRunId"]),
            blocked_node_run,
        )

        rejected_handoff = {
            **inbound_handoff,
            "status": "rejected",
            "acceptedAt": "",
            "acceptedBy": "",
            "rejectionReason": f"human_{decision}",
        }
        handoffs = list(current.get("handoffs") or [])
        replace_by_id(
            handoffs,
            "handoffId",
            str(inbound_handoff["handoffId"]),
            rejected_handoff,
        )
        children = list(current.get("childRunIds") or [])
        if child["runId"] not in children:
            children.append(child["runId"])
        receipt = {
            "receiptId": f"receipt-{uuid.uuid4().hex[:10]}",
            "runId": run_id,
            "nodeId": task["nodeId"],
            "nodeRunId": node_run["nodeRunId"],
            "command": "resolve_human_task",
            "idempotencyKey": idempotency_key,
            "status": "applied",
            "recordedAt": now,
        }
        event = build_event(
            current,
            workflowId=current["workflowId"],
            workflowVersionId=current["workflowVersionId"],
            checkpointId=str(task.get("checkpointId") or ""),
            nodeId=task["nodeId"],
            nodeRunId=node_run["nodeRunId"],
            attempt=node_run["attempt"],
            type="HumanDecisionRecorded",
            summary={
                "taskId": task_id,
                "decision": decision,
                "childRunId": child["runId"],
            },
            artifactRefs=[],
        )
        return {
            **current,
            "status": "superseded",
            "runtimeCurrentNodeIds": [],
            "humanTasks": human_tasks,
            "nodeRuns": node_runs,
            "handoffs": handoffs,
            "childRunIds": children,
            "supersededByRunId": child["runId"],
            "completionKind": "forked_correction",
            "terminalReason": f"human_{decision}",
            "blockedReason": f"human_{decision}",
            "commandReceipts": [
                *(current.get("commandReceipts") or []),
                receipt,
            ],
            "events": [*(current.get("events") or []), event],
        }

    return store.mutate_run(run_id, mutation)
