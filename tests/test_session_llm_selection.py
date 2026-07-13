from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import sessions as sessions_route
from core.web.services import agent_config_workspace_service, session_service
from config.public_config import list_llm_model_options
from config.llm_key_env import configured_llm_key_env_names


pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_schema_v2_provider_models_feed_the_model_picker():
    options = list_llm_model_options(
        {
            "llm": {
                "schema_version": 2,
                "providers": {
                    "ai-pixel": {
                        "label": "Ai-Pixel",
                        "service_class": "relay",
                        "api": "openai-responses",
                        "base_url": "https://relay.example/v1",
                        "credential_ref": "env:AI_PIXEL_API_KEY",
                        "protocols": {"default": "responses"},
                        "models": {
                            "luna": {
                                "upstream_id": "gpt-5.6-luna",
                                "label": "Luna",
                                "defaults": {
                                    "reasoning_effort_values": ["low", "medium", "xhigh"],
                                    "default_reasoning_effort": "xhigh",
                                    "reasoning_effort_descriptions": {"xhigh": "最大推理深度"},
                                },
                            },
                            "terra": {"upstream_id": "gpt-5.6-terra", "label": "Terra"},
                        },
                    }
                },
                "profiles": {"primary": {"model_ref": "ai-pixel/luna"}},
            }
        }
    )

    assert [item["model_id"] for item in options] == ["ai-pixel/luna", "ai-pixel/terra"]
    assert options[0]["provider"]["provider_id"] == "ai-pixel"
    assert options[0]["provider_kind"] == "relay"
    assert options[0]["model"] == "gpt-5.6-luna"
    assert options[0]["details"]["reasoning_effort_values"] == ["low", "medium", "xhigh"]


def test_schema_v2_credential_refs_restore_provider_key_env_names():
    env_names = configured_llm_key_env_names(
        {
            "llm": {
                "schema_version": 2,
                "providers": {
                    "relay": {
                        "credential_ref": "env:RELAY_SHARED_API_KEY",
                        "models": {"luna": {"upstream_id": "gpt-5.6-luna"}},
                    }
                },
            }
        }
    )

    assert env_names == {"RELAY_SHARED_API_KEY"}


def _model_choices() -> list[dict]:
    return [
        {
            "modelId": "relay_gpt_5_6_luna",
            "label": "gpt-5.6-luna",
            "model": "gpt-5.6-luna",
            "providerId": "ai-pixel",
            "providerLabel": "Ai-Pixel",
            "providerKind": "relay",
            "apiKeyConfigured": True,
            "missingApiKey": False,
            "supportsReasoningEffort": True,
            "reasoningEffortValues": ["low", "medium", "high"],
            "reasoningEffortOptions": [
                {"value": "low", "label": "低", "description": "更快响应"},
                {"value": "medium", "label": "中", "description": "平衡速度与推理"},
                {"value": "high", "label": "高", "description": "复杂任务使用"},
            ],
            "defaultReasoningEffort": "medium",
            "isDefault": True,
        },
        {
            "modelId": "local_qwen",
            "label": "Qwen Local",
            "model": "qwen3.6",
            "providerId": "local",
            "providerLabel": "Local Runtime",
            "providerKind": "local_runtime",
            "apiKeyConfigured": True,
            "missingApiKey": False,
            "supportsReasoningEffort": False,
            "reasoningEffortValues": [],
            "reasoningEffortOptions": [],
            "defaultReasoningEffort": "",
            "isDefault": False,
        },
    ]


def test_session_llm_options_expose_current_model_and_effort(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        agent_config_workspace_service,
        "list_agent_model_choices",
        lambda: _model_choices(),
        raising=False,
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {
            "id": "session-live",
            "agentId": "agent-live",
            "dialogueModelId": "relay_gpt_5_6_luna",
            "reasoningEffort": "high",
        },
    )
    monkeypatch.setattr(session_service, "_default_session_dialogue_model_id", lambda: "relay_gpt_5_6_luna")

    payload = session_service.get_session_llm_options("session-live")

    assert payload["sessionId"] == "session-live"
    assert payload["currentModelId"] == "relay_gpt_5_6_luna"
    assert payload["currentReasoningEffort"] == "high"
    assert payload["models"][0]["isDefault"] is True
    assert payload["models"][0]["defaultReasoningEffort"] == "medium"
    assert [item["value"] for item in payload["models"][0]["reasoningEffortOptions"]] == ["low", "medium", "high"]


