"""Permanent deletion retains native lifecycle and non-replayable receipts."""
from copy import deepcopy

import pytest

from core.web.services.external_management.contracts import contracts
from core.web.services.external_management.service import ManagementError, ManagementService, TargetIdentity
from tests.test_configured_agent_creation import configured_env  # noqa: F401
from tests.test_external_management_agent_archive import _ordinary_with_child


BINDING = {"projectId": "p", "instanceId": "i"}
PARAMETERS = {"agent_id": "agent-a", "expected_config_revision": 3}


@pytest.fixture
def purge_env(tmp_path):
    class Native:
        def __init__(self):
            self.calls = 0
            self.lose = False
            self.apply = True
            self.pending = False
            self.agent = {"agentId": "agent-a", "status": "archived", "directSessionId": "session-a",
                "configRevision": 3, "displayName": "A", "updatedAt": "v3", "llmBindings": {}, "metadata": {}}

        def read_purge_preview(self, agent_id):
            if self.agent is None:
                raise ManagementError("AGENT_UNAVAILABLE", 404)
            return deepcopy(self.agent)

        def read_archive_state(self, agent_id):
            return deepcopy(self.agent)

        def purge(self, parameters, marker):
            self.calls += 1
            assert list((tmp_path / "management" / "requests").glob("*.json"))
            if self.apply:
                self.agent = None
            if self.lose:
                raise TimeoutError("lost native acknowledgement")
            return {"agentId": parameters["agent_id"], "status": "purged", "cleanupPending": self.pending}

    native = Native()
    service = ManagementService(tmp_path / "management", identity=lambda: TargetIdentity(BINDING, "root"), native=native)
    grant = service.bind({"client_id": "purge", "expected_binding": BINDING, "scopes": ["agents:read"]})
    service.invoke(grant["subject_id"], grant["subject_capability"], "authorization_upgrade", {
        "request_id": "scope-1", "expected_binding": BINDING,
        "parameters": {"expected_scopes": ["agents:read"], "add_scopes": ["agents:purge"]}})
    return service, native, grant


def invoke(env, **parameters):
    service, _, grant = env
    return service.invoke(grant["subject_id"], grant["subject_capability"], "agent_purge", {
        "request_id": "purge-1", "expected_binding": BINDING, "parameters": {**PARAMETERS, **parameters}})


def test_purge_is_independent_governed_action_not_a_bootstrap_grant(tmp_path):
    from core.web.services.external_management.documentation import _entry
    assert contracts()["agent_purge"]["scope"] == "agents:purge"
    assert contracts()["agent_purge"]["governed"] is True
    entry = _entry({"method": "DELETE", "path": "/api/agents/{agent_id}/purge", "operationId": "purge", "summary": "purge", "tags": []})
    assert entry["action"] == "agent_purge" and entry["executable"] is True
    service = ManagementService(tmp_path, identity=lambda: TargetIdentity(BINDING, "root"), native=object())
    assert "agents:purge" not in service.binding()["scopes"]
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        service.bind({"client_id": "initial", "expected_binding": BINDING, "scopes": ["agents:purge"]})


@pytest.mark.parametrize("pending", [False, True])
def test_purge_ack_and_absence_freeze_small_historical_result(purge_env, pending):
    service, native, grant = purge_env
    native.pending = pending
    first = invoke(purge_env)
    assert first == {"status": "completed", "action": "agent_purge", "requestId": "purge-1",
        "verified": True, "reused": False,
        "purge": {"agentId": "agent-a", "status": "purged", "cleanupPending": pending}}
    native.agent = {"agentId": "agent-a", "status": "active"}
    restarted = ManagementService(service.root, identity=service.identity, native=native)
    assert restarted.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge", "purge-1") == {**first, "reused": True}
    assert invoke((restarted, native, grant)) == {**first, "reused": True}
    with pytest.raises(ManagementError, match="IDEMPOTENCY_CONFLICT"):
        invoke(purge_env, expected_config_revision=4)
    assert native.calls == 1


@pytest.mark.parametrize("applied", [False, True])
def test_purge_lost_ack_missing_agent_stays_unknown_without_replay(purge_env, applied):
    service, native, grant = purge_env
    native.lose, native.apply = True, applied
    assert invoke(purge_env)["status"] == "unknown"
    restarted = ManagementService(service.root, identity=service.identity, native=native)
    result = restarted.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge", "purge-1")
    assert result["status"] == "unknown" and result["verified"] is False and "purge" not in result
    assert invoke((restarted, native, grant)) == result and native.calls == 1


