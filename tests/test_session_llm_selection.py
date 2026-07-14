from __future__ import annotations

import copy

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
            "modelId": "ai-pixel/gpt-5.6-luna",
            "modelRef": "ai-pixel/gpt-5.6-luna",
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
            "modelRef": "local/qwen",
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
    monkeypatch.setattr(session_service, "_session_reasoning_effort_snapshot", lambda _session_id: "high")
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda _session_id: _model_choices()[0])
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *_args, **_kwargs: pytest.fail("LLM options must not hydrate full session detail"),
    )
    payload = session_service.get_session_llm_options("session-live")

    assert payload["sessionId"] == "session-live"
    assert payload["currentModelId"] == "ai-pixel/gpt-5.6-luna"
    assert payload["currentReasoningEffort"] == "high"
    assert payload["model"]["modelRef"] == "ai-pixel/gpt-5.6-luna"
    assert "models" not in payload


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


def _install_chat_state(monkeypatch: pytest.MonkeyPatch, efforts: dict[str, str]) -> dict:
    state = {
        "conversations": [
            {
                "conversation_id": session_id,
                "agent_id": "agent-live",
                "reasoning_effort": effort,
                "updated_at": "2026-07-13T00:00:00Z",
            }
            for session_id, effort in efforts.items()
        ]
    }

    def save_state(_project_root, payload):
        state.clear()
        state.update(copy.deepcopy(payload))

    monkeypatch.setattr(session_service, "load_chat_state", lambda _project_root: copy.deepcopy(state))
    monkeypatch.setattr(session_service, "save_chat_state", save_state)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda session_id, **_kwargs: {
            "id": session_id,
            "agentId": "agent-live",
            "reasoningEffort": next(
                item.get("reasoning_effort", "")
                for item in state["conversations"]
                if item["conversation_id"] == session_id
            ),
        },
    )
    return state


def test_reasoning_effort_snapshot_uses_initialized_chat_state_without_detail_hydration(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_chat_state(monkeypatch, {"session-live": "high"})
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *_args, **_kwargs: pytest.fail("initialized effort must not hydrate session detail"),
    )
    monkeypatch.setattr(
        session_service,
        "_session_fixed_model_choice",
        lambda *_args, **_kwargs: pytest.fail("initialized effort must not resolve model catalog"),
    )

    assert session_service._session_reasoning_effort_snapshot("session-live") == "high"


def test_session_effort_update_never_writes_agent(monkeypatch: pytest.MonkeyPatch):
    state = _install_chat_state(monkeypatch, {"session-live": "medium"})
    update_agent_calls = []
    monkeypatch.setattr(session_service, "update_agent_instance", lambda *args, **kwargs: update_agent_calls.append((args, kwargs)))
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda _session_id: _model_choices()[0])
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)

    payload = session_service.update_session_reasoning_effort("session-live", reasoning_effort="high")

    assert payload["currentModelId"] == "ai-pixel/gpt-5.6-luna"
    assert payload["currentReasoningEffort"] == "high"
    assert payload["model"]["modelRef"] == "ai-pixel/gpt-5.6-luna"
    assert "models" not in payload
    assert update_agent_calls == []
    assert state["conversations"][0]["reasoning_effort"] == "high"


def test_two_sessions_keep_independent_efforts(monkeypatch: pytest.MonkeyPatch):
    state = _install_chat_state(monkeypatch, {"session-a": "low", "session-b": "high"})
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda _session_id: _model_choices()[0])
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)

    session_service.update_session_reasoning_effort("session-a", reasoning_effort="medium")

    efforts = {item["conversation_id"]: item["reasoning_effort"] for item in state["conversations"]}
    assert efforts == {"session-a": "medium", "session-b": "high"}


def test_session_reasoning_effort_rejects_unsupported_value_without_partial_update(monkeypatch: pytest.MonkeyPatch):
    state = _install_chat_state(monkeypatch, {"session-live": "medium"})
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda _session_id: _model_choices()[0])

    with pytest.raises(session_service.SessionValidationError, match="不支持推理强度"):
        session_service.update_session_reasoning_effort("session-live", reasoning_effort="xhigh")

    assert state["conversations"][0]["reasoning_effort"] == "medium"


def test_session_reasoning_effort_routes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        sessions_route,
        "get_session_llm_options",
        lambda session_id: {"sessionId": session_id, "model": _model_choices()[0]},
        raising=False,
    )
    monkeypatch.setattr(
        sessions_route,
        "update_session_reasoning_effort",
        lambda session_id, *, reasoning_effort: {
            "sessionId": session_id,
            "currentModelId": "ai-pixel/gpt-5.6-luna",
            "currentReasoningEffort": reasoning_effort,
        },
        raising=False,
    )

    options_response = client.get("/api/sessions/session-live/llm-options")
    update_response = client.patch(
        "/api/sessions/session-live/reasoning-effort",
        json={"reasoningEffort": "high"},
    )
    legacy_payload_response = client.patch(
        "/api/sessions/session-live/reasoning-effort",
        json={"modelId": "ai-pixel/gpt-5.6-luna", "reasoningEffort": "high"},
    )
    removed_route_response = client.patch(
        "/api/sessions/session-live/llm-selection",
        json={"modelId": "ai-pixel/gpt-5.6-luna", "reasoningEffort": "high"},
    )

    assert options_response.status_code == 200
    assert options_response.json()["model"]["modelRef"] == "ai-pixel/gpt-5.6-luna"
    assert update_response.status_code == 200
    assert update_response.json()["currentReasoningEffort"] == "high"
    assert legacy_payload_response.status_code == 422
    assert removed_route_response.status_code in {404, 405}
