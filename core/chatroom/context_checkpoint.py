"""Deterministic, rebuildable context projection for Agent chat rooms.

Room transcript messages remain authoritative.  This module only derives a
stable checkpoint, a structured delta, and exact-reference lookup results from
that authority; it never mutates a Session Journal or Room Store object.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .context_payload import structured_protocol_from_message

CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_KIND = "ChatRoomContextCheckpoint.v1"
DEFAULT_DYNAMIC_TOKEN_THRESHOLD = 16_384
DEFAULT_VERBATIM_ROUNDS = 2
DEFAULT_REF_LIMIT = 5
DEFAULT_REF_BYTES = 32 * 1024

_TERMINAL_ROUND_STATUSES = {"completed", "partial", "stopped", "failed", "cancelled"}
_TERMINAL_MESSAGE_STATUS = "completed"
_SPACE_RE = re.compile(r"\s+")


class ChatRoomContextRefError(ValueError):
    """Raised when a room-scoped exact reference request is invalid."""


def _clean_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def _text_key(value: Any) -> str:
    return _clean_text(value).casefold()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    raw = value if isinstance(value, str) else _canonical_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _room_id(room: Mapping[str, Any]) -> str:
    return str(room.get("roomId") or room.get("id") or "").strip()


def _round_id(round_payload: Mapping[str, Any]) -> str:
    return str(round_payload.get("roundId") or round_payload.get("id") or "").strip()


def _message_id(message: Mapping[str, Any]) -> str:
    return str(message.get("messageId") or message.get("id") or "").strip()


def _speaker_id(message: Mapping[str, Any]) -> str:
    return str(
        message.get("participantId")
        or message.get("teamRole")
        or message.get("agentId")
        or message.get("speakerTitle")
        or ""
    ).strip()


def _speaker_role_id(room: Mapping[str, Any], message: Mapping[str, Any]) -> str:
    direct = str(message.get("teamRole") or message.get("roleId") or "").strip()
    if direct:
        return direct
    participant_id = str(message.get("participantId") or "").strip()
    for participant in list(room.get("participants") or []):
        if not isinstance(participant, Mapping):
            continue
        if str(participant.get("participantId") or "").strip() != participant_id:
            continue
        return str(
            participant.get("teamRole")
            or participant.get("roleId")
            or participant_id
        ).strip()
    return participant_id or _speaker_id(message)


def _message_ref(room_id: str, round_id: str, message: Mapping[str, Any]) -> str:
    return f"{room_id}/{round_id}/{_message_id(message)}"


def _participants_hash(room: Mapping[str, Any]) -> str:
    participants: list[dict[str, str]] = []
    for item in list(room.get("participants") or []):
        if not isinstance(item, Mapping):
            continue
        participants.append(
            {
                "participantId": _clean_text(item.get("participantId")),
                "agentId": _clean_text(item.get("agentId")),
                "teamRole": _clean_text(item.get("teamRole") or item.get("roleId")),
            }
        )
    participants.sort(key=lambda item: _canonical_json(item).casefold())
    return _sha256(participants)


def _rounds_by_id(room: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in list(room.get("rounds") or []):
        if isinstance(item, Mapping) and _round_id(item):
            result[_round_id(item)] = item
    return result


def _terminal_rounds(room: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        item
        for item in list(room.get("rounds") or [])
        if isinstance(item, Mapping)
        and str(item.get("status") or "").strip().lower() in _TERMINAL_ROUND_STATUSES
    ]


def _item_id(kind: str, identity: Any) -> str:
    return f"{kind}-{_sha256(identity)[:16]}"


def _source_item(value: Any, *, source_ref: str, speaker: str) -> dict[str, Any]:
    return {"value": copy.deepcopy(value), "sourceRef": source_ref, "speaker": speaker}


def _json_key(value: Any) -> str:
    if isinstance(value, str):
        return _text_key(value)
    return _canonical_json(_normalize_json_strings(value)).casefold()


def _normalize_json_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        return [_normalize_json_strings(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_json_strings(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    return value


def _reduce_state(
    room: Mapping[str, Any], covered_round_ids: Sequence[str]
) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    room_id = _room_id(room)
    selected = set(covered_round_ids)
    agreement_groups: dict[str, dict[str, Any]] = {}
    agreement_round_support: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    generic_groups: dict[str, dict[str, dict[str, Any]]] = {
        "disagreements": {},
        "risks": {},
        "evidenceRequests": {},
        "knowledgeCandidates": {},
    }
    action_groups: dict[str, dict[str, Any]] = {}
    pending_updates: list[tuple[str, str, str, str]] = []
    legacy: list[dict[str, str]] = []
    source_refs: list[str] = []
    topics: list[dict[str, str]] = []

    for round_payload in list(room.get("rounds") or []):
        if not isinstance(round_payload, Mapping):
            continue
        round_id = _round_id(round_payload)
        if round_id not in selected:
            continue
        topic = _clean_text(round_payload.get("topic"))
        if topic:
            topics.append({"topic": topic, "sourceRoundId": round_id})
        for message in list(round_payload.get("messages") or []):
            if not isinstance(message, Mapping):
                continue
            message_id = _message_id(message)
            if not message_id:
                continue
            source_ref = _message_ref(room_id, round_id, message)
            source_refs.append(source_ref)
            speaker = _speaker_id(message)
            speaker_role_id = _speaker_role_id(room, message)
            protocol = None
            if str(message.get("status") or "").strip().lower() == _TERMINAL_MESSAGE_STATUS:
                protocol = structured_protocol_from_message(message)
            if protocol is None:
                if str(message.get("status") or "").strip().lower() != _TERMINAL_MESSAGE_STATUS:
                    continue
                content = str(message.get("content") or "")
                first_line = next(
                    (_clean_text(line) for line in content.splitlines() if _clean_text(line)),
                    "",
                )
                if first_line:
                    legacy.append(
                        {
                            "excerpt": first_line[:500],
                            "sourceRef": source_ref,
                            "speaker": speaker,
                        }
                    )
                continue

            for statement in list(protocol.get("agreements") or []):
                text = _clean_text(statement)
                if not text:
                    continue
                key = _text_key(text)
                group = agreement_groups.setdefault(
                    key,
                    {
                        "itemId": _item_id("agreement", key),
                        "statement": text,
                        "status": "proposed",
                        "sourceRefs": [],
                        "supporterRoleIds": [],
                    },
                )
                if source_ref not in group["sourceRefs"]:
                    group["sourceRefs"].append(source_ref)
                if speaker and speaker not in group["supporterRoleIds"]:
                    group["supporterRoleIds"].append(speaker)
                agreement_round_support[key][round_id].add(speaker)

            for state_key, protocol_key, kind in (
                ("disagreements", "disagreements", "disagreement"),
                ("risks", "risks", "risk"),
                ("evidenceRequests", "evidenceRequests", "evidence"),
                ("knowledgeCandidates", "knowledgeCandidates", "knowledge"),
            ):
                for value in list(protocol.get(protocol_key) or []):
                    normalized = _normalize_json_strings(value)
                    key = _json_key(normalized)
                    if not key:
                        continue
                    group = generic_groups[state_key].setdefault(
                        key,
                        {
                            "itemId": _item_id(kind, key),
                            **(
                                {"statement": normalized}
                                if isinstance(normalized, str)
                                else {"value": normalized}
                            ),
                            "status": "open" if state_key in {"disagreements", "risks"} else "proposed",
                            "sourceRefs": [],
                        },
                    )
                    if source_ref not in group["sourceRefs"]:
                        group["sourceRefs"].append(source_ref)

            for action in list(protocol.get("actionItems") or []):
                if not isinstance(action, Mapping):
                    continue
                owner = _clean_text(action.get("ownerRoleId"))
                action_text = _clean_text(action.get("action"))
                due_gate = _clean_text(action.get("dueGate"))
                if not owner or not action_text:
                    continue
                identity = [_text_key(owner), _text_key(action_text), _text_key(due_gate)]
                item_id = _item_id("action", identity)
                group = action_groups.setdefault(
                    item_id,
                    {
                        "itemId": item_id,
                        "ownerRoleId": owner,
                        "action": action_text,
                        "dueGate": due_gate,
                        "status": "proposed",
                        "sourceRefs": [],
                    },
                )
                if source_ref not in group["sourceRefs"]:
                    group["sourceRefs"].append(source_ref)
                requested_status = _clean_text(action.get("status") or "proposed").lower()
                if _text_key(speaker_role_id) == _text_key(owner) and requested_status in {
                    "accepted",
                    "completed",
                    "blocked",
                }:
                    group["status"] = requested_status

            for update in list(protocol.get("stateUpdates") or []):
                if not isinstance(update, Mapping):
                    continue
                pending_updates.append(
                    (
                        _clean_text(update.get("itemId")),
                        _clean_text(update.get("status")).lower(),
                        speaker_role_id,
                        source_ref,
                    )
                )

    rounds_by_id = _rounds_by_id(room)
    for key, group in agreement_groups.items():
        for round_id, supporters in agreement_round_support[key].items():
            round_payload = rounds_by_id.get(round_id, {})
            planned = {
                str(item).strip()
                for item in list(round_payload.get("speakerOrder") or [])
                if str(item).strip()
            }
            round_status = str(round_payload.get("status") or "").strip().lower()
            if round_status == "completed" and planned and planned.issubset(supporters):
                group["status"] = "confirmed"
                break

    all_items: dict[str, dict[str, Any]] = {
        item["itemId"]: item
        for item in [
            *agreement_groups.values(),
            *action_groups.values(),
            *(entry for groups in generic_groups.values() for entry in groups.values()),
        ]
    }
    rejected_updates: list[dict[str, str]] = []
    for item_id, status, speaker, source_ref in pending_updates:
        target = all_items.get(item_id)
        if target is None:
            rejected_updates.append(
                {"itemId": item_id, "reason": "unknown_item_id", "sourceRef": source_ref}
            )
            continue
        if item_id.startswith("agreement-") and status != target.get("status"):
            rejected_updates.append(
                {
                    "itemId": item_id,
                    "reason": "consensus_required",
                    "sourceRef": source_ref,
                }
            )
            continue
        if item_id.startswith("action-") and _text_key(speaker) != _text_key(
            target.get("ownerRoleId")
        ):
            rejected_updates.append(
                {"itemId": item_id, "reason": "owner_required", "sourceRef": source_ref}
            )
            continue
        allowed = (
            {"proposed", "confirmed", "superseded"}
            if item_id.startswith("agreement-")
            else {"proposed", "accepted", "completed", "blocked"}
            if item_id.startswith("action-")
            else {"open", "resolved", "accepted", "rejected", "superseded"}
        )
        if status not in allowed:
            rejected_updates.append(
                {"itemId": item_id, "reason": "invalid_status", "sourceRef": source_ref}
            )
            continue
        target["status"] = status
        if source_ref not in target["sourceRefs"]:
            target["sourceRefs"].append(source_ref)

    def _sorted(groups: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
        values = [copy.deepcopy(value) for value in groups.values()]
        for value in values:
            value["sourceRefs"] = sorted(set(value["sourceRefs"]))
            if "supporterRoleIds" in value:
                value["supporterRoleIds"] = sorted(set(value["supporterRoleIds"]))
        return sorted(values, key=lambda value: str(value["itemId"]))

    state = {
        "topics": topics,
        "agreements": _sorted(agreement_groups),
        "disagreements": _sorted(generic_groups["disagreements"]),
        "risks": _sorted(generic_groups["risks"]),
        "actionItems": _sorted(action_groups),
        "evidenceRequests": _sorted(generic_groups["evidenceRequests"]),
        "knowledgeCandidates": _sorted(generic_groups["knowledgeCandidates"]),
        "formalDecisionRefs": [],
        "rejectedStateUpdates": sorted(
            rejected_updates,
            key=lambda value: (value["sourceRef"], value["itemId"], value["reason"]),
        ),
    }
    formal_source_refs = _apply_formal_context_projections(state, room)
    if formal_source_refs:
        legacy = [
            item for item in legacy if item.get("sourceRef") not in formal_source_refs
        ]
        source_refs.extend(formal_source_refs)
    return state, legacy, source_refs


def _formal_context_projections(room: Mapping[str, Any]) -> list[dict[str, Any]]:
    available_refs = {
        _message_ref(_room_id(room), _round_id(round_payload), message)
        for round_payload in list(room.get("rounds") or [])
        if isinstance(round_payload, Mapping) and _round_id(round_payload)
        for message in list(round_payload.get("messages") or [])
        if isinstance(message, Mapping) and _message_id(message)
    }
    rows = [
        dict(item)
        for item in list(room.get("contextFormalProjections") or [])
        if isinstance(item, Mapping)
        and str(item.get("digestRef") or "").strip()
        and bool(list(item.get("sourceMessageRefs") or []))
        and all(
            str(ref).strip() in available_refs
            for ref in list(item.get("sourceMessageRefs") or [])
        )
    ]
    return sorted(rows, key=lambda item: str(item.get("digestRef") or ""))


def _apply_formal_context_projections(
    state: dict[str, Any], room: Mapping[str, Any]
) -> set[str]:
    """Overlay approved digest facts on message-derived proposals."""

    formal_source_refs: set[str] = set()
    projections = _formal_context_projections(room)
    if not projections:
        return formal_source_refs

    for projection in projections:
        digest_ref = str(projection.get("digestRef") or "").strip()
        source_message_refs = {
            str(item).strip()
            for item in list(projection.get("sourceMessageRefs") or [])
            if str(item).strip()
        }
        formal_source_refs.update(source_message_refs)
        if source_message_refs:
            for key in (
                "agreements",
                "disagreements",
                "risks",
                "actionItems",
                "evidenceRequests",
                "knowledgeCandidates",
            ):
                state[key] = [
                    item
                    for item in state[key]
                    if not source_message_refs.intersection(item.get("sourceRefs") or [])
                ]

        protocol = (
            projection.get("protocol")
            if isinstance(projection.get("protocol"), Mapping)
            else {}
        )
        for topic in list(protocol.get("topics") or []):
            text = _clean_text(topic)
            if text and not any(
                _text_key(item.get("topic")) == _text_key(text)
                for item in state["topics"]
            ):
                state["topics"].append(
                    {"topic": text, "sourceRoundId": "", "sourceDigestRef": digest_ref}
                )
        for statement in list(protocol.get("agreements") or []):
            text = _clean_text(statement)
            if not text:
                continue
            key = _text_key(text)
            state["agreements"] = [
                item
                for item in state["agreements"]
                if _text_key(item.get("statement")) != key
            ]
            state["agreements"].append(
                {
                    "itemId": _item_id("agreement", key),
                    "statement": text,
                    "status": "confirmed",
                    "sourceRefs": [digest_ref, *sorted(source_message_refs)],
                    "supporterRoleIds": [],
                }
            )

        for state_key, protocol_key, kind, status in (
            ("disagreements", "disagreements", "disagreement", "open"),
            ("risks", "risks", "risk", "open"),
            ("evidenceRequests", "evidenceRequests", "evidence", "accepted"),
            ("knowledgeCandidates", "knowledgeCandidates", "knowledge", "accepted"),
        ):
            for value in list(protocol.get(protocol_key) or []):
                normalized = _normalize_json_strings(value)
                key = _json_key(normalized)
                if not key:
                    continue
                state[state_key] = [
                    item for item in state[state_key] if item.get("itemId") != _item_id(kind, key)
                ]
                state[state_key].append(
                    {
                        "itemId": _item_id(kind, key),
                        **(
                            {"statement": normalized}
                            if isinstance(normalized, str)
                            else {"value": normalized}
                        ),
                        "status": status,
                        "sourceRefs": [digest_ref, *sorted(source_message_refs)],
                    }
                )

        for action in list(protocol.get("actionItems") or []):
            if not isinstance(action, Mapping):
                continue
            owner = _clean_text(action.get("ownerRoleId") or action.get("owner"))
            action_text = _clean_text(action.get("action") or action.get("task"))
            due_gate = _clean_text(action.get("dueGate") or action.get("due"))
            if not owner or not action_text:
                continue
            item_id = _item_id(
                "action",
                [_text_key(owner), _text_key(action_text), _text_key(due_gate)],
            )
            state["actionItems"] = [
                item for item in state["actionItems"] if item.get("itemId") != item_id
            ]
            requested = _clean_text(action.get("status") or "accepted").lower()
            state["actionItems"].append(
                {
                    "itemId": item_id,
                    "ownerRoleId": owner,
                    "action": action_text,
                    "dueGate": due_gate,
                    "status": (
                        requested
                        if requested in {"accepted", "completed", "blocked"}
                        else "accepted"
                    ),
                    "sourceRefs": [digest_ref, *sorted(source_message_refs)],
                }
            )
        state["formalDecisionRefs"] = sorted(
            {
                *state["formalDecisionRefs"],
                *(
                    str(item).strip()
                    for item in list(projection.get("decisionRefs") or [])
                    if str(item).strip()
                ),
            }
        )

    for key in (
        "agreements",
        "disagreements",
        "risks",
        "actionItems",
        "evidenceRequests",
        "knowledgeCandidates",
    ):
        state[key] = sorted(state[key], key=lambda item: str(item.get("itemId") or ""))
    return formal_source_refs


def _hash_material(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "coveredThroughRef": checkpoint.get("coveredThroughRef"),
        "coveredRoundIds": checkpoint.get("coveredRoundIds"),
        "coveredMessageRefs": checkpoint.get("coveredMessageRefs"),
        "state": checkpoint.get("state"),
        "legacyRecap": checkpoint.get("legacyRecap"),
        "sourceDigestRefs": checkpoint.get("sourceDigestRefs"),
        "sourceMessageRefs": checkpoint.get("sourceMessageRefs"),
    }


def build_chat_room_context_checkpoint(
    room: Mapping[str, Any],
    *,
    covered_round_ids: Sequence[str],
    revision: int,
    created_at: str,
    token_stats: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a byte-deterministic checkpoint from selected Room Store rounds."""

    room_id = _room_id(room)
    selected_ids = [str(item).strip() for item in covered_round_ids if str(item).strip()]
    available = _rounds_by_id(room)
    selected_ids = [item for item in selected_ids if item in available]
    state, legacy, source_refs = _reduce_state(room, selected_ids)
    covered_refs: list[str] = []
    for round_id in selected_ids:
        for message in list(available[round_id].get("messages") or []):
            if isinstance(message, Mapping) and _message_id(message):
                covered_refs.append(_message_ref(room_id, round_id, message))

    source_digest_refs = sorted(
        {
            str(item.get("digestRef") or "").strip()
            for item in _formal_context_projections(room)
            if str(item.get("digestRef") or "").strip()
        }
        | {
            str(item).strip()
            for item in list(room.get("sourceDigestRefs") or [])
            if str(item).strip()
        }
    )
    checkpoint: dict[str, Any] = {
        "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
        "kind": CHECKPOINT_KIND,
        "checkpointId": "",
        "roomId": room_id,
        "revision": max(1, int(revision)),
        "participantSetHash": _participants_hash(room),
        "coveredThroughRef": covered_refs[-1] if covered_refs else "",
        "coveredRoundIds": selected_ids,
        "coveredMessageRefs": covered_refs,
        "state": state,
        "legacyRecap": legacy,
        "sourceDigestRefs": source_digest_refs,
        "sourceMessageRefs": sorted(set(source_refs)),
        "contentHash": "",
        "tokenStats": dict(token_stats or {}),
        "createdAt": str(created_at),
    }
    checkpoint["contentHash"] = _sha256(_hash_material(checkpoint))
    checkpoint["checkpointId"] = (
        f"{room_id}:context:{checkpoint['revision']}:{checkpoint['contentHash'][:16]}"
    )
    return checkpoint


