"""Append-only claim ledger contract with accepted-evidence support gating.

A ``ClaimLedgerEntry`` can only become ``supported`` when every referenced
piece of evidence has been accepted (``reviewStatus == "accepted"``) and is
scope-consistent with the claim.  Meeting text can never directly promote a
claim: meeting-sourced claims start as ``proposed`` with no evidence refs.
Supersede and retract are append-only operations that always preserve
counter-evidence on the affected records.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import (
    ContractValidationError,
    require_list,
    require_sha256,
    require_text,
)
from .research_scope import REQUIRED_SCOPE_FIELDS, scope_hash_for

CLAIM_STATUSES = {"proposed", "supported", "superseded", "retracted"}
CLAIM_SOURCES = {"agent", "meeting", "evidence"}
ACCEPTED_REVIEW_STATUS = "accepted"
SUPPORT_LEVELS = {"supports", "contradicts", "insufficient", "unverified"}


def _scope_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    identity = {field: require_text(payload, field) for field in REQUIRED_SCOPE_FIELDS}
    identity["agentId"] = require_text(payload, "agentId")
    identity["mode"] = require_text(payload, "mode").lower()
    return identity


def _validated_scope_hash(payload: Mapping[str, Any], identity: Mapping[str, str]) -> str:
    supplied = require_sha256(payload, "scopeHash")
    expected = scope_hash_for(
        **{field: identity[field] for field in REQUIRED_SCOPE_FIELDS},
        agent_id=identity["agentId"],
        mode=identity["mode"],
    )
    if supplied != expected:
        raise ContractValidationError("scopeHash does not match the claim scope identity")
    return supplied


@dataclass(frozen=True, slots=True)
class ClaimEvidenceRef:
    """A scope-carrying pointer to one claim-evidence record."""

    claimEvidenceId: str
    scopeHash: str
    reviewStatus: str
    supportLevel: str
    sourceId: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClaimEvidenceRef:
        review_status = require_text(payload, "reviewStatus").lower()
        support_level = require_text(payload, "supportLevel").lower()
        if support_level not in SUPPORT_LEVELS:
            raise ContractValidationError(
                "supportLevel must be one of: " + ", ".join(sorted(SUPPORT_LEVELS))
            )
        return cls(
            claimEvidenceId=require_text(payload, "claimEvidenceId"),
            scopeHash=require_sha256(payload, "scopeHash"),
            reviewStatus=review_status,
            supportLevel=support_level,
            sourceId=require_text(payload, "sourceId"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claimEvidenceId": self.claimEvidenceId,
            "scopeHash": self.scopeHash,
            "reviewStatus": self.reviewStatus,
            "supportLevel": self.supportLevel,
            "sourceId": self.sourceId,
        }

    def is_accepted(self) -> bool:
        return self.reviewStatus == ACCEPTED_REVIEW_STATUS

    def supports_claim(self) -> bool:
        return self.is_accepted() and self.supportLevel == "supports"

    def contradicts_claim(self) -> bool:
        return self.is_accepted() and self.supportLevel == "contradicts"


@dataclass(frozen=True, slots=True)
class ClaimLedgerEntry:
    """One append-only claim ledger entry with full provenance gating."""

    claimId: str
    claim: str
    program: str
    theme: str
    campaign: str
    question: str
    branch: str
    workflow: str
    agentId: str
    mode: str
    scopeHash: str
    status: str
    source: str
    evidenceRefs: tuple[ClaimEvidenceRef, ...]
    counterEvidenceRefs: tuple[str, ...]
    supersedesClaimId: str
    retractsClaimId: str
    meetingPromotionAllowed: bool
    createdBy: str
    createdAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClaimLedgerEntry:
        status = require_text(payload, "status").lower()
        if status not in CLAIM_STATUSES:
            raise ContractValidationError(
                "claim status must be one of: " + ", ".join(sorted(CLAIM_STATUSES))
            )
        source = require_text(payload, "source").lower()
        if source not in CLAIM_SOURCES:
            raise ContractValidationError(
                "claim source must be one of: " + ", ".join(sorted(CLAIM_SOURCES))
            )
        identity = _scope_identity(payload)
        scope_hash = _validated_scope_hash(payload, identity)
        evidence_refs = tuple(
            ClaimEvidenceRef.from_dict(item)
            for item in require_list(payload, "evidenceRefs")
        )
        meeting_promotion_allowed = bool(payload.get("meetingPromotionAllowed"))
        if source == "meeting":
            if meeting_promotion_allowed:
                raise ContractValidationError(
                    "meeting text can never promote a claim directly"
                )
            if evidence_refs:
                raise ContractValidationError(
                    "a meeting-sourced claim cannot carry evidence refs"
                )
            if status != "proposed":
                raise ContractValidationError(
                    "a meeting-sourced claim must start as proposed"
                )
        if status == "supported":
            if not evidence_refs:
                raise ContractValidationError(
                    "a supported claim requires accepted, scope-consistent evidence"
                )
            for ref in evidence_refs:
                if not ref.is_accepted():
                    raise ContractValidationError(
                        "a supported claim may only reference accepted evidence"
                    )
                if ref.scopeHash != scope_hash:
                    raise ContractValidationError(
                        "a supported claim may only reference scope-consistent evidence"
                    )
            if not any(ref.supports_claim() for ref in evidence_refs):
                raise ContractValidationError(
                    "a supported claim requires at least one accepted supporting evidence ref"
                )
        counter_evidence_refs = tuple(
            str(item) for item in require_list(payload, "counterEvidenceRefs")
        )
        return cls(
            claimId=require_text(payload, "claimId"),
            claim=require_text(payload, "claim"),
            **identity,
            scopeHash=scope_hash,
            status=status,
            source=source,
            evidenceRefs=evidence_refs,
            counterEvidenceRefs=counter_evidence_refs,
            supersedesClaimId=str(payload.get("supersedesClaimId") or "").strip(),
            retractsClaimId=str(payload.get("retractsClaimId") or "").strip(),
            meetingPromotionAllowed=meeting_promotion_allowed,
            createdBy=require_text(payload, "createdBy"),
            createdAt=require_text(payload, "createdAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claimId": self.claimId,
            "claim": self.claim,
            "program": self.program,
            "theme": self.theme,
            "campaign": self.campaign,
            "question": self.question,
            "branch": self.branch,
            "workflow": self.workflow,
            "agentId": self.agentId,
            "mode": self.mode,
            "scopeHash": self.scopeHash,
            "status": self.status,
            "source": self.source,
            "evidenceRefs": [item.to_dict() for item in self.evidenceRefs],
            "counterEvidenceRefs": list(self.counterEvidenceRefs),
            "supersedesClaimId": self.supersedesClaimId,
            "retractsClaimId": self.retractsClaimId,
            "meetingPromotionAllowed": self.meetingPromotionAllowed,
            "createdBy": self.createdBy,
            "createdAt": self.createdAt,
        }
