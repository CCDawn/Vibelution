"""Resolve one Workflow NodeRun to its exact canonical external Agent task."""

from __future__ import annotations

from typing import Any

from .agent_node_execution import SOURCE_NODE_TASKS


def load_external_agent_task(
    record: dict[str, Any],
    node_run: dict[str, Any],
) -> dict[str, Any] | None:
    node_id = str(node_run.get("nodeId") or "")
    task_id = str(node_run.get("taskId") or "")
    team_id = str(record.get("teamId") or "")
    if node_id in SOURCE_NODE_TASKS:
        from core.web.services.team_workflow.source_collection.stage_task_query import (
            get_source_collection_stage_session_task,
        )

        result = get_source_collection_stage_session_task(team_id, task_id)
        return dict(result["task"]) if result is not None else None

    from core.web.services.team_workflow.research_project_agent_tasks import (
        get_research_project_agent_task_status,
    )

    payload = get_research_project_agent_task_status(
        team_id,
        str(record.get("projectId") or ""),
    )
    return next(
        (
            dict(item)
            for item in payload.get("tasks") or []
            if str(item.get("taskId") or "") == task_id
        ),
        None,
    )
