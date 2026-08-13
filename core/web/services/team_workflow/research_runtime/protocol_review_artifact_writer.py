"""Validate and persist one formal protocol-review report."""

from __future__ import annotations

from typing import Any

from .workflow_artifact_store import put_workflow_artifact

_REQUIRED_CHECKS = (
    "dataset",
    "baseline",
    "metric",
    "seed",
    "budget",
    "stop_condition",
    "smoke_plan",
)
_ALLOWED_STATUSES = {"approved", "changes_requested"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Protocol review {field} must be a non-negative integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Protocol review {field} must be a non-negative integer."
        ) from exc
    if parsed < 0:
        raise ValueError(f"Protocol review {field} must be a non-negative integer.")
    return parsed


def record_protocol_review_report(
    *,
    team_id: str,
    task_context: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Write the immutable review report for the task-bound protocol draft."""
    task = (
        task_context.get("task")
        if isinstance(task_context.get("task"), dict)
        else {}
    )
    review_input = (
        task_context.get("protocolReviewInput")
        if isinstance(task_context.get("protocolReviewInput"), dict)
        else {}
    )
    protocol = (
        review_input.get("protocolDraft")
        if isinstance(review_input.get("protocolDraft"), dict)
        else {}
    )
    if task.get("taskKind") != "protocol_review" or task.get(
        "workflowNodeId"
    ) != "protocol_review":
        raise ValueError("Protocol review requires a bound protocol_review task.")
    if review_input.get("status") != "ready" or not protocol:
        raise ValueError("Formal protocol_draft is not ready for review.")
    workflow_run_id = _text(task.get("workflowRunId"))
    source_run_id = _text(task.get("sourceCollectionRunId"))
    task_id = _text(task.get("taskId"))
    protocol_id = _text(protocol.get("protocolId") or protocol.get("planId"))
    if not workflow_run_id or not source_run_id or not task_id or not protocol_id:
        raise ValueError("Bound protocol review is missing workflow identity.")
    status = _text(payload.get("status")).lower()
    if status not in _ALLOWED_STATUSES:
        raise ValueError("Protocol review status must be approved or changes_requested.")
    blocking_issue_count = _non_negative_int(
        payload.get("blocking_issue_count"), field="blocking_issue_count"
    )
    open_waivers = _non_negative_int(
        payload.get("open_waivers"), field="open_waivers"
    )
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    missing_checks = [name for name in _REQUIRED_CHECKS if name not in checks]
    if missing_checks:
        raise ValueError(
            f"Protocol review is missing checks: {', '.join(missing_checks)}."
        )
    if status == "approved":
        if blocking_issue_count or open_waivers:
            raise ValueError("Approved protocol review cannot have blockers or waivers.")
        failed_checks = [
            name for name in _REQUIRED_CHECKS if _text(checks.get(name)).lower() != "pass"
        ]
        if failed_checks:
            raise ValueError(
                f"Approved protocol review has non-passing checks: {', '.join(failed_checks)}."
            )
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ValueError("Protocol review findings must be a list.")
    report_payload = {
        "reviewId": f"review-{task_id}",
        "protocolId": protocol_id,
        "status": status,
        "blocking_issue_count": blocking_issue_count,
        "open_waivers": open_waivers,
        "checks": {name: _text(checks.get(name)).lower() for name in _REQUIRED_CHECKS},
        "findings": findings[:24],
        "researchProjectId": _text(task.get("researchProjectId")),
        "createdFromTaskId": task_id,
        "createdFromSessionId": _text(task.get("sessionId")),
        "createdFromTurnId": _text((task.get("turn") or {}).get("turnId")),
        "reviewedByAgent": _text(task.get("agentId")),
    }
    record = put_workflow_artifact(
        team_id,
        kind="protocol_review_report",
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_run_id,
        artifact_identity=report_payload["reviewId"],
        payload=report_payload,
    )
    return {
        "artifact": {
            "recordId": _text(record.get("recordId")),
            "kind": "protocol_review_report",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "contentHash": _text(record.get("contentHash")),
        },
        "scopeBinding": {
            "workflowRunId": workflow_run_id,
            "protocolId": protocol_id,
            "source": "bound_protocol_review_task",
        },
    }
