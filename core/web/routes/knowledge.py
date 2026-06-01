"""Team knowledge platform API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.web.services.team_knowledge_service import (
    TeamKnowledgeError,
    TeamKnowledgeNotFoundError,
    TeamKnowledgePermissionError,
    create_knowledge_base,
    create_ingestion_package,
    create_rating_suggestion,
    create_refinement_proposal,
    create_source_artifact,
    get_knowledge_trace,
    get_knowledge_steward_overview,
    knowledge_permission_audit,
    list_ingestion_adapters,
    list_knowledge_governance_tasks,
    list_knowledge_steward_recommendations,
    list_knowledge_items,
    list_knowledge_overview,
    list_rating_suggestions,
    list_team_knowledge_bases,
    review_rating_suggestions_bulk,
    review_rating_suggestion,
    review_refinement_proposal,
    search_knowledge_items,
    update_knowledge_item_rating,
)


router = APIRouter(tags=["knowledge"])


class KnowledgeBaseCreatePayload(BaseModel):
    name: str = Field("", max_length=160)
    description: str = Field("", max_length=1200)
    actorAgentId: str = Field("", max_length=160)
    acl: dict[str, Any] = Field(default_factory=dict)


class SourceArtifactCreatePayload(BaseModel):
    sourceType: str = Field("", max_length=80)
    sourceRef: dict[str, Any] = Field(default_factory=dict)
    sourceCreatedAt: str = Field("", max_length=80)
    capturedBy: str = Field("", max_length=160)
    sourceHash: str = Field("", max_length=160)
    evidenceRange: dict[str, Any] = Field(default_factory=dict)
    title: str = Field("", max_length=240)
    summary: str = Field("", max_length=4000)
    actorAgentId: str = Field("", max_length=160)


class RefinementProposalCreatePayload(BaseModel):
    sourceArtifactIds: list[str] = Field(default_factory=list, max_length=80)
    proposedByAgentId: str = Field("", max_length=160)
    title: str = Field("", max_length=240)
    summary: str = Field("", max_length=4000)
    content: str = Field("", max_length=40000)
    tags: list[str] = Field(default_factory=list, max_length=40)


class IngestionPackageCreatePayload(BaseModel):
    sourceType: str = Field("", max_length=80)
    sourceRef: dict[str, Any] = Field(default_factory=dict)
    sourceCreatedAt: str = Field("", max_length=80)
    capturedBy: str = Field("", max_length=160)
    evidenceRange: dict[str, Any] = Field(default_factory=dict)
    sourceTitle: str = Field("", max_length=240)
    sourceSummary: str = Field("", max_length=4000)
    excerpt: str = Field("", max_length=12000)
    proposedByAgentId: str = Field("", max_length=160)
    proposalTitle: str = Field("", max_length=240)
    proposalSummary: str = Field("", max_length=4000)
    proposalContent: str = Field("", max_length=40000)
    tags: list[str] = Field(default_factory=list, max_length=40)


class RefinementProposalReviewPayload(BaseModel):
    status: str = Field("", max_length=32)
    reviewedByAgentId: str = Field("", max_length=160)
    resolutionNote: str = Field("", max_length=2000)


class KnowledgeItemRatingPayload(BaseModel):
    actorAgentId: str = Field("", max_length=160)
    importanceLevel: str = Field("", max_length=32)
    confidence: float | None = None
    stability: str = Field("", max_length=32)
    scope: str = Field("", max_length=32)
    reviewPriority: str = Field("", max_length=32)
    markingReason: str = Field("", max_length=2000)


class RatingSuggestionCreatePayload(BaseModel):
    suggestedByAgentId: str = Field("", max_length=160)
    targetType: str = Field("", max_length=40)
    knowledgeItemId: str = Field("", max_length=160)
    proposalId: str = Field("", max_length=160)
    importanceLevel: str = Field("", max_length=32)
    confidence: float | None = None
    stability: str = Field("", max_length=32)
    reviewPriority: str = Field("", max_length=32)
    markingReason: str = Field("", max_length=2000)


class RatingSuggestionReviewPayload(BaseModel):
    status: str = Field("", max_length=32)
    reviewedByAgentId: str = Field("", max_length=160)
    resolutionNote: str = Field("", max_length=2000)


class RatingSuggestionBulkReviewPayload(BaseModel):
    suggestionIds: list[str] = Field(default_factory=list, max_length=100)
    status: str = Field("", max_length=32)
    reviewedByAgentId: str = Field("", max_length=160)
    resolutionNote: str = Field("", max_length=2000)


@router.get("/knowledge/overview")
def knowledge_overview(agentId: str = "") -> dict:
    return list_knowledge_overview(agent_id=agentId)


@router.get("/knowledge/steward/overview")
def knowledge_steward_overview() -> dict:
    return get_knowledge_steward_overview()


@router.get("/knowledge/steward/recommendations")
def knowledge_steward_recommendations(agentId: str = "", limit: int = 12) -> dict:
    try:
        return list_knowledge_steward_recommendations(agent_id=agentId, limit=limit)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/search")
def knowledge_search(
    agentId: str = "",
    query: str = "",
    teamId: str = "",
    knowledgeBaseId: str = "",
    tags: list[str] = Query(default=[]),
    sourceType: str = "",
    importanceLevel: str = "",
    confidenceMin: float | None = None,
    stability: str = "",
    createdFrom: str = "",
    createdTo: str = "",
    limit: int = 25,
) -> dict:
    try:
        return search_knowledge_items(
            agent_id=agentId,
            query=query,
            team_id=teamId,
            knowledge_base_id=knowledgeBaseId,
            tags=tags,
            source_type=sourceType,
            importance_level=importanceLevel,
            confidence_min=confidenceMin,
            stability=stability,
            created_from=createdFrom,
            created_to=createdTo,
            limit=limit,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/permissions/audit")
def knowledge_permissions_audit(agentId: str = "") -> dict:
    return knowledge_permission_audit(agent_id=agentId)


@router.get("/knowledge/governance/tasks")
def knowledge_governance_tasks(agentId: str = "", status: str = "open") -> dict:
    try:
        return list_knowledge_governance_tasks(agent_id=agentId, status=status)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/ingestion-adapters")
def knowledge_ingestion_adapters() -> dict:
    return list_ingestion_adapters()


@router.get("/teams/{team_id}/knowledge-bases")
def team_knowledge_base_list(team_id: str, agentId: str = "") -> dict:
    try:
        return list_team_knowledge_bases(team_id, agent_id=agentId)
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/knowledge-bases", status_code=status.HTTP_201_CREATED)
def team_knowledge_base_create(team_id: str, payload: KnowledgeBaseCreatePayload) -> dict:
    try:
        return create_knowledge_base(
            team_id,
            name=payload.name,
            description=payload.description,
            actor_agent_id=payload.actorAgentId,
            acl=payload.acl,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/knowledge-bases/{knowledge_base_id}/source-artifacts", status_code=status.HTTP_201_CREATED)
def knowledge_source_artifact_create(knowledge_base_id: str, payload: SourceArtifactCreatePayload) -> dict:
    try:
        return create_source_artifact(
            knowledge_base_id,
            source_type=payload.sourceType,
            source_ref=payload.sourceRef,
            source_created_at=payload.sourceCreatedAt,
            captured_by=payload.capturedBy,
            source_hash=payload.sourceHash,
            evidence_range=payload.evidenceRange,
            title=payload.title,
            summary=payload.summary,
            actor_agent_id=payload.actorAgentId,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/knowledge-bases/{knowledge_base_id}/refinement-proposals", status_code=status.HTTP_201_CREATED)
def knowledge_refinement_proposal_create(knowledge_base_id: str, payload: RefinementProposalCreatePayload) -> dict:
    try:
        return create_refinement_proposal(
            knowledge_base_id,
            source_artifact_ids=payload.sourceArtifactIds,
            proposed_by_agent_id=payload.proposedByAgentId,
            title=payload.title,
            summary=payload.summary,
            content=payload.content,
            tags=payload.tags,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/knowledge-bases/{knowledge_base_id}/ingestion-packages", status_code=status.HTTP_201_CREATED)
def knowledge_ingestion_package_create(knowledge_base_id: str, payload: IngestionPackageCreatePayload) -> dict:
    try:
        return create_ingestion_package(
            knowledge_base_id,
            source_type=payload.sourceType,
            source_ref=payload.sourceRef,
            source_created_at=payload.sourceCreatedAt,
            captured_by=payload.capturedBy,
            evidence_range=payload.evidenceRange,
            source_title=payload.sourceTitle,
            source_summary=payload.sourceSummary,
            excerpt=payload.excerpt,
            proposed_by_agent_id=payload.proposedByAgentId,
            proposal_title=payload.proposalTitle,
            proposal_summary=payload.proposalSummary,
            proposal_content=payload.proposalContent,
            tags=payload.tags,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/knowledge-bases/{knowledge_base_id}/refinement-proposals/{proposal_id}/review")
def knowledge_refinement_proposal_review(
    knowledge_base_id: str,
    proposal_id: str,
    payload: RefinementProposalReviewPayload,
) -> dict:
    try:
        return review_refinement_proposal(
            knowledge_base_id,
            proposal_id,
            status=payload.status,
            reviewed_by_agent_id=payload.reviewedByAgentId,
            resolution_note=payload.resolutionNote,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge-bases/{knowledge_base_id}/items")
def knowledge_item_list(knowledge_base_id: str, agentId: str = "") -> dict:
    try:
        return list_knowledge_items(knowledge_base_id, agent_id=agentId)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge-bases/{knowledge_base_id}/trace/{target_id}")
def knowledge_trace(knowledge_base_id: str, target_id: str, agentId: str = "") -> dict:
    try:
        return get_knowledge_trace(knowledge_base_id, target_id, agent_id=agentId)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/knowledge-bases/{knowledge_base_id}/items/{knowledge_item_id}/rating")
def knowledge_item_rating_update(
    knowledge_base_id: str,
    knowledge_item_id: str,
    payload: KnowledgeItemRatingPayload,
) -> dict:
    try:
        return update_knowledge_item_rating(
            knowledge_base_id,
            knowledge_item_id,
            actor_agent_id=payload.actorAgentId,
            importance_level=payload.importanceLevel,
            confidence=payload.confidence,
            stability=payload.stability,
            scope=payload.scope,
            review_priority=payload.reviewPriority,
            marking_reason=payload.markingReason,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge-bases/{knowledge_base_id}/rating-suggestions")
def knowledge_rating_suggestion_list(knowledge_base_id: str, agentId: str = "", status: str = "") -> dict:
    try:
        return list_rating_suggestions(knowledge_base_id, agent_id=agentId, status=status)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/knowledge-bases/{knowledge_base_id}/rating-suggestions", status_code=status.HTTP_201_CREATED)
def knowledge_rating_suggestion_create(knowledge_base_id: str, payload: RatingSuggestionCreatePayload) -> dict:
    try:
        return create_rating_suggestion(
            knowledge_base_id,
            suggested_by_agent_id=payload.suggestedByAgentId,
            target_type=payload.targetType,
            knowledge_item_id=payload.knowledgeItemId,
            proposal_id=payload.proposalId,
            importance_level=payload.importanceLevel,
            confidence=payload.confidence,
            stability=payload.stability,
            review_priority=payload.reviewPriority,
            marking_reason=payload.markingReason,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/knowledge-bases/{knowledge_base_id}/rating-suggestions/{suggestion_id}/review")
def knowledge_rating_suggestion_review(
    knowledge_base_id: str,
    suggestion_id: str,
    payload: RatingSuggestionReviewPayload,
) -> dict:
    try:
        return review_rating_suggestion(
            knowledge_base_id,
            suggestion_id,
            status=payload.status,
            reviewed_by_agent_id=payload.reviewedByAgentId,
            resolution_note=payload.resolutionNote,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/knowledge-bases/{knowledge_base_id}/rating-suggestions/review-batch")
def knowledge_rating_suggestion_bulk_review(
    knowledge_base_id: str,
    payload: RatingSuggestionBulkReviewPayload,
) -> dict:
    try:
        return review_rating_suggestions_bulk(
            knowledge_base_id,
            suggestion_ids=payload.suggestionIds,
            status=payload.status,
            reviewed_by_agent_id=payload.reviewedByAgentId,
            resolution_note=payload.resolutionNote,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
