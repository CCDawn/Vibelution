"""Retry charging policy for workflow NodeRun lineage.

Outcome classification is owned by the frozen taxonomy in
``core.research.workflow.contracts.retry_taxonomy``; this module keeps the
NodeRun-lineage view (retry-kind strings, ledger-driven charged counting and
budget gating). Behavior is frozen: ``retry_kind_for`` maps taxonomy-known
codes through :meth:`RetryTaxonomy.node_lineage_retry_kind`, and codes
outside the taxonomy keep the charged ``business_retry`` lineage fallback
instead of failing closed -- the fail-closed contract lives in taxonomy
lookups, not in this legacy lineage view. The ``countsAgainstRetryBudget``
ledger flag written at attempt creation is the durable per-attempt
projection of the taxonomy charge rule, so ``charged_retry_count`` reads the
ledger and stays stable for historical attempts.
"""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts.retry_taxonomy import (
    DEFAULT_RETRY_TAXONOMY,
    NODE_LINEAGE_RETRY_KIND_INFRASTRUCTURE_RECOVERY,
    RetryOutcomeClass,
)

INFRASTRUCTURE_FAILURE_CODES = frozenset(
    DEFAULT_RETRY_TAXONOMY.codes_for_outcome_class(
        RetryOutcomeClass.RETRYABLE_INFRA
    )
)


def retry_kind_for(node_run: dict[str, Any]) -> str:
    failure_code = str(node_run.get("failureCode") or "").strip()
    return DEFAULT_RETRY_TAXONOMY.node_lineage_retry_kind(failure_code)


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
    if retry_kind == NODE_LINEAGE_RETRY_KIND_INFRASTRUCTURE_RECOVERY:
        return True, retry_kind
    max_retries = int(
        ((record.get("inputSnapshot") or {}).get("budgetPolicy") or {}).get(
            "maxRetries", 0
        )
    )
    return charged_retry_count(record, node_id) < max_retries, retry_kind
