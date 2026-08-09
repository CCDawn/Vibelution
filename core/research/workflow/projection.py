"""Canvas projection DTO builders (read model only)."""

from __future__ import annotations

from typing import Any

from .definition import build_challenge_cup_workflow_definition
from .models import NodeRunStatus, WorkflowRunStatus


def empty_run_overlay() -> dict[str, Any]:
    return {
        "runId": None,
        "teamId": None,
        "runVersion": None,
        "status": None,
        "runtimeCurrentNodeIds": [],
        "nodeRuns": {},
        "pendingHumanTasks": [],
    }


def build_canvas_projection(
    *,
    run_id: str | None = None,
    team_id: str | None = None,
    run_version: int | None = None,
    run_status: WorkflowRunStatus | None = None,
    runtime_current_node_ids: list[str] | None = None,
    node_runs: dict[str, dict[str, Any]] | None = None,
    pending_human_tasks: list[dict[str, Any]] | None = None,
    parent_run_id: str | None = None,
    child_run_ids: list[str] | None = None,
    completion_kind: str | None = None,
    official_candidate_ref: str | None = None,
    blocked_reason: str | None = None,
    iteration_budget_max: int | None = None,
) -> dict[str, Any]:
    """Return definition + run overlay. Never includes selectedNodeId."""
    definition = build_challenge_cup_workflow_definition()
    payload = definition.to_dict()
    # selectedNodeId must never appear on server projection.
    run = {
        "runId": run_id,
        "teamId": team_id,
        "runVersion": run_version,
        "status": run_status.value if run_status else None,
        "runtimeCurrentNodeIds": list(runtime_current_node_ids or []),
        "nodeRuns": node_runs or {},
        "pendingHumanTasks": pending_human_tasks or [],
        "parentRunId": parent_run_id,
        "childRunIds": list(child_run_ids or []),
        "completionKind": completion_kind or None,
        "officialCandidateRef": official_candidate_ref or None,
        "blockedReason": blocked_reason or None,
        "iterationBudgetMax": iteration_budget_max,
    }
    return {"definition": payload, "run": run}


def default_node_run_projection(node_id: str, status: NodeRunStatus = NodeRunStatus.PENDING) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "status": status.value,
        "nodeRunId": None,
        "attempt": 0,
        "primaryAgentId": "",
        "actorKind": "",
    }
