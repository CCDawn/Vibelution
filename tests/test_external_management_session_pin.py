"""Governed ordinary-session pinning reuses the native writer and durable intent."""
from __future__ import annotations

import json

import pytest

from tests.test_external_management_workspace import env  # noqa: F401 -- shared isolated native authorities

PREFIX = "/v1/launcher-assistant-management"


@pytest.fixture
def pin_env(env, monkeypatch):
    from core.web.services.session import session_pin_ops
    grant = env.service.bind({"client_id": "pin-launcher", "expected_binding": env.identity,
        "scopes": ["sessions:pin"]})
    env.pin_headers = {**env.headers, "X-Vibelution-Management-Subject": grant["subject_id"],
        "X-Vibelution-Management-Capability": grant["subject_capability"]}
    env.writes = []
    def setter(session_id, *, pinned):
        env.writes.append((session_id, pinned))
        env.row["pinnedAtMs"] = 456 if pinned else None
        return {"id": session_id, "pinned": pinned, "pinnedAtMs": env.row["pinnedAtMs"]}
    monkeypatch.setattr(session_pin_ops, "set_chat_session_pinned", setter)
    return env


def invoke(env, *, request_id="pin-1", parameters=None, headers=None):
    return env.client.post(PREFIX + "/actions/session_pin", headers=headers or env.pin_headers,
        json={"request_id": request_id, "expected_binding": env.identity,
            "parameters": parameters if parameters is not None else {"session_id": "session-a", "pinned": False}})


def test_pin_http_durable_receipt_no_replay_and_parameter_conflict(pin_env):
    e = pin_env
    first = invoke(e)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["verified"] is True and result["session"]["pinned"] is False
    assert set(result) == {"status", "action", "requestId", "verified", "reused", "session"}
    assert "SECRET" not in first.text and "agent" not in result
    second = invoke(e)
    receipt = e.client.get(PREFIX + "/actions/session_pin/requests/pin-1", headers=e.pin_headers)
    assert second.json() == receipt.json() == {**result, "reused": True}
    assert e.writes == [("session-a", False)]
    conflict = invoke(e, parameters={"session_id": "session-a", "pinned": True})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    record = json.loads(next((e.service.root / "requests").glob("*.json")).read_text())
    assert record["sessionId"] == "session-a" and "agentId" not in record


def test_target_state_is_noop_without_refreshing_pinned_timestamp(pin_env):
    result = invoke(pin_env, parameters={"session_id": "session-a", "pinned": True})
    assert result.status_code == 200 and result.json()["session"]["pinnedAtMs"] == 123
    assert result.json()["verified"] is True and pin_env.writes == []


def test_completed_receipt_is_historical_and_current_session_is_separate(pin_env):
    e = pin_env
    e.row["pinnedAtMs"] = None
    params = {"session_id": "session-a", "pinned": True}
    first = invoke(e, parameters=params).json()
    assert first["session"]["pinnedAtMs"] == 456
    e.row["pinnedAtMs"] = None  # Later independent operator action.
    assert invoke(e, parameters=params).json() == {**first, "reused": True}
    receipt = e.client.get(PREFIX + "/actions/session_pin/requests/pin-1", headers=e.pin_headers)
    assert receipt.json() == {**first, "reused": True}
    current = e.client.get(PREFIX + "/sessions/session-a", headers=e.headers)
    assert current.json()["session"]["pinned"] is False and e.writes == [("session-a", True)]


