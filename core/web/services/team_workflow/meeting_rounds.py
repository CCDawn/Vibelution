"""Append-only meeting round service with closure artifacts.

Closing a meeting round always produces a ``MeetingDigest``, at least one
``DecisionRecord``, and one ``PersonalMemoryCandidate`` for every participating
agent.  Repeated close/recovery is idempotent: identical inputs reuse the
existing artifacts instead of duplicating them.

Schema v2 (requirements §15.1/§15.3) adds the four-state lifecycle
``open -> summarizing -> awaiting_approval -> closed``: a room-bound meeting
(hypothesis-first ``hypothesis_review`` rounds) is summarized from its linked
chat-room messages into a Coordinator digest draft, a human approves the
draft, and only then are the closure artifacts written.  The approval gate
enforces the §15.4 completion conditions fail-closed (disagreements, risks,
and action items from the source messages must survive into the digest;
decisions need evidence refs; action items need role owners; the digest must
link back to real room messages).  Legacy non-room-bound meetings keep the
original direct ``close_meeting_round`` path.  No research runtime is
involved; chat-room access is read-only except for the binding metadata the
runtime writes through ``bind_meeting_chat_room_round``.

DEV fixture convention: the deterministic digest drafter and the closure
gate share a marker convention over room message content — ``AGREE:``,
``DISAGREE:``, ``RISK:``, ``ACTION: <ownerRoleId> | <action>``,
``KNOWLEDGE:`` — and a bare ``pass`` marks a speaker with no new content.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts import (
    ContractValidationError,
    DecisionRecord,
    MeetingDigest,
    MeetingRound,
    scope_hash_for,
)

SCHEMA_VERSION = 2
LEGACY_DIGEST_SCHEMA_VERSION = 1
DEFAULT_MODE = "formal"
_LOCK = threading.RLock()
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")

_MARKER_PREFIXES = (
    "AGREE",
    "DISAGREE",
    "RISK",
    "ACTION",
    "KNOWLEDGE",
    "CANDIDATE",
    "EVIDENCE_REQUEST",
)
_PASS_TOKENS = {"pass", "pass.", "pass。"}

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ResearchMeetingRoundError(RuntimeError):
    """Base error for meeting round persistence."""


class ResearchMeetingRoundNotFoundError(ResearchMeetingRoundError):
    """Raised when a meeting round does not exist."""


def _project_root() -> Path:
    return Path(PROJECT_ROOT)


def _safe_team_id(team_id: str) -> str:
    from core.web.services.team_workflow.storage_ids import safe_storage_component

    return safe_storage_component(team_id, fallback="team")


def _team_workspace_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )


def _kind_path(team_id: str, kind: str) -> Path:
    return _team_workspace_root(team_id) / "research_workflow" / f"{kind}.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    return read_jsonl_tolerant(path)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    append_jsonl_locked(path, record)


def _resolve_scope(payload: Mapping[str, Any]) -> dict[str, str]:
    identity: dict[str, str] = {}
    for field in _SCOPE_FIELDS:
        value = str(payload.get(field) or "").strip()
        if not value:
            raise ContractValidationError(
                f"scope requires a non-empty '{field}' field"
            )
        identity[field] = value
    agent_id = str(payload.get("agentId") or "").strip()
    if not agent_id:
        raise ContractValidationError("scope requires a non-empty agentId")
    mode = str(payload.get("mode") or "").strip().lower() or DEFAULT_MODE
    if mode not in {"formal", "dev", "platform"}:
        raise ContractValidationError(f"unsupported scope mode: {mode}")
    scope_hash = scope_hash_for(**identity, agent_id=agent_id, mode=mode)
    return {**identity, "agentId": agent_id, "mode": mode, "scopeHash": scope_hash}


def _latest_by_id(records: list[dict[str, Any]], field: str, record_id: str) -> dict[str, Any] | None:
    matched = [record for record in records if str(record.get(field) or "") == record_id]
    return matched[-1] if matched else None


def _rounds_path(team_id: str) -> Path:
    return _kind_path(team_id, "meeting_rounds")


def _digests_path(team_id: str) -> Path:
    return _kind_path(team_id, "meeting_digests")


def _decisions_path(team_id: str) -> Path:
    return _kind_path(team_id, "decision_records")


def _normalized_str_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or []) if str(item or "").strip()]


def _meeting_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "meetingRoundId",
            "program",
            "theme",
            "campaign",
            "question",
            "branch",
            "workflow",
            "agentId",
            "mode",
            "scopeHash",
            "meetingType",
            "participants",
            "discussionItemRefs",
            "stage",
            "roundType",
            "agenda",
            "agendaQuestions",
            "agendaRules",
            "rounds",
            "participantRoleIds",
            "inputArtifactRefs",
            "linkedChatRoomId",
        )
    }


def _closure_hash(payload: Mapping[str, Any]) -> str:
    return _stable_hash(
        {
            "summary": str(payload.get("summary") or "").strip(),
            "discussionTopics": list(payload.get("discussionTopics") or []),
            "decisions": list(payload.get("decisions") or []),
            "closedBy": str(payload.get("closedBy") or "").strip(),
            "memoryClass": str(payload.get("memoryClass") or "personal_reflection"),
            "memorySummaries": dict(payload.get("memorySummaries"))
            if isinstance(payload.get("memorySummaries"), Mapping)
            else {},
            "reusePolicy": str(payload.get("reusePolicy") or "advisory_only"),
            "evidenceStatus": str(payload.get("evidenceStatus") or "unverified"),
            "accepted": bool(payload.get("accepted")),
        }
    )


def _approval_closure_hash(payload: Mapping[str, Any], digest_draft: Mapping[str, Any]) -> str:
    return _stable_hash(
        {
            "closure": _closure_hash(payload),
            "digestDraft": _stable_hash(dict(digest_draft)),
        }
    )


def create_meeting_round(team_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create one append-only meeting round with an explicit participant list."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    request = dict(payload) if isinstance(payload, Mapping) else {}
    scope = _resolve_scope(request)
    now = _utc_now()
    requested_status = str(request.get("status") or "open").strip().lower()
    if requested_status != "open":
        raise ContractValidationError(
            "a meeting round must be created open and closed through close_meeting_round"
        )
    meeting_round_id = (
        str(request.get("meetingRoundId") or "").strip()
        or f"meeting-{_stable_hash({'scopeHash': scope['scopeHash'], 'meetingType': str(request.get('meetingType') or ''), 'startedAt': now})[:16]}"
    )
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "meetingRoundId": meeting_round_id,
        **scope,
        "meetingType": str(request.get("meetingType") or "hypothesis_review").strip().lower(),
        "participants": _normalized_str_list(request.get("participants")),
        "discussionItemRefs": _normalized_str_list(request.get("discussionItemRefs")),
        "status": "open",
        "startedAt": str(request.get("startedAt") or "").strip() or now,
        "closedAt": "",
        "closedBy": "",
        "stage": str(request.get("stage") or "").strip().lower(),
        "roundType": str(request.get("roundType") or "").strip().lower(),
        "agenda": _normalized_str_list(request.get("agenda")),
        "agendaQuestions": _normalized_str_list(request.get("agendaQuestions")),
        "agendaRules": _normalized_str_list(request.get("agendaRules")),
        "rounds": request.get("rounds") if request.get("rounds") is not None else 3,
        "participantRoleIds": _normalized_str_list(request.get("participantRoleIds")),
        "inputArtifactRefs": _normalized_str_list(request.get("inputArtifactRefs")),
        "linkedChatRoomId": str(request.get("linkedChatRoomId") or "").strip(),
        "chatRoomRoundIds": [],
    }
    if not record["participants"]:
        raise ContractValidationError("a meeting round requires at least one participant")
    parsed = MeetingRound.from_dict(record)
    record["rounds"] = parsed.rounds
    with _LOCK:
        existing = _latest_by_id(_read_jsonl(_rounds_path(normalized_team_id)), "meetingRoundId", meeting_round_id)
        if existing is not None and existing.get("schemaVersion") is not None:
            if _meeting_definition(existing) != _meeting_definition(record):
                raise ResearchMeetingRoundError(
                    "meeting round id is already bound to different content"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "meetingRound": existing,
                "storagePath": str(_rounds_path(normalized_team_id)),
            }
        _append_jsonl(_rounds_path(normalized_team_id), record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "meetingRound": record,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def _ensure_transition_from(
    meeting_round: Mapping[str, Any], expected: str, target: str
) -> None:
    """Pin the exact source status for one lifecycle action (fail closed)."""

    current = str(meeting_round.get("status") or "").strip().lower()
    if current != expected:
        raise ContractValidationError(
            f"meeting status transition {current or '<unknown>'} -> {target} is not allowed"
        )


def _load_meeting_round(normalized_team_id: str, meeting_round_id: str) -> dict[str, Any]:
    records = _read_jsonl(_rounds_path(normalized_team_id))
    meeting_round = _latest_by_id(records, "meetingRoundId", meeting_round_id)
    if meeting_round is None:
        raise ResearchMeetingRoundNotFoundError("Meeting round not found.")
    return meeting_round


def _append_round_record(normalized_team_id: str, record: dict[str, Any]) -> dict[str, Any]:
    MeetingRound.from_dict(record)
    _append_jsonl(_rounds_path(normalized_team_id), record)
    return record


def bind_meeting_chat_room_round(
    team_id: str,
    meeting_round_id: str,
    room_id: str,
    round_id: str,
) -> dict[str, Any]:
    """Bind one chat-room discussion round to an open meeting round (both ways).

    The meeting record carries ``linkedChatRoomId``/``chatRoomRoundIds``; the
    room round carries ``config.meetingRoundId`` (set by the caller when it
    starts the round).  Rebinding the same pair is a no-op.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    normalized_room_id = str(room_id or "").strip()
    normalized_room_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    if not normalized_room_id or not normalized_room_round_id:
        raise ContractValidationError("binding a meeting round requires roomId and roundId")
    with _LOCK:
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        status = str(meeting_round.get("status") or "").strip().lower()
        if status != "open":
            raise ResearchMeetingRoundError(
                "only an open meeting round can bind a chat room discussion round"
            )
        linked_room_id = str(meeting_round.get("linkedChatRoomId") or "").strip()
        if linked_room_id and linked_room_id != normalized_room_id:
            raise ResearchMeetingRoundError(
                "meeting round is already bound to a different chat room"
            )
        bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
        if linked_room_id == normalized_room_id and normalized_room_round_id in bound_round_ids:
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "meetingRound": meeting_round,
                "storagePath": str(_rounds_path(normalized_team_id)),
            }
        updated = dict(meeting_round)
        updated["linkedChatRoomId"] = normalized_room_id
        updated["chatRoomRoundIds"] = [*bound_round_ids, normalized_room_round_id]
        updated["updatedAt"] = _utc_now()
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "bound",
        "meetingRound": updated,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def _room_rounds_by_id(room_detail: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(room_detail, Mapping):
        return {}
    return {
        str(item.get("roundId") or "").strip(): dict(item)
        for item in list(room_detail.get("rounds") or [])
        if isinstance(item, dict) and str(item.get("roundId") or "").strip()
    }


def _load_bound_room_rounds(meeting_round: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Read the bound chat-room rounds (read-only) for one room-bound meeting."""

    room_id = str(meeting_round.get("linkedChatRoomId") or "").strip()
    round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    if not room_id or not round_ids:
        return {}
    from core.web.services import chat_room_service

    room_detail = chat_room_service.get_chat_room_detail(room_id)
    if room_detail is None:
        raise ResearchMeetingRoundError("Linked chat room not found for the meeting round.")
    rounds_by_id = _room_rounds_by_id(room_detail)
    missing = [round_id for round_id in round_ids if round_id not in rounds_by_id]
    if missing:
        raise ResearchMeetingRoundError(
            f"Linked chat room is missing bound discussion round: {missing[0]}"
        )
    return {round_id: rounds_by_id[round_id] for round_id in round_ids}


def meeting_source_messages(meeting_round: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the bound room discussion messages in stable round/message order."""

    messages: list[dict[str, Any]] = []
    room_id = str(meeting_round.get("linkedChatRoomId") or "").strip()
    for round_id, room_round in _load_bound_room_rounds(meeting_round).items():
        for message in list(room_round.get("messages") or []):
            if not isinstance(message, dict):
                continue
            entry = dict(message)
            entry["roomId"] = room_id
            entry["roundId"] = round_id
            messages.append(entry)
    return messages


def completed_meeting_source_messages(
    meeting_round: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return successful, non-pass discussion messages that a digest may cite."""

    return [
        message
        for message in meeting_source_messages(meeting_round)
        if str(message.get("status") or "").strip().lower() == "completed"
        and not is_pass_message(message)
    ]


_EMPTY_DISCUSSION_RECOVERY_TYPES = {
    "hypothesis_candidate_generation",
    "hypothesis_review",
}


def supersede_empty_discussion_meeting(
    team_id: str,
    meeting_round_id: str,
    *,
    actor: str = "system:failed-discussion-recovery",
) -> dict[str, Any]:
    """Close one terminal discussion attempt that produced no citable message.

    Applies to candidate-generation and hypothesis-review rounds alike.  This
    recovery record deliberately carries no digest or decisions: it is an
    abandoned attempt, not an approved research conclusion.  A follow-up
    meeting (fresh generation attempt or next review round) can then open
    without rewriting the append-only history of the failed attempt.
    """

    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    with _LOCK:
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
    status = str(meeting_round.get("status") or "").strip().lower()
    if status == "closed" and str(meeting_round.get("recoveryReason") or "") == (
        "discussion_has_no_completed_messages"
    ):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "meetingRound": meeting_round,
            "storagePath": str(_rounds_path(normalized_team_id)),
        }
    if (
        str(meeting_round.get("meetingType") or "").strip().lower()
        not in _EMPTY_DISCUSSION_RECOVERY_TYPES
    ):
        raise ResearchMeetingRoundError(
            "only discussion meetings may use empty-discussion recovery"
        )
    if status not in {"open", "summarizing"}:
        raise ResearchMeetingRoundError(
            f"meeting status {status or '<unknown>'} cannot be superseded"
        )
    if running_bound_round_ids(meeting_round):
        raise ResearchMeetingRoundError(
            "discussion round is still running and cannot be superseded"
        )
    if completed_meeting_source_messages(meeting_round):
        raise ResearchMeetingRoundError(
            "discussion produced completed messages and cannot be superseded"
        )

    now = _utc_now()
    closed_record = dict(meeting_round)
    closed_record["status"] = "closed"
    closed_record["closedAt"] = now
    closed_record["closedBy"] = str(actor or "").strip() or "system:failed-discussion-recovery"
    closed_record["recoveryReason"] = "discussion_has_no_completed_messages"
    closed_record["summaryDraftError"] = {
        "code": "discussion_has_no_completed_messages",
        "message": "讨论未产出可引用的成功发言，已结束本次失败尝试",
        "remediationLabel": "重新发起讨论",
    }
    closed_record["updatedAt"] = now
    with _LOCK:
        latest = _load_meeting_round(normalized_team_id, normalized_round_id)
        if str(latest.get("status") or "").strip().lower() != status:
            raise ResearchMeetingRoundError(
                "meeting status changed while failed-discussion recovery was running"
            )
        _append_round_record(normalized_team_id, closed_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "superseded",
        "meetingRound": closed_record,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def message_source_ref(message: Mapping[str, Any]) -> str:
    """Stable digest -> room message backlink: ``roomId/roundId/messageId``."""

    return "/".join(
        [
            str(message.get("roomId") or "").strip(),
            str(message.get("roundId") or "").strip(),
            str(message.get("messageId") or "").strip(),
        ]
    )


def is_pass_message(message: Mapping[str, Any]) -> bool:
    return str(message.get("content") or "").strip().lower() in _PASS_TOKENS


def extract_discussion_markers(messages: Sequence[Mapping[str, Any]]) -> dict[str, list[Any]]:
    """Extract the DEV fixture marker lines from completed room messages."""

    extracted: dict[str, list[Any]] = {
        "agreements": [],
        "disagreements": [],
        "risks": [],
        "actionItems": [],
        "knowledgeCandidates": [],
        "proposedCandidates": [],
        "evidenceRequests": [],
        "evidenceRequestErrors": [],
    }
    for message in messages:
        if str(message.get("status") or "").strip().lower() != "completed":
            continue
        content = str(message.get("content") or "").strip()
        if not content or is_pass_message(message):
            continue
        speaker = (
            str(message.get("speakerTitle") or "").strip()
            or str(message.get("participantId") or "").strip()
            or "participant"
        )
        for line in content.splitlines():
            text = line.strip()
            if not text or ":" not in text:
                continue
            prefix, _, body = text.partition(":")
            marker = prefix.strip().upper()
            if marker not in _MARKER_PREFIXES:
                continue
            value = body.strip()
            if not value:
                continue
            if marker == "AGREE":
                extracted["agreements"].append(value)
            elif marker == "DISAGREE":
                extracted["disagreements"].append(
                    {
                        "issue": value,
                        "positions": [f"{speaker}: {value}"],
                        "unresolvedReason": "讨论中未收敛（fixture 提取）",
                    }
                )
            elif marker == "RISK":
                extracted["risks"].append(value)
            elif marker == "KNOWLEDGE":
                extracted["knowledgeCandidates"].append(value)
            elif marker == "ACTION":
                owner, separator, action = value.partition("|")
                extracted["actionItems"].append(
                    {
                        "ownerRoleId": owner.strip(),
                        "action": (action if separator else owner).strip(),
                        "dueGate": "",
                    }
                )
            elif marker == "CANDIDATE":
                # CANDIDATE: <id> | <statement> | <rationale> — one proposed
                # hypothesis per line from a candidate-generation discussion.
                parts = [part.strip() for part in value.split("|")]
                if len(parts) >= 2:
                    candidate_id, statement = parts[0], parts[1]
                    rationale = parts[2] if len(parts) >= 3 else ""
                else:
                    candidate_id, statement, rationale = "", parts[0], ""
                extracted["proposedCandidates"].append(
                    {
                        "candidateId": candidate_id,
                        "statement": statement,
                        "rationale": rationale,
                        "proposedBy": speaker,
                    }
                )
            elif marker == "EVIDENCE_REQUEST":
                try:
                    if len(value) > _EVIDENCE_REQUEST_MARKER_MAX_CHARS:
                        extracted["evidenceRequestErrors"].append(
                            {
                                "code": "evidence_request_too_large",
                                "message": "EVIDENCE_REQUEST marker exceeds 65536 chars",
                            }
                        )
                        continue
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    extracted["evidenceRequestErrors"].append(
                        {
                            "code": "evidence_request_json_invalid",
                            "message": "EVIDENCE_REQUEST marker is not valid JSON",
                        }
                    )
                    continue
                if not isinstance(parsed, dict):
                    extracted["evidenceRequestErrors"].append(
                        {
                            "code": "evidence_request_invalid",
                            "message": "EVIDENCE_REQUEST JSON must be an object",
                        }
                    )
                    continue
                extracted["evidenceRequests"].append(parsed)
    return extracted


UNSTRUCTURED_DERIVED_FROM = "unstructured"
EMPTY_DIGEST_CAPTURE_MESSAGE = "纪要未捕获讨论内容"
_UNSTRUCTURED_SUMMARY_MAX_CHARS = 240
_STRUCTURED_MARKER_KEYS = (
    "agreements",
    "disagreements",
    "risks",
    "actionItems",
    "knowledgeCandidates",
    "proposedCandidates",
    "evidenceRequests",
)
_EVIDENCE_REQUEST_MARKER_MAX_CHARS = 65536
_DIGEST_CAPTURE_KEYS = (
    "agreements",
    "disagreements",
    "actionItems",
    "knowledgeCandidates",
    "evidenceRequests",
)


def digest_agreement_texts(value: Any) -> list[str]:
    """Normalize marker strings and unstructured objects into digest texts."""

    texts: list[str] = []
    for item in list(value or []):
        if isinstance(item, Mapping):
            text = str(
                item.get("text") or item.get("issue") or item.get("summary") or ""
            ).strip()
        else:
            text = str(item or "").strip()
        if text:
            texts.append(text)
    return texts


def structured_marker_item_count(markers: Mapping[str, Any]) -> int:
    return sum(len(list(markers.get(key) or [])) for key in _STRUCTURED_MARKER_KEYS)


def digest_draft_captured_discussion(draft: Mapping[str, Any]) -> bool:
    return any(list(draft.get(key) or []) for key in _DIGEST_CAPTURE_KEYS)


def _unstructured_summary_text(content: str) -> str:
    collapsed = " ".join(str(content or "").split())
    if len(collapsed) <= _UNSTRUCTURED_SUMMARY_MAX_CHARS:
        return collapsed
    return collapsed[: _UNSTRUCTURED_SUMMARY_MAX_CHARS - 1].rstrip() + "…"


def derive_unstructured_digest_entries(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Turn free-form completed speeches into cited summary entries.

    These are not fabricated consensus: each item is a speech excerpt marked
    ``derivedFrom=unstructured`` and linked back to the source message.
    """

    entries: list[dict[str, Any]] = []
    for message in messages:
        if str(message.get("status") or "").strip().lower() != "completed":
            continue
        if is_pass_message(message):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        message_id = str(message.get("messageId") or "").strip()
        if not message_id:
            continue
        speaker = (
            str(message.get("speakerTitle") or "").strip()
            or str(message.get("participantId") or "").strip()
            or "participant"
        )
        entries.append(
            {
                "text": _unstructured_summary_text(content),
                "speaker": speaker,
                "derivedFrom": UNSTRUCTURED_DERIVED_FROM,
                "sourceMessageRefs": [message_source_ref(message)],
            }
        )
    return entries


def apply_unstructured_digest_fallback(
    markers: Mapping[str, list[Any]],
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, list[Any]]:
    """Fill agreements with cited speech summaries when marker extraction is empty."""

    merged = {str(key): list(value) for key, value in dict(markers).items()}
    if structured_marker_item_count(merged):
        return merged
    entries = derive_unstructured_digest_entries(messages)
    if entries:
        merged["agreements"] = entries
    return merged


def assert_review_digest_captured_discussion(
    meeting_round: Mapping[str, Any],
    draft: Mapping[str, Any],
    source_messages: Sequence[Mapping[str, Any]],
) -> None:
    """Fail-closed: a review with completed speech cannot approve an empty digest."""

    if str(meeting_round.get("meetingType") or "").strip().lower() != "hypothesis_review":
        return
    completed = [
        message
        for message in source_messages
        if str(message.get("status") or "").strip().lower() == "completed"
        and not is_pass_message(message)
        and str(message.get("content") or "").strip()
    ]
    if not completed:
        return
    if not digest_draft_captured_discussion(draft):
        raise ContractValidationError(EMPTY_DIGEST_CAPTURE_MESSAGE)


def source_message_content_hash(messages: Sequence[Mapping[str, Any]]) -> str:
    """Stable hash of bound discussion message content used for draft reuse."""

    return _stable_hash(
        [
            {
                "ref": message_source_ref(message),
                "content": str(message.get("content") or ""),
                "status": str(message.get("status") or "").strip().lower(),
            }
            for message in list(messages or [])
            if isinstance(message, Mapping)
        ]
    )


def running_bound_round_ids(meeting_round: Mapping[str, Any]) -> list[str]:
    """Return bound chat-room round ids that are still in a running status."""

    from core.web.services import chat_room_service

    bound_rounds = _load_bound_room_rounds(meeting_round)
    return [
        round_id
        for round_id, room_round in bound_rounds.items()
        if str(room_round.get("status") or "").strip().lower()
        in chat_room_service.RUNNING_ROUND_STATUSES
    ]


def record_meeting_summary_draft_error(
    team_id: str,
    meeting_round_id: str,
    error: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist a structured draft failure while keeping ``summarizing``."""

    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    with _LOCK:
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        updated = dict(meeting_round)
        if str(updated.get("status") or "").strip().lower() == "open":
            updated["status"] = "summarizing"
            updated["summaryStartedAt"] = _utc_now()
        updated["summaryDraftError"] = {
            "code": str(error.get("code") or "summary_draft_failed").strip()
            or "summary_draft_failed",
            "message": str(error.get("message") or "").strip(),
            "remediationLabel": str(error.get("remediationLabel") or "重试生成纪要").strip()
            or "重试生成纪要",
        }
        updated["updatedAt"] = _utc_now()
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": str(updated.get("status") or "summarizing"),
        "meetingRound": updated,
        "summaryDraftError": updated["summaryDraftError"],
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def begin_meeting_summary(
    team_id: str,
    meeting_round_id: str,
    *,
    actor: str = "",
    human_triggered: bool = False,
) -> dict[str, Any]:
    """Move one open meeting round to ``summarizing`` (discussion finished or human call)."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    with _LOCK:
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        _ensure_transition_from(meeting_round, "open", "summarizing")
        bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    if bound_round_ids and not human_triggered:
        from core.web.services import chat_room_service

        bound_rounds = _load_bound_room_rounds(meeting_round)
        running = [
            round_id
            for round_id, room_round in bound_rounds.items()
            if str(room_round.get("status") or "").strip().lower()
            in chat_room_service.RUNNING_ROUND_STATUSES
        ]
        if running:
            raise ResearchMeetingRoundError(
                "discussion round is still running; wait for completion or pass human_triggered=True"
            )
    with _LOCK:
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        _ensure_transition_from(meeting_round, "open", "summarizing")
        updated = dict(meeting_round)
        updated["status"] = "summarizing"
        updated["summarizedBy"] = str(actor or "").strip()
        updated["summaryStartedAt"] = _utc_now()
        updated["summaryHumanTriggered"] = bool(human_triggered)
        updated["updatedAt"] = updated["summaryStartedAt"]
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "summarizing",
        "meetingRound": updated,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def _validate_digest_draft(draft: Mapping[str, Any]) -> None:
    """Fail closed when a digest draft drops any §15.3/§15.4 required section."""

    missing_keys = [
        key
        for key in (
            "agreements",
            "disagreements",
            "actionItems",
            "risks",
            "knowledgeCandidates",
            "sourceMessageRefs",
        )
        if key not in draft
    ]
    if missing_keys:
        raise ContractValidationError(
            "digest draft is missing required sections: " + ", ".join(missing_keys)
        )
    if not str(draft.get("summary") or "").strip():
        raise ContractValidationError("digest draft requires a summary")
    if not _normalized_str_list(draft.get("sourceMessageRefs")):
        raise ContractValidationError(
            "digest draft sourceMessageRefs must reference at least one source message"
        )


def submit_meeting_digest_draft(
    team_id: str,
    meeting_round_id: str,
    draft: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach a Coordinator digest draft and move ``summarizing -> awaiting_approval``."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    normalized_draft = dict(draft) if isinstance(draft, Mapping) else {}
    with _LOCK:
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        _ensure_transition_from(meeting_round, "summarizing", "awaiting_approval")
        _validate_digest_draft(normalized_draft)
        probe = {
            "digestId": "digest-draft-probe",
            "meetingRoundId": normalized_round_id,
            "scopeHash": str(meeting_round.get("scopeHash") or ""),
            "summary": str(normalized_draft.get("summary") or "").strip(),
            "participantAgentIds": list(meeting_round.get("participants") or []),
            "discussionTopics": _normalized_str_list(normalized_draft.get("discussionTopics")),
            "decisionRefs": ["decision-draft-probe"],
            "closedBy": "draft-probe",
            "createdAt": _utc_now(),
            "agendaSummary": str(normalized_draft.get("agendaSummary") or "").strip(),
            "agreements": digest_agreement_texts(normalized_draft.get("agreements")),
            "disagreements": list(normalized_draft.get("disagreements") or []),
            "actionItems": list(normalized_draft.get("actionItems") or []),
            "risks": list(normalized_draft.get("risks") or []),
            "blockers": list(normalized_draft.get("blockers") or []),
            "knowledgeCandidates": list(normalized_draft.get("knowledgeCandidates") or []),
            "sourceMessageRefs": list(normalized_draft.get("sourceMessageRefs") or []),
            "contentHash": str(normalized_draft.get("contentHash") or ""),
        }
        MeetingDigest.from_dict(probe)
        normalized_draft["contentHash"] = _digest_content_hash(normalized_draft)
        updated = dict(meeting_round)
        updated["status"] = "awaiting_approval"
        updated["digestDraft"] = normalized_draft
        updated.pop("summaryDraftError", None)
        updated["updatedAt"] = _utc_now()
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "awaiting_approval",
        "meetingRound": updated,
        "digestDraft": normalized_draft,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def reject_meeting_digest_draft(
    team_id: str,
    meeting_round_id: str,
    *,
    actor: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Human rejects the digest draft: ``awaiting_approval -> summarizing``."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    with _LOCK:
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        _ensure_transition_from(meeting_round, "awaiting_approval", "summarizing")
        updated = dict(meeting_round)
        updated["status"] = "summarizing"
        updated.pop("digestDraft", None)
        updated["draftRejectedBy"] = str(actor or "").strip()
        updated["draftRejectedReason"] = str(reason or "").strip()
        updated["updatedAt"] = _utc_now()
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "summarizing",
        "meetingRound": updated,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def _digest_content_hash(payload: Mapping[str, Any]) -> str:
    return _stable_hash(
        {
            "summary": str(payload.get("summary") or "").strip(),
            "agendaSummary": str(payload.get("agendaSummary") or "").strip(),
            "discussionTopics": _normalized_str_list(payload.get("discussionTopics")),
            "agreements": digest_agreement_texts(payload.get("agreements")),
            "disagreements": list(payload.get("disagreements") or []),
            "actionItems": list(payload.get("actionItems") or []),
            "risks": _normalized_str_list(payload.get("risks")),
            "blockers": _normalized_str_list(payload.get("blockers")),
            "knowledgeCandidates": _normalized_str_list(payload.get("knowledgeCandidates")),
            "sourceMessageRefs": _normalized_str_list(payload.get("sourceMessageRefs")),
            "proposedCandidates": list(payload.get("proposedCandidates") or []),
            "evidenceRequests": list(payload.get("evidenceRequests") or []),
        }
    )


def _build_digest(meeting_round: dict[str, Any], request: dict[str, Any], now: str) -> dict[str, Any]:
    summary = str(request.get("summary") or "").strip()
    if not summary:
        raise ContractValidationError("closing a meeting round requires a summary")
    digest_id = f"digest-{_stable_hash({'meetingRoundId': meeting_round['meetingRoundId'], 'scopeHash': meeting_round['scopeHash'], 'summary': summary})[:16]}"
    return {
        "schemaVersion": LEGACY_DIGEST_SCHEMA_VERSION,
        "digestId": digest_id,
        "meetingRoundId": str(meeting_round["meetingRoundId"]),
        "scopeHash": str(meeting_round["scopeHash"]),
        "summary": summary,
        "participantAgentIds": list(meeting_round.get("participants") or []),
        "discussionTopics": _normalized_str_list(request.get("discussionTopics")),
        "decisionRefs": _normalized_str_list(request.get("decisionRefs")),
        "closedBy": str(request.get("closedBy") or "").strip(),
        "createdAt": now,
    }


def _build_digest_v2(
    meeting_round: dict[str, Any],
    draft: Mapping[str, Any],
    request: Mapping[str, Any],
    now: str,
) -> dict[str, Any]:
    """Merge the approved draft with human amendments into the final digest."""

    merged: dict[str, Any] = dict(draft)
    for key in (
        "summary",
        "agendaSummary",
        "discussionTopics",
        "agreements",
        "disagreements",
        "actionItems",
        "risks",
        "blockers",
        "knowledgeCandidates",
        "sourceMessageRefs",
        "proposedCandidates",
        "evidenceRequests",
    ):
        if key in request and request.get(key) is not None:
            merged[key] = request.get(key)
    summary = str(merged.get("summary") or "").strip()
    if not summary:
        raise ContractValidationError("closing a meeting round requires a summary")
    digest_id = f"digest-{_stable_hash({'meetingRoundId': meeting_round['meetingRoundId'], 'scopeHash': meeting_round['scopeHash'], 'summary': summary})[:16]}"
    digest = {
        "schemaVersion": SCHEMA_VERSION,
        "digestId": digest_id,
        "meetingRoundId": str(meeting_round["meetingRoundId"]),
        "scopeHash": str(meeting_round["scopeHash"]),
        "summary": summary,
        "participantAgentIds": list(meeting_round.get("participants") or []),
        "discussionTopics": _normalized_str_list(merged.get("discussionTopics")),
        "decisionRefs": _normalized_str_list(merged.get("decisionRefs")),
        "closedBy": str(request.get("closedBy") or "").strip(),
        "createdAt": now,
        "agendaSummary": str(merged.get("agendaSummary") or "").strip(),
        "agreements": digest_agreement_texts(merged.get("agreements")),
        "disagreements": list(merged.get("disagreements") or []),
        "actionItems": list(merged.get("actionItems") or []),
        "risks": _normalized_str_list(merged.get("risks")),
        "blockers": _normalized_str_list(merged.get("blockers")),
        "knowledgeCandidates": _normalized_str_list(merged.get("knowledgeCandidates")),
        "sourceMessageRefs": _normalized_str_list(merged.get("sourceMessageRefs")),
    }
    digest["contentHash"] = _digest_content_hash(digest)
    return digest


def _build_decision(meeting_round: dict[str, Any], raw: Mapping[str, Any], now: str) -> dict[str, Any]:
    decision = str(raw.get("decision") or "").strip().lower()
    if not decision:
        raise ContractValidationError("each decision requires a decision kind")
    candidate_refs = _normalized_str_list(raw.get("candidateRefs"))
    evidence_refs = _normalized_str_list(raw.get("evidenceRefs"))
    decision_id = f"decision-{_stable_hash({'meetingRoundId': meeting_round['meetingRoundId'], 'scopeHash': meeting_round['scopeHash'], 'decision': decision, 'candidateRefs': candidate_refs, 'evidenceRefs': evidence_refs})[:16]}"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "decisionId": decision_id,
        "meetingRoundId": str(meeting_round["meetingRoundId"]),
        "scopeHash": str(meeting_round["scopeHash"]),
        "decision": decision,
        "rationale": str(raw.get("rationale") or "").strip(),
        "decidedBy": str(raw.get("decidedBy") or "").strip(),
        "candidateRefs": candidate_refs,
        "evidenceRefs": evidence_refs,
        "status": str(raw.get("status") or "adopted").strip().lower(),
        "createdAt": now,
    }


def _marker_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("issue") or value.get("action") or "").strip()
    return str(value or "").strip()


def _assert_markers_preserved(
    digest: Mapping[str, Any],
    markers: Mapping[str, list[Any]],
) -> None:
    digest_disagreements = [
        str(item.get("issue") or "")
        for item in list(digest.get("disagreements") or [])
        if isinstance(item, Mapping)
    ]
    for marker in list(markers.get("disagreements") or []):
        issue = _marker_text(marker)
        if issue and not any(issue in digest_issue for digest_issue in digest_disagreements):
            raise ContractValidationError(
                "a disagreement from the source messages is missing in the meeting digest"
            )
    digest_risks = _normalized_str_list(digest.get("risks"))
    for marker in list(markers.get("risks") or []):
        risk = _marker_text(marker)
        if risk and not any(risk in digest_risk for digest_risk in digest_risks):
            raise ContractValidationError(
                "an unresolved risk from the source messages is missing in the meeting digest"
            )
    digest_actions = [
        str(item.get("action") or "")
        for item in list(digest.get("actionItems") or [])
        if isinstance(item, Mapping)
    ]
    for marker in list(markers.get("actionItems") or []):
        action = _marker_text(marker)
        if action and not any(action in digest_action for digest_action in digest_actions):
            raise ContractValidationError(
                "an action item from the source messages is missing in the meeting digest"
            )


def _assert_closure_conditions(
    meeting_round: Mapping[str, Any],
    digest: Mapping[str, Any],
    decisions: list[dict[str, Any]],
    raw_decisions: Sequence[Mapping[str, Any]],
    source_messages: list[dict[str, Any]],
) -> None:
    """Requirements §15.4 meeting completion conditions, enforced fail-closed."""

    if not str(digest.get("summary") or "").strip() or not decisions:
        raise ContractValidationError(
            "closing a meeting round requires a summary and at least one decision record"
        )
    _assert_markers_preserved(digest, extract_discussion_markers(source_messages))
    for decision in decisions:
        if not list(decision.get("evidenceRefs") or []):
            raise ContractValidationError(
                "each decision record requires at least one evidence ref"
            )
    for index, item in enumerate(list(digest.get("actionItems") or [])):
        if not isinstance(item, Mapping):
            raise ContractValidationError(f"actionItems[{index}] must be an object")
        if not str(item.get("ownerRoleId") or "").strip():
            raise ContractValidationError("each action item requires a role owner")
        if not str(item.get("action") or "").strip():
            raise ContractValidationError("each action item requires an action")
    source_refs = _normalized_str_list(digest.get("sourceMessageRefs"))
    if not source_refs:
        raise ContractValidationError(
            "digest sourceMessageRefs must reference at least one source message"
        )
    if source_messages:
        known_message_ids = {
            str(message.get("messageId") or "").strip()
            for message in source_messages
            if str(message.get("messageId") or "").strip()
        }
        for ref in source_refs:
            message_id = ref.rsplit("/", 1)[-1].strip()
            if not message_id or message_id not in known_message_ids:
                raise ContractValidationError(
                    f"digest sourceMessageRefs must reference existing room messages: {ref}"
                )
    for raw in raw_decisions:
        if bool(raw.get("requiresHumanApproval")) and str(raw.get("status") or "").strip().lower() != "pending":
            raise ContractValidationError(
                "decisions that require human approval must be marked pending"
            )


def _persist_closure_artifacts(
    normalized_team_id: str,
    meeting_round: dict[str, Any],
    digest: dict[str, Any],
    decisions: list[dict[str, Any]],
    request: Mapping[str, Any],
    now: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    from core.web.services.team_workflow.personal_memory_candidates import (
        record_personal_memory_candidates,
    )

    with _LOCK:
        appended_digest = _latest_by_id(
            _read_jsonl(_digests_path(normalized_team_id)),
            "digestId",
            digest["digestId"],
        )
        if appended_digest is None:
            _append_jsonl(_digests_path(normalized_team_id), digest)
        else:
            digest = appended_digest
        appended_decisions: list[dict[str, Any]] = []
        for decision in decisions:
            existing_decision = _latest_by_id(
                _read_jsonl(_decisions_path(normalized_team_id)),
                "decisionId",
                decision["decisionId"],
            )
            if existing_decision is None:
                _append_jsonl(_decisions_path(normalized_team_id), decision)
            else:
                decision = existing_decision
            appended_decisions.append(decision)
        decisions = appended_decisions
        participants = _normalized_str_list(meeting_round.get("participants"))
        memory_result = record_personal_memory_candidates(
            normalized_team_id,
            scope_payload={
                "program": meeting_round.get("program") or "",
                "theme": meeting_round.get("theme") or "",
                "campaign": meeting_round.get("campaign") or "",
                "question": meeting_round.get("question") or "",
                "branch": meeting_round.get("branch") or "",
                "workflow": meeting_round.get("workflow") or "",
                "agentId": meeting_round.get("agentId") or "",
                "mode": meeting_round.get("mode") or "",
            },
            agents=participants,
            source_refs=[
                f"meeting_round:{meeting_round['meetingRoundId']}",
                f"meeting_digest:{digest['digestId']}",
                *[f"decision_record:{item['decisionId']}" for item in decisions],
            ],
            memory_class=str(request.get("memoryClass") or "personal_reflection"),
            summaries=request.get("memorySummaries") if isinstance(request.get("memorySummaries"), Mapping) else None,
            reuse_policy=str(request.get("reusePolicy") or "advisory_only"),
            evidence_status=str(request.get("evidenceStatus") or "unverified"),
            accepted=bool(request.get("accepted")),
        )
    return digest, decisions, memory_result


def _closed_record(
    meeting_round: dict[str, Any],
    digest: Mapping[str, Any],
    decisions: list[dict[str, Any]],
    memory_result: Mapping[str, Any],
    request: Mapping[str, Any],
    now: str,
    *,
    closure_hash: str,
) -> dict[str, Any]:
    closed_record = dict(meeting_round)
    closed_record["status"] = "closed"
    closed_record["closedAt"] = now
    closed_record["closedBy"] = str(request.get("closedBy") or "").strip()
    closed_record["digestId"] = digest["digestId"]
    closed_record["decisionRefs"] = [str(item.get("decisionId") or "") for item in decisions]
    closed_record["personalMemoryCandidateRefs"] = [
        {
            "memoryCandidateId": str(item.get("memoryCandidateId") or ""),
            "agentId": str(item.get("agentId") or ""),
            "theme": str(item.get("theme") or ""),
            "targetTheme": str(item.get("targetTheme") or ""),
        }
        for item in memory_result["candidates"]
    ]
    closed_record["closureHash"] = closure_hash
    closed_record["updatedAt"] = now
    return closed_record


def _reused_close_result(
    normalized_team_id: str,
    meeting_round: dict[str, Any],
) -> dict[str, Any]:
    digest_id = str(meeting_round.get("digestId") or "").strip()
    digest = (
        _latest_by_id(_read_jsonl(_digests_path(normalized_team_id)), "digestId", digest_id)
        if digest_id
        else None
    )
    decision_refs = list(meeting_round.get("decisionRefs") or [])
    decisions = [
        item
        for item in _read_jsonl(_decisions_path(normalized_team_id))
        if str(item.get("decisionId") or "") in decision_refs
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "reused",
        "closed": True,
        "meetingRound": meeting_round,
        "digest": digest or (meeting_round.get("digest") or {}),
        "decisions": decisions,
        "personalMemoryCandidateRefs": list(
            meeting_round.get("personalMemoryCandidateRefs") or []
        ),
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def approve_meeting_closure(
    team_id: str,
    meeting_round_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Human confirms the digest draft: ``awaiting_approval -> closed``.

    Runs the §15.4 completion gate fail-closed, then writes the digest,
    decision records, and per-participant memory candidates.  Repeating the
    same approval reuses the existing artifacts (closure hash idempotency).
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _LOCK:
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        current = str(meeting_round.get("status") or "").strip().lower()
        if current == "closed":
            digest_draft = (
                dict(meeting_round.get("digestDraft"))
                if isinstance(meeting_round.get("digestDraft"), Mapping)
                else {}
            )
            if str(meeting_round.get("closureHash") or "") != _approval_closure_hash(request, digest_draft):
                raise ResearchMeetingRoundError(
                    "closed meeting round cannot be reused with different closure content"
                )
            return _reused_close_result(normalized_team_id, meeting_round)
        _ensure_transition_from(meeting_round, "awaiting_approval", "closed")
        digest_draft = (
            dict(meeting_round.get("digestDraft"))
            if isinstance(meeting_round.get("digestDraft"), Mapping)
            else {}
        )
        if not digest_draft:
            raise ResearchMeetingRoundError(
                "meeting round has no digest draft; submit one before approval"
            )
    source_messages = meeting_source_messages(meeting_round)
    assert_review_digest_captured_discussion(meeting_round, digest_draft, source_messages)
    now = _utc_now()
    digest = _build_digest_v2(meeting_round, digest_draft, request, now)
    raw_decisions = [item for item in list(request.get("decisions") or []) if isinstance(item, Mapping)]
    if not raw_decisions:
        raise ContractValidationError(
            "closing a meeting round requires at least one decision record"
        )
    decisions = [_build_decision(meeting_round, item, now) for item in raw_decisions]
    for decision in decisions:
        DecisionRecord.from_dict(decision)
    digest["decisionRefs"] = [str(item.get("decisionId") or "") for item in decisions]
    _assert_closure_conditions(meeting_round, digest, decisions, raw_decisions, source_messages)
    MeetingDigest.from_dict(digest)
    digest, decisions, memory_result = _persist_closure_artifacts(
        normalized_team_id, meeting_round, digest, decisions, request, now
    )
    memory_agents = {str(item.get("agentId") or "") for item in memory_result["candidates"]}
    missing_memory_agents = [
        agent_id
        for agent_id in _normalized_str_list(meeting_round.get("participants"))
        if agent_id not in memory_agents
    ]
    if missing_memory_agents:
        raise ContractValidationError(
            "personal memory candidates must cover every participant: " + ", ".join(missing_memory_agents)
        )
    closed_record = _closed_record(
        meeting_round,
        digest,
        decisions,
        memory_result,
        request,
        now,
        closure_hash=_approval_closure_hash(request, digest_draft),
    )
    with _LOCK:
        _append_round_record(normalized_team_id, closed_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "closed": True,
        "meetingRound": closed_record,
        "digest": digest,
        "decisions": decisions,
        "personalMemoryCandidateRefs": closed_record["personalMemoryCandidateRefs"],
        "memorySummary": {
            "createdCount": memory_result["createdCount"],
            "reusedCount": memory_result["reusedCount"],
        },
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def close_meeting_round(
    team_id: str,
    meeting_round_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Close one meeting round, producing digest, decisions, and memory candidates.

    Idempotent: repeating close with the same content reuses the already
    appended artifacts and the closed round record.  This direct path stays
    available for legacy non-room-bound meetings; room-bound rounds (the
    hypothesis-first flow) must close through the four-state
    ``begin_meeting_summary -> submit_meeting_digest_draft ->
    approve_meeting_closure`` gate instead.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _LOCK:
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        current_status = str(meeting_round.get("status") or "").strip().lower()
        if current_status == "closed":
            if str(meeting_round.get("closureHash") or "") != _closure_hash(request):
                raise ResearchMeetingRoundError(
                    "closed meeting round cannot be reused with different closure content"
                )
            return _reused_close_result(normalized_team_id, meeting_round)
        if current_status in {"summarizing", "awaiting_approval"}:
            raise ResearchMeetingRoundError(
                "meeting round is in the approval flow; close it through approve_meeting_closure"
            )
        if str(meeting_round.get("linkedChatRoomId") or "").strip():
            raise ResearchMeetingRoundError(
                "room-bound meeting rounds close through the summarize/approve flow"
            )
    participants = _normalized_str_list(meeting_round.get("participants"))
    now = _utc_now()
    digest = _build_digest(meeting_round, request, now)
    raw_decisions = [item for item in list(request.get("decisions") or []) if isinstance(item, Mapping)]
    if not raw_decisions:
        raise ContractValidationError(
            "closing a meeting round requires at least one decision record"
        )
    decisions = [_build_decision(meeting_round, item, now) for item in raw_decisions]
    for decision in decisions:
        DecisionRecord.from_dict(decision)
    digest["decisionRefs"] = [str(item.get("decisionId") or "") for item in decisions]
    MeetingDigest.from_dict(digest)
    digest, decisions, memory_result = _persist_closure_artifacts(
        normalized_team_id, meeting_round, digest, decisions, request, now
    )
    closed_record = _closed_record(
        meeting_round,
        digest,
        decisions,
        memory_result,
        request,
        now,
        closure_hash=_closure_hash(request),
    )
    with _LOCK:
        _append_round_record(normalized_team_id, closed_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "closed": True,
        "meetingRound": closed_record,
        "digest": digest,
        "decisions": decisions,
        "personalMemoryCandidateRefs": closed_record[
            "personalMemoryCandidateRefs"
        ],
        "memorySummary": {
            "createdCount": memory_result["createdCount"],
            "reusedCount": memory_result["reusedCount"],
        },
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def list_meeting_rounds(team_id: str) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    with _LOCK:
        records = _read_jsonl(_rounds_path(normalized_team_id))
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[str(record.get("meetingRoundId") or "")] = record
    rows = sorted(latest.values(), key=lambda item: str(item.get("startedAt") or ""))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "meetingCount": len(rows),
        "meetings": rows,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def get_meeting_round(team_id: str, meeting_round_id: str) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    with _LOCK:
        record = _load_meeting_round(normalized_team_id, normalized_round_id)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "meetingRound": record,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }
