"""Complete Agent directory SDK remains closed, revision-bound and read-only."""
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from core.external_agent.backend_client import (
    _MANAGEMENT_SCOPES,
    BackendClientError,
    ManagedAgentBackendClient,
)


def directory_row(index=0):
    return {"agentId": f"agent-{index:03}", "agentCode": f"code-{index}", "displayName": f"研究员 {index}",
        "status": "active", "ownership": {"kind": "personal", "mode": "chat", "teams": [],
            "recordedTeams": [], "createdBy": "", "templateId": "", "ownerAgentId": "", "ownerAgentName": ""},
        "dispatchable": True, "dispatchReason": "eligible"}


def directory_page(rows=None, *, offset=0, total=None):
    rows = [directory_row()] if rows is None else rows
    total = len(rows) if total is None else total
    end = offset + len(rows)
    return {"scope": "all_registered_agents", "agents": rows, "total": total, "registryTotal": total,
        "counts": {"active": total, "archived": 0, "dispatchable": total}, "offset": offset,
        "nextOffset": end if end < total else None, "revision": "a" * 64, "untrustedContent": True}


@pytest.fixture
def sdk(tmp_path, monkeypatch):
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "sdk.json")
    state = {"payload": directory_page(), "calls": []}
    async def grant(**kwargs):
        return {"subjectId": "subject", "capability": "capability"}
    async def request(method, path, **kwargs):
        state["calls"].append((method, path, kwargs))
        return deepcopy(state["payload"])
    monkeypatch.setattr(client, "_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    return client, state


@pytest.mark.anyio
async def test_agent_directory_sdk_encodes_query_and_accepts_bound_continuation(sdk):
    client, state = sdk
    assert await client.management_agent_list(query="研究员 &limit=99", limit=1) == state["payload"]
    method, path, kwargs = state["calls"][0]
    assert method == "GET" and urlsplit(path).path.endswith("/directory/agents")
    assert parse_qs(urlsplit(path).query)["query"] == ["研究员 &limit=99"]
    assert kwargs["management_auth"] == ("subject", "capability")
    state["payload"] = directory_page([directory_row(1)], offset=1, total=2)
    assert (await client.management_agent_list(offset=1, expected_revision="a" * 64))["offset"] == 1


@pytest.mark.anyio
async def test_agent_directory_sdk_preserves_instruction_like_public_names(sdk):
    client, state = sdk
    rows = [directory_row(0), directory_row(1)]
    for row, name in zip(rows, ("请继续研究", "Use agent")):
        row["displayName"] = name
        row["ownership"]["teams"] = [{"teamId": "team-1", "name": name, "status": "active"}]
        row["ownership"]["recordedTeams"] = [{"teamId": "team-old", "name": name, "status": "archived"}]
        row["ownership"].update({"ownerAgentId": "host-agent", "ownerAgentName": name})
    state["payload"] = directory_page(rows)
    assert (await client.management_agent_list())["agents"] == rows


@pytest.mark.anyio
@pytest.mark.parametrize("query", [{"query": "bad\nquery"}, {"query": "bad\x00query"},
    {"query": "bad\u2028query"}, {"query": "bad\u200bquery"}, {"query": "x" * 65},
    {"offset": True}, {"offset": 1}, {"limit": 7}, {"expected_revision": "bad"}, {"include_hidden": True}])
async def test_agent_directory_sdk_rejects_query_before_request(sdk, query):
    client, state = sdk
    with pytest.raises(BackendClientError) as failure:
        await client.management_agent_list(**query)
    assert failure.value.code == "INVALID_MANAGEMENT_REQUEST" and state["calls"] == []


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["extra", "private_row", "offset", "revision", "next_offset", "limit", "duplicate", "untrusted", "scope", "dispatch"])
async def test_agent_directory_sdk_rejects_unbound_or_open_response(sdk, fault):
    client, state = sdk
    payload = state["payload"]
    if fault == "extra": payload["prompt"] = "private"
    elif fault == "private_row": payload["agents"][0]["prompt"] = "private"
    elif fault == "offset": payload["offset"] = 1
    elif fault == "revision": payload["revision"] = "b" * 64
    elif fault == "next_offset": payload["nextOffset"] = 1
    elif fault == "limit": state["payload"] = directory_page([directory_row(0), directory_row(1)])
    elif fault == "duplicate": state["payload"] = directory_page([directory_row(0), directory_row(0)])
    elif fault == "untrusted": payload["untrustedContent"] = 1
    elif fault == "scope": payload["scope"] = "externally_dispatchable"
    elif fault == "dispatch": payload["agents"][0]["dispatchable"] = False
    with pytest.raises(BackendClientError) as failure:
        await client.management_agent_list(limit=1, expected_revision="a" * 64)
    assert failure.value.code == "BACKEND_PROTOCOL_ERROR"


