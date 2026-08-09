"""Exact, reconciled read access for one source-collection stage task."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .stage_reconcile import (
    _find_source_collection_stage_session_task_by_id,
    _reconcile_source_collection_stage_session_task,
)


def get_source_collection_stage_session_task(
    team_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Return the exact canonical task after deterministic turn reconciliation."""
    task, run_id = _find_source_collection_stage_session_task_by_id(team_id, task_id)
    if task is None or not run_id:
        return None
    reconciled = _reconcile_source_collection_stage_session_task(
        team_id,
        run_id,
        dict(task),
    )
    return {
        "runId": run_id,
        "task": deepcopy(reconciled),
    }
