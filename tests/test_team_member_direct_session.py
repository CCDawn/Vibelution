from core.web.services import (
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


def test_create_team_ensures_missing_member_direct_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="No Session")
    assert not str(agent.get("directSessionId") or "").strip()

    team = team_service.create_team(
        name="Ensure Session Team",
        members=[{"agentId": agent["agentId"], "role": "lead", "purpose": "协调"}],
    )
    refreshed = agent_directory_service.get_agent(agent["agentId"], include_archived=False)
    session_id = str((refreshed or {}).get("directSessionId") or "").strip()
    assert session_id
    detail = session_service.get_session_detail(session_id, message_limit=0, transcript_scope="none")
    assert detail
    assert str(detail.get("conversationIndexKind") or "") == agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    assert str((refreshed or {}).get("conversationIndexKind") or "") == agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    room = chat_room_service.get_chat_room_detail(team["linkedChatRoomId"])
    participant_sessions = {
        str(item.get("sessionId") or item.get("directSessionId") or "").strip()
        for item in list(room.get("participants") or [])
        if isinstance(item, dict)
    }
    assert session_id in participant_sessions


def test_update_team_keeps_existing_direct_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Has Session",
        direct_session_id="session-keep",
    )
    team = team_service.create_team(name="Keep Session Team")
    updated = team_service.update_team(
        team["teamId"],
        members=[{"agentId": agent["agentId"], "role": "reviewer"}],
    )
    refreshed = agent_directory_service.get_agent(agent["agentId"], include_archived=False)
    assert str((refreshed or {}).get("directSessionId") or "").strip() == "session-keep"
    assert updated["members"][0]["agentId"] == agent["agentId"]


def test_ensure_failure_is_observable_and_does_not_steal_session(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    events: list[str] = []
    monkeypatch.setattr(
        team_service,
        "_record_team_event",
        lambda event_code, team, fields=None: events.append(event_code),
    )
    monkeypatch.setattr(
        session_service,
        "ensure_agent_direct_session",
        lambda **kwargs: (_ for _ in ()).throw(session_service.SessionValidationError("archived")),
    )
    agent = agent_directory_service.create_agent_instance(display_name="Broken")
    team = team_service.create_team(
        name="Failed Ensure Team",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )
    refreshed = agent_directory_service.get_agent(agent["agentId"], include_archived=False)
    assert not str((refreshed or {}).get("directSessionId") or "").strip()
    assert "team.member.direct_session.failed" in events
    assert team["teamId"]


def test_runtime_context_includes_same_team_roster_only(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta")
    outsider = agent_directory_service.create_agent_instance(display_name="Outsider")
    team_service.create_team(
        name="Roster Team",
        members=[
            {"agentId": alpha["agentId"], "role": "lead", "purpose": "带队", "responsibilities": ["分工"]},
            {"agentId": beta["agentId"], "role": "reviewer", "purpose": "审查"},
        ],
    )
    team_service.create_team(name="Other Team", members=[{"agentId": outsider["agentId"], "role": "lead"}])

    block = agent_directory_service.build_agent_runtime_context_block(alpha["agentId"])
    beta_refreshed = agent_directory_service.get_agent(beta["agentId"], include_archived=False)
    outsider_refreshed = agent_directory_service.get_agent(outsider["agentId"], include_archived=False)
    assert "TeamRoster:" in block
    assert "Roster Team" in block
    assert beta["agentId"] in block
    assert str((beta_refreshed or {}).get("directSessionId") or "") in block
    assert outsider["agentId"] not in block
    assert "Other Team" not in block
    assert str((outsider_refreshed or {}).get("directSessionId") or "") not in block


def test_runtime_context_without_team_is_none(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Solo")
    block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])
    assert "TeamRoster: none" in block
