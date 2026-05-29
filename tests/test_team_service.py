import pytest

from core.web.services import (
    agent_config_workspace_service,
    agent_directory_service,
    chat_room_service,
    project_agent_bus_service,
    session_service,
    team_service,
)


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def test_create_team_with_active_agent_writes_default_canvas(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")

    team = team_service.create_team(
        name="科研协作组",
        purpose="组织科研 agent",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )

    assert team["teamId"] == "team"
    assert team["members"][0]["agentId"] == agent["agentId"]
    assert team["canvas"]["canvasKind"] == team_service.CANVAS_KIND
    assert team["canvas"]["nodes"][0]["agentId"] == agent["agentId"]
    assert team["linkedChatRoomId"]
    assert team["linkedChatRoom"]["participantCount"] == 1
    assert chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])["participants"][0]["agentId"] == agent["agentId"]
    assert team_service.list_teams()["summary"]["activeTeamCount"] == 1


def test_team_canvas_save_syncs_linked_chat_room_members(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    team = team_service.create_team(name="Sync Team", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    linked_room_id = team["linkedChatRoomId"]
    canvas = team_service.get_team_canvas(team["teamId"])
    canvas["nodes"].append(
        {
            "id": "node-beta",
            "label": "Beta reviewer",
            "type": "agent",
            "status": "bound",
            "x": 420,
            "y": 120,
            "agentId": beta["agentId"],
            "agentCode": beta["agentCode"],
            "agentName": beta["displayName"],
            "role": "reviewer",
            "purpose": "检查输出",
        }
    )

    updated_canvas = team_service.save_team_canvas(team["teamId"], canvas)
    updated_team = team_service.get_team(team["teamId"])
    linked_room = chat_room_service.get_chat_room_detail(updated_team["linkedChatRoomId"])

    assert updated_canvas["validation"]["valid"] is True
    assert updated_team["linkedChatRoomId"] == linked_room_id
    assert [member["agentId"] for member in updated_team["members"]] == [alpha["agentId"], beta["agentId"]]
    assert [participant["agentId"] for participant in linked_room["participants"]] == [alpha["agentId"], beta["agentId"]]


def test_team_rejects_archived_member_at_create(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Archived", direct_session_id="session-archived")
    agent_directory_service.archive_agent_instance(agent["agentId"])

    with pytest.raises(team_service.TeamServiceError, match="not active"):
        team_service.create_team(name="失效团队", members=[{"agentId": agent["agentId"]}])


def test_team_canvas_validation_flags_stale_agent_ref(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Canvas Team", members=[{"agentId": agent["agentId"]}])

    agent_directory_service.archive_agent_instance(agent["agentId"])
    canvas = team_service.get_team_canvas(team["teamId"])

    assert canvas["validation"]["valid"] is True
    assert canvas["nodes"][0]["status"] == "stale"
    assert canvas["validation"]["issues"][0]["code"] == "stale_agent_ref"


def test_save_team_canvas_rejects_missing_edge_endpoint(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Edge Team")
    canvas = team_service.get_team_canvas(team["teamId"])

    canvas["edges"] = [{"id": "bad", "source": "team-lead", "target": "missing"}]

    with pytest.raises(team_service.TeamServiceError, match="existing nodes"):
        team_service.save_team_canvas(team["teamId"], canvas)


def test_agent_config_workspace_includes_team_reference(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_config_workspace_service, "_safe_prompt_workspace", lambda: {"templates": []})
    monkeypatch.setattr(agent_config_workspace_service, "_safe_config_workspace", lambda: {"profileCards": []})
    monkeypatch.setattr(agent_config_workspace_service, "_safe_chat_rooms", lambda: [])
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team_service.create_team(name="Reference Team", members=[{"agentId": agent["agentId"], "role": "owner"}])

    workspace = agent_config_workspace_service.get_agent_config_workspace()

    enriched = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert any(item["kind"] == "team" and item["route"] == "/agents/teams" for item in enriched["references"])
    assert workspace["summary"]["teamCount"] == 1


def test_send_team_message_targets_active_team_members_only(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    outsider = agent_directory_service.create_agent_instance(display_name="Outsider", direct_session_id="session-outsider")
    team = team_service.create_team(
        name="Broadcast Team",
        members=[{"agentId": alpha["agentId"]}, {"agentId": beta["agentId"]}],
    )
    agent_directory_service.archive_agent_instance(beta["agentId"])
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "wake_agent_for_inbox_message",
        lambda message: {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-team",
            "reason": "",
        },
    )

    event = team_service.send_team_message(team["teamId"], content="团队成员同步一下")

    assert event["targetScope"] == "agents"
    assert event["targetAgentIds"] == [alpha["agentId"]]
    assert event["metadata"]["teamId"] == team["teamId"]
    assert agent_directory_service.count_agent_inbox_messages_for_agent(alpha["agentId"]) == 1
    assert agent_directory_service.count_agent_inbox_messages_for_agent(beta["agentId"]) == 0
    assert agent_directory_service.count_agent_inbox_messages_for_agent(outsider["agentId"]) == 0


def test_team_message_is_visible_in_project_bus_timeline_by_team_metadata(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Timeline Team", members=[{"agentId": alpha["agentId"]}])
    monkeypatch.setattr(project_agent_bus_service.session_service, "wake_agent_for_inbox_message", lambda message: {})

    event = team_service.send_team_message(team["teamId"], content="记录到团队广播历史")
    timeline = project_agent_bus_service.list_project_agent_bus_events()

    team_events = [
        item
        for item in timeline["events"]
        if item.get("metadata", {}).get("teamId") == team["teamId"]
    ]
    assert team_events[-1]["eventId"] == event["eventId"]
    assert team_events[-1]["metadata"]["source"] == "team"
    assert team_events[-1]["targetAgentIds"] == [alpha["agentId"]]


def test_send_team_message_requires_active_members(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Empty Team")

    with pytest.raises(team_service.TeamServiceError, match="no active Agent members"):
        team_service.send_team_message(team["teamId"], content="没人会收到")
