"""Build the bounded formal hypothesis input for protocol-design tasks."""

from __future__ import annotations

from typing import Any

from .research_runtime.artifact_readback_registry import (
    load_scoped_artifact_payload,
)


def _text(value: Any, *, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def build_protocol_input_context(
    team_id: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    """Read the exact workflow-scoped ``hypothesis_set`` for one task."""
    workflow_run_id = _text(task.get("workflowRunId"), limit=200)
    source_run_id = _text(task.get("sourceCollectionRunId"), limit=200)
    if not workflow_run_id or not source_run_id:
        return {
            "status": "missing_workflow_scope",
            "workflowRunId": workflow_run_id,
            "sourceCollectionRunId": source_run_id,
            "hypothesisCount": 0,
            "candidates": [],
        }
    envelope = load_scoped_artifact_payload(
        "hypothesis_set",
        team_id=_text(team_id, limit=160),
        authority_run_id=source_run_id,
        workflow_run_id=workflow_run_id,
    )
    payload = (
        envelope.get("payload")
        if isinstance(envelope, dict) and isinstance(envelope.get("payload"), dict)
        else {}
    )
    candidates = []
    for item in list(payload.get("candidates") or [])[:16]:
        if not isinstance(item, dict):
            continue
        candidate_id = _text(item.get("candidateId"), limit=160)
        claim = _text(item.get("claim"))
        if not candidate_id or not claim:
            continue
        scores = item.get("scores") if isinstance(item.get("scores"), dict) else {}
        candidates.append(
            {
                "candidateId": candidate_id,
                "claim": claim,
                "counterEvidenceRefs": [
                    _text(ref, limit=200)
                    for ref in list(item.get("counterEvidenceRefs") or [])[:24]
                    if _text(ref, limit=200)
                ],
                "status": _text(item.get("status"), limit=80),
                "scores": dict(scores),
            }
        )
    return {
        "status": "ready" if candidates else "missing_hypothesis_set",
        "workflowRunId": workflow_run_id,
        "sourceCollectionRunId": source_run_id,
        "portfolioId": _text(payload.get("portfolioId"), limit=160),
        "hypothesisCount": len(candidates),
        "candidates": candidates,
        "authority": "workflow_hypothesis_set",
    }
