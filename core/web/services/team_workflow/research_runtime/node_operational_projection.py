"""Read-only operational projection for one workflow node attempt."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _latest(
    items: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any] | None:
    return next((dict(item) for item in reversed(items) if predicate(item)), None)


def project_node_operations(
    record: dict[str, Any],
    node_id: str,
) -> dict[str, Any]:
    node_runs = [
        dict(item)
        for item in record.get("nodeRuns") or []
        if str(item.get("nodeId") or "") == node_id
    ]
    latest_node_run = node_runs[-1] if node_runs else None
    node_run_id = str((latest_node_run or {}).get("nodeRunId") or "")
    envelope = _latest(
        list(record.get("executionEnvelopes") or []),
        lambda item: str(item.get("nodeId") or "") == node_id,
    )
    lease = _latest(
        list(record.get("taskLeases") or []),
        lambda item: bool(node_run_id)
        and str(item.get("nodeRunId") or "") == node_run_id,
    )
    quality_gate = _latest(
        list(record.get("qualityGateEvaluations") or []),
        lambda item: str(item.get("nodeId") or "") == node_id,
    )
    manifests = [
        dict(item)
        for item in record.get("artifactManifests") or []
        if bool(node_run_id)
        and str(item.get("producerNodeRunId") or "") == node_run_id
    ]
    return {
        "executionEnvelope": envelope,
        "taskLease": lease,
        "qualityGateEvaluation": quality_gate,
        "artifactManifests": manifests,
        "artifactReuseCount": sum(
            1 for item in manifests if item.get("cacheDisposition") == "reused"
        ),
    }
