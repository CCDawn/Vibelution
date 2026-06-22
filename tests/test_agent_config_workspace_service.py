import json
from types import SimpleNamespace

import config as config_package
import pytest
from fastapi.testclient import TestClient
from config import ProviderConfig

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.orchestration import context_engine
from core.web.routes import agents as agents_route
from core.web.services import (
    agent_bulk_delete_service,
    agent_config_workspace_service,
    agent_directory_service,
    agent_tool_governance_service,
    agent_mode_binding_service,
    chat_room_service,
    config_service,
    prompt_template_service,
    self_evolution_control_service,
    session_service,
    supervised_agent_service,
    team_service,
)
from tests.helpers.system_agent_state import (
    _mark_config_agent_instances_present,
    _seed_supervised_fixed_role_agent,
)


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _raw_mode_binding(mode: str):
    path = agent_mode_binding_service.mode_binding_path()
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return next(
        item
        for item in payload.get("bindings") or []
        if isinstance(item, dict) and item.get("mode") == mode
    )


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_delete_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervised_agent_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(self_evolution_control_service, "PROJECT_ROOT", tmp_path)
    model_library_ids = {
        str(item.get("model_id") or "").strip()
        for item in _fake_config_workspace()["modelOptions"]
        if str(item.get("model_id") or "").strip()
    }
    model_library_ids.update({"relay_openai_gpt_5_5", "xiaomi_mimo_v2_5_pro_token_plan"})
    monkeypatch.setattr(agent_directory_service, "_configured_model_library_ids", lambda *args, **kwargs: set(model_library_ids))
    monkeypatch.setattr(supervised_agent_service, "_configured_model_library_ids", lambda *args, **kwargs: set(model_library_ids))


def _mark_session_active(tmp_path, session_id: str):
    journal = tmp_path / "workspace" / "sessions" / session_id / "turn_journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("{}\n", encoding="utf-8")


def _fake_config_workspace():
    return {
        "modelOptions": [
            {
                "model_id": "model-primary",
                "source": "model",
                "provider": {"id": "openai"},
                "provider_kind": "openai",
                "model": "gpt-test",
                "label": "GPT Test",
                "details": {},
                "api_key_env": "OPENAI_API_KEY",
                "api_key_configured": True,
                "api_key_state": "configured",
            },
            {
                "model_id": "model-gpt-reasoning",
                "source": "model",
                "provider": {"id": "relay", "kind": "relay", "compat_mode": "openai"},
                "provider_kind": "relay",
                "model": "gpt-5.5",
                "label": "GPT Reasoning",
                "transport": "responses",
                "details": {"transport": "responses"},
                "api_key_env": "RELAY_API_KEY",
                "api_key_configured": True,
                "api_key_state": "configured",
            },
            {
                "model_id": "model-research",
                "source": "model",
                "provider": {"id": "relay", "context_window": 64000},
                "contextWindow": 64000,
                "provider_kind": "relay",
                "model": "research-test",
                "label": "Research Test",
                "details": {},
                "api_key_env": "RELAY_API_KEY",
                "api_key_configured": False,
                "api_key_state": "missing",
            },
        ],
    }


def _seed_agent_avatars(root):
    avatar_dir = root / "workspace" / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    for filename in agent_directory_service.AGENT_AVATAR_FILENAMES:
        (avatar_dir / filename).write_bytes(b"\x89PNG\r\n\x1a\navatar")


def test_agent_registry_repair_migrates_legacy_profile_fields_to_llm_bindings(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    fake_llm = SimpleNamespace(
        get_profile=lambda profile_id=None, role="primary": SimpleNamespace(profile_id=profile_id or "primary"),
        get_model_library_entry_for_profile=lambda profile: ("model-primary", {}),
        model_library={"model-primary": {"model": "gpt-test"}},
    )
    monkeypatch.setattr("config.settings.get_config", lambda: SimpleNamespace(llm=fake_llm))
    registry_path = tmp_path / "workspace" / "agents" / "agents.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "agents": [
                    {
                        "agentId": "agent-legacy",
                        "agentCode": "A014",
                        "displayName": "旧 Agent",
                        "kind": "persistent",
                        "primaryMode": "chat",
                        "roleKey": "",
                        "profileId": "primary",
                        "templateId": "primary",
                        "promptTemplateId": "prompt-chat-default",
                        "directSessionId": "session-legacy",
                        "workspacePath": "workspace/agents/agent-legacy",
                        "toolPolicyId": "default",
                        "memoryPolicyId": "memory-agent-legacy",
                        "createdBy": "legacy",
                        "status": "active",
                        "metadata": {},
                        "createdAt": "2026-06-04T00:00:00+00:00",
                        "updatedAt": "2026-06-04T00:00:00+00:00",
                    }
                ],
                "toolPolicies": {"default": agent_directory_service.default_tool_policy("default")},
                "memoryPolicies": {},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    agent = next(item for item in payload["agents"] if item["agentId"] == "agent-legacy")
    assert agent["llmBindings"]["dialogue"]["modelId"] == "model-primary"
    assert "profileId" not in agent
    assert "templateId" not in agent
    assert all(
        item["code"] != "missing_llm_slot_dialogue"
        for item in payload["health"]["byAgent"].get("agent-legacy", [])
    )
    stored = json.loads(registry_path.read_text(encoding="utf-8"))
    stored_agent = stored["agents"][0]
    assert stored_agent["llmBindings"]["dialogue"]["modelId"] == "model-primary"
    assert "profileId" not in stored_agent
    assert "templateId" not in stored_agent
    assert stored_agent["metadata"]["llmBindingMigration"]["legacyModelSourceId"] == "primary"