def test_purge_requires_ack_and_raw_absence_for_first_verification(purge_env):
    service, native, grant = purge_env
    native.apply = False
    assert invoke(purge_env)["status"] == "unknown"
    native.agent = None
    assert service.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge", "purge-1")["status"] == "completed"
    assert native.calls == 1


def test_purge_initially_missing_target_never_produces_success_or_replays(purge_env, monkeypatch):
    service, native, grant = purge_env
    original = deepcopy(native.agent)
    native.agent = None
    def missing(_parameters, _marker):
        native.calls += 1
        raise ManagementError("AGENT_UNAVAILABLE", 404)
    monkeypatch.setattr(native, "purge", missing)
    with pytest.raises(ManagementError, match="AGENT_UNAVAILABLE"):
        invoke(purge_env)
    native.agent = original
    for request in (lambda: invoke(purge_env), lambda: service.receipt(
            grant["subject_id"], grant["subject_capability"], "agent_purge", "purge-1")):
        with pytest.raises(ManagementError, match="AGENT_UNAVAILABLE"):
            request()
    assert native.calls == 1 and native.agent == original


def test_purge_partial_native_failure_is_unknown_not_a_retryable_write(purge_env, monkeypatch):
    service, native, grant = purge_env
    def partial(_parameters, _marker):
        native.calls += 1
        native.agent = None
        raise ManagementError("OPERATION_UNCONFIRMED", 503)
    monkeypatch.setattr(native, "purge", partial)
    assert invoke(purge_env)["status"] == "unknown"
    assert service.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge", "purge-1")["status"] == "unknown"
    assert invoke(purge_env)["status"] == "unknown" and native.calls == 1


