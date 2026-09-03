"""Meeting round contract that scopes agent participants to one review session.

Schema v2 aligns with the full-lifecycle meeting model (requirements §15.1):
rounds carry a stage, a round type, the agenda quartet (agenda, guiding
questions, rules, planned discussion rounds), participant role ids, input
artifact refs, and the linked chat-room binding.  The status set grows from
``open|closed`` to ``open|summarizing|awaiting_approval|closed`` so closure
follows a draft-then-approve gate.  Legacy v1 records (no schemaVersion or
``schemaVersion: 1``) stay read-only compatible: new fields default to empty
and ``rounds`` defaults to 3, mirroring the Question v1/v2 dual-read pattern.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_mapping,
    require_sha256,
    require_text,
)
from .research_scope import REQUIRED_SCOPE_FIELDS, scope_hash_for

MEETING_TYPES = {
    "hypothesis_review",
    "hypothesis_candidate_generation",
    "plan_review",
    "result_review",
    "iteration_review",
    "scope_review",
}
MANAGED_HYPOTHESIS_PARTICIPANT_CONTRACT_TYPES = {
    "hypothesis_candidate_generation",
    "hypothesis_review",
}
MEETING_STATUSES = {"open", "summarizing", "awaiting_approval", "closed"}
MEETING_STAGES = {
    "knowledge",
    "hypothesis",
    "protocol",
    "experiment",
    "promotion",
    "submission",
}
MEETING_ROUND_TYPES = {
    "agenda_brief",
    "status_sync",
    "evidence_closure",
    "decision_gate",
    "risk_escalation",
    "generation",
}
DEFAULT_MEETING_ROUNDS = 2
MEETING_STATUS_TRANSITIONS = {
    "open": {"summarizing"},
    "summarizing": {"awaiting_approval"},
    "awaiting_approval": {"summarizing", "closed"},
    "closed": set(),
}


def ensure_meeting_status_transition(current: str, target: str) -> None:
    """Fail closed on any meeting status transition outside the frozen map."""

    normalized_current = str(current or "").strip().lower()
    normalized_target = str(target or "").strip().lower()
    if normalized_target not in MEETING_STATUSES:
        raise ContractValidationError(
            "meeting status must be one of: " + ", ".join(sorted(MEETING_STATUSES))
        )
    allowed = MEETING_STATUS_TRANSITIONS.get(normalized_current)
    if allowed is None or normalized_target not in allowed:
        raise ContractValidationError(
            f"meeting status transition {normalized_current or '<unknown>'} -> "
            f"{normalized_target} is not allowed"
        )


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


def _optional_str_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    if key not in payload or payload.get(key) is None:
        return ()
    return tuple(str(item) for item in require_list(payload, key))


def _optional_enum(payload: Mapping[str, Any], key: str, allowed: set[str]) -> str:
    value = str(payload.get(key) or "").strip().lower()
    if value and value not in allowed:
        raise ContractValidationError(
            f"{key} must be one of: " + ", ".join(sorted(allowed))
        )
    return value


def _optional_rounds(payload: Mapping[str, Any]) -> int:
    if "rounds" not in payload or payload.get("rounds") is None:
        return DEFAULT_MEETING_ROUNDS
    return require_int(payload, "rounds", minimum=1)


def _optional_non_negative_int(payload: Mapping[str, Any], key: str) -> int:
    if key not in payload or payload.get(key) is None:
        return 0
    return require_int(payload, key, minimum=0)


def _optional_role_snapshot(
    payload: Mapping[str, Any], key: str = "participantRoleSnapshot"
) -> tuple[dict[str, Any], ...]:
    if key not in payload or payload.get(key) is None:
        return ()
    entries = require_list(payload, key)
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ContractValidationError(
                f"{key}[{index}] must be an object"
            )
        normalized.append(require_mapping({key: entry}, key))
    return tuple(normalized)


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
    stage: str = ""
    roundType: str = ""
    agenda: tuple[str, ...] = field(default_factory=tuple)
    agendaQuestions: tuple[str, ...] = field(default_factory=tuple)
    agendaRules: tuple[str, ...] = field(default_factory=tuple)
    rounds: int = DEFAULT_MEETING_ROUNDS
    participantRoleIds: tuple[str, ...] = field(default_factory=tuple)
    teamRoleContractVersion: int = 0
    participantPolicyVersion: int = 0
    roleContractFingerprint: str = ""
    participantRoleSnapshot: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    resolutionHash: str = ""
    inputArtifactRefs: tuple[str, ...] = field(default_factory=tuple)
    linkedChatRoomId: str = ""
    chatRoomRoundIds: tuple[str, ...] = field(default_factory=tuple)

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
        if status != "closed" and (closed_at or closed_by):
            raise ContractValidationError(
                "only a closed meeting round may carry closedAt and closedBy"
            )
        team_role_contract_version = _optional_non_negative_int(
            payload, "teamRoleContractVersion"
        )
        participant_policy_version = _optional_non_negative_int(
            payload, "participantPolicyVersion"
        )
        role_contract_fingerprint = str(
            payload.get("roleContractFingerprint") or ""
        ).strip().lower()
        resolution_hash = str(payload.get("resolutionHash") or "").strip().lower()
        participant_role_snapshot = _optional_role_snapshot(payload)
        participant_role_ids = _optional_str_tuple(payload, "participantRoleIds")
        has_challenge_cup_participant_contract_fields = any(
            (
                team_role_contract_version,
                participant_policy_version,
                role_contract_fingerprint,
                participant_role_snapshot,
                resolution_hash,
            )
        )
        has_participant_contract = (
            has_challenge_cup_participant_contract_fields
            or (
                meeting_type in MANAGED_HYPOTHESIS_PARTICIPANT_CONTRACT_TYPES
                and bool(participant_role_ids)
            )
        )
        if has_participant_contract:
            if team_role_contract_version < 1:
                raise ContractValidationError(
                    "teamRoleContractVersion must be positive for participant contract snapshots"
                )
            if participant_policy_version < 1:
                raise ContractValidationError(
                    "participantPolicyVersion must be positive for participant contract snapshots"
                )
            if not role_contract_fingerprint:
                raise ContractValidationError(
                    "roleContractFingerprint is required for participant contract snapshots"
                )
            if not resolution_hash:
                raise ContractValidationError(
                    "resolutionHash is required for participant contract snapshots"
                )
            require_sha256(
                {"roleContractFingerprint": role_contract_fingerprint},
                "roleContractFingerprint",
            )
            require_sha256({"resolutionHash": resolution_hash}, "resolutionHash")
            if not participant_role_snapshot:
                raise ContractValidationError(
                    "participantRoleSnapshot is required for participant contract snapshots"
                )
            if len(participant_role_snapshot) != len(participants):
                raise ContractValidationError(
                    "participantRoleSnapshot must contain one entry per participant"
                )
            snapshot_role_ids = tuple(
                str(item.get("roleId") or "").strip()
                for item in participant_role_snapshot
            )
            snapshot_agent_ids = tuple(
                str(item.get("agentId") or "").strip()
                for item in participant_role_snapshot
            )
            if any(not role_id for role_id in snapshot_role_ids):
                raise ContractValidationError(
                    "participantRoleSnapshot entries require roleId"
                )
            if any(not agent_id for agent_id in snapshot_agent_ids):
                raise ContractValidationError(
                    "participantRoleSnapshot entries require agentId"
                )
            if len(set(snapshot_role_ids)) != len(snapshot_role_ids):
                raise ContractValidationError(
                    "participantRoleSnapshot roleIds must be unique"
                )
            if len(set(snapshot_agent_ids)) != len(snapshot_agent_ids):
                raise ContractValidationError(
                    "participantRoleSnapshot agentIds must be unique"
                )
            if not participant_role_ids:
                raise ContractValidationError(
                    "participantRoleIds is required for participant contract snapshots"
                )
            if participant_role_ids != snapshot_role_ids:
                raise ContractValidationError(
                    "participantRoleIds must match participantRoleSnapshot roleIds"
                )
            if snapshot_agent_ids != participants:
                raise ContractValidationError(
                    "participantRoleSnapshot agentIds must match participants"
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
            stage=_optional_enum(payload, "stage", MEETING_STAGES),
            roundType=_optional_enum(payload, "roundType", MEETING_ROUND_TYPES),
            agenda=_optional_str_tuple(payload, "agenda"),
            agendaQuestions=_optional_str_tuple(payload, "agendaQuestions"),
            agendaRules=_optional_str_tuple(payload, "agendaRules"),
            rounds=_optional_rounds(payload),
            participantRoleIds=participant_role_ids,
            teamRoleContractVersion=team_role_contract_version,
            participantPolicyVersion=participant_policy_version,
            roleContractFingerprint=role_contract_fingerprint,
            participantRoleSnapshot=participant_role_snapshot,
            resolutionHash=resolution_hash,
            inputArtifactRefs=_optional_str_tuple(payload, "inputArtifactRefs"),
            linkedChatRoomId=str(payload.get("linkedChatRoomId") or "").strip(),
            chatRoomRoundIds=_optional_str_tuple(payload, "chatRoomRoundIds"),
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
            "stage": self.stage,
            "roundType": self.roundType,
            "agenda": list(self.agenda),
            "agendaQuestions": list(self.agendaQuestions),
            "agendaRules": list(self.agendaRules),
            "rounds": self.rounds,
            "participantRoleIds": list(self.participantRoleIds),
            "teamRoleContractVersion": self.teamRoleContractVersion,
            "participantPolicyVersion": self.participantPolicyVersion,
            "roleContractFingerprint": self.roleContractFingerprint,
            "participantRoleSnapshot": [dict(item) for item in self.participantRoleSnapshot],
            "resolutionHash": self.resolutionHash,
            "inputArtifactRefs": list(self.inputArtifactRefs),
            "linkedChatRoomId": self.linkedChatRoomId,
            "chatRoomRoundIds": list(self.chatRoomRoundIds),
        }
