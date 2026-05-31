"""Team knowledge platform API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.team_knowledge_service import (
    TeamKnowledgeError,
    TeamKnowledgeNotFoundError,
    TeamKnowledgePermissionError,
    create_knowledge_base,
    create_refinement_proposal,
    create_source_artifact,
    list_knowledge_items,
    list_knowledge_overview,
    list_team_knowledge_bases,
    review_refinement_proposal,
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


@router.get("/knowledge/overview")
def knowledge_overview(agentId: str = "") -> dict:
    return list_knowledge_overview(agent_id=agentId)


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