def validate_chat_room_context_checkpoint(
    checkpoint: Mapping[str, Any] | None, room: Mapping[str, Any]
) -> dict[str, Any]:
    """Verify identity, exact sources, and the canonical content hash."""

    if not isinstance(checkpoint, Mapping):
        return {"valid": False, "reason": "checkpoint_missing"}
    if checkpoint.get("schemaVersion") != CHECKPOINT_SCHEMA_VERSION:
        return {"valid": False, "reason": "schema_version_invalid"}
    if checkpoint.get("kind") != CHECKPOINT_KIND:
        return {"valid": False, "reason": "kind_invalid"}
    if str(checkpoint.get("roomId") or "") != _room_id(room):
        return {"valid": False, "reason": "room_mismatch"}
    if str(checkpoint.get("participantSetHash") or "") != _participants_hash(room):
        return {"valid": False, "reason": "participant_set_changed"}
    available = _rounds_by_id(room)
    covered_ids = list(checkpoint.get("coveredRoundIds") or [])
    if any(str(item) not in available for item in covered_ids):
        return {"valid": False, "reason": "covered_round_missing"}
    expected = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=[str(item) for item in covered_ids],
        revision=int(checkpoint.get("revision") or 1),
        created_at=str(checkpoint.get("createdAt") or ""),
        token_stats=(
            checkpoint.get("tokenStats")
            if isinstance(checkpoint.get("tokenStats"), Mapping)
            else None
        ),
    )
    if checkpoint.get("contentHash") != expected["contentHash"]:
        return {"valid": False, "reason": "content_hash_mismatch"}
    if list(checkpoint.get("coveredMessageRefs") or []) != expected["coveredMessageRefs"]:
        return {"valid": False, "reason": "covered_message_refs_mismatch"}
    if list(checkpoint.get("sourceMessageRefs") or []) != expected["sourceMessageRefs"]:
        return {"valid": False, "reason": "source_message_refs_mismatch"}
    return {"valid": True, "reason": "ok"}


