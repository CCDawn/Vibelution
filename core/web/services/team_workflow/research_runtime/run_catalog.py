"""Catalog DTO for Ledger RunRecord (list/create response)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.research.workflow.ledger.records import RunRecord


def _iso_from_ms(value_ms: int) -> str:
    return (
        datetime.fromtimestamp(value_ms / 1000, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def catalog_dict_from_run(run: RunRecord) -> dict[str, Any]:
    status = "queued" if run.status == "created" else run.status
    return {
        "runId": run.run_id,
        "workflowId": run.workflow_id,
        "workflowVersionId": run.workflow_version_id,
        "structureHash": run.structure_hash,
        "teamId": run.team_id,
        "projectId": run.project_id,
        "questionId": run.question_id,
        "runVersion": run.run_version,
        "status": status,
        "threadId": run.thread_id,
        "runtimeCurrentNodeIds": [run.active_node_id] if run.active_node_id else [],
        "completionKind": run.completion_kind or "",
        "terminalReason": run.terminal_reason or "",
        "createdAt": _iso_from_ms(run.created_at_ms),
        "updatedAt": _iso_from_ms(run.updated_at_ms),
        "createdAtMs": run.created_at_ms,
        "updatedAtMs": run.updated_at_ms,
        "completedAtMs": run.completed_at_ms,
        "inputSnapshotHash": run.input_snapshot_hash,
        "bindingSnapshotSetId": run.binding_snapshot_set_id,
        "activeNodeId": run.active_node_id,
        "parentRunId": run.parent_run_id,
    }
