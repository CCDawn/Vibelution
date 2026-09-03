"""Public contracts for the G12 calibration judgement-record routes.

The service (``g12_calibration_store``) owns behavior, fail-closed binding
and storage; these models only declare the typed wire contract. Public JSON
stays camelCase and never inlines review evidence content.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class G12ManifestRecordRequest(BaseModel):
    """One full ``AuditSampleManifest`` document (gate must be G12)."""

    model_config = {"extra": "allow"}

    manifestId: str = ""
    manifestHash: str = ""


class G12ManifestRecordResponse(BaseModel):
    status: str = ""
    manifestId: str = ""
    manifestHash: str = ""
    totalRequired: int = 0


class G12JudgementPayload(BaseModel):
    """One judgement record; the store validates the frozen record shape."""

    model_config = {"extra": "allow"}

    questionId: str = ""
    sampleKind: str = ""
    autoDecision: str = ""
    humanDecision: str = ""
    riskClass: str = ""
    domain: str = ""
    evidenceRef: str = ""
    recordedAt: str = ""


class G12JudgementsRecordRequest(BaseModel):
    manifestId: str = ""
    judgements: list[G12JudgementPayload] = Field(default_factory=list)


class G12JudgementsRecordResponse(BaseModel):
    status: str = ""
    manifestId: str = ""
    manifestHash: str = ""
    recordedCount: int = 0
    skippedDuplicateCount: int = 0
    totalRecorded: int = 0
    totalRequired: int = 0
    bundleStatus: str = ""
    pending: list[dict[str, Any]] = Field(default_factory=list)


class G12GateStatusResponse(BaseModel):
    schemaVersion: str = ""
    teamId: str = ""
    bundle: dict[str, Any] | None = None
    verdict: dict[str, Any] = Field(default_factory=dict)
    evidenceStatus: str = ""
    gatePassed: bool = False
    recordedBy: str = ""


__all__ = [
    "G12GateStatusResponse",
    "G12JudgementPayload",
    "G12JudgementsRecordRequest",
    "G12JudgementsRecordResponse",
    "G12ManifestRecordRequest",
    "G12ManifestRecordResponse",
]
