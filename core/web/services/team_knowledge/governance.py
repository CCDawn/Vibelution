"""Governed proposals and immutable reviewed revisions in the canonical owner store."""

from __future__ import annotations

from typing import Any

from . import lifecycle

def _service():
    from core.web.services import team_knowledge_service
    return team_knowledge_service


def create_refinement_proposal(
    knowledge_base_id: str,
    *,
    source_artifact_ids: list[str] | None,
    proposed_by_agent_id: str = "",
    title: str,
    summary: str = "",
    content: str,
    tags: list[str] | None = None,
    required_reviewer_agent_id: str = "",
    research_project_id: str = "",
    question_id: str = "",
    source_collection_run_id: str = "",
    source_candidate_id: str = "",
    source_identity_hash: str = "",
    evidence_level: str = "",
    supersedes_knowledge_item_id: str = "",
    expected_content_sha256: str = "",
    revision_reason: str = "",
) -> dict[str, Any]:
    s = _service()
    owner, base = s._require_base_with_owner(knowledge_base_id)
    actor_agent_id = str(proposed_by_agent_id or "").strip()
    s._require_permission(owner, base, actor_agent_id, "propose")
    normalized_title = s.trim_lines(title or "", max_lines=1).strip()
    normalized_content = s._normalize_formal_knowledge_content(content)
    if not normalized_title:
        raise s.TeamKnowledgeError("Proposal title is required.")
    if not normalized_content:
        raise s.TeamKnowledgeError("Proposal content is required.")
    artifact_ids = s._unique_strings(source_artifact_ids or [])
    if not artifact_ids:
        raise s.TeamKnowledgeError("Formal knowledge proposals require at least one central source artifact.")
    central_source_ids: list[str] = []
    artifacts_by_id = {
        str(item.get("sourceArtifactId") or ""): item
        for item in s._source_artifacts_for_base(owner, base["knowledgeBaseId"])
    }
    known_artifacts = set(artifacts_by_id)
    missing = [item for item in artifact_ids if item not in known_artifacts]
    if missing:
        raise s.TeamKnowledgeError(f"Unknown source artifact ids: {', '.join(missing[:3])}")
    ungoverned = [
        item_id
        for item_id in artifact_ids
        if not str((artifacts_by_id.get(item_id) or {}).get("centralSourceId") or "").strip()
    ]
    if ungoverned:
        raise s.TeamKnowledgeError("Formal knowledge proposals require central-curated source artifacts.")
    central_source_ids = s._unique_strings(
        str((artifacts_by_id.get(item_id) or {}).get("centralSourceId") or "")
        for item_id in artifact_ids
    )
    financial_tags = s._tk_financial.validate_financial_proposal(owner, base, artifact_ids, normalized_content)
    now = s.utc_now_iso()
    proposal = {
        "proposalId": s._new_event_id("kprop"),
        "ownerType": owner["ownerType"],
        "ownerId": owner["ownerId"],
        "teamId": owner["ownerId"] if owner["ownerType"] == "team" else "",
        "agentId": owner["ownerId"] if owner["ownerType"] == "agent" else "",
        "targetKnowledgeBaseId": base["knowledgeBaseId"],
        "sourceArtifactIds": artifact_ids,
        "centralSourceIds": central_source_ids,
        "proposedByAgentId": actor_agent_id,
        "requiredReviewerAgentId": s.trim_lines(required_reviewer_agent_id or "", max_lines=1).strip(),
        "researchProjectId": s.trim_lines(research_project_id or "", max_lines=1).strip(),
        "questionId": s.trim_lines(question_id or "", max_lines=1).strip(),
        "sourceCollectionRunId": s.trim_lines(source_collection_run_id or "", max_lines=1).strip(),
        "sourceCandidateId": s.trim_lines(source_candidate_id or "", max_lines=1).strip(),
        "sourceIdentityHash": s.trim_lines(source_identity_hash or "", max_lines=1).strip(),
        "evidenceLevel": s.trim_lines(evidence_level or "", max_lines=1).strip(),
        "status": "pending",
        "title": normalized_title,
        "summary": s.trim_lines(summary or "", max_lines=6).strip(),
        "content": normalized_content,
        "tags": s._unique_strings(s._tk_financial.merge_financial_tags(financial_tags, tags))[:24],
        "createdAt": now,
        "updatedAt": now,
        "reviewedAt": "",
        "reviewedByAgentId": "",
        "resolutionNote": "",
        "batchId": "",
        "knowledgeItemIds": [],
    }
    with s._LOCK:
        if str(base.get("status") or "active") != "active":
            raise s.TeamKnowledgeError("An archived knowledge base cannot receive proposals.")
        proposal["sourceLifecycleRevisions"] = lifecycle.require_active_sources(owner, base, artifact_ids)
        parent = str(supersedes_knowledge_item_id or "").strip()
        if parent:
            proposal.update(lifecycle.prepare_revision_fields(
                owner, base, parent, expected_content_sha256=expected_content_sha256, reason=revision_reason,
            ))
        elif expected_content_sha256 or revision_reason:
            raise s.TeamKnowledgeError("Revision hash and reason require a supersedesKnowledgeItemId.")
        s._append_jsonl(s._proposals_path_for_owner(owner), proposal)
        s._append_audit(owner, "knowledge.proposal.created", proposal, actor_agent_id=actor_agent_id)
    s._record_event(
        "knowledge.proposal.created",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=actor_agent_id,
        fields={"proposalId": proposal["proposalId"], "sourceArtifactCount": len(artifact_ids)},
    )
    return proposal



