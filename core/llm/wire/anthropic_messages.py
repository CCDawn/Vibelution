"""Native Anthropic Messages request and response projection."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from ..protocols import WireProtocol
from ..semantic_messages import (
    ImagePart,
    InvocationScope,
    ReasoningReplayPart,
    ReasoningTextPart,
    SemanticMessage,
    SemanticModelRequest,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    validate_provider_ready_messages,
)
from ..types import CanonicalToolResult, TurnOutcome
from .chat_completions import ChatCompletionsWireAdapter
from .types import BuiltPayload


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _json_text(value: Any) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, separators=(",", ":"))


def _finish_reason(value: Any) -> str:
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
        "refusal": "content_filter",
    }.get(str(value or "").strip().lower(), str(value or "stop"))


class AnthropicMessagesNativeWireAdapter:
    adapter_id = "anthropic_messages_native"
    wire_protocol = WireProtocol.ANTHROPIC_MESSAGES

    def encode_request(self, request: SemanticModelRequest, *, route: Any) -> BuiltPayload:
        if request.replay_state is not None:
            raise ValueError("Anthropic Messages native adapter does not accept opaque replay state")
        validate_provider_ready_messages(request.messages)
        systems: list[dict[str, Any]] = []
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            blocks = self._encode_message(message)
            if message.role == "system":
                systems.extend(blocks)
            else:
                messages.append({"role": "user" if message.role == "tool" else message.role, "content": blocks})
        payload: dict[str, Any] = {
            "model": str(getattr(route, "effective_model", "") or ""),
            "max_tokens": request.settings.max_output_tokens,
            "messages": messages,
            "stream": request.settings.stream,
        }
        if systems:
            payload["system"] = systems
        if request.tools:
            payload["tools"] = [
                {"name": tool.name, "description": tool.description, "input_schema": _json_value(tool.input_schema)}
                for tool in request.tools
            ]
            if request.settings.tool_choice != "omit":
                payload["tool_choice"] = {"type": request.settings.tool_choice}
        if request.settings.temperature is not None:
            payload["temperature"] = request.settings.temperature
        if request.settings.top_p is not None:
            payload["top_p"] = request.settings.top_p
        return BuiltPayload(body=payload, endpoint=str(getattr(route, "runtime_endpoint", "") or ""))

    def _encode_message(self, message: SemanticMessage) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                block: dict[str, Any] = {"type": "text", "text": part.text}
                if part.cache_hint is not None:
                    block["cache_control"] = {"type": part.cache_hint.mode}
                blocks.append(block)
            elif isinstance(part, ImagePart):
                blocks.append({"type": "image", "source": {"type": "url", "url": part.uri}})
            elif isinstance(part, ToolCallPart):
                blocks.append({"type": "tool_use", "id": part.call.call_id, "name": part.call.name, "input": _json_value(part.call.arguments)})
            elif isinstance(part, ToolResultPart):
                blocks.extend(self.encode_tool_results((part.result,)))
            elif isinstance(part, ReasoningTextPart):
                blocks.append({"type": "thinking", "thinking": part.text})
            elif isinstance(part, ReasoningReplayPart):
                raise ValueError("Anthropic native adapter does not accept reasoning replay ids")
        return blocks

    def encode_tool_results(self, results: Sequence[CanonicalToolResult]) -> list[Any]:
        return [
            {
                "type": "tool_result",
                "tool_use_id": result.call_id,
                "content": result.output if isinstance(result.output, str) else _json_text(result.output),
                "is_error": result.is_error,
            }
            for result in results
        ]

    def decode_response(self, response: Any, *, route: Any, scope: InvocationScope) -> TurnOutcome:
        payload = _mapping(response)
        text: list[str] = []
        reasoning: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for index, raw_block in enumerate(payload.get("content") or []):
            block = _mapping(raw_block)
            block_type = str(block.get("type") or "")
            if block_type == "text":
                text.append(str(block.get("text") or ""))
            elif block_type in {"thinking", "redacted_thinking"}:
                reasoning.append(str(block.get("thinking") or ""))
            elif block_type == "tool_use":
                tool_calls.append({"index": index, "id": str(block.get("id") or f"tool-{index}"), "type": "function", "function": {"name": str(block.get("name") or ""), "arguments": _json_text(block.get("input") or {})}})
        message: dict[str, Any] = {"role": "assistant", "content": "".join(text)}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if tool_calls:
            message["tool_calls"] = tool_calls
        translated = {
            "id": payload.get("id"),
            "choices": [{"index": 0, "message": message, "finish_reason": _finish_reason(payload.get("stop_reason"))}],
            "usage": payload.get("usage"),
        }
        return ChatCompletionsWireAdapter().decode_response(translated, route=route, scope=scope)

    def decode_stream(self, events: Iterable[Any], *, route: Any, scope: InvocationScope):
        return ChatCompletionsWireAdapter().decode_stream(self._translate_stream(events), route=route, scope=scope)

    def _translate_stream(self, events: Iterable[Any]) -> Iterator[dict[str, Any]]:
        response_id = ""
        for raw_event in events:
            event = _mapping(raw_event)
            event_type = str(event.get("type") or "")
            if event_type == "message_start":
                message = _mapping(event.get("message"))
                response_id = str(message.get("id") or response_id)
                if message.get("usage"):
                    yield {"id": response_id, "choices": [], "usage": message.get("usage")}
            elif event_type == "content_block_start":
                index = int(event.get("index") or 0)
                block = _mapping(event.get("content_block"))
                if block.get("type") == "tool_use":
                    yield {"id": response_id, "choices": [{"index": 0, "delta": {"tool_calls": [{"index": index, "id": block.get("id"), "type": "function", "function": {"name": block.get("name"), "arguments": ""}}]}}]}
            elif event_type == "content_block_delta":
                index = int(event.get("index") or 0)
                delta = _mapping(event.get("delta"))
                delta_type = str(delta.get("type") or "")
                translated_delta: dict[str, Any] = {}
                if delta_type == "text_delta":
                    translated_delta["content"] = str(delta.get("text") or "")
                elif delta_type == "thinking_delta":
                    translated_delta["reasoning_content"] = str(delta.get("thinking") or "")
                elif delta_type == "input_json_delta":
                    translated_delta["tool_calls"] = [{"index": index, "function": {"arguments": str(delta.get("partial_json") or "")}}]
                if translated_delta:
                    yield {"id": response_id, "choices": [{"index": 0, "delta": translated_delta}]}
            elif event_type == "message_delta":
                delta = _mapping(event.get("delta"))
                yield {"id": response_id, "choices": [{"index": 0, "delta": {}, "finish_reason": _finish_reason(delta.get("stop_reason"))}], "usage": event.get("usage")}
            elif event_type == "error":
                error = _mapping(event.get("error"))
                yield {"type": "chat.failed", "error": {"message": str(error.get("message") or error.get("type") or "Anthropic request failed")}}


__all__ = ["AnthropicMessagesNativeWireAdapter"]
