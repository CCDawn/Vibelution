"""Meeting digest contract produced when a meeting round closes."""

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


@dataclass(frozen=True, slots=True)
class MeetingDigest:
    """Append-only summary of one closed meeting round."""

    digestId: str
    meetingRoundId: str
    scopeHash: str
    summary: str
    participantAgentIds: tuple[str, ...]
    discussionTopics: tuple[str, ...]
    decisionRefs: tuple[str, ...]
    closedBy: str
    createdAt: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MeetingDigest:
        participants = tuple(
            str(item) for item in require_list(payload, "participantAgentIds", non_empty=True)
        )
        return cls(
            digestId=require_text(payload, "digestId"),
            meetingRoundId=require_text(payload, "meetingRoundId"),
            scopeHash=require_sha256(payload, "scopeHash"),
            summary=require_text(payload, "summary"),
            participantAgentIds=participants,
            discussionTopics=tuple(
                str(item) for item in require_list(payload, "discussionTopics")
            ),
            decisionRefs=tuple(
                str(item)
                for item in require_list(payload, "decisionRefs", non_empty=True)
            ),
            closedBy=require_text(payload, "closedBy"),
            createdAt=require_text(payload, "createdAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "digestId": self.digestId,
            "meetingRoundId": self.meetingRoundId,
            "scopeHash": self.scopeHash,
            "summary": self.summary,
            "participantAgentIds": list(self.participantAgentIds),
            "discussionTopics": list(self.discussionTopics),
            "decisionRefs": list(self.decisionRefs),
            "closedBy": self.closedBy,
            "createdAt": self.createdAt,
        }
