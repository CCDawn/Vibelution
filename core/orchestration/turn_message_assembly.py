# -*- coding: utf-8 -*-
"""Turn message sequencing. Prompt policy stays in prompt_manager / context_engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from langchain_core.messages import SystemMessage

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
    for raw_call in list(raw_calls or []):
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
    if role.strip().lower() != "assistant":
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
    pending_volatile_context_blocks = [str(block) for block in list(pending_blocks or [])]
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
    pending_static = [str(block) for block in list(static_context_blocks or [])]
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
    pending_runtime = [str(block) for block in list(runtime_context_blocks or [])]
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
    pending_static = [str(block) for block in list(static_context_blocks or [])]
    if pending_static and updated:
        extend = extend_cacheable_prefix_fn or _default_extend_cacheable_prefix()
        merged_message, cacheable_prefix_merged = extend(updated[0], pending_static)
        if cacheable_prefix_merged:
            updated[0] = merged_message
    return updated
