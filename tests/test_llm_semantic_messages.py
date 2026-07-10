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
    message = SemanticMessage(
        role="assistant",
        parts=(
            TextPart("progress"),
            ImagePart(uri="memory://image-1", media_type="image/png"),
            ToolCallPart(tool_call),
            ToolResultPart(tool_result),
            ReasoningReplayPart("replay-item-1"),
        ),
    )
    request = SemanticModelRequest(
        scope=InvocationScope(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-1",
            iteration=2,
        ),
        messages=(message,),
        tools=(
            SemanticToolDefinition(
                name="lookup",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
        ),
        settings=SemanticGenerationSettings(max_output_tokens=64, stream=True),
    )

    assert request.messages[0].parts == message.parts
    assert request.messages[0].parts[2].call is tool_call
    assert request.messages[0].parts[3].result is tool_result
    assert request.messages[0].parts[4].replay_item_id == "replay-item-1"
    assert not hasattr(request.messages[0], "tool_calls")
    with pytest.raises(TypeError):
        tool_call.arguments["query"] = "changed"
    with pytest.raises(TypeError):
        request.tools[0].input_schema["properties"]["query"]["type"] = "number"


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
