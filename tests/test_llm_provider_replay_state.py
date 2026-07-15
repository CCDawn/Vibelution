import pytest

from core.llm.protocols import WireProtocol
from core.llm.provider_replay_state import (
    MAX_REPLAY_BYTES,
    MAX_REPLAY_ITEMS,
    OpaqueReplayItem,
    ProviderReplayState,
    ReplayStateMismatchError,
    endpoint_fingerprint,
)
from core.llm.semantic_messages import InvocationScope, ReasoningReplayPart, SemanticGenerationSettings
from core.llm.semantic_projector import SemanticProjectionInput, project_semantic_request


def make_state(**overrides) -> ProviderReplayState:
    values = {
        "issuer": "responses-adapter",
        "provider_id": "relay_openai",
        "endpoint_fingerprint": endpoint_fingerprint("https://relay.example.test/v1"),
        "model_id": "relay_gpt_5_6_luna",
        "wire_protocol": WireProtocol.RESPONSES,
        "opaque_items": (OpaqueReplayItem(item_id="reasoning-1", payload=b"opaque-secret"),),
    }
    values.update(overrides)
    return ProviderReplayState(**values)


def test_replay_state_accepts_only_exact_issuer_provider_endpoint_model_and_wire_tuple():
    state = make_state()

    assert state.require_compatible(
        issuer="responses-adapter",
        provider_id="relay_openai",
        endpoint_fingerprint=endpoint_fingerprint("https://relay.example.test/v1/"),
        model_id="relay_gpt_5_6_luna",
        wire_protocol=WireProtocol.RESPONSES,
    ) is state


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issuer", "chat-adapter"),
        ("provider_id", "other-relay"),
        ("endpoint_fingerprint", endpoint_fingerprint("https://other.example.test/v1")),
        ("model_id", "other-model"),
        ("wire_protocol", WireProtocol.CHAT_COMPLETIONS),
    ],
)
def test_replay_state_rejects_cross_route_replay_without_leaking_opaque_data(field, value):
    state = make_state()
    expected = {
        "issuer": state.issuer,
        "provider_id": state.provider_id,
        "endpoint_fingerprint": state.endpoint_fingerprint,
        "model_id": state.model_id,
        "wire_protocol": state.wire_protocol,
    }
    expected[field] = value

    with pytest.raises(ReplayStateMismatchError) as error:
        state.require_compatible(**expected)

    message = str(error.value)
    assert "opaque-secret" not in message
    assert "relay.example.test" not in message
    assert "other.example.test" not in message


def test_replay_state_repr_and_summary_never_expose_opaque_payload():
    state = make_state()

    assert "opaque-secret" not in repr(state)
    assert state.byte_size == len(b"opaque-secret")
    assert state.safe_summary() == {
        "issuer": "responses-adapter",
        "providerId": "relay_openai",
        "endpointFingerprint": state.endpoint_fingerprint,
        "modelId": "relay_gpt_5_6_luna",
        "wireProtocol": "responses",
        "itemCount": 1,
        "byteSize": len(b"opaque-secret"),
        "hasResponseId": False,
        "pendingCallCount": 0,
    }


def test_replay_state_enforces_item_and_byte_limits():
    too_many = tuple(OpaqueReplayItem(item_id=f"item-{index}", payload=b"x") for index in range(MAX_REPLAY_ITEMS + 1))
    with pytest.raises(ValueError, match="item limit"):
        make_state(opaque_items=too_many)

    with pytest.raises(ValueError, match="byte limit"):
        make_state(opaque_items=(OpaqueReplayItem(item_id="large", payload=b"x" * (MAX_REPLAY_BYTES + 1)),))

    with pytest.raises(ValueError, match="pending call ids must be unique"):
        make_state(pending_call_ids=("call-1", "call-1"))

    with pytest.raises(ValueError, match="pending call id byte limit"):
        make_state(pending_call_ids=("x" * 1025,))


def test_without_response_id_preserves_opaque_replay_but_clears_stateful_continuation():
    state = make_state(response_id="resp-1", pending_call_ids=("call-1",))

    stateless = state.without_response_id()

    assert stateless.response_id == ""
    assert stateless.pending_call_ids == ()
    assert stateless.opaque_items == state.opaque_items
    assert stateless.safe_summary()["pendingCallCount"] == 0


def test_route_switch_projection_clears_replay_bookmark_when_state_is_discarded():
    request = project_semantic_request(
        SemanticProjectionInput(
            messages=(
                {
                    "role": "assistant",
                    "content": "canonical answer",
                    "additional_kwargs": {"reasoning_replay_item_id": "reasoning-1"},
                },
                {"role": "user", "content": "continue"},
            ),
            tools=(),
            scope=InvocationScope(session_id="session-1", turn_id="turn-2", invocation_id="invocation-2", iteration=0),
            settings=SemanticGenerationSettings(max_output_tokens=32),
            tool_to_schema=lambda tool: tool,
            replay_state=None,
        )
    )

    assert all(
        not isinstance(part, ReasoningReplayPart)
        for message in request.messages
        for part in message.parts
    )
