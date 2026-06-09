from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_bulk_delete_service,
    agent_bulk_edit_service,
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    session_service,
    team_service,
)


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_delete_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_bulk_edit_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)


def test_agent_bulk_prompt_template_updates_active_agents_and_skips_archived(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Bulk Prompt Alpha", prompt_template_id="prompt-chat-default")
    beta = agent_directory_service.create_agent_instance(display_name="Bulk Prompt Beta", prompt_template_id="prompt-chat-default")
    archived = agent_directory_service.create_agent_instance(display_name="Bulk Prompt Archived", prompt_template_id="prompt-chat-default")
    agent_directory_service.archive_agent_instance(archived["agentId"])
    events = []
    monkeypatch.setattr(
        agent_bulk_edit_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post(
        "/api/agents/bulk-prompt-template",
        json={
            "agentIds": [alpha["agentId"], beta["agentId"], alpha["agentId"], archived["agentId"], "missing-agent"],
            "promptTemplateId": "prompt-research-broad",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["requestedAgentIds"] == [alpha["agentId"], beta["agentId"], archived["agentId"], "missing-agent"]
    assert payload["summary"] == {
        "requestedCount": 4,
        "successCount": 2,
        "skippedCount": 2,
        "failedCount": 0,
    }
    assert [item["agentId"] for item in payload["success"]] == [alpha["agentId"], beta["agentId"]]
    assert payload["skipped"] == [
        {"agentId": archived["agentId"], "reason": "archived", "message": "Archived Agent cannot be updated."},
        {"agentId": "missing-agent", "reason": "not_found", "message": "Agent not found: missing-agent"},
    ]
    assert agent_directory_service.get_agent(alpha["agentId"])["promptTemplateId"] == "prompt-research-broad"
    assert agent_directory_service.get_agent(beta["agentId"])["promptTemplateId"] == "prompt-research-broad"
    assert agent_directory_service.get_agent(archived["agentId"], include_archived=True)["promptTemplateId"] == "prompt-chat-default"
    assert events[-1][0][:3] == ("agent_directory", "bulk_edit", "agent.bulk_prompt_template.updated")
    assert events[-1][1]["fields"]["successCount"] == 2
    assert events[-1][1]["fields"]["skippedCount"] == 2


def test_agent_bulk_prompt_template_rejects_empty_template_id(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Bulk Prompt Invalid")

    response = client.post(
        "/api/agents/bulk-prompt-template",
        json={"agentIds": [agent["agentId"]], "promptTemplateId": ""},
    )

    assert response.status_code == 422, response.text
    assert "Prompt template id is required" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"])["promptTemplateId"] == agent["promptTemplateId"]