def test_slow_purge_receipt_preserves_late_failure_and_authorization(purge_env, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    service, native, grant = purge_env
    entered, release = Event(), Event()

    def fail_late(_parameters, _marker):
        native.calls += 1
        entered.set()
        assert release.wait(5)
        raise ManagementError("STATE_CONFLICT", 409)

    monkeypatch.setattr(native, "purge", fail_late)
    reader = ManagementService(service.root, identity=service.identity, native=native)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(invoke, purge_env)
        try:
            assert entered.wait(2)
            with pytest.raises(ManagementError, match="SUBJECT_DENIED"):
                reader.receipt(grant["subject_id"], "x" * 48, "agent_purge", "purge-1")
            progress = pool.submit(reader.receipt, grant["subject_id"], grant["subject_capability"],
                "agent_purge", "purge-1").result(timeout=0.5)
            assert progress["status"] == "unknown" and progress["verified"] is False and "purge" not in progress
        finally:
            release.set()
        with pytest.raises(ManagementError, match="STATE_CONFLICT"):
            writer.result(timeout=5)
    for request in (lambda: reader.receipt(grant["subject_id"], grant["subject_capability"], "agent_purge", "purge-1"),
                    lambda: invoke(purge_env)):
        with pytest.raises(ManagementError, match="STATE_CONFLICT"):
            request()
    assert native.calls == 1 and native.agent["status"] == "archived"


@pytest.mark.parametrize("extra", [{"force": True}, {"allow_active": True}, {"actor": "operator"},
    {"expected_config_revision": True}, {"expected_config_revision": "3"}, {"expected_config_revision": -1}])
def test_purge_closed_parameters_before_native(purge_env, extra):
    with pytest.raises(ManagementError) as error:
        invoke(purge_env, **extra)
    assert error.value.status_code == 422 and purge_env[1].calls == 0


def test_purge_scope_binding_and_preview_are_separate(purge_env):
    service, native, _ = purge_env
    grant = service.bind({"client_id": "reader", "expected_binding": BINDING, "scopes": ["agents:read", "agents:archive"]})
    preview = service.read_purge_preview(grant["subject_id"], grant["subject_capability"], "agent-a")
    assert preview["agent"]["configRevision"] == 3 and preview["status"] == "archived"
    assert preview["irreversible"] is True and preview["untrustedContent"] is True
    assert preview["effects"] == ["agent", "sessions", "private_workspace", "team_room_mode_references"]
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        invoke((service, native, grant))
    original = purge_env[2]
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        service.invoke(original["subject_id"], original["subject_capability"], "agent_purge", {
            "request_id": "changed", "expected_binding": {**BINDING, "instanceId": "foreign"}, "parameters": PARAMETERS})
    assert native.calls == 0


def _archived(env):
    current, child = _ordinary_with_child(env)
    from core.web.services.external_management.native import NativeAgentGateway
    gateway = NativeAgentGateway(env["root"])
    gateway.archive({"agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}, {})
    return gateway, gateway.read_purge_preview(current["agentId"]), child


def test_native_purge_removes_real_agent_child_sessions_and_workspace(configured_env):
    from core.web.services import session_service as sessions
    gateway, current, child = _archived(configured_env)
    workspace = configured_env["root"] / current["workspacePath"]
    marker = workspace / "events" / "private.jsonl"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("private", encoding="utf-8")
    result = gateway.purge({"agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}, {})
    assert result == {"agentId": current["agentId"], "status": "purged", "cleanupPending": False}
    assert gateway.read_archive_state(current["agentId"]) is None and not workspace.exists()
    for session_id in (current["directSessionId"], child["id"]):
        assert sessions.get_session_detail(session_id) is None


def test_native_purge_cleans_actual_team_membership(configured_env):
    from core.web.services import team_service as teams
    from core.web.services.external_management.native import NativeAgentGateway
    current, _child = _ordinary_with_child(configured_env)
    team = teams.create_team(name="Purge reference", members=[{"agentId": current["agentId"], "role": "member"}])
    directory = configured_env["directory"]
    directory.archive_agent_instance(current["agentId"])
    gateway = NativeAgentGateway(configured_env["root"])
    archived = gateway.read_purge_preview(current["agentId"])
    assert gateway.purge({"agent_id": current["agentId"], "expected_config_revision": archived["configRevision"]}, {})["status"] == "purged"
    assert teams.get_team(team["teamId"])["members"] == []


@pytest.mark.parametrize("denial", ["active", "protected", "stale", "busy", "missing"])
def test_native_purge_rejections_preserve_authorities(configured_env, denial):
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services import session_service as sessions
    directory = configured_env["directory"]
    if denial == "active":
        current, child = _ordinary_with_child(configured_env)
        gateway = NativeAgentGateway(configured_env["root"])
    else:
        gateway, current, child = _archived(configured_env)
    expected = current["configRevision"]
    agent_id = current["agentId"]
    if denial == "protected":
        state = directory.load_state()
        directory._find_agent(state, agent_id)["metadata"]["protected"] = True
        directory.save_state(state)
    elif denial == "stale":
        expected += 1
    elif denial == "busy":
        sessions._set_session_running(child["id"], True)
    elif denial == "missing":
        agent_id = "missing-agent"
    before = directory.registry_path().read_bytes()
    with pytest.raises(ManagementError) as error:
        gateway.purge({"agent_id": agent_id, "expected_config_revision": expected}, {})
    assert error.value.code == {"active": "STATE_CONFLICT", "protected": "AGENT_PROTECTED",
        "stale": "STATE_CONFLICT", "busy": "AGENT_BUSY", "missing": "AGENT_UNAVAILABLE"}[denial]
    assert directory.registry_path().read_bytes() == before
    assert gateway.read_archive_state(current["agentId"]) is not None
    assert sessions.get_session_detail(child["id"])["agentId"] == current["agentId"]


def test_native_preview_is_existing_only_and_purge_allows_archived_team_hidden_metadata(configured_env, monkeypatch):
    gateway, current, _child = _archived(configured_env)
    directory = configured_env["directory"]
    state = directory.load_state()
    raw = directory._find_agent(state, current["agentId"])
    raw["metadata"].update({"teamId": "historical-team", "hiddenFromIndex": True, "virtualHumanCompanion": True})
    directory.save_state(state)
    before = directory.registry_path().read_bytes()
    with monkeypatch.context() as guard:
        guard.setattr(directory, "get_agent", lambda *a, **k: pytest.fail("preview may not repair"))
        guard.setattr(directory, "save_state", lambda *a, **k: pytest.fail("preview may not write"))
        assert gateway.read_purge_preview(current["agentId"])["agentId"] == current["agentId"]
    assert directory.registry_path().read_bytes() == before
    result = gateway.purge({"agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}, {})
    assert result["status"] == "purged"


@pytest.mark.parametrize("unsafe", ["foreign_workspace", "reparse"])
def test_native_purge_keeps_private_workspace_and_junction_guards(configured_env, monkeypatch, unsafe):
    from core.web.routes import agents as owner
    gateway, current, _child = _archived(configured_env)
    directory = configured_env["directory"]
    if unsafe == "foreign_workspace":
        state = directory.load_state()
        directory._find_agent(state, current["agentId"])["workspacePath"] = "workspace/agents/another-agent"
        directory.save_state(state)
    else:
        monkeypatch.setattr(directory, "_path_has_reparse_component", lambda *_a, **_k: True)
    before = directory.registry_path().read_bytes()
    monkeypatch.setattr(owner, "agent_purge", lambda *_a: pytest.fail("unsafe workspace must not enter native owner"))
    for request in (lambda: gateway.read_purge_preview(current["agentId"]), lambda: gateway.purge({
            "agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}, {})):
        with pytest.raises(ManagementError, match="AGENT_PROTECTED"):
            request()
    assert directory.registry_path().read_bytes() == before


def test_purge_preview_effects_are_complete_and_ordered():
    from pydantic import ValidationError
    from core.web.services.external_management.contracts import AgentPurgePreviewResponse
    agent = {"agentId": "agent-a", "directSessionId": "s", "displayName": "A", "configRevision": 1,
        "updatedAt": "now", "modelId": "m", "avatarImagePath": ""}
    values = {"agent": agent, "status": "archived", "irreversible": True, "untrustedContent": True}
    for effects in ([], ["agent"], ["agent", "agent", "private_workspace", "team_room_mode_references"],
                    ["sessions", "agent", "private_workspace", "team_room_mode_references"]):
        with pytest.raises(ValidationError):
            AgentPurgePreviewResponse.model_validate({**values, "effects": effects})


def test_native_purge_rechecks_concurrent_config_change_under_archive_cas(configured_env, monkeypatch):
    from contextlib import contextmanager
    from threading import Event, Thread
    from core.web.services import session_service as sessions
    from core.web.routes import agents as owner
    gateway, current, _child = _archived(configured_env)
    ready, changed = Event(), Event()
    errors = []

    def update():
        try:
            assert ready.wait(2)
            configured_env["directory"].update_agent_instance(current["agentId"], display_name="Concurrent edit")
        except BaseException as exc:
            errors.append(exc)
        finally:
            changed.set()

    original = sessions.agent_archive_transaction
    @contextmanager
    def after_preview(*args, **kwargs):
        ready.set()
        assert changed.wait(2)
        with original(*args, **kwargs) as locked:
            yield locked

    monkeypatch.setattr(sessions, "agent_archive_transaction", after_preview)
    monkeypatch.setattr(owner, "agent_purge", lambda *_a: pytest.fail("stale CAS must not call native owner"))
    worker = Thread(target=update)
    worker.start()
    try:
        with pytest.raises(ManagementError, match="STATE_CONFLICT"):
            gateway.purge({"agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}, {})
    finally:
        ready.set()
        worker.join(timeout=3)
    assert not worker.is_alive() and not errors
    assert gateway.read_archive_state(current["agentId"])["displayName"] == "Concurrent edit"


def test_purge_handoff_keeps_lifecycle_locked_and_prevents_new_turn(configured_env, monkeypatch):
    from threading import Event, Thread
    from core.web.services import session_service as sessions
    from core.web.routes import agents as owner
    gateway, current, child = _archived(configured_env)
    results = []
    submitted = Event()
    workers = []

    def attempt_submit():
        try:
            sessions.submit_session_message(child["id"], "Must remain archived")
            results.append("unexpected-turn")
        except (sessions.SessionValidationError, sessions.SessionNotFoundError):
            results.append("submit-rejected")
        finally:
            submitted.set()

    def observe(_agent_id):
        def probe_locks():
            for name, lock in (("chat", sessions._CHAT_STATE_LOCK.bounded(timeout=0.05)),
                               ("agent", configured_env["directory"].agent_session_lifecycle_transaction(timeout=0.05))):
                try:
                    with lock:
                        results.append("unlocked-" + name)
                except TimeoutError:
                    results.append("locked-" + name)
        probe = Thread(target=probe_locks)
        probe.start()
        probe.join(timeout=2)
        assert not probe.is_alive() and {"locked-chat", "locked-agent"} <= set(results)
        worker = Thread(target=attempt_submit)
        workers.append(worker)
        worker.start()
        # A concurrent submit must either wait for the lifecycle fence or
        # reject the sealed Session; it cannot publish a new Turn.
        submitted.wait(0.05)
        assert "unexpected-turn" not in results
        return {"agentId": _agent_id, "status": "purged", "deleted": True,
            "purgeSummary": {"sessions": {"cleanupPending": False}}}

    monkeypatch.setattr(owner, "agent_purge", observe)
    monkeypatch.setattr(sessions, "_resolve_active_agent_for_turn", lambda *_a, **_k: pytest.fail("archived submit admitted"))
    gateway.purge({"agent_id": current["agentId"], "expected_config_revision": current["configRevision"]}, {})
    for worker in workers:
        worker.join(timeout=3)
        assert not worker.is_alive()
    assert results.count("submit-rejected") == 1 and "unexpected-turn" not in results
