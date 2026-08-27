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


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _as_mapping(value: Any) -> Dict[str, Any]:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _mapping_get(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _coerce_message_list(value: Any) -> list:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("messages")
        if nested is None:
            nested = value.get("items")
        if nested is None:
            nested = value.get("history")
        if nested is not None:
            return _coerce_message_list(nested)
        if any(key in value for key in ("role", "content", "type", "tool_calls", "toolCalls")):
            return [dict(value)]
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _coerce_text_blocks(value: Any) -> list[str]:
    value = _maybe_json(value)
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Mapping):
        return []
    try:
        blocks = list(value)
    except TypeError:
        text = _coerce_text(value)
        return [text] if text else []
    return [_coerce_text(block) for block in blocks if _coerce_text(block) or block == ""]


def _seeded_call_items(raw_calls: Any) -> list:
    raw_calls = _maybe_json(raw_calls)
    if raw_calls is None or isinstance(raw_calls, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(raw_calls, Mapping):
        nested = raw_calls.get("tool_calls")
        if nested is None:
            nested = raw_calls.get("toolCalls")
        if nested is not None:
            return _seeded_call_items(nested)
        return [dict(raw_calls)] if raw_calls else []
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
        if not isinstance(raw_call, Mapping):
            continue
        function = _as_mapping(_mapping_get(raw_call, "function"))
        call_id = _coerce_text(
            _mapping_get(raw_call, "id", "tool_call_id", "toolCallId")
        ).strip()
        name = _coerce_text(
            _mapping_get(raw_call, "name", "toolName") or _mapping_get(function, "name")
        ).strip()
        arguments = _mapping_get(raw_call, "args", "arguments")
        if arguments is None:
            arguments = _mapping_get(function, "arguments", "args")
        if arguments is None:
            arguments = {}
        if isinstance(arguments, (bytes, bytearray, memoryview, str)):
            parsed_arguments = _maybe_json(arguments)
            if parsed_arguments is arguments and isinstance(arguments, str):
                try:
                    parsed_arguments = json.loads(arguments)
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_arguments = {"raw": arguments}
            arguments = parsed_arguments
        arguments = _as_mapping(arguments)
        if call_id and name:
            normalized.append({"id": call_id, "name": name, "args": arguments})
    return normalized


def sanitize_seeded_chat_content(role: str, content: str) -> str:
    text = _coerce_text(content)
    normalized_role = _coerce_text(role).strip().lower()
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
        return _coerce_message_list(messages), []
    context_messages = [
        SystemMessage(content=block)
        for block in pending_volatile_context_blocks
        if _coerce_text(block).strip()
    ]
    if not context_messages:
        return _coerce_message_list(messages), []
    insert = insert_volatile_fn or _default_insert_volatile()
    return (
        insert(
            messages=list(_coerce_message_list(messages)),
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
        user_prompt=_coerce_text(user_prompt),
        effective_goal=_coerce_text(effective_goal),
        active_turn_messages=(
            _coerce_message_list(active_turn_messages)
            if active_turn_messages is not None
            else None
        ),
        active_turn_goal=_coerce_text(active_turn_goal),
        build_system_message=build_system_message,
        build_external_request_message=build_external_request_message,
        allow_append_user_message=_coerce_bool(allow_append_user_message, False),
    )
    pending_static = _coerce_text_blocks(static_context_blocks)
    cacheable_prefix_merged = False
    static_context_inserted = bool(pending_static)
    if pending_static:
        extend = extend_cacheable_prefix_fn or _default_extend_cacheable_prefix()
        if messages:
            merged_message, cacheable_prefix_merged = extend(messages[0], pending_static)
            cacheable_prefix_merged = _coerce_bool(cacheable_prefix_merged, False)
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
        resumed=_coerce_bool(resumed, False),
        static_context_inserted=static_context_inserted,
        cacheable_prefix_merged=_coerce_bool(cacheable_prefix_merged, False),
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
    updated = _coerce_message_list(messages)
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
        if _coerce_bool(cacheable_prefix_merged, False):
            updated[0] = merged_message
    return updated


def _message_role_name(message: Any) -> str:
    if isinstance(message, Mapping):
        role = _coerce_text(_mapping_get(message, "role", "type", "kind")).strip().lower()
    else:
        role = _coerce_text(getattr(message, "type", "") or getattr(message, "role", "")).strip().lower()
    if role in {"ai", "assistant"}:
        return "assistant"
    if role in {"human", "user"}:
        return "user"
    return role


def langchain_messages_from_conversation_layer(messages: Iterable[Any]) -> list:
    """Project ledger conversation-layer dicts into LangChain/provider messages."""

    restored: list = []
    for item in _coerce_message_list(messages):
        if not isinstance(item, Mapping):
            restored.append(item)
            continue
        role = _message_role_name(item)
        assistant_tool_calls = (
            normalize_seeded_tool_calls(
                _mapping_get(item, "tool_calls", "toolCalls") or []
            )
            if role == "assistant"
            else []
        )
        raw_content = _mapping_get(item, "content")
        content = raw_content if isinstance(raw_content, list) else _coerce_text(raw_content).strip()
        if isinstance(content, str):
            content = sanitize_seeded_chat_content(role, content)
        if not content and not assistant_tool_calls and role != "tool":
            continue
        if role in {"runtime_context", "runtime", "system"}:
            restored.append(SystemMessage(content=_coerce_text(content)))
        elif role == "user":
            restored.append({"role": "user", "content": content})
        elif role == "assistant":
            restored.append(AIMessage(content=_coerce_text(content), tool_calls=assistant_tool_calls))
        elif role == "tool":
            tool_call_id = _coerce_text(_mapping_get(item, "tool_call_id", "toolCallId")).strip()
            if tool_call_id:
                restored.append(ToolMessage(content=_coerce_text(content), tool_call_id=tool_call_id))
    return restored


def _message_continuation_identity(message: Any) -> tuple[str, str, tuple[str, ...]]:
    """Stable identity for matching an in-memory message against a ledger item."""

    if isinstance(message, Mapping):
        content = _coerce_text(_mapping_get(message, "content", "")).strip()
        raw_calls = _mapping_get(message, "tool_calls", "toolCalls") or []
    else:
        raw_content = getattr(message, "content", "")
        content = _coerce_text(raw_content if isinstance(raw_content, str) else "").strip()
        raw_calls = getattr(message, "tool_calls", None) or []
    call_ids = tuple(
        _coerce_text(
            _mapping_get(call, "id", "tool_call_id", "toolCallId")
            if isinstance(call, Mapping)
            else getattr(call, "id", "")
        ).strip()
        for call in normalize_seeded_tool_calls(list(raw_calls) or [])
    )
    return (_message_role_name(message), content, call_ids)


def splice_current_turn_conversation(
    messages: Sequence[Any] | None,
    current_turn_layer: Sequence[Any] | None,
) -> list:
    """Keep assembled prefix/current user; replace this turn's assistant/tool suffix."""

    from core.orchestration.turn_status_bar import strip_turn_status_bar_messages

    stripped = strip_turn_status_bar_messages(_coerce_message_list(messages))
    continuation = [
        item
        for item in _coerce_message_list(current_turn_layer)
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
    # A same-turn continuation (internal auto-continue) still carries this
    # turn's in-memory assistant/tool run in front of the continuation user
    # message.  Appending the ledger layer would double-count that run and
    # fail the projector's duplicate-tool-call invariant, so drop the run
    # only when it pairwise-matches the ledger continuation prefix; history
    # from earlier turns never matches and stays untouched.
    run_start = last_user
    while run_start > 0 and _message_role_name(stripped[run_start - 1]) in {"assistant", "tool"}:
        run_start -= 1
    stale_run = stripped[run_start:last_user]
    if stale_run and len(stale_run) <= len(continuation) and all(
        _message_continuation_identity(memory_item) == _message_continuation_identity(ledger_item)
        for memory_item, ledger_item in zip(stale_run, continuation)
    ):
        return stripped[:run_start] + continuation + stripped[last_user:]
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
        self.error_type = _coerce_text(error_type).strip() or "turn_journal_replay_failed"
        self.message = _coerce_text(message).strip() or "Current-turn journal replay failed."
        self.details = _as_mapping(details)


def current_turn_has_journal_conversation_layer(events: Iterable[Any], *, turn_id: str) -> bool:
    from core.chat.conversation_invariant import live_conversation_messages_from_events

    layer = live_conversation_messages_from_events(
        _coerce_message_list(events),
        turn_id=_coerce_text(turn_id).strip(),
    )
    return any(_message_role_name(item) in {"assistant", "tool"} for item in layer)


def ledger_conversation_fingerprint_for_messages(messages: Sequence[Any] | None) -> str:
    """Fingerprint for send-time ledger reconciliation (matches LLMClient invariant)."""

    from core.chat.conversation_invariant import conversation_layer_fingerprint
    from core.chat.model_messages import ProviderMessageChain

    provider_messages = ProviderMessageChain.from_messages(_coerce_message_list(messages)).to_provider_payload()
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

    materialized = _coerce_message_list(messages)
    event_list = _coerce_message_list(events)
    layer = live_conversation_messages_from_events(
        event_list,
        turn_id=_coerce_text(turn_id).strip(),
    )
    if not any(_message_role_name(item) in {"assistant", "tool"} for item in layer):
        if _coerce_bool(require_layer, False) and _coerce_bool(strict, False):
            raise TurnJournalReplayError(
                error_type="journal_layer_missing",
                message="Current turn has no reconstructable assistant/tool layer in ConversationLedger.",
                details={"turnId": _coerce_text(turn_id).strip()},
            )
        return materialized
    invariant = check_conversation_payload_invariant(layer)
    if not invariant.ok:
        if _coerce_bool(strict, False):
            raise TurnJournalReplayError(
                error_type=_coerce_text(invariant.error_type or "conversation_invariant_failed"),
                message=_coerce_text(invariant.message or "Current-turn journal replay failed invariant check."),
                details={
                    "turnId": _coerce_text(turn_id).strip(),
                    **_as_mapping(invariant.details),
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

    materialized = _coerce_message_list(messages)
    event_list = _coerce_message_list(events)
    normalized_turn_id = _coerce_text(turn_id).strip()
    if current_turn_has_journal_conversation_layer(event_list, turn_id=normalized_turn_id):
        return replay_current_turn_messages(
            materialized,
            event_list,
            turn_id=normalized_turn_id,
            strict=strict,
            require_layer=True,
        )

    if not _coerce_bool(strict, True):
        return materialized

    historical = canonical_conversation_messages_from_events(
        event_list,
        current_turn_id=normalized_turn_id,
    )
    layer = conversation_layer_messages(materialized)
    history_layer = layer[:-1] if layer and _message_role_name(layer[-1]) == "user" else layer

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


def ledger_seeded_history_fingerprint(
    events: Iterable[Any],
    *,
    turn_id: str,
) -> str:
    """Fingerprint of the canonical seeded history for ``turn_id``.

    This is the provenance stamp of a ledger-assembled chat seed: the producer
    (session worker) stamps it when assembling history from the ledger, and the
    send-time gate recomputes it from the live ledger to prove the seed was
    derived from exactly this ledger state — windowing and compaction applied
    afterwards by the context assembler are deliberate transforms and are not
    required to reproduce the canonical replay verbatim.
    """

    from core.chat.conversation_invariant import (
        canonical_conversation_messages_from_events,
    )

    event_list = _coerce_message_list(events)
    normalized_turn_id = _coerce_text(turn_id).strip()
    historical = canonical_conversation_messages_from_events(
        event_list,
        current_turn_id=normalized_turn_id,
    )
    return _chat_seeded_history_fingerprint(historical)


def _chat_seeded_history_fingerprint(items: Sequence[Any]) -> str:
    from core.chat.conversation_invariant import conversation_layer_fingerprint
    from core.infrastructure.runtime_input import build_chat_user_message

    projected: list[Any] = []
    for item in items:
        if isinstance(item, Mapping):
            role = _coerce_text(item.get("role")).strip().lower()
            if role == "user":
                content = item.get("content")
                if isinstance(content, list):
                    projected.append({"role": "user", "content": content})
                else:
                    projected.append(build_chat_user_message(_coerce_text(content)))
                continue
            projected.append(dict(item))
            continue
        role = _message_role_name(item)
        if role == "user":
            projected.append(build_chat_user_message(_coerce_text(getattr(item, "content", ""))))
        else:
            projected.append(item)
    return conversation_layer_fingerprint(projected)
