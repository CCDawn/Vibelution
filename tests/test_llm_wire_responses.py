import json
from enum import Enum
from types import SimpleNamespace

import pytest

from core.llm.protocols import WireProtocol
from core.llm.provider_replay_state import OpaqueReplayItem, ProviderReplayState, endpoint_fingerprint
from core.llm.semantic_messages import (
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
from core.llm.semantic_projector import SemanticProjectionInput, project_semantic_request
from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, CanonicalToolResult
from core.llm.wire.responses import ResponsesWireAdapter


def route(*, responses_continuation: bool = False, responses_websocket: bool = False):
    return SimpleNamespace(
        adapter_id="responses",
        wire_protocol=WireProtocol.RESPONSES,
        provider_id="relay_openai",
        model_id="relay_gpt_5_6_luna",
        effective_model="gpt-5.6-luna",
        runtime_endpoint="https://relay.example.test/v1",
        compat=SimpleNamespace(
            responses_continuation=responses_continuation,
            responses_websocket=responses_websocket,
        ),
    )


def scope(iteration: int = 0) -> InvocationScope:
    return InvocationScope(
        session_id="session-1",
        turn_id="turn-1",
        invocation_id=f"invocation-{iteration + 1}",
        iteration=iteration,
    )


def identity(item_id: str, *, iteration: int = 0) -> CanonicalItemIdentity:
    current = scope(iteration)
    return CanonicalItemIdentity(
        session_id=current.session_id,
        turn_id=current.turn_id,
        invocation_id=current.invocation_id,
        iteration=current.iteration,
        item_id=item_id,
    )


def test_responses_stateless_history_emits_full_call_output_pairs_without_previous_response_id():
    current_route = route()
    replay_item = {"type": "reasoning", "id": "reasoning-1", "encrypted_content": "ciphertext"}
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(
            OpaqueReplayItem(item_id="reasoning-1", payload=json.dumps(replay_item).encode("utf-8")),
        ),
        response_id="resp-previous",
    )
    call = CanonicalToolCall(
        identity=identity("tool-call-1", iteration=0),
        call_id="call-1",
        name="lookup",
        arguments={"query": "moon"},
    )
    result = CanonicalToolResult(
        identity=identity("tool-result-1", iteration=1),
        call_id="call-1",
        tool_name="lookup",
        output={"value": 42},
    )
    request = SemanticModelRequest(
        scope=scope(1),
        messages=(
            SemanticMessage(role="user", parts=(TextPart("look up the moon"),)),
            SemanticMessage(
                role="assistant",
                parts=(ReasoningReplayPart("reasoning-1"), ToolCallPart(call)),
            ),
            SemanticMessage(role="tool", parts=(ToolResultPart(result),)),
            SemanticMessage(role="assistant", parts=(TextPart("The value is 42."),)),
            SemanticMessage(role="user", parts=(TextPart("continue"),)),
        ),
        tools=(
            SemanticToolDefinition(
                name="lookup",
                description="Lookup data",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
        ),
        settings=SemanticGenerationSettings(max_output_tokens=128, stream=True),
        replay_state=replay_state,
    )

    payload = ResponsesWireAdapter().encode_request(request, route=current_route).body

    assert payload["model"] == "gpt-5.6-luna"
    assert payload["max_output_tokens"] == 128
    assert payload["stream"] is True
    assert "previous_response_id" not in payload
    assert payload["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "look up the moon"}]},
        replay_item,
        {"type": "function_call", "call_id": "call-1", "name": "lookup", "arguments": '{"query": "moon"}'},
        {"type": "function_call_output", "call_id": "call-1", "output": '{"value":42}'},
        {"role": "assistant", "content": [{"type": "output_text", "text": "The value is 42."}]},
        {"role": "user", "content": [{"type": "input_text", "text": "continue"}]},
    ]
    assert payload["input"][-1] == {"role": "user", "content": [{"type": "input_text", "text": "continue"}]}
    assert payload["tools"][0]["parameters"]["properties"]["query"]["type"] == "string"


def test_responses_stateful_continuation_sends_only_pending_call_outputs():
    current_route = route(responses_continuation=True)
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(),
        response_id="resp-previous",
        pending_call_ids=("call-1",),
    )
    call = CanonicalToolCall(
        identity=identity("tool-call-1", iteration=0),
        call_id="call-1",
        name="lookup",
        arguments={"query": "moon"},
    )
    result = CanonicalToolResult(
        identity=identity("tool-result-1", iteration=1),
        call_id="call-1",
        tool_name="lookup",
        output={"value": 42},
    )
    request = SemanticModelRequest(
        scope=scope(1),
        messages=(
            SemanticMessage(role="user", parts=(TextPart("look up the moon"),)),
            SemanticMessage(role="assistant", parts=(ToolCallPart(call),)),
            SemanticMessage(role="tool", parts=(ToolResultPart(result),)),
        ),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=128),
        replay_state=replay_state,
    )

    payload = ResponsesWireAdapter().encode_request(request, route=current_route).body

    assert payload["previous_response_id"] == "resp-previous"
    assert payload["input"] == [
        {"type": "function_call_output", "call_id": "call-1", "output": '{"value":42}'}
    ]


