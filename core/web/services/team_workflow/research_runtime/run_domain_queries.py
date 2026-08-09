"""Read-only domain projections for one canonical WorkflowRun."""

from __future__ import annotations

from typing import Any


def _envelope(record: dict[str, Any], key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runId": str(record["runId"]),
        "teamId": str(record["teamId"]),
        "runVersion": int(record["runVersion"]),
        key: items,
    }


def project_budget(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **_envelope(
            record,
            "budgetLedgers",
            [dict(item) for item in record.get("budgetLedgers") or []],
        ),
        "budgetReservations": [
            dict(item) for item in record.get("budgetReservations") or []
        ],
    }


def project_hypotheses(record: dict[str, Any]) -> dict[str, Any]:
    return _envelope(
        record,
        "hypothesisPortfolios",
        [dict(item) for item in record.get("hypothesisPortfolios") or []],
    )


def project_experiment_campaigns(record: dict[str, Any]) -> dict[str, Any]:
    return _envelope(
        record,
        "experimentCampaigns",
        [dict(item) for item in record.get("experimentCampaigns") or []],
    )


def project_evaluation(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **_envelope(
            record,
            "competitionEvaluations",
            [dict(item) for item in record.get("competitionEvaluations") or []],
        ),
        "qualityGateEvaluations": [
            dict(item) for item in record.get("qualityGateEvaluations") or []
        ],
    }
