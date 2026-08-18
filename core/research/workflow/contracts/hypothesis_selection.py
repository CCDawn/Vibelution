"""Hypothesis selection record contract for the hypothesis-first flow.

A ``HypothesisSelectionRecord`` is the auditable, append-only fact that a
decider picked an ordered set of hypothesis candidates from one approved v2
question artifact.  Re-selection appends a new record whose
``previousSelectionId`` points at the record it replaces, so the current base
hypothesis set of a question is always the latest record of an unbroken chain.

Parsing fails closed: every scope identity field is required, the supplied
``scopeHash`` must match the identity, the ordered candidate list must carry
1..``MAX_SELECTED_CANDIDATES`` distinct non-empty ids, and ``decidedBy`` /
``createdAt`` must be present.  Membership of each candidate in the approved
question artifact is enforced by the owning service, which holds the artifact
read path; this contract only guarantees shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._validation import (
    ContractValidationError,
    require_list,
    require_text,
)
from .research_scope import REQUIRED_SCOPE_FIELDS, scope_hash_for

MAX_SELECTED_CANDIDATES = 16


def _scope_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    identity = {field: require_text(payload, field) for field in REQUIRED_SCOPE_FIELDS}
    identity["agentId"] = require_text(payload, "agentId")
    identity["mode"] = require_text(payload, "mode").lower()
    return identity


def _validated_scope_hash(payload: Mapping[str, Any], identity: Mapping[str, str]) -> str:
    supplied = require_text(payload, "scopeHash").lower()
    expected = scope_hash_for(
        **{field: identity[field] for field in REQUIRED_SCOPE_FIELDS},
        agent_id=identity["agentId"],
        mode=identity["mode"],
    )
    if supplied != expected:
        raise ContractValidationError(
            "scopeHash does not match the selection scope identity"
        )
    return supplied


@dataclass(frozen=True, slots=True)
class HypothesisSelectionRecord:
    """One scoped, ordered hypothesis candidate selection with chain linkage."""

    selectionId: str
    program: str
    theme: str
    campaign: str
    question: str
    branch: str
    workflow: str
    agentId: str
    mode: str
    scopeHash: str
    questionId: str
    selectedCandidateIds: tuple[str, ...]
    previousSelectionId: str
    decidedBy: str
    createdAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HypothesisSelectionRecord:
        identity = _scope_identity(payload)
        raw_candidates = require_list(payload, "selectedCandidateIds", non_empty=True)
        candidates = tuple(str(item or "").strip() for item in raw_candidates)
        if any(not candidate for candidate in candidates):
            raise ContractValidationError(
                "selectedCandidateIds must not contain empty entries"
            )
        if len(candidates) > MAX_SELECTED_CANDIDATES:
            raise ContractValidationError(
                f"selectedCandidateIds must contain at most {MAX_SELECTED_CANDIDATES} candidates"
            )
        if len(set(candidates)) != len(candidates):
            raise ContractValidationError("selectedCandidateIds must be unique")
        return cls(
            selectionId=require_text(payload, "selectionId"),
            **identity,
            scopeHash=_validated_scope_hash(payload, identity),
            questionId=require_text(payload, "questionId"),
            selectedCandidateIds=candidates,
            previousSelectionId=str(payload.get("previousSelectionId") or "").strip(),
            decidedBy=require_text(payload, "decidedBy"),
            createdAt=require_text(payload, "createdAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selectionId": self.selectionId,
            "program": self.program,
            "theme": self.theme,
            "campaign": self.campaign,
            "question": self.question,
            "branch": self.branch,
            "workflow": self.workflow,
            "agentId": self.agentId,
            "mode": self.mode,
            "scopeHash": self.scopeHash,
            "questionId": self.questionId,
            "selectedCandidateIds": list(self.selectedCandidateIds),
            "previousSelectionId": self.previousSelectionId,
            "decidedBy": self.decidedBy,
            "createdAt": self.createdAt,
        }
