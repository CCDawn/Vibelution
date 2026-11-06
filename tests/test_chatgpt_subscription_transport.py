from __future__ import annotations

import json

import httpx
import pytest

from core.llm.errors import LLMError
from core.llm.chatgpt_subscription.inference import call_subscription_responses


def _payload(**extra):
    return {"base_url": "https://api.openai.com/v1/responses", "api_key": "synthetic-only",
            "model": "test-model", "input": [{"role": "user", "content": "hello"}],
            "stream": True, "store": False, **extra}


def test_native_transport_does_not_emit_runtime_or_unsupported_fields():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, text='data: {"type":"response.completed","response":{"id":"r1","status":"completed","output":[]}}\n\n')
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = call_subscription_responses(_payload(temperature=0.2, max_output_tokens=200,
            _subscription_collect_response=True, client=client), client_factory=lambda **_: pytest.fail("must reuse client"))
    assert result["status"] == "completed"
    body = json.loads(requests[0].content)
    assert "temperature" not in body and "max_output_tokens" not in body
    assert "api_key" not in body and "client" not in body and "_subscription_collect_response" not in body
    assert requests[0].headers["authorization"] == "Bearer synthetic-only"
    assert body["stream"] is True and body["store"] is False


def test_transport_rejects_redirect_and_untrusted_destination_before_sending():
    for endpoint in ("https://example.com/v1/responses", "http://api.openai.com/v1/responses",
                     "https://api.openai.com/v1/responses?other=true"):
        with pytest.raises(LLMError):
            call_subscription_responses(_payload(base_url=endpoint), client_factory=lambda **_: pytest.fail("must not create client"))


def test_stream_keeps_partial_output_and_reports_quota_without_retry_or_raw_message():
    events = [
        {"type": "response.output_text.delta", "delta": "partial"},
        {"type": "response.failed", "response": {"error": {
            "code": "subscription_sharing_usage_limit_exceeded", "message": "synthetic-secret-must-not-escape"}}},
    ]
    def respond(_):
        return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        stream = call_subscription_responses(_payload(client=client), client_factory=lambda **_: None)
        assert next(stream)["delta"] == "partial"
        with pytest.raises(LLMError) as error:
            next(stream)
    assert error.value.retryable is False
    assert error.value.category == "quota_error"
    assert "synthetic-secret" not in str(error.value)


def test_sync_request_requires_completed_terminal_and_never_returns_partial_as_success():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200,
            text='data: {"type":"response.output_text.delta","delta":"unfinished"}\n\n'))) as client:
        with pytest.raises(LLMError):
            call_subscription_responses(_payload(client=client, _subscription_collect_response=True), client_factory=lambda **_: None)


def test_http_401_invalidates_only_the_credential_used_by_this_request():
    rejected = []
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401, json={"error": {"code": "invalid_api_key"}}))) as client:
        with pytest.raises(LLMError) as error:
            list(call_subscription_responses(_payload(client=client), client_factory=lambda **_: None,
                                             auth_rejected=rejected.append))
    assert rejected == ["synthetic-only"]
    assert error.value.retryable is False
