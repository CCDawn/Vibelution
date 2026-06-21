import json
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from tests.test_agent_config_workspace_service import (
    ProviderConfig,
    _fake_config_workspace,
    _mark_config_agent_instances_present,
    _raw_mode_binding,
    _seed_supervised_fixed_role_agent,
    _use_tmp_project_root,
    agent_bulk_delete_service,
    agent_config_workspace_service,
    agent_directory_service,
    agent_mode_binding_service,
    agent_tool_governance_service,
    agents_route,
    chat_room_service,
    client,
    config_package,
    config_service,
    context_engine,
    prompt_template_service,
    self_evolution_control_service,
    session_service,
    supervised_agent_service,
    team_service,
)


def _iter_api_routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route.path, route.methods
            continue
        nested_routes = []
        route_prefix = str(getattr(route, "prefix", "") or "").rstrip("/")
        if isinstance(getattr(route, "routes", None), (list, tuple)):
            nested_routes = list(route.routes)
        elif getattr(route, "original_router", None) is not None:
            nested_router = getattr(route, "original_router")
            include_context = getattr(route, "include_context", None)
            route_prefix = str(getattr(include_context, "prefix", "") or "").rstrip("/")
            nested_routes = list(getattr(nested_router, "routes", []))
        if not nested_routes:
            continue
        for sub_route in nested_routes:
            if isinstance(sub_route, APIRoute):
                full_path = str(getattr(sub_route, "path", "")).strip()
                if not full_path.startswith("/"):
                    full_path = f"/{full_path}"
                yield f"{route_prefix}{full_path}" if route_prefix else full_path, sub_route.methods

