"""Persist one immutable stage-one candidate screening decision."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.contracts import CandidateScreeningArtifact

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import list_workflow_artifacts, put_workflow_artifact

ARTIFACT_KIND = "candidate_screening"


def record_candidate_screening_artifact(
    *,
    team_id: str,
    workflow_run_id: str,
    artifact: CandidateScreeningArtifact,
) -> dict[str, str]:
    record = put_workflow_artifact(
        team_id,
        kind=ARTIFACT_KIND,
        workflow_run_id=workflow_run_id,
        artifact_identity=artifact.screeningId,
        payload=artifact.to_dict(),
    )
    envelope = {
        "teamId": str(team_id or "").strip(),
        "kind": ARTIFACT_KIND,
        "workflowRunId": str(record.get("workflowRunId") or workflow_run_id),
        "sourceCollectionRunId": str(
            record.get("sourceCollectionRunId") or workflow_run_id
        ),
        "payload": artifact.to_dict(),
    }
    content_hash = canonical_sha256(envelope)
    return {
        "recordId": str(record.get("recordId") or ""),
        "contentHash": content_hash,
        "canonicalRef": build_canonical_ref(
            kind=ARTIFACT_KIND,
            team_id=team_id,
            authority_run_id=workflow_run_id,
            content_hash=content_hash,
        ),
    }


def collapsed_screening_for_candidates(
    records: Sequence[Mapping[str, Any]], *, question_id: str,
    workflow_run_id: str, candidate_ids: Sequence[str],
) -> dict[str, Any] | None:
    """Read a failed screening only for the exact current run and draft pool."""
    ids = set(candidate_ids)
    if not workflow_run_id or not ids:
        return None
    for record in reversed(records):
        if record.get("workflowRunId") != workflow_run_id:
            continue
        payload = record.get("payload") or {}
        if payload.get("questionId") != question_id:
            continue
        candidates = payload.get("candidates") or []
        if {item.get("candidateId") for item in candidates} != ids:
            continue
        finalists = set(payload.get("pairwiseCandidateIds") or [])
        mechanisms = {
            (item.get("axisProfile") or {}).get("mechanism")
            for item in candidates if item.get("candidateId") in finalists
        }
        if len(finalists) < 2 or len(mechanisms) < 2:
            return dict(payload)
        return None
    return None


def read_collapsed_screening(
    team_id: str, *, question_id: str, workflow_run_id: str,
    candidate_ids: Sequence[str],
) -> dict[str, Any] | None:
    if not workflow_run_id:
        return None
    return collapsed_screening_for_candidates(
        list_workflow_artifacts(team_id, kind=ARTIFACT_KIND,
                                workflow_run_id=workflow_run_id),
        question_id=question_id, workflow_run_id=workflow_run_id,
        candidate_ids=candidate_ids,
    )


__all__ = ["record_candidate_screening_artifact", "collapsed_screening_for_candidates",
           "read_collapsed_screening"]
