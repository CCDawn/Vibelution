"""Meeting digest contract produced when a meeting round closes.

Schema v2 aligns with the full-lifecycle digest model (requirements §15.3):
the digest keeps the agenda summary, agreements, structured disagreements,
owned action items, risks, blockers, knowledge candidates, source message
refs, and a content hash so a closed meeting stays auditable and every
conclusion can be traced back to the original room messages.  Legacy v1
digests (no schemaVersion or ``schemaVersion: 1``) stay read-only compatible:
the new fields default to empty, mirroring the Question v1/v2 dual-read
pattern. Model-backed drafts may additionally retain an open Markdown document
and a source-owned protocol fact ledger; both are optional v2 extensions so
previously persisted digests remain readable without migration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ._validation import (
    ContractValidationError,
    require_list,
    require_sha256,
    require_text,
)


def _optional_str_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    if key not in payload or payload.get(key) is None:
        return ()
    return tuple(str(item) for item in require_list(payload, key))


def _disagreements(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    if "disagreements" not in payload or payload.get("disagreements") is None:
        return ()
    items = require_list(payload, "disagreements")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ContractValidationError(f"disagreements[{index}] must be an object")
        issue = str(item.get("issue") or "").strip()
        if not issue:
            raise ContractValidationError(f"disagreements[{index}].issue must be a non-empty string")
        positions = item.get("positions")
        if not isinstance(positions, list) or not positions:
            raise ContractValidationError(f"disagreements[{index}].positions must be a non-empty list")
        unresolved_reason = str(item.get("unresolvedReason") or "").strip()
        if not unresolved_reason:
            raise ContractValidationError(
                f"disagreements[{index}].unresolvedReason must be a non-empty string"
            )
        normalized.append(
            {
                "issue": issue,
                "positions": [str(position) for position in positions],
                "unresolvedReason": unresolved_reason,
            }
        )
    return tuple(normalized)


def _action_items(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    if "actionItems" not in payload or payload.get("actionItems") is None:
        return ()
    items = require_list(payload, "actionItems")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ContractValidationError(f"actionItems[{index}] must be an object")
        owner_role_id = str(item.get("ownerRoleId") or "").strip()
        if not owner_role_id:
            raise ContractValidationError(f"actionItems[{index}].ownerRoleId must be a non-empty string")
        action = str(item.get("action") or "").strip()
        if not action:
            raise ContractValidationError(f"actionItems[{index}].action must be a non-empty string")
        normalized.append(
            {
                "ownerRoleId": owner_role_id,
                "action": action,
                "dueGate": str(item.get("dueGate") or "").strip(),
            }
        )
    return tuple(normalized)


def _optional_content_hash(payload: Mapping[str, Any]) -> str:
    value = str(payload.get("contentHash") or "").strip().lower()
    if not value:
        return ""
    return require_sha256(payload, "contentHash")


def _optional_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{key} must be an object")
    return dict(value)


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
    agendaSummary: str = ""
    agreements: tuple[str, ...] = field(default_factory=tuple)
    disagreements: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    actionItems: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)
    knowledgeCandidates: tuple[str, ...] = field(default_factory=tuple)
    sourceMessageRefs: tuple[str, ...] = field(default_factory=tuple)
    documentMarkdown: str = ""
    documentTemplateId: str = ""
    factLedger: dict[str, Any] = field(default_factory=dict)
    contentHash: str = ""

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
            agendaSummary=str(payload.get("agendaSummary") or "").strip(),
            agreements=_optional_str_tuple(payload, "agreements"),
            disagreements=_disagreements(payload),
            actionItems=_action_items(payload),
            risks=_optional_str_tuple(payload, "risks"),
            blockers=_optional_str_tuple(payload, "blockers"),
            knowledgeCandidates=_optional_str_tuple(payload, "knowledgeCandidates"),
            sourceMessageRefs=_optional_str_tuple(payload, "sourceMessageRefs"),
            documentMarkdown=str(payload.get("documentMarkdown") or "").strip(),
            documentTemplateId=str(payload.get("documentTemplateId") or "").strip(),
            factLedger=_optional_mapping(payload, "factLedger"),
            contentHash=_optional_content_hash(payload),
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
            "agendaSummary": self.agendaSummary,
            "agreements": list(self.agreements),
            "disagreements": [dict(item) for item in self.disagreements],
            "actionItems": [dict(item) for item in self.actionItems],
            "risks": list(self.risks),
            "blockers": list(self.blockers),
            "knowledgeCandidates": list(self.knowledgeCandidates),
            "sourceMessageRefs": list(self.sourceMessageRefs),
            "documentMarkdown": self.documentMarkdown,
            "documentTemplateId": self.documentTemplateId,
            "factLedger": dict(self.factLedger),
            "contentHash": self.contentHash,
        }
