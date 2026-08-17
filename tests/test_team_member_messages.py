import json

from core.web.routes.teams import TeamMemberMessageListResponse
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


def test_member_message_index_stores_summary_not_body(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha")
    team = team_service.create_team(name="Index Team", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    body = "full collaboration body that must not be indexed twice"
    entry = team_service.record_team_member_message(
        team["teamId"],
        message_id="msg-1",
        source_agent_id="agent-source",
        source_agent_name="Source",
        target_agent_id=alpha["agentId"],
        target_agent_name="Alpha",
        target_session_id="session-target",
        summary="short preview",
    )
    assert "content" not in entry
    assert entry["summary"] == "short preview"
    listed = team_service.list_team_member_messages(team["teamId"])
    assert listed["messages"][0]["messageId"] == "msg-1"
    assert listed["messages"][0]["targetSessionId"] == "session-target"
    assert "content" not in listed["messages"][0]
    assert body not in json.dumps(listed)
    assert TeamMemberMessageListResponse.model_validate(listed).model_dump() == listed


def test_list_member_messages_reads_recent_window(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha")
    team = team_service.create_team(name="Window Team", members=[{"agentId": alpha["agentId"], "role": "lead"}])
    for index in range(60):
        team_service.record_team_member_message(
            team["teamId"],
            message_id=f"msg-{index}",
            source_agent_id="agent-source",
            source_agent_name="Source",
            target_agent_id=alpha["agentId"],
            target_agent_name="Alpha",
            target_session_id="session-target",
            summary=f"preview-{index}",
        )
    path = team_service._teams_root() / team_service._safe_token(team["teamId"], default="team", max_length=96) / "member_messages.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")
    listed = team_service.list_team_member_messages(team["teamId"], limit=5)
    assert [item["messageId"] for item in listed["messages"]] == [
        "msg-59",
        "msg-58",
        "msg-57",
        "msg-56",
        "msg-55",
    ]
    assert all("content" not in item for item in listed["messages"])
