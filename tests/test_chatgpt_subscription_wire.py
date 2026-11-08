from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from core.llm.chatgpt_subscription.wire import (
    ChatGPTSubscriptionWireAdapter,
    SUBSCRIPTION_API_BASE,
    UNSUPPORTED_SUBSCRIPTION_FIELDS,
    normalize_subscription_event,
    sanitize_subscription_payload,
    subscription_error_from_event,
)
from core.llm.protocols import WireProtocol
from core.llm.semantic_messages import (
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
from core.llm.types import CanonicalToolResult
from core.llm.wire.responses import ResponsesWireAdapter


def route():
    return SimpleNamespace(
        provider_id="chatgpt", model_id="chatgpt-model", effective_model="account-model",
        runtime_endpoint=SUBSCRIPTION_API_BASE, wire_protocol=WireProtocol.RESPONSES,
        compat=SimpleNamespace(responses_continuation=True, responses_websocket=True),
    )


def scope():
    return InvocationScope(session_id="session", turn_id="turn", invocation_id="invocation", iteration=0)


def request(*, messages=None, replay_state=None):
    return SemanticModelRequest(
        scope=scope(), messages=messages or (SemanticMessage(role="user", parts=(TextPart("look up"),)),),
        tools=(SemanticToolDefinition(name="lookup", description="Lookup", input_schema={"type": "object"}),),
        settings=SemanticGenerationSettings(max_output_tokens=32, stream=False, temperature=0.3, top_p=0.7),
        replay_state=replay_state,
    )


def test_subscription_body_enforces_stateless_stream_without_mutating_input():
    payload = {
        "model": "account-model",
        "input": [{"role": "system", "content": "policy"}, {"role": "user", "content": "hello"}],
        "stream": False,
        "store": True,
        "previous_response_id": "previous",
        "max_output_tokens": 32,
        "temperature": 0.2,
        "top_p": 0.8,
        "metadata": {"private": "value"},
    }
    original = copy.deepcopy(payload)

    body = sanitize_subscription_payload(payload)

    assert body == {
        "model": "account-model",
        "input": [{"role": "developer", "content": "policy"}, {"role": "user", "content": "hello"}],
        "stream": True,
        "store": False,
    }
    assert payload == original


@pytest.mark.parametrize("field", sorted(UNSUPPORTED_SUBSCRIPTION_FIELDS))
def test_subscription_body_removes_all_forbidden_fields(field):
    body = sanitize_subscription_payload({"model": "m", "input": [], field: "forbidden"})
    assert field not in body


@pytest.mark.parametrize("field", ["api_key", "base_url", "timeout", "extra_headers", "extra_body", "service_tier", "future_unknown"])
def test_subscription_rejects_transport_and_unknown_fields_without_echoing_values(field):
    with pytest.raises(ValueError) as caught:
        sanitize_subscription_payload({"input": [], field: "private-value"})
    assert "private-value" not in str(caught.value)


def test_subscription_tool_namespace_is_idempotent_and_preserves_local_name():
    payload = {
        "input": [
            {"type": "function_call", "name": "lookup", "call_id": "call", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call", "output": "ok"},
        ],
        "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
    }
    body = sanitize_subscription_payload(payload)
    assert body["tools"][0]["type"] == "namespace"
    assert body["tools"][0]["name"] == "functions"
    assert body["tools"][0]["tools"][0]["name"] == "lookup"
    assert body["input"][0]["namespace"] == "functions"
    assert body["input"][0]["name"] == "lookup"
    assert body["input"][1] == payload["input"][1]
    assert sanitize_subscription_payload(body) == body


@pytest.mark.parametrize("kind", ["tool_search", "mcp", "computer", "image_generation", "file_search", "code_interpreter", "programmatic_tool_calling"])
def test_subscription_rejects_hosted_or_tool_search_tools(kind):
    with pytest.raises(ValueError):
        sanitize_subscription_payload({"input": [], "tools": [{"type": kind}]})


@pytest.mark.parametrize("tool", [
    {"type": "namespace", "name": "foreign", "tools": []},
    {"type": "function", "name": "lookup", "defer_loading": True},
    {"type": "function", "name": "lookup", "allowed_callers": ["programmatic"]},
])
def test_subscription_rejects_unroutable_local_tools(tool):
    with pytest.raises(ValueError):
        sanitize_subscription_payload({"input": [], "tools": [tool]})


def test_subscription_custom_tools_and_additional_tools_are_namespaced():
    tool = {"type": "custom", "name": "patch", "format": {"type": "text"}}
    body = sanitize_subscription_payload({"input": [{"type": "additional_tools", "tools": [tool]}]})
    assert body["input"][0]["tools"][0]["tools"] == [tool]


@pytest.mark.parametrize("kind", ["input_audio", "input_video", "text", "image_url"])
def test_subscription_rejects_unsupported_message_content(kind):
    with pytest.raises(ValueError, match="content"):
        sanitize_subscription_payload({"input": [{"role": "user", "content": [{"type": kind}]}]})


def test_subscription_preserves_supported_images_files_and_strict_output_schema():
    content = [{"type": "input_image", "image_url": "data:image/png;base64,AA=="}, {"type": "input_file", "filename": "x.txt", "file_data": "data:text/plain;base64,AA=="}]
    text = {"format": {"type": "json_schema", "name": "result", "strict": True, "schema": {"type": "object"}}}
    body = sanitize_subscription_payload({"input": [{"role": "user", "content": content}], "text": text})
    assert body["input"][0]["content"] == content and body["text"] == text


def test_subscription_adapter_keeps_full_tool_history_and_encrypted_reasoning():
    adapter = ChatGPTSubscriptionWireAdapter()
    reasoning = {"id": "reasoning", "type": "reasoning", "encrypted_content": "opaque", "summary": []}
    tool = {"id": "tool", "type": "function_call", "namespace": "functions", "name": "lookup", "call_id": "call", "arguments": '{"x":1}'}
    events = [
        {"type": "response.created", "response": {"id": "response"}},
        {"type": "response.output_item.done", "item": reasoning},
        {"type": "response.output_item.done", "item": tool},
        {"type": "response.completed", "response": {"id": "response", "status": "completed", "output": [reasoning, tool]}},
    ]
    decoded = adapter.decode_stream(events, route=route(), scope=scope())
    canonical_events = list(decoded)
    outcome = decoded.outcome
    assert outcome.kind == "tool_calls"
    assert outcome.tool_calls[0].name == "lookup"
    assert [event.tool_name for event in canonical_events if event.kind == "tool_call_ready"] == ["lookup"]
    assert outcome.replay_state.issuer == adapter.adapter_id
    result = CanonicalToolResult(identity=outcome.tool_calls[0].identity, call_id="call", tool_name="lookup", output="ok")
    followup = request(messages=(
        SemanticMessage(role="system", parts=(TextPart("policy"),)),
        SemanticMessage(role="user", parts=(TextPart("look up"),)),
        SemanticMessage(role="assistant", parts=(ReasoningReplayPart("reasoning"), ToolCallPart(outcome.tool_calls[0]))),
        SemanticMessage(role="tool", parts=(ToolResultPart(result),)),
        SemanticMessage(role="user", parts=(TextPart("continue"),)),
    ), replay_state=outcome.replay_state)
    body = adapter.encode_request(followup, route=route()).body
    assert [item.get("role") or item["type"] for item in body["input"]] == ["developer", "user", "reasoning", "function_call", "function_call_output", "user"]
    assert body["input"][2] == reasoning
    assert body["input"][3]["namespace"] == "functions"
    assert body["input"][3]["call_id"] == body["input"][4]["call_id"] == "call"
    assert body["include"] == ["reasoning.encrypted_content"]
    assert "previous_response_id" not in body
    assert "_vibelution_responses_websocket" not in body
    assert body["stream"] is True and body["store"] is False
    assert not (set(body) & UNSUPPORTED_SUBSCRIPTION_FIELDS)
    with pytest.raises(ValueError, match="issuer"):
        ResponsesWireAdapter().encode_request(followup, route=route())


@pytest.mark.parametrize("endpoint", [
    "https://relay.example/v1", SUBSCRIPTION_API_BASE + "/",
    SUBSCRIPTION_API_BASE + "/responses/", SUBSCRIPTION_API_BASE + "/responses?x=1",
    SUBSCRIPTION_API_BASE + "/responses#fragment", SUBSCRIPTION_API_BASE + "/chat/completions",
])
def test_subscription_adapter_rejects_nonpublic_route(endpoint):
    foreign = route()
    foreign.runtime_endpoint = endpoint
    with pytest.raises(ValueError, match="origin"):
        ChatGPTSubscriptionWireAdapter().encode_request(request(), route=foreign)


def test_subscription_real_resolver_endpoint_supports_encode_and_route_scoped_replay():
    from config.chatgpt_subscription import build_subscription_provider
    from config.models import LLMProfile, ProviderConfig
    from core.llm.protocol_resolver import resolve_model_protocol
    from core.llm.provider_replay_state import endpoint_fingerprint

    provider = ProviderConfig(**{**build_subscription_provider(), "legacy_inference_allowed": False})
    profile = LLMProfile(profile_id="subscription", provider_id="chatgpt", model="account-model", contract="responses_agent", transport="responses")
    resolved = resolve_model_protocol(profile, provider)
    assert resolved.runtime_endpoint == SUBSCRIPTION_API_BASE + "/responses"
    assert resolved.adapter_id == ChatGPTSubscriptionWireAdapter.adapter_id
    adapter = ChatGPTSubscriptionWireAdapter()
    encoded = adapter.encode_request(request(), route=resolved)
    assert encoded.endpoint == resolved.runtime_endpoint
    reasoning = {"type": "reasoning", "id": "reason", "encrypted_content": "opaque"}
    outcome = adapter.decode_response({"id": "resp", "status": "completed", "output": [reasoning]}, route=resolved, scope=scope())
    replay = outcome.replay_state
    assert replay.endpoint_fingerprint == endpoint_fingerprint(resolved.runtime_endpoint)
    assert replay.endpoint_fingerprint != endpoint_fingerprint(SUBSCRIPTION_API_BASE)
    followup = request(messages=(
        SemanticMessage(role="user", parts=(TextPart("first"),)),
        SemanticMessage(role="assistant", parts=(ReasoningReplayPart("reason"),)),
        SemanticMessage(role="user", parts=(TextPart("next"),)),
    ), replay_state=replay)
    assert adapter.encode_request(followup, route=resolved).body["input"][1] == reasoning
    with pytest.raises(ValueError, match="endpoint_fingerprint"):
        adapter.encode_request(followup, route=route())


def test_subscription_sync_response_normalizes_namespace_without_changing_local_name():
    adapter = ChatGPTSubscriptionWireAdapter()
    raw = {"id": "resp", "status": "completed", "output": [
        {"id": "tool", "type": "function_call", "namespace": "functions", "name": "mcp__local__tool", "call_id": "call", "arguments": '{"x":1}'},
    ]}
    original = copy.deepcopy(raw)
    outcome = adapter.decode_response(raw, route=route(), scope=scope())
    assert outcome.kind == "tool_calls"
    assert outcome.tool_calls[0].name == "mcp__local__tool"
    assert outcome.tool_calls[0].call_id == "call"
    assert dict(outcome.tool_calls[0].arguments) == {"x": 1}
    assert [event.tool_name for event in outcome.events if event.kind == "tool_call_ready"] == ["mcp__local__tool"]
    assert raw == original
    raw["output"][0]["namespace"] = "foreign"
    with pytest.raises(ValueError, match="namespace"):
        adapter.decode_response(raw, route=route(), scope=scope())


@pytest.mark.parametrize("code,category,retryable", [
    ("subscription_sharing_usage_limit_exceeded", "quota_error", False),
    ("subscription_sharing_usage_unavailable", "server_error", True),
    ("subscription_sharing_user_unavailable", "server_error", True),
    ("subscription_sharing_user_not_eligible", "auth_error", False),
    ("subscription_sharing_invalid_user", "auth_error", False),
    ("subscription_sharing_unsupported_capability", "capability_error", False),
    ("subscription_sharing_route_not_supported", "configuration_error", False),
    ("chatpass_v2_scope_not_authorized", "auth_error", False),
])
def test_subscription_failed_stream_errors_keep_safe_code_and_recovery(code, category, retryable):
    event = {"type": "response.failed", "response": {"id": "resp", "status": "failed", "error": {"code": code, "param": "tools[0]", "message": "private-token-and-provider-body"}}}
    original = copy.deepcopy(event)
    error = subscription_error_from_event(event, status_code=200, request_id="req-123")
    assert error.category == category and error.retryable is retryable
    assert error.details["providerErrorCode"] == code
    assert error.details["providerErrorParam"] == "tools[0]"
    assert error.details["httpStatus"] == 200
    assert "private-token" not in str(error)
    decoded = ChatGPTSubscriptionWireAdapter().decode_stream([event], route=route(), scope=scope())
    assert list(decoded)[-1].kind == "turn_failed"
    assert decoded.outcome.kind == "failed" and not decoded.outcome.final_text
    assert code in decoded.outcome.error and "private-token" not in decoded.outcome.error
    assert event == original


@pytest.mark.parametrize("terminal,expected", [("response.completed", "final_answer"), ("response.incomplete", "incomplete"), ("response.done", "incomplete"), (None, "incomplete")])
def test_subscription_success_requires_confirmed_completed_terminal(terminal, expected):
    events = [{"type": "response.output_text.delta", "item_id": "msg", "delta": "partial"}]
    if terminal:
        events.append({"type": terminal, "response": {"status": "completed", "output_text": "partial"}})
    decoded = ChatGPTSubscriptionWireAdapter().decode_stream(events, route=route(), scope=scope())
    list(decoded)
    assert decoded.outcome.kind == expected


def test_subscription_sync_projection_requires_explicit_completed_status():
    outcome = ChatGPTSubscriptionWireAdapter().decode_response({"id": "resp", "output_text": "partial"}, route=route(), scope=scope())
    assert outcome.kind == "incomplete" and not outcome.final_text


def test_subscription_event_normalization_never_renames_local_tools():
    event = {"type": "response.output_item.done", "item": {"type": "function_call", "namespace": "functions", "name": "mcp__local__tool", "call_id": "call"}}
    normalized = normalize_subscription_event(event)
    assert normalized["item"]["name"] == "mcp__local__tool"
    assert "namespace" not in normalized["item"]
    assert event["item"]["namespace"] == "functions"
    event["item"]["namespace"] = "untrusted"
    with pytest.raises(ValueError, match="namespace"):
        normalize_subscription_event(event)


@pytest.mark.parametrize("status,category,retryable", [(401, "auth_error", False), (403, "auth_error", False), (429, "quota_error", False), (503, "server_error", True)])
def test_subscription_admission_detail_is_not_a_machine_code(status, category, retryable):
    error = subscription_error_from_event({"detail": "private diagnostic"}, status_code=status)
    assert error.category == category and error.retryable is retryable
    assert "providerErrorCode" not in error.details
    assert "private diagnostic" not in str(error)
