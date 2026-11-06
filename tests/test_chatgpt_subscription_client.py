"""Production LLMClient subscription boundary with isolated config and HTTP only."""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest

from config.chatgpt_subscription import build_subscription_provider
from config.models import LLMConfig, LLMProfile, ProviderConfig
from core.llm import client as client_module
from core.llm.chatgpt_subscription.wire import UNSUPPORTED_SUBSCRIPTION_FIELDS
from core.llm.client import LLMClient, llm_cancel_context, model_invocation_receipt_context_scope
from core.llm.types import LLMError
from tests.helpers.isolated_config import isolated_settings_config


_TOKEN = "synthetic-subscription-token"
_MODEL = "account-model"
_TRANSPORT_FIELDS = {"api_key", "base_url", "timeout", "client", "extra_headers", "extra_body", "ssl_verify", "_subscription_collect_response", "max_tokens"}
_TOOLS = [{"type": "function", "function": {
    "name": "lookup", "description": "Lookup a value", "parameters": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
    },
}}]


def _metadata(iteration=0):
    return {"sessionId": "subscription-test-session", "turnId": "subscription-test-turn",
            "invocationId": f"subscription-test-invocation-{iteration}", "iteration": iteration,
            "promptPurpose": "main_reply"}


def _config(*, headers=None):
    provider = build_subscription_provider()
    provider.update(provider_id="default", context_window=32768, extra_headers=headers or {}, legacy_inference_allowed=False)
    # The helper's v1 kwargs migration predates OAuth providers. Build actual
    # validated v2 runtime models on its isolated, operator-file-free baseline.
    config = isolated_settings_config()
    config.llm = LLMConfig(schema_version=2, providers={"default": ProviderConfig(**provider)}, profiles={
        "primary": LLMProfile(profile_id="primary", provider_id="default", model=_MODEL,
                              transport="responses", contract="responses_agent", max_output_tokens=128,
                              temperature=0.7, prompt_cache={"mode": "automatic", "retention": "24h"},
                              retry_policy={"max_attempts": 2}),
    })
    return config


@pytest.fixture(autouse=True)
def _isolate_credentials_catalog_and_legacy_network(monkeypatch, tmp_path):
    import core.llm.chatgpt_subscription as subscription

    manager = SimpleNamespace(status=lambda: {"connected": True}, get_access_token=lambda: _TOKEN)
    monkeypatch.setattr(subscription, "get_chatgpt_subscription_auth", lambda: manager)
    for name in ("config.model_catalog.resolve_model_catalog_state_path",
                 "config.runtime_capabilities.resolve_model_catalog_state_path",
                 "config.paths.resolve_model_catalog_state_path"):
        monkeypatch.setattr(name, lambda *_, **__: tmp_path / "catalog.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("VIBELUTION_ENABLE_USER_ENV_FALLBACK", raising=False)

    def forbidden(*_, **__):
        pytest.fail("subscription must not use LiteLLM or an ordinary API backend")

    monkeypatch.setattr(client_module, "_default_completion_backend", forbidden)
    monkeypatch.setattr(client_module, "_default_responses_backend", forbidden)
    monkeypatch.setattr(client_module, "_new_cancellable_responses_http_handler", forbidden)


def _completed(text="reply"):
    return {"type": "response.completed", "response": {
        "id": "response-final", "status": "completed", "output": [{
            "id": "message-final", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        }], "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
    }}


def _sse(events):
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events)


@pytest.fixture
def http_boundary(monkeypatch):
    requests, clients, factories, responses = [], [], [], []

    def respond(request):
        requests.append(request)
        assert responses, "unexpected repeated inference"
        value = responses.pop(0)
        return value() if callable(value) else httpx.Response(200, text=_sse(value))

    def factory(**kwargs):
        factories.append(kwargs)
        client = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)
        clients.append(client)
        return client

    monkeypatch.setattr(client_module, "_llm_new_httpx_client", factory)
    yield SimpleNamespace(requests=requests, clients=clients, factories=factories, responses=responses)
    for client in clients:
        client.close()
    for request in requests:
        _assert_request(request)


def _invoke(client, streaming, messages, **kwargs):
    if not streaming:
        return client.invoke_outcome(messages, **kwargs), []
    chunks = list(client.stream_events(messages, **kwargs))
    done = [chunk for chunk in chunks if chunk.type == "done"]
    assert len(done) == 1
    return done[0].provider_payload["turn_outcome"], chunks