def test_responses_stateful_continuation_preserves_new_user_input_after_pending_output():
    current_route = route(responses_continuation=True)
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(),
        response_id="resp-previous",
        pending_call_ids=("call-1",),
    )
    call = CanonicalToolCall(
        identity=identity("tool-call-1", iteration=0),
        call_id="call-1",
        name="lookup",
        arguments={"query": "moon"},
    )
    result = CanonicalToolResult(
        identity=identity("tool-result-1", iteration=1),
        call_id="call-1",
        tool_name="lookup",
        output={"value": 42},
    )
    request = SemanticModelRequest(
        scope=scope(2),
        messages=(
            SemanticMessage(role="user", parts=(TextPart("look up the moon"),)),
            SemanticMessage(role="assistant", parts=(ToolCallPart(call),)),
            SemanticMessage(role="tool", parts=(ToolResultPart(result),)),
            SemanticMessage(role="user", parts=(TextPart("continue"),)),
        ),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=128),
        replay_state=replay_state,
    )

    payload = ResponsesWireAdapter().encode_request(request, route=current_route).body

    assert payload["previous_response_id"] == "resp-previous"
    assert payload["input"] == [
        {"type": "function_call_output", "call_id": "call-1", "output": '{"value":42}'},
        {"role": "user", "content": [{"type": "input_text", "text": "continue"}]},
    ]


def test_responses_stateful_turn_continuation_sends_only_context_after_previous_assistant():
    current_route = route(responses_continuation=True)
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(
            OpaqueReplayItem(
                item_id="reasoning-previous",
                payload=json.dumps(
                    {"type": "reasoning", "id": "reasoning-previous", "encrypted_content": "ciphertext"}
                ).encode("utf-8"),
            ),
        ),
        response_id="resp-previous",
    )
    request = SemanticModelRequest(
        scope=scope(2),
        messages=(
            SemanticMessage(role="system", parts=(TextPart("stable instructions"),)),
            SemanticMessage(role="user", parts=(TextPart("first question"),)),
            SemanticMessage(role="assistant", parts=(TextPart("first answer"),)),
            SemanticMessage(role="system", parts=(TextPart("current runtime context"),)),
            SemanticMessage(role="user", parts=(TextPart("follow up"),)),
        ),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=128),
        replay_state=replay_state,
    )

    payload = ResponsesWireAdapter().encode_request(request, route=current_route).body

    assert payload["previous_response_id"] == "resp-previous"
    assert payload["input"] == [
        {"role": "system", "content": [{"type": "input_text", "text": "current runtime context"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "follow up"}]},
    ]


