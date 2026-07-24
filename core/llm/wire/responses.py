"""Canonical OpenAI Responses wire adapter."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from ..protocols import WireProtocol
from ..provider_replay_state import OpaqueReplayItem, ProviderReplayState, endpoint_fingerprint
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
from ..streaming import ResponsesToolCallAccumulator
from ..usage import usage_diagnostic_summary_from_payload
from ..types import (
    CanonicalItemIdentity,
    CanonicalToolCall,
    CanonicalToolResult,
    LLMProtocolEvent,
    TurnOutcome,
)
from .types import BuiltPayload


STREAM_EXHAUSTED_WITHOUT_TERMINAL = "stream_exhausted_without_terminal"


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


def _json_arguments(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(_thaw(value), ensure_ascii=False)


def _decode_replay_item(replay_item: OpaqueReplayItem) -> dict[str, Any]:
    try:
        provider_item = json.loads(replay_item.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("reasoning replay item is not valid provider JSON") from exc
    if not isinstance(provider_item, dict):
        raise ValueError("reasoning replay item must decode to an object")
    if provider_item.get("type") != "reasoning":
        raise ValueError("reasoning replay item must have Responses type `reasoning`")
    provider_item_id = provider_item.get("id")
    if not isinstance(provider_item_id, str) or provider_item_id.strip() != replay_item.item_id:
        raise ValueError("reasoning replay item id does not match replay state")
    return provider_item


def _item_text(item: Mapping[str, Any]) -> str:
    direct = item.get("text")
    if isinstance(direct, str):
        return direct
    parts: list[str] = []
    content = item.get("content")
    if isinstance(content, list):
        for raw_block in content:
            block = _as_dict(raw_block)
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _response_status(response: Mapping[str, Any]) -> str:
    return str(response.get("status") or "").strip().lower()


def _response_incomplete_reason(response: Mapping[str, Any]) -> str:
    details = _as_dict(response.get("incomplete_details"))
    return str(details.get("reason") or "").strip()[:160]


def _response_event_type(value: Any) -> str:
    """Normalize provider event enums without depending on the SDK type."""

    return str(getattr(value, "value", value) or "").strip()


class ResponsesDecodedStream:
    """Single-consumer canonical stream with an outcome available after exhaustion."""

    def __init__(
        self,
        raw_events: Iterable[Any],
        *,
        route: Any,
        scope: InvocationScope,
        adapter_id: str,
    ) -> None:
        self._raw_events = raw_events
        self._route = route
        self._scope = scope
        self._adapter_id = adapter_id
        self._outcome: TurnOutcome | None = None
        self._iterator = self._consume()

    @property
    def outcome(self) -> TurnOutcome:
        if self._outcome is None:
            raise RuntimeError("Responses stream outcome is available only after the stream is exhausted")
        return self._outcome

    def __iter__(self) -> ResponsesDecodedStream:
        return self

    def __next__(self) -> LLMProtocolEvent:
        return next(self._iterator)

    def _consume(self) -> Iterator[LLMProtocolEvent]:
        assembler = _ResponsesTurnAssembler(
            route=self._route,
            scope=self._scope,
            adapter_id=self._adapter_id,
        )
        for raw_event in self._raw_events:
            for event in assembler.feed(raw_event):
                yield event
        for event in assembler.finish():
            yield event
        self._outcome = assembler.outcome


class ResponsesWireAdapter:
    adapter_id = "responses"
    wire_protocol = WireProtocol.RESPONSES
    _WEBSOCKET_TRANSPORT_KEY = "_vibelution_responses_websocket"

    def encode_request(self, request: SemanticModelRequest, *, route: Any) -> BuiltPayload:
        if request.replay_state is not None:
            request.replay_state.require_compatible(
                issuer=self.adapter_id,
                provider_id=str(getattr(route, "provider_id", "") or ""),
                endpoint_fingerprint=endpoint_fingerprint(str(getattr(route, "runtime_endpoint", "") or "")),
                model_id=str(getattr(route, "model_id", "") or ""),
                wire_protocol=WireProtocol.RESPONSES,
            )
        validate_provider_ready_messages(request.messages)
        replay_state = request.replay_state
        compat = getattr(route, "compat", None)
        continuation_supported = bool(getattr(compat, "responses_continuation", False))
        websocket_enabled = bool(getattr(compat, "responses_websocket", False))
        continuation_input_supported = continuation_supported or websocket_enabled
        use_tool_continuation = bool(
            replay_state is not None
            and replay_state.response_id
            and replay_state.pending_call_ids
            and continuation_input_supported
        )
        use_turn_continuation = bool(
            replay_state is not None
            and replay_state.response_id
            and not replay_state.pending_call_ids
            and continuation_input_supported
        )
        full_input = (
            self._encode_messages(request, require_all_replay_referenced=False)
            if websocket_enabled
            else None
        )
        continuation_input = (
            self._encode_messages_after_previous_assistant(request)
            if use_turn_continuation
            else None
        )
        if continuation_input is None:
            use_turn_continuation = False
            continuation_input = full_input or self._encode_messages(request)
        if full_input is None:
            full_input = continuation_input
        if use_tool_continuation:
            pending_call_ids = tuple(replay_state.pending_call_ids)
            pending_call_id_set = set(pending_call_ids)
            outputs_by_call_id: dict[str, dict[str, Any]] = {}
            output_positions: list[int] = []
            for position, item in enumerate(full_input):
                item_dict = _as_dict(item)
                if str(item_dict.get("type") or "") != "function_call_output":
                    continue
                call_id = str(item_dict.get("call_id") or "").strip()
                if call_id not in pending_call_id_set:
                    continue
                if call_id in outputs_by_call_id:
                    raise ValueError(f"duplicate function_call_output for previous response call_id: {call_id}")
                outputs_by_call_id[call_id] = item_dict
                output_positions.append(position)
            missing_call_ids = [call_id for call_id in pending_call_ids if call_id not in outputs_by_call_id]
            if missing_call_ids:
                raise ValueError(
                    "missing function_call_output for previous response call_id(s): "
                    + ", ".join(missing_call_ids)
                )
            latest_output_position = max(output_positions)
            new_user_input = [
                _as_dict(item)
                for item in full_input[latest_output_position + 1 :]
                if str(_as_dict(item).get("role") or "") == "user"
            ]
            continuation_input = [
                *(outputs_by_call_id[call_id] for call_id in pending_call_ids),
                *new_user_input,
            ]
        encoded_input = full_input if websocket_enabled else continuation_input
        payload: dict[str, Any] = {
            "model": str(getattr(route, "effective_model", "") or ""),
            "input": encoded_input,
            "max_output_tokens": request.settings.max_output_tokens,
            "stream": request.settings.stream,
        }
        if continuation_supported and not websocket_enabled and (use_tool_continuation or use_turn_continuation):
            payload["previous_response_id"] = replay_state.response_id
        if websocket_enabled:
            websocket_options: dict[str, Any] = {"enabled": True}
            if use_tool_continuation or use_turn_continuation:
                websocket_options.update(
                    {
                        "previous_response_id": replay_state.response_id,
                        "input": continuation_input,
                    }
                )
            payload[self._WEBSOCKET_TRANSPORT_KEY] = websocket_options
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": _thaw(tool.input_schema),
                }
                for tool in request.tools
            ]
            if request.settings.tool_choice != "omit":
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
        raw_events: list[dict[str, Any]] = []
        for item in list(response_dict.get("output") or []):
            raw_events.append({"type": "response.output_item.done", "item": _as_dict(item)})
        status = _response_status(response_dict) or "completed"
        terminal_type = {
            "completed": "response.completed",
            "incomplete": "response.incomplete",
            "failed": "response.failed",
            "cancelled": "response.cancelled",
            "canceled": "response.cancelled",
        }.get(status, "response.failed")
        raw_events.append({"type": terminal_type, "response": response_dict})
        decoded = self.decode_stream(raw_events, route=route, scope=scope)
        tuple(decoded)
        return decoded.outcome

    def decode_stream(
        self,
        events: Iterable[Any],
        *,
        route: Any,
        scope: InvocationScope,
    ) -> ResponsesDecodedStream:
        return ResponsesDecodedStream(
            events,
            route=route,
            scope=scope,
            adapter_id=self.adapter_id,
        )

    def encode_tool_results(self, results: Sequence[CanonicalToolResult]) -> list[Any]:
        return [
            {
                "type": "function_call_output",
                "call_id": result.call_id,
                "output": _json_output(result.output),
            }
            for result in results
        ]

    def _encode_messages(
        self,
        request: SemanticModelRequest,
        *,
        require_all_replay_referenced: bool = True,
    ) -> list[Any]:
        replay_by_id = {
            item.item_id: item
            for item in (request.replay_state.opaque_items if request.replay_state is not None else ())
        }
        referenced_replay_ids = {
            part.replay_item_id
            for message in request.messages
            for part in message.parts
            if isinstance(part, ReasoningReplayPart)
        }
        if require_all_replay_referenced and any(
            item_id not in referenced_replay_ids for item_id in replay_by_id
        ):
            raise ValueError("opaque replay items must be explicitly referenced by ReasoningReplayPart")
        encoded: list[Any] = []
        for message in request.messages:
            encoded.extend(self._encode_message(message, replay_by_id=replay_by_id))
        return encoded

    def _encode_messages_after_previous_assistant(self, request: SemanticModelRequest) -> list[Any] | None:
        previous_assistant_index = -1
        for index, message in enumerate(request.messages):
            if message.role == "assistant":
                previous_assistant_index = index
        if previous_assistant_index < 0 or previous_assistant_index >= len(request.messages) - 1:
            return None
        encoded: list[Any] = []
        for message in request.messages[previous_assistant_index + 1 :]:
            encoded.extend(self._encode_message(message, replay_by_id={}))
        return encoded or None

    def _encode_message(
        self,
        message: SemanticMessage,
        *,
        replay_by_id: Mapping[str, OpaqueReplayItem],
    ) -> list[Any]:
        encoded: list[Any] = []
        content: list[dict[str, Any]] = []

        def flush_content() -> None:
            if content:
                encoded.append({"role": message.role, "content": list(content)})
                content.clear()

        for part in message.parts:
            if isinstance(part, TextPart):
                block_type = "output_text" if message.role == "assistant" else "input_text"
                content.append({"type": block_type, "text": part.text})
            elif isinstance(part, ImagePart):
                block = {"type": "input_image", "image_url": part.uri}
                if part.detail:
                    block["detail"] = part.detail
                content.append(block)
            elif isinstance(part, ToolCallPart):
                flush_content()
                encoded.append(
                    {
                        "type": "function_call",
                        "call_id": part.call.call_id,
                        "name": part.call.name,
                        "arguments": _json_arguments(part.call.arguments),
                    }
                )
            elif isinstance(part, ToolResultPart):
                flush_content()
                encoded.extend(self.encode_tool_results([part.result]))
            elif isinstance(part, ReasoningReplayPart):
                flush_content()
                replay_item = replay_by_id.get(part.replay_item_id)
                if replay_item is None:
                    raise ValueError(f"reasoning replay item `{part.replay_item_id}` is unavailable")
                encoded.append(_decode_replay_item(replay_item))
            elif isinstance(part, ReasoningTextPart):
                raise ValueError("standard Responses cannot encode plain reasoning text")
        flush_content()
        return encoded


class _ResponsesTurnAssembler:
    def __init__(self, *, route: Any, scope: InvocationScope, adapter_id: str) -> None:
        self.route = route
        self.scope = scope
        self.adapter_id = adapter_id
        self.sequence = 0
        self.response_id = ""
        self.events: list[LLMProtocolEvent] = []
        self.items: dict[str, dict[str, Any]] = {}
        self.completed_item_ids: set[str] = set()
        self.emitted_text: dict[str, str] = {}
        self.completed_text: dict[str, tuple[str, str]] = {}
        self.tool_accumulator = ResponsesToolCallAccumulator()
        self.tool_calls: list[CanonicalToolCall] = []
        self.pending_call_ids: list[str] = []
        self.replay_items: list[OpaqueReplayItem] = []
        self._outcome: TurnOutcome | None = None
        self._terminal_seen = False

    @property
    def outcome(self) -> TurnOutcome:
        if self._outcome is None:
            raise RuntimeError("Responses assembler has no terminal outcome")
        return self._outcome

    def feed(self, raw_event: Any) -> list[LLMProtocolEvent]:
        event = _as_dict(raw_event)
        event_type = _response_event_type(event.get("type"))
        emitted: list[LLMProtocolEvent] = []
        if not event_type:
            return emitted
        response = _as_dict(event.get("response"))
        response_id = str(response.get("id") or event.get("response_id") or "")
        if response_id:
            self.response_id = response_id
        if event_type not in {"response.created", "response.in_progress"} and not any(
            item.kind == "turn_started" for item in self.events
        ):
            emitted.append(
                self._emit(
                    "turn_started",
                    provider_event_type="synthetic.responses.turn_started",
                    status="streaming",
                )
            )
        if event_type in {"response.created", "response.in_progress"}:
            if not any(item.kind == "turn_started" for item in self.events):
                emitted.append(self._emit("turn_started", provider_event_type=event_type, status="streaming"))
            return emitted
        if event_type == "response.output_item.added":
            item = _as_dict(event.get("item"))
            emitted.extend(self._item_added(item, event_type))
            return emitted
        if event_type in {
            "response.reasoning_text.delta",
            "response.reasoning_summary_text.delta",
        }:
            item_id = self._event_item_id(event, "reasoning")
            text = str(event.get("delta") or event.get("text") or "")
            if text:
                emitted.append(
                    self._emit(
                        "reasoning_delta",
                        item_id=item_id,
                        channel="reasoning",
                        phase="reasoning",
                        text=text,
                        provider_event_type=event_type,
                    )
                )
            return emitted
        if event_type == "response.output_text.delta":
            item_id = self._event_item_id(event, "message")
            text = str(event.get("delta") or "")
            emitted.extend(self._emit_text(item_id, text, provider_event_type=event_type))
            return emitted
        if event_type in {
            "response.function_call_arguments.delta",
            "response.tool_call_arguments.delta",
            "response.custom_tool_call_input.delta",
        }:
            self.tool_accumulator.add_arguments_delta(event)
            item_id = self._event_item_id(event, "tool")
            call_id = str(event.get("call_id") or self.items.get(item_id, {}).get("call_id") or "")
            emitted.append(
                self._emit(
                    "tool_arguments_delta",
                    item_id=item_id,
                    call_id=call_id,
                    channel="tool",
                    arguments_delta=str(event.get("delta") or ""),
                    provider_event_type=event_type,
                )
            )
            return emitted
        if event_type in {
            "response.function_call_arguments.done",
            "response.tool_call_arguments.done",
            "response.custom_tool_call_input.done",
        }:
            self.tool_accumulator.add_arguments_done(event)
            return emitted
        if event_type == "response.output_item.done":
            emitted.extend(self._item_done(_as_dict(event.get("item")), event_type))
            return emitted
        if event_type in {
            "response.completed",
            "response.done",
            "response.incomplete",
            "response.failed",
            "response.cancelled",
            "response.canceled",
            "response.error",
            "error",
        }:
            emitted.extend(self._terminal(event_type, event, response))
            return emitted
        return emitted

    def finish(self) -> list[LLMProtocolEvent]:
        if self._terminal_seen:
            return []
        return self._terminal(
            STREAM_EXHAUSTED_WITHOUT_TERMINAL,
            {},
            {"status": "incomplete"},
        )

    def _item_added(self, item: dict[str, Any], event_type: str) -> list[LLMProtocolEvent]:
        item_id = self._item_id(item, "item")
        self.items[item_id] = dict(item)
        item_type = str(item.get("type") or "")
        if item_type not in {"function_call", "tool_call", "custom_tool_call"}:
            return []
        self.tool_accumulator.add_item(item)
        call_id = str(item.get("call_id") or item.get("id") or item_id)
        name = str(item.get("name") or "")
        self.items[item_id]["call_id"] = call_id
        return [
            self._emit(
                "tool_call_started",
                item_id=item_id,
                call_id=call_id,
                channel="tool",
                phase="tool",
                status="in_progress",
                tool_name=name,
                provider_event_type=event_type,
            )
        ]

    def _item_done(self, item: dict[str, Any], event_type: str) -> list[LLMProtocolEvent]:
        item_type = str(item.get("type") or "")
        item_id = self._item_id(item, item_type or "item")
        if item_id in self.completed_item_ids:
            return []
        self.completed_item_ids.add(item_id)
        self.items[item_id] = {**self.items.get(item_id, {}), **item}
        if item_type in {"function_call", "tool_call", "custom_tool_call"}:
            call = self.tool_accumulator.finalize_item(item)
            if call is None:
                return []
            call_id = str(call.id or item.get("call_id") or item_id)
            canonical = CanonicalToolCall(
                identity=self._identity(item_id),
                call_id=call_id,
                name=call.name,
                arguments=call.arguments,
                provider_item_id=item_id,
            )
            self.tool_calls.append(canonical)
            if call_id not in self.pending_call_ids:
                self.pending_call_ids.append(call_id)
            return [
                self._emit(
                    "tool_call_ready",
                    item_id=item_id,
                    call_id=call_id,
                    channel="tool",
                    phase="tool",
                    status="completed",
                    tool_name=call.name,
                    provider_event_type=event_type,
                )
            ]
        if item_type == "reasoning":
            self._capture_replay_item(item_id, item)
            return [
                self._emit(
                    "item_completed",
                    item_id=item_id,
                    channel="reasoning",
                    phase="reasoning",
                    status=str(item.get("status") or "completed"),
                    provider_event_type=event_type,
                )
            ]
        if item_type in {"message", "output_text", "text"}:
            phase = self._item_phase(item_id, item)
            channel = "commentary" if phase == "commentary" else "answer"
            text = _item_text(item)
            emitted = self._emit_text(item_id, text, provider_event_type=event_type, phase=phase)
            self.completed_text[item_id] = (channel, text)
            emitted.append(
                self._emit(
                    "item_completed",
                    item_id=item_id,
                    channel=channel,
                    phase=phase,
                    status=str(item.get("status") or "completed"),
                    text=text,
                    provider_event_type=event_type,
                )
            )
            return emitted
        return []

    def _emit_text(
        self,
        item_id: str,
        text: str,
        *,
        provider_event_type: str,
        phase: str = "",
    ) -> list[LLMProtocolEvent]:
        if not text:
            return []
        resolved_phase = phase or self._item_phase(item_id, self.items.get(item_id, {}))
        channel = "commentary" if resolved_phase == "commentary" else "answer"
        previous = self.emitted_text.get(item_id, "")
        delta = text
        if previous:
            if text.startswith(previous):
                delta = text[len(previous) :]
            elif previous.endswith(text):
                delta = ""
        if not delta:
            return []
        self.emitted_text[item_id] = previous + delta
        return [
            self._emit(
                "commentary_delta" if channel == "commentary" else "answer_delta",
                item_id=item_id,
                channel=channel,
                phase=resolved_phase,
                text=delta,
                provider_event_type=provider_event_type,
            )
        ]

    def _terminal(
        self,
        event_type: str,
        event: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> list[LLMProtocolEvent]:
        if self._terminal_seen:
            return []
        emitted: list[LLMProtocolEvent] = []
        for raw_item in list(response.get("output") or []):
            emitted.extend(self._item_done(_as_dict(raw_item), "response.output_item.done"))
        output_text = response.get("output_text")
        if isinstance(output_text, str) and output_text and not any(
            channel == "answer" for channel, _ in self.completed_text.values()
        ):
            fallback_id = self._fallback_item_id("answer")
            self.items[fallback_id] = {"phase": "final_answer"}
            emitted.extend(
                self._emit_text(
                    fallback_id,
                    output_text,
                    provider_event_type=event_type,
                    phase="final_answer",
                )
            )
            self.completed_text[fallback_id] = ("answer", output_text)
        usage_event = self._usage_event(event_type, response)
        if usage_event is not None:
            emitted.append(usage_event)
        status = _response_status(response)
        if event_type in {"response.incomplete", STREAM_EXHAUSTED_WITHOUT_TERMINAL} or status == "incomplete":
            outcome_kind = "incomplete"
            terminal_kind = "turn_incomplete"
        elif event_type in {"response.cancelled", "response.canceled"} or status in {"cancelled", "canceled"}:
            outcome_kind = "cancelled"
            terminal_kind = "turn_cancelled"
        elif event_type in {"response.failed", "response.error", "error"} or status == "failed":
            outcome_kind = "failed"
            terminal_kind = "turn_failed"
        elif self.tool_calls:
            outcome_kind = "tool_calls"
            terminal_kind = "turn_completed"
        else:
            outcome_kind = "final_answer"
            terminal_kind = "turn_completed"
        terminal_event = self._emit(
            terminal_kind,
            status=outcome_kind,
            terminal=True,
            provider_event_type=event_type,
        )
        emitted.append(terminal_event)
        self._terminal_seen = True
        final_items = [text for channel, text in self.completed_text.values() if channel == "answer"]
        final_text = "".join(final_items) if outcome_kind == "final_answer" else ""
        replay_state = self._replay_state()
        identity_item_id = next(
            (item_id for item_id, (channel, _) in reversed(list(self.completed_text.items())) if channel == "answer"),
            self.tool_calls[-1].identity.item_id if self.tool_calls else "",
        )
        self._outcome = TurnOutcome(
            kind=outcome_kind,
            identity=self._identity(identity_item_id),
            events=tuple(self.events),
            tool_calls=tuple(self.tool_calls),
            final_text=final_text,
            pending_tool_call_ids=tuple(self.pending_call_ids) if outcome_kind == "tool_calls" else (),
            terminal_event_seen=True,
            error=(
                self._error_message(event, response)
                if outcome_kind == "failed"
                else STREAM_EXHAUSTED_WITHOUT_TERMINAL
                if event_type == STREAM_EXHAUSTED_WITHOUT_TERMINAL
                else _response_incomplete_reason(response)
                if outcome_kind == "incomplete"
                else ""
            ),
            replay_state=replay_state,
        )
        return emitted

    def _usage_event(self, event_type: str, response: Mapping[str, Any]) -> LLMProtocolEvent | None:
        usage = _as_dict(response.get("usage"))
        if not usage:
            return None
        return self._emit(
            "usage_updated",
            status="observed",
            provider_event_type=event_type,
            diagnostic_summary=usage_diagnostic_summary_from_payload(usage),
        )

    def _capture_replay_item(self, item_id: str, item: Mapping[str, Any]) -> None:
        if not any(key in item for key in ("encrypted_content", "signature", "summary")):
            return
        payload = json.dumps(_thaw(item), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.replay_items.append(OpaqueReplayItem(item_id=item_id, payload=payload))

    def _replay_state(self) -> ProviderReplayState | None:
        if not self.replay_items and not self.response_id:
            return None
        return ProviderReplayState(
            issuer=self.adapter_id,
            provider_id=str(getattr(self.route, "provider_id", "") or ""),
            endpoint_fingerprint=endpoint_fingerprint(str(getattr(self.route, "runtime_endpoint", "") or "")),
            model_id=str(getattr(self.route, "model_id", "") or ""),
            wire_protocol=WireProtocol.RESPONSES,
            opaque_items=tuple(self.replay_items),
            response_id=self.response_id,
            pending_call_ids=tuple(self.pending_call_ids),
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

    def _event_item_id(self, event: Mapping[str, Any], kind: str) -> str:
        item_id = str(event.get("item_id") or event.get("output_item_id") or "")
        return item_id or self._fallback_item_id(kind)

    def _item_id(self, item: Mapping[str, Any], kind: str) -> str:
        item_id = str(item.get("id") or item.get("item_id") or item.get("call_id") or "")
        return item_id or self._fallback_item_id(kind)

    def _fallback_item_id(self, kind: str) -> str:
        return f"responses:{self.scope.invocation_id}:{kind}:{len(self.items)}"

    def _item_phase(self, item_id: str, item: Mapping[str, Any]) -> str:
        phase = str(item.get("phase") or self.items.get(item_id, {}).get("phase") or "").strip().lower()
        return "commentary" if phase in {"commentary", "analysis"} else "final_answer"

    @staticmethod
    def _error_message(event: Mapping[str, Any], response: Mapping[str, Any]) -> str:
        error = _as_dict(event.get("error")) or _as_dict(response.get("error"))
        return str(error.get("message") or response.get("status_details") or "Responses request failed")