def review_refinement_proposal(
    knowledge_base_id: str,
    proposal_id: str,
    *,
    status: str,
    reviewed_by_agent_id: str = "",
    resolution_note: str = "",
) -> dict[str, Any]:
    s = _service()
    owner, base = s._require_base_with_owner(knowledge_base_id)
    reviewer_id = str(reviewed_by_agent_id or "").strip()
    s._require_permission(owner, base, reviewer_id, "review")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"approved", "applied", "rejected"}:
        raise s.TeamKnowledgeError("Review status must be approved, applied, or rejected.")
    with s._LOCK:
        proposals = s._read_jsonl(s._proposals_path_for_owner(owner))
        proposal = s._find_by_id(proposals, "proposalId", proposal_id)
        if not proposal or str(proposal.get("targetKnowledgeBaseId") or "") != base["knowledgeBaseId"]:
            raise s.TeamKnowledgeNotFoundError("Knowledge proposal not found.")
        if str(proposal.get("status") or "") != "pending":
            raise s.TeamKnowledgeError("Only pending proposals can be reviewed.")
        required_reviewer_id = str(proposal.get("requiredReviewerAgentId") or "").strip()
        proposer_id = str(proposal.get("proposedByAgentId") or "").strip()
        if required_reviewer_id and reviewer_id != required_reviewer_id:
            raise s.TeamKnowledgePermissionError("This proposal must be reviewed by its designated reviewer.")
        if required_reviewer_id and proposer_id and reviewer_id == proposer_id:
            raise s.TeamKnowledgePermissionError("A designated reviewer cannot review their own proposal.")
        if owner["ownerType"] == "team" and proposer_id and reviewer_id == proposer_id:
            raise s.TeamKnowledgePermissionError("Team proposals must be reviewed by an Agent other than the proposer.")
        if normalized_status != "rejected":
            if str(base.get("status") or "active") != "active":
                raise s.TeamKnowledgeError("An archived knowledge base cannot apply proposals.")
            source_revisions = lifecycle.require_active_sources(owner, base, list(proposal.get("sourceArtifactIds") or []))
            captured = proposal.get("sourceLifecycleRevisions") or {key: 0 for key in source_revisions}
            if captured != source_revisions:
                raise s.TeamKnowledgeIdempotencyConflictError("Knowledge sources changed; submit a fresh proposal.")
            lifecycle.validate_revision_review(owner, base, proposal)
            s._tk_financial.validate_financial_proposal(
                owner,
                base,
                list(proposal.get("sourceArtifactIds") or []),
                str(proposal.get("content") or ""),
            )
        now = s.utc_now_iso()
        proposal["status"] = "rejected" if normalized_status == "rejected" else "applied"
        proposal["updatedAt"] = now
        proposal["reviewedAt"] = now
        proposal["reviewedByAgentId"] = reviewer_id
        proposal["resolutionNote"] = s.trim_lines(resolution_note or "", max_lines=4).strip()
        batch: dict[str, Any] | None = None
        item: dict[str, Any] | None = None
        if proposal["status"] == "applied":
            batch = s._batch_from_proposal(owner, base, proposal, reviewer_id, now)
            item = s._item_from_proposal(owner, base, proposal, batch, reviewer_id, now)
            item = lifecycle.decorate_revision_item(item, proposal)
            proposal["batchId"] = batch["batchId"]
            proposal["knowledgeItemIds"] = [item["knowledgeItemId"]]
            s._append_jsonl(s._batches_path_for_owner(owner), batch)
            s._append_jsonl(s._items_path_for_owner(owner), item)
            s._append_audit(owner, "knowledge.batch.applied", batch, actor_agent_id=reviewer_id)
        s._write_jsonl(s._proposals_path_for_owner(owner), proposals)
        s._append_audit(owner, "knowledge.proposal.reviewed", proposal, actor_agent_id=reviewer_id)
    s._record_event(
        "knowledge.proposal.reviewed",
        owner,
        base["knowledgeBaseId"],
        actor_agent_id=reviewer_id,
        fields={"proposalId": proposal["proposalId"], "status": proposal["status"], "batchId": proposal.get("batchId") or ""},
    )
    if batch:
        s._record_event(
            "knowledge.batch.applied",
            owner,
            base["knowledgeBaseId"],
            actor_agent_id=reviewer_id,
            fields={"batchId": batch["batchId"], "knowledgeItemCount": 1},
        )
    payload = {"proposal": proposal, "batch": batch, "item": item}
    if item:
        from .semantic import sync_reviewed_item
        payload["semanticIndex"] = sync_reviewed_item(knowledge_base_id, item, agent_id=reviewer_id)
    return payload