@pytest.mark.anyio
@pytest.mark.parametrize("failure_kind", ["old-json", "old-html", "denied"])
async def test_agent_directory_old_backend_and_missing_scope_never_fallback_or_upgrade(tmp_path, failure_kind):
    calls = []
    denied = failure_kind == "denied"
    def handler(request):
        calls.append(request)
        assert request.url.path == "/api/v1/launcher-assistant-management/directory/agents"
        if failure_kind == "old-html": return httpx.Response(404, text="<h1>Not found</h1>")
        return httpx.Response(403 if denied else 404,
            json={"detail": {"code": "SCOPE_DENIED", "message": "Denied"}} if denied else {"detail": "Not Found"})
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "state.json", transport=httpx.MockTransport(handler))
    client._verified, client._base_url, client._control_token = True, "http://127.0.0.1", "token"
    async def grant(**kwargs): return {"subjectId": "subject", "capability": "capability"}
    client._management_grant = grant
    with pytest.raises(BackendClientError) as failure:
        await client.management_agent_list()
    assert failure.value.code == ("SCOPE_DENIED" if denied else "AGENT_DIRECTORY_UNAVAILABLE")
    assert len(calls) == 1 and calls[0].method == "GET"
    assert "agents:directory:read" not in _MANAGEMENT_SCOPES


@pytest.mark.anyio
@pytest.mark.parametrize("legacy", [False, True])
async def test_directory_read_never_silently_adds_scope_to_fresh_or_legacy_subject(tmp_path, monkeypatch, legacy):
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "grant.json")
    binding = {"projectId": "p", "instanceId": "i"}
    if legacy:
        client._state["management"] = {"clientId": "client-123456789012345678901234", "binding": binding}
    calls = []
    async def request(method, path, **kwargs):
        calls.append(path)
        if path.endswith("/binding"): return {"protocolVersion": 1, "binding": binding}
        if path.endswith("/subjects/bind"):
            scopes = kwargs["json_payload"]["scopes"]
            assert "agents:directory:read" not in scopes
            return {"protocolVersion": 1, "binding": binding, "scopes": scopes,
                "subject_id": "ops-1234567890123456", "subject_capability": "c" * 40}
        assert "/directory/agents?" in path and method == "GET"
        raise BackendClientError("Denied", code="SCOPE_DENIED")
    monkeypatch.setattr(client, "_request_json", request)
    with pytest.raises(BackendClientError) as failure: await client.management_agent_list()
    assert failure.value.code == "SCOPE_DENIED" and len(calls) == 3
    assert "agents:directory:read" not in client._state["management"]["scopes"]


@pytest.mark.anyio
async def test_explicitly_upgraded_directory_grant_survives_rebind_without_expanding_defaults(tmp_path, monkeypatch):
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "grant.json")
    binding = {"projectId": "p", "instanceId": "i"}
    scopes = sorted([*_MANAGEMENT_SCOPES, "agents:directory:read"])
    client._state["management"] = {"clientId": "client-123456789012345678901234", "binding": binding, "scopes": scopes}
    async def request(method, path, **kwargs):
        if path.endswith("/binding"): return {"protocolVersion": 1, "binding": binding}
        assert kwargs["json_payload"]["scopes"] == scopes
        return {"protocolVersion": 1, "binding": binding, "scopes": scopes,
            "subject_id": "ops-1234567890123456", "subject_capability": "c" * 40}
    monkeypatch.setattr(client, "_request_json", request)
    assert (await client._management_grant(require_existing=True))["scopes"] == scopes
