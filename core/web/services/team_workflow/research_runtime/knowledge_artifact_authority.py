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
        list_candidate_store_authority_records,
    )

    authority_candidates = list_candidate_store_authority_records(
        team_id,
        run_id=authority_run_id,
        metadata_task_type="steward_pack_draft",
    )

    scoped = [
        candidate
        for candidate in authority_candidates
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


def load_knowledge_package_payload(
    *,
    team_id: str,
    authority_run_id: str,
    workflow_run_id: str = "",
    content_hash: str = "",
) -> dict[str, Any] | None:
    """Read an accepted package from approved Team Knowledge items.

    The candidate record locates the authoritative approval. The artifact
    payload contains only stable KnowledgeItem content and approval identities,
    so later metadata edits cannot silently change an issued receipt.
    """
    from core.web.services import team_knowledge_service, team_service
    from core.web.services.team_workflow.source_collection.candidates import (
        list_candidate_store_authority_records,
    )

    try:
        authority_candidates = list_candidate_store_authority_records(
            team_id,
            run_id=authority_run_id,
            metadata_task_type="steward_pack_draft",
        )
    except team_service.TeamNotFoundError:
        return None
    candidates = [
        candidate
        for candidate in authority_candidates
        if isinstance(candidate, dict)
        and _is_materialized_scoped_draft(
            candidate,
            team_id=team_id,
            authority_run_id=authority_run_id,
            workflow_run_id=workflow_run_id,
        )
        and _official_package_identity(candidate) is not None
    ]
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            str(candidate.get("updatedAt") or ""),
            str(candidate.get("createdAt") or ""),
            str(candidate.get("candidateId") or ""),
        ),
        reverse=True,
    )
    for candidate in ordered:
        identity = _official_package_identity(candidate)
        if identity is None:
            continue
        base_id, item_ids, reviewer_id = identity
        try:
            response = team_knowledge_service.list_knowledge_items(
                base_id,
                agent_id=reviewer_id,
            )
        except team_knowledge_service.TeamKnowledgeError:
            continue
        item_by_id = {
            str(item.get("knowledgeItemId") or ""): item
            for item in list(response.get("items") or [])
            if isinstance(item, dict)
        }
        if any(item_id not in item_by_id for item_id in item_ids):
            continue
        payload = _accepted_package_payload(
            candidate,
            team_id=team_id,
            authority_run_id=authority_run_id,
            knowledge_base_id=base_id,
            item_ids=item_ids,
            item_by_id=item_by_id,
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
    output = dict(metadata["output"])
    validation = dict(metadata["validation"])
    return {
        "teamId": team_id,
        "sourceCollectionRunId": authority_run_id,
        "candidateId": str(candidate.get("candidateId") or ""),
        "draft": output,
        "validation": validation,
        "reviewable": bool(
            validation.get("valid") is True
            and (
                output.get("requiresReview") is True
                or output.get("approvalRequired") is True
            )
        ),
    }


def _official_package_identity(
    candidate: dict[str, Any],
) -> tuple[str, tuple[str, ...], str] | None:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    ingestion = (
        metadata.get("knowledgeIngestion")
        if isinstance(metadata.get("knowledgeIngestion"), dict)
        else {}
    )
    if str(ingestion.get("status") or "") != "official_synced":
        return None
    base_id = str(ingestion.get("knowledgeBaseId") or "").strip()
    item_ids = tuple(
        sorted(
            {
                str(item).strip()
                for item in list(ingestion.get("knowledgeItemIds") or [])
                if str(item).strip()
            }
        )
    )
    reviewer_id = str(ingestion.get("reviewedByAgentId") or "").strip()
    if not base_id or not item_ids or not reviewer_id:
        return None
    return base_id, item_ids, reviewer_id


def _accepted_package_payload(
    candidate: dict[str, Any],
    *,
    team_id: str,
    authority_run_id: str,
    knowledge_base_id: str,
    item_ids: tuple[str, ...],
    item_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    metadata = candidate["metadata"]
    ingestion = metadata["knowledgeIngestion"]
    knowledge_items = []
    for item_id in item_ids:
        item = item_by_id[item_id]
        stable_content = {
            "knowledgeItemId": item_id,
            "knowledgeBaseId": str(item.get("knowledgeBaseId") or ""),
            "title": str(item.get("title") or ""),
            "summary": str(item.get("summary") or ""),
            "content": str(item.get("content") or ""),
            "sourceArtifactIds": sorted(
                str(value)
                for value in list(item.get("sourceArtifactIds") or [])
                if str(value)
            ),
            "createdAt": str(item.get("createdAt") or ""),
        }
        knowledge_items.append(
            {
                "knowledgeItemId": item_id,
                "contentHash": canonical_sha256(stable_content),
            }
        )
    return {
        "teamId": team_id,
        "sourceCollectionRunId": authority_run_id,
        "candidateId": str(candidate.get("candidateId") or ""),
        "knowledgeBaseId": knowledge_base_id,
        "knowledgeItems": knowledge_items,
        "sourceArtifactIds": sorted(
            {
                str(value)
                for value in [
                    *list(ingestion.get("sourceArtifactIds") or []),
                    ingestion.get("sourceArtifactId"),
                ]
                if str(value or "").strip()
            }
        ),
        "approval": {
            "proposalId": str(ingestion.get("proposalId") or ""),
            "batchId": str(ingestion.get("batchId") or ""),
            "reviewedAt": str(ingestion.get("reviewedAt") or ""),
            "reviewedByAgentId": str(ingestion.get("reviewedByAgentId") or ""),
        },
        "accepted": True,
    }
