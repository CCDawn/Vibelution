"""Domain GET projections over Ledger Snapshot (no JSON Run writer)."""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts.workflow_snapshot import ResearchWorkflowSnapshot

from .evidence_graph_projection import project_evidence_graph
from .handoff_query import HandoffQueryError, get_handoff_detail, list_handoffs
from .node_command_adapter import NodeCommandUnavailable
from .research_ledger import project_research_ledger
from .run_domain_queries import (
    project_budget,
    project_evaluation,
    project_experiment_campaigns,
    project_hypotheses,
)


def snapshot_projection_record(snapshot: ResearchWorkflowSnapshot) -> dict[str, Any]:
    run = snapshot.run.to_dict()
    return {
        "runId": run["runId"],
        "teamId": run["teamId"],
        "runVersion": run["runVersion"],
        "projectId": run["projectId"],
        "handoffs": [item.to_dict() for item in snapshot.handoff_summary.refs],
        "nodeRuns": [],
        "artifactManifests": [],
        "budgetLedgers": [],
        "budgetReservations": [],
        "hypothesisPortfolios": [],
        "experimentCampaigns": [],
        "competitionEvaluations": [],
        "qualityGateEvaluations": [],
        "humanTasks": [item.to_dict() for item in snapshot.pending_human_tasks],
        "langGraph": {"artifacts": {}},
        "resultPackage": None,
    }


def project_handoffs(snapshot: ResearchWorkflowSnapshot) -> dict[str, Any]:
    return list_handoffs(snapshot_projection_record(snapshot))


def project_handoff_detail(snapshot: ResearchWorkflowSnapshot, handoff_id: str) -> dict[str, Any]:
    return get_handoff_detail(snapshot_projection_record(snapshot), handoff_id)


def project_budget_from_snapshot(snapshot: ResearchWorkflowSnapshot) -> dict[str, Any]:
    return project_budget(snapshot_projection_record(snapshot))


def project_hypotheses_from_snapshot(snapshot: ResearchWorkflowSnapshot) -> dict[str, Any]:
    return project_hypotheses(snapshot_projection_record(snapshot))


def project_campaigns_from_snapshot(snapshot: ResearchWorkflowSnapshot) -> dict[str, Any]:
    return project_experiment_campaigns(snapshot_projection_record(snapshot))


def project_evaluation_from_snapshot(snapshot: ResearchWorkflowSnapshot) -> dict[str, Any]:
    return project_evaluation(snapshot_projection_record(snapshot))


def project_research_ledger_from_snapshot(snapshot: ResearchWorkflowSnapshot) -> dict[str, Any]:
    record = snapshot_projection_record(snapshot)
    try:
        from core.web.services import (
            research_evidence_service,
            team_knowledge_service,
        )
        from core.web.services.team_workflow.experiment_api.plan import (
            get_experiment_planning_status,
        )

        claim_evidence = research_evidence_service.list_claim_evidence(str(record["teamId"]))
        team_knowledge = team_knowledge_service.list_team_knowledge_bases(
            str(record["teamId"]),
            internal=True,
        )
        experiment_planning = get_experiment_planning_status(str(record["teamId"]))
    except Exception as exc:
        from .service import ResearchWorkflowError

        raise ResearchWorkflowError(
            f"ResearchLedger canonical source failed: {exc}",
            code="research_ledger_source_failed",
        ) from exc
    payload = project_research_ledger(
        record,
        claim_evidence=claim_evidence,
        team_knowledge=team_knowledge,
        experiment_planning=experiment_planning,
    )
    try:
        payload["graph"] = project_evidence_graph(record, claim_evidence=claim_evidence)
    except NodeCommandUnavailable:
        payload["graph"] = {"nodes": [], "edges": []}
    return payload


def project_knowledge_invocations(snapshot: ResearchWorkflowSnapshot) -> dict[str, Any]:
    """knowledge_invocations domain projection (per-node badge aggregates).

    Serves the snapshot's invocation badge aggregates through the standard
    per-domain GET projection surface; the aggregates themselves are built
    once by the snapshot projection builder.
    """
    run = snapshot.run.to_dict()
    return {
        "runId": run["runId"],
        "teamId": run["teamId"],
        "runVersion": run["runVersion"],
        "badges": {
            node_id: badge.to_dict()
            for node_id, badge in snapshot.invocation_badges.items()
        },
        "totals": {
            "totalCount": sum(badge.total_count for badge in snapshot.invocation_badges.values()),
            "runningCount": sum(
                badge.running_count for badge in snapshot.invocation_badges.values()
            ),
            "awaitingHandoffCount": sum(
                badge.awaiting_handoff_count for badge in snapshot.invocation_badges.values()
            ),
            "absorbedCount": sum(
                badge.absorbed_count for badge in snapshot.invocation_badges.values()
            ),
        },
    }


__all__ = [
    "HandoffQueryError",
    "project_budget_from_snapshot",
    "project_campaigns_from_snapshot",
    "project_evaluation_from_snapshot",
    "project_handoff_detail",
    "project_handoffs",
    "project_hypotheses_from_snapshot",
    "project_knowledge_invocations",
    "project_research_ledger_from_snapshot",
    "snapshot_projection_record",
]
