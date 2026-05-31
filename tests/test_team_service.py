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
    assert team["conversation"]["status"] == "linked"
    assert team["conversation"]["memberAgentIds"] == [agent["agentId"]]
    assert team["conversation"]["roomAgentIds"] == [agent["agentId"]]
    assert chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])["participants"][0]["agentId"] == agent["agentId"]
    assert team_service.list_teams()["summary"]["activeTeamCount"] == 1


def test_team_chat_room_participants_keep_team_role_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Alpha",
        direct_session_id="session-alpha",
        metadata={"responsibilities": ["跟踪关键决策", "提醒执行风险"]},
    )

    team = team_service.create_team(
        name="科研协作组",
        purpose="组织科研 agent",
        members=[{"agentId": agent["agentId"], "role": "research_lead", "purpose": "科研负责人"}],
    )

    participant = chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])["participants"][0]
    assert participant["teamId"] == team["teamId"]
    assert participant["teamName"] == "科研协作组"
    assert participant["teamPurpose"] == "组织科研 agent"
    assert participant["teamRole"] == "research_lead"
    assert participant["teamMemberPurpose"] == "科研负责人"
    assert participant["teamResponsibilities"] == ["跟踪关键决策", "提醒执行风险"]


def test_ensure_research_team_from_organization_uses_stable_team_id(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    organization = {
        "updatedAt": "2026-05-29T00:00:00Z",
        "agents": [
            {"nodeId": "alpha-node", "agentId": alpha["agentId"], "displayName": "Alpha", "role": "lead", "status": "active", "x": 240, "y": 160},
            {"nodeId": "beta-node", "agentId": beta["agentId"], "displayName": "Beta", "role": "reviewer", "status": "active", "x": 520, "y": 260},
        ],
        "edges": [
            {"edgeId": "edge-alpha-beta", "fromAgentId": alpha["agentId"], "toAgentId": beta["agentId"], "label": "同步证据", "status": "active"}
        ],
    }

    first = team_service.ensure_research_team_from_organization(organization)
    second = team_service.ensure_research_team_from_organization(organization)
    canvas = team_service.get_team_canvas("research-team")
    teams = team_service.list_teams()["teams"]

    assert first["teamId"] == "research-team"
    assert second["teamId"] == "research-team"
    assert [team["teamId"] for team in teams] == ["research-team"]
    assert first["linkedChatRoomId"] == second["linkedChatRoomId"]
    assert team_service.list_teams()["summary"]["activeTeamCount"] == 1
    assert len(chat_room_service.list_chat_rooms()) == 1
    assert [member["agentId"] for member in second["members"]] == [alpha["agentId"], beta["agentId"]]
    assert {node["agentId"] for node in canvas["nodes"]} == {alpha["agentId"], beta["agentId"]}
    assert {node["id"] for node in canvas["nodes"]} == {alpha["agentId"], beta["agentId"]}
    assert canvas["edges"] == [
        {
            "id": "edge-alpha-beta",
            "source": alpha["agentId"],
            "target": beta["agentId"],
            "label": "同步证据",
            "type": "communication",
        },
    ]


def test_research_team_canvas_separates_reporting_and_communication_edges(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    ceo = agent_directory_service.create_agent_instance(display_name="CEO", direct_session_id="session-ceo")
    advisor = agent_directory_service.create_agent_instance(display_name="Advisor", direct_session_id="session-advisor")
    steward = agent_directory_service.create_agent_instance(display_name="Steward", direct_session_id="session-steward")
    organization = {
        "updatedAt": "2026-05-29T00:00:00Z",
        "agents": [
            {"nodeId": "ceo", "agentId": ceo["agentId"], "displayName": "CEO", "role": "ceo", "status": "active", "x": 120, "y": 120},
            {"nodeId": "advisor", "agentId": advisor["agentId"], "displayName": "Advisor", "role": "organization_advisor", "status": "active", "x": 460, "y": 120},
            {"nodeId": "steward", "agentId": steward["agentId"], "displayName": "Steward", "role": "capability_steward", "status": "active", "x": 800, "y": 120},
        ],
        "edges": [
            {"edgeId": "edge-ceo-advisor", "fromAgentId": ceo["agentId"], "toAgentId": advisor["agentId"], "label": "CEO 下达组织调整任务", "status": "active"},
            {"edgeId": "edge-advisor-ceo", "fromAgentId": advisor["agentId"], "toAgentId": ceo["agentId"], "label": "组织顾问向 CEO 汇报", "status": "active"},
            {"edgeId": "edge-advisor-steward", "fromAgentId": advisor["agentId"], "toAgentId": steward["agentId"], "label": "组织顾问请求能力配置", "status": "active"},
        ],
    }

    team_service.ensure_research_team_from_organization(organization)

    canvas = team_service.get_team_canvas("research-team")
    reporting_edges = [edge for edge in canvas["edges"] if edge["type"] == "reports_to"]
    communication_edges = [edge for edge in canvas["edges"] if edge["type"] == "communication"]
    assert [(edge["source"], edge["target"]) for edge in reporting_edges] == [
        (ceo["agentId"], advisor["agentId"]),
        (ceo["agentId"], steward["agentId"]),
    ]
    assert {edge["id"] for edge in communication_edges} == {"edge-ceo-advisor", "edge-advisor-ceo", "edge-advisor-steward"}


def test_research_team_sync_reuses_existing_team_chat_room(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    organization = {
        "agents": [
            {"nodeId": "alpha-node", "agentId": alpha["agentId"], "displayName": "Alpha", "role": "lead", "status": "active"},
            {"nodeId": "beta-node", "agentId": beta["agentId"], "displayName": "Beta", "role": "reviewer", "status": "active"},
        ],
        "edges": [],
    }
    existing_room = chat_room_service.create_chat_room(
        title="旧科研团队群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
        config={"source": "team", "teamId": "research-team", "teamName": "科研团队"},
    )

    team = team_service.ensure_research_team_from_organization(organization)

    rooms = chat_room_service.list_chat_rooms()
    assert team["linkedChatRoomId"] == existing_room["roomId"]
    assert [room["roomId"] for room in rooms] == [existing_room["roomId"]]
    assert {participant["agentId"] for participant in rooms[0]["participants"]} == {alpha["agentId"], beta["agentId"]}


def test_ensure_evolution_system_teams_materializes_mode_roles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    result = team_service.ensure_evolution_system_teams()
    teams = {team["teamId"]: team for team in result["teams"]}

    assert set(teams) == {"self-evolution-team", "supervised-evolution-team"}
    assert teams["self-evolution-team"]["systemTeamKind"] == "self_evolution"
    assert teams["supervised-evolution-team"]["systemTeamKind"] == "supervised_evolution"
    assert teams["self-evolution-team"]["memberCount"] == 3
    assert teams["supervised-evolution-team"]["memberCount"] == 5
    assert teams["self-evolution-team"]["linkedChatRoomId"]
    assert teams["supervised-evolution-team"]["linkedChatRoomId"]
    assert len(chat_room_service.list_chat_rooms()) == 2
    assert team_service.get_team_canvas("self-evolution-team")["canvasKind"] == team_service.CANVAS_KIND
    assert team_service.get_team_canvas("supervised-evolution-team")["canvasKind"] == team_service.CANVAS_KIND


def test_compact_team_list_does_not_hydrate_linked_rooms(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team_service.create_team(name="Compact Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact list should not hydrate linked rooms")),
    )

    payload = team_service.list_teams_compact()

    assert payload["summary"]["activeTeamCount"] == 1
    assert payload["teams"][0]["linkedChatRoomId"]
    assert "linkedChatRoom" not in payload["teams"][0]
    assert "conversation" not in payload["teams"][0]


def test_team_detail_uses_compact_linked_room_without_full_chat_room_hydration(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    team = team_service.create_team(name="Fast Detail Team", members=[{"agentId": agent["agentId"], "role": "lead"}])
    monkeypatch.setattr(
        chat_room_service,
        "get_chat_room_detail",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("team detail should use compact linked room")),
    )

    detail = team_service.get_team(team["teamId"])

    assert detail["linkedChatRoomId"] == team["linkedChatRoomId"]
    assert detail["linkedChatRoom"]["participantCount"] == 1
    assert detail["conversation"]["status"] == "linked"
    assert detail["canvas"]["nodes"][0]["agentId"] == agent["agentId"]


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


def test_agent_can_only_belong_to_one_active_team(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(team_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    first = team_service.create_team(name="Alpha Team", members=[{"agentId": agent["agentId"], "role": "lead"}])

    with pytest.raises(team_service.TeamServiceError, match="already belongs to Team"):
        team_service.create_team(name="Other Team", members=[{"agentId": agent["agentId"], "role": "reviewer"}])

    conflict_events = [item for item in events if item[0][2] == "team.membership_conflict_rejected"]
    assert conflict_events[-1][1]["fields"]["agentId"] == agent["agentId"]
    assert conflict_events[-1][1]["fields"]["conflictTeamId"] == first["teamId"]
    team_service.archive_team(first["teamId"])
    second = team_service.create_team(name="Other Team", members=[{"agentId": agent["agentId"], "role": "reviewer"}])

    assert second["members"][0]["agentId"] == agent["agentId"]


def test_team_canvas_rejects_agent_bound_to_another_active_team(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    team_service.create_team(name="Alpha Team", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    beta_team = team_service.create_team(name="Beta Team", members=[{"agentId": beta["agentId"], "role": "reviewer"}])
    canvas = team_service.get_team_canvas(beta_team["teamId"])
    canvas["nodes"].append(
        {
            "id": "node-alpha",
            "label": "Alpha borrowed",
            "type": "agent",
            "x": 520,
            "y": 160,
            "agentId": alpha["agentId"],
            "role": "borrowed",
        }
    )

    with pytest.raises(team_service.TeamServiceError, match="Agent 已属于团队"):
        team_service.save_team_canvas(beta_team["teamId"], canvas)


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
    assert any(item["kind"] == "team" and item["route"] == "/teams" for item in enriched["references"])
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
