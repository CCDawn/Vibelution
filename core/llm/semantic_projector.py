"""Project existing model messages into provider-neutral semantic requests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .provider_replay_state import ProviderReplayState
from .semantic_messages import (
    CacheHint,
    ImagePart,
    InvocationScope,
    ReasoningReplayPart,
    ReasoningTextPart,
    SemanticGenerationSettings,
    SemanticMessage,
    SemanticModelRequest,
    SemanticToolDefinition,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from .types import CanonicalItemIdentity, CanonicalToolCall, CanonicalToolResult


class SemanticProjectionError(ValueError):
    def __init__(self, code: str, message_index: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message_index = message_index


@dataclass(frozen=True)
class SemanticProjectionInput:
    messages: Sequence[Any]
    tools: Sequence[Any]
    scope: InvocationScope
    settings: SemanticGenerationSettings
    tool_to_schema: Callable[[Any], Mapping[str, Any]]
    replay_state: ProviderReplayState | None = None
    system_message_policy: str = "preserve"
    allow_assistant_prefill: bool = True
    reasoning_roundtrip: bool = False


def _value(owner: Any, name: str, default: Any = None) -> Any:
    if isinstance(owner, Mapping):
        return owner.get(name, default)
    return getattr(owner, name, default)


def _role(message: Any, index: int) -> str:
    raw = str(_value(message, "role", "") or _value(message, "type", "") or "").strip().lower()
    role = {"human": "user", "ai": "assistant"}.get(raw, raw)
    if role not in {"system", "user", "assistant", "tool"}:
        raise SemanticProjectionError("unsupported_role", index, f"unsupported model message role at index {index}")
    return role


def _identity(scope: InvocationScope, item_id: str) -> CanonicalItemIdentity:
    return CanonicalItemIdentity(
        session_id=scope.session_id,
        turn_id=scope.turn_id,
        invocation_id=scope.invocation_id,
        iteration=scope.iteration,
        item_id=item_id,
    )


def _cache_hint(block: Mapping[str, Any], index: int) -> CacheHint | None:
    raw = block.get("cache_control")
    if raw in (None, {}):
        return None
    if not isinstance(raw, Mapping) or set(raw) != {"type"} or raw.get("type") != "ephemeral":
        raise SemanticProjectionError("unsupported_cache_hint", index, "unsupported cache hint shape")
    return CacheHint("ephemeral")


def _content_parts(content: Any, index: int) -> list[Any]:
    if content in (None, ""):
        return []
    if isinstance(content, str):
        return [TextPart(content)]
    if not isinstance(content, (list, tuple)):
        raise SemanticProjectionError("unsupported_content", index, "unsupported model message content shape")
    parts: list[Any] = []
    for block in content:
        if not isinstance(block, Mapping):
            raise SemanticProjectionError("unsupported_content_block", index, "unsupported model content block")
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in {"text", "input_text", "output_text"}:
            parts.append(TextPart(str(block.get("text") or ""), cache_hint=_cache_hint(block, index)))
            continue
        if block_type in {"image", "image_url", "input_image"}:
            image = block.get("image_url")
            if isinstance(image, Mapping):
                uri = str(image.get("url") or "")
                detail = str(image.get("detail") or block.get("detail") or "")
            else:
                uri = str(image or block.get("url") or "")
                detail = str(block.get("detail") or "")
            media_type = str(block.get("media_type") or block.get("mime_type") or "application/octet-stream")
            parts.append(
                ImagePart(
                    uri=uri,
                    media_type=media_type,
                    detail=detail,
                    cache_hint=_cache_hint(block, index),
                )
            )
            continue
        raise SemanticProjectionError("unsupported_content_block", index, "unsupported model content block type")
    return parts


def _arguments(value: Any, index: int) -> Mapping[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SemanticProjectionError("invalid_tool_arguments", index, "tool arguments are not valid JSON") from exc
        if isinstance(decoded, Mapping):
            return decoded
    raise SemanticProjectionError("invalid_tool_arguments", index, "tool arguments must be an object")


def _tool_call(raw: Any, *, scope: InvocationScope, index: int) -> CanonicalToolCall:
    function = _value(raw, "function", {})
    call_id = str(_value(raw, "id", "") or _value(raw, "call_id", "") or "").strip()
    name = str(_value(raw, "name", "") or _value(function, "name", "") or "").strip()
    arguments = _value(raw, "args", None)
    if arguments is None:
        arguments = _value(raw, "arguments", None)
    if arguments is None:
        arguments = _value(function, "arguments", None)
    if not call_id or not name:
        raise SemanticProjectionError("invalid_tool_call", index, "tool call requires non-empty id and name")
    return CanonicalToolCall(
        identity=_identity(scope, f"tool-call:{call_id}"),
        call_id=call_id,
        name=name,
        arguments=_arguments(arguments, index),
    )


def _project_messages(
    messages: Sequence[Any],
    *,
    scope: InvocationScope,
    system_message_policy: str,
    allow_assistant_prefill: bool,
    reasoning_roundtrip: bool,
) -> list[SemanticMessage]:
    projected: list[SemanticMessage] = []
    calls_by_id: dict[str, CanonicalToolCall] = {}
    system_seen = False
    for index, message in enumerate(messages):
        if isinstance(message, Mapping) and "toolCalls" in message:
            raise SemanticProjectionError(
                "ui_projection_not_model_input",
                index,
                "UI toolCalls projection is not valid model input",
            )
        role = _role(message, index)
        if role == "system":
            if system_seen and system_message_policy == "first_only_rest_user":
                role = "user"
            system_seen = True
        parts = _content_parts(_value(message, "content", ""), index)
        raw_calls = _value(message, "tool_calls", ()) or ()
        for raw_call in raw_calls:
            call = _tool_call(raw_call, scope=scope, index=index)
            if call.call_id in calls_by_id:
                raise SemanticProjectionError("duplicate_tool_call_id", index, "duplicate tool call id")
            calls_by_id[call.call_id] = call
            parts.append(ToolCallPart(call))
        replay_item_id = str(
            _value(message, "reasoning_replay_item_id", "")
            or _value(_value(message, "additional_kwargs", {}), "reasoning_replay_item_id", "")
            or ""
        ).strip()
        if replay_item_id:
            parts.append(ReasoningReplayPart(replay_item_id))
        reasoning_text = str(
            _value(message, "reasoning_content", "")
            or _value(_value(message, "additional_kwargs", {}), "reasoning_content", "")
            or ""
        ).strip()
        if reasoning_text and reasoning_roundtrip:
            parts.append(ReasoningTextPart(reasoning_text))
        if role == "tool":
            call_id = str(_value(message, "tool_call_id", "") or "").strip()
            call = calls_by_id.get(call_id)
            if call is None:
                raise SemanticProjectionError("orphan_tool_result", index, "tool result has no preceding call")
            tool_name = str(_value(message, "name", "") or call.name).strip()
            parts = [
                ToolResultPart(
                    CanonicalToolResult(
                        identity=_identity(scope, f"tool-result:{call_id}"),
                        call_id=call_id,
                        tool_name=tool_name,
                        output=_value(message, "content", ""),
                    )
                )
            ]
        if role == "assistant" and not parts and not allow_assistant_prefill:
            continue
        projected.append(SemanticMessage(role=role, parts=tuple(parts)))
    return projected


def _project_tools(
    tools: Sequence[Any],
    *,
    tool_to_schema: Callable[[Any], Mapping[str, Any]],
) -> list[SemanticToolDefinition]:
    projected: list[SemanticToolDefinition] = []
    for tool in tools:
        schema = tool_to_schema(tool)
        function = schema.get("function") if isinstance(schema.get("function"), Mapping) else schema
        projected.append(
            SemanticToolDefinition(
                name=str(function.get("name") or ""),
                description=str(function.get("description") or ""),
                input_schema=function.get("parameters") if isinstance(function.get("parameters"), Mapping) else {},
            )
        )
    return projected


def project_semantic_request(input: SemanticProjectionInput) -> SemanticModelRequest:
    return SemanticModelRequest(
        scope=input.scope,
        messages=tuple(
            _project_messages(
                input.messages,
                scope=input.scope,
                system_message_policy=input.system_message_policy,
                allow_assistant_prefill=input.allow_assistant_prefill,
                reasoning_roundtrip=input.reasoning_roundtrip,
            )
        ),
        tools=tuple(_project_tools(input.tools, tool_to_schema=input.tool_to_schema)),
        settings=input.settings,
        replay_state=input.replay_state,
    )


__all__ = [
    "SemanticProjectionError",
    "SemanticProjectionInput",
    "project_semantic_request",
]
