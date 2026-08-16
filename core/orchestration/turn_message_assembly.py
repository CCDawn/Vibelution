# -*- coding: utf-8 -*-
"""Turn message sequencing. Prompt policy stays in prompt_manager / context_engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from core.orchestration.agent_runtime_bindings import (
    _INTERNAL_TOOL_PROTOCOL_MARKERS,
    _TOOL_POLICY_FAILURE_RE,
)


PrepareTurnMessagesFn = Callable[..., tuple[list, bool]]
InsertContextFn = Callable[..., list]
ExtendCacheablePrefixFn = Callable[[Any, Any], tuple[Any, bool]]
BuildMessageFn = Callable[[Any], Any]
IsDynamicContextFn = Callable[[Any], bool]

SEEDED_TOOL_POLICY_OMISSION = "[工具策略提示] 历史中有一次未授权工具调用已被省略。"


def _coerce_text_blocks(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return []
    try:
        return [str(block) for block in list(value)]
    except TypeError:
        return [str(value)]


def _seeded_call_items(raw_calls: Any) -> list:
    if isinstance(raw_calls, Mapping):
        return [dict(raw_calls)]
    if isinstance(raw_calls, (str, bytes)) or raw_calls in (None, ""):
        return []
    try:
        return list(raw_calls)
    except TypeError:
        return []


@dataclass(frozen=True)
class AssembledTurnMessages:
    messages: list
    resumed: bool
    static_context_inserted: bool
    cacheable_prefix_merged: bool
    static_context_blocks: tuple[str, ...]
    pending_runtime_context_blocks: tuple[str, ...]
    dynamic_system_context_inserted: bool


def normalize_seeded_tool_calls(raw_calls: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for raw_call in _seeded_call_items(raw_calls):
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
        call_id = str(
            raw_call.get("id")
            or raw_call.get("tool_call_id")
            or raw_call.get("toolCallId")
            or ""
        ).strip()
        name = str(
            raw_call.get("name")
            or raw_call.get("toolName")
            or function.get("name")
            or ""
        ).strip()
        arguments = raw_call.get("args", raw_call.get("arguments", function.get("arguments", {})))
        if isinstance(arguments, str):
            try:
                parsed_arguments = json.loads(arguments)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed_arguments = {"raw": arguments}
            arguments = parsed_arguments if isinstance(parsed_arguments, dict) else {"value": parsed_arguments}
        if not isinstance(arguments, dict):
            arguments = {}
        if call_id and name:
            normalized.append({"id": call_id, "name": name, "args": arguments})
    return normalized


def sanitize_seeded_chat_content(role: str, content: str) -> str:
    text = str(content or "")
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in {"assistant", "ai"}:
        return text
    for marker in _INTERNAL_TOOL_PROTOCOL_MARKERS:
        if marker in text:
            return ""
    cleaned = _TOOL_POLICY_FAILURE_RE.sub(SEEDED_TOOL_POLICY_OMISSION, text)
    if "Tool failed: spawn_agent_tool" in cleaned:
        return ""
    return cleaned.strip()


def _default_insert_volatile() -> InsertContextFn:
    from core.orchestration.turn_outcome import TurnOutcomeController

    return TurnOutcomeController.insert_volatile_context_before_current_user


def _default_insert_static() -> InsertContextFn:
    from core.orchestration.turn_outcome import TurnOutcomeController

    return TurnOutcomeController.insert_static_context_after_system


def _default_prepare_turn_messages() -> PrepareTurnMessagesFn:
    from core.orchestration.turn_outcome import TurnOutcomeController

    return TurnOutcomeController.prepare_turn_messages


def _default_extend_cacheable_prefix() -> ExtendCacheablePrefixFn:
    from core.infrastructure.llm_utils import extend_system_message_cacheable_prefix

    return extend_system_message_cacheable_prefix


def insert_pending_volatile_context_messages(
    messages: Sequence[Any] | None,
    pending_blocks: Iterable[Any] | None,
    *,
    insert_volatile_fn: InsertContextFn | None = None,
) -> tuple[list, list[str]]:
    pending_volatile_context_blocks = _coerce_text_blocks(pending_blocks)
    if not pending_volatile_context_blocks:
        return list(messages or []), []
    context_messages = [
        SystemMessage(content=block)
        for block in pending_volatile_context_blocks
        if str(block or "").strip()
    ]
    if not context_messages:
        return list(messages or []), []
    insert = insert_volatile_fn or _default_insert_volatile()
    return (
        insert(
            messages=list(messages or []),
            context_messages=context_messages,
        ),
        pending_volatile_context_blocks,
    )


def assemble_prepared_turn_messages(
    *,
    system_prompt: Any,
    user_prompt: str,
    effective_goal: str,
    active_turn_messages: Optional[list],
    active_turn_goal: str,
    build_system_message: BuildMessageFn,
    build_external_request_message: BuildMessageFn,
    allow_append_user_message: bool,
    static_context_blocks: Sequence[str] | None = None,
    runtime_context_blocks: Sequence[str] | None = None,
    dynamic_system_context_message: Any = None,
    prepare_turn_messages_fn: PrepareTurnMessagesFn | None = None,
    insert_static_fn: InsertContextFn | None = None,
    insert_volatile_fn: InsertContextFn | None = None,
    extend_cacheable_prefix_fn: ExtendCacheablePrefixFn | None = None,
) -> AssembledTurnMessages:
    prepare = prepare_turn_messages_fn or _default_prepare_turn_messages()
    messages, resumed = prepare(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        effective_goal=effective_goal,
        active_turn_messages=active_turn_messages,
        active_turn_goal=active_turn_goal,
        build_system_message=build_system_message,
        build_external_request_message=build_external_request_message,
        allow_append_user_message=allow_append_user_message,
    )
    pending_static = _coerce_text_blocks(static_context_blocks)
    cacheable_prefix_merged = False
    static_context_inserted = bool(pending_static)
    if pending_static:
        extend = extend_cacheable_prefix_fn or _default_extend_cacheable_prefix()
        if messages:
            merged_message, cacheable_prefix_merged = extend(messages[0], pending_static)
            if cacheable_prefix_merged:
                messages[0] = merged_message
        if not cacheable_prefix_merged:
            insert_static = insert_static_fn or _default_insert_static()
            messages = insert_static(
                messages=messages,
                context_messages=[SystemMessage(content=block) for block in pending_static],
            )
    pending_runtime = _coerce_text_blocks(runtime_context_blocks)
    volatile_context_messages = []
    if dynamic_system_context_message is not None:
        volatile_context_messages.append(dynamic_system_context_message)
    if pending_runtime:
        volatile_context_messages.extend(SystemMessage(content=block) for block in pending_runtime)
    if volatile_context_messages:
        insert_volatile = insert_volatile_fn or _default_insert_volatile()
        messages = insert_volatile(
            messages=messages,
            context_messages=volatile_context_messages,
        )
    return AssembledTurnMessages(
        messages=messages,
        resumed=bool(resumed),
        static_context_inserted=static_context_inserted,
        cacheable_prefix_merged=bool(cacheable_prefix_merged),
        static_context_blocks=tuple(pending_static),
        pending_runtime_context_blocks=tuple(pending_runtime),
        dynamic_system_context_inserted=dynamic_system_context_message is not None,
    )


def refresh_system_prefix_on_messages(
    *,
    messages: Sequence[Any] | None,
    system_prompt: Any,
    static_context_blocks: Sequence[str] | None = None,
    build_cacheable_prefix_fn: BuildMessageFn,
    is_dynamic_system_context_fn: IsDynamicContextFn,
    build_dynamic_system_context_fn: BuildMessageFn,
    extend_cacheable_prefix_fn: ExtendCacheablePrefixFn | None = None,
    insert_volatile_fn: InsertContextFn | None = None,
) -> list:
    updated = list(messages or [])
    prefix = build_cacheable_prefix_fn(system_prompt)
    if updated:
        updated[0] = prefix
    else:
        updated = [prefix]
    updated = [message for message in updated if not is_dynamic_system_context_fn(message)]
    current_dynamic = build_dynamic_system_context_fn(system_prompt)
    if current_dynamic is not None:
        insert_volatile = insert_volatile_fn or _default_insert_volatile()
        updated = insert_volatile(
            messages=updated,
            context_messages=[current_dynamic],
        )
    pending_static = _coerce_text_blocks(static_context_blocks)
    if pending_static and updated:
        extend = extend_cacheable_prefix_fn or _default_extend_cacheable_prefix()
        merged_message, cacheable_prefix_merged = extend(updated[0], pending_static)
        if cacheable_prefix_merged:
            updated[0] = merged_message
    return updated


def _message_role_name(message: Any) -> str:
    if isinstance(message, dict):
        role = str(message.get("role") or "").strip().lower()
    else:
        role = str(getattr(message, "type", "") or getattr(message, "role", "") or "").strip().lower()
    if role in {"ai", "assistant"}:
        return "assistant"
    if role in {"human", "user"}:
        return "user"
    return role


def langchain_messages_from_conversation_layer(messages: Iterable[Any]) -> list:
    """Project ledger conversation-layer dicts into LangChain/provider messages."""

    restored: list = []
    for item in list(messages or []):
        if not isinstance(item, dict):
            restored.append(item)
            continue
        role = _message_role_name(item)
        assistant_tool_calls = (
            normalize_seeded_tool_calls(item.get("tool_calls") or item.get("toolCalls") or [])
            if role == "assistant"
            else []
        )
        raw_content = item.get("content")
        content = raw_content if isinstance(raw_content, list) else str(raw_content or "").strip()
        if isinstance(content, str):
            content = sanitize_seeded_chat_content(role, content)
        if not content and not assistant_tool_calls and role != "tool":
            continue
        if role in {"runtime_context", "runtime", "system"}:
            restored.append(SystemMessage(content=str(content)))
        elif role == "user":
            restored.append({"role": "user", "content": content})
        elif role == "assistant":
            restored.append(AIMessage(content=str(content), tool_calls=assistant_tool_calls))
        elif role == "tool":
            tool_call_id = str(item.get("tool_call_id") or item.get("toolCallId") or "").strip()
            if tool_call_id:
                restored.append(ToolMessage(content=str(content), tool_call_id=tool_call_id))
    return restored


def splice_current_turn_conversation(
    messages: Sequence[Any] | None,
    current_turn_layer: Sequence[Any] | None,
) -> list:
    """Keep assembled prefix/current user; replace this turn's assistant/tool suffix."""

    from core.orchestration.turn_status_bar import strip_turn_status_bar_messages

    stripped = strip_turn_status_bar_messages(list(messages or []))
    continuation = [
        item
        for item in list(current_turn_layer or [])
        if _message_role_name(item) in {"assistant", "tool"}
    ]
    if not continuation:
        return stripped
    last_user = -1
    for index, message in enumerate(stripped):
        if _message_role_name(message) == "user":
            last_user = index
    if last_user < 0:
        return stripped + continuation
    return stripped[: last_user + 1] + continuation


