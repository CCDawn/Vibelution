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


def payload_protocol_summary(payload: Dict[str, Any], route: ResolvedProtocolRoute) -> Dict[str, Any]:
    messages = _messages(payload)
    roles = [_role(item) or "unknown" for item in messages]
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
        "assistantPrefillDetected": _assistant_prefill_detected(messages),
        "toolCount": len(payload.get("tools") or []) if isinstance(payload.get("tools"), list) else 0,
        "payloadValidationResult": "not_validated",
        "payloadValidationErrorType": "",
    }


def validate_payload_against_protocol(
    payload: Dict[str, Any],
    route: ResolvedProtocolRoute,
) -> PayloadValidationResult:
    messages = _messages(payload)
    summary = payload_protocol_summary(payload, route)
    policy = route.policy
    compat = route.compat

    def fail(error_type: str, message: str, **details: Any) -> PayloadValidationResult:
        return PayloadValidationResult(
            ok=False,
            error_type=error_type,
            message=message,
            details={**summary, **details, "payloadValidationResult": "blocked_before_provider", "payloadValidationErrorType": error_type},
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
    "validate_payload_against_protocol",
]
