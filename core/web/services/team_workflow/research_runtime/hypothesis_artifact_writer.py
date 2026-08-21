"""Validate and persist one formal hypothesis portfolio."""

from __future__ import annotations

import copy
from typing import Any

from core.research.workflow.contracts import HypothesisPortfolio

from .workflow_artifact_store import put_workflow_artifact


def _text(value: Any) -> str:
    return str(value or "").strip()


def record_hypothesis_set(
    *,
    team_id: str,
    task_context: dict[str, Any],
    payload: dict[str, Any],
    artifact_identity: str = "",
) -> dict[str, Any]:
    """Fail closed unless every hypothesis is scoped to accepted evidence."""
    task = (
        task_context.get("task")
        if isinstance(task_context.get("task"), dict)
        else {}
    )
    hypothesis_input = (
        task_context.get("hypothesisInput")
        if isinstance(task_context.get("hypothesisInput"), dict)
        else {}
    )
    if hypothesis_input.get("status") != "ready":
        raise ValueError(
            "Accepted knowledge package is not ready for hypothesis writeback."
        )
    workflow_run_id = _text(task.get("workflowRunId"))
    source_run_id = _text(task.get("sourceCollectionRunId"))
    if not workflow_run_id or not source_run_id:
        raise ValueError("Bound hypothesis task is missing workflow scope.")
    canonical_payload = {**payload, "runId": workflow_run_id}
    portfolio = HypothesisPortfolio.from_dict(canonical_payload)
    if not portfolio.candidates:
        raise ValueError("Hypothesis portfolio requires at least one candidate.")
    allowed_refs = {
        _text(item)[:200]
        for item in list(hypothesis_input.get("allowedEvidenceRefs") or [])
        if _text(item)[:200]
    }
    used_refs = {
        ref
        for candidate in portfolio.candidates
        for ref in candidate.counterEvidenceRefs
        if ref
    }
    if any(not candidate.counterEvidenceRefs for candidate in portfolio.candidates):
        raise ValueError(
            "Every hypothesis candidate requires a counter-evidence reference."
        )
    unknown_refs = sorted(used_refs - allowed_refs)
    if unknown_refs:
        raise ValueError(
            "Hypothesis counter-evidence references are outside the accepted knowledge package: "
            + ", ".join(unknown_refs[:8])
        )
    current_round = payload.get("currentEvolutionRound", 1)
    if isinstance(current_round, bool) or not isinstance(current_round, int):
        raise ValueError("currentEvolutionRound must be an integer.")
    if current_round < 1 or current_round > portfolio.maxEvolutionRounds:
        raise ValueError("currentEvolutionRound exceeds the hypothesis round limit.")
    artifact_payload = {
        **portfolio.to_dict(),
        "hypothesis_count": len(portfolio.candidates),
        "currentEvolutionRound": current_round,
        "createdFromTaskId": _text(task.get("taskId")),
        "createdFromSessionId": _text(task.get("sessionId")),
        "createdFromTurnId": _text((task.get("turn") or {}).get("turnId")),
    }
    # Fan-in metadata is structured provenance, not a replacement for the
    # canonical HypothesisPortfolio.  Preserve it so downstream readers can
    # trace each candidate to its child session without reading messages.
    for key in (
        "selectionId",
        "fragmentRefs",
        "aggregationMode",
        "candidateSessionAnchors",
        "candidateDetails",
        "provenance",
    ):
        if key in payload:
            artifact_payload[key] = copy.deepcopy(payload[key])
    if _text(payload.get("contentHash")):
        artifact_payload["fragmentAggregationHash"] = _text(payload["contentHash"])
    record = put_workflow_artifact(
        team_id,
        kind="hypothesis_set",
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_run_id,
        artifact_identity=_text(artifact_identity) or portfolio.portfolioId,
        payload=artifact_payload,
    )
    return {
        "artifact": {
            "recordId": _text(record.get("recordId")),
            "kind": "hypothesis_set",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "contentHash": _text(record.get("contentHash")),
        },
        "scopeBinding": {
            "workflowRunId": workflow_run_id,
            "source": "bound_hypothesis_task",
        },
    }


def record_hypothesis_set_from_fragments(
    *,
    team_id: str,
    task_context: dict[str, Any],
    selection: dict[str, Any],
    fragments: list[dict[str, Any]],
    scope: dict[str, Any],
    artifact_identity: str = "",
) -> dict[str, Any]:
    """Aggregate structured child fragments, then use the canonical writer.

    This bridge keeps the existing ``hypothesis_set`` authority intact.  The
    aggregator never receives a session store and therefore cannot fall back
    to transcript summarization.
    """
    from .hypothesis_fragment_aggregator import aggregate_hypothesis_fragments

    payload = aggregate_hypothesis_fragments(
        selection=selection,
        fragments=fragments,
        scope=scope,
    )
    return record_hypothesis_set(
        team_id=team_id,
        task_context=task_context,
        payload=payload,
        artifact_identity=artifact_identity,
    )
