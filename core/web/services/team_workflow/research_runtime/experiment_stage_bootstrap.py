"""Establish the experiment planning authority at the workflow stage boundary.

The formal research workflow enters experiment planning at ``hypothesis_design``.
The experiment writeback tools intentionally fail closed when no experiment
stage round exists, so the workflow runtime must establish that round before it
starts the first experiment Agent task.  Later nodes reuse the same active round
through ``start_research_stage_round``'s idempotent continuation contract.

The accepted Knowledge Package receipt is the only handoff source for this
bootstrap. Candidate inventory is not consulted as a second authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ExperimentStageBootstrapError(RuntimeError):
    """Hypothesis entry cannot start without the accepted package receipt."""


def ensure_experiment_stage_round_for_agent_node(
    *,
    node_id: str,
    team_id: str,
    project_id: str,
    input_snapshot: Mapping[str, Any],
    requested_by_agent: str,
    store: Any | None = None,
    run_id: str = "",
    accepted_knowledge_package: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Create or reuse the experiment round before the first experiment node."""

    if node_id != "hypothesis_design":
        return None
    package = (
        dict(accepted_knowledge_package)
        if isinstance(accepted_knowledge_package, Mapping)
        else None
    )
    if package is None and store is not None and str(run_id or "").strip():
        from .human_acceptance_artifact import (
            load_accepted_knowledge_package_from_receipt,
        )

        package = load_accepted_knowledge_package_from_receipt(
            store,
            team_id=team_id,
            run_id=str(run_id),
        )
    from .human_acceptance_artifact import is_accepted_knowledge_package

    if not is_accepted_knowledge_package(package):
        raise ExperimentStageBootstrapError("knowledge_package_not_materialized")
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
