"""Canonical Team Knowledge artifact read-back for research workflow runs."""

from __future__ import annotations

from collections.abc import Sequence
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
    identities = [
        (candidate, *identity)
        for candidate in ordered
        if (identity := _official_package_identity(candidate)) is not None
    ]

    # A package issued after the aggregation fix must include every official
    # steward draft in the current source scope.  Build that payload first so
    # a new receipt always pins the complete authority, while the hash-bound
    # branch below can still replay an already-issued single-draft receipt.
    aggregate = _aggregate_official_package_identity(identities)
    if aggregate is not None:
        aggregate_candidates, base_id, item_ids, reviewer_ids = aggregate
        item_by_id = _load_official_package_items(
            team_knowledge_service,
            knowledge_base_id=base_id,
            reviewer_ids=reviewer_ids,
        )
        if item_by_id is not None and not any(
            item_id not in item_by_id for item_id in item_ids
        ):
            payload = _aggregate_accepted_package_payload(
                aggregate_candidates,
                team_id=team_id,
                authority_run_id=authority_run_id,
                knowledge_base_id=base_id,
                item_ids=item_ids,
                item_by_id=item_by_id,
            )
            if not content_hash or canonical_sha256(payload) == content_hash:
                return payload

    if not content_hash:
        return None

    # Content-hash reads are immutable historical readback.  Keep the old
    # single-draft shape discoverable by its issued hash, without allowing it
    # to become the payload returned for a new unpinned read.
    for candidate, base_id, item_ids, reviewer_id in identities:
        item_by_id = _load_official_package_items(
            team_knowledge_service,
            knowledge_base_id=base_id,
            reviewer_ids=(reviewer_id,),
        )
        if item_by_id is None or any(
            item_id not in item_by_id for item_id in item_ids
        ):
            continue
        payload = _accepted_package_payload(
            candidate,
            team_id=team_id,
            authority_run_id=authority_run_id,
            knowledge_base_id=base_id,
            item_ids=item_ids,
            item_by_id=item_by_id,
        )
        if canonical_sha256(payload) == content_hash:
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


def _aggregate_official_package_identity(
    identities: list[tuple[dict[str, Any], str, tuple[str, ...], str]],
) -> tuple[
    tuple[dict[str, Any], ...], str, tuple[str, ...], tuple[str, ...]
] | None:
    """Return one complete identity for the current official draft scope.

    All official drafts in one source scope must resolve to the same Team
    Knowledge base.  Each draft keeps its own reviewer identity so a valid
    package is not discarded merely because reviewers differ.
    """
    if not identities:
        return None
    base_ids = {base_id for _, base_id, _, _ in identities}
    if len(base_ids) != 1:
        return None
    base_id = next(iter(base_ids))
    reviewer_ids = tuple(
        sorted({reviewer_id for _, _, _, reviewer_id in identities if reviewer_id})
    )
    if not reviewer_ids:
        return None
    candidates = tuple(
        sorted(
            (candidate for candidate, _, _, _ in identities),
            key=lambda candidate: str(candidate.get("candidateId") or ""),
        )
    )
    item_ids = tuple(
        sorted(
            {
                item_id
                for _, _, candidate_item_ids, _ in identities
                for item_id in candidate_item_ids
                if str(item_id).strip()
            }
        )
    )
    if not candidates or not item_ids:
        return None
    return candidates, base_id, item_ids, reviewer_ids


def _load_official_package_items(
    team_knowledge_service: Any,
    *,
    knowledge_base_id: str,
    reviewer_ids: Sequence[str],
) -> dict[str, dict[str, Any]] | None:
    item_by_id: dict[str, dict[str, Any]] = {}
    loaded = False
    for reviewer_id in reviewer_ids:
        try:
            response = team_knowledge_service.list_knowledge_items(
                knowledge_base_id,
                agent_id=reviewer_id,
            )
        except team_knowledge_service.TeamKnowledgeError:
            continue
        if not isinstance(response, dict):
            continue
        loaded = True
        for item in list(response.get("items") or []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("knowledgeItemId") or "").strip()
            if item_id:
                item_by_id[item_id] = item
    return item_by_id if loaded else None


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


def _aggregate_accepted_package_payload(
    candidates: tuple[dict[str, Any], ...],
    *,
    team_id: str,
    authority_run_id: str,
    knowledge_base_id: str,
    item_ids: tuple[str, ...],
    item_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidate_ids = sorted(
        {
            str(candidate.get("candidateId") or "").strip()
            for candidate in candidates
            if str(candidate.get("candidateId") or "").strip()
        }
    )
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

    approvals = []
    source_artifact_ids = set()
    for candidate in candidates:
        metadata = (
            candidate.get("metadata")
            if isinstance(candidate.get("metadata"), dict)
            else {}
        )
        ingestion = (
            metadata.get("knowledgeIngestion")
            if isinstance(metadata.get("knowledgeIngestion"), dict)
            else {}
        )
        approvals.append(
            {
                "proposalId": str(ingestion.get("proposalId") or ""),
                "batchId": str(ingestion.get("batchId") or ""),
                "reviewedAt": str(ingestion.get("reviewedAt") or ""),
                "reviewedByAgentId": str(
                    ingestion.get("reviewedByAgentId") or ""
                ),
            }
        )
        source_artifact_ids.update(
            str(value).strip()
            for value in [
                *list(ingestion.get("sourceArtifactIds") or []),
                ingestion.get("sourceArtifactId"),
            ]
            if str(value or "").strip()
        )

    return {
        "teamId": team_id,
        "sourceCollectionRunId": authority_run_id,
        "candidateId": candidate_ids[0] if candidate_ids else "",
        "candidateIds": candidate_ids,
        "knowledgeBaseId": knowledge_base_id,
        "knowledgeItems": knowledge_items,
        "sourceArtifactIds": sorted(source_artifact_ids),
        "approval": approvals[0] if approvals else {},
        "approvals": approvals,
        "accepted": True,
    }
