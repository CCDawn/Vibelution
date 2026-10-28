"""Original-subject SDK reads only the closed Team result response."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient, _MANAGEMENT_SCOPES
from tests.test_external_agent_backend_client import _runtime_state


@pytest.mark.anyio
async def test_result_sdk_requires_original_subject_and_rejects_untrusted_shape(tmp_path, monkeypatch):
    _runtime_state(tmp_path)
    client = ManagedAgentBackendClient(tmp_path, state_path=tmp_path / "credentials.json")
    payload = {"status": "available", "text": "Result", "truncated": False, "untrustedContent": True}
    calls = []
    async def grant(*, require_original, require_complete):
        assert require_original is True
        assert require_complete is True
        return {"subjectId": "original-subject", "capability": "original-capability"}
    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return deepcopy(payload)
    monkeypatch.setattr(client, "_original_management_grant", grant)
    monkeypatch.setattr(client, "_request_json", request)
    assert "teams:results:read" not in _MANAGEMENT_SCOPES
    assert await client.management_team_result(request_id="request-1") == payload
    assert calls[-1] == ("GET", "/api/v1/launcher-assistant-management/team-runs/requests/request-1/result",
                         {"management_auth": ("original-subject", "original-capability")})
    with pytest.raises(BackendClientError) as invalid:
        await client.management_team_result(request_id="../other")
    assert invalid.value.code == "INVALID_MANAGEMENT_REQUEST" and len(calls) == 1
    for patch in ({"untrustedContent": False}, {"text": "x" * 12001}, {"status": "empty"},
                  {"truncated": True}, {"privateTranscript": "x"}):
        original = deepcopy(payload)
        payload.update(patch)
        with pytest.raises(BackendClientError) as malformed:
            await client.management_team_result(request_id="request-1")
        assert malformed.value.code == "BACKEND_PROTOCOL_ERROR"
        payload.clear()
        payload.update(original)


@pytest.mark.anyio
@pytest.mark.parametrize("missing", [("subjectId",), ("capability",), ("subjectId", "capability")])
async def test_incomplete_original_subject_never_binds_or_writes(tmp_path, monkeypatch, missing):
    state_path = tmp_path / "credentials.json"
    saved = {"clientId": "client-" + "a" * 32, "subjectId": "ops-" + "b" * 32,
             "capability": "c" * 48, "binding": {"projectId": "project", "instanceId": "instance"}}
    for key in missing:
        saved.pop(key)
    state_path.write_text(json.dumps({"projectRoot": str(tmp_path.resolve()), "management": saved}), encoding="utf-8")
    before = state_path.read_bytes()
    client = ManagedAgentBackendClient(tmp_path, state_path=state_path)
    calls = []
    async def request(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("unexpected network request")
    monkeypatch.setattr(client, "_request_json", request)
    with pytest.raises(BackendClientError) as denied:
        await client.management_team_result(request_id="request-1")
    assert denied.value.code == "UNKNOWN_MANAGEMENT_SUBJECT"
    assert not calls and state_path.read_bytes() == before