def test_real_canonical_pin_writer_preserves_selection_and_transcript(env, monkeypatch):
    from core.chat.conversation_store import ConversationStore
    from core.web.services.session import session_pin_ops
    e = env
    grant = e.service.bind({"client_id": "pin-real", "expected_binding": e.identity,
        "scopes": ["sessions:pin"]})
    e.pin_headers = {**e.headers, "X-Vibelution-Management-Subject": grant["subject_id"],
        "X-Vibelution-Management-Capability": grant["subject_capability"]}
    original = session_pin_ops.set_chat_session_pinned
    writes = []
    def observed(session_id, *, pinned):
        writes.append((session_id, pinned))
        return original(session_id, pinned=pinned)
    monkeypatch.setattr(session_pin_ops, "set_chat_session_pinned", observed)
    monkeypatch.setattr(e.sessions, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(e.sessions, "record_runtime_scene_event", lambda *a, **k: None)
    monkeypatch.setattr(e.sessions, "get_web_language", lambda: "en")
    with ConversationStore(e.root / "pin.sqlite3") as store:
        rev = store.repository.create_agent(agent_id="agent-a", display_name="A", kind="persistent",
            config={}, source="test").result(timeout=3)["configRevisionId"]
        store.repository.create_session(session_id="session-a", agent_id="agent-a", agent_config_revision_id=rev,
            title="ordinary", conversation_index_kind="personal_agent", conversation_index_visibility="user_visible").result(timeout=3)
        store.repository.upsert_session_runtime_state("session-a", e.runtime).result(timeout=3)
        store.repository.upsert_session_runtime_state("selected", {"conversation_id": "selected"}, activate=True).result(timeout=3)
        monkeypatch.setattr(e.directory_runtime, "get_open_directory_store", lambda: store)
        before = store.repository.get_session_runtime_state("session-a")
        first = invoke(e, parameters={"session_id": "session-a", "pinned": True})
        assert first.status_code == 200, first.text
        timestamp = first.json()["session"]["pinnedAtMs"]
        assert timestamp > 0 and writes == [("session-a", True)]
        assert invoke(e, parameters={"session_id": "session-a", "pinned": True}).json()["session"]["pinnedAtMs"] == timestamp
        assert invoke(e, request_id="another-noop", parameters={"session_id": "session-a", "pinned": True}).json()["session"]["pinnedAtMs"] == timestamp
        assert writes == [("session-a", True)]
        assert store.repository.get_active_session_id() == "selected"
        assert store.repository.get_session_runtime_state("session-a") == before
        unpinned = invoke(e, request_id="unpin-1")
        assert unpinned.json()["session"]["pinned"] is False and writes == [("session-a", True), ("session-a", False)]
        assert store.repository.get_active_session_id() == "selected"


@pytest.mark.parametrize("extra", [{"agent_id": "fake"}, {"actor": "operator"}, {"root": "other"},
    {"title": "injected"}, {"body": "injected"}, {"pinned": "false"}, {"pinned": 0}, {"pinned": None},
    {"session_id": "../private"}, {"agentId": "fake"}])
def test_pin_closed_strict_parameters_before_native_writer(pin_env, extra):
    response = invoke(pin_env, parameters={"session_id": "session-a", "pinned": False, **extra})
    assert response.status_code == 422 and pin_env.writes == []


def test_read_scope_cannot_write_and_existing_grant_cannot_gain_pin(pin_env):
    from core.web.services.external_management.service import ManagementError
    assert invoke(pin_env, headers=pin_env.headers).status_code == 403
    with pytest.raises(ManagementError) as denied:
        pin_env.service.bind({"client_id": "launcher", "expected_binding": pin_env.identity,
            "scopes": ["sessions:read", "sessions:pin"]})
    assert denied.value.code == "SUBJECT_GRANT_CONFLICT" and pin_env.writes == []
    assert pin_env.client.post(PREFIX + "/actions/session_pin", json={}).status_code == 403


@pytest.mark.parametrize("target,patch", [("row", {"hiddenFromIndex": True}),
    ("row", {"sessionKind": "supervised"}), ("row", {"sessionRole": 42}),
    ("row", {"pinnedAtMs": True}), ("row", {"pinnedAtMs": -1}), ("row", {"pinned": False}),
    ("runtime", {"agent_id": "foreign"}), ("agent", {"roleKey": "personal_assistant"}),
    ("agent", {"metadata": {"virtualHumanCompanion": True}}), ("agent", {"metadata": {"teamId": "team"}})])
def test_pin_native_visibility_and_damaged_metadata_block_writer(pin_env, target, patch):
    getattr(pin_env, target).update(patch)
    pin_env.save()
    assert invoke(pin_env).status_code == 404 and pin_env.writes == []


@pytest.mark.parametrize("source", ["roster", "plugin", "registry-damage", "roster-damage", "directory-unavailable", "wrong-root"])
def test_pin_requires_every_native_visibility_authority(pin_env, monkeypatch, source):
    e = pin_env
    if source == "roster":
        e.team_index.write_text(json.dumps({"teams": [{"teamId": "team", "members": [{"agentId": "agent-a"}]}]}))
    elif source == "plugin":
        (e.plugin_root / "binding.json").write_text('{"enabled":true,"agentId":"agent-a"}')
    elif source == "registry-damage":
        e.registry.write_text("broken")
    elif source == "roster-damage":
        e.team_index.write_text("broken")
    elif source == "directory-unavailable":
        monkeypatch.setattr(e.directory_runtime, "get_open_directory_store", lambda: None)
    else:
        monkeypatch.setattr(e.directory_runtime, "directory_store_project_root", lambda: e.root / "foreign")
    response = invoke(e)
    assert response.status_code == ({"directory-unavailable": 503, "wrong-root": 409}.get(source, 404))
    assert e.writes == []


@pytest.mark.parametrize("after_write", [True, False])
def test_lost_ack_restart_readback_never_repeats_writer(pin_env, monkeypatch, after_write):
    from core.web.services.external_management.service import ManagementService
    from core.web.services.session import session_pin_ops
    e = pin_env
    def lost(session_id, *, pinned):
        e.writes.append((session_id, pinned))
        if after_write:
            e.row["pinnedAtMs"] = None
        raise TimeoutError("lost native ack")
    monkeypatch.setattr(session_pin_ops, "set_chat_session_pinned", lost)
    assert invoke(e).json()["status"] == "unknown"
    restarted = ManagementService(e.service.root, identity=e.service.identity, native=e.native)
    subject = e.pin_headers["X-Vibelution-Management-Subject"]
    capability = e.pin_headers["X-Vibelution-Management-Capability"]
    result = restarted.receipt(subject, capability, "session_pin", "pin-1")
    assert result["status"] == ("completed" if after_write else "unknown")
    assert result["verified"] is after_write
    assert restarted.invoke(subject, capability, "session_pin", {"request_id": "pin-1",
        "expected_binding": e.identity, "parameters": {"session_id": "session-a", "pinned": False}}) == result
    assert e.writes == [("session-a", False)]


def test_writer_ack_does_not_replace_canonical_desired_state_readback(pin_env, monkeypatch):
    from core.web.services.session import session_pin_ops
    monkeypatch.setattr(session_pin_ops, "set_chat_session_pinned", lambda *a, **k:
        {"id": "session-a", "pinned": False, "pinnedAtMs": None})
    result = invoke(pin_env)
    assert result.json()["status"] == "unknown" and result.json()["verified"] is False


def test_pin_description_scope_and_native_documentation_mapping():
    from core.web.services.external_management.contracts import SCOPES, BindSubject, contracts
    from core.web.services.external_management.documentation import _entry
    assert contracts()["session_pin"]["governed"] is True
    assert contracts()["session_pin"]["scope"] == "sessions:pin"
    assert len(BindSubject.model_validate({"client_id": "fresh", "expected_binding": {"projectId": "p", "instanceId": "i"},
        "scopes": list(SCOPES)}).scopes) == len(SCOPES) == 14
    assert SCOPES[-1] == "legacy:receipts:read"
    for path in ("/api/sessions/{session_id}/pin", "/api/sessions/{session_id}/unpin"):
        entry = _entry({"operationId": "pin", "method": "POST", "path": path, "summary": "pin", "tags": []})
        assert entry["action"] == "session_pin" and entry["executable"] is True
