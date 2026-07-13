import json
from types import SimpleNamespace

import pytest

from core.llm.protocols import WireProtocol
from core.llm.provider_replay_state import OpaqueReplayItem, ProviderReplayState, endpoint_fingerprint
from core.llm.semantic_messages import (
    InvocationScope,
    ReasoningReplayPart,
    SemanticGenerationSettings,
    SemanticMessage,
    SemanticModelRequest,
    SemanticToolDefinition,
    TextPart,
    ToolResultPart,
)
from core.llm.types import CanonicalItemIdentity, CanonicalToolResult
from core.llm.wire.responses import ResponsesWireAdapter


def route():
    return SimpleNamespace(
        adapter_id="responses",
        wire_protocol=WireProtocol.RESPONSES,
        provider_id="relay_openai",
        model_id="relay_gpt_5_6_luna",
        effective_model="gpt-5.6-luna",
        runtime_endpoint="https://relay.example.test/v1",
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


def test_responses_encoder_uses_semantic_ir_and_preserves_replay_and_tool_result_identity():
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
            SemanticMessage(role="assistant", parts=(ReasoningReplayPart("reasoning-1"),)),
            SemanticMessage(role="tool", parts=(ToolResultPart(result),)),
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
    assert replay_item in payload["input"]
    assert {"type": "function_call_output", "call_id": "call-1", "output": '{"value":42}'} in payload["input"]
    assert payload["input"][-1] == {"role": "user", "content": [{"type": "input_text", "text": "continue"}]}
    assert payload["tools"][0]["parameters"]["properties"]["query"]["type"] == "string"


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