def test_responses_websocket_keeps_full_http_payload_and_sidecars_incremental_input():
    current_route = route(responses_websocket=True)
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(),
        response_id="resp-previous",
    )
    request = SemanticModelRequest(
        scope=scope(2),
        messages=(
            SemanticMessage(role="system", parts=(TextPart("stable instructions"),)),
            SemanticMessage(role="user", parts=(TextPart("first question"),)),
            SemanticMessage(role="assistant", parts=(TextPart("first answer"),)),
            SemanticMessage(role="system", parts=(TextPart("current runtime context"),)),
            SemanticMessage(role="user", parts=(TextPart("follow up"),)),
        ),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=128, stream=True),
        replay_state=replay_state,
    )

    payload = ResponsesWireAdapter().encode_request(request, route=current_route).body

    assert "previous_response_id" not in payload
    assert [item["role"] for item in payload["input"]] == [
        "system",
        "user",
        "assistant",
        "system",
        "user",
    ]
    assert payload["_vibelution_responses_websocket"] == {
        "enabled": True,
        "previous_response_id": "resp-previous",
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": "current runtime context"}]},
            {"role": "user", "content": [{"type": "input_text", "text": "follow up"}]},
        ],
    }


def test_responses_turn_continuation_without_assistant_boundary_falls_back_to_full_input():
    current_route = route(responses_continuation=True)
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(),
        response_id="resp-stale",
    )
    request = SemanticModelRequest(
        scope=scope(1),
        messages=(SemanticMessage(role="user", parts=(TextPart("fresh conversation"),)),),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=128),
        replay_state=replay_state,
    )

    payload = ResponsesWireAdapter().encode_request(request, route=current_route).body

    assert "previous_response_id" not in payload
    assert payload["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "fresh conversation"}]}
    ]


def test_responses_stateful_continuation_requires_every_pending_call_output():
    current_route = route(responses_continuation=True)
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(),
        response_id="resp-previous",
        pending_call_ids=("call-missing",),
    )
    request = SemanticModelRequest(
        scope=scope(1),
        messages=(SemanticMessage(role="user", parts=(TextPart("continue"),)),),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=128),
        replay_state=replay_state,
    )

    with pytest.raises(ValueError, match="missing function_call_output"):
        ResponsesWireAdapter().encode_request(request, route=current_route)


def test_responses_rejects_unreferenced_opaque_replay_instead_of_auto_injecting_it():
    current_route = route()
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(
            OpaqueReplayItem(
                item_id="reasoning-1",
                payload=json.dumps({"type": "reasoning", "id": "reasoning-1", "encrypted_content": "ciphertext"}).encode("utf-8"),
            ),
        ),
        response_id="resp-previous",
    )
    request = SemanticModelRequest(
        scope=scope(),
        messages=(SemanticMessage(role="user", parts=(TextPart("fresh input"),)),),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=32),
        replay_state=replay_state,
    )

    with pytest.raises(ValueError, match="opaque replay items must be explicitly referenced"):
        ResponsesWireAdapter().encode_request(request, route=current_route)


def test_semantic_projector_to_responses_preserves_replay_text_call_output_order():
    current_route = route()
    replay_item = {"type": "reasoning", "id": "reasoning-1", "encrypted_content": "ciphertext"}
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(
            OpaqueReplayItem(item_id="reasoning-1", payload=json.dumps(replay_item).encode("utf-8")),
        ),
        response_id="resp-previous",
    )
    request = project_semantic_request(
        SemanticProjectionInput(
            messages=(
                {
                    "role": "assistant",
                    "content": "checking",
                    "tool_calls": (
                        {"id": "call-1", "name": "lookup", "args": {"query": "moon"}},
                    ),
                    "additional_kwargs": {"reasoning_replay_item_id": "reasoning-1"},
                },
                {"role": "tool", "tool_call_id": "call-1", "content": "result"},
            ),
            tools=(),
            scope=scope(),
            settings=SemanticGenerationSettings(max_output_tokens=32),
            tool_to_schema=lambda tool: tool,
            replay_state=replay_state,
        )
    )

    payload = ResponsesWireAdapter().encode_request(request, route=current_route).body

    assert payload["input"] == [
        replay_item,
        {"role": "assistant", "content": [{"type": "output_text", "text": "checking"}]},
        {"type": "function_call", "call_id": "call-1", "name": "lookup", "arguments": '{"query": "moon"}'},
        {"type": "function_call_output", "call_id": "call-1", "output": "result"},
    ]
    assert "previous_response_id" not in payload


