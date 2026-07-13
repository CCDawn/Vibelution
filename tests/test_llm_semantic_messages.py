from types import SimpleNamespace

import pytest

from core.llm.protocols import WireProtocol
from core.llm.provider_replay_state import OpaqueReplayItem, ProviderReplayState, endpoint_fingerprint
from core.llm.semantic_messages import (
    ImagePart,
    InvocationScope,
    ReasoningReplayPart,
    SemanticGenerationSettings,
    SemanticMessage,
    SemanticModelRequest,
    SemanticToolDefinition,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from core.llm.semantic_projector import (
    SemanticProjectionError,
    SemanticProjectionInput,
    project_semantic_request,
)
from core.llm.types import (
    CanonicalItemIdentity,
    CanonicalToolCall,
    CanonicalToolResult,
    LLMProtocolEvent,
    TurnOutcome,
)
from core.llm.wire.registry import WireAdapterRegistry
from core.llm.wire.types import BuiltPayload


def identity(*, revision: int = 0) -> CanonicalItemIdentity:
    return CanonicalItemIdentity(
        session_id="session-1",
        turn_id="turn-1",
        invocation_id="invocation-1",
        iteration=2,
        item_id="item-1",
        item_revision=revision,
    )


def test_semantic_request_preserves_parts_without_openai_wire_shape():
    tool_call = CanonicalToolCall(
        identity=identity(),
        call_id="call-1",
        name="lookup",
        arguments={"query": "moon"},
    )
    tool_result = CanonicalToolResult(
        identity=identity(revision=1),
        call_id="call-1",
        tool_name="lookup",
        output="result",
    )
    assistant_message = SemanticMessage(
        role="assistant",
        parts=(
            TextPart("progress"),
            ImagePart(uri="memory://image-1", media_type="image/png"),
            ToolCallPart(tool_call),
            ReasoningReplayPart("replay-item-1"),
        ),
    )
    tool_message = SemanticMessage(role="tool", parts=(ToolResultPart(tool_result),))
    request = SemanticModelRequest(
        scope=InvocationScope(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-1",
            iteration=2,
        ),
        messages=(assistant_message, tool_message),
        tools=(
            SemanticToolDefinition(
                name="lookup",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
        ),
        settings=SemanticGenerationSettings(max_output_tokens=64, stream=True),
    )

    assert request.messages[0].parts == assistant_message.parts
    assert request.messages[0].parts[2].call is tool_call
    assert request.messages[0].parts[3].replay_item_id == "replay-item-1"
    assert request.messages[1].parts[0].result is tool_result
    assert not hasattr(request.messages[0], "tool_calls")
    with pytest.raises(TypeError):
        tool_call.arguments["query"] = "changed"
    with pytest.raises(TypeError):
        request.tools[0].input_schema["properties"]["query"]["type"] = "number"


def _project(messages):
    return project_semantic_request(
        SemanticProjectionInput(
            messages=messages,
            tools=(),
            scope=InvocationScope(session_id="session-1", turn_id="turn-1", invocation_id="invocation-1", iteration=0),
            settings=SemanticGenerationSettings(max_output_tokens=64),
            tool_to_schema=lambda tool: tool,
        )
    )


def test_semantic_projector_preserves_complete_parallel_tool_chain():
    request = _project(
        (
            {"role": "user", "content": "look up both"},
            {
                "role": "assistant",
                "content": "checking",
                "tool_calls": (
                    {"id": "call-a", "name": "first", "args": {"value": "a"}},
                    {"id": "call-b", "name": "second", "args": {"value": "b"}},
                ),
            },
            {"role": "tool", "tool_call_id": "call-a", "content": "A"},
            {"role": "tool", "tool_call_id": "call-b", "content": "B"},
            {"role": "assistant", "content": "both done"},
            {"role": "user", "content": "continue"},
        )
    )

    calls = [part.call.call_id for part in request.messages[1].parts if isinstance(part, ToolCallPart)]
    results = [message.parts[0].result.call_id for message in request.messages[2:4]]
    assert calls == ["call-a", "call-b"]
    assert results == ["call-a", "call-b"]
    assert [message.role for message in request.messages] == ["user", "assistant", "tool", "tool", "assistant", "user"]


def test_semantic_projector_rejects_incomplete_tool_chain():
    with pytest.raises(SemanticProjectionError) as error:
        _project(
            (
                {"role": "assistant", "tool_calls": ({"id": "call-a", "name": "first", "args": {}},)},
            )
        )

    assert error.value.code == "unresolved_tool_call"


def test_semantic_projector_allows_parallel_results_in_semantic_completion_order():
    request = _project(
        (
            {
                "role": "assistant",
                "tool_calls": (
                    {"id": "call-a", "name": "first", "args": {}},
                    {"id": "call-b", "name": "second", "args": {}},
                ),
            },
            {"role": "tool", "tool_call_id": "call-b", "content": "B"},
            {"role": "tool", "tool_call_id": "call-a", "content": "A"},
            {"role": "assistant", "content": "both done"},
        )
    )

    assert [message.parts[0].result.call_id for message in request.messages[1:3]] == ["call-b", "call-a"]


@pytest.mark.parametrize(
    "interruption",
    [
        {"role": "user", "content": "continue too early"},
        {"role": "assistant", "content": "ordinary assistant text"},
    ],
)
def test_semantic_projector_rejects_message_interrupting_unresolved_parallel_calls(interruption):
    with pytest.raises(SemanticProjectionError) as error:
        _project(
            (
                {
                    "role": "assistant",
                    "tool_calls": (
                        {"id": "call-a", "name": "first", "args": {}},
                        {"id": "call-b", "name": "second", "args": {}},
                    ),
                },
                {"role": "tool", "tool_call_id": "call-b", "content": "B"},
                interruption,
            )
        )

    assert error.value.code == "interrupted_tool_chain"


def test_semantic_request_requires_explicit_non_empty_invocation_scope():
    with pytest.raises(ValueError, match="invocation scope"):
        InvocationScope(session_id="", turn_id="", invocation_id="", iteration=0)

    regular = InvocationScope(session_id="session-1", turn_id="turn-1", invocation_id="invocation-1", iteration=0)
    assert regular.is_synthetic is False

    synthetic = InvocationScope.for_synthetic(invocation_id="health-probe-1", purpose="health_probe")
    assert synthetic.is_synthetic is True
    assert synthetic.session_id.startswith("synthetic:")
    assert synthetic.turn_id.startswith("synthetic:")


def test_protocol_event_identity_uses_composite_item_revision_not_sequence():
    first = LLMProtocolEvent(
        kind="answer_delta",
        sequence=7,
        session_id="session-1",
        turn_id="turn-1",
        invocation_id="invocation-1",
        iteration=2,
        item_id="item-1",
        item_revision=0,
        channel="answer",
        text="hello",
    )
    revised = LLMProtocolEvent(
        kind="item_completed",
        sequence=8,
        session_id="session-1",
        turn_id="turn-1",
        invocation_id="invocation-1",
        iteration=2,
        item_id="item-1",
        item_revision=1,
        channel="answer",
        terminal=True,
    )

    assert first.identity != revised.identity
    assert first.identity.item_id == revised.identity.item_id
    assert first.sequence != revised.sequence
    with pytest.raises(TypeError):
        first.diagnostic_summary["raw_payload"] = {"secret": True}


class StubAdapter:
    def __init__(self, protocol: WireProtocol, adapter_id: str) -> None:
        self.wire_protocol = protocol
        self.adapter_id = adapter_id

    def encode_request(self, request: SemanticModelRequest, *, route) -> BuiltPayload:
        return BuiltPayload(body={"model": route.effective_model, "semantic_message_count": len(request.messages)})

    def decode_response(self, response, *, route, scope):
        return TurnOutcome.final_answer(identity=identity(), text=str(response))

    def decode_stream(self, events, *, route, scope):
        return iter(())

    def encode_tool_results(self, results):
        return list(results)


def test_wire_registry_dispatches_by_immutable_route_and_rejects_protocol_mismatch():
    registry = WireAdapterRegistry()
    responses = StubAdapter(WireProtocol.RESPONSES, "responses")
    registry.register(responses)
    route = SimpleNamespace(adapter_id="responses", wire_protocol=WireProtocol.RESPONSES)

    assert registry.resolve(route) is responses

    mismatched_route = SimpleNamespace(adapter_id="responses", wire_protocol=WireProtocol.CHAT_COMPLETIONS)
    with pytest.raises(ValueError, match="wire protocol"):
        registry.resolve(mismatched_route)


def test_wire_registry_rejects_cross_route_replay_before_adapter_send():
    class CountingAdapter(StubAdapter):
        called = False

        def encode_request(self, request: SemanticModelRequest, *, route) -> BuiltPayload:
            self.called = True
            return super().encode_request(request, route=route)

    registry = WireAdapterRegistry()
    adapter = CountingAdapter(WireProtocol.RESPONSES, "responses")
    registry.register(adapter)
    route = SimpleNamespace(
        adapter_id="responses",
        wire_protocol=WireProtocol.RESPONSES,
        provider_id="relay_openai",
        runtime_endpoint="https://relay.example.test/v1",
        model_id="relay_gpt_5_6_luna",
        effective_model="gpt-5.6-luna",
    )
    replay_state = ProviderReplayState(
        issuer="other-adapter",
        provider_id="relay_openai",
        endpoint_fingerprint=endpoint_fingerprint(route.runtime_endpoint),
        model_id=route.model_id,
        wire_protocol=route.wire_protocol,
        opaque_items=(OpaqueReplayItem(item_id="reasoning-1", payload=b"opaque"),),
    )
    request = SemanticModelRequest(
        scope=InvocationScope(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-1",
            iteration=0,
        ),
        messages=(),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=32),
        replay_state=replay_state,
    )

    with pytest.raises(ValueError, match="route identity mismatch"):
        registry.encode_request(route, request)
    assert adapter.called is False


def test_wire_registry_passes_immutable_route_to_stateless_encoder():
    registry = WireAdapterRegistry()
    adapter = StubAdapter(WireProtocol.RESPONSES, "responses")
    registry.register(adapter)
    route = SimpleNamespace(
        adapter_id="responses",
        wire_protocol=WireProtocol.RESPONSES,
        provider_id="relay_openai",
        runtime_endpoint="https://relay.example.test/v1",
        model_id="relay_gpt_5_6_luna",
        effective_model="gpt-5.6-luna",
    )
    request = SemanticModelRequest(
        scope=InvocationScope(session_id="s", turn_id="t", invocation_id="i", iteration=0),
        messages=(),
        tools=(),
        settings=SemanticGenerationSettings(max_output_tokens=32),
    )

    payload = registry.encode_request(route, request)

    assert payload.body["model"] == "gpt-5.6-luna"
