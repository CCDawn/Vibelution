"""Governed archive delegates native lifecycle and never replays an intent."""
from copy import deepcopy

import pytest

from core.web.services.external_management.service import ManagementService, TargetIdentity, ManagementError
from tests.test_configured_agent_creation import configured_env  # noqa: F401

BINDING = {"projectId": "p", "instanceId": "i"}
PARAMETERS = {"agent_id": "agent-a", "expected_config_revision": 3}


@pytest.fixture
def archive_env(tmp_path):
    class Native:
        def __init__(self):
            self.calls = 0
            self.lose = False
            self.apply = True
            self.agent = {"agentId": "agent-a", "status": "active", "directSessionId": "real-session",
                "configRevision": 3, "displayName": "A", "updatedAt": "v3", "llmBindings": {}, "metadata": {}}

        def read(self, agent_id):
            return deepcopy(self.agent)

        def read_archive_state(self, agent_id):
            return deepcopy(self.agent)

        def archive(self, parameters, marker):
            self.calls += 1
            assert list((tmp_path / "management" / "requests").glob("*.json"))
            if self.apply:
                self.agent["status"] = "archived"
            if self.lose:
                raise TimeoutError("lost ack")
            return deepcopy(self.agent)

    native = Native()
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(BINDING, "root"), native=native)
    grant = service.bind({"client_id": "archive", "expected_binding": BINDING, "scopes": ["agents:archive"]})
    return service, native, grant


def invoke(env, **parameters):
    service, _, grant = env
    return service.invoke(grant["subject_id"], grant["subject_capability"], "agent_archive",
        {"request_id": "archive-1", "expected_binding": BINDING, "parameters": {**PARAMETERS, **parameters}})


def test_archive_durable_intent_historical_receipt_and_conflict(archive_env):
    first = invoke(archive_env)
    service, native, grant = archive_env
    assert first["status"] == "completed" and first["verified"] is True
    assert first["agent"]["agentId"] == "agent-a" and first["agent"]["directSessionId"] == "real-session"
    native.agent["status"] = "active"  # Later operator state does not rewrite the historical receipt.
    assert invoke(archive_env) == {**first, "reused": True}
    assert service.receipt(grant["subject_id"], grant["subject_capability"], "agent_archive", "archive-1") == {**first, "reused": True}
    with pytest.raises(ManagementError) as conflict:
        invoke(archive_env, expected_config_revision=4)
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT" and native.calls == 1


@pytest.mark.parametrize("applied", [True, False])
def test_archive_lost_ack_restart_reads_only(archive_env, applied):
    service, native, grant = archive_env
    native.lose, native.apply = True, applied
    assert invoke(archive_env)["status"] == "unknown"
    restarted = ManagementService(service.root, identity=service.identity, native=native)
    result = restarted.receipt(grant["subject_id"], grant["subject_capability"], "agent_archive", "archive-1")
    assert result["status"] == ("completed" if applied else "unknown")
    assert invoke((restarted, native, grant)) == result and native.calls == 1


@pytest.mark.parametrize("extra", [{"force": True}, {"purge": True}, {"actor": "operator"},
    {"expected_config_revision": True}, {"expected_config_revision": "3"}, {"expected_config_revision": -1}])
def test_archive_strict_closed_before_native(archive_env, extra):
    with pytest.raises(ManagementError) as invalid:
        invoke(archive_env, **extra)
    assert invalid.value.status_code == 422 and archive_env[1].calls == 0


def test_archive_requires_independent_scope(archive_env):
    service, native, _ = archive_env
    grant = service.bind({"client_id": "read-only", "expected_binding": BINDING, "scopes": ["agents:read", "agents:update"]})
    with pytest.raises(ManagementError) as denied:
        invoke((service, native, grant))
    assert denied.value.code == "SCOPE_DENIED" and native.calls == 0


def test_archive_contract_and_documentation():
    from core.web.services.external_management.contracts import contracts
    from core.web.services.external_management.documentation import _entry
    assert contracts()["agent_archive"]["governed"] is True
    assert contracts()["agent_archive"]["scope"] == "agents:archive"
    entry = _entry({"method": "DELETE", "path": "/api/agents/{agent_id}", "operationId": "archive", "summary": "archive", "tags": []})
    assert entry["action"] == "agent_archive" and entry["executable"] is True


