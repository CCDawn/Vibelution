from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from config.chatgpt_subscription import build_subscription_provider
from config.models import LLMProfile, ProviderConfig
from config import public_config
from core.llm import chatgpt_subscription, client as llm_client
from core.llm.chatgpt_subscription.errors import ChatGPTSubscriptionError


@pytest.mark.parametrize("auth_error, expected", [(None, ""), ("signed_out", "missing_credential"), ("reauth_required", "auth_error")])
def test_real_configuration_probe_uses_oauth_and_native_terminal_validation(monkeypatch, auth_error, expected):
    requests = []
    provider = ProviderConfig(**{**build_subscription_provider(), "provider_id": "subscription", "legacy_inference_allowed": False})
    profile = LLMProfile(profile_id="primary", provider_id="subscription", model="example-model",
                         protocol="openai_responses", transport="responses", contract="responses_agent",
                         context_window=4096)
    final = {"id": "r1", "status": "completed", "output": [{"id": "m1", "type": "message", "role": "assistant", "phase": "final_answer",
             "status": "completed", "content": [{"type": "output_text", "text": "pong", "annotations": []}]}]}

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="data: " + json.dumps({"type": "response.completed", "response": final}) + "\n\n")

    def access_token():
        if auth_error:
            raise ChatGPTSubscriptionError(auth_error)
        return "synthetic-oauth"

    manager = SimpleNamespace(get_access_token=access_token, mark_auth_rejected=lambda _: None)
    monkeypatch.setattr(chatgpt_subscription, "get_chatgpt_subscription_auth", lambda: manager)
    monkeypatch.setattr(llm_client, "_llm_new_httpx_client", lambda **_: httpx.Client(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(public_config, "validate_llm_provider_target", lambda *args, **kwargs: None)
    result = public_config._probe_llm_runtime(provider, profile)
    if auth_error:
        assert result["ok"] is False and result["error_category"] == expected
        assert requests == []
        return
    assert result["ok"] is True, result
    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer synthetic-oauth"
    assert json.loads(requests[0].content)["stream"] is True


def test_wrapped_stream_backend_dispatches_native_even_with_false_collect_flag(monkeypatch):
    sentinel = object()
    seen = []
    monkeypatch.setattr(llm_client, "_default_subscription_responses_backend", lambda payload: seen.append(payload) or sentinel)
    assert llm_client._default_responses_backend({"_subscription_collect_response": False}) is sentinel
    assert seen == [{"_subscription_collect_response": False}]
