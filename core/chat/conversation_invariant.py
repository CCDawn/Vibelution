# -*- coding: utf-8 -*-
"""Conversation-layer invariant: model-visible dialogue must reconstruct from the ledger.

System layers (runtime context, Turn Status Bar, skills) are labeled and excluded.
Silent provider tool-chain repair at send time is fail-closed; persist a ledger
event first instead of inventing model-visible prose.

Physical JSONL rewrite is an explicit exception, not the default append path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.context.volatility import is_volatile_context_text

from .conversation_ledger import (
    ConversationLedgerEvent,
    apply_context_compression_checkpoints,
    conversation_model_messages_from_events,
)

CONVERSATION_ROLES = frozenset({"user", "assistant", "tool"})
SYSTEM_LAYER_ROLES = frozenset({"system", "runtime", "runtime_context"})
SILENT_PROVIDER_REPAIR_ERROR = "silent_provider_tool_chain_repair"
LEDGER_FINGERPRINT_MISMATCH_ERROR = "ledger_conversation_fingerprint_mismatch"
FORBIDDEN_UI_TOOL_CALLS_ERROR = "ui_tool_calls_field"
LEDGER_REWRITE_EXCEPTION_OWNERS = (
    "session.runtime_glue._truncate_session_ledger_before_message",
    "chat_room_service group transcript cleanup",
)


@dataclass(frozen=True)
class ConversationPayloadInvariantResult:
    ok: bool
    error_type: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def historical_conversation_events(
    events: Iterable[ConversationLedgerEvent],
    *,
    current_turn_id: str = "",
) -> list[ConversationLedgerEvent]:
    """Drop the in-flight turn so seed history does not include the current request."""

    normalized_current_turn_id = str(current_turn_id or "").strip()
    event_list = list(events or [])
    if not normalized_current_turn_id:
        return event_list
    return [
        event
        for event in event_list
        if str(getattr(event, "turn_id", "") or "").strip() != normalized_current_turn_id
    ]


def canonical_conversation_messages_from_events(
    events: Iterable[ConversationLedgerEvent],
    *,
    current_turn_id: str = "",
) -> list[dict[str, Any]]:
    """Rebuild the conversation layer from ledger events.

    Declared transforms: exclude ``current_turn_id``, then apply compression
    checkpoints. Inbox compaction and live tool-result truncation are not
    applied here.
    """

    historical = historical_conversation_events(events, current_turn_id=current_turn_id)
    replayed = apply_context_compression_checkpoints(
        historical,
        current_turn_id=current_turn_id,
    )
    return conversation_layer_messages(conversation_model_messages_from_events(replayed))


def live_conversation_messages_from_events(
    events: Iterable[ConversationLedgerEvent],
    *,
    turn_id: str = "",
) -> list[dict[str, Any]]:
    """Rebuild conversation layer including the in-flight turn.

    Unlike ``canonical_conversation_messages_from_events``, this does not drop
    ``turn_id``. When ``turn_id`` is set, only that turn's reconstructed
    conversation messages are returned so callers can splice them onto an
    already assembled system/history prefix.
    """

    normalized_turn_id = str(turn_id or "").strip()
    event_list = list(events or [])
    if normalized_turn_id:
        event_list = [
            event
            for event in event_list
            if str(getattr(event, "turn_id", "") or "").strip() == normalized_turn_id
        ]
    replayed = apply_context_compression_checkpoints(
        event_list,
        current_turn_id=normalized_turn_id,
    )
    return conversation_layer_messages(conversation_model_messages_from_events(replayed))


def is_system_layer_message(message: Any) -> bool:
    role = _message_role(message)
    if role in SYSTEM_LAYER_ROLES:
        return True
    return is_volatile_context_text(_message_text(message))


def conversation_layer_messages(messages: Iterable[Any]) -> list[Any]:
    layer: list[Any] = []
    for message in list(messages or []):
        role = _message_role(message)
        if role not in CONVERSATION_ROLES:
            continue
        if is_system_layer_message(message):
            continue
        layer.append(message)
    return layer


def conversation_layer_fingerprint(messages: Iterable[Any]) -> str:
    normalized: list[dict[str, Any]] = []
    for message in conversation_layer_messages(messages):
        item: dict[str, Any] = {
            "role": _message_role(message),
            "content": _message_text(message),
        }
        tool_call_ids = _message_tool_call_ids(message)
        if tool_call_ids:
            item["toolCallIds"] = tool_call_ids
        tool_call_id = _message_tool_call_id(message)
        if tool_call_id:
            item["toolCallId"] = tool_call_id
        normalized.append(item)
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def check_conversation_payload_invariant(
    messages: Iterable[Any],
    *,
    expected_fingerprint: str = "",
) -> ConversationPayloadInvariantResult:
    """Return whether conversation-layer messages may be sent to a provider."""

    materialized = list(messages or [])
    ui_index = _ui_tool_calls_index(materialized)
    if ui_index >= 0:
        return ConversationPayloadInvariantResult(
            ok=False,
            error_type=FORBIDDEN_UI_TOOL_CALLS_ERROR,
            message=(
                "UI field `toolCalls` is not allowed in model input. "
                "Build model context from ConversationLedger ModelProjection first."
            ),
            details={"messageIndex": ui_index, "forbiddenField": "toolCalls"},
        )
    repair_index = _silent_tool_chain_repair_index(materialized)
    if repair_index >= 0:
        return ConversationPayloadInvariantResult(
            ok=False,
            error_type=SILENT_PROVIDER_REPAIR_ERROR,
            message=(
                "Silent provider tool-chain repair is not allowed at model send. "
                "Persist a ConversationLedger event first."
            ),
            details={"messageIndex": repair_index, "providerChainRepaired": True},
        )
    normalized_expected = str(expected_fingerprint or "").strip()
    if normalized_expected:
        actual = conversation_layer_fingerprint(materialized)
        if actual != normalized_expected:
            return ConversationPayloadInvariantResult(
                ok=False,
                error_type=LEDGER_FINGERPRINT_MISMATCH_ERROR,
                message="Conversation-layer payload does not match the ledger reconstruction fingerprint.",
                details={
                    "expectedFingerprint": normalized_expected,
                    "actualFingerprint": actual,
                },
            )
    return ConversationPayloadInvariantResult(ok=True)


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        role = str(message.get("role") or "").strip().lower()
    else:
        role = str(getattr(message, "type", "") or getattr(message, "role", "") or "").strip().lower()
    if role in {"ai", "assistant"}:
        return "assistant"
    if role in {"human", "user"}:
        return "user"
    return role


def _message_text(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item or ""))
        return "".join(parts)
    return str(content or "")


def _message_tool_call_ids(message: Any) -> list[str]:
    raw_calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
    if not isinstance(raw_calls, list):
        return []
    ids: list[str] = []
    for index, item in enumerate(raw_calls):
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        tool_call_id = str(item.get("id") or item.get("toolCallId") or function.get("id") or "").strip()
        if tool_call_id:
            ids.append(tool_call_id)
        elif str(item.get("name") or function.get("name") or "").strip():
            ids.append(f"tool_{index}")
    return ids


def _message_tool_call_id(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("tool_call_id") or message.get("toolCallId") or "").strip()
    return str(getattr(message, "tool_call_id", "") or "").strip()


def _ui_tool_calls_index(messages: list[Any]) -> int:
    for index, message in enumerate(messages):
        if isinstance(message, dict) and "toolCalls" in message:
            return index
    return -1


_SILENT_REPAIR_KINDS = frozenset(
    {
        "historical_orphan_tool_result",
        "historical_unresolved_tool_call",
    }
)


def _message_metadata(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        metadata = message.get("metadata")
        return dict(metadata) if isinstance(metadata, dict) else {}
    metadata = getattr(message, "additional_kwargs", None)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _silent_tool_chain_repair_index(messages: list[Any]) -> int:
    for index, message in enumerate(messages):
        metadata = _message_metadata(message)
        if metadata.get("repairedProviderToolChain") is True:
            return index
        if str(metadata.get("kind") or "").strip() in _SILENT_REPAIR_KINDS:
            return index
    return -1