def test_agent_config_workspace_marks_gpt_responses_reasoning_effort_models(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    registry_path = tmp_path / "workspace" / "agents" / "agents.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "agents": [],
                "toolPolicies": {},
                "memoryPolicies": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    reasoning_model = next(item for item in payload["agentModelChoices"] if item["modelId"] == "model-gpt-reasoning")
    primary_model = next(item for item in payload["agentModelChoices"] if item["modelId"] == "model-primary")
    assert reasoning_model["supportsReasoningEffort"] is True
    assert reasoning_model["reasoningEffortValues"] == ["low", "medium", "high"]
    assert primary_model["supportsReasoningEffort"] is False
    assert primary_model["reasoningEffortValues"] == []


def test_agent_config_workspace_lists_agents_once_and_derives_references(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    chat_agent = session_service.create_chat_session(title="会话 Agent")
    _mark_session_active(tmp_path, chat_agent["id"])
    research_session = session_service.create_chat_session(title="科研 Agent")
    research_agent = agent_directory_service.update_agent_instance(
        research_session["agentId"],
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        metadata={"researchAgentKey": "broad"},
    )
    agent_mode_binding_service.update_mode_binding(
        "research",
        pool=[research_agent["agentId"]],
        flow_bindings={"broad_search": research_agent["agentId"]},
    )
    chat_room_service.create_chat_room(
        title="研究群聊",
        participant_agent_ids=[chat_agent["agentId"], research_agent["agentId"]],
    )
    archived_agent = agent_directory_service.create_agent_instance(display_name="旧 Agent")
    agent_directory_service.archive_agent_instance(archived_agent["agentId"])

    payload = agent_config_workspace_service.get_agent_config_workspace()

    agent_ids = [item["agentId"] for item in payload["agents"]]
    assert len(agent_ids) == len(set(agent_ids))
    assert chat_agent["agentId"] in agent_ids
    assert research_agent["agentId"] in agent_ids
    agents = {item["agentId"]: item for item in payload["agents"]}
    assert agents[chat_agent["agentId"]]["agentBoundary"]["type"] == "work_session"
    assert agents[chat_agent["agentId"]]["agentBoundary"]["directSessionRole"] == "primary_entry"
    assert agents[research_agent["agentId"]]["agentBoundary"]["type"] == "team_role"
    assert agents[research_agent["agentId"]]["agentBoundary"]["directSessionRole"] == "recovery_channel"
    research_refs = payload["references"][research_agent["agentId"]]
    assert any(item["kind"] == "mode_pool" and item["mode"] == "research" for item in research_refs)
    assert any(item["kind"] == "flow_binding" and item["field"] == "broad_search" for item in research_refs)
    assert any(item["kind"] == "chat_room" and item["sourceLabel"] == "研究群聊" for item in research_refs)
    chat_room_ref = next(item for item in research_refs if item["kind"] == "chat_room")
    assert chat_room_ref["route"].startswith("/chat?room=")
    groups = {item["id"]: item for item in payload["groups"]}
    assert "all" not in groups
    assert groups["active"]["section"] == "status"
    assert groups["active"]["label"] == "可用 Agent"
    assert groups["active"]["count"] == 3
    assert agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID in groups["active"]["agentIds"]
    assert archived_agent["agentId"] not in groups["active"]["agentIds"]
    assert groups["work_session"]["section"] == "boundary"
    assert groups["work_session"]["label"] == "会话入口 Agent"
    assert chat_agent["agentId"] in groups["work_session"]["agentIds"]
    assert research_agent["agentId"] not in groups["work_session"]["agentIds"]
    assert groups["team_role"]["section"] == "boundary"
    assert groups["team_role"]["label"] == "团队/科研角色 Agent"
    assert research_agent["agentId"] in groups["team_role"]["agentIds"]
    assert groups["service_role"]["section"] == "boundary"
    assert groups["service_role"]["label"] == "平台服务 Agent"
    assert agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID in groups["service_role"]["agentIds"]
    assert groups["needs_review"]["section"] == "status"
    assert groups["archived"]["section"] == "status"
    assert archived_agent["agentId"] in groups["archived"]["agentIds"]
    assert groups["research"]["section"] == "mode"
    assert groups["research"]["label"] == "科研模式"
    assert groups["group_chat"]["section"] == "reference"
    assert groups["group_chat"]["label"] == "群聊引用"
    assert groups["team"]["section"] == "reference"
    assert research_agent["agentId"] in groups["research"]["agentIds"]
    assert research_agent["agentId"] in groups["group_chat"]["agentIds"]


def test_agent_config_workspace_keeps_empty_direct_session_out_of_work_session_group(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    session = session_service.create_chat_session(title="Agent 0")
    agent_id = session["agentId"]

    payload = agent_config_workspace_service.get_agent_config_workspace()

    agents = {item["agentId"]: item for item in payload["agents"]}
    groups = {item["id"]: item for item in payload["groups"]}
    assert agents[agent_id]["agentBoundary"]["type"] == "service_role"
    assert agents[agent_id]["agentBoundary"]["directSessionRole"] == "pending_activity"
    assert agents[agent_id]["agentBoundary"]["reason"] == "empty_direct_session"
    assert agent_id not in groups["work_session"]["agentIds"]


def test_agent_config_workspace_promotes_direct_session_after_activity(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    session = session_service.create_chat_session(title="真实会话")
    agent_id = session["agentId"]
    _mark_session_active(tmp_path, session["id"])

    payload = agent_config_workspace_service.get_agent_config_workspace()

    agents = {item["agentId"]: item for item in payload["agents"]}
    groups = {item["id"]: item for item in payload["groups"]}
    assert agents[agent_id]["agentBoundary"]["type"] == "work_session"
    assert agent_id in groups["work_session"]["agentIds"]


def test_agent_boundary_prefers_team_reference_over_protected_service_marker():
    boundary = agent_config_workspace_service._derive_agent_boundary(
        {
            "status": "active",
            "primaryMode": "research",
            "roleKey": "cn_primary_sources",
            "metadata": {
                "protected": True,
                "fixedRole": True,
                "configSurface": "team",
            },
            "directSessionId": "session-source",
        },
        references=[
            {
                "kind": "team",
                "sourceId": "ai-search-team",
                "sourceLabel": "AI 搜索范围团队",
                "mode": "",
                "field": "cn_primary_sources",
                "status": "active",
            }
        ],
    )

    assert boundary["type"] == "team_role"
    assert boundary["reason"] == "team_reference"
    assert boundary["requiresTeamMembership"] == "true"


def test_agent_config_workspace_summary_counts_only_actionable_health_issues():
    summary = agent_config_workspace_service._summary(
        [
            {"status": "active", "runtimeStatus": {}, "agentInboxPendingCount": 2},
            {"status": "archived", "runtimeStatus": {}, "agentInboxPendingCount": 1},
        ],
        [],
        [
            {"severity": "info", "code": "pending_inbox_messages"},
            {"severity": "warning", "code": "missing_prompt_template"},
            {"severity": "blocking", "code": "unresolved_model_reference_dialogue"},
        ],
        [],
        [],
        {"modes": {"chat": {}}},
    )

    assert summary["healthIssueCount"] == 2
    assert summary["warningIssueCount"] == 1
    assert summary["blockingIssueCount"] == 1
    assert summary["inboxPendingCount"] == 3


def test_agent_config_workspace_persists_context_compression_policy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="压缩策略 Agent")

    workspace_before = agent_config_workspace_service.get_agent_config_workspace()
    before_agent = next(item for item in workspace_before["agents"] if item["agentId"] == agent["agentId"])
    assert before_agent["contextCompressionPolicy"] == {"mode": "inherit"}
    assert before_agent["contextCompressionEffectivePolicy"]["source"] == "global"

    inherited = agent_directory_service.effective_agent_context_compression_policy(
        {"contextCompressionPolicy": {"mode": "inherit"}},
        {
            "max_token_limit": 32000,
            "max_compressions_per_session": 20,
            "levels": {},
            "summary_chars": {},
            "preservation": {},
        },
        context_window_limit=12000,
    )
    assert inherited["maxTokenLimit"] == 32000
    assert inherited["effectiveTokenLimit"] == 12000

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "contextCompressionPolicy": {
                "mode": "custom",
                "enabled": False,
                "maxTokenLimit": 9000,
                "maxCompressionsPerSession": 4,
                "levels": {"light": 0.5, "standard": 0.7, "deep": 0.85, "emergency": 0.93},
                "summaryChars": {"light": 400, "standard": 800, "deep": 1200, "emergency": 1600},
                "preservation": {
                    "keepAiMessages": 3,
                    "preserveErrors": True,
                    "extractKeyDecisions": False,
                },
            }
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["contextCompressionPolicy"]["mode"] == "custom"
    assert updated["contextCompressionPolicy"]["enabled"] is False
    assert updated["contextCompressionEffectivePolicy"]["source"] == "agent_custom"
    assert updated["contextCompressionEffectivePolicy"]["effectiveTokenLimit"] == 9000
    assert updated["contextCompressionEffectivePolicy"]["levels"]["standard"] == 0.7
    assert updated["contextCompressionEffectivePolicy"]["summaryChars"]["deep"] == 1200
    assert updated["contextCompressionEffectivePolicy"]["preservation"]["extractKeyDecisions"] is False

    workspace_after = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in workspace_after["agents"] if item["agentId"] == agent["agentId"])
    assert workspace_agent["contextCompressionEffectivePolicy"]["source"] == "agent_custom"
    assert workspace_agent["contextCompressionEffectivePolicy"]["maxCompressionsPerSession"] == 4

    stored = agent_directory_service.get_agent(agent["agentId"])
    assert stored["contextCompressionPolicy"]["mode"] == "custom"
    assert stored["contextCompressionPolicy"]["maxTokenLimit"] == 9000


def test_agent_directory_reuses_repaired_snapshot_for_repeated_reads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent_directory_service.create_agent_instance(display_name="缓存 Agent")

    repair_calls = 0
    real_repair = agent_directory_service.repair_agent_directory

    def tracked_repair():
        nonlocal repair_calls
        repair_calls += 1
        return real_repair()

    monkeypatch.setattr(agent_directory_service, "repair_agent_directory", tracked_repair)

    first = agent_directory_service.list_agents(include_archived=True)
    second = agent_directory_service.list_agents(include_archived=True)
    looked_up = agent_directory_service.get_agent(first[0]["agentId"])

    assert [item["agentId"] for item in first] == [item["agentId"] for item in second]
    assert looked_up and looked_up["agentId"] == first[0]["agentId"]
    assert repair_calls == 1


def test_agent_directory_repaired_snapshot_cache_invalidates_after_save(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="缓存 Agent",
        metadata={"cacheProbe": "before"},
    )

    assert agent_directory_service.get_agent(agent["agentId"])["metadata"]["cacheProbe"] == "before"
    assert agent_directory_service.get_agent(agent["agentId"])["metadata"]["cacheProbe"] == "before"

    agent_directory_service.update_agent_instance(agent["agentId"], metadata={"cacheProbe": "after"})

    assert agent_directory_service.get_agent(agent["agentId"])["metadata"]["cacheProbe"] == "after"


def test_repair_agent_directory_legacy_fields_is_idempotent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    fake_llm = SimpleNamespace(
        get_profile=lambda profile_id=None, role="primary": SimpleNamespace(profile_id=profile_id or "primary"),
        get_model_library_entry_for_profile=lambda profile: ("model-primary", {}),
        model_library={"model-primary": {"model": "gpt-test"}},
    )
    monkeypatch.setattr("config.settings.get_config", lambda: SimpleNamespace(llm=fake_llm))

    registry_path = tmp_path / "workspace" / "agents" / "agents.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "agents": [
                    {
                        "agentId": "agent-legacy",
                        "agentCode": "A014",
                        "displayName": "旧 Agent",
                        "kind": "persistent",
                        "primaryMode": "chat",
                        "roleKey": "chat",
                        "profileId": "primary",
                        "templateId": "primary",
                        "promptTemplateId": "prompt-chat-default",
                        "directSessionId": "session-legacy",
                        "workspacePath": "workspace/agents/agent-legacy",
                        "toolPolicyId": "default",
                        "memoryPolicyId": "memory-agent-legacy",
                        "createdBy": "legacy",
                        "status": "active",
                        "metadata": {},
                        "createdAt": "2026-06-04T00:00:00+00:00",
                        "updatedAt": "2026-06-04T00:00:00+00:00",
                    }
                ],
                "toolPolicies": {"default": agent_directory_service.default_tool_policy("default")},
                "memoryPolicies": {},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    save_calls = 0
    real_save_state = agent_directory_service.save_state

    def tracked_save_state(state: dict) -> dict:
        nonlocal save_calls
        save_calls += 1
        return real_save_state(state)

    monkeypatch.setattr(agent_directory_service, "save_state", tracked_save_state)

    first = agent_directory_service.repair_agent_directory()
    second = agent_directory_service.repair_agent_directory()

    assert save_calls == 1
    assert all("profileId" not in item for item in first["agents"] if isinstance(item, dict))
    assert all("profileId" not in item for item in second["agents"] if isinstance(item, dict))


def test_work_session_boundary_skips_persona_task_and_team_onboarding_requirements(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    session = session_service.create_chat_session(title="开发会话")
    _mark_session_active(tmp_path, session["id"])
    agent_id = session["agentId"]
    agent = agent_directory_service.get_agent(agent_id)
    metadata = dict(agent["metadata"])
    metadata.pop("personaProfile", None)
    metadata.pop("taskProfile", None)
    metadata["onboardingMissing"] = ["personaProfile", "taskProfile"]
    agent_directory_service.update_agent_instance(agent_id, metadata=metadata)

    payload = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in payload["agents"] if item["agentId"] == agent_id)
    issue_codes = {item["code"] for item in workspace_agent["health"]}

    assert workspace_agent["agentBoundary"]["type"] == "work_session"
    assert workspace_agent["agentBoundary"]["requiresPersonaProfile"] == "false"
    assert workspace_agent["agentBoundary"]["requiresTaskProfile"] == "false"
    assert "agent_onboarding_incomplete" not in issue_codes


def test_agent_directory_assigns_default_avatar_from_workspace_avatars(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)

    chat_agent = agent_directory_service.create_agent_instance(display_name="会话 Agent")
    deep_agent = agent_directory_service.create_agent_instance(
        display_name="深搜 Agent",
        primary_mode="research",
        role_key="research_deep",
        prompt_template_id="prompt-research-deep",
    )
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    agents = {item["agentId"]: item for item in workspace["agents"]}

    assert chat_agent["avatarImagePath"].startswith("workspace/avatars/")
    assert chat_agent["avatarImageUrl"].startswith("/api/agents/avatar-image/")
    assert deep_agent["avatarImagePath"] == "workspace/avatars/06-deep-investigator.png"
    assert deep_agent["avatarImageUrl"] == "/api/agents/avatar-image/06-deep-investigator.png"
    assert agents[chat_agent["agentId"]]["avatarImageUrl"] == chat_agent["avatarImageUrl"]
    assert agents[deep_agent["agentId"]]["metadata"]["avatarImageSource"] == "default"

    response = client.get("/api/agents/avatar-image/06-deep-investigator.png")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


def test_agent_avatar_can_be_selected_uploaded_and_reset(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _seed_agent_avatars(tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="头像 Agent", primary_mode="research", role_key="research_deep")

    options = client.get("/api/agents/avatar-options")
    assert options.status_code == 200
    assert options.json()["count"] >= 2

    update_response = client.patch(
        f"/api/agents/{agent['agentId']}/avatar",
        json={"avatarImagePath": "workspace/avatars/01-session-agent.png"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["avatarImagePath"] == "workspace/avatars/01-session-agent.png"
    assert update_response.json()["metadata"]["avatarImageSource"] == "custom"

    upload_response = client.post(
        f"/api/agents/{agent['agentId']}/avatar-image",
        json={
            "filename": "custom.png",
            "contentType": "image/png",
            "dataBase64": "iVBORw0KGgphdmF0YXI=",
        },
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()
    assert uploaded["path"].startswith("workspace/avatars/agent-avatar-")
    assert uploaded["agent"]["metadata"]["avatarImageSource"] == "custom"
    assert (tmp_path / uploaded["path"]).exists()

    reset_response = client.patch(
        f"/api/agents/{agent['agentId']}/avatar",
        json={"resetToDefault": True},
    )
    assert reset_response.status_code == 200
    assert reset_response.json()["avatarImagePath"] == "workspace/avatars/06-deep-investigator.png"
    assert reset_response.json()["metadata"]["avatarImageSource"] == "default"


def test_agent_config_workspace_reports_missing_model_key_and_prompt(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="待处理 Agent",
        llm_bindings={"dialogue": {"modelId": "model-research"}},
        primary_mode="research",
        role_key="research_deep",
        prompt_template_id="prompt-missing",
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    issues = payload["health"]["byAgent"][agent["agentId"]]
    assert {item["code"] for item in issues} >= {"missing_llm_slot_api_key_dialogue", "missing_prompt_template", "missing_direct_session"}
    assert payload["health"]["counts"]["warning"] >= 3
    assert agent["agentId"] in {item for group in payload["groups"] if group["id"] == "needs_review" for item in group["agentIds"]}
    model_option_ids = [item["model_id"] for item in payload["modelOptions"]]
    agent_model_choice_ids = [item["modelId"] for item in payload["agentModelChoices"]]
    assert "model-primary" in model_option_ids
    assert "model-research" in model_option_ids
    assert "model-primary" in agent_model_choice_ids
    assert "model-research" in agent_model_choice_ids
    research_choice = next(item for item in payload["agentModelChoices"] if item["modelId"] == "model-research")
    assert research_choice["contextWindow"] == 64000


def test_agent_api_effective_compression_uses_dialogue_model_context_window(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    cfg = config_package.get_config().model_copy(deep=True)
    cfg.context_compression.max_token_limit = 32768
    cfg.llm.providers["window-test-provider"] = ProviderConfig(
        provider_id="window-test-provider",
        kind="openai",
        api_key_env="WINDOW_TEST_API_KEY",
        base_url="https://example.test/v1",
        context_window=900000,
    )
    cfg.llm.model_library["window-test-model"] = {
        "provider_id": "window-test-provider",
        "model": "window-test",
        "label": "Window Test",
    }
    monkeypatch.setattr(config_package, "get_config", lambda: cfg)

    agent = agent_directory_service.create_agent_instance(
        display_name="窗口 Agent",
        llm_bindings={"dialogue": {"modelId": "window-test-model"}},
    )

    payload = agent_directory_service._agent_to_api_summary(agent)
    policy = payload["contextCompressionEffectivePolicy"]
    assert policy["maxTokenLimit"] == 32768
    assert policy["effectiveTokenLimit"] == 32768
    assert policy["compressionTriggerTokenLimit"] == 32768
    assert policy["contextWindowLimit"] == 900000
    assert policy["modelContextWindowLimit"] == 900000


def test_agent_instance_generates_public_person_name_and_keeps_functional_name(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    agent = agent_directory_service.create_agent_instance(display_name="科研 Agent", primary_mode="research")

    assert agent["displayName"]
    assert agent["displayName"] != "科研 Agent"
    assert agent["agentCode"]
    assert agent["metadata"]["functionalDisplayName"] == "科研 Agent"
    assert agent["metadata"]["displayNameSource"] == "generated_person_name"
    assert agent["workspaceTerritory"]["privateRoot"] == agent["workspacePath"]
    assert agent["workspaceTerritory"]["sharedRoot"] == "workspace/shared"
    assert agent["workspaceTerritory"]["writeScopes"] == ["private"]
    for subdir in ("scratch", "notes", "inbox", "outbox", "runs", "artifacts"):
        assert (tmp_path / agent["workspaceTerritory"]["subdirs"][subdir]).is_dir()
    assert (tmp_path / "workspace" / "shared").is_dir()


def test_agent_private_workspace_path_accepts_standard_relative_path_without_resolve(monkeypatch):
    def fail_resolve(*args, **kwargs):
        raise AssertionError("standard Agent workspace paths should not hit filesystem resolve")

    monkeypatch.setattr(agent_directory_service, "_resolve_project_path", fail_resolve)

    assert agent_directory_service._is_agent_private_workspace_path("workspace/agents/agent-alpha", "agent-alpha")
    assert agent_directory_service._is_agent_private_workspace_path("workspace\\agents\\agent-alpha", "agent-alpha")


def test_repair_agent_directory_moves_legacy_workspace_into_private_territory(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="旧会话 Agent")
    state = agent_directory_service.load_state()
    raw = next(item for item in state["agents"] if item["agentId"] == agent["agentId"])
    raw["workspacePath"] = "workspace/sessions/session-legacy"
    policy_id = raw["memoryPolicyId"]
    state["memoryPolicies"][policy_id] = {
        "policyId": policy_id,
        "privateMemoryRoot": "workspace/sessions/session-legacy/memory",
        "readSharedGroups": ["project"],
        "writeSharedGroups": ["project"],
    }
    agent_directory_service.save_state(state)

    repaired = agent_directory_service.get_agent(agent["agentId"])

    assert repaired["workspacePath"] == f"workspace/agents/{agent['agentId']}"
    assert repaired["workspaceTerritory"]["legacyWorkspacePath"] == "workspace/sessions/session-legacy"
    assert repaired["memoryPolicy"]["privateMemoryRoot"] == f"workspace/agents/{agent['agentId']}/memory"
    assert repaired["memoryPolicy"]["agentInboxMessagesPath"] == f"workspace/agents/{agent['agentId']}/events/agent_inbox_messages.jsonl"
    assert repaired["memoryPolicy"]["readSharedGroups"] == ["project"]
    assert repaired["memoryPolicy"]["writeSharedGroups"] == ["project"]
    assert repaired["memoryPolicy"]["readKnowledgeBaseIds"] == []
    assert repaired["memoryPolicy"]["proposeKnowledgeBaseIds"] == []
    assert repaired["memoryPolicy"]["reviewKnowledgeBaseIds"] == []
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    issues = workspace["health"]["byAgent"][agent["agentId"]]
    assert any(item["code"] == "legacy_workspace_retained" and item["severity"] == "info" for item in issues)


def test_agent_config_workspace_logs_stage_timings_and_reuses_loaded_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="计时 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        metadata={
            "personaProfile": {"personality": "稳定记录加载计时。"},
            "taskProfile": {"mission": "验证 Agent 配置工作区日志。", "taskTypes": ["diagnostics"]},
        },
    )
    captured_bindings = {}
    recorded_events = []

    def fake_get_mode_bindings_payload(*, agent_options=None):
        captured_bindings["agentOptions"] = list(agent_options or [])
        return {
            "modes": {
                "research": {
                    "mode": "research",
                    "defaultAgentId": agent["agentId"],
                    "availableAgentIds": [agent["agentId"]],
                    "pool": [agent["agentId"]],
                    "flowBindings": {},
                    "slots": {},
                    "excludedAgentIds": [],
                    "excludedSlots": [],
                }
            },
            "repairWarnings": [],
        }

    monkeypatch.setattr(agent_config_workspace_service, "get_mode_bindings_payload", fake_get_mode_bindings_payload)
    monkeypatch.setattr(
        agent_config_workspace_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    captured_agents = {item["agentId"]: item for item in captured_bindings["agentOptions"]}
    assert captured_agents[agent["agentId"]]["primaryMode"] == "research"
    assert agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID in captured_agents
    assert payload["summary"]["agentCount"] == 2
    loaded_events = [
        event for event in recorded_events if event[0][:3] == ("agent_configuration", "workspace", "agent_config.workspace.loaded")
    ]
    assert loaded_events
    timings = loaded_events[-1][1]["fields"]["timingsMs"]
    assert {"list_agents", "mode_bindings", "runtime_histories", "runtime_statuses", "total"}.issubset(timings)
    assert timings["total"] >= timings["mode_bindings"]
    assert loaded_events[-1][1]["fields"]["loadModes"] == {
        "chatRooms": "compact",
        "teams": "graph_references",
        "runtimeStatuses": "batched",
    }


def test_agent_config_workspace_records_model_reference_resolution(monkeypatch):
    recorded_events = []
    monkeypatch.setattr(
        agent_config_workspace_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    agent_config_workspace_service._record_model_reference_resolution([])

    assert recorded_events
    args, kwargs = recorded_events[-1]
    assert args[:3] == ("agent_config", "model_binding", "agent_config.model_references.resolved")
    assert kwargs["outcome"] == "resolved"
    assert kwargs["fields"]["unresolvedCount"] == 0


def test_agent_directory_list_agents_logs_slow_hydration_breakdown(monkeypatch):
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    agent_directory_service._record_agent_list_loaded(
        include_archived=True,
        detail="full",
        raw_agent_count=49,
        returned_agent_count=49,
        timings={
            "lock_wait": 12.0,
            "repair": 42.0,
            "filter": 1.0,
            "hydrate": 3600.0,
            "to_api": 84.0,
            "sort": 0.5,
            "total": 3740.0,
        },
        hydration_timings={
            "tool_policies": 1.0,
            "memory_policies": 1.5,
            "tool_governance_requests": 2100.0,
            "group_context_events": 900.0,
            "agent_inbox_messages": 520.0,
        },
    )

    assert recorded_events
    args, kwargs = recorded_events[-1]
    assert args[:3] == ("agent_directory", "list_agents", "agent_directory.list_agents.slow")
    assert kwargs["level"] == "warning"
    fields = kwargs["fields"]
    assert fields["includeArchived"] is True
    assert fields["detail"] == "full"
    assert fields["rawAgentCount"] == 49
    assert fields["returnedAgentCount"] == 49
    assert fields["timingsMs"]["hydrate"] == 3600.0
    assert fields["hydrationTimingsMs"]["tool_governance_requests"] == 2100.0
    assert fields["slowestStage"] == "hydrate"
    assert fields["slowestHydrationStage"] == "tool_governance_requests"


def test_agent_directory_summary_list_skips_heavy_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created = agent_directory_service.create_agent_instance(display_name="Summary Agent", primary_mode="chat")
    hydration_calls = 0

    def fail_hydration(*args, **kwargs):
        nonlocal hydration_calls
        hydration_calls += 1
        raise AssertionError("summary agent list should not hydrate policies or activity")

    monkeypatch.setattr(agent_directory_service, "_build_agent_api_hydration_context", fail_hydration)

    agents = agent_directory_service.list_agents(detail="summary")

    assert hydration_calls == 0
    agent = next(item for item in agents if item["agentId"] == created["agentId"])
    assert agent["displayName"] == created["displayName"]
    assert "toolPolicy" not in agent
    assert "memoryPolicy" not in agent
    assert "toolGovernanceRequests" not in agent
    assert "groupContextEvents" not in agent
    assert "agentInboxMessages" not in agent
    assert "agentInboxPendingCount" not in agent


def test_agent_directory_config_list_skips_chat_and_inbox_activity_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    created = agent_directory_service.create_agent_instance(display_name="Config Agent", primary_mode="chat")
    reviewer = agent_directory_service.create_agent_instance(display_name="Reviewer Agent", primary_mode="chat")
    request = agent_tool_governance_service.submit_tool_governance_request(
        created["agentId"],
        proposed_by_agent_id=reviewer["agentId"],
        grant_tools=["grep_search_tool"],
        reason="配置页需要显示最近的工具申请。",
    )
    hydration_calls = 0

    def fail_full_hydration(*args, **kwargs):
        nonlocal hydration_calls
        hydration_calls += 1
        raise AssertionError("config agent list should not hydrate group context or inbox activity")

    window_batch_calls = 0

    def fake_model_context_windows(agents):
        nonlocal window_batch_calls
        window_batch_calls += 1
        return {
            agent_directory_service.agent_dialogue_model_id(agent): 123456
            for agent in agents
            if agent_directory_service.agent_dialogue_model_id(agent)
        }

    monkeypatch.setattr(
        agent_directory_service,
        "agent_dialogue_model_id",
        lambda agent: f"dialogue-{agent.get('agentId')}" if isinstance(agent, dict) and agent.get("agentId") else "",
    )
    with agent_directory_service._AGENT_API_HYDRATION_CACHE_LOCK:
        agent_directory_service._AGENT_API_HYDRATION_CACHE_SIGNATURE = None
        agent_directory_service._AGENT_API_HYDRATION_CACHE_FAST_SIGNATURE = None
        agent_directory_service._AGENT_API_HYDRATION_CACHE = None

    monkeypatch.setattr(agent_directory_service, "_build_agent_api_hydration_context", fail_full_hydration)
    monkeypatch.setattr(agent_directory_service, "_model_context_window_limits_for_agents", fake_model_context_windows)
    monkeypatch.setattr(
        agent_directory_service,
        "_agent_api_config_hydration_signature",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cold config hydration should not scan exact signatures")),
    )

    agents = agent_directory_service.list_agents(detail="config")

    assert hydration_calls == 0
    assert window_batch_calls == 1
    agent = next(item for item in agents if item["agentId"] == created["agentId"])
    assert agent["toolPolicy"]["policyId"] == created["toolPolicyId"]
    assert agent["memoryPolicy"]["policyId"] == created["memoryPolicyId"]
    assert agent["contextCompressionEffectivePolicy"]["contextWindowLimit"] == 123456
    assert agent["toolGovernanceRequests"][0]["requestId"] == request["requestId"]
    assert agent["groupContextEvents"] == []
    assert agent["agentInboxMessages"] == []
    assert agent["agentInboxPendingCount"] == 0
    assert agent["activityHydration"] == "config"

    monkeypatch.setattr(
        agent_directory_service,
        "_load_recent_tool_governance_requests_for_agents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("config hydration should reuse cache")),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "_count_pending_agent_inbox_messages_for_agents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("config inbox counts should reuse cache")),
    )

    cached_agents = agent_directory_service.list_agents(detail="config")
    cached_agent = next(item for item in cached_agents if item["agentId"] == created["agentId"])
    assert cached_agent["toolGovernanceRequests"][0]["requestId"] == request["requestId"]
    assert window_batch_calls == 1


def test_agent_config_workspace_batches_agent_api_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", primary_mode="chat")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", primary_mode="research")
    agent_directory_service.write_agent_inbox_message(
        alpha["agentId"],
        content="请处理待办。",
        created_by="test",
    )
    agent_directory_service.write_group_context_event(
        beta["agentId"],
        {
            "sourceRoomId": "room-test",
            "sourceRoundId": "round-1",
            "topic": "配置页性能",
            "summary": "确认批量 hydration。",
            "ownMessage": "Beta ready",
            "peerHighlights": [],
        },
    )
    agent_tool_governance_service.submit_tool_governance_request(
        alpha["agentId"],
        grant_tools=["grep_search_tool"],
        reason="low-risk check",
        apply_mode="review",
    )
    full_read_paths = []
    original_read_jsonl = agent_directory_service._read_jsonl

    def counting_read_jsonl(path):
        full_read_paths.append(str(path).replace("\\", "/"))
        return original_read_jsonl(path)

    monkeypatch.setattr(agent_directory_service, "_read_jsonl", counting_read_jsonl)

    payload = agent_config_workspace_service.get_agent_config_workspace()

    agents = {item["agentId"]: item for item in payload["agents"]}
    assert agents[alpha["agentId"]]["agentInboxPendingCount"] == 1
    assert agents[alpha["agentId"]]["agentInboxMessages"] == []
    assert len(agents[alpha["agentId"]]["toolGovernanceRequests"]) == 1
    assert agents[beta["agentId"]]["groupContextEvents"] == []
    assert agents[alpha["agentId"]]["toolPolicy"]["policyId"]
    assert agents[alpha["agentId"]]["memoryPolicy"]["privateMemoryRoot"].endswith(f"{alpha['agentId']}/memory")
    assert not any("agent_inbox_messages.jsonl" in path for path in full_read_paths)
    assert not any("group_context_events.jsonl" in path for path in full_read_paths)
    assert not any("tool_governance_requests.jsonl" in path for path in full_read_paths)


def test_agent_directory_full_list_reuses_hydration_until_event_signature_changes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Cached Hydration Agent", primary_mode="chat")
    agent_directory_service.write_agent_inbox_message(
        agent["agentId"],
        content="首条待办。",
        created_by="test",
    )
    read_recent_calls = 0
    original_read_recent = agent_directory_service._read_recent_jsonl

    def counting_read_recent(*args, **kwargs):
        nonlocal read_recent_calls
        read_recent_calls += 1
        return original_read_recent(*args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "_read_recent_jsonl", counting_read_recent)

    first = agent_directory_service.list_agents(include_archived=True)
    first_call_count = read_recent_calls
    second = agent_directory_service.list_agents(include_archived=True)

    assert first_call_count > 0
    assert read_recent_calls == first_call_count
    assert first == second

    agent_directory_service.write_agent_inbox_message(
        agent["agentId"],
        content="第二条待办。",
        created_by="test",
    )
    updated = agent_directory_service.list_agents(include_archived=True)

    assert read_recent_calls > first_call_count
    updated_agent = next(item for item in updated if item["agentId"] == agent["agentId"])
    assert updated_agent["agentInboxPendingCount"] == 2


def test_agent_directory_full_list_fast_cache_skips_event_signature_scan_on_hit(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Fast Cached Hydration Agent", primary_mode="chat")
    agent_directory_service.write_agent_inbox_message(
        agent["agentId"],
        content="首条待办。",
        created_by="test",
    )
    first = agent_directory_service.list_agents(include_archived=True)
    signature_paths: list[str] = []
    original_signature = agent_directory_service._jsonl_signature

    def counting_signature(path):
        signature_paths.append(str(path).replace("\\", "/"))
        return original_signature(path)

    monkeypatch.setattr(agent_directory_service, "_jsonl_signature", counting_signature)

    second = agent_directory_service.list_agents(include_archived=True)

    assert second == first
    assert signature_paths == []

    agent_directory_service.write_agent_inbox_message(
        agent["agentId"],
        content="第二条待办。",
        created_by="test",
    )
    signature_paths.clear()
    updated = agent_directory_service.list_agents(include_archived=True)

    assert any(path.endswith("agent_inbox_messages.jsonl") for path in signature_paths)
    updated_agent = next(item for item in updated if item["agentId"] == agent["agentId"])
    assert updated_agent["agentInboxPendingCount"] == 2


def test_agent_directory_full_list_fast_cache_invalidates_after_tool_governance_write(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Governance Cached Hydration Agent", primary_mode="chat")
    agent_directory_service.list_agents(include_archived=True)
    signature_paths: list[str] = []
    original_signature = agent_directory_service._jsonl_signature

    def counting_signature(path):
        signature_paths.append(str(path).replace("\\", "/"))
        return original_signature(path)

    monkeypatch.setattr(agent_directory_service, "_jsonl_signature", counting_signature)
    agent_tool_governance_service.submit_tool_governance_request(
        agent["agentId"],
        grant_tools=["grep_search_tool"],
        reason="low-risk check",
        apply_mode="review",
    )

    signature_paths.clear()
    updated = agent_directory_service.list_agents(include_archived=True)

    assert any(path.endswith("tool_governance_requests.jsonl") for path in signature_paths)
    updated_agent = next(item for item in updated if item["agentId"] == agent["agentId"])
    assert len(updated_agent["toolGovernanceRequests"]) == 1


def test_agent_config_workspace_defers_inbox_messages_while_full_detail_preserves_older_pending(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="Pending Tail Agent", primary_mode="chat")
    path = agent_directory_service._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "eventId": "older-pending",
            "messageId": "older-pending",
            "status": "pending",
            "content": "仍需处理",
            "createdAt": "2026-06-01T00:00:00+00:00",
        }
    ]
    rows.extend(
        {
            "eventId": f"consumed-{index}",
            "messageId": f"consumed-{index}",
            "status": "consumed",
            "content": f"已处理 {index}",
            "createdAt": f"2026-06-01T00:00:{index:02d}+00:00",
        }
        for index in range(24)
    )
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n", encoding="utf-8")

    payload = agent_config_workspace_service.get_agent_config_workspace()

    workspace_agent = next(item for item in payload["agents"] if item["agentId"] == agent["agentId"])
    assert workspace_agent["agentInboxPendingCount"] == 1
    assert workspace_agent["agentInboxMessages"] == []
    full_agent = next(item for item in agent_directory_service.list_agents(include_archived=True) if item["agentId"] == agent["agentId"])
    assert [item["messageId"] for item in full_agent["agentInboxMessages"]] == ["older-pending"]
    assert agent_directory_service.list_agent_inbox_messages_for_agent(agent["agentId"], status="pending", limit=8)[0]["messageId"] == "older-pending"


def test_agent_config_workspace_reuses_loaded_agents_for_policy_options(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="Policy Agent")
    monkeypatch.setattr(
        agent_config_workspace_service,
        "list_agent_policy_options",
        lambda: (_ for _ in ()).throw(AssertionError("policy options should be derived from loaded agents")),
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert any(item["policyId"] == agent["toolPolicyId"] for item in payload["toolPolicies"])
    assert any(item["policyId"] == agent["memoryPolicyId"] for item in payload["memoryPolicies"])


def test_agent_registry_rejects_suspicious_direct_session_agent_shrink(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    for index in range(9):
        agent_directory_service.create_agent_instance(
            display_name=f"Session Agent {index}",
            direct_session_id=f"session-{index}",
        )
    before = agent_directory_service.load_state()
    before_count = len(before["agents"])

    with pytest.raises(agent_directory_service.AgentDirectoryError, match="suspicious Agent registry shrink"):
        agent_directory_service.save_state(
            {
                "agents": [
                    {
                        "agentId": "agent-only",
                        "displayName": "Only Agent",
                        "status": "active",
                    }
                ]
            }
        )

    after = agent_directory_service.load_state()
    assert len(after["agents"]) == before_count
    assert {item["agentId"] for item in after["agents"]} == {item["agentId"] for item in before["agents"]}


def test_agent_config_workspace_uses_compact_room_and_team_indexes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    room = chat_room_service.create_chat_room(
        title="配置中心群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    team = team_service.create_team(
        name="配置中心团队",
        members=[{"agentId": alpha["agentId"], "role": "lead"}],
    )

    def fail_session_scan():
        raise AssertionError("config workspace should not scan sessions through compact room/team indexes")

    monkeypatch.setattr(session_service, "list_sessions", fail_session_scan)

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert payload["summary"]["chatRoomCount"] == 2
    assert payload["summary"]["teamCount"] == 1
    assert any(item["roomId"] == room["roomId"] for item in payload["chatRooms"])
    alpha_refs = payload["references"][alpha["agentId"]]
    assert any(item["kind"] == "chat_room" and item["sourceLabel"] == "配置中心群聊" for item in alpha_refs)
    assert any(item["kind"] == "team" and item["sourceLabel"] == "配置中心团队" for item in alpha_refs)
    team_indexes = payload["teamIndexes"]
    assert any(
        item["section"] == "team_index"
        and item["label"] == "配置中心团队"
        and item["agentIds"] == [alpha["agentId"]]
        and item["count"] == 1
        for item in team_indexes
    )


def test_agent_config_workspace_uses_config_agent_detail(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    created = agent_directory_service.create_agent_instance(display_name="轻量配置 Agent")
    captured_details: list[str] = []
    real_list_agents = agent_config_workspace_service.list_agents

    def capture_list_agents(*, include_archived=False, detail="full"):
        captured_details.append(str(detail))
        return real_list_agents(include_archived=include_archived, detail=detail)

    def fail_full_hydration(*args, **kwargs):
        raise AssertionError("Agent Center should use detail=config instead of full Agent hydration")

    monkeypatch.setattr(agent_config_workspace_service, "list_agents", capture_list_agents)
    monkeypatch.setattr(agent_directory_service, "_build_agent_api_hydration_context", fail_full_hydration)

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert captured_details == ["config"]
    workspace_agent = next(item for item in payload["agents"] if item["agentId"] == created["agentId"])
    assert workspace_agent["toolPolicy"]["policyId"] == created["toolPolicyId"]
    assert workspace_agent["activityHydration"] == "config"
    assert workspace_agent["groupContextEvents"] == []
    assert workspace_agent["agentInboxMessages"] == []


def test_agent_config_workspace_hides_empty_teams_from_team_indexes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = agent_directory_service.create_agent_instance(display_name="数据发现")
    team_service._save_index(
        {
            "schemaVersion": team_service.SCHEMA_VERSION,
            "updatedAt": "2026-05-18T12:00:00Z",
            "teams": [
                {
                    "teamId": "empty-challenge-cup-team",
                    "name": "挑战杯科研团队",
                    "status": "active",
                    "teamKind": "research",
                    "teamSource": "research_organization",
                    "members": [],
                },
                {
                    "teamId": "challenge-cup-ai-research-team",
                    "name": "挑战杯ai科研团队",
                    "status": "active",
                    "teamKind": "research",
                    "teamSource": "research_organization",
                    "members": [{"agentId": alpha["agentId"], "role": "数据发现"}],
                },
            ],
        }
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()
    team_ids = {item["teamId"] for item in payload["teams"]}
    team_indexes = {item["id"]: item for item in payload["teamIndexes"]}

    assert payload["summary"]["teamCount"] == 1
    assert "empty-challenge-cup-team" not in team_ids
    assert "team:empty-challenge-cup-team" not in team_indexes
    assert team_indexes["team:challenge-cup-ai-research-team"]["agentIds"] == [alpha["agentId"]]


def test_agent_config_workspace_exposes_ai_search_source_scope_indexes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    owner = agent_directory_service.create_agent_instance(display_name="Scope Owner")
    fallback = agent_directory_service.create_agent_instance(display_name="Scope Fallback")
    team = team_service.create_team(
        name="AI Search Index",
        purpose="track source scope",
        members=[
            {"agentId": owner["agentId"], "role": "scope_owner"},
            {"agentId": fallback["agentId"], "role": "fallback"},
        ],
        team_kind="ai_search",
        team_category="AI 搜索",
        team_source="ai_search",
    )
    monkeypatch.setattr(
        agent_config_workspace_service,
        "_safe_team_source_scope",
        lambda item: {
            "groups": [
                {
                    "groupId": "global_primary",
                    "label": "全球主源",
                    "ownerRole": "scope_owner",
                    "tier": "tier1",
                    "description": "primary global sources",
                    "sourceCount": 3,
                    "enabledByDefault": True,
                    "evidenceRole": "primary",
                }
            ]
        }
        if item.get("teamId") == team["teamId"]
        else None,
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()
    indexes = {item["id"]: item for item in payload["teamIndexes"]}

    team_index = indexes[f"team:{team['teamId']}"]
    assert team_index["section"] == "team_index"
    assert team_index["teamKind"] == "ai_search"
    assert team_index["agentIds"] == [owner["agentId"], fallback["agentId"]]
    source_index = indexes[f"source:{team['teamId']}:global_primary"]
    assert source_index["section"] == "source_scope"
    assert source_index["agentIds"] == [owner["agentId"]]
    assert source_index["sourceCount"] == 3
    assert source_index["enabledByDefault"] is True
    assert source_index["evidenceRole"] == "primary"


def test_agent_config_workspace_expands_ai_search_source_scope_indexes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    team = team_service.ensure_ai_search_system_team()

    payload = agent_config_workspace_service.get_agent_config_workspace()

    indexes = {item["id"]: item for item in payload["teamIndexes"]}
    assert indexes["team:ai-search-team"]["label"] == "AI 搜索范围团队"
    assert indexes["team:ai-search-team"]["section"] == "team_index"
    assert indexes["team:ai-search-team"]["count"] == 4
    assert indexes["source:ai-search-team:global_official"]["section"] == "source_scope"
    assert indexes["source:ai-search-team:global_official"]["sourceCount"] >= 10
    assert indexes["source:ai-search-team:global_official"]["agentIds"] == [team["members"][1]["agentId"]]
    assert indexes["source:ai-search-team:global_official"]["count"] == 1
    assert indexes["source:ai-search-team:community_signals"]["enabledByDefault"] is False


def test_agent_config_workspace_batches_runtime_history_reads(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    calls = []

    def fake_list_agent_runs_for_agents(agent_ids, *, limit=20):
        calls.append((tuple(agent_ids), limit))
        return {
            "agentIds": list(agent_ids),
            "limit": limit,
            "agents": {
                alpha["agentId"]: {
                    "agentId": alpha["agentId"],
                    "limit": limit,
                    "runs": [
                        {
                            "runId": "turn-alpha",
                            "runKind": "agent_run",
                            "agentId": alpha["agentId"],
                            "sessionId": "session-alpha",
                            "status": "running",
                            "summary": "alpha working",
                            "updatedAt": "2026-06-06T01:00:00Z",
                        }
                    ],
                    "subAgentRuns": [],
                },
                beta["agentId"]: {
                    "agentId": beta["agentId"],
                    "limit": limit,
                    "runs": [
                        {
                            "runId": "turn-beta",
                            "runKind": "agent_run",
                            "agentId": beta["agentId"],
                            "sessionId": "session-beta",
                            "status": "failed",
                            "summary": "beta failed",
                            "updatedAt": "2026-06-06T01:01:00Z",
                        }
                    ],
                    "subAgentRuns": [],
                },
            },
        }

    monkeypatch.setattr(agent_config_workspace_service, "list_agent_runs_for_agents", fake_list_agent_runs_for_agents)

    payload = agent_config_workspace_service.get_agent_config_workspace()
    agents = {item["agentId"]: item for item in payload["agents"]}

    assert len(calls) == 1
    assert calls[0][1] == 6
    assert alpha["agentId"] in calls[0][0]
    assert beta["agentId"] in calls[0][0]
    assert agents[alpha["agentId"]]["runtimeStatus"]["state"] == "running"
    assert agents[beta["agentId"]]["runtimeStatus"]["state"] == "failed"
    assert payload["summary"]["runningAgentCount"] == 1
    assert payload["summary"]["blockedAgentCount"] == 1


def test_agent_config_workspace_uses_graph_team_references_without_room_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team_service.create_team(name="Graph Reference Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_compact",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("agent config should not hydrate linked room compact")),
    )

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert payload["summary"]["teamCount"] == 1
    assert payload["teams"][0]["teamId"]
    assert "linkedChatRoom" not in payload["teams"][0]
    assert any(item["kind"] == "team" and item["sourceLabel"] == "Graph Reference Team" for item in payload["references"][agent["agentId"]])


def test_agent_config_workspace_repairs_archived_team_chat_room_residue(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Archived Residue Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    room_id = team["linkedChatRoomId"]
    teams_path = tmp_path / "workspace" / "teams" / "teams.json"
    teams_payload = json.loads(teams_path.read_text(encoding="utf-8"))
    teams_payload["teams"][0]["status"] = "archived"
    teams_payload["teams"][0]["updatedAt"] = "2026-06-06T00:00:00+00:00"
    teams_path.write_text(json.dumps(teams_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    agent_directory_service.archive_agent_instance(agent["agentId"])

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert chat_room_service.get_chat_room_detail(room_id) is None
    assert not any(item["code"] == "stale_chat_room_participant" for item in payload["health"]["issues"])
    stored = json.loads(teams_path.read_text(encoding="utf-8"))
    assert stored["teams"][0]["linkedChatRoomId"] == ""


def test_agent_workspace_write_boundary_uses_tool_policy_for_shared_paths(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(display_name="领地 Agent")

    own = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / agent["workspaceTerritory"]["artifactsRoot"] / "result.txt",
        purpose="test_private",
    )
    shared = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / "workspace" / "shared" / "notes" / "public.md",
        purpose="test_shared",
    )
    external = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / "workspace" / "agents" / "other-agent" / "memory" / "memo.json",
        purpose="test_external",
    )

    assert own.allowed is True
    assert own.scope == "private"
    assert shared.allowed is False
    assert shared.reason == "shared_write_requires_policy"
    assert external.allowed is False
    assert external.reason == "outside_agent_territory"
    assert any(
        event[0][:3] == ("agent_directory", "territory", "agent_territory.write_blocked")
        and event[1]["fields"]["reason"] == "shared_write_requires_policy"
        for event in recorded_events
    )

    updated = agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={
            "writeScopes": ["shared", "shared", "external"],
            "readScopes": ["private", "shared", "outside"],
        },
    )
    shared_allowed = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / "workspace" / "shared" / "notes" / "public.md",
        purpose="test_shared_allowed",
    )
    external_after_policy = agent_directory_service.evaluate_agent_workspace_write(
        agent["agentId"],
        tmp_path / "workspace" / "agents" / "other-agent" / "memory" / "memo.json",
        purpose="test_external_after_policy",
    )

    assert updated["toolPolicy"]["writeScopes"] == ["shared"]
    assert updated["toolPolicy"]["readScopes"] == ["private", "shared"]
    assert shared_allowed.allowed is True
    assert shared_allowed.scope == "shared"
    assert external_after_policy.allowed is False
    assert external_after_policy.reason == "outside_agent_territory"


def test_repair_agent_directory_keeps_generated_person_name_stable(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="科研 Agent", primary_mode="research")
    registry_path = agent_directory_service.registry_path()
    first_name = agent_directory_service.get_agent(agent["agentId"])["displayName"]
    first_mtime = registry_path.stat().st_mtime_ns

    agent_directory_service.repair_agent_directory()
    second_name = agent_directory_service.get_agent(agent["agentId"])["displayName"]
    second_mtime = registry_path.stat().st_mtime_ns
    agent_directory_service.repair_agent_directory()
    third_name = agent_directory_service.get_agent(agent["agentId"])["displayName"]
    third_mtime = registry_path.stat().st_mtime_ns

    assert second_name == first_name
    assert third_name == first_name
    assert third_mtime == second_mtime == first_mtime


def test_update_agent_instance_keeps_generated_person_name_when_functional_title_syncs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="科研 Agent", primary_mode="research")
    first_name = agent["displayName"]

    updated = agent_directory_service.update_agent_instance(
        agent["agentId"],
        display_name="科研 Agent",
        primary_mode="research",
        role_key="research_broad",
        preserve_generated_display_name=True,
    )

    assert updated["displayName"] == first_name
    assert updated["metadata"]["functionalDisplayName"] == "科研 Agent"
    assert updated["metadata"]["displayNameSource"] == "generated_person_name"


def test_repair_agent_directory_migrates_legacy_functional_user_display_name(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="自进化执行 Agent",
        primary_mode="self_evolution",
        role_key="executor",
        metadata={
            "agentMode": "self_evolution",
            "selfEvolutionRole": "executor",
            "selfEvolutionRoleLabel": "自进化执行 Agent",
        },
    )
    agent_directory_service.update_agent_instance(agent["agentId"], display_name="自进化执行 Agent")

    repaired = agent_directory_service.get_agent(agent["agentId"])

    assert repaired["displayName"] != "自进化执行 Agent"
    assert repaired["metadata"]["functionalDisplayName"] == "自进化执行 Agent"
    assert repaired["metadata"]["displayNameSource"] == "generated_person_name"


def test_repair_agent_directory_fills_fixed_role_profiles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="自进化执行 Agent",
        primary_mode="self_evolution",
        role_key="executor",
        llm_bindings={"dialogue": {"modelId": "model-research"}},
        prompt_template_id="prompt-self-executor",
        metadata={
            "agentMode": "self_evolution",
            "fixedRole": True,
            "selfEvolutionRole": "executor",
            "selfEvolutionRoleLabel": "自进化执行 Agent",
        },
    )

    agent_directory_service.repair_agent_directory()
    repaired = agent_directory_service.get_agent(agent["agentId"])
    workspace = agent_config_workspace_service.get_agent_config_workspace(use_cache=False, include_runtime=False)
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])

    assert "自进化流程" in repaired["personaProfile"]["background"]
    assert "executor" in repaired["taskProfile"]["taskTypes"]
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in workspace_agent["health"])


def test_repair_agent_directory_fills_research_org_profiles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="CEO Agent",
        primary_mode="research",
        role_key="research_ceo",
        llm_bindings={"dialogue": {"modelId": "model-research"}},
        prompt_template_id="prompt-research-ceo",
        metadata={
            "systemRole": "ceo",
            "researchOrgRole": "ceo",
            "protected": True,
            "functionalDisplayName": "CEO Agent",
            "responsibilities": [
                "Directly communicates with the user.",
                "Turns research goals into organizational tasks.",
            ],
        },
    )
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={"allowedTools": [], "preferredTools": [], "mutationAccess": "none"},
    )

    agent_directory_service.repair_agent_directory()
    repaired = agent_directory_service.get_agent(agent["agentId"])
    workspace = agent_config_workspace_service.get_agent_config_workspace(use_cache=False, include_runtime=False)
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])

    assert "研究组织" in repaired["personaProfile"]["background"]
    assert repaired["taskProfile"]["mission"] == "把研究目标转成组织任务"
    assert "Directly communicates with the user." in repaired["taskProfile"]["responsibilities"]
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in workspace_agent["health"])


