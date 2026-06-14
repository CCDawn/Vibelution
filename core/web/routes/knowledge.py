"""Team knowledge platform API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.web.services.rag_retrieval_service import RagRetrievalError, get_rag_retrieval_health, retrieve_rag_contexts
from core.web.services.runtime_scene_service import record_runtime_scene_event
from core.web.services.team_knowledge_service import (
    TeamKnowledgeError,
    TeamKnowledgeNotFoundError,
    TeamKnowledgePermissionError,
    create_knowledge_base,
    create_agent_knowledge_base,
    create_ingestion_package,
    create_rating_suggestion,
    create_refinement_proposal,
    collect_source_to_inbox,
    create_source_artifact_from_central_source,
    get_knowledge_dashboard_snapshot,
    get_knowledge_governance_plan,
    get_knowledge_operations_health,
    get_knowledge_trace,
    get_knowledge_steward_overview,
    get_knowledge_steward_workbench,
    knowledge_permission_audit,
    list_central_sources,
    list_ingestion_adapters,
    list_knowledge_governance_tasks,
    list_knowledge_steward_recommendations,
    list_knowledge_items,
    list_knowledge_overview,
    list_rating_suggestions,
    list_owner_source_inbox,
    list_team_knowledge_bases,
    list_agent_knowledge_bases,
    review_owner_inbox_source,
    review_rating_suggestions_bulk,
    review_rating_suggestion,
    review_refinement_proposal,
    search_knowledge_items,
    update_owner_source_governance,
    update_knowledge_item_rating,
)


router = APIRouter(tags=["knowledge"])


def _require_agent_id(agent_id: str, *, purpose: str = "governed Team Knowledge access") -> str:
    normalized = str(agent_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"agentId is required for {purpose}.")
    return normalized


class KnowledgeBaseCreatePayload(BaseModel):
    name: str = Field("", max_length=160)
    description: str = Field("", max_length=1200)
    actorAgentId: str = Field("", max_length=160)
    acl: dict[str, Any] = Field(default_factory=dict)


class SourceInboxCollectPayload(BaseModel):
    ownerType: str = Field("", max_length=32)
    ownerId: str = Field("", max_length=160)
    sourceType: str = Field("", max_length=80)
    sourceRef: dict[str, Any] = Field(default_factory=dict)
    originalContent: str = Field("", max_length=200000)
    originalFilename: str = Field("", max_length=240)
    sourceCreatedAt: str = Field("", max_length=80)
    capturedBy: str = Field("", max_length=160)
    sourceHash: str = Field("", max_length=160)
    evidenceRange: dict[str, Any] = Field(default_factory=dict)
    title: str = Field("", max_length=240)
    summary: str = Field("", max_length=4000)
    actorAgentId: str = Field("", max_length=160)


class SourceInboxReviewPayload(BaseModel):
    decision: str = Field("", max_length=40)
    reviewedByAgentId: str = Field("", max_length=160)
    resolutionNote: str = Field("", max_length=2000)
    duplicateOf: str = Field("", max_length=160)


class SourceGovernanceUpdatePayload(BaseModel):
    localStewardAgentIds: list[str] = Field(default_factory=list, max_length=80)
    actorAgentId: str = Field("", max_length=160)


class CentralSourceArtifactCreatePayload(BaseModel):
    centralSourceId: str = Field("", max_length=160)
    actorAgentId: str = Field("", max_length=160)
    evidenceRange: dict[str, Any] = Field(default_factory=dict)
    title: str = Field("", max_length=240)
    summary: str = Field("", max_length=4000)


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
    centralSourceId: str = Field("", max_length=160)
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


@router.get("/knowledge/dashboard-snapshot")
def knowledge_dashboard_snapshot(agentId: str = "", recommendationLimit: int = 6, workbenchLimit: int = 8, planLimit: int = 8) -> dict:
    normalized_agent_id = _require_agent_id(agentId, purpose="knowledge dashboard snapshot")
    try:
        return get_knowledge_dashboard_snapshot(
            agent_id=normalized_agent_id,
            recommendation_limit=recommendationLimit,
            workbench_limit=workbenchLimit,
            plan_limit=planLimit,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/steward/overview")
def knowledge_steward_overview(agentId: str = "") -> dict:
    return get_knowledge_steward_overview(agent_id=_require_agent_id(agentId, purpose="knowledge steward overview"))


@router.get("/knowledge/steward/recommendations")
def knowledge_steward_recommendations(agentId: str = "", limit: int = 12) -> dict:
    normalized_agent_id = _require_agent_id(agentId, purpose="knowledge steward recommendations")
    try:
        return list_knowledge_steward_recommendations(agent_id=normalized_agent_id, limit=limit)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/steward/workbench")
def knowledge_steward_workbench(agentId: str = "", limit: int = 12) -> dict:
    normalized_agent_id = _require_agent_id(agentId, purpose="knowledge steward workbench")
    try:
        return get_knowledge_steward_workbench(agent_id=normalized_agent_id, limit=limit)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/operations/health")
def knowledge_operations_health(agentId: str = "") -> dict:
    normalized_agent_id = _require_agent_id(agentId, purpose="knowledge operations health")
    try:
        return get_knowledge_operations_health(agent_id=normalized_agent_id)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/governance/plan")
def knowledge_governance_plan(agentId: str = "", limit: int = 12) -> dict:
    normalized_agent_id = _require_agent_id(agentId, purpose="knowledge governance plan")
    try:
        return get_knowledge_governance_plan(agent_id=normalized_agent_id, limit=limit)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/search")
def knowledge_search(
    agentId: str = "",
    query: str = "",
    teamId: str = "",
    ownerType: str = "",
    ownerId: str = "",
    knowledgeBaseId: str = "",
    tags: list[str] = Query(default=[]),
    sourceType: str = "",
    importanceLevel: str = "",
    confidenceMin: float | None = None,
    stability: str = "",
    createdFrom: str = "",
    createdTo: str = "",
    searchMode: str = "exact",
    limit: int = 25,
) -> dict:
    normalized_agent_id = _require_agent_id(agentId, purpose="governed knowledge search")
    try:
        return search_knowledge_items(
            agent_id=normalized_agent_id,
            query=query,
            team_id=teamId,
            owner_type=ownerType,
            owner_id=ownerId,
            knowledge_base_id=knowledgeBaseId,
            tags=tags,
            source_type=sourceType,
            importance_level=importanceLevel,
            confidence_min=confidenceMin,
            stability=stability,
            created_from=createdFrom,
            created_to=createdTo,
            search_mode=searchMode,
            limit=limit,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/rag/retrieve")
def knowledge_rag_retrieve(
    agentId: str = "",
    query: str = "",
    teamId: str = "",
    ownerType: str = "",
    ownerId: str = "",
    knowledgeBaseId: str = "",
    tags: list[str] = Query(default=[]),
    retrievalMode: str = "hybrid",
    provider: str = "local",
    topK: int = 5,
    maxContextChars: int = 1200,
) -> dict:
    normalized_agent_id = str(agentId or "").strip()
    if not normalized_agent_id:
        _record_rag_retrieve_event(
            "knowledge.rag.retrieve.blocked",
            agent_id="",
            knowledge_base_id=knowledgeBaseId,
            retrieval_mode=retrievalMode,
            provider=provider,
            query_length=len(str(query or "").strip()),
            outcome="blocked",
            fields={"reason": "agent_id_required"},
        )
        raise HTTPException(status_code=422, detail="agentId is required for governed RAG retrieval.")
    try:
        payload = retrieve_rag_contexts(
            agent_id=normalized_agent_id,
            query=query,
            team_id=teamId,
            owner_type=ownerType,
            owner_id=ownerId,
            knowledge_base_id=knowledgeBaseId,
            tags=tags,
            retrieval_mode=retrievalMode,
            provider=provider,
            top_k=topK,
            max_context_chars=maxContextChars,
        )
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        _record_rag_retrieve_event(
            "knowledge.rag.retrieve.succeeded",
            agent_id=normalized_agent_id,
            knowledge_base_id=knowledgeBaseId,
            retrieval_mode=str(request.get("retrievalMode") or retrievalMode),
            provider=str(request.get("provider") or provider),
            query_length=int(request.get("queryLength") or len(str(query or "").strip())),
            outcome="succeeded",
            fields={
                "contextCount": int(summary.get("contextCount") or 0),
                "citationCount": int(summary.get("citationCount") or 0),
                "candidateCount": int(summary.get("candidateCount") or 0),
                "scannedKnowledgeBaseCount": int(summary.get("scannedKnowledgeBaseCount") or 0),
            },
        )
        return payload
    except TeamKnowledgePermissionError as exc:
        _record_rag_retrieve_event(
            "knowledge.rag.retrieve.blocked",
            agent_id=normalized_agent_id,
            knowledge_base_id=knowledgeBaseId,
            retrieval_mode=retrievalMode,
            provider=provider,
            query_length=len(str(query or "").strip()),
            outcome="blocked",
            fields={"errorType": type(exc).__name__},
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        _record_rag_retrieve_event(
            "knowledge.rag.retrieve.failed",
            agent_id=normalized_agent_id,
            knowledge_base_id=knowledgeBaseId,
            retrieval_mode=retrievalMode,
            provider=provider,
            query_length=len(str(query or "").strip()),
            outcome="failed",
            fields={"errorType": type(exc).__name__},
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RagRetrievalError, TeamKnowledgeError) as exc:
        _record_rag_retrieve_event(
            "knowledge.rag.retrieve.failed",
            agent_id=normalized_agent_id,
            knowledge_base_id=knowledgeBaseId,
            retrieval_mode=retrievalMode,
            provider=provider,
            query_length=len(str(query or "").strip()),
            outcome="failed",
            fields={"errorType": type(exc).__name__},
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/rag/health")
def knowledge_rag_health(agentId: str = "") -> dict:
    normalized_agent_id = str(agentId or "").strip()
    if not normalized_agent_id:
        _record_rag_health_event(
            "knowledge.rag.health.blocked",
            agent_id="",
            outcome="blocked",
            fields={"reason": "agent_id_required"},
        )
        raise HTTPException(status_code=422, detail="agentId is required for governed RAG health.")
    return get_rag_retrieval_health(agent_id=normalized_agent_id)


def _record_rag_health_event(
    event_code: str,
    *,
    agent_id: str,
    outcome: str,
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "knowledge_routes",
            "rag",
            event_code,
            message=event_code,
            outcome=outcome,
            fields={
                "agentId": str(agent_id or "").strip(),
                **dict(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        pass


@router.post("/knowledge/sources/inbox", status_code=status.HTTP_201_CREATED)
def knowledge_source_inbox_collect(payload: SourceInboxCollectPayload) -> dict:
    try:
        return collect_source_to_inbox(
            payload.ownerType,
            payload.ownerId,
            source_type=payload.sourceType,
            source_ref=payload.sourceRef,
            original_content=payload.originalContent,
            original_filename=payload.originalFilename,
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


@router.get("/knowledge/sources/inbox")
def knowledge_source_inbox_list(ownerType: str = "", ownerId: str = "", agentId: str = "", status: str = "") -> dict:
    try:
        return list_owner_source_inbox(ownerType, ownerId, agent_id=agentId, status=status)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/knowledge/sources/inbox/{owner_type}/{owner_id}/{inbox_source_id}/review")
def knowledge_source_inbox_review(owner_type: str, owner_id: str, inbox_source_id: str, payload: SourceInboxReviewPayload) -> dict:
    try:
        return review_owner_inbox_source(
            owner_type,
            owner_id,
            inbox_source_id,
            decision=payload.decision,
            reviewed_by_agent_id=payload.reviewedByAgentId,
            resolution_note=payload.resolutionNote,
            duplicate_of=payload.duplicateOf,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/knowledge/sources/governance/{owner_type}/{owner_id}")
def knowledge_source_governance_update(owner_type: str, owner_id: str, payload: SourceGovernanceUpdatePayload) -> dict:
    try:
        return update_owner_source_governance(
            owner_type,
            owner_id,
            local_steward_agent_ids=payload.localStewardAgentIds,
            actor_agent_id=payload.actorAgentId,
        )
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/sources/registry")
def knowledge_central_source_registry(agentId: str = "", ownerType: str = "", ownerId: str = "") -> dict:
    try:
        return list_central_sources(agent_id=agentId, owner_type=ownerType, owner_id=ownerId)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _record_rag_retrieve_event(
    event_code: str,
    *,
    agent_id: str,
    knowledge_base_id: str,
    retrieval_mode: str,
    provider: str,
    query_length: int,
    outcome: str,
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "knowledge_routes",
            "rag",
            event_code,
            message=event_code,
            outcome=outcome,
            fields={
                "agentId": str(agent_id or "").strip(),
                "knowledgeBaseId": str(knowledge_base_id or "").strip(),
                "retrievalMode": str(retrieval_mode or "").strip(),
                "provider": str(provider or "").strip(),
                "queryLength": max(0, int(query_length or 0)),
                **dict(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        pass


@router.get("/knowledge/permissions/audit")
def knowledge_permissions_audit(agentId: str = "") -> dict:
    return knowledge_permission_audit(agent_id=_require_agent_id(agentId, purpose="knowledge permission audit"))


@router.get("/knowledge/governance/tasks")
def knowledge_governance_tasks(agentId: str = "", status: str = "open") -> dict:
    normalized_agent_id = _require_agent_id(agentId, purpose="knowledge governance tasks")
    try:
        return list_knowledge_governance_tasks(agent_id=normalized_agent_id, status=status)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/ingestion-adapters")
def knowledge_ingestion_adapters() -> dict:
    return list_ingestion_adapters()


@router.get("/teams/{team_id}/knowledge-bases")
def team_knowledge_base_list(team_id: str, agentId: str = "") -> dict:
    normalized_agent_id = _require_agent_id(agentId, purpose="team knowledge base listing")
    try:
        return list_team_knowledge_bases(team_id, agent_id=normalized_agent_id)
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


@router.get("/agents/{agent_id}/knowledge-bases")
def agent_knowledge_base_list(agent_id: str, actorAgentId: str = "") -> dict:
    normalized_actor_agent_id = _require_agent_id(actorAgentId, purpose="agent knowledge base listing")
    try:
        return list_agent_knowledge_bases(agent_id, actor_agent_id=normalized_actor_agent_id)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/knowledge-bases", status_code=status.HTTP_201_CREATED)
def agent_knowledge_base_create(agent_id: str, payload: KnowledgeBaseCreatePayload) -> dict:
    try:
        return create_agent_knowledge_base(
            agent_id,
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


@router.post("/knowledge-bases/{knowledge_base_id}/central-source-artifacts", status_code=status.HTTP_201_CREATED)
def knowledge_central_source_artifact_create(knowledge_base_id: str, payload: CentralSourceArtifactCreatePayload) -> dict:
    try:
        return create_source_artifact_from_central_source(
            knowledge_base_id,
            payload.centralSourceId,
            actor_agent_id=payload.actorAgentId,
            evidence_range=payload.evidenceRange,
            title=payload.title,
            summary=payload.summary,
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
            central_source_id=payload.centralSourceId,
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
    normalized_agent_id = _require_agent_id(agentId, purpose="knowledge item listing")
    try:
        return list_knowledge_items(knowledge_base_id, agent_id=normalized_agent_id)
    except TeamKnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TeamKnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamKnowledgeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge-bases/{knowledge_base_id}/trace/{target_id}")
def knowledge_trace(knowledge_base_id: str, target_id: str, agentId: str = "") -> dict:
    normalized_agent_id = _require_agent_id(agentId, purpose="knowledge trace")
    try:
        return get_knowledge_trace(knowledge_base_id, target_id, agent_id=normalized_agent_id)
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
    normalized_agent_id = _require_agent_id(agentId, purpose="rating suggestion listing")
    try:
        return list_rating_suggestions(knowledge_base_id, agent_id=normalized_agent_id, status=status)
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