def test_agent_model_choices_preserve_model_specific_reasoning_efforts():
    choices = agent_config_workspace_service._agent_model_choices(
        [
            {
                "model_id": "relay_reasoning",
                "label": "Relay Reasoning",
                "model": "gpt-5.6-luna",
                "provider": {"id": "relay", "kind": "relay", "compat_mode": "openai"},
                "provider_kind": "relay",
                "transport": "responses",
                "details": {
                    "reasoning_effort_values": ["minimal", "medium", "xhigh"],
                    "default_reasoning_effort": "xhigh",
                    "reasoning_effort_descriptions": {
                        "minimal": "最快响应",
                        "xhigh": "最大推理深度",
                    },
                },
                "api_key_configured": True,
            }
        ]
    )

    assert choices[0]["reasoningEffortValues"] == ["minimal", "medium", "xhigh"]
    assert choices[0]["defaultReasoningEffort"] == "xhigh"
    assert choices[0]["reasoningEffortOptions"][0] == {
        "value": "minimal",
        "label": "最小",
        "description": "最快响应",
    }


def test_public_agent_model_choice_loader_uses_compact_config_workspace(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        agent_config_workspace_service,
        "_safe_config_workspace",
        lambda: {"modelOptions": [{"model_id": "local", "model": "local", "provider": {"id": "local"}}]},
    )

    assert agent_config_workspace_service.list_agent_model_choices()[0]["modelId"] == "local"


def test_session_llm_selection_updates_model_and_effort_atomically(monkeypatch: pytest.MonkeyPatch):
    original_agent = {
        "agentId": "agent-live",
        "llmBindings": {
            "dialogue": {"modelId": "local_qwen"},
            "vision": {"modelId": "vision-model"},
        },
        "metadata": {"llmReasoningEffort": {"summary": "low"}, "kept": True},
    }
    captured: dict = {}
    monkeypatch.setattr(agent_config_workspace_service, "list_agent_model_choices", lambda: _model_choices(), raising=False)
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {"id": "session-live", "agentId": "agent-live"},
    )
    monkeypatch.setattr(session_service, "get_agent", lambda _agent_id, **_kwargs: original_agent)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)

    def fake_update(agent_id: str, **kwargs):
        captured.update({"agentId": agent_id, **kwargs})
        return {
            **original_agent,
            "llmBindings": kwargs["llm_bindings"],
            "metadata": {**original_agent["metadata"], **kwargs["metadata"]},
        }

    monkeypatch.setattr(session_service, "update_agent_instance", fake_update)

    payload = session_service.update_session_llm_selection(
        "session-live",
        model_id="relay_gpt_5_6_luna",
        reasoning_effort="high",
    )

    assert captured["agentId"] == "agent-live"
    assert captured["llm_bindings"] == {
        "dialogue": {"modelId": "relay_gpt_5_6_luna"},
        "vision": {"modelId": "vision-model"},
    }
    assert captured["metadata"]["llmReasoningEffort"] == {"summary": "low", "dialogue": "high"}
    assert payload["currentModelId"] == "relay_gpt_5_6_luna"
    assert payload["currentReasoningEffort"] == "high"


def test_session_llm_selection_rejects_unsupported_effort_without_partial_update(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_config_workspace_service, "list_agent_model_choices", lambda: _model_choices(), raising=False)
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda _session_id, **_kwargs: {"id": "session-live", "agentId": "agent-live"},
    )
    monkeypatch.setattr(session_service, "get_agent", lambda _agent_id, **_kwargs: {"agentId": "agent-live"})
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    update_calls: list[dict] = []
    monkeypatch.setattr(session_service, "update_agent_instance", lambda *_args, **kwargs: update_calls.append(kwargs))

    with pytest.raises(session_service.SessionValidationError, match="不支持推理强度"):
        session_service.update_session_llm_selection(
            "session-live",
            model_id="local_qwen",
            reasoning_effort="high",
        )

    assert update_calls == []


def test_session_llm_selection_routes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sessions_route,
        "get_session_llm_options",
        lambda session_id: {"sessionId": session_id, "models": _model_choices()},
        raising=False,
    )
    monkeypatch.setattr(
        sessions_route,
        "update_session_llm_selection",
        lambda session_id, *, model_id, reasoning_effort: {
            "sessionId": session_id,
            "currentModelId": model_id,
            "currentReasoningEffort": reasoning_effort,
        },
        raising=False,
    )

    options_response = client.get("/api/sessions/session-live/llm-options")
    update_response = client.patch(
        "/api/sessions/session-live/llm-selection",
        json={"modelId": "relay_gpt_5_6_luna", "reasoningEffort": "high"},
    )

    assert options_response.status_code == 200
    assert options_response.json()["models"][0]["modelId"] == "relay_gpt_5_6_luna"
    assert update_response.status_code == 200
    assert update_response.json()["currentReasoningEffort"] == "high"
