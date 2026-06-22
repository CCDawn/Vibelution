import json
from types import SimpleNamespace

import pytest

from tests.test_agent_config_workspace_service import (
    ProviderConfig,
    _fake_config_workspace,
    _mark_config_agent_instances_present,
    _mark_session_active,
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

def test_agent_delete_api_archives_and_cleans_bindings_and_rooms(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=alpha["agentId"],
        available_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    agent_mode_binding_service.update_mode_binding(
        "research",
        pool=[alpha["agentId"], beta["agentId"]],
        flow_bindings={"broad_search": alpha["agentId"]},
    )
    room = chat_room_service.create_chat_room(
        title="待清理群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    team = team_service.create_team(
        name="待清理团队",
        members=[{"agentId": alpha["agentId"], "role": "lead"}, {"agentId": beta["agentId"], "role": "peer"}],
    )

    response = client.delete(f"/api/agents/{alpha['agentId']}")

    assert response.status_code == 200, response.text
    archived = response.json()
    assert archived["status"] == "archived"
    assert archived["archiveSummary"]["dataRetention"] == "archived_only"
    assert archived["archiveSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert archived["archiveSummary"]["removedFromTeamIds"] == [team["teamId"]]
    assert alpha["agentId"] not in {item["agentId"] for item in agent_directory_service.list_agents(include_archived=False)}
    assert agent_directory_service.get_agent(alpha["agentId"], include_archived=True)["status"] == "archived"
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == beta["agentId"]
    assert alpha["agentId"] not in bindings["chat"]["availableAgentIds"]
    assert alpha["agentId"] not in bindings["research"]["pool"]
    assert alpha["agentId"] not in bindings["research"]["flowBindings"].values()
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [beta["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [beta["agentId"]]
    assert all(node.get("agentId") != alpha["agentId"] for node in team_detail["canvas"]["nodes"])
    linked_room = chat_room_service.get_chat_room_detail(team_detail["linkedChatRoomId"])
    assert [participant["agentId"] for participant in linked_room["participants"]] == [beta["agentId"]]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    groups = {group["id"]: group for group in workspace["groups"]}
    assert alpha["agentId"] in groups["archived"]["agentIds"]
    assert alpha["agentId"] not in groups["active"]["agentIds"]
    assert alpha["agentId"] not in groups["chat"]["agentIds"]
    assert alpha["agentId"] not in groups["research"]["agentIds"]
    assert alpha["agentId"] not in groups["group_chat"]["agentIds"]


def test_agent_config_workspace_does_not_report_historical_mode_repair_warnings(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = session_service.create_chat_session(title="归档 Agent")
    state = agent_mode_binding_service.default_mode_binding_state()
    state["modes"]["chat"]["defaultAgentId"] = agent["agentId"]
    state["modes"]["chat"]["availableAgentIds"] = [agent["agentId"]]
    agent_mode_binding_service.save_mode_binding_state(state)
    agent_directory_service.archive_agent_instance(agent["agentId"])

    payload = agent_config_workspace_service.get_agent_config_workspace()

    assert agent["agentId"] not in payload["modeBindings"]["chat"]["availableAgentIds"]
    assert not any(
        item["code"] == "stale_mode_binding" and item["agentId"] == agent["agentId"]
        for item in payload["health"]["issues"]
    )


def test_agent_delete_api_blocks_supervised_fixed_role_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    baseline = _seed_supervised_fixed_role_agent("baseline")

    response = client.delete(f"/api/agents/{baseline['agentId']}")
    assert response.status_code == 422, response.text
    assert "Protected core Agent" in response.json()["detail"]

    workspace_response = client.get("/api/agents/config-workspace")
    assert workspace_response.status_code == 200, workspace_response.text
    active = agent_directory_service.get_agent(baseline["agentId"], include_archived=True)
    assert active["status"] == "active"
    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["baseline"] == baseline["agentId"]
    assert "baseline" not in payload["excludedSlots"]
    assert baseline["agentId"] in payload["availableAgentIds"]
    workspace = workspace_response.json()
    assert baseline["agentId"] in {item["agentId"] for item in workspace["agents"] if item["status"] == "active"}
    assert baseline["agentId"] in workspace["modeBindings"]["supervised_evolution"]["availableAgentIds"]


def test_agent_delete_api_blocks_core_supervised_judge(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    judge = _seed_supervised_fixed_role_agent("judge")

    response = client.delete(f"/api/agents/{judge['agentId']}")

    assert response.status_code == 422
    assert "Protected core Agent" in response.json()["detail"]
    active = agent_directory_service.get_agent(judge["agentId"], include_archived=False)
    assert active["metadata"]["protected"] is True
    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["judge"] == judge["agentId"]


def test_agent_patch_status_archived_uses_safe_archive_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    reviewer_session = session_service.create_chat_session(title="PATCH 归档 Agent")
    reviewer = agent_directory_service.get_agent(reviewer_session["agentId"])
    peer = session_service.create_chat_session(title="Peer Agent")
    room = chat_room_service.create_chat_room(
        title="PATCH 归档群聊",
        participant_agent_ids=[reviewer["agentId"], peer["agentId"]],
    )
    team = team_service.create_team(
        name="PATCH 归档团队",
        members=[{"agentId": reviewer["agentId"], "role": "reviewer"}, {"agentId": peer["agentId"], "role": "peer"}],
    )

    response = client.patch(
        f"/api/agents/{reviewer['agentId']}",
        json={"displayName": reviewer["displayName"], "status": "archived"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "archived"
    assert payload["archiveSummary"]["source"] == "patch_status"
    assert payload["archiveSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert payload["archiveSummary"]["removedFromTeamIds"] == [team["teamId"]]
    archived = agent_directory_service.get_agent(reviewer["agentId"], include_archived=True)
    assert archived["status"] == "archived"
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["chat"]
    assert reviewer["agentId"] not in bindings["availableAgentIds"]
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [peer["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [peer["agentId"]]


def test_agent_purge_api_blocks_supervised_fixed_role_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    auditor = _seed_supervised_fixed_role_agent("auditor")

    archive_response = client.delete(f"/api/agents/{auditor['agentId']}")
    assert archive_response.status_code == 422, archive_response.text
    assert "Protected core Agent" in archive_response.json()["detail"]

    workspace_response = client.get("/api/agents/config-workspace")
    assert workspace_response.status_code == 200, workspace_response.text
    assert agent_directory_service.get_agent(auditor["agentId"], include_archived=True)["status"] == "active"
    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["auditor"] == auditor["agentId"]
    assert "auditor" not in payload["excludedSlots"]
    workspace = workspace_response.json()
    supervised_agents = [
        item
        for item in workspace["agents"]
        if item.get("primaryMode") == "supervised_evolution"
        and item.get("roleKey") == "auditor"
    ]
    assert [item["agentId"] for item in supervised_agents] == [auditor["agentId"]]


def test_agent_purge_api_preserves_fixed_role_tombstone_after_legacy_archive(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    reviewer = agent_directory_service.create_agent_instance(
        display_name="Legacy Archived Reviewer",
        primary_mode="supervised_evolution",
        role_key="reviewer",
    )
    agent_directory_service.archive_agent_instance(reviewer["agentId"])
    agent_directory_service.update_agent_instance(
        reviewer["agentId"],
        metadata={"fixedRole": True, "supervisedRole": "reviewer"},
    )
    _mark_config_agent_instances_present()
    repaired = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert repaired["slots"]["reviewer"] == ""

    purge_response = client.delete(f"/api/agents/{reviewer['agentId']}/purge")
    assert purge_response.status_code == 422, purge_response.text
    assert "Protected core Agent" in purge_response.json()["detail"]
    workspace_response = client.get("/api/agents/config-workspace")
    assert workspace_response.status_code == 200, workspace_response.text

    payload = agent_mode_binding_service.get_mode_bindings_payload()["modes"]["supervised_evolution"]
    assert payload["slots"]["reviewer"] == ""
    assert "reviewer" in payload["excludedSlots"]
    assert agent_directory_service.get_agent(reviewer["agentId"], include_archived=True)["status"] == "archived"
    workspace = workspace_response.json()
    assert [
        item
        for item in workspace["agents"]
        if item.get("primaryMode") == "supervised_evolution"
        and item.get("roleKey") == "reviewer"
    ]


def test_agent_delete_api_rejects_only_group_member_without_partial_archive(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Solo Agent")
    chat_room_service.create_chat_room(
        title="单成员历史群聊",
        participant_session_ids=[agent["id"]],
    )

    response = client.delete(f"/api/agents/{agent['agentId']}")

    assert response.status_code == 422
    assert "唯一成员" in response.json()["detail"] or "only member" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"])["status"] == "active"


def test_agent_delete_api_rejects_protected_agent_without_reference_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    protected = session_service.create_chat_session(title="核心 Agent")
    peer = session_service.create_chat_session(title="普通 Agent")
    _mark_session_active(tmp_path, protected["id"])
    agent_directory_service.update_agent_instance(protected["agentId"], metadata={"protected": True})
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=protected["agentId"],
        available_agent_ids=[protected["agentId"], peer["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="保护群聊",
        participant_agent_ids=[protected["agentId"], peer["agentId"]],
    )

    response = client.delete(f"/api/agents/{protected['agentId']}")

    assert response.status_code == 422
    assert "Protected core Agent" in response.json()["detail"]
    assert agent_directory_service.get_agent(protected["agentId"])["status"] == "active"
    chat_binding = _raw_mode_binding("chat")
    assert chat_binding["defaultAgentId"] == protected["agentId"]
    assert protected["agentId"] in chat_binding["availableAgentIds"]
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [protected["agentId"], peer["agentId"]]


def test_agent_delete_api_logs_stage_timings_and_skips_duplicate_mode_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=alpha["agentId"],
        available_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    events = []
    mode_cleanup_calls = []
    real_remove_agent_from_mode_bindings = agents_route.remove_agent_from_mode_bindings

    def tracked_remove_agent_from_mode_bindings(agent_id):
        mode_cleanup_calls.append(agent_id)
        return real_remove_agent_from_mode_bindings(agent_id)

    monkeypatch.setattr(agents_route, "remove_agent_from_mode_bindings", tracked_remove_agent_from_mode_bindings)
    monkeypatch.setattr(
        agents_route,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.delete(f"/api/agents/{alpha['agentId']}")

    assert response.status_code == 200, response.text
    assert mode_cleanup_calls == [alpha["agentId"]]
    completed = [event for event in events if event[0][:3] == ("agent_directory", "delete", "agent.archive.completed")]
    assert completed
    fields = completed[-1][1]["fields"]
    assert {"ensure_archive_allowed", "remove_from_teams", "remove_from_chat_rooms", "remove_from_mode_bindings", "archive_agent"}.issubset(fields["timingsMs"])
    assert fields["durationMs"] >= fields["timingsMs"]["archive_agent"]
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == beta["agentId"]


def test_agent_purge_api_deletes_archived_agent_workspace_and_registry_record(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    agent = agent_directory_service.update_agent_instance(
        alpha["agentId"],
        tool_policy={"allowedTools": ["read_file_tool"]},
        memory_policy={"readSharedGroups": ["project"]},
    )
    workspace_path = tmp_path / agent["workspacePath"]
    marker = workspace_path / "events" / "agent_inbox_messages.jsonl"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"messageId":"m1"}\n', encoding="utf-8")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=alpha["agentId"],
        available_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="待 purge 群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    team = team_service.create_team(
        name="待 purge 团队",
        members=[{"agentId": alpha["agentId"], "role": "lead"}, {"agentId": beta["agentId"], "role": "peer"}],
    )
    agent_directory_service.archive_agent_instance(alpha["agentId"])

    response = client.delete(f"/api/agents/{alpha['agentId']}/purge")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["agentId"] == alpha["agentId"]
    assert payload["status"] == "purged"
    assert payload["deleted"] is True
    assert payload["workspaceDeleted"] is True
    assert agent["workspacePath"] in payload["deletedPaths"]
    assert payload["removedToolPolicy"] is True
    assert payload["removedMemoryPolicy"] is True
    assert payload["purgeSummary"]["dataRetention"] == "purged"
    assert payload["purgeSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert payload["purgeSummary"]["removedFromTeamIds"] == [team["teamId"]]
    assert not workspace_path.exists()
    assert agent_directory_service.get_agent(alpha["agentId"], include_archived=True) is None
    state = agent_directory_service.load_state()
    assert agent["toolPolicyId"] not in state["toolPolicies"]
    assert agent["memoryPolicyId"] not in state["memoryPolicies"]
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == beta["agentId"]
    assert alpha["agentId"] not in bindings["chat"]["availableAgentIds"]
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [beta["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [beta["agentId"]]


def test_agent_bulk_purge_api_removes_many_agents_with_one_reference_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    alpha = session_service.create_chat_session(title="Bulk Alpha")
    beta = session_service.create_chat_session(title="Bulk Beta")
    gamma = session_service.create_chat_session(title="Bulk Gamma")
    active = session_service.create_chat_session(title="Bulk Active")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=alpha["agentId"],
        available_agent_ids=[alpha["agentId"], beta["agentId"], gamma["agentId"], active["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="批量删除群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"], gamma["agentId"], active["agentId"]],
    )
    team = team_service.create_team(
        name="批量删除团队",
        members=[
            {"agentId": alpha["agentId"], "role": "alpha"},
            {"agentId": beta["agentId"], "role": "beta"},
            {"agentId": active["agentId"], "role": "active"},
        ],
    )
    for item in (alpha, beta, gamma):
        agent_directory_service.archive_agent_instance(item["agentId"], repair_mode_bindings=False)

    cleanup_calls = []
    real_remove_agents_from_chat_rooms = agent_bulk_delete_service.remove_agents_from_chat_rooms

    def tracked_remove_agents_from_chat_rooms(agent_ids, *, allow_empty_rooms=False, direct_session_ids_by_agent_id=None, **kwargs):
        cleanup_calls.append(list(agent_ids))
        return real_remove_agents_from_chat_rooms(
            agent_ids,
            allow_empty_rooms=allow_empty_rooms,
            direct_session_ids_by_agent_id=direct_session_ids_by_agent_id,
            **kwargs,
        )

    monkeypatch.setattr(agent_bulk_delete_service, "remove_agents_from_chat_rooms", tracked_remove_agents_from_chat_rooms)

    response = client.post(
        "/api/agents/bulk-purge",
        json={"agentIds": [alpha["agentId"], beta["agentId"], active["agentId"], gamma["agentId"]]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["summary"]["requestedCount"] == 4
    assert payload["summary"]["successCount"] == 3
    assert payload["summary"]["skippedCount"] == 1
    assert payload["summary"]["failedCount"] == 0
    assert cleanup_calls == [[alpha["agentId"], beta["agentId"], gamma["agentId"]]]
    assert [item["agentId"] for item in payload["success"]] == [alpha["agentId"], beta["agentId"], gamma["agentId"]]
    assert payload["skipped"] == [
        {"agentId": active["agentId"], "reason": "not_archived", "message": "Only archived Agents can be permanently deleted."}
    ]
    assert payload["cleanupSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert payload["cleanupSummary"]["removedFromTeamIds"] == [team["teamId"]]
    assert payload["timingsMs"]["remove_from_chat_rooms"] >= 0
    for item in (alpha, beta, gamma):
        assert agent_directory_service.get_agent(item["agentId"], include_archived=True) is None
        detail = session_service.get_session_detail(item["id"])
        assert detail["agentStatusCode"] == "deleted_agent"
    assert agent_directory_service.get_agent(active["agentId"], include_archived=True)["status"] == "active"
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [active["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert [member["agentId"] for member in team_detail["members"]] == [active["agentId"]]
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == active["agentId"]
    assert bindings["chat"]["availableAgentIds"] == [active["agentId"]]


def test_agent_purge_api_rejects_active_agent_without_reference_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Active Agent")
    peer = session_service.create_chat_session(title="Peer Agent")
    room = chat_room_service.create_chat_room(
        title="单成员待删除群聊",
        participant_session_ids=[agent["id"], peer["id"]],
    )

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 422, response.text
    assert "Only archived Agents can be permanently deleted" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "active"
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [agent["agentId"], peer["agentId"]]
    detail = session_service.get_session_detail(agent["id"])
    assert detail["agentId"] == agent["agentId"]
    assert not detail["agentMissing"]
    assert detail["agentStatusCode"] == ""


def test_agent_purge_api_rejects_protected_archived_agent_without_reference_cleanup(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    protected = session_service.create_chat_session(title="Protected Archived")
    peer = session_service.create_chat_session(title="Peer Agent")
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=protected["agentId"],
        available_agent_ids=[protected["agentId"], peer["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="保护归档群聊",
        participant_agent_ids=[protected["agentId"], peer["agentId"]],
    )
    agent_directory_service.archive_agent_instance(protected["agentId"])
    agent_directory_service.update_agent_instance(
        protected["agentId"],
        metadata={"protected": True},
    )

    response = client.delete(f"/api/agents/{protected['agentId']}/purge")

    assert response.status_code == 422
    assert "Protected core Agent" in response.json()["detail"]
    assert agent_directory_service.get_agent(protected["agentId"], include_archived=True)["status"] == "archived"
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [protected["agentId"], peer["agentId"]]


def test_agent_purge_api_allows_archived_agent_that_was_only_room_member(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Solo Archived Agent")
    room = chat_room_service.create_chat_room(
        title="单成员历史群聊",
        participant_session_ids=[agent["id"]],
    )
    agent_directory_service.archive_agent_instance(agent["agentId"])

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["purgeSummary"]["removedFromRoomIds"] == [room["roomId"]]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True) is None
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert room_detail["participants"] == []


def test_agent_purge_api_reports_workspace_delete_failure_without_server_error(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Locked Workspace Agent")
    peer = session_service.create_chat_session(title="Peer Agent")
    room = chat_room_service.create_chat_room(
        title="锁定工作区群聊",
        participant_session_ids=[agent["id"], peer["id"]],
    )
    team = team_service.create_team(
        name="锁定工作区团队",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=agent["agentId"],
        available_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    workspace_path = tmp_path / agent["workspacePath"]
    workspace_path.mkdir(parents=True, exist_ok=True)
    agent_directory_service.archive_agent_instance(agent["agentId"], repair_mode_bindings=False)

    def _fail_rmtree(path):
        raise PermissionError("locked")

    monkeypatch.setattr(agent_directory_service.shutil, "rmtree", _fail_rmtree)

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 422, response.text
    assert "PermissionError" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"
    detail = session_service.get_session_detail(agent["id"])
    assert detail["agentId"] == agent["agentId"]
    assert detail["agentStatusCode"] == "archived_agent"
    assert workspace_path.exists()
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert [participant["agentId"] for participant in room_detail["participants"]] == [peer["agentId"]]
    team_detail = team_service.get_team(team["teamId"])
    assert team_detail["members"] == []
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == peer["agentId"]
    assert agent["agentId"] not in bindings["chat"]["availableAgentIds"]
    assert bindings["chat"]["availableAgentIds"] == [peer["agentId"]]


def test_agent_purge_api_rejects_reference_cleanup_failure_without_deleting_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = session_service.create_chat_session(title="Cleanup Failure Agent")
    agent_record = agent_directory_service.get_agent(agent["agentId"])
    workspace_path = tmp_path / agent_record["workspacePath"]
    workspace_path.mkdir(parents=True, exist_ok=True)
    agent_directory_service.archive_agent_instance(agent["agentId"])

    def _fail_room_cleanup(*args, **kwargs):
        raise chat_room_service.ChatRoomValidationError("cleanup blocked")

    monkeypatch.setattr(agents_route, "remove_agent_from_chat_rooms", _fail_room_cleanup)

    response = client.delete(f"/api/agents/{agent['agentId']}/purge")

    assert response.status_code == 422, response.text
    assert "cleanup blocked" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"
    assert workspace_path.exists()
