from __future__ import annotations

import json

from fastapi.testclient import TestClient

from core.agent_kernel import service as agent_kernel_service
from core.infrastructure import developer_sandbox
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _isolate_kernel(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    data_home = tmp_path / "operator-data"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    return project_root, data_home


def _create_agent(display_name: str = "Kernel Alpha") -> dict:
    return agent_directory_service.create_agent_instance(display_name=display_name, direct_session_id="session-alpha")


def _kernel_event(agent_id: str, *, idempotency_key: str = "kernel-idempotency-1", content: str = "hello") -> dict:
    return {
        "eventId": f"event-{idempotency_key}",
        "sender": {"type": "user", "id": "user"},
        "recipientAgentIds": [agent_id],
        "semanticType": "agent.message",
        "payload": {"content": content, "goal": content},
        "idempotencyKey": idempotency_key,
    }


def test_kernel_event_creates_task_execution_outcome_and_inbox_message(tmp_path, monkeypatch):
    _project_root, data_home = _isolate_kernel(tmp_path, monkeypatch)
    agent = _create_agent()

    response = _client().post("/api/kernel/events", json=_kernel_event(agent["agentId"]))

    assert response.status_code == 202
    payload = response.json()
    assert payload["reused"] is False
    assert payload["event"]["status"] == "accepted"
    assert payload["task"]["status"] == "succeeded"
    assert payload["task"]["assignedAgentIds"] == [agent["agentId"]]
    assert payload["execution"]["status"] == "succeeded"
    assert payload["outcome"]["status"] == "succeeded"
    assert payload["outcome"]["deliveries"][0]["status"] == "delivered"

    inbox_response = _client().get(f"/api/agents/{agent['agentId']}/inbox")
    assert inbox_response.status_code == 200
    inbox = inbox_response.json()
    assert inbox["pendingCount"] == 1
    assert inbox["messages"][0]["metadata"]["kernelTaskId"] == payload["task"]["taskId"]

    kernel_root = data_home / "workspace" / "agent_kernel"
    assert (kernel_root / "events.jsonl").exists()
    assert (kernel_root / "tasks.jsonl").exists()
    assert (kernel_root / "executions.jsonl").exists()
    assert (kernel_root / "outcomes.jsonl").exists()
    assert (kernel_root / "index.json").exists()


def test_kernel_event_idempotency_reuses_existing_terminal_task(tmp_path, monkeypatch):
    _isolate_kernel(tmp_path, monkeypatch)
    agent = _create_agent()
    client = _client()

    first = client.post("/api/kernel/events", json=_kernel_event(agent["agentId"], idempotency_key="same-key"))
    second = client.post("/api/kernel/events", json=_kernel_event(agent["agentId"], idempotency_key="same-key"))

    assert first.status_code == 202
    assert second.status_code == 202
    first_payload = first.json()
    second_payload = second.json()
    assert second_payload["reused"] is True
    assert second_payload["task"]["taskId"] == first_payload["task"]["taskId"]
    assert second_payload["task"]["status"] == "succeeded"

    tasks = client.get("/api/kernel/tasks").json()["tasks"]
    assert [task["taskId"] for task in tasks] == [first_payload["task"]["taskId"]]


def test_kernel_event_rejects_missing_recipient_but_keeps_audit_event(tmp_path, monkeypatch):
    _isolate_kernel(tmp_path, monkeypatch)
    client = _client()

    response = client.post(
        "/api/kernel/events",
        json={
            "eventId": "event-missing-recipient",
            "semanticType": "agent.message",
            "payload": {"content": "no target"},
            "idempotencyKey": "missing-recipient",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["event"]["status"] == "rejected"
    assert detail["event"]["failureReason"] == "missing_recipient"

    audit_response = client.get("/api/kernel/events/event-missing-recipient")
    assert audit_response.status_code == 200
    assert audit_response.json()["status"] == "rejected"


def test_kernel_inbox_ack_consumes_message_without_deleting_projection(tmp_path, monkeypatch):
    _isolate_kernel(tmp_path, monkeypatch)
    agent = _create_agent()
    client = _client()
    created = client.post("/api/kernel/events", json=_kernel_event(agent["agentId"], idempotency_key="ack-key")).json()
    message_id = created["outcome"]["deliveries"][0]["inboxMessageId"]

    ack_response = client.post(
        f"/api/agents/{agent['agentId']}/inbox/{message_id}/ack",
        json={"consumedBySessionId": "session-alpha", "consumedByTurnId": "turn-1"},
    )

    assert ack_response.status_code == 200
    acked = ack_response.json()
    assert acked["acked"] is True
    assert acked["message"]["status"] == "consumed"
    assert acked["message"]["consumedByTurnId"] == "turn-1"
    assert client.get(f"/api/agents/{agent['agentId']}/inbox").json()["pendingCount"] == 0
    consumed = client.get(f"/api/agents/{agent['agentId']}/inbox", params={"status": "consumed"}).json()
    assert consumed["messages"][0]["messageId"] == message_id


def test_kernel_proposal_stub_is_non_blocking_side_workflow(tmp_path, monkeypatch):
    _isolate_kernel(tmp_path, monkeypatch)
    agent = _create_agent()

    response = _client().post(
        "/api/kernel/events",
        json={
            **_kernel_event(agent["agentId"], idempotency_key="proposal-key"),
            "payload": {
                "content": "prepare proposal",
                "proposalType": "tool_permission_change",
                "proposalSummary": "Grant image tool",
            },
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["task"]["status"] == "succeeded"
    assert payload["outcome"]["status"] == "succeeded"
    assert payload["proposals"][0]["status"] == "queued"
    assert payload["proposals"][0]["proposalType"] == "tool_permission_change"
    assert payload["outcome"]["proposalRefs"] == [payload["proposals"][0]["proposalId"]]


def test_kernel_state_path_routes_to_developer_sandbox(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "project"
    data_home = tmp_path / "operator-data"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", project_root)

    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    enabled = developer_sandbox.update_developer_mode_status(
        True,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )
    sandbox_id = enabled["sandbox"]["sandboxId"]

    assert agent_kernel_service._kernel_root() == (
        project_root / ".runtime" / "developer-mode" / "sandboxes" / sandbox_id / "workspace" / "agent_kernel"
    )


def test_kernel_index_materializes_taskledger_truth(tmp_path, monkeypatch):
    _project_root, data_home = _isolate_kernel(tmp_path, monkeypatch)
    agent = _create_agent()
    payload = _client().post("/api/kernel/events", json=_kernel_event(agent["agentId"], idempotency_key="index-key")).json()

    index = json.loads((data_home / "workspace" / "agent_kernel" / "index.json").read_text(encoding="utf-8"))

    task = index["tasksById"][payload["task"]["taskId"]]
    assert task["status"] == "succeeded"
    assert task["outcomeId"] == payload["outcome"]["outcomeId"]
    assert index["taskIdsByIdempotencyKey"]["index-key"] == payload["task"]["taskId"]
