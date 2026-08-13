"""Canonical Team Knowledge artifact read-back for research workflow runs."""

from __future__ import annotations

from typing import Any

from .human_gate_artifacts import canonical_sha256

_MATERIALIZED_INGESTION_STATES = {"pending_review", "official_synced"}


def load_knowledge_package_draft_payload(
    *,
    team_id: str,
    authority_run_id: str,
    workflow_run_id: str = "",
    content_hash: str = "",
) -> dict[str, Any] | None:
    """Read one immutable steward draft from the canonical candidate authority.

    Collection selects the newest strictly scoped draft. Read-back with a
    content hash searches every scoped draft so a later retry cannot invalidate
    an already-issued canonical reference.
    """
    from core.web.services.team_workflow.source_collection.candidates import (
        list_candidate_store,
    )

    response = list_candidate_store(team_id, limit=500)

    scoped = [
        candidate
        for candidate in list(response.get("candidates") or [])
        if isinstance(candidate, dict)
        and _is_materialized_scoped_draft(
            candidate,
            team_id=team_id,
            authority_run_id=authority_run_id,
            workflow_run_id=workflow_run_id,
        )
    ]
    ordered = sorted(
        scoped,
        key=lambda candidate: (
            str(candidate.get("updatedAt") or ""),
            str(candidate.get("createdAt") or ""),
            str(candidate.get("candidateId") or ""),
        ),
        reverse=True,
    )
    for candidate in ordered:
        payload = _draft_payload(
            candidate,
            team_id=team_id,
            authority_run_id=authority_run_id,
        )
        if not content_hash or canonical_sha256(payload) == content_hash:
            return payload
    return None


def _is_materialized_scoped_draft(
    candidate: dict[str, Any],
    *,
    team_id: str,
    authority_run_id: str,
    workflow_run_id: str,
) -> bool:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    trace = output.get("sourceTrace") if isinstance(output.get("sourceTrace"), dict) else {}
    validation = (
        metadata.get("validation") if isinstance(metadata.get("validation"), dict) else {}
    )
    ingestion = (
        metadata.get("knowledgeIngestion")
        if isinstance(metadata.get("knowledgeIngestion"), dict)
        else {}
    )
    candidate_team = str(candidate.get("teamId") or "").strip()
    trace_team = str(trace.get("teamId") or "").strip()
    trace_authority = str(trace.get("sourceCollectionRunId") or "").strip()
    trace_workflow = str(trace.get("workflowRunId") or "").strip()
    return bool(
        str(metadata.get("taskType") or "") == "steward_pack_draft"
        and output
        and validation.get("valid") is True
        and str(ingestion.get("status") or "") in _MATERIALIZED_INGESTION_STATES
        and candidate_team == team_id
        and trace_team == team_id
        and trace_authority == authority_run_id
        and (not workflow_run_id or not trace_workflow or trace_workflow == workflow_run_id)
    )


def _draft_payload(
    candidate: dict[str, Any],
    *,
    team_id: str,
    authority_run_id: str,
) -> dict[str, Any]:
    metadata = candidate["metadata"]
    return {
        "teamId": team_id,
        "sourceCollectionRunId": authority_run_id,
        "candidateId": str(candidate.get("candidateId") or ""),
        "draft": dict(metadata["output"]),
        "validation": dict(metadata["validation"]),
    }