def test_agents_api_summary_detail_returns_light_payload(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    created = agent_directory_service.create_agent_instance(display_name="Summary Route Agent", primary_mode="chat")

    response = client.get("/api/agents", params={"detail": "summary"})

    assert response.status_code == 200, response.json()
    payload = response.json()
    agent = next(item for item in payload if item["agentId"] == created["agentId"])
    assert agent["displayName"] == created["displayName"]
    assert "toolPolicy" not in agent
    assert "memoryPolicy" not in agent
    assert "toolGovernanceRequests" not in agent
    assert "groupContextEvents" not in agent
    assert "agentInboxMessages" not in agent


def test_agent_config_workspace_api_route(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    calls = []
    route_payload = {
        "schemaVersion": 1,
        "summary": {"agentCount": 1},
        "toolPolicies": [{"policyId": "default"}],
        "memoryPolicies": [{"policyId": "default"}],
        "agents": [],
        "groups": [],
        "chatRooms": [],
    }
    monkeypatch.setattr(
        agents_route,
        "get_agent_config_workspace",
        lambda **kwargs: calls.append(kwargs) or route_payload,
    )

    registered_routes = [
        route
        for route in _iter_api_routes(client.app)
        if route[0] == "/api/agents/config-workspace" and "GET" in set(route[1] or set())
    ]
    payload = agents_route.agent_config_workspace()

    assert registered_routes
    assert calls == [{"use_cache": True}]
    assert payload["schemaVersion"] == 1
    assert payload["summary"]["agentCount"] >= 1
    assert any(item["policyId"] == "default" for item in payload["toolPolicies"])
    assert payload["memoryPolicies"]


def test_agent_config_workspace_route_uses_short_lived_cache(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent_config_workspace_service.invalidate_agent_config_workspace_cache()
    calls = []
    original_list_agents = agent_config_workspace_service.list_agents

    def counted_list_agents(*args, **kwargs):
        calls.append(kwargs)
        return original_list_agents(*args, **kwargs)

    monkeypatch.setattr(agent_config_workspace_service, "list_agents", counted_list_agents)
    agent_directory_service.create_agent_instance(display_name="缓存 Agent")

    first = agent_config_workspace_service.get_agent_config_workspace(use_cache=True)
    second = agent_config_workspace_service.get_agent_config_workspace(use_cache=True)

    assert len(calls) == 1
    assert first["diagnostics"]["cache"]["enabled"] is True
    assert first["diagnostics"]["cache"]["hit"] is False
    assert second["diagnostics"]["cache"]["hit"] is True
    assert second["summary"]["agentCount"] == first["summary"]["agentCount"]


def test_agent_config_workspace_surfaces_runtime_status_from_run_snapshots(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    running_agent = agent_directory_service.create_agent_instance(display_name="运行 Agent")
    failed_agent = agent_directory_service.create_agent_instance(display_name="失败 Agent")

    context_engine.record_agent_turn_result(
        running_agent["agentId"],
        running_agent["directSessionId"],
        {
            "runId": "turn-running",
            "status": "running",
            "summary": "still working",
            "updatedAt": "2026-05-28T10:00:00Z",
        },
    )
    context_engine.record_agent_turn_result(
        failed_agent["agentId"],
        failed_agent["directSessionId"],
        {
            "runId": "turn-failed",
            "status": "failed",
            "summary": "tool failed",
            "updatedAt": "2026-05-28T10:01:00Z",
        },
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()
    agents = {item["agentId"]: item for item in payload["agents"]}

    assert agents[running_agent["agentId"]]["runtimeStatus"]["state"] == "running"
    assert agents[running_agent["agentId"]]["runtimeStatus"]["runId"]
    assert agents[failed_agent["agentId"]]["runtimeStatus"]["state"] == "failed"
    assert agents[failed_agent["agentId"]]["runtimeStatus"]["summary"] == "tool failed"
    assert payload["summary"]["runningAgentCount"] == 1
    assert payload["summary"]["blockedAgentCount"] == 1


def test_agent_config_workspace_ignores_stale_runtime_snapshots_for_current_direct_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="换绑 Agent")
    original_session_id = agent["directSessionId"]
    replacement_session_id = "session-current-direct"

    context_engine.record_agent_turn_result(
        agent["agentId"],
        original_session_id,
        {
            "runId": "turn-old-session",
            "status": "completed",
            "summary": "old direct session result",
            "updatedAt": "2026-05-28T10:00:00Z",
        },
    )
    agent_directory_service.update_agent_instance(agent["agentId"], direct_session_id=replacement_session_id)

    payload = agent_config_workspace_service.get_agent_config_workspace()
    current = next(item for item in payload["agents"] if item["agentId"] == agent["agentId"])

    assert current["directSessionId"] == replacement_session_id
    assert current["runtimeStatus"]["state"] == "idle"
    assert current["runtimeStatus"]["reason"] == "no_current_direct_session_runs"
    assert current["runtimeStatus"]["sessionId"] == replacement_session_id
    assert current["runtimeStatus"]["runId"] == ""
    assert current["runtimeStatus"]["latestHistoricalSessionId"] == original_session_id
    assert current["runtimeStatus"]["staleRuntimeRunCount"] == 1


def test_agent_config_workspace_reports_unresolved_model_reference(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="坏模型 Agent",
        llm_bindings={"dialogue": {"modelId": "missing-model-id"}},
        primary_mode="chat",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()
    current = next(item for item in payload["agents"] if item["agentId"] == agent["agentId"])
    issues = payload["health"]["byAgent"][agent["agentId"]]

    assert current["dialogueModel"] is None
    assert current["llmBindingModels"]["dialogue"] is None
    assert current["llmBindings"]["dialogue"]["modelId"] == "missing-model-id"
    assert any(item["code"] == "unresolved_model_reference_dialogue" for item in issues)
    assert payload["health"]["counts"]["blocking"] >= 1


def test_agent_config_workspace_repairs_legacy_agent_model_ids(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    def fake_config_workspace():
        return {
            "modelOptions": [
                {
                    "model_id": "relay_openai_gpt_5_5",
                    "source": "model_library",
                    "provider": {"id": "relay_openai", "kind": "relay", "compat_mode": "openai"},
                    "provider_kind": "relay",
                    "model": "gpt-5.5",
                    "label": "GPT-5.5 via relay",
                    "transport": "responses",
                    "details": {"transport": "responses"},
                    "api_key_env": "OPENAI_API_KEY",
                    "api_key_configured": True,
                    "api_key_state": "configured",
                },
                {
                    "model_id": "xiaomi_mimo_v2_5_pro_token_plan",
                    "source": "model_library",
                    "provider": {"id": "xiaomi_mimo_token_plan_cn", "kind": "xiaomi"},
                    "provider_kind": "xiaomi",
                    "model": "mimo-v2.5-pro",
                    "label": "MiMo V2.5 Pro",
                    "details": {},
                    "api_key_env": "MIMO_API_KEY",
                    "api_key_configured": True,
                    "api_key_state": "configured",
                },
            ],
        }

    fake_llm = SimpleNamespace(
        model_library={
            "relay_openai_gpt_5_5": {"model": "gpt-5.5"},
            "xiaomi_mimo_v2_5_pro_token_plan": {"model": "mimo-v2.5-pro"},
        },
    )
    monkeypatch.setattr(config_service, "get_config_workspace", fake_config_workspace)
    monkeypatch.setattr("config.settings.get_config", lambda: SimpleNamespace(llm=fake_llm))

    gpt_agent = agent_directory_service.create_agent_instance(
        display_name="旧 GPT Agent",
        llm_bindings={"dialogue": {"modelId": "gpt_5_5_gpt_5_5"}},
        primary_mode="chat",
    )
    mimo_agent = agent_directory_service.create_agent_instance(
        display_name="旧 MiMo Agent",
        llm_bindings={"dialogue": {"modelId": "mimo_v2_5_pro"}},
        primary_mode="chat",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()
    by_id = {item["agentId"]: item for item in payload["agents"]}

    assert by_id[gpt_agent["agentId"]]["llmBindings"]["dialogue"]["modelId"] == "relay_openai_gpt_5_5"
    assert by_id[mimo_agent["agentId"]]["llmBindings"]["dialogue"]["modelId"] == "xiaomi_mimo_v2_5_pro_token_plan"
    assert not any(
        item["code"] == "unresolved_model_reference_dialogue"
        for item in payload["health"]["byAgent"].get(gpt_agent["agentId"], [])
    )
    assert not any(
        item["code"] == "unresolved_model_reference_dialogue"
        for item in payload["health"]["byAgent"].get(mimo_agent["agentId"], [])
    )

    stored = json.loads((tmp_path / "workspace" / "agents" / "agents.json").read_text(encoding="utf-8"))
    stored_by_id = {item["agentId"]: item for item in stored["agents"]}
    assert stored_by_id[gpt_agent["agentId"]]["llmBindings"]["dialogue"]["modelId"] == "relay_openai_gpt_5_5"
    assert stored_by_id[mimo_agent["agentId"]]["llmBindings"]["dialogue"]["modelId"] == "xiaomi_mimo_v2_5_pro_token_plan"
    assert stored_by_id[gpt_agent["agentId"]]["metadata"]["llmBindingModelIdRepairs"][-1]["legacyModelId"] == "gpt_5_5_gpt_5_5"
    assert stored_by_id[mimo_agent["agentId"]]["metadata"]["llmBindingModelIdRepairs"][-1]["legacyModelId"] == "mimo_v2_5_pro"


def test_agent_config_workspace_repairs_stale_chat_room_participant_model_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="群聊模型 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-room-model-agent",
    )
    peer = agent_directory_service.create_agent_instance(
        display_name="群聊正常 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-room-model-peer",
    )
    room = chat_room_service.create_chat_room(
        title="配置中心群聊",
        participant_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    room_path = tmp_path / "workspace" / "chat_rooms" / "chat_rooms.json"
    state = json.loads(room_path.read_text(encoding="utf-8"))
    participant = state["rooms"][0]["participants"][0]
    participant["dialogueModelId"] = "missing-room-model"
    participant["llmBindings"] = {"dialogue": {"modelId": "missing-room-model"}}
    room_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    payload = agent_config_workspace_service.get_agent_config_workspace()
    issues = payload["health"]["byAgent"][agent["agentId"]]

    workspace_room = next(
        item
        for item in agent_config_workspace_service._safe_chat_rooms(agents=[agent, peer])
        if item["roomId"] == room["roomId"]
    )
    workspace_participant = next(item for item in workspace_room["participants"] if item["agentId"] == agent["agentId"])
    assert workspace_participant["dialogueModelId"] == "model-primary"
    assert workspace_participant["llmBindings"]["dialogue"]["modelId"] == "model-primary"
    assert not any(
        item["code"] == "unresolved_chat_room_participant_model_reference"
        and "missing-room-model" in item["detail"]
        for item in issues
    )
    repaired_room = chat_room_service.get_chat_room_detail(room["roomId"])
    repaired_participant = next(item for item in repaired_room["participants"] if item["agentId"] == agent["agentId"])
    assert repaired_participant["dialogueModelId"] == "model-primary"
    assert repaired_participant["llmBindings"]["dialogue"]["modelId"] == "model-primary"
