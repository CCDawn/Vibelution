"""Decision record contract produced when a meeting round closes."""

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

DECISION_KINDS = {
    "select_candidate",
    "reject_candidate",
    "advance",
    "repair_and_repeat",
    "close_round",
    "request_new_evidence",
}
DECISION_STATUSES = {"pending", "adopted", "rejected"}


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One append-only decision taken by a closed meeting round."""

    decisionId: str
    meetingRoundId: str
    scopeHash: str
    decision: str
    rationale: str
    decidedBy: str
    candidateRefs: tuple[str, ...]
    evidenceRefs: tuple[str, ...]
    status: str
    createdAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DecisionRecord:
        decision = require_text(payload, "decision").lower()
        if decision not in DECISION_KINDS:
            raise ContractValidationError(
                "decision must be one of: " + ", ".join(sorted(DECISION_KINDS))
            )
        status = require_text(payload, "status").lower()
        if status not in DECISION_STATUSES:
            raise ContractValidationError(
                "decision status must be one of: " + ", ".join(sorted(DECISION_STATUSES))
            )
        return cls(
            decisionId=require_text(payload, "decisionId"),
            meetingRoundId=require_text(payload, "meetingRoundId"),
            scopeHash=require_sha256(payload, "scopeHash"),
            decision=decision,
            rationale=require_text(payload, "rationale"),
            decidedBy=require_text(payload, "decidedBy"),
            candidateRefs=tuple(
                str(item) for item in require_list(payload, "candidateRefs")
            ),
            evidenceRefs=tuple(
                str(item) for item in require_list(payload, "evidenceRefs")
            ),
            status=status,
            createdAt=require_text(payload, "createdAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisionId": self.decisionId,
            "meetingRoundId": self.meetingRoundId,
            "scopeHash": self.scopeHash,
            "decision": self.decision,
            "rationale": self.rationale,
            "decidedBy": self.decidedBy,
            "candidateRefs": list(self.candidateRefs),
            "evidenceRefs": list(self.evidenceRefs),
            "status": self.status,
            "createdAt": self.createdAt,
        }
