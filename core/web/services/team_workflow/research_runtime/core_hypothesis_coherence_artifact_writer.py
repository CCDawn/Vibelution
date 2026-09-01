"""Persist the stage-one per-candidate core-coherence authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.contracts import (
    ContractValidationError,
    CoreHypothesisCoherenceResult,
)

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact

ARTIFACT_KIND = "core_hypothesis_coherence"


def record_core_hypothesis_coherence_artifact(
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str = "",
    review_context_id: str,
    results: Sequence[Mapping[str, Any]],
    require_receipts: bool,
) -> dict[str, str]:
    parsed = [CoreHypothesisCoherenceResult.from_dict(item) for item in results]
    if len(parsed) < 2 or len({item.candidateId for item in parsed}) != len(parsed):
        raise ContractValidationError(
            "core hypothesis coherence artifact requires at least two unique candidates"
        )
    if require_receipts and any(not item.receiptRef for item in parsed):
        raise ContractValidationError(
            "formal core hypothesis coherence requires a reflection receipt per candidate"
        )
    payload = {
        "schemaVersion": 1,
        "reviewContextId": str(review_context_id or "").strip(),
        "candidateCount": len(parsed),
        "passed": all(item.passed for item in parsed),
        "results": [item.to_dict() for item in parsed],
    }
    identity = f"coherence-{canonical_sha256({'reviewContextId': payload['reviewContextId'], 'candidateIds': [item.candidateId for item in parsed]})[:20]}"
    record = put_workflow_artifact(
        team_id,
        kind=ARTIFACT_KIND,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_collection_run_id,
        artifact_identity=identity,
        payload=payload,
    )
    authority_run_id = str(
        record.get("sourceCollectionRunId")
        or source_collection_run_id
        or workflow_run_id
    ).strip()
    envelope = {
        "teamId": str(team_id or "").strip(),
        "kind": ARTIFACT_KIND,
        "workflowRunId": str(record.get("workflowRunId") or workflow_run_id),
        "sourceCollectionRunId": authority_run_id,
        "payload": payload,
    }
    content_hash = canonical_sha256(envelope)
    return {
        "recordId": str(record.get("recordId") or ""),
        "contentHash": content_hash,
        "canonicalRef": build_canonical_ref(
            kind=ARTIFACT_KIND,
            team_id=team_id,
            authority_run_id=authority_run_id,
            content_hash=content_hash,
        ),
    }


__all__ = ["record_core_hypothesis_coherence_artifact"]
