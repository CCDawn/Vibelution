from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from core.external_agent.backend_client import (
    BackendClientError,
    ManagedAgentBackendClient,
)


def _runtime_state(root: Path, *, url: str = "http://127.0.0.1:8123") -> None:
    git_dir = root / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("rev-1\n", encoding="utf-8")
    path = root / ".runtime" / "launcher" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "url": url,
                "runtimeProjectRoot": str(root.resolve()),
                "runtimeSourceCommit": "rev-1",
            }
        ),
        encoding="utf-8",
    )


def _transport(
    root: Path,
    calls: list[httpx.Request],
    *,
    get_status: str = "running",
    server_version: str = "0.3.0",
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/control-token":
            return httpx.Response(
                200,
                json={
                    "header": "X-Vibelution-Control-Token",
                    "controlToken": "control-1",
                },
            )
        if request.url.path == "/api/v1/external-agent/info":
            return httpx.Response(
                200,
                json={
                    "apiProtocolVersion": "1.0",
                    "serverVersion": server_version,
                    "projectRoot": str(root.resolve()),
                    "runtimeSourceRevision": "rev-1",
                },
            )
        if request.url.path == "/api/v1/external-agent/agents":
            return httpx.Response(200, json={"status": "ok", "agents": []})
        if request.url.path == "/api/v1/external-agent/connections/shutdown":
            return httpx.Response(200, json={"status": "ok"})
        if (
            request.method == "POST"
            and request.url.path == "/api/v1/external-agent/tasks"
        ):
            return httpx.Response(
                201,
                json={"taskId": "eat-1", "status": "running", "_leaseId": "lease-1"},
            )
        if (
            request.method == "GET"
            and request.url.path == "/api/v1/external-agent/tasks/eat-1"
        ):
            return httpx.Response(
                200,
                json={"taskId": "eat-1", "status": get_status},
            )
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(
                200,
                json={"taskId": "eat-1", "status": "running", "_leaseId": "lease-1"},
            )
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"taskId": "eat-1", "status": "cancelled"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_client_verifies_runtime_and_strips_private_fields(tmp_path) -> None:
    _runtime_state(tmp_path)
    calls: list[httpx.Request] = []
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, calls),
        adapter_connection_id="connection-1",
    )

    result = await client.start_task(
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="request-1",
        title="",
    )
    fetched = await client.get_task(task_id="eat-1")

    assert result == {"taskId": "eat-1", "status": "running"}
    assert fetched == {"taskId": "eat-1", "status": "running"}
    start = next(
        request
        for request in calls
        if request.method == "POST" and request.url.path.endswith("/tasks")
    )
    get = next(
        request
        for request in calls
        if request.method == "GET" and request.url.path.endswith("/tasks/eat-1")
    )
    capability = start.headers["X-Vibelution-External-Agent-Task-Capability"]
    assert capability
    assert get.headers["X-Vibelution-External-Agent-Task-Capability"] == capability
    assert start.headers["X-Vibelution-Control-Token"] == "control-1"
    assert "_leaseId" not in result


@pytest.mark.anyio
async def test_client_recovers_task_capability_and_lease_after_restart(
    tmp_path,
) -> None:
    _runtime_state(tmp_path)
    state_path = tmp_path / "adapter-state.json"
    calls: list[httpx.Request] = []
    first = ManagedAgentBackendClient(
        tmp_path,
        state_path=state_path,
        transport=_transport(tmp_path, calls),
        adapter_connection_id="connection-1",
    )
    await first.start_task(
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="request-1",
        title="",
    )
    second = ManagedAgentBackendClient(
        tmp_path,
        state_path=state_path,
        transport=_transport(tmp_path, calls),
        adapter_connection_id="connection-2",
    )

    await second.heartbeat_once()
    await second.get_task(task_id="eat-1")

    heartbeat = next(
        request for request in calls if request.url.path.endswith("/heartbeat")
    )
    body = json.loads(heartbeat.content)
    assert body == {"lease_id": "lease-1"}
    assert heartbeat.headers["X-Vibelution-External-Agent-Connection"] == "connection-2"