class TurnJournalReplayError(RuntimeError):
    """Raised when chat turn conversation layer cannot be rebuilt from the ledger."""

    def __init__(
        self,
        *,
        error_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = str(error_type or "").strip() or "turn_journal_replay_failed"
        self.message = str(message or "").strip() or "Current-turn journal replay failed."
        self.details = dict(details or {})


def current_turn_has_journal_conversation_layer(events: Iterable[Any], *, turn_id: str) -> bool:
    from core.chat.conversation_invariant import live_conversation_messages_from_events

    layer = live_conversation_messages_from_events(events, turn_id=turn_id)
    return any(_message_role_name(item) in {"assistant", "tool"} for item in layer)


def ledger_conversation_fingerprint_for_messages(messages: Sequence[Any] | None) -> str:
    """Fingerprint for send-time ledger reconciliation (matches LLMClient invariant)."""

    from core.chat.conversation_invariant import conversation_layer_fingerprint
    from core.chat.model_messages import ProviderMessageChain

    provider_messages = ProviderMessageChain.from_messages(list(messages or [])).to_provider_payload()
    return conversation_layer_fingerprint(provider_messages)


def replay_current_turn_messages(
    messages: Sequence[Any] | None,
    events: Iterable[Any],
    *,
    turn_id: str,
    strict: bool = False,
    require_layer: bool = False,
) -> list:
    """Rebuild the in-flight turn's assistant/tool chain from ledger events.

    No-op when the current turn has no model-visible assistant/tool events unless
    ``require_layer`` is true. When ``strict`` is true and the reconstructed
    layer fails the send-time conversation invariant, raise
    ``TurnJournalReplayError`` instead of silently keeping the in-memory chain.
    """

    from core.chat.conversation_invariant import (
        check_conversation_payload_invariant,
        live_conversation_messages_from_events,
    )

    materialized = list(messages or [])
    layer = live_conversation_messages_from_events(events, turn_id=turn_id)
    if not any(_message_role_name(item) in {"assistant", "tool"} for item in layer):
        if require_layer and strict:
            raise TurnJournalReplayError(
                error_type="journal_layer_missing",
                message="Current turn has no reconstructable assistant/tool layer in ConversationLedger.",
                details={"turnId": str(turn_id or "").strip()},
            )
        return materialized
    invariant = check_conversation_payload_invariant(layer)
    if not invariant.ok:
        if strict:
            raise TurnJournalReplayError(
                error_type=str(invariant.error_type or "conversation_invariant_failed"),
                message=str(invariant.message or "Current-turn journal replay failed invariant check."),
                details={
                    "turnId": str(turn_id or "").strip(),
                    **dict(invariant.details or {}),
                },
            )
        return materialized
    return splice_current_turn_conversation(
        materialized,
        langchain_messages_from_conversation_layer(layer),
    )


def reconcile_chat_messages_with_ledger(
    messages: Sequence[Any] | None,
    events: Iterable[Any],
    *,
    turn_id: str,
    strict: bool = True,
) -> list:
    """Align chat turn payload with ConversationLedger before model send.

    When the current turn already has assistant/tool journal events, replay the
    in-flight suffix. Otherwise verify seeded history matches ledger replay.
    """

    from core.chat.conversation_invariant import (
        canonical_conversation_messages_from_events,
        conversation_layer_fingerprint,
        conversation_layer_messages,
    )

    materialized = list(messages or [])
    event_list = list(events or [])
    normalized_turn_id = str(turn_id or "").strip()
    if current_turn_has_journal_conversation_layer(event_list, turn_id=normalized_turn_id):
        return replay_current_turn_messages(
            materialized,
            event_list,
            turn_id=normalized_turn_id,
            strict=strict,
            require_layer=True,
        )

    if not strict:
        return materialized

    historical = canonical_conversation_messages_from_events(
        event_list,
        current_turn_id=normalized_turn_id,
    )
    layer = conversation_layer_messages(materialized)
    history_layer = layer[:-1] if layer and _message_role_name(layer[-1]) == "user" else layer
    from core.infrastructure.runtime_input import build_chat_user_message

    def _chat_seeded_history_fingerprint(items: Sequence[Any]) -> str:
        projected: list[Any] = []
        for item in items:
            if isinstance(item, dict):
                role = str(item.get("role") or "").strip().lower()
                if role == "user":
                    content = item.get("content")
                    if isinstance(content, list):
                        projected.append({"role": "user", "content": content})
                    else:
                        projected.append(build_chat_user_message(str(content or "")))
                    continue
                projected.append(dict(item))
                continue
            role = _message_role_name(item)
            if role == "user":
                projected.append(build_chat_user_message(str(getattr(item, "content", "") or "")))
            else:
                projected.append(item)
        return conversation_layer_fingerprint(projected)

    expected_fingerprint = _chat_seeded_history_fingerprint(historical)
    actual_fingerprint = conversation_layer_fingerprint(history_layer)
    if expected_fingerprint != actual_fingerprint:
        raise TurnJournalReplayError(
            error_type="ledger_history_mismatch",
            message="Seeded chat history does not match ConversationLedger reconstruction.",
            details={
                "turnId": normalized_turn_id,
                "expectedFingerprint": expected_fingerprint,
                "actualFingerprint": actual_fingerprint,
            },
        )
    return materialized
