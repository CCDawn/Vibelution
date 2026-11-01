"""The purge SDK binds the destructive result to its requested target."""
from copy import deepcopy

import pytest

from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient, _MANAGEMENT_SCOPES


def preview():
    return {"agent": {"agentId": "agent-1", "directSessionId": "session-1", "displayName": "A",
        "configRevision": 3, "updatedAt": "v3", "modelId": "model", "avatarImagePath": ""},
        "status": "archived", "irreversible": True, "untrustedContent": True,
        "effects": ["agent", "sessions", "private_workspace", "team_room_mode_references"]}


def receipt(**changes):
    return {"status": "completed", "action": "agent_purge", "requestId": "purge-1", "verified": True,
        "reused": False, "purge": {"agentId": "agent-1", "status": "purged", "cleanupPending": False}, **changes}


@pytest.fixture
def sdk(tmp_path, monkeypatch):
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "sdk.json")
    state = {"payload": receipt(), "calls": []}
    async def grant(**_kwargs):
        return {"subjectId": "subject", "capability": "capability", "binding": {"projectId": "p", "instanceId": "i"}}
    async def request(method, path, **kwargs):
        state["calls"].append((method, path, kwargs))
        return deepcopy(state["payload"])
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    return client, state


@pytest.mark.anyio
@pytest.mark.parametrize("pending", [False, True])
async def test_purge_sdk_keeps_native_cleanup_state_and_does_not_expand_bootstrap(sdk, pending):
    client, state = sdk
    state["payload"]["purge"]["cleanupPending"] = pending
    result = await client.management_action(action="agent_purge", request_id="purge-1",
        parameters={"agent_id": "agent-1", "expected_config_revision": 3})
    assert result["purge"]["cleanupPending"] is pending and "agent" not in result
    assert "agents:purge" not in _MANAGEMENT_SCOPES
    assert state["calls"][0][2]["json_payload"]["parameters"]["agent_id"] == "agent-1"


@pytest.mark.anyio
@pytest.mark.parametrize("changes", [{"force": True}, {"expected_config_revision": True},
    {"expected_config_revision": -1}, {"expected_config_revision": "3"}])
async def test_purge_sdk_rejects_open_or_coerced_parameters_before_request(sdk, changes):
    client, state = sdk
    with pytest.raises(BackendClientError) as failure:
        await client.management_action(action="agent_purge", request_id="purge-1",
            parameters={"agent_id": "agent-1", "expected_config_revision": 3, **changes})
    assert failure.value.code == "INVALID_MANAGEMENT_REQUEST" and not state["calls"]


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["target", "extra", "agent", "unknown_result", "bool", "action", "request"])
async def test_purge_sdk_rejects_unbound_or_malformed_receipt(sdk, fault):
    client, state = sdk
    payload = state["payload"]
    if fault == "target": payload["purge"]["agentId"] = "another-agent"
    elif fault == "extra": payload["purge"]["privatePath"] = "private"
    elif fault == "agent": payload["agent"] = preview()["agent"]
    elif fault == "unknown_result": payload.update(status="unknown", verified=False, code="OPERATION_UNCONFIRMED")
    elif fault == "bool": payload["purge"]["cleanupPending"] = 0
    elif fault == "action": payload["action"] = "agent_archive"
    elif fault == "request": payload["requestId"] = "foreign-request"
    with pytest.raises(BackendClientError) as failure:
        await client.management_action(action="agent_purge", request_id="purge-1",
            parameters={"agent_id": "agent-1", "expected_config_revision": 3})
    assert failure.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.anyio
async def test_preview_is_closed_read_only_and_bound_to_archived_agent(sdk):
    client, state = sdk
    state["payload"] = preview()
    assert await client.management_agent_purge_preview(agent_id="agent-1") == preview()
    assert state["calls"][0][0] == "GET" and state["calls"][0][1].endswith("/agents/agent-1/purge-preview")
    for invalid in ({**preview(), "status": "active"}, {**preview(), "privatePath": "private"},
                    {**preview(), "irreversible": False}, {**preview(), "effects": ["agent"]}):
        state["payload"] = invalid
        with pytest.raises(BackendClientError) as failure:
            await client.management_agent_purge_preview(agent_id="agent-1")
        assert failure.value.code == "BACKEND_PROTOCOL_ERROR"


def test_purge_unknown_receipt_never_claims_a_deleted_agent():
    raw = {"status": "unknown", "action": "agent_purge", "requestId": "purge-1", "verified": False,
        "reused": True, "code": "OPERATION_UNCONFIRMED"}
    assert ManagedAgentBackendClient._management_public_receipt(raw, action="agent_purge", request_id="purge-1") == raw
