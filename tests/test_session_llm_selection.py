from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import sessions as sessions_route
from core.web.services import agent_config_workspace_service, agent_model_candidate_service, session_service
from config.public_config import list_llm_model_options
from config.llm_key_env import configured_llm_key_env_names


pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_session_model_choices_use_candidate_service_without_facade_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delattr(session_service, "list_agent_model_candidates", raising=False)
    monkeypatch.setattr(session_service, "_default_session_dialogue_model_id", lambda: "provider/model-a")
    monkeypatch.setattr(
        agent_model_candidate_service,
        "list_agent_model_candidates",
        lambda: {
            "candidates": [
                {
                    "modelId": "provider/model-a",
                    "reasoningEffortValues": ["low", "high"],
                }
            ]
        },
    )

    choices = session_service._session_llm_model_choices()

    assert choices[0]["modelId"] == "provider/model-a"
    assert choices[0]["isDefault"] is True
    assert choices[0]["reasoningEffortValues"] == ["low", "high"]


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
    monkeypatch.setattr(session_service, "_ensure_session_conversation_record", lambda *_a, **_k: True)
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


def test_session_reasoning_effort_recovers_missing_chat_state_from_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Workspace-backed sessions may rematerialize identity, but config stays on Agent."""
    state = {"conversations": [], "version": 1}
    update_agent_calls = []
    session_id = "session-orphan"
    agent_id = "agent-orphan"
    journal = tmp_path / "turn_journal.jsonl"
    journal.write_text(
        json.dumps(
            {
                "eventType": "turn_started",
                "sessionId": session_id,
                "payload": {"agentId": agent_id},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def save_state(_project_root, payload):
        state.clear()
        state.update(copy.deepcopy(payload))

    monkeypatch.setattr(session_service, "load_chat_state", lambda _project_root: copy.deepcopy(state))
    monkeypatch.setattr(session_service, "save_chat_state", save_state)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: False)
    monkeypatch.setattr(
        session_service,
        "_ensure_agent_directory_conversation_materialized",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        session_service,
        "_ensure_session_workspace",
        lambda _sid: tmp_path,
    )
    monkeypatch.setattr(
        session_service,
        "get_agent",
        lambda aid, include_archived=False: {
            "agentId": agent_id,
            "displayName": "orphan-agent",
            "agentCode": "orphan",
            "directSessionId": "",
            "status": "active",
            "updatedAt": "2026-07-24T00:00:00Z",
            "createdAt": "2026-07-24T00:00:00Z",
        } if aid == agent_id else None,
    )
    monkeypatch.setattr(
        session_service,
        "_agent_directory_conversation_record",
        lambda agent, *, session_id: {
            "conversation_id": session_id,
            "agent_id": agent["agentId"],
            "agentId": agent["agentId"],
            "title": agent["displayName"],
            "updated_at": "2026-07-24T00:00:00Z",
        },
    )
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda _sid: _model_choices()[0])
    monkeypatch.setattr(
        session_service,
        "update_agent_instance",
        lambda *args, **kwargs: update_agent_calls.append((args, kwargs)) or {
            "agentId": agent_id,
            "configRevision": 2,
        },
    )
    monkeypatch.setattr(session_service, "get_session_llm_options", lambda sid: {
        "sessionId": sid,
        "currentModelId": "ai-pixel/gpt-5.6-luna",
        "currentReasoningEffort": "high",
        "model": _model_choices()[0],
    })

    payload = session_service.update_session_reasoning_effort(session_id, reasoning_effort="high")

    assert payload["currentReasoningEffort"] == "high"
    assert any(item.get("conversation_id") == session_id for item in state["conversations"])
    recovered = next(item for item in state["conversations"] if item["conversation_id"] == session_id)
    assert "reasoning_effort" not in recovered
    assert recovered.get("agentId") == agent_id or recovered.get("agent_id") == agent_id
    assert update_agent_calls == [
        (
            (agent_id,),
            {"reasoning_effort_by_slot": {"dialogue": "high"}},
        )
    ]


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


def test_reasoning_effort_snapshot_reads_agent_config_and_ignores_session_value(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_chat_state(monkeypatch, {"session-live": "high"})
    monkeypatch.setattr(
        session_service,
        "_session_agent_id_snapshot",
        lambda _session_id: "agent-live",
    )
    monkeypatch.setattr(
        session_service,
        "get_agent",
        lambda agent_id, **_kwargs: {
            "agentId": agent_id,
            "metadata": {"llmReasoningEffort": {"dialogue": "medium"}},
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *_args, **_kwargs: pytest.fail("Agent config snapshot must not hydrate session detail"),
    )
    monkeypatch.setattr(
        session_service,
        "_session_fixed_model_choice",
        lambda *_args, **_kwargs: pytest.fail("Agent config snapshot must not resolve model catalog"),
    )

    assert session_service._session_reasoning_effort_snapshot("session-live") == "medium"


def test_session_effort_update_writes_owning_agent_and_keeps_session_as_projection(monkeypatch: pytest.MonkeyPatch):
    state = _install_chat_state(monkeypatch, {"session-live": "medium"})
    update_agent_calls = []
    monkeypatch.setattr(
        session_service,
        "update_agent_instance",
        lambda *args, **kwargs: update_agent_calls.append((args, kwargs)) or {
            "agentId": "agent-live",
            "configRevision": 2,
            "metadata": {"llmReasoningEffort": {"dialogue": "high"}},
        },
    )
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda _session_id: _model_choices()[0])
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(
        session_service,
        "get_session_llm_options",
        lambda session_id: {
            "sessionId": session_id,
            "currentModelId": "ai-pixel/gpt-5.6-luna",
            "currentReasoningEffort": "high",
            "model": _model_choices()[0],
        },
    )

    payload = session_service.update_session_reasoning_effort("session-live", reasoning_effort="high")

    assert payload["currentModelId"] == "ai-pixel/gpt-5.6-luna"
    assert payload["currentReasoningEffort"] == "high"
    assert payload["model"]["modelRef"] == "ai-pixel/gpt-5.6-luna"
    assert "models" not in payload
    assert update_agent_calls == [
        (
            ("agent-live",),
            {"reasoning_effort_by_slot": {"dialogue": "high"}},
        )
    ]
    assert state["conversations"][0]["reasoning_effort"] == "medium"


def test_two_sessions_bound_to_one_agent_do_not_keep_independent_effort_authority(monkeypatch: pytest.MonkeyPatch):
    state = _install_chat_state(monkeypatch, {"session-a": "low", "session-b": "high"})
    update_agent_calls = []
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda _session_id: _model_choices()[0])
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(
        session_service,
        "update_agent_instance",
        lambda *args, **kwargs: update_agent_calls.append((args, kwargs)) or {
            "agentId": "agent-live",
            "configRevision": 2,
        },
    )
    monkeypatch.setattr(
        session_service,
        "get_session_llm_options",
        lambda session_id: {
            "sessionId": session_id,
            "currentModelId": "ai-pixel/gpt-5.6-luna",
            "currentReasoningEffort": "medium",
            "model": _model_choices()[0],
        },
    )

    session_service.update_session_reasoning_effort("session-a", reasoning_effort="medium")

    efforts = {item["conversation_id"]: item["reasoning_effort"] for item in state["conversations"]}
    assert efforts == {"session-a": "low", "session-b": "high"}
    assert update_agent_calls == [
        (
            ("agent-live",),
            {"reasoning_effort_by_slot": {"dialogue": "medium"}},
        )
    ]


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
