"""Web-facing ClaimEvidence service with no formal knowledge side effects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.research.evidence import ClaimEvidenceStore

from . import team_service


PROJECT_ROOT = team_service.PROJECT_ROOT


def register_claim_evidence(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team = team_service.get_team(team_id)
    evidence = _store().register(team_id, payload)
    return {
        "schemaVersion": 1,
        "team": _team_ref(team),
        "evidence": evidence,
        "boundaries": _boundaries(),
    }


def list_claim_evidence(team_id: str, *, candidate_id: str = "", claim_id: str = "") -> dict[str, Any]:
    team = team_service.get_team(team_id)
    evidence = _store().list(team_id, candidate_id=candidate_id, claim_id=claim_id)
    return {
        "schemaVersion": 1,
        "team": _team_ref(team),
        "evidence": evidence,
        "summary": {"count": len(evidence)},
        "boundaries": _boundaries(),
    }


def review_claim_evidence(team_id: str, claim_evidence_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team = team_service.get_team(team_id)
    evidence = _store().review(
        team_id,
        claim_evidence_id,
        decision=str(payload.get("decision") or ""),
        reviewed_by=str(payload.get("reviewedBy") or ""),
        note=str(payload.get("note") or ""),
    )
    return {
        "schemaVersion": 1,
        "team": _team_ref(team),
        "evidence": evidence,
        "boundaries": _boundaries(),
    }


def claim_evidence_coverage(team_id: str, *, candidate_id: str = "") -> dict[str, Any]:
    team_service.get_team(team_id)
    return {**_store().coverage(team_id, candidate_id=candidate_id), "boundaries": _boundaries()}


def project_legacy_evidence(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team = team_service.get_team(team_id)
    evidence = _store().project_legacy(
        team_id,
        candidate_id=str(payload.get("candidateId") or ""),
        legacy_entries=list(payload.get("legacyEntries") or []),
    )
    return {
        "schemaVersion": 1,
        "team": _team_ref(team),
        "evidence": evidence,
        "summary": {"count": len(evidence)},
        "boundaries": {**_boundaries(), "persistsCanonicalEvidence": False},
    }


def reconcile_claim_evidence_source(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    team = team_service.get_team(team_id)
    result = _store().reconcile_source_revision(
        team_id,
        source_id=str(payload.get("sourceId") or ""),
        current_revision=str(payload.get("currentSourceRevision") or ""),
    )
    return {
        "schemaVersion": 1,
        "team": _team_ref(team),
        "result": result,
        "boundaries": _boundaries(),
    }


def _store() -> ClaimEvidenceStore:
    return ClaimEvidenceStore(Path(PROJECT_ROOT))


def _team_ref(team: dict[str, Any]) -> dict[str, str]:
    return {"teamId": str(team.get("teamId") or ""), "name": str(team.get("name") or "")}


def _boundaries() -> dict[str, bool]:
    return {
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "persistsCanonicalEvidence": True,
        "requiresHumanReview": True,
    }