@pytest.mark.anyio
async def test_client_shutdown_cancels_nonterminal_tasks(tmp_path) -> None:
    _runtime_state(tmp_path)
    calls: list[httpx.Request] = []
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, calls),
        adapter_connection_id="connection-1",
    )
    await client.start_task(
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="request-1",
        title="",
    )

    await client.shutdown()

    assert any(request.url.path.endswith("/tasks/eat-1/cancel") for request in calls)
    assert any(request.url.path.endswith("/connections/shutdown") for request in calls)
    persisted = json.loads(
        (tmp_path / "adapter-state.json").read_text(encoding="utf-8")
    )
    assert persisted["tasks"] == {}


@pytest.mark.anyio
async def test_client_keeps_terminal_task_queryable_until_shutdown(tmp_path) -> None:
    _runtime_state(tmp_path)
    calls: list[httpx.Request] = []
    state_path = tmp_path / "adapter-state.json"
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=state_path,
        transport=_transport(tmp_path, calls, get_status="succeeded"),
        adapter_connection_id="connection-1",
    )
    await client.start_task(
        agent_id="coder",
        task="do work",
        permission_profile="read_only",
        client_request_id="request-1",
        title="",
    )

    first = await client.get_task(task_id="eat-1")
    second = await client.get_task(task_id="eat-1")

    assert first["status"] == second["status"] == "succeeded"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["tasks"]["eat-1"]["status"] == "succeeded"

    await client.shutdown()

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["tasks"] == {}
    assert not any(request.url.path.endswith("/tasks/eat-1/cancel") for request in calls)


@pytest.mark.anyio
async def test_client_rejects_non_loopback_or_mismatched_runtime(tmp_path) -> None:
    _runtime_state(tmp_path, url="http://192.168.1.10:8123")
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    with pytest.raises(BackendClientError, match="loopback") as non_loopback:
        await client.list_agents()
    assert non_loopback.value.code == "RUNTIME_IDENTITY_MISMATCH"

    _runtime_state(tmp_path)

    def mismatch(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/control-token":
            return httpx.Response(
                200,
                json={
                    "header": "X-Vibelution-Control-Token",
                    "controlToken": "control-1",
                },
            )
        return httpx.Response(
            200,
            json={
                "apiProtocolVersion": "1.0",
                "serverVersion": "0.3.0",
                "projectRoot": str((tmp_path / "other").resolve()),
                "runtimeSourceRevision": "rev-1",
            },
        )

    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=httpx.MockTransport(mismatch),
    )
    with pytest.raises(BackendClientError, match="project root") as mismatch_error:
        await client.list_agents()
    assert mismatch_error.value.code == "RUNTIME_IDENTITY_MISMATCH"


@pytest.mark.anyio
async def test_client_rejects_runtime_from_another_source_revision(tmp_path) -> None:
    _runtime_state(tmp_path)
    (tmp_path / ".git" / "HEAD").write_text("rev-2\n", encoding="utf-8")
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, []),
    )

    with pytest.raises(BackendClientError, match="source revision") as mismatch:
        await client.list_agents()

    assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"


@pytest.mark.anyio
async def test_client_rejects_runtime_from_another_server_version(tmp_path) -> None:
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=_transport(tmp_path, [], server_version="0.2.0"),
    )

    with pytest.raises(BackendClientError, match="server version") as mismatch:
        await client.list_agents()

    assert mismatch.value.code == "RUNTIME_IDENTITY_MISMATCH"


@pytest.mark.anyio
async def test_client_preserves_backend_stable_error_code(tmp_path) -> None:
    _runtime_state(tmp_path)

    def denied(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/control-token":
            return httpx.Response(
                200,
                json={
                    "header": "X-Vibelution-Control-Token",
                    "controlToken": "control-1",
                },
            )
        if request.url.path == "/api/v1/external-agent/info":
            return httpx.Response(
                200,
                json={
                    "apiProtocolVersion": "1.0",
                    "serverVersion": "0.3.0",
                    "projectRoot": str(tmp_path.resolve()),
                    "runtimeSourceRevision": "rev-1",
                },
            )
        return httpx.Response(
            404,
            json={
                "detail": {
                    "code": "AGENT_NOT_FOUND",
                    "message": "Agent is not available.",
                }
            },
        )

    client = ManagedAgentBackendClient(
        tmp_path,
        state_path=tmp_path / "adapter-state.json",
        transport=httpx.MockTransport(denied),
    )

    with pytest.raises(
        BackendClientError, match="Agent is not available"
    ) as denied_error:
        await client.list_agents()

    assert denied_error.value.code == "AGENT_NOT_FOUND"
