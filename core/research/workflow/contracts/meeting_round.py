"""Meeting round contract that scopes agent participants to one review session."""

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

MEETING_TYPES = {
    "hypothesis_review",
    "plan_review",
    "result_review",
    "iteration_review",
    "scope_review",
}
MEETING_STATUSES = {"open", "closed"}


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
        raise ContractValidationError("scopeHash does not match the meeting scope identity")
    return supplied


@dataclass(frozen=True, slots=True)
class MeetingRound:
    """One scoped, offline agent meeting round with an explicit participant list."""

    meetingRoundId: str
    program: str
    theme: str
    campaign: str
    question: str
    branch: str
    workflow: str
    agentId: str
    mode: str
    scopeHash: str
    meetingType: str
    participants: tuple[str, ...]
    discussionItemRefs: tuple[str, ...]
    status: str
    startedAt: str
    closedAt: str
    closedBy: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MeetingRound:
        meeting_type = require_text(payload, "meetingType").lower()
        if meeting_type not in MEETING_TYPES:
            raise ContractValidationError(
                "meetingType must be one of: " + ", ".join(sorted(MEETING_TYPES))
            )
        status = require_text(payload, "status").lower()
        if status not in MEETING_STATUSES:
            raise ContractValidationError(
                "meeting status must be one of: " + ", ".join(sorted(MEETING_STATUSES))
            )
        identity = _scope_identity(payload)
        participants = tuple(
            str(item) for item in require_list(payload, "participants", non_empty=True)
        )
        if len(set(participants)) != len(participants):
            raise ContractValidationError("participant agent ids must be unique")
        started_at = require_text(payload, "startedAt")
        closed_at = str(payload.get("closedAt") or "").strip()
        closed_by = str(payload.get("closedBy") or "").strip()
        if status == "closed" and not (closed_at and closed_by):
            raise ContractValidationError(
                "a closed meeting round requires closedAt and closedBy"
            )
        return cls(
            meetingRoundId=require_text(payload, "meetingRoundId"),
            **identity,
            scopeHash=_validated_scope_hash(payload, identity),
            meetingType=meeting_type,
            participants=participants,
            discussionItemRefs=tuple(
                str(item) for item in require_list(payload, "discussionItemRefs")
            ),
            status=status,
            startedAt=started_at,
            closedAt=closed_at,
            closedBy=closed_by,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "meetingRoundId": self.meetingRoundId,
            "program": self.program,
            "theme": self.theme,
            "campaign": self.campaign,
            "question": self.question,
            "branch": self.branch,
            "workflow": self.workflow,
            "agentId": self.agentId,
            "mode": self.mode,
            "scopeHash": self.scopeHash,
            "meetingType": self.meetingType,
            "participants": list(self.participants),
            "discussionItemRefs": list(self.discussionItemRefs),
            "status": self.status,
            "startedAt": self.startedAt,
            "closedAt": self.closedAt,
            "closedBy": self.closedBy,
        }
