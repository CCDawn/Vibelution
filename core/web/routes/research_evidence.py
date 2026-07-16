"""Claim-level research evidence routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.research.evidence import ClaimEvidenceError
from core.research.question_tree import ResearchQuestionTreeError
from core.web.services import research_evidence_service
from core.web.services.team_service import TeamNotFoundError


router = APIRouter(tags=["research-evidence"])


class ClaimEvidencePayload(BaseModel):
    claimId: str
    candidateId: str
    sourceId: str
    sourceRevision: str
    locator: dict[str, Any]
    quote: str
    evidenceKind: Literal["primary_result", "review_summary", "metadata", "counter_evidence"]
    reasoningRole: Literal["fact", "inference", "analogy", "hypothesis"]
    supportLevel: Literal["supports", "contradicts", "insufficient", "unverified"]
    extractionMethod: Literal["paperqa2", "manual", "model"]
    extractorAgentId: str
    modelRef: str = ""


class ClaimEvidenceReviewPayload(BaseModel):
    decision: Literal["accepted", "rejected"]
    reviewedBy: str
    note: str = ""


class LegacyEvidenceProjectionPayload(BaseModel):
    candidateId: str
    legacyEntries: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class SourceRevisionPayload(BaseModel):
    sourceId: str
    currentSourceRevision: str


class ResearchQuestionTreePayload(BaseModel):
    researchQuestion: str
    createdByAgent: str
    customPerspectives: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


@router.post("/teams/{team_id}/research-evidence/claims", status_code=status.HTTP_201_CREATED)
def create_claim_evidence(team_id: str, payload: ClaimEvidencePayload) -> dict:
    return _route_call(research_evidence_service.register_claim_evidence, team_id, payload.model_dump())


@router.get("/teams/{team_id}/research-evidence/claims")
def get_claim_evidence(
    team_id: str,
    candidate_id: str = Query(default="", alias="candidateId"),
    claim_id: str = Query(default="", alias="claimId"),
) -> dict:
    return _route_call(
        research_evidence_service.list_claim_evidence,
        team_id,
        candidate_id=candidate_id,
        claim_id=claim_id,
    )


@router.post("/teams/{team_id}/research-evidence/claims/{claim_evidence_id}/review")
def review_claim_evidence(team_id: str, claim_evidence_id: str, payload: ClaimEvidenceReviewPayload) -> dict:
    return _route_call(
        research_evidence_service.review_claim_evidence,
        team_id,
        claim_evidence_id,
        payload.model_dump(),
    )


@router.get("/teams/{team_id}/research-evidence/coverage")
def get_claim_evidence_coverage(
    team_id: str,
    candidate_id: str = Query(default="", alias="candidateId"),
) -> dict:
    return _route_call(research_evidence_service.claim_evidence_coverage, team_id, candidate_id=candidate_id)


@router.post("/teams/{team_id}/research-evidence/legacy-projection")
def legacy_evidence_projection(team_id: str, payload: LegacyEvidenceProjectionPayload) -> dict:
    return _route_call(research_evidence_service.project_legacy_evidence, team_id, payload.model_dump())


@router.post("/teams/{team_id}/research-evidence/sources/reconcile")
def reconcile_source_revision(team_id: str, payload: SourceRevisionPayload) -> dict:
    return _route_call(research_evidence_service.reconcile_claim_evidence_source, team_id, payload.model_dump())


@router.post("/teams/{team_id}/research-question-trees", status_code=status.HTTP_201_CREATED)
def create_research_question_tree(team_id: str, payload: ResearchQuestionTreePayload) -> dict:
    return _route_call(research_evidence_service.create_research_question_tree, team_id, payload.model_dump())


@router.get("/teams/{team_id}/research-question-trees")
def list_research_question_trees(team_id: str) -> dict:
    return _route_call(research_evidence_service.list_research_question_trees, team_id)


def _route_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ClaimEvidenceError, ResearchQuestionTreeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
