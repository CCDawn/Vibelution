"""Personal memory candidate contract with cross-theme advisory gating.

A ``PersonalMemoryCandidate`` records one agent's working memory from a closed
round.  It is classified by theme, campaign, memory class, reuse policy, and
evidence status.  Cross-theme candidates are only ever advisory and always
require revalidation; a candidate that has not been accepted is never injected.
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

MEMORY_CLASSES = {
    "personal_reflection",
    "lesson",
    "preference",
    "observation",
    "working_note",
}
REUSE_POLICIES = {"advisory_only", "reusable_same_scope", "blocked"}
EVIDENCE_STATUSES = {"unverified", "reported", "corroborated", "refuted"}


@dataclass(frozen=True, slots=True)
class PersonalMemoryCandidate:
    """One agent's classified memory candidate with injection gating."""

    memoryCandidateId: str
    agentId: str
    theme: str
    campaign: str
    scopeHash: str
    targetTheme: str
    targetCampaign: str
    targetScopeHash: str
    sourceRefs: tuple[str, ...]
    memoryClass: str
    reusePolicy: str
    evidenceStatus: str
    summary: str
    needsRevalidation: bool
    advisoryOnly: bool
    accepted: bool
    injected: bool
    createdAt: str
    acceptedAt: str
    injectedAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PersonalMemoryCandidate:
        memory_class = require_text(payload, "memoryClass").lower()
        if memory_class not in MEMORY_CLASSES:
            raise ContractValidationError(
                "memoryClass must be one of: " + ", ".join(sorted(MEMORY_CLASSES))
            )
        reuse_policy = require_text(payload, "reusePolicy").lower()
        if reuse_policy not in REUSE_POLICIES:
            raise ContractValidationError(
                "reusePolicy must be one of: " + ", ".join(sorted(REUSE_POLICIES))
            )
        evidence_status = require_text(payload, "evidenceStatus").lower()
        if evidence_status not in EVIDENCE_STATUSES:
            raise ContractValidationError(
                "evidenceStatus must be one of: " + ", ".join(sorted(EVIDENCE_STATUSES))
            )
        theme = require_text(payload, "theme")
        campaign = require_text(payload, "campaign")
        target_theme = require_text(payload, "targetTheme")
        target_campaign = require_text(payload, "targetCampaign")
        scope_hash = require_sha256(payload, "scopeHash")
        target_scope_hash = require_sha256(payload, "targetScopeHash")
        cross_theme = (
            theme != target_theme
            or campaign != target_campaign
            or scope_hash != target_scope_hash
        )
        advisory_only = bool(payload.get("advisoryOnly"))
        needs_revalidation = bool(payload.get("needsRevalidation"))
        if cross_theme and not (advisory_only and needs_revalidation):
            raise ContractValidationError(
                "cross-theme memory candidates must be advisoryOnly and needsRevalidation"
            )
        accepted = bool(payload.get("accepted"))
        injected = bool(payload.get("injected"))
        if injected and not accepted:
            raise ContractValidationError(
                "an unaccepted memory candidate must never be injected"
            )
        accepted_at = str(payload.get("acceptedAt") or "").strip()
        injected_at = str(payload.get("injectedAt") or "").strip()
        if accepted and not accepted_at:
            raise ContractValidationError("an accepted memory candidate requires acceptedAt")
        if injected and not injected_at:
            raise ContractValidationError("an injected memory candidate requires injectedAt")
        return cls(
            memoryCandidateId=require_text(payload, "memoryCandidateId"),
            agentId=require_text(payload, "agentId"),
            theme=theme,
            campaign=campaign,
            scopeHash=scope_hash,
            targetTheme=target_theme,
            targetCampaign=target_campaign,
            targetScopeHash=target_scope_hash,
            sourceRefs=tuple(str(item) for item in require_list(payload, "sourceRefs")),
            memoryClass=memory_class,
            reusePolicy=reuse_policy,
            evidenceStatus=evidence_status,
            summary=require_text(payload, "summary"),
            needsRevalidation=needs_revalidation,
            advisoryOnly=advisory_only,
            accepted=accepted,
            injected=injected,
            createdAt=require_text(payload, "createdAt"),
            acceptedAt=accepted_at,
            injectedAt=injected_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memoryCandidateId": self.memoryCandidateId,
            "agentId": self.agentId,
            "theme": self.theme,
            "campaign": self.campaign,
            "scopeHash": self.scopeHash,
            "targetTheme": self.targetTheme,
            "targetCampaign": self.targetCampaign,
            "targetScopeHash": self.targetScopeHash,
            "sourceRefs": list(self.sourceRefs),
            "memoryClass": self.memoryClass,
            "reusePolicy": self.reusePolicy,
            "evidenceStatus": self.evidenceStatus,
            "summary": self.summary,
            "needsRevalidation": self.needsRevalidation,
            "advisoryOnly": self.advisoryOnly,
            "accepted": self.accepted,
            "injected": self.injected,
            "createdAt": self.createdAt,
            "acceptedAt": self.acceptedAt,
            "injectedAt": self.injectedAt,
        }

    def is_cross_theme(self) -> bool:
        return (
            self.theme != self.targetTheme
            or self.campaign != self.targetCampaign
            or self.scopeHash != self.targetScopeHash
        )
