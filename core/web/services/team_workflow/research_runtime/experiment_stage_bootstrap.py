"""Establish the experiment planning authority at the workflow stage boundary.

The formal research workflow enters experiment planning at ``hypothesis_design``.
The experiment writeback tools intentionally fail closed when no experiment
stage round exists, so the workflow runtime must establish that round before it
starts the first experiment Agent task.  Later nodes reuse the same active round
through ``start_research_stage_round``'s idempotent continuation contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def ensure_experiment_stage_round_for_agent_node(
    *,
    node_id: str,
    team_id: str,
    project_id: str,
    input_snapshot: Mapping[str, Any],
    requested_by_agent: str,
) -> dict[str, Any] | None:
    """Create or reuse the experiment round before the first experiment node."""

    if node_id != "hypothesis_design":
        return None
    objective = input_snapshot.get("researchObjectiveContract")
    question = ""
    if isinstance(objective, Mapping):
        question = str(objective.get("question") or "").strip()
    payload = {
        "stageType": "experiment",
        "researchProjectId": project_id,
        "requestedByAgent": requested_by_agent,
    }
    if question:
        payload["topic"] = question
    return _start_research_stage_round(team_id, payload)


def _start_research_stage_round(
    team_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from core.web.services.team_workflow.research_loop import (
        start_research_stage_round,
    )

    return start_research_stage_round(team_id, payload)
