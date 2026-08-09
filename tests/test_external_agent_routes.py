from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import external_agent


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def list_agents(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"status": "ok", "agents": []}

    def start_task(self, **kwargs):
        self.calls.append(("start", kwargs))
        return {
            "taskId": "eat-1",
            "status": "running",
            "_leaseId": "lease-1",
        }

    def get_task(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {"taskId": kwargs["task_id"], "status": "running"}

    def resolve_approval(self, **kwargs):
        self.calls.append(("approval", kwargs))
        return {"status": "ok", "decision": kwargs["decision"]}

    def cancel_task(self, **kwargs):
        self.calls.append(("cancel", kwargs))
        return {"taskId": kwargs["task_id"], "status": "stop_unconfirmed"}

    def heartbeat(self, **kwargs):
        self.calls.append(("heartbeat", kwargs))
        return {"taskId": kwargs["task_id"], "status": "running"}

    def record_adapter_event(self, event_code, **kwargs):
        self.calls.append((event_code, kwargs))


def _client(monkeypatch) -> tuple[TestClient, FakeService]:
    service = FakeService()
    monkeypatch.setattr(external_agent, "_SERVICE", service)
    app = FastAPI()
    app.include_router(external_agent.router, prefix="/api")
    return TestClient(app), service


def _headers(
    *, capability: str = "task-cap-1", connection: str = "connection-1"
) -> dict[str, str]:
    return {
        CONTROL_TOKEN_HEADER: get_control_token(),
        external_agent.TASK_CAPABILITY_HEADER: capability,
        external_agent.ADAPTER_CONNECTION_HEADER: connection,
    }


def test_external_routes_require_control_token_even_for_reads(monkeypatch) -> None:
    client, service = _client(monkeypatch)

    assert client.get("/api/v1/external-agent/agents").status_code == 403
    assert (
        client.get(
            "/api/v1/external-agent/tasks/eat-1",
            headers={external_agent.TASK_CAPABILITY_HEADER: "task-cap-1"},
        ).status_code
        == 403
    )
    assert service.calls == []


def test_gateway_info_requires_control_token_and_reports_disabled_default(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)
    service.enabled = False

    assert client.get("/api/v1/external-agent/info").status_code == 403
    response = client.get(
        "/api/v1/external-agent/info",
        headers={CONTROL_TOKEN_HEADER: get_control_token()},
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["apiProtocolVersion"] == "1.0"
    assert response.json()["serverVersion"] == "0.3.0"


def test_adapter_connection_and_shutdown_are_auditable(monkeypatch) -> None:
    client, service = _client(monkeypatch)
    headers = {
        CONTROL_TOKEN_HEADER: get_control_token(),
        external_agent.ADAPTER_CONNECTION_HEADER: "connection-1",
    }

    assert client.get("/api/v1/external-agent/info", headers=headers).status_code == 200
    assert (
        client.post(
            "/api/v1/external-agent/connections/shutdown",
            headers=headers,
            json={},
        ).status_code
        == 200
    )

    assert service.calls == [
        (
            "external_agent.adapter.connected",
            {"adapter_connection_id": "connection-1"},
        ),
        (
            "external_agent.adapter.shutdown",
            {"adapter_connection_id": "connection-1"},
        ),
    ]


def test_start_binds_private_task_capability_and_server_capabilities(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        "/api/v1/external-agent/tasks",
        headers=_headers(),
        json={
            "agent_id": "coder",
            "task": "do work",
            "permission_profile": "read_only",
            "client_request_id": "request-1",
        },
    )

    assert response.status_code == 201
    assert response.json()["_leaseId"] == "lease-1"
    call = service.calls[0][1]
    assert call["owner_id"] == "task-cap-1"
    assert call["adapter_connection_id"] == "connection-1"
    assert call["capabilities"] == set()
    assert call["include_private"] is True


def test_task_routes_require_capability_and_never_take_owner_from_body(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    missing = client.get(
        "/api/v1/external-agent/tasks/eat-1",
        headers={CONTROL_TOKEN_HEADER: get_control_token()},
    )
    found = client.get("/api/v1/external-agent/tasks/eat-1", headers=_headers())
    approval = client.post(
        "/api/v1/external-agent/tasks/eat-1/approvals/approval-1/resolve",
        headers=_headers(),
        json={"decision": "accept", "expected_revision": "fp-1", "owner_id": "forged"},
    )
    cancelled = client.post(
        "/api/v1/external-agent/tasks/eat-1/cancel",
        headers=_headers(),
        json={},
    )

    assert missing.status_code == 403
    assert found.status_code == approval.status_code == cancelled.status_code == 200
    assert [name for name, _ in service.calls] == ["get", "approval", "cancel"]
    assert all(call["owner_id"] == "task-cap-1" for _, call in service.calls)


def test_heartbeat_keeps_lease_private_to_adapter_backend_channel(monkeypatch) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        "/api/v1/external-agent/tasks/eat-1/heartbeat",
        headers=_headers(),
        json={"lease_id": "lease-1"},
    )

    assert response.status_code == 200
    assert service.calls[0] == (
        "heartbeat",
        {
            "owner_id": "task-cap-1",
            "task_id": "eat-1",
            "lease_id": "lease-1",
            "adapter_connection_id": "connection-1",
        },
    )