def _assert_request(request):
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["authorization"] == f"Bearer {_TOKEN}"
    body = json.loads(request.content)
    assert body["stream"] is True and body["store"] is False
    assert body["model"] == _MODEL
    assert not (set(body) & (UNSUPPORTED_SUBSCRIPTION_FIELDS | _TRANSPORT_FIELDS))
    assert _TOKEN not in request.content.decode()
    assert not any(item.get("role") == "system" for item in body["input"])
    return body


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("cancel_checker", [False, True])
def test_subscription_default_client_uses_native_http_for_sync_and_stream(http_boundary, streaming, cancel_checker):
    http_boundary.responses.append([
        {"type": "response.output_text.delta", "item_id": "message-final", "delta": "reply"},
        _completed(),
    ])
    client = LLMClient(config=_config())
    assert client.protocol_route.backend_identity == "chatgpt_subscription_http_native"
    try:
        with llm_cancel_context(lambda: "") if cancel_checker else nullcontext():
            outcome, chunks = _invoke(client, streaming, [
                {"role": "system", "content": "policy"}, {"role": "user", "content": "hello"},
            ], metadata=_metadata())
        assert outcome.kind == "final_answer" and outcome.final_text == "reply"
        if streaming:
            assert "".join(chunk.text for chunk in chunks if chunk.type == "text_delta") == "reply"
        assert len(http_boundary.requests) == len(http_boundary.factories) == 1
        assert isinstance(http_boundary.clients[0], httpx.Client)
        assert http_boundary.factories[0]["verify"] is True
        body = _assert_request(http_boundary.requests[0])
        assert body["input"][0]["role"] == "developer"
    finally:
        client.close()
    assert all(http.is_closed for http in http_boundary.clients)


@pytest.mark.parametrize("streaming", [False, True])
def test_subscription_tool_loop_replays_full_history_through_real_payload_builder(http_boundary, streaming):
    reasoning = {"id": "reason", "type": "reasoning", "encrypted_content": "synthetic-replay", "summary": []}
    call = {"id": "tool", "type": "function_call", "namespace": "functions", "name": "lookup", "call_id": "call", "arguments": '{"query":"moon"}'}
    http_boundary.responses.extend([
        [{"type": "response.completed", "response": {"id": "response-tool", "status": "completed", "output": [reasoning, call]}}],
        [_completed("looked up")],
    ])
    client = LLMClient(config=_config(), bound_tools=_TOOLS)
    messages = [{"role": "system", "content": "policy"}, {"role": "user", "content": "look up the moon"}]
    try:
        first, _ = _invoke(client, streaming, messages, metadata=_metadata())
        assert first.kind == "tool_calls" and first.tool_calls[0].name == "lookup"
        assert dict(first.tool_calls[0].arguments) == {"query": "moon"}
        assistant = client.project_outcome_message(first)
        full_history = [*messages, assistant, {"role": "tool", "tool_call_id": "call", "name": "lookup", "content": "satellite"}]
        built = client._build_payload(full_history, stream=streaming, metadata=_metadata(1), replay_state=first.replay_state)
        second, _ = _invoke(client, streaming, full_history, metadata=_metadata(1), replay_state=first.replay_state)
        assert second.final_text == "looked up"
        assert len(http_boundary.requests) == 2
        first_body, second_body = [_assert_request(value) for value in http_boundary.requests]
        assert first_body["tools"][0]["type"] == "namespace"
        assert first_body["tools"][0]["name"] == "functions"
        assert first_body["tools"][0]["tools"][0]["name"] == "lookup"
        assert second_body["input"] == built["input"]
        assert [item.get("type") or item.get("role") for item in second_body["input"]] == ["developer", "user", "reasoning", "function_call", "function_call_output"]
        assert second_body["input"][2] == reasoning
        assert second_body["input"][3]["namespace"] == "functions"
        assert second_body["input"][3]["name"] == "lookup"
        assert second_body["input"][3]["call_id"] == second_body["input"][4]["call_id"] == "call"
    finally:
        client.close()


