# -*- coding: utf-8 -*-
"""Validate LLM payloads against selected model protocol policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .protocol_resolver import ResolvedProtocolRoute
from .types import LLMError


@dataclass(frozen=True)
class PayloadValidationResult:
    ok: bool
    error_type: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


def _messages(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    messages = payload.get("messages")
    return [item for item in messages if isinstance(item, dict)] if isinstance(messages, list) else []


def _input_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    input_items = payload.get("input")
    return [item for item in input_items if isinstance(item, dict)] if isinstance(input_items, list) else []


def _conversation_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    messages = _messages(payload)
    return messages if messages else _input_items(payload)


def _role(message: Dict[str, Any]) -> str:
    return str(message.get("role") or "").strip().lower()


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item or ""))
        return "".join(parts)
    return str(value or "")


def _assistant_prefill_detected(messages: List[Dict[str, Any]]) -> bool:
    if not messages:
        return False
    last = messages[-1]
    if _role(last) != "assistant":
        return False
    if last.get("tool_calls"):
        return False
    return bool(_text(last.get("content")).strip() or last.get("reasoning_content"))


def _tool_call_ids(message: Dict[str, Any]) -> list[str]:
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    ids: list[str] = []
    for index, item in enumerate(raw_calls):
        if not isinstance(item, dict):
            continue
        tool_call_id = str(item.get("id") or "").strip() or f"tool_{index}"
        ids.append(tool_call_id)
    return ids


def _content_block_types(items: List[Dict[str, Any]]) -> list[str]:
    block_types: list[str] = []
    for item in list(items or []):
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                block_types.append(str(block.get("type") or "").strip().lower())
    return block_types


def validate_tool_result_pairing(messages: List[Dict[str, Any]]) -> PayloadValidationResult:
    """Validate assistant tool calls and tool-role results before provider send."""

    pending: list[str] = []
    seen_tool_call_ids: set[str] = set()
    seen_tool_result_ids: set[str] = set()
    for index, message in enumerate(messages):
        role = _role(message)
        if role == "assistant":
            if pending:
                return PayloadValidationResult(
                    ok=False,
                    error_type="missing_tool_result",
                    message="Assistant tool call is missing a matching tool result before the next assistant message.",
                    details={"messageIndex": index, "pendingToolCallIds": list(pending)},
                )
            for tool_call_id in _tool_call_ids(message):
                if tool_call_id in seen_tool_call_ids:
                    return PayloadValidationResult(
                        ok=False,
                        error_type="duplicate_tool_call_id",
                        message="Duplicate assistant tool_call id detected before provider send.",
                        details={"messageIndex": index, "toolCallId": tool_call_id},
                    )
                seen_tool_call_ids.add(tool_call_id)
                pending.append(tool_call_id)
            continue
        if role == "tool":
            content = message.get("content")
            if isinstance(content, list):
                # DashScope official merged tool-result message: one tool
                # message whose content blocks each carry a tool_call_id
                # (parallel tool calls merged for the 20-block cache window).
                block_ids: list[str] = []
                for block_index, block in enumerate(content):
                    block_call_id = (
                        str(block.get("tool_call_id") or "").strip()
                        if isinstance(block, dict)
                        else ""
                    )
                    if not block_call_id:
                        return PayloadValidationResult(
                            ok=False,
                            error_type="tool_result_missing_id",
                            message="Merged tool result content block is missing tool_call_id.",
                            details={"messageIndex": index, "blockIndex": block_index},
                        )
                    block_ids.append(block_call_id)
                for block_call_id in block_ids:
                    if block_call_id in seen_tool_result_ids:
                        return PayloadValidationResult(
                            ok=False,
                            error_type="duplicate_tool_result",
                            message="Duplicate tool result detected before provider send.",
                            details={"messageIndex": index, "toolCallId": block_call_id},
                        )
                    if block_call_id not in pending:
                        return PayloadValidationResult(
                            ok=False,
                            error_type="orphan_tool_result",
                            message="Tool result has no pending assistant tool call.",
                            details={
                                "messageIndex": index,
                                "toolCallId": block_call_id,
                                "pendingToolCallIds": list(pending),
                            },
                        )
                    seen_tool_result_ids.add(block_call_id)
                    pending.remove(block_call_id)
                continue
            tool_call_id = str(message.get("tool_call_id") or "").strip()
            if not tool_call_id:
                return PayloadValidationResult(
                    ok=False,
                    error_type="tool_result_missing_id",
                    message="Tool result message is missing tool_call_id.",
                    details={"messageIndex": index},
                )
            if tool_call_id in seen_tool_result_ids:
                return PayloadValidationResult(
                    ok=False,
                    error_type="duplicate_tool_result",
                    message="Duplicate tool result detected before provider send.",
                    details={"messageIndex": index, "toolCallId": tool_call_id},
                )
            if tool_call_id not in pending:
                return PayloadValidationResult(
                    ok=False,
                    error_type="orphan_tool_result",
                    message="Tool result has no pending assistant tool call.",
                    details={"messageIndex": index, "toolCallId": tool_call_id, "pendingToolCallIds": list(pending)},
                )
            seen_tool_result_ids.add(tool_call_id)
            pending.remove(tool_call_id)
            continue
        if pending:
            return PayloadValidationResult(
                ok=False,
                error_type="missing_tool_result",
                message="Assistant tool call is missing a matching tool result before the next non-tool message.",
                details={"messageIndex": index, "pendingToolCallIds": list(pending)},
            )
    if pending:
        return PayloadValidationResult(
            ok=False,
            error_type="missing_tool_result",
            message="Assistant tool call is missing a matching tool result at the end of the payload.",
            details={"pendingToolCallIds": list(pending)},
        )
    return PayloadValidationResult(ok=True)


def validate_responses_function_pairing(
    items: List[Dict[str, Any]],
    *,
    allow_external_call_ids: bool = False,
) -> PayloadValidationResult:
    """Validate Responses function_call/function_call_output items before provider send."""

    pending: list[str] = []
    seen_call_ids: set[str] = set()
    seen_output_ids: set[str] = set()
    for index, item in enumerate(items):
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "function_call":
            call_id = str(item.get("call_id") or "").strip()
            if not call_id:
                return PayloadValidationResult(
                    ok=False,
                    error_type="function_call_missing_id",
                    message="Responses function_call item is missing call_id.",
                    details={"messageIndex": index},
                )
            if call_id in seen_call_ids:
                return PayloadValidationResult(
                    ok=False,
                    error_type="duplicate_function_call_id",
                    message="Duplicate Responses function_call call_id detected before provider send.",
                    details={"messageIndex": index, "callId": call_id},
                )
            seen_call_ids.add(call_id)
            pending.append(call_id)
            continue
        if item_type == "function_call_output":
            call_id = str(item.get("call_id") or "").strip()
            if not call_id:
                return PayloadValidationResult(
                    ok=False,
                    error_type="function_call_output_missing_id",
                    message="Responses function_call_output item is missing call_id.",
                    details={"messageIndex": index},
                )
            if call_id in seen_output_ids:
                return PayloadValidationResult(
                    ok=False,
                    error_type="duplicate_function_call_output",
                    message="Duplicate Responses function_call_output detected before provider send.",
                    details={"messageIndex": index, "callId": call_id},
                )
            if call_id not in pending:
                if allow_external_call_ids:
                    seen_output_ids.add(call_id)
                    continue
                return PayloadValidationResult(
                    ok=False,
                    error_type="orphan_function_call_output",
                    message="Responses function_call_output has no pending function_call.",
                    details={"messageIndex": index, "callId": call_id, "pendingCallIds": list(pending)},
                )
            seen_output_ids.add(call_id)
            pending.remove(call_id)
            continue
        if pending:
            return PayloadValidationResult(
                ok=False,
                error_type="missing_function_call_output",
                message="Responses function_call is missing a matching function_call_output before the next non-tool item.",
                details={"messageIndex": index, "pendingCallIds": list(pending)},
            )
    if pending:
        return PayloadValidationResult(
            ok=False,
            error_type="missing_function_call_output",
            message="Responses function_call is missing a matching function_call_output at the end of the payload.",
            details={"pendingCallIds": list(pending)},
        )
    return PayloadValidationResult(ok=True)


def payload_protocol_summary(payload: Dict[str, Any], route: ResolvedProtocolRoute) -> Dict[str, Any]:
    messages = _conversation_items(payload)
    roles = [_role(item) or "unknown" for item in messages]
    response_item_types = [
        str(item.get("type") or item.get("role") or "unknown").strip().lower() or "unknown"
        for item in _input_items(payload)
    ]
    thinking = payload.get("thinking")
    thinking_type = str(thinking.get("type") or "").strip().lower() if isinstance(thinking, dict) else ""
    thinking_requested = any(key in payload for key in ("thinking", "enable_thinking"))
    thinking_enabled = thinking_requested and thinking_type != "disabled"
    return {
        **route.log_summary(),
        "thinkingRequested": thinking_requested,
        "thinkingEnabled": thinking_enabled,
        "messageCount": len(messages),
        "messageRoles": roles,
        "messageRoleTail": roles[-5:],
        "lastMessageRole": roles[-1] if roles else "",
        "responsesItemTypeTail": response_item_types[-5:],
        "assistantPrefillDetected": _assistant_prefill_detected(messages),
        "toolCount": len(payload.get("tools") or []) if isinstance(payload.get("tools"), list) else 0,
        "payloadTransportShape": "responses_input" if "input" in payload else "chat_messages",
        "payloadValidationResult": "not_validated",
        "payloadValidationErrorType": "",
    }


def validate_payload_against_protocol(
    payload: Dict[str, Any],
    route: ResolvedProtocolRoute,
) -> PayloadValidationResult:
    messages = _conversation_items(payload)
    summary = payload_protocol_summary(payload, route)
    policy = route.policy
    compat = route.compat
    transport = str(getattr(policy, "transport", "") or "").strip().lower()

    def fail(error_type: str, message: str, **details: Any) -> PayloadValidationResult:
        return PayloadValidationResult(
            ok=False,
            error_type=error_type,
            message=message,
            details={**summary, **details, "payloadValidationResult": "blocked_before_provider", "payloadValidationErrorType": error_type},
        )

    if transport == "responses":
        if "messages" in payload:
            return fail("responses_transport_messages_not_allowed", "Responses transport payload must use top-level `input`, not `messages`.")
        if "input" not in payload:
            return fail("responses_transport_input_required", "Responses transport payload is missing top-level `input`.")
        invalid_blocks = [block for block in _content_block_types(messages) if block in {"text", "image_url"}]
        if invalid_blocks:
            return fail(
                "responses_transport_content_block_type_not_allowed",
                "Responses transport payload must use Responses content blocks such as input_text/input_image.",
                invalidContentBlockTypes=invalid_blocks[:8],
            )
        pairing_result = validate_responses_function_pairing(
            _input_items(payload),
            allow_external_call_ids=bool(str(payload.get("previous_response_id") or "").strip()),
        )
        if not pairing_result.ok:
            return fail(pairing_result.error_type, pairing_result.message, **pairing_result.details)
    else:
        if "input" in payload:
            return fail("chat_transport_input_not_allowed", "Chat Completions transport payload must use top-level `messages`, not `input`.")
        invalid_blocks = [block for block in _content_block_types(messages) if block in {"input_text", "input_image"}]
        if invalid_blocks:
            return fail(
                "chat_transport_content_block_type_not_allowed",
                "Chat Completions transport payload must not contain Responses content blocks.",
                invalidContentBlockTypes=invalid_blocks[:8],
            )

    if not policy.allow_tools:
        if payload.get("tools") or payload.get("tool_choice"):
            return fail("tools_not_allowed", f"Protocol `{route.protocol.value}` does not allow tool payload fields.")

    if not policy.allow_explicit_tool_choice or compat.tool_choice_mode == "omit":
        if "tool_choice" in payload:
            return fail("tool_choice_not_allowed", f"Protocol `{route.protocol.value}` requires omitting tool_choice.")

    if not policy.allow_stream_usage_options or not compat.stream_usage_options:
        stream_options = payload.get("stream_options")
        if isinstance(stream_options, dict) and stream_options.get("include_usage"):
            return fail("stream_usage_not_allowed", f"Protocol `{route.protocol.value}` does not allow stream usage options.")

    if not policy.allow_multiple_system_messages:
        if sum(1 for item in messages if _role(item) == "system") > 1:
            return fail("multiple_system_messages_not_allowed", f"Protocol `{route.protocol.value}` allows only one system message.")

    thinking_requested = bool(summary["thinkingRequested"])
    thinking_enabled = bool(summary.get("thinkingEnabled"))
    if policy.thinking_param_shape == "none" and thinking_enabled:
        return fail("thinking_not_allowed", f"Protocol `{route.protocol.value}` does not allow thinking parameters.")

    if not policy.allow_reasoning_roundtrip or not compat.reasoning_roundtrip:
        for index, message in enumerate(messages):
            if "reasoning_content" in message:
                return fail(
                    "reasoning_roundtrip_not_allowed",
                    f"Protocol `{route.protocol.value}` does not allow outgoing reasoning_content.",
                    messageIndex=index,
                )

    if (
        thinking_enabled
        and not compat.allow_assistant_prefill
        and summary["assistantPrefillDetected"]
    ):
        return fail(
            "assistant_prefill_not_allowed",
            f"Protocol `{route.protocol.value}` forbids assistant prefill while thinking is enabled.",
        )

    if policy.final_message_policy in {"no_assistant_prefill", "must_end_user_or_tool"}:
        if messages and _role(messages[-1]) == "assistant":
            if policy.final_message_policy == "must_end_user_or_tool" or _assistant_prefill_detected(messages):
                return fail(
                    "assistant_final_message_not_allowed",
                    f"Protocol `{route.protocol.value}` does not allow the final payload message to be assistant prefill.",
                )

    if transport != "responses":
        pairing_result = validate_tool_result_pairing(messages)
        if not pairing_result.ok:
            return fail(pairing_result.error_type, pairing_result.message, **pairing_result.details)

    return PayloadValidationResult(
        ok=True,
        details={**summary, "payloadValidationResult": "passed", "payloadValidationErrorType": ""},
    )


def assert_payload_valid(payload: Dict[str, Any], route: ResolvedProtocolRoute) -> Dict[str, Any]:
    result = validate_payload_against_protocol(payload, route)
    if result.ok:
        return result.details
    raise LLMError(
        "payload_protocol_error",
        result.message,
        retryable=False,
        provider=route.provider_kind,
        model=route.model,
        details=result.details,
    )


__all__ = [
    "PayloadValidationResult",
    "assert_payload_valid",
    "payload_protocol_summary",
    "validate_responses_function_pairing",
    "validate_tool_result_pairing",
    "validate_payload_against_protocol",
]
