"""Retry charging policy for workflow NodeRun lineage."""

from __future__ import annotations

from typing import Any

INFRASTRUCTURE_FAILURE_CODES = {
    "external_task_interrupted",
    "lease_expired",
}


def retry_kind_for(node_run: dict[str, Any]) -> str:
    failure_code = str(node_run.get("failureCode") or "").strip()
    if failure_code in INFRASTRUCTURE_FAILURE_CODES:
        return "infrastructure_recovery"
    return "business_retry"


def charged_retry_count(record: dict[str, Any], node_id: str) -> int:
    node_runs = [
        item
        for item in record.get("nodeRuns") or []
        if str(item.get("nodeId") or "") == node_id
    ]
    return sum(
        1
        for item in node_runs[1:]
        if item.get("countsAgainstRetryBudget") is not False
    )


def retry_is_available(
    record: dict[str, Any],
    node_id: str,
    latest: dict[str, Any],
) -> tuple[bool, str]:
    retry_kind = retry_kind_for(latest)
    if retry_kind == "infrastructure_recovery":
        return True, retry_kind
    max_retries = int(
        ((record.get("inputSnapshot") or {}).get("budgetPolicy") or {}).get(
            "maxRetries", 0
        )
    )
    return charged_retry_count(record, node_id) < max_retries, retry_kind