def test_repair_agent_directory_fills_research_agent_profiles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="论文阅读 Agent",
        primary_mode="chat",
        role_key="research_paper_reader",
        llm_bindings={"dialogue": {"modelId": "model-research"}},
        prompt_template_id="prompt-research-paper_reader",
        metadata={
            "functionalDisplayName": "论文阅读 Agent",
            "researchAgentKey": "paper_reader",
            "researchTemplateId": "research_broad_explorer",
        },
    )
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={
            "allowedTools": ["research_knowledge_query_tool"],
            "preferredTools": ["research_knowledge_query_tool"],
            "mutationAccess": "none",
        },
    )

    agent_directory_service.repair_agent_directory()
    repaired = agent_directory_service.get_agent(agent["agentId"])
    workspace = agent_config_workspace_service.get_agent_config_workspace(use_cache=False, include_runtime=False)
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])

    assert "研究流程" in repaired["personaProfile"]["background"]
    assert "paper_reader" in repaired["taskProfile"]["taskTypes"]
    assert repaired["toolPolicy"]["allowedTools"] == [
        "agent_message_tool",
        "research_knowledge_query_tool",
        "web_search_tool",
        "web_fetch_tool",
        "batch_web_search_tool",
        "paper_search_tool",
        "search_summarize_sources_tool",
    ]
    assert repaired["toolPolicy"]["mutationAccess"] == "none"
    assert repaired["toolPolicy"]["writeScopes"] == []
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in workspace_agent["health"])


def test_repair_agent_directory_keeps_real_user_display_name(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="科研 Agent", primary_mode="research")
    agent_directory_service.update_agent_instance(agent["agentId"], display_name="张三")

    repaired = agent_directory_service.get_agent(agent["agentId"])

    assert repaired["displayName"] == "张三"
    assert repaired["metadata"]["displayNameSource"] == "user"
