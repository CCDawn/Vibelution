"""Durable record builders for human workflow gates."""

from __future__ import annotations

import hashlib
from typing import Any


def human_task_id(node_run_id: str) -> str:
    digest = hashlib.sha256(node_run_id.encode("utf-8")).hexdigest()[:16]
    return f"ht-{digest}"


def build_pending_human_task(
    *,
    run_id: str,
    node_id: str,
    node_run_id: str,
    checkpoint_id: str,
    handoff_id: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "taskId": human_task_id(node_run_id),
        "runId": run_id,
        "nodeId": node_id,
        "nodeRunId": node_run_id,
        "handoffId": handoff_id,
        "checkpointId": checkpoint_id,
        "status": "pending",
        "allowedDecisions": ["accept", "reject", "revise"],
        "prompt": f"Resolve workflow gate at {node_id}",
        "createdAt": created_at,
        "resolvedAt": "",
        "resolvedBy": "",
        "decision": "",
        "idempotencyKey": "",
        "childRunId": "",
    }