def test_responses_rejects_plain_reasoning_text_instead_of_silent_drop():
    request = SemanticModelRequest(
        scope=scope(),
        messages=(SemanticMessage(role="assistant", parts=(ReasoningTextPart("private reasoning"),)),),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=32),
    )

    with pytest.raises(ValueError, match="reasoning text"):
        ResponsesWireAdapter().encode_request(request, route=route())


def test_responses_rejects_explicit_non_reasoning_opaque_replay_payload():
    current_route = route()
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id=current_route.provider_id,
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(
            OpaqueReplayItem(
                item_id="reasoning-1",
                payload=b'{"id":"reasoning-1","type":"message","content":[]}',
            ),
        ),
    )
    request = SemanticModelRequest(
        scope=scope(),
        messages=(SemanticMessage(role="assistant", parts=(ReasoningReplayPart("reasoning-1"),)),),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=32),
        replay_state=replay_state,
    )

    with pytest.raises(ValueError, match="type `reasoning`"):
        ResponsesWireAdapter().encode_request(request, route=current_route)


def test_responses_encoder_rejects_cross_route_replay_without_registry_bypass():
    current_route = route()
    replay_state = ProviderReplayState(
        issuer="responses",
        provider_id="other-provider",
        endpoint_fingerprint=endpoint_fingerprint(current_route.runtime_endpoint),
        model_id=current_route.model_id,
        wire_protocol=current_route.wire_protocol,
        opaque_items=(OpaqueReplayItem(item_id="reasoning-1", payload=b'{}'),),
    )
    request = SemanticModelRequest(
        scope=scope(),
        messages=(SemanticMessage(role="assistant", parts=(ReasoningReplayPart("reasoning-1"),)),),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=32),
        replay_state=replay_state,
    )

    with pytest.raises(ValueError, match="route identity mismatch"):
        ResponsesWireAdapter().encode_request(request, route=current_route)


def test_responses_commentary_tool_continuation_then_final_has_one_final_answer():
    adapter = ResponsesWireAdapter()
    first_stream = adapter.decode_stream(
        [
            {"type": "response.created", "response": {"id": "resp-1"}},
            {
                "type": "response.output_item.added",
                "item": {"type": "message", "id": "commentary-1", "role": "assistant", "phase": "commentary"},
            },
            {"type": "response.output_text.delta", "item_id": "commentary-1", "delta": "Checking."},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "id": "commentary-1",
                    "role": "assistant",
                    "phase": "commentary",
                    "content": [{"type": "output_text", "text": "Checking."}],
                },
            },
            {
                "type": "response.output_item.added",
                "item": {"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "lookup", "arguments": ""},
            },
            {"type": "response.function_call_arguments.delta", "item_id": "fc-1", "call_id": "call-1", "delta": '{"query":"moon"}'},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "fc-1",
                    "call_id": "call-1",
                    "name": "lookup",
                    "arguments": '{"query":"moon"}',
                },
            },
            {"type": "response.completed", "response": {"id": "resp-1", "status": "completed", "output": None}},
        ],
        route=route(),
        scope=scope(0),
    )
    first_events = tuple(first_stream)

    assert first_stream.outcome.kind == "tool_calls"
    assert first_stream.outcome.tool_calls[0].call_id == "call-1"
    assert first_stream.outcome.pending_tool_call_ids == ("call-1",)
    assert any(event.kind == "commentary_delta" and event.text == "Checking." for event in first_events)
    assert not any(event.kind == "answer_delta" for event in first_events)

    final_stream = adapter.decode_stream(
        [
            {"type": "response.created", "response": {"id": "resp-2"}},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "id": "answer-1",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": "The result is 42."}],
                },
            },
            {"type": "response.completed", "response": {"id": "resp-2", "status": "completed", "output": None}},
        ],
        route=route(),
        scope=scope(1),
    )
    final_events = tuple(final_stream)

    assert final_stream.outcome.kind == "final_answer"
    assert final_stream.outcome.final_text == "The result is 42."
    assert sum(event.kind == "answer_delta" for event in final_events) == 1
    assert sum(event.kind == "turn_completed" for event in final_events) == 1


