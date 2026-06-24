from __future__ import annotations

import json

from fastapi.testclient import TestClient

import core.agent_kernel.adapters as agent_kernel_adapters
from core.agent_kernel import ADAPTER_VERSION, build_agent_message_event, service as agent_kernel_service
from core.infrastructure import developer_sandbox
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, session_service


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _isolate_kernel(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    data_home = tmp_path / "operator-data"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    return project_root, data_home


def _create_agent(display_name: str = "Kernel Adapter Alpha", *, direct_session_id: str = "session-alpha") -> dict:
    return agent_directory_service.create_agent_instance(display_name=display_name, direct_session_id=direct_session_id)


def _adapter_payload(agent_id: str, *, source_id: str = "message-1", wake_target: bool = False) -> dict:
    return {
        "source": "manual_api",
        "sender": {"type": "user", "id": "operator"},
        "recipientAgentIds": [agent_id],
        "content": "please inspect this message",
        "sourceId": source_id,
        "wakeTarget": wake_target,
        "metadata": {
            "sourceSessionId": "session-alpha",
            "sourceMessageId": source_id,
            "projectionRef": {"kind": "conversation_message", "id": f"projection-{source_id}"},
        },
    }


def test_build_agent_message_event_generates_stable_kernel_event() -> None:
    first = build_agent_message_event(
        source="manual_api",
        sender={"type": "user", "id": "operator"},
        recipient_agent_ids=["agent-a"],
        content="hello kernel",
        source_id="message-1",
        metadata={"sourceSessionId": "session-alpha", "sourceMessageId": "message-1"},
    )
    second = build_agent_message_event(
        source="manual_api",
        sender={"type": "user", "id": "operator"},
        recipient_agent_ids=["agent-a"],
        content="hello kernel",
        source_id="message-1",
        metadata={"sourceSessionId": "session-alpha", "sourceMessageId": "message-1"},
    )

    assert first["semanticType"] == "agent.message"
    assert first["payload"]["content"] == "hello kernel"
    assert first["recipientAgentIds"] == ["agent-a"]
    assert first["wakeTarget"] is True
    assert first["metadata"]["sourceSurface"] == "manual_api"
    assert first["metadata"]["sourceSessionId"] == "session-alpha"
    assert first["metadata"]["sourceMessageId"] == "message-1"
    assert first["metadata"]["adapterVersion"] == ADAPTER_VERSION
    assert first["idempotencyKey"] == second["idempotencyKey"]
    assert first["eventId"] == second["eventId"]


def test_submit_adapter_event_delegates_to_kernel_without_direct_projection_writes(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_handle(event: dict) -> dict:
        captured["event"] = event
        return {
            "reused": False,
            "event": event,
            "task": {"taskId": "task-fake"},
            "execution": {"workRunId": "workrun-fake"},
            "outcome": {"outcomeId": "outcome-fake", "status": "succeeded"},
            "proposals": [],
        }

    def fail_projection_write(*_args, **_kwargs):
        raise AssertionError("adapter must not write projections directly")

    monkeypatch.setattr(agent_kernel_service, "handle_kernel_event", fake_handle)
    monkeypatch.setattr(agent_directory_service, "write_agent_inbox_message", fail_projection_write)
    monkeypatch.setattr(session_service, "wake_agent_for_inbox_message", fail_projection_write)

    result = agent_kernel_adapters.submit_agent_message_event(
        source="manual_api",
        sender={"type": "user", "id": "operator"},
        recipient_agent_ids=["agent-a"],
        content="delegate only",
        source_id="message-2",
        wake_target=False,
    )

    assert captured["event"]["metadata"]["adapterVersion"] == ADAPTER_VERSION
    assert captured["event"]["wakeTarget"] is False
    assert result["adapter"]["adapterVersion"] == ADAPTER_VERSION
    assert result["task"]["taskId"] == "task-fake"


def test_agent_message_adapter_reuses_task_for_same_source_and_content(tmp_path, monkeypatch) -> None:
    _isolate_kernel(tmp_path, monkeypatch)
    agent = _create_agent()
    client = _client()
    payload = _adapter_payload(agent["agentId"], source_id="same-message")

    first = client.post("/api/kernel/adapter/agent-message", json=payload)
    second = client.post("/api/kernel/adapter/agent-message", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["reused"] is False
    assert second_payload["reused"] is True
    assert second_payload["task"]["taskId"] == first_payload["task"]["taskId"]
    assert second_payload["adapter"]["source"] == "manual_api"
    assert second_payload["adapter"]["adapterVersion"] == ADAPTER_VERSION


def test_agent_message_adapter_propagates_wake_target_false(tmp_path, monkeypatch) -> None:
    _isolate_kernel(tmp_path, monkeypatch)
    agent = _create_agent()

    response = _client().post(
        "/api/kernel/adapter/agent-message",
        json=_adapter_payload(agent["agentId"], source_id="no-wake", wake_target=False),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["event"]["deliveryPolicy"]["wakeTarget"] is False
    assert payload["outcome"]["deliveries"][0]["wake"]["wakeStatus"] == "not_requested"
    assert payload["execution"]["deliveryRefs"][0]["wakeStatus"] == "not_requested"


def test_agent_message_adapter_preserves_inbox_projection_metadata(tmp_path, monkeypatch) -> None:
    _isolate_kernel(tmp_path, monkeypatch)
    source = _create_agent("Kernel Adapter Source")
    agent = _create_agent("Kernel Adapter Target", direct_session_id="session-target")

    response = _client().post(
        "/api/kernel/adapter/agent-message",
        json={
            "source": "agent_message_tool",
            "sender": {"type": "agent", "id": source["agentId"], "agentId": source["agentId"]},
            "recipientAgentIds": [agent["agentId"]],
            "content": "please inspect this direct message",
            "sourceId": "tool-message-1",
            "wakeTarget": False,
            "metadata": {
                "sourceSessionId": "session-alpha",
                "sourceMessageId": "tool-message-1",
                "inboxKind": "agent_direct_message",
                "messageSummary": "direct review request",
                "agentToolMetadataJson": "{\"priority\":\"normal\"}",
            },
        },
    )

    assert response.status_code == 202
    payload = response.json()
    inbox = agent_directory_service.list_agent_inbox_messages_for_agent(agent["agentId"])[0]
    assert inbox["kind"] == "agent_direct_message"
    assert inbox["sourceSessionId"] == "session-alpha"
    assert inbox["summary"] == "direct review request"
    assert json.loads(inbox["metadata"]["agentToolMetadataJson"]) == {"priority": "normal"}
    assert inbox["metadata"]["kernelTaskId"] == payload["task"]["taskId"]
    assert inbox["metadata"]["kernelEventId"] == payload["event"]["eventId"]


def test_kernel_task_timeline_returns_read_model_with_delivery_and_projection_refs(tmp_path, monkeypatch) -> None:
    _isolate_kernel(tmp_path, monkeypatch)
    agent = _create_agent()
    client = _client()
    created = client.post(
        "/api/kernel/adapter/agent-message",
        json=_adapter_payload(agent["agentId"], source_id="timeline-message", wake_target=False),
    ).json()

    response = client.get(f"/api/kernel/tasks/{created['task']['taskId']}/timeline")

    assert response.status_code == 200
    timeline = response.json()
    assert timeline["taskId"] == created["task"]["taskId"]
    assert timeline["event"]["metadata"]["sourceSurface"] == "manual_api"
    assert timeline["task"]["status"] == "succeeded"
    assert timeline["execution"]["status"] == "succeeded"
    assert timeline["outcome"]["status"] == "succeeded"
    assert timeline["deliveries"][0]["wake"]["wakeStatus"] == "not_requested"
    assert timeline["readModel"]["truthSource"] == "TaskLedger"
    assert timeline["readModel"]["factAuthority"] is False
    assert timeline["readModel"]["sourceRef"]["owner"] == "TaskLedger"
    assert timeline["readModel"]["sourceRef"]["canonicalEditRoute"] == f"/kernel?taskId={created['task']['taskId']}"
    assert any(item["kind"] == "event.accepted" for item in timeline["timeline"])
    assert any(item["kind"] == "task.succeeded" for item in timeline["timeline"])
    assert any(item["kind"] == "delivery.delivered" and item["wakeStatus"] == "not_requested" for item in timeline["timeline"])
    assert any(ref["kind"] == "session" and ref["id"] == "session-alpha" for ref in timeline["projectionRefs"])
    assert any(ref["kind"] == "message" and ref["id"] == "timeline-message" for ref in timeline["projectionRefs"])
    assert any(ref["kind"] == "conversation_message" and ref["id"] == "projection-timeline-message" for ref in timeline["projectionRefs"])
    session_ref = next(ref for ref in timeline["projectionRefs"] if ref["kind"] == "session")
    message_ref = next(ref for ref in timeline["projectionRefs"] if ref["kind"] == "message")
    projection_ref = next(ref for ref in timeline["projectionRefs"] if ref["kind"] == "conversation_message")
    assert session_ref["sourceRef"]["owner"] == "ConversationLedger"
    assert session_ref["projectionCanWrite"] is False
    assert session_ref["projectionEdit"]["mode"] == "deep_link_to_source"
    assert session_ref["canonicalEditRoute"] == "/chat?session=session-alpha"
    assert message_ref["canonicalEditRoute"] == "/chat?session=session-alpha&message=timeline-message"
    assert projection_ref["canonicalEditRoute"] == "/chat?session=session-alpha&message=projection-timeline-message"
    assert timeline["runtimeEvidenceRefs"][0]["eventCode"] == "kernel.event.completed"


def test_kernel_task_timeline_returns_empty_projection_refs_when_source_has_no_projection(tmp_path, monkeypatch) -> None:
    _isolate_kernel(tmp_path, monkeypatch)
    agent = _create_agent()
    client = _client()
    created = client.post(
        "/api/kernel/adapter/agent-message",
        json={
            "source": "manual_api",
            "sender": {"type": "user", "id": "operator"},
            "recipientAgentIds": [agent["agentId"]],
            "content": "no projection refs",
            "sourceId": "source-only",
            "wakeTarget": False,
            "metadata": {},
        },
    ).json()

    timeline = client.get(f"/api/kernel/tasks/{created['task']['taskId']}/timeline").json()

    assert timeline["task"]["status"] == "succeeded"
    assert timeline["projectionRefs"] == []


def test_kernel_task_timeline_returns_404_for_missing_task(tmp_path, monkeypatch) -> None:
    _isolate_kernel(tmp_path, monkeypatch)

    response = _client().get("/api/kernel/tasks/missing-task/timeline")

    assert response.status_code == 404
