"""Claim-level research evidence routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from core.research.evidence import ClaimEvidenceError
from core.research.question_tree import ResearchQuestionTreeError
from core.web.routes.research_evidence_models import (
    ClaimEvidenceCoverageResponse,
    ClaimEvidenceItemResponse,
    ClaimEvidenceListResponse,
    ClaimEvidencePayload,
    ClaimEvidenceReconcileResponse,
    ClaimEvidenceReviewPayload,
    LegacyEvidenceProjectionPayload,
    ResearchQuestionTreeListResponse,
    ResearchQuestionTreePayload,
    ResearchQuestionTreeResponse,
    SourceRevisionPayload,
)
from core.web.services import research_evidence_service
from core.web.services.team_service import TeamNotFoundError


router = APIRouter(tags=["research-evidence"])


@router.post(
    "/teams/{team_id}/research-evidence/claims",
    status_code=status.HTTP_201_CREATED,
    response_model=ClaimEvidenceItemResponse,
    response_model_exclude_unset=True,
)
def create_claim_evidence(team_id: str, payload: ClaimEvidencePayload) -> dict:
    return _route_call(research_evidence_service.register_claim_evidence, team_id, payload.model_dump())


@router.get(
    "/teams/{team_id}/research-evidence/claims",
    response_model=ClaimEvidenceListResponse,
    response_model_exclude_unset=True,
)
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


@router.post(
    "/teams/{team_id}/research-evidence/claims/{claim_evidence_id}/review",
    response_model=ClaimEvidenceItemResponse,
    response_model_exclude_unset=True,
)
def review_claim_evidence(team_id: str, claim_evidence_id: str, payload: ClaimEvidenceReviewPayload) -> dict:
    return _route_call(
        research_evidence_service.review_claim_evidence,
        team_id,
        claim_evidence_id,
        payload.model_dump(),
    )


@router.get(
    "/teams/{team_id}/research-evidence/coverage",
    response_model=ClaimEvidenceCoverageResponse,
    response_model_exclude_unset=True,
)
def get_claim_evidence_coverage(
    team_id: str,
    candidate_id: str = Query(default="", alias="candidateId"),
) -> dict:
    return _route_call(research_evidence_service.claim_evidence_coverage, team_id, candidate_id=candidate_id)


@router.post(
    "/teams/{team_id}/research-evidence/legacy-projection",
    response_model=ClaimEvidenceListResponse,
    response_model_exclude_unset=True,
)
def legacy_evidence_projection(team_id: str, payload: LegacyEvidenceProjectionPayload) -> dict:
    return _route_call(research_evidence_service.project_legacy_evidence, team_id, payload.model_dump())


@router.post(
    "/teams/{team_id}/research-evidence/sources/reconcile",
    response_model=ClaimEvidenceReconcileResponse,
    response_model_exclude_unset=True,
)
def reconcile_source_revision(team_id: str, payload: SourceRevisionPayload) -> dict:
    return _route_call(research_evidence_service.reconcile_claim_evidence_source, team_id, payload.model_dump())


@router.post(
    "/teams/{team_id}/research-question-trees",
    status_code=status.HTTP_201_CREATED,
    response_model=ResearchQuestionTreeResponse,
    response_model_exclude_unset=True,
)
def create_research_question_tree(team_id: str, payload: ResearchQuestionTreePayload) -> dict:
    return _route_call(research_evidence_service.create_research_question_tree, team_id, payload.model_dump())


@router.get(
    "/teams/{team_id}/research-question-trees",
    response_model=ResearchQuestionTreeListResponse,
    response_model_exclude_unset=True,
)
def list_research_question_trees(team_id: str) -> dict:
    return _route_call(research_evidence_service.list_research_question_trees, team_id)


def _route_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ClaimEvidenceError, ResearchQuestionTreeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