@pytest.mark.parametrize("streaming", [False, True])
def test_subscription_cancelled_after_first_packet_uses_native_http_and_closes(http_boundary, streaming):
    state = {"reason": ""}

    class CancelAfterPacket(httpx.SyncByteStream):
        def __iter__(self):
            yield _sse([{"type": "response.output_text.delta", "item_id": "message-final", "delta": "partial"}]).encode()
            state["reason"] = "synthetic-stop"
            yield _sse([_completed("must not complete")]).encode()

    http_boundary.responses.append(lambda: httpx.Response(200, stream=CancelAfterPacket()))
    client = LLMClient(config=_config())
    try:
        with llm_cancel_context(lambda: state["reason"]), pytest.raises(LLMError) as caught:
            _invoke(client, streaming, [{"role": "user", "content": "hello"}], metadata=_metadata())
        assert caught.value.category == "cancelled" and not caught.value.retryable
        assert len(http_boundary.requests) == 1
        assert isinstance(http_boundary.clients[0], httpx.Client)
    finally:
        client.close()
    assert all(http.is_closed for http in http_boundary.clients)


def test_subscription_partial_output_then_usage_unavailable_never_retries(http_boundary):
    events = [
        {"type": "response.output_text.delta", "item_id": "partial-message", "delta": "partial"},
        {"type": "response.output_item.done", "item": {
            "id": "partial-tool", "type": "function_call", "namespace": "functions", "name": "lookup",
            "call_id": "unfinished-call", "arguments": '{"query":"moon"}',
        }},
        {"type": "response.failed", "response": {"status": "failed", "error": {
            "code": "subscription_sharing_usage_unavailable", "message": "synthetic-provider-secret",
        }}},
    ]
    # A second synthetic failure lets the real retry loop finish safely if it
    # regresses, so the request-count assertion exposes duplicate inference.
    http_boundary.responses.extend([events, events])
    client = LLMClient(config=_config(), bound_tools=_TOOLS)
    chunks = []
    try:
        with pytest.raises(LLMError) as caught:
            for chunk in client.stream_events([{"role": "user", "content": "hello"}], metadata=_metadata()):
                chunks.append(chunk)
        assert len(http_boundary.requests) == 1
        assert caught.value.category == "server_error" and not caught.value.retryable
        assert "synthetic-provider-secret" not in str(caught.value)
        assert "".join(chunk.text for chunk in chunks if chunk.type == "text_delta") == "partial"
        assert not any(chunk.type in {"tool_call_final", "done"} for chunk in chunks)
    finally:
        client.close()


@pytest.mark.parametrize("streaming", [False, True])
def test_subscription_hard_output_budget_authority_fails_closed_before_http(http_boundary, streaming):
    callback_calls = []

    def preflight(**kwargs):
        callback_calls.append(kwargs)
        return {"maxOutputTokens": 5, "remainingTokens": 100}

    context = {
        "receiptRunAuthority": "workflow_run", "receiptRunId": "workflow-run", "modelPolicySha256": "a" * 64,
        "expectedModelRoute": {"modelRef": "default/account-model", "providerId": "default", "modelId": _MODEL},
        "questionInvocationBinding": {
            "questionId": "question", "workflowRunId": "workflow-run", "formalNodeId": "node",
            "formalNodeRunId": "node-run", "sessionId": _metadata()["sessionId"], "taskId": "task",
            "turnId": _metadata()["turnId"], "outcomeKinds": ["candidate"],
        }, "invocationBudgetPreflight": preflight,
    }
    client = LLMClient(config=_config())
    try:
        with model_invocation_receipt_context_scope(context), pytest.raises(LLMError) as caught:
            _invoke(client, streaming, [{"role": "user", "content": "hello"}], metadata=_metadata())
        assert caught.value.category == "capability_error" and not caught.value.retryable
        assert not http_boundary.requests and not http_boundary.factories
        # The unsupported hard cap must be rejected before consulting authority
        # with a fabricated zero output allowance or dropping its returned cap.
        assert callback_calls == []
    finally:
        client.close()


@pytest.mark.parametrize("header", ["Authorization", "Cookie", "X-Api-Key"])
def test_subscription_rejects_other_credential_headers_before_http(http_boundary, header):
    http_boundary.responses.append([_completed()])
    client = LLMClient(config=_config(headers={header: "synthetic-other-provider-secret"}))
    try:
        with pytest.raises(LLMError) as caught:
            client.invoke_outcome([{"role": "user", "content": "hello"}], metadata=_metadata())
        assert caught.value.category in {"configuration_error", "capability_error"}
        assert not caught.value.retryable
        assert not http_boundary.requests
        assert "synthetic-other-provider-secret" not in str(caught.value)
    finally:
        client.close()
