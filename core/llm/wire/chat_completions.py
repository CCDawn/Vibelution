"""Canonical OpenAI Chat Completions wire adapter."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from ..message_projector import message_to_openai_dict
from ..protocols import WireProtocol
from ..provider_replay_state import OpaqueReplayItem, endpoint_fingerprint
from ..reasoning_extractor import ThinkTagStreamParser, extract_reasoning_text
from ..semantic_messages import (
    ImagePart,
    InvocationScope,
    ReasoningReplayPart,
    SemanticMessage,
    SemanticModelRequest,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from ..streaming import ToolCallAccumulator, extract_text_content
from ..types import (
    CanonicalItemIdentity,
    CanonicalToolCall,
    CanonicalToolResult,
    LLMProtocolEvent,
    TurnOutcome,
)
from .types import BuiltPayload


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if value is not None and hasattr(value, "__dict__"):
        return dict(getattr(value, "__dict__", {}) or {})
    return {}


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_thaw(item) for item in sorted(value, key=repr)]
    return value


def _json_output(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(_thaw(value), ensure_ascii=False, separators=(",", ":"))


class ChatDecodedStream:
    def __init__(self, raw_chunks: Iterable[Any], *, route: Any, scope: InvocationScope) -> None:
        self._raw_chunks = raw_chunks
        self._route = route
        self._scope = scope
        self._outcome: TurnOutcome | None = None
        self._iterator = self._consume()

    @property
    def outcome(self) -> TurnOutcome:
        if self._outcome is None:
            raise RuntimeError("Chat stream outcome is available only after the stream is exhausted")
        return self._outcome

    def __iter__(self) -> ChatDecodedStream:
        return self

    def __next__(self) -> LLMProtocolEvent:
        return next(self._iterator)

    def _consume(self) -> Iterator[LLMProtocolEvent]:
        assembler = _ChatTurnAssembler(route=self._route, scope=self._scope)
        for raw_chunk in self._raw_chunks:
            for event in assembler.feed(raw_chunk):
                yield event
        for event in assembler.finish():
            yield event
        self._outcome = assembler.outcome


class ChatCompletionsWireAdapter:
    adapter_id = "chat_completions"
    wire_protocol = WireProtocol.CHAT_COMPLETIONS

    def encode_request(self, request: SemanticModelRequest, *, route: Any) -> BuiltPayload:
        if request.replay_state is not None:
            request.replay_state.require_compatible(
                issuer=self.adapter_id,
                provider_id=str(getattr(route, "provider_id", "") or ""),
                endpoint_fingerprint=endpoint_fingerprint(str(getattr(route, "runtime_endpoint", "") or "")),
                model_id=str(getattr(route, "model_id", "") or ""),
                wire_protocol=WireProtocol.CHAT_COMPLETIONS,
            )
        payload: dict[str, Any] = {
            "model": str(getattr(route, "effective_model", "") or ""),
            "messages": self._encode_messages(request),
            "max_tokens": request.settings.max_output_tokens,
            "stream": request.settings.stream,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": _thaw(tool.input_schema),
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = request.settings.tool_choice
        if request.settings.temperature is not None:
            payload["temperature"] = request.settings.temperature
        if request.settings.top_p is not None:
            payload["top_p"] = request.settings.top_p
        return BuiltPayload(
            body=payload,
            endpoint=str(getattr(route, "runtime_endpoint", "") or ""),
        )

    def decode_response(self, response: Any, *, route: Any, scope: InvocationScope) -> TurnOutcome:
        response_dict = _as_dict(response)
        chunks: list[dict[str, Any]] = []
        for raw_choice in list(response_dict.get("choices") or []):
            choice = _as_dict(raw_choice)
            chunks.append(
                {
                    "id": response_dict.get("id"),
                    "choices": [
                        {
                            "index": choice.get("index", 0),
                            "delta": _as_dict(choice.get("message")),
                            "finish_reason": choice.get("finish_reason"),
                        }
                    ],
                    "usage": response_dict.get("usage"),
                }
            )
        if not chunks:
            chunks.append({"type": "chat.failed", "error": {"message": "Chat response has no choices"}})
        decoded = self.decode_stream(chunks, route=route, scope=scope)
        tuple(decoded)
        return decoded.outcome

    def decode_stream(
        self,
        events: Iterable[Any],
        *,
        route: Any,
        scope: InvocationScope,
    ) -> ChatDecodedStream:
        return ChatDecodedStream(events, route=route, scope=scope)

    def encode_tool_results(self, results: Sequence[CanonicalToolResult]) -> list[Any]:
        return [
            {
                "role": "tool",
                "tool_call_id": result.call_id,
                "content": _json_output(result.output),
            }
            for result in results
        ]

    def _encode_messages(self, request: SemanticModelRequest) -> list[dict[str, Any]]:
        replay_by_id = {
            item.item_id: item
            for item in (request.replay_state.opaque_items if request.replay_state is not None else ())
        }
        encoded: list[dict[str, Any]] = []
        for message in request.messages:
            encoded.extend(self._encode_message(message, replay_by_id=replay_by_id))
        return encoded

    def _encode_message(
        self,
        message: SemanticMessage,
        *,
        replay_by_id: Mapping[str, OpaqueReplayItem],
    ) -> list[dict[str, Any]]:
        text_parts: list[str] = []
        content_blocks: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        standalone: list[dict[str, Any]] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                text_parts.append(part.text)
                content_blocks.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                content_blocks.append({"type": "image_url", "image_url": {"url": part.uri}})
            elif isinstance(part, ToolCallPart):
                tool_calls.append(
                    {
                        "id": part.call.call_id,
                        "type": "function",
                        "function": {
                            "name": part.call.name,
                            "arguments": _json_output(part.call.arguments),
                        },
                    }
                )
            elif isinstance(part, ToolResultPart):
                standalone.extend(self.encode_tool_results([part.result]))
            elif isinstance(part, ReasoningReplayPart):
                replay_item = replay_by_id.get(part.replay_item_id)
                if replay_item is None:
                    raise ValueError(f"reasoning replay item `{part.replay_item_id}` is unavailable")
                try:
                    provider_message = json.loads(replay_item.payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("reasoning replay item is not valid provider JSON") from exc
                if not isinstance(provider_message, dict):
                    raise ValueError("reasoning replay item must decode to an object")
                standalone.append(provider_message)
        primary: list[dict[str, Any]] = []
        if text_parts or content_blocks or tool_calls:
            has_image = any(block.get("type") == "image_url" for block in content_blocks)
            payload: dict[str, Any] = {
                "role": message.role,
                "content": content_blocks if has_image else "".join(text_parts),
            }
            if tool_calls:
                payload["tool_calls"] = tool_calls
            primary.append(
                message_to_openai_dict(
                    payload,
                    preserve_structured_content=has_image,
                    preserve_reasoning_content=True,
                )
            )
        return [*primary, *standalone]


class _ChatTurnAssembler:
    def __init__(self, *, route: Any, scope: InvocationScope) -> None:
        self.route = route
        self.scope = scope
        self.sequence = 0
        self.response_id = ""
        self.events: list[LLMProtocolEvent] = []
        self.text_by_choice: dict[int, str] = {}
        self.text_item_by_choice: dict[int, str] = {}
        self.tool_accumulators: dict[int, ToolCallAccumulator] = {}
        self.tool_call_ids_by_position: dict[tuple[int, int], str] = {}
        self.started_call_ids: set[str] = set()
        self.think_parsers: dict[int, ThinkTagStreamParser] = {}
        self.tool_calls: list[CanonicalToolCall] = []
        self._terminal_seen = False
        self._outcome: TurnOutcome | None = None

    @property
    def outcome(self) -> TurnOutcome:
        if self._outcome is None:
            raise RuntimeError("Chat assembler has no terminal outcome")
        return self._outcome

    def feed(self, raw_chunk: Any) -> list[LLMProtocolEvent]:
        if self._terminal_seen:
            return []
        chunk = _as_dict(raw_chunk)
        chunk_type = str(chunk.get("type") or "")
        emitted: list[LLMProtocolEvent] = []
        response_id = str(chunk.get("id") or "")
        if response_id:
            self.response_id = response_id
        if not any(event.kind == "turn_started" for event in self.events):
            emitted.append(
                self._emit(
                    "turn_started",
                    status="streaming",
                    provider_event_type="synthetic.chat.turn_started",
                )
            )
        if chunk_type == "chat.cancelled":
            emitted.extend(self._terminal("cancelled", provider_event_type=chunk_type))
            return emitted
        if chunk_type == "chat.failed":
            error = _as_dict(chunk.get("error"))
            emitted.extend(
                self._terminal(
                    "failed",
                    provider_event_type=chunk_type,
                    error=str(error.get("message") or "Chat request failed"),
                )
            )
            return emitted
        usage = _as_dict(chunk.get("usage"))
        if usage:
            emitted.append(self._usage_event(usage))
        for raw_choice in list(chunk.get("choices") or []):
            choice = _as_dict(raw_choice)
            choice_index = int(choice.get("index") or 0)
            delta = _as_dict(choice.get("delta"))
            emitted.extend(self._delta(choice_index, delta))
            finish_reason = str(choice.get("finish_reason") or "").strip().lower()
            if finish_reason:
                emitted.extend(self._finish_choice(choice_index, finish_reason))
                break
        return emitted

    def finish(self) -> list[LLMProtocolEvent]:
        if self._terminal_seen:
            return []
        return self._terminal("incomplete", provider_event_type="stream_exhausted_without_finish_reason")

    def _delta(self, choice_index: int, delta: Mapping[str, Any]) -> list[LLMProtocolEvent]:
        emitted: list[LLMProtocolEvent] = []
        reasoning = extract_reasoning_text(delta, extract_text_content, include_content_tags=False)
        if reasoning.text:
            emitted.append(
                self._emit(
                    "reasoning_delta",
                    item_id=self._reasoning_item_id(choice_index),
                    channel="reasoning",
                    phase="reasoning",
                    text=reasoning.text,
                    provider_event_type="chat.delta.reasoning",
                )
            )
        parser = self.think_parsers.setdefault(choice_index, ThinkTagStreamParser())
        split = parser.feed(delta.get("content") or "", extract_text_content)
        if split.reasoning_text:
            emitted.append(
                self._emit(
                    "reasoning_delta",
                    item_id=self._reasoning_item_id(choice_index),
                    channel="reasoning",
                    phase="reasoning",
                    text=split.reasoning_text,
                    provider_event_type="chat.delta.think_tag",
                )
            )
        if split.visible_text:
            item_id = self._text_item_id(choice_index)
            self.text_by_choice[choice_index] = self.text_by_choice.get(choice_index, "") + split.visible_text
            allow_tools = bool(getattr(getattr(self.route, "policy", None), "allow_tools", False))
            emitted.append(
                self._emit(
                    "interim_text_delta" if allow_tools else "answer_delta",
                    item_id=item_id,
                    channel="interim" if allow_tools else "answer",
                    phase="interim" if allow_tools else "final_answer",
                    text=split.visible_text,
                    provisional=allow_tools,
                    provider_event_type="chat.delta.content",
                )
            )
        tool_deltas = list(delta.get("tool_calls") or [])
        if tool_deltas:
            accumulator = self.tool_accumulators.setdefault(choice_index, ToolCallAccumulator())
            for fallback_index, raw_tool in enumerate(tool_deltas):
                tool = _as_dict(raw_tool)
                tool_index = int(tool.get("index") if tool.get("index") is not None else fallback_index)
                function = _as_dict(tool.get("function"))
                position = (choice_index, tool_index)
                provider_call_id = str(tool.get("id") or "")
                if provider_call_id:
                    self.tool_call_ids_by_position[position] = provider_call_id
                call_id = provider_call_id or self.tool_call_ids_by_position.get(position, "")
                name = str(function.get("name") or "")
                if call_id and call_id not in self.started_call_ids:
                    self.started_call_ids.add(call_id)
                    emitted.append(
                        self._emit(
                            "tool_call_started",
                            item_id=call_id,
                            call_id=call_id,
                            channel="tool",
                            phase="tool",
                            status="in_progress",
                            tool_name=name,
                            provider_event_type="chat.delta.tool_call",
                        )
                    )
                arguments_delta = function.get("arguments")
                if call_id and arguments_delta not in (None, ""):
                    emitted.append(
                        self._emit(
                            "tool_arguments_delta",
                            item_id=call_id,
                            call_id=call_id,
                            channel="tool",
                            phase="tool",
                            arguments_delta=str(arguments_delta),
                            provider_event_type="chat.delta.tool_arguments",
                        )
                    )
            accumulator.add_deltas(tool_deltas)
        return emitted

    def _finish_choice(self, choice_index: int, finish_reason: str) -> list[LLMProtocolEvent]:
        emitted = self._flush_think_parser(choice_index)
        calls = self.tool_accumulators.get(choice_index, ToolCallAccumulator()).final_calls()
        for index, call in enumerate(calls):
            provider_call_id = self.tool_call_ids_by_position.get((choice_index, index), "")
            call_id = provider_call_id or f"chat:{self.scope.invocation_id}:tool:{index}"
            canonical = CanonicalToolCall(
                identity=self._identity(call_id),
                call_id=call_id,
                name=call.name,
                arguments=call.arguments,
                provider_item_id=call_id,
            )
            self.tool_calls.append(canonical)
            if call_id not in self.started_call_ids:
                self.started_call_ids.add(call_id)
                emitted.append(
                    self._emit(
                        "tool_call_started",
                        item_id=call_id,
                        call_id=call_id,
                        channel="tool",
                        phase="tool",
                        status="in_progress",
                        tool_name=call.name,
                        provider_event_type="chat.finish.tool_call_fallback",
                    )
                )
            emitted.append(
                self._emit(
                    "tool_call_ready",
                    item_id=call_id,
                    call_id=call_id,
                    channel="tool",
                    phase="tool",
                    status="completed",
                    tool_name=call.name,
                    provider_event_type="chat.finish.tool_calls",
                )
            )
        text = self.text_by_choice.get(choice_index, "")
        item_id = self._text_item_id(choice_index)
        if finish_reason == "tool_calls" and not self.tool_calls:
            emitted.extend(
                self._terminal(
                    "incomplete",
                    provider_event_type="chat.finish.tool_calls_without_valid_call",
                )
            )
            return emitted
        if self.tool_calls or finish_reason == "tool_calls":
            if text:
                emitted.append(
                    self._emit(
                        "item_completed",
                        item_id=item_id,
                        item_revision=1,
                        channel="commentary",
                        phase="commentary",
                        status="completed",
                        text=text,
                        provider_event_type="chat.finish.tool_calls",
                    )
                )
            emitted.extend(self._terminal("tool_calls", provider_event_type="chat.finish.tool_calls"))
        elif finish_reason == "stop":
            allow_tools = bool(getattr(getattr(self.route, "policy", None), "allow_tools", False))
            if text:
                emitted.append(
                    self._emit(
                        "item_completed",
                        item_id=item_id,
                        item_revision=1 if allow_tools else 0,
                        channel="answer",
                        phase="final_answer",
                        status="completed",
                        text=text,
                        provider_event_type="chat.finish.stop",
                    )
                )
            emitted.extend(self._terminal("final_answer", provider_event_type="chat.finish.stop"))
        else:
            emitted.extend(self._terminal("incomplete", provider_event_type=f"chat.finish.{finish_reason}"))
        return emitted

    def _flush_think_parser(self, choice_index: int) -> list[LLMProtocolEvent]:
        parser = self.think_parsers.get(choice_index)
        if parser is None:
            return []
        flushed = parser.flush()
        emitted: list[LLMProtocolEvent] = []
        if flushed.reasoning_text:
            emitted.append(
                self._emit(
                    "reasoning_delta",
                    item_id=self._reasoning_item_id(choice_index),
                    channel="reasoning",
                    phase="reasoning",
                    text=flushed.reasoning_text,
                    provider_event_type="chat.finish.think_tag",
                )
            )
        if flushed.visible_text:
            self.text_by_choice[choice_index] = self.text_by_choice.get(choice_index, "") + flushed.visible_text
            emitted.append(
                self._emit(
                    "interim_text_delta",
                    item_id=self._text_item_id(choice_index),
                    channel="interim",
                    phase="interim",
                    text=flushed.visible_text,
                    provisional=True,
                    provider_event_type="chat.finish.visible_text",
                )
            )
        return emitted

    def _terminal(self, kind: str, *, provider_event_type: str, error: str = "") -> list[LLMProtocolEvent]:
        if self._terminal_seen:
            return []
        terminal_kind = {
            "final_answer": "turn_completed",
            "tool_calls": "turn_completed",
            "incomplete": "turn_incomplete",
            "failed": "turn_failed",
            "cancelled": "turn_cancelled",
        }[kind]
        terminal_event = self._emit(
            terminal_kind,
            status=kind,
            terminal=True,
            provider_event_type=provider_event_type,
        )
        self._terminal_seen = True
        text = "".join(self.text_by_choice.values()) if kind == "final_answer" else ""
        identity_item = self._text_item_id(0) if text else self.tool_calls[-1].identity.item_id if self.tool_calls else ""
        self._outcome = TurnOutcome(
            kind=kind,
            identity=self._identity(identity_item),
            events=tuple(self.events),
            tool_calls=tuple(self.tool_calls),
            final_text=text,
            pending_tool_call_ids=tuple(call.call_id for call in self.tool_calls) if kind == "tool_calls" else (),
            terminal_event_seen=True,
            error=error,
        )
        return [terminal_event]

    def _usage_event(self, usage: Mapping[str, Any]) -> LLMProtocolEvent:
        return self._emit(
            "usage_updated",
            status="observed",
            provider_event_type="chat.usage",
            diagnostic_summary={
                "inputTokens": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
                "outputTokens": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
                "totalTokens": int(usage.get("total_tokens") or 0),
            },
        )

    def _emit(self, kind: str, **kwargs: Any) -> LLMProtocolEvent:
        event = LLMProtocolEvent(
            kind=kind,
            sequence=self.sequence,
            session_id=self.scope.session_id,
            turn_id=self.scope.turn_id,
            invocation_id=self.scope.invocation_id,
            iteration=self.scope.iteration,
            response_id=self.response_id,
            **kwargs,
        )
        self.sequence += 1
        self.events.append(event)
        return event

    def _identity(self, item_id: str) -> CanonicalItemIdentity:
        return CanonicalItemIdentity(
            session_id=self.scope.session_id,
            turn_id=self.scope.turn_id,
            invocation_id=self.scope.invocation_id,
            iteration=self.scope.iteration,
            item_id=item_id,
        )

    def _text_item_id(self, choice_index: int) -> str:
        return self.text_item_by_choice.setdefault(
            choice_index,
            f"chat:{self.scope.invocation_id}:choice:{choice_index}:text",
        )

    def _reasoning_item_id(self, choice_index: int) -> str:
        return f"chat:{self.scope.invocation_id}:choice:{choice_index}:reasoning"
