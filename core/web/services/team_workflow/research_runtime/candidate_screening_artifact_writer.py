"""Persist one immutable stage-one candidate screening decision."""

from __future__ import annotations

from core.research.workflow.contracts import CandidateScreeningArtifact

from .artifact_readback_registry import build_canonical_ref
from .human_gate_artifacts import canonical_sha256
from .workflow_artifact_store import put_workflow_artifact

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


__all__ = ["record_candidate_screening_artifact"]