def _messages_for_rounds(
    rounds: Sequence[Mapping[str, Any]], round_ids: set[str]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for round_payload in rounds:
        if _round_id(round_payload) not in round_ids:
            continue
        result.extend(
            copy.deepcopy(message)
            for message in list(round_payload.get("messages") or [])
            if isinstance(message, Mapping)
        )
    return result


def maybe_rotate_chat_room_context_checkpoint(
    room: Mapping[str, Any],
    *,
    previous_checkpoint: Mapping[str, Any] | None,
    estimate_tokens: Callable[[Sequence[Any]], int],
    token_threshold: int = DEFAULT_DYNAMIC_TOKEN_THRESHOLD,
    verbatim_rounds: int = DEFAULT_VERBATIM_ROUNDS,
    created_at: str,
    force_reason: str | None = None,
) -> dict[str, Any]:
    """Rotate only after a terminal boundary or an explicit semantic event."""

    rounds = _terminal_rounds(room)
    previous_validation = validate_chat_room_context_checkpoint(previous_checkpoint, room)
    previous_valid = bool(previous_validation["valid"])
    covered_before = (
        {str(item) for item in list(previous_checkpoint.get("coveredRoundIds") or [])}
        if previous_valid and previous_checkpoint is not None
        else set()
    )
    dynamic_messages = _messages_for_rounds(
        rounds, {_round_id(item) for item in rounds} - covered_before
    )
    before_tokens = max(0, int(estimate_tokens(dynamic_messages)))
    semantic_rotation = bool(force_reason) or (
        previous_checkpoint is not None
        and previous_validation.get("reason") == "participant_set_changed"
    )
    if previous_valid and before_tokens <= token_threshold and not semantic_rotation:
        return {
            "checkpoint": copy.deepcopy(previous_checkpoint),
            "rotated": False,
            "reason": "within_threshold",
            "recentWindowBudgetExceeded": False,
            "dynamicTokens": before_tokens,
        }
    if previous_checkpoint is None and before_tokens <= token_threshold and not semantic_rotation:
        return {
            "checkpoint": None,
            "rotated": False,
            "reason": "within_threshold",
            "recentWindowBudgetExceeded": False,
            "dynamicTokens": before_tokens,
        }

    keep_count = max(0, int(verbatim_rounds))
    coverable = rounds[:-keep_count] if keep_count else rounds
    covered_ids = [_round_id(item) for item in coverable]
    recent_ids = {_round_id(item) for item in rounds[-keep_count:]} if keep_count else set()
    after_messages = _messages_for_rounds(rounds, recent_ids)
    after_tokens = max(0, int(estimate_tokens(after_messages)))
    revision = int(previous_checkpoint.get("revision") or 0) + 1 if previous_checkpoint else 1
    checkpoint = build_chat_room_context_checkpoint(
        room,
        covered_round_ids=covered_ids,
        revision=revision,
        created_at=created_at,
        token_stats={"before": before_tokens, "after": after_tokens},
    )
    return {
        "checkpoint": checkpoint,
        "rotated": True,
        "reason": force_reason or (
            "participant_set_changed"
            if previous_validation.get("reason") == "participant_set_changed"
            else "dynamic_threshold_exceeded"
        ),
        "recentWindowBudgetExceeded": after_tokens > token_threshold,
        "dynamicTokens": after_tokens,
    }


def _checkpoint_prompt_value(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": checkpoint.get("schemaVersion"),
        "kind": checkpoint.get("kind"),
        "checkpointId": checkpoint.get("checkpointId"),
        "roomId": checkpoint.get("roomId"),
        "revision": checkpoint.get("revision"),
        "coveredThroughRef": checkpoint.get("coveredThroughRef"),
        "coveredRoundIds": checkpoint.get("coveredRoundIds"),
        "state": checkpoint.get("state"),
        "legacyRecap": checkpoint.get("legacyRecap"),
        "sourceDigestRefs": checkpoint.get("sourceDigestRefs"),
        "sourceMessageRefs": checkpoint.get("sourceMessageRefs"),
        "contentHash": checkpoint.get("contentHash"),
    }


def _projection_message(
    *, kind: str, payload: Mapping[str, Any], cache_marker: bool
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "text",
        "text": _canonical_json(payload),
    }
    if cache_marker:
        block["cache_control"] = {"type": "ephemeral"}
    return {
        "role": "assistant",
        "content": [block],
        "metadata": {"kind": kind},
    }


def build_chat_room_context_snapshot(
    room: Mapping[str, Any],
    *,
    checkpoint: Mapping[str, Any] | None,
    verbatim_rounds: int = DEFAULT_VERBATIM_ROUNDS,
) -> dict[str, Any]:
    """Build the immutable room-wide projection once for all round speakers."""

    validation = validate_chat_room_context_checkpoint(checkpoint, room)
    checkpoint_valid = bool(validation["valid"])
    checkpoint_rebuilt = False
    active_checkpoint: Mapping[str, Any] | None = checkpoint
    if checkpoint is not None and not checkpoint_valid:
        active_checkpoint = build_chat_room_context_checkpoint(
            room,
            covered_round_ids=[str(item) for item in list(checkpoint.get("coveredRoundIds") or [])],
            revision=int(checkpoint.get("revision") or 1),
            created_at=str(checkpoint.get("createdAt") or "rebuilt"),
            token_stats=(
                checkpoint.get("tokenStats")
                if isinstance(checkpoint.get("tokenStats"), Mapping)
                else None
            ),
        )
        checkpoint_rebuilt = True

    terminal = _terminal_rounds(room)
    keep_count = max(0, int(verbatim_rounds))
    recent_round_ids = [_round_id(item) for item in terminal[-keep_count:]] if keep_count else []
    covered_ids = (
        {str(item) for item in list(active_checkpoint.get("coveredRoundIds") or [])}
        if active_checkpoint is not None
        else set()
    )
    recent_id_set = set(recent_round_ids)
    delta_ids = [
        _round_id(item)
        for item in terminal
        if _round_id(item) not in covered_ids and _round_id(item) not in recent_id_set
    ]
    delta_checkpoint = (
        build_chat_room_context_checkpoint(
            room,
            covered_round_ids=delta_ids,
            revision=1,
            created_at="delta",
        )
        if delta_ids
        else None
    )
    checkpoint_message = (
        _projection_message(
            kind="chat_room_context_checkpoint",
            payload=_checkpoint_prompt_value(active_checkpoint),
            cache_marker=True,
        )
        if active_checkpoint is not None
        else None
    )
    delta_message = (
        _projection_message(
            kind="chat_room_context_delta",
            payload={
                "schemaVersion": 1,
                "kind": "ChatRoomContextDelta.v1",
                "roundIds": delta_ids,
                "state": delta_checkpoint["state"],
                "legacyRecap": delta_checkpoint["legacyRecap"],
                "sourceMessageRefs": delta_checkpoint["sourceMessageRefs"],
            },
            cache_marker=False,
        )
        if delta_checkpoint is not None
        else None
    )
    return {
        "schemaVersion": 1,
        "kind": "ChatRoomContextSnapshot.v1",
        "roomId": _room_id(room),
        "checkpoint": copy.deepcopy(active_checkpoint),
        "checkpointMessage": checkpoint_message,
        "deltaMessage": delta_message,
        "coveredRoundIds": sorted(covered_ids),
        "deltaRoundIds": delta_ids,
        "recentRoundIds": recent_round_ids,
        "checkpointValid": checkpoint_valid,
        "checkpointRebuilt": checkpoint_rebuilt,
        "checkpointValidationReason": validation["reason"],
    }


def apply_chat_room_context_snapshot(
    history: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply one precomputed room snapshot to a participant's own history."""

    if snapshot.get("kind") != "ChatRoomContextSnapshot.v1":
        raise ValueError("invalid chat room context snapshot")
    room_id = str(snapshot.get("roomId") or "").strip()
    replace_ids = {
        str(item)
        for item in [
            *list(snapshot.get("coveredRoundIds") or []),
            *list(snapshot.get("deltaRoundIds") or []),
        ]
    }
    copied_history = [copy.deepcopy(dict(item)) for item in history]
    insertion_index: int | None = None
    retained: list[dict[str, Any]] = []
    for item in copied_history:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        is_room_transcript = (
            str(metadata.get("kind") or "") == "group_room_transcript"
            and str(metadata.get("sourceRoomId") or "") == room_id
        )
        source_round_id = str(metadata.get("sourceRoundId") or "")
        if is_room_transcript and insertion_index is None:
            insertion_index = len(retained)
        if is_room_transcript and source_round_id in replace_ids:
            continue
        retained.append(item)
    if insertion_index is None:
        insertion_index = len(retained)
    inserts = [
        copy.deepcopy(message)
        for message in (snapshot.get("checkpointMessage"), snapshot.get("deltaMessage"))
        if isinstance(message, Mapping)
    ]
    projected = retained[:insertion_index] + inserts + retained[insertion_index:]
    return projected, {
        "checkpointValid": bool(snapshot.get("checkpointValid")),
        "checkpointRebuilt": bool(snapshot.get("checkpointRebuilt")),
        "checkpointValidationReason": str(snapshot.get("checkpointValidationReason") or ""),
        "recentRoundIds": list(snapshot.get("recentRoundIds") or []),
        "deltaRoundIds": list(snapshot.get("deltaRoundIds") or []),
    }


def apply_chat_room_context_projection(
    history: Sequence[Mapping[str, Any]],
    *,
    room: Mapping[str, Any],
    checkpoint: Mapping[str, Any] | None,
    verbatim_rounds: int = DEFAULT_VERBATIM_ROUNDS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replace covered history with checkpoint/delta while preserving raw tail."""

    snapshot = build_chat_room_context_snapshot(
        room,
        checkpoint=checkpoint,
        verbatim_rounds=verbatim_rounds,
    )
    return apply_chat_room_context_snapshot(history, snapshot)


def resolve_chat_room_context_refs(
    room: Mapping[str, Any],
    refs: Sequence[str],
    *,
    max_refs: int = DEFAULT_REF_LIMIT,
    max_bytes: int = DEFAULT_REF_BYTES,
) -> list[dict[str, Any]]:
    """Resolve exact message refs inside the current room without truncation."""

    if len(refs) > max_refs:
        raise ChatRoomContextRefError(f"at most {max_refs} references are allowed")
    room_id = _room_id(room)
    index: dict[str, Mapping[str, Any]] = {}
    for round_payload in list(room.get("rounds") or []):
        if not isinstance(round_payload, Mapping):
            continue
        round_id = _round_id(round_payload)
        for message in list(round_payload.get("messages") or []):
            if isinstance(message, Mapping) and _message_id(message):
                index[_message_ref(room_id, round_id, message)] = message

    result: list[dict[str, Any]] = []
    for raw_ref in refs:
        ref = str(raw_ref or "").strip()
        parts = ref.split("/")
        if len(parts) != 3:
            raise ChatRoomContextRefError(f"invalid chat room context ref: {ref}")
        if parts[0] != room_id:
            raise ChatRoomContextRefError(f"reference is outside current room: {ref}")
        message = index.get(ref)
        if message is None:
            raise ChatRoomContextRefError(f"reference does not exist in current room: {ref}")
        content = str(message.get("content") or "")
        result.append(
            {
                "ref": ref,
                "content": content,
                "speaker": str(message.get("speakerTitle") or _speaker_id(message)),
                "timestamp": str(message.get("timestamp") or ""),
                "contentHash": _sha256(content),
            }
        )
    encoded = _canonical_json(result).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ChatRoomContextRefError(
            "resolved chat room context exceeds 32768 bytes "
            f"(configured limit: {max_bytes} bytes); narrow the reference set"
        )
    return result


__all__ = [
    "CHECKPOINT_KIND",
    "CHECKPOINT_SCHEMA_VERSION",
    "DEFAULT_DYNAMIC_TOKEN_THRESHOLD",
    "DEFAULT_REF_BYTES",
    "DEFAULT_REF_LIMIT",
    "DEFAULT_VERBATIM_ROUNDS",
    "ChatRoomContextRefError",
    "apply_chat_room_context_projection",
    "apply_chat_room_context_snapshot",
    "build_chat_room_context_checkpoint",
    "build_chat_room_context_snapshot",
    "maybe_rotate_chat_room_context_checkpoint",
    "resolve_chat_room_context_refs",
    "validate_chat_room_context_checkpoint",
]