def _ordinary_with_child(env):
    from core.web.services.agent_operation_service import create_configured_agent_with_session
    from core.web.services.team import team_store
    config = env["directory"].CONFIG_PATH
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
    roster = team_store._teams_index_path(seed=False)
    roster.parent.mkdir(parents=True, exist_ok=True)
    roster.write_text('{"teams":[]}', encoding="utf-8")
    agent = create_configured_agent_with_session(display_name="Archive test", primary_mode="chat",
        role_key="assistant_worker", prompt_template_id="prompt-chat-default",
        llm_bindings={"dialogue": {"modelId": "model-primary"}}, tool_policy={"allowedTools": []},
        source="archive-test")
    child = env["sessions"].create_child_session(agent["directSessionId"], user_request="Archive lifecycle",
        task_title="Child", auto_start=False, switch_to_child=False, source="archive-test")["childSession"]
    return agent, child


def test_native_archive_real_transaction_seals_direct_and_child(configured_env):
    from core.web.services import agent_directory_service as directory, session_service as sessions
    from core.web.services.external_management.native import NativeAgentGateway
    current, child = _ordinary_with_child(configured_env)
    gateway = NativeAgentGateway(configured_env["root"])
    result = gateway.archive({"agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}, {})
    assert result["status"] == "archived" and result["directSessionId"] == current["directSessionId"]
    for session_id in (current["directSessionId"], child["id"]):
        detail = sessions.get_session_detail(session_id)
        assert detail["readOnly"] is True and detail["archiveState"]["source"] == "agent_archive"


@pytest.mark.parametrize("denial", ["stale", "protected", "busy"])
def test_native_archive_rejections_preserve_agent_and_sessions(configured_env, denial):
    from core.web.services import agent_directory_service as directory, session_service as sessions
    from core.web.services.external_management.native import NativeAgentGateway
    current, child = _ordinary_with_child(configured_env)
    expected = current["configRevision"]
    if denial == "stale":
        expected += 1
    elif denial == "protected":
        directory.update_agent_instance(current["agentId"], metadata={"protected": True})
    else:
        sessions._set_session_running(child["id"], True)
    with pytest.raises(ManagementError) as rejected:
        NativeAgentGateway(configured_env["root"]).archive({"agent_id": current["agentId"], "expected_config_revision": expected}, {})
    assert rejected.value.code == {"stale": "STATE_CONFLICT", "protected": "AGENT_PROTECTED", "busy": "AGENT_BUSY"}[denial]
    assert directory.get_agent(current["agentId"], include_archived=True)["status"] == "active"
    for session_id in (current["directSessionId"], child["id"]):
        assert not sessions.get_session_detail(session_id).get("readOnly")


@pytest.mark.parametrize("patch", [{"roleKey": "personal_assistant"}, {"roleKey": ""}, {"kind": "ephemeral"},
    {"configRevision": True}, {"conversationIndexKind": "hidden"}, {"conversationIndexKind": 42},
    {"metadata": {"virtualHumanCompanion": True}}, {"metadata": {"teamId": "team"}},
    {"metadata": {"systemRole": "internal"}}, {"metadata": {"hiddenFromIndex": True}}])
def test_native_archive_rejects_private_or_damaged_agent_before_owner(configured_env, monkeypatch, patch):
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.routes import agents as owner
    current, _child = _ordinary_with_child(configured_env)
    directory = configured_env["directory"]
    # Damage the raw authority to prove projections cannot normalize it away.
    import json
    state = directory.load_state()
    directory._find_agent(state, current["agentId"]).update(patch)
    directory.registry_path().write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(owner, "_archive_agent_with_session_lifecycle", lambda *a, **k: pytest.fail("owner must not run"))
    with pytest.raises(ManagementError) as denied:
        NativeAgentGateway(configured_env["root"]).archive({"agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}, {})
    assert denied.value.code in {"AGENT_PROTECTED", "STATE_CONFLICT"}


def test_archive_admission_never_uses_repairing_getter(configured_env, monkeypatch):
    from core.web.services.external_management.native import NativeAgentGateway
    current, _child = _ordinary_with_child(configured_env)
    directory = configured_env["directory"]
    registry = directory.registry_path()
    before = registry.read_bytes()
    with monkeypatch.context() as guard:
        guard.setattr(directory, "get_agent", lambda *a, **k: pytest.fail("repairing getter before admission"))
        guard.setattr(directory, "save_state", lambda *a, **k: pytest.fail("write before admission"))
        with pytest.raises(ManagementError) as denied:
            NativeAgentGateway(configured_env["root"]).archive({"agent_id": current["agentId"],
                "expected_config_revision": current["configRevision"] + 1}, {})
        assert denied.value.code == "STATE_CONFLICT"
    assert registry.read_bytes() == before


def test_archive_unknown_readback_never_repairs_or_seeds(configured_env, monkeypatch, tmp_path):
    from core.web.services.external_management.native import NativeAgentGateway
    from core.infrastructure import developer_sandbox
    current, _child = _ordinary_with_child(configured_env)
    directory = configured_env["directory"]
    gateway = NativeAgentGateway(configured_env["root"])
    calls = []
    def lose_ack(*args):
        calls.append(True)
        raise TimeoutError("lost ack")
    monkeypatch.setattr(gateway, "archive", lose_ack)
    service = ManagementService(tmp_path / "archive-read", identity=lambda: TargetIdentity(BINDING, "root"), native=gateway)
    grant = service.bind({"client_id": "raw-read", "expected_binding": BINDING, "scopes": ["agents:archive"]})
    envelope = {"request_id": "read-1", "expected_binding": BINDING, "parameters": {
        "agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}}
    assert service.invoke(grant["subject_id"], grant["subject_capability"], "agent_archive", envelope)["status"] == "unknown"
    state = directory.load_state()
    raw = directory._find_agent(state, current["agentId"])
    raw["status"] = "archived"
    raw["metadata"]["avatarImagePath"] = "workspace/avatars/archive-test.png"
    raw.pop("personaProfile", None)  # A legacy repair candidate must remain raw.
    directory.save_state(state)
    registry = directory.registry_path()
    before = registry.read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail("archive recovery may not repair, seed or initialize")
    with monkeypatch.context() as guard:
        guard.setattr(directory, "get_agent", forbidden)
        guard.setattr(directory, "save_state", forbidden)
        guard.setattr(directory, "load_agent_record", forbidden)
        guard.setattr(developer_sandbox, "_ensure_active_state", forbidden)
        guard.setattr(developer_sandbox, "seeded_sandbox_workspace_path", forbidden)
        restarted = ManagementService(service.root, identity=service.identity, native=gateway)
        result = restarted.receipt(grant["subject_id"], grant["subject_capability"], "agent_archive", "read-1")
        assert result["status"] == "completed" and result["verified"] is True
        assert result["agent"]["avatarImagePath"] == "workspace/avatars/archive-test.png"
    assert registry.read_bytes() == before and len(calls) == 1


def test_archive_missing_developer_authority_never_initializes(configured_env, monkeypatch):
    from core.web.services.external_management.native import NativeAgentGateway
    from core.infrastructure import developer_sandbox
    current, _child = _ordinary_with_child(configured_env)
    directory = configured_env["directory"]
    registry = directory.registry_path()
    before = registry.read_bytes()
    active = developer_sandbox._active_state_path(configured_env["root"])
    assert not active.exists()
    directory.CONFIG_PATH.write_text("[launcher.developer_mode]\nenabled = true\n", encoding="utf-8")
    def forbidden(*args, **kwargs):
        pytest.fail("missing authority may not initialize or seed")
    with monkeypatch.context() as guard:
        guard.setattr(developer_sandbox, "CONFIG_PATH", directory.CONFIG_PATH)
        guard.setattr(developer_sandbox, "_ensure_active_state", forbidden)
        guard.setattr(developer_sandbox, "seeded_sandbox_workspace_path", forbidden)
        gateway = NativeAgentGateway(configured_env["root"])
        with pytest.raises(ManagementError) as denied:
            gateway.archive({"agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}, {})
        assert denied.value.code == "AGENT_UNAVAILABLE"
        with pytest.raises(ValueError):
            gateway.read_archive_state(current["agentId"])
    assert not active.exists() and registry.read_bytes() == before