def test_responses_non_stream_and_stream_reconstruct_same_final_from_completed_items():
    adapter = ResponsesWireAdapter()
    response = {
        "id": "resp-final",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "commentary-1",
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "Working."}],
            },
            {
                "type": "message",
                "id": "answer-1",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Done."}],
            },
        ],
    }
    non_stream = adapter.decode_response(response, route=route(), scope=scope())
    stream = adapter.decode_stream(
        [
            {"type": "response.output_item.done", "item": response["output"][0]},
            {"type": "response.output_item.done", "item": response["output"][1]},
            {"type": "response.completed", "response": {**response, "output": None}},
        ],
        route=route(),
        scope=scope(),
    )
    tuple(stream)

    assert non_stream.kind == stream.outcome.kind == "final_answer"
    assert non_stream.final_text == stream.outcome.final_text == "Done."
    assert non_stream.events[0].kind == stream.outcome.events[0].kind == "turn_started"
    assert [event.channel for event in non_stream.events if event.kind.endswith("_delta")] == ["commentary", "answer"]


def test_responses_terminal_contained_output_is_yielded_to_stream_consumers():
    decoded = ResponsesWireAdapter().decode_stream(
        [
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-final",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "id": "answer-1",
                            "role": "assistant",
                            "phase": "final_answer",
                            "content": [{"type": "output_text", "text": "Recovered."}],
                        }
                    ],
                },
            }
        ],
        route=route(),
        scope=scope(),
    )

    assert iter(decoded) is decoded
    events = tuple(decoded)
    assert any(event.kind == "answer_delta" and event.text == "Recovered." for event in events)
    assert decoded.outcome.final_text == "Recovered."


def test_responses_accepts_string_enum_event_types_from_litellm():
    class ResponsesApiStreamEvents(str, Enum):
        RESPONSE_OUTPUT_ITEM_DONE = "response.output_item.done"
        RESPONSE_COMPLETED = "response.completed"

    decoded = ResponsesWireAdapter().decode_stream(
        [
            {
                "type": ResponsesApiStreamEvents.RESPONSE_OUTPUT_ITEM_DONE,
                "item": {
                    "type": "message",
                    "id": "answer-1",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": "Recovered from enum events."}],
                },
            },
            {
                "type": ResponsesApiStreamEvents.RESPONSE_COMPLETED,
                "response": {"id": "resp-final", "status": "completed", "output": None},
            },
        ],
        route=route(),
        scope=scope(),
    )

    tuple(decoded)

    assert decoded.outcome.kind == "final_answer"
    assert decoded.outcome.final_text == "Recovered from enum events."


@pytest.mark.parametrize(
    ("terminal_event", "expected_kind"),
    [
        ({"type": "response.incomplete", "response": {"id": "resp-1", "status": "incomplete"}}, "incomplete"),
        ({"type": "response.cancelled", "response": {"id": "resp-1", "status": "cancelled"}}, "cancelled"),
    ],
)
def test_responses_non_success_terminal_events_never_return_final_answer(terminal_event, expected_kind):
    decoded = ResponsesWireAdapter().decode_stream([terminal_event], route=route(), scope=scope())
    events = tuple(decoded)

    assert decoded.outcome.kind == expected_kind
    assert decoded.outcome.final_text == ""
    assert events[-1].terminal is True


def test_responses_incomplete_preserves_provider_reason_for_diagnostics():
    decoded = ResponsesWireAdapter().decode_stream(
        [
            {
                "type": "response.incomplete",
                "response": {
                    "id": "resp-incomplete",
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                },
            }
        ],
        route=route(),
        scope=scope(),
    )

    tuple(decoded)

    assert decoded.outcome.kind == "incomplete"
    assert decoded.outcome.error == "max_output_tokens"


def test_responses_tool_result_encoder_preserves_call_id():
    result = CanonicalToolResult(
        identity=identity("tool-result-1", iteration=1),
        call_id="call-1",
        tool_name="lookup",
        output="ok",
    )

    assert ResponsesWireAdapter().encode_tool_results([result]) == [
        {"type": "function_call_output", "call_id": "call-1", "output": "ok"}
    ]
