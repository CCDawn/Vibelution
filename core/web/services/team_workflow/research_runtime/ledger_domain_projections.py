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


_BUDGET_COUNTER_KEYS = (
    "tokens",
    "toolCalls",
    "wallClockSeconds",
    "maxRetries",
)
_TERMINAL_CONSUMED_STATUSES = frozenset({"settled", "consumed"})
_TERMINAL_UNUSED_STATUSES = frozenset({"released", "voided", "failed"})


def _counter(value: object) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _normalized_budget_counters(value: Any, *, requested: bool = False) -> dict[str, int]:
    raw = dict(value) if isinstance(value, dict) else {}
    tokens = raw.get("tokens")
    if requested and tokens is None:
        tokens = raw.get("estimatedTokens")
    return {
        "tokens": _counter(tokens),
        "toolCalls": _counter(raw.get("toolCalls")),
        "wallClockSeconds": _counter(
            raw.get("wallClockSeconds", raw.get("seconds"))
        ),
        "maxRetries": _counter(raw.get("maxRetries", raw.get("retries"))),
    }


def _actual_usage(value: Any) -> dict[str, Any]:
    actual = dict(value) if isinstance(value, dict) else {}
    if "wallClockSeconds" not in actual and "seconds" in actual:
        actual["wallClockSeconds"] = _counter(actual.pop("seconds"))
    if "maxRetries" not in actual and "retries" in actual:
        actual["maxRetries"] = _counter(actual.pop("retries"))
    return actual


def _budget_records(snapshot: ResearchWorkflowSnapshot) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    run_id = snapshot.run.run_id
    reservations: list[dict[str, Any]] = []
    stages: dict[str, dict[str, Any]] = {}
    for ref in snapshot.budget_summary.receipt_refs:
        reserved_payload = dict(ref.reserved_payload)
        settled_payload = dict(ref.settled_payload)
        requested = _normalized_budget_counters(
            reserved_payload.get("reserved", reserved_payload),
            requested=True,
        )
        limits = _normalized_budget_counters(reserved_payload.get("limits"))
        actual = _actual_usage(settled_payload.get("usage"))
        actual_counters = _normalized_budget_counters(actual)
        stage_id = str(ref.stage_id or "")
        status = str(ref.status or "")
        reservation = {
            "reservationId": str(ref.reservation_id or ""),
            "receiptId": str(ref.receipt_id or ""),
            "runId": run_id,
            "nodeRunId": str(ref.node_run_id or ""),
            "stageId": stage_id,
            "budgetLedgerId": f"budget-{run_id}-{stage_id}",
            "requested": requested,
            "actual": actual,
            "status": status,
            "policySnapshotHash": str(ref.policy_hash or ""),
            "reservedAtMs": ref.created_at_ms,
            "settledAtMs": (
                ref.updated_at_ms if status in _TERMINAL_CONSUMED_STATUSES else None
            ),
        }
        reservations.append(reservation)

        stage = stages.setdefault(
            stage_id,
            {
                "budgetLedgerId": f"budget-{run_id}-{stage_id}",
                "runId": run_id,
                "stageId": stage_id,
                "policySnapshotHash": str(ref.policy_hash or ""),
                "limits": {key: 0 for key in _BUDGET_COUNTER_KEYS},
                "reserved": {key: 0 for key in _BUDGET_COUNTER_KEYS},
                "consumed": {key: 0 for key in _BUDGET_COUNTER_KEYS},
                "remaining": {key: 0 for key in _BUDGET_COUNTER_KEYS},
                "stopReason": "",
                "updatedAtMs": ref.updated_at_ms,
            },
        )
        for key in _BUDGET_COUNTER_KEYS:
            stage["limits"][key] = max(stage["limits"][key], limits[key])
            if status in _TERMINAL_CONSUMED_STATUSES:
                stage["consumed"][key] += actual_counters[key]
            elif status not in _TERMINAL_UNUSED_STATUSES:
                stage["reserved"][key] += requested[key]
        stage["updatedAtMs"] = max(
            _counter(stage.get("updatedAtMs")),
            _counter(ref.updated_at_ms),
        )

    for stage in stages.values():
        stage["remaining"] = {
            key: max(
                0,
                stage["limits"][key]
                - stage["reserved"][key]
                - stage["consumed"][key],
            )
            for key in _BUDGET_COUNTER_KEYS
        }
    return list(stages.values()), reservations


def snapshot_projection_record(snapshot: ResearchWorkflowSnapshot) -> dict[str, Any]:
    run = snapshot.run.to_dict()
    budget_ledgers, budget_reservations = _budget_records(snapshot)
    return {
        "runId": run["runId"],
        "teamId": run["teamId"],
        "runVersion": run["runVersion"],
        "projectId": run["projectId"],
        "handoffs": [item.to_dict() for item in snapshot.handoff_summary.refs],
        "nodeRuns": [],
        "artifactManifests": [],
        "budgetLedgers": budget_ledgers,
        "budgetReservations": budget_reservations,
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
