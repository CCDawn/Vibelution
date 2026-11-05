"""Independent Launcher management permission persistence and trusted HTTP boundary."""

import copy
import threading

import pytest
from fastapi.testclient import TestClient

from core.assistant_runtime.host import NativeFacade, create_app
from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as personal
from tests.test_personal_assistant_service import finance_env, personal_env


@pytest.fixture(autouse=True)
def _private_operator_config(tmp_path, monkeypatch, reset_singletons):
    config_path = tmp_path / "operator" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(config_path.parent))
    from config import settings
    monkeypatch.setattr(settings, "_settings", None)
    monkeypatch.setattr(settings, "_config_path", str(config_path))


@pytest.fixture
def permissions():
    from core.web.services.local_assistant import management_permissions
    return management_permissions


def test_projection_defaults_are_pure_and_bad_persisted_policy_fails_closed(permissions):
    agent = {"metadata": {"unrelated": {"keep": True}}}
    before = copy.deepcopy(agent)
    assert permissions.projection(agent) == {"preset": "request_approval", "revision": 0}
    assert agent == before
    for value in (None, {}, {"preset": "full_access", "revision": True},
                  {"preset": "full_access", "revision": -1},
                  {"preset": "full_access", "revision": 2**53},
                  {"preset": "FULL_ACCESS", "revision": 1},
                  {"preset": "auto_review", "revision": 1, "extra": True}):
        with pytest.raises(permissions.ManagementPermissionError) as error:
            permissions.projection({"metadata": {permissions.METADATA_KEY: value}})
        assert error.value.code == "ASSISTANT_PERMISSION_UNAVAILABLE"


def test_native_owner_persists_cas_without_changing_agent_policy(personal_env, permissions, monkeypatch):
    assistant = personal.create_personal_assistant()["assistant"]
    aid = assistant["agentId"]
    before = directory.get_agent(aid)
    assert permissions.read(aid) == {"preset": "request_approval", "revision": 0}
    assert personal.get_personal_assistant_settings()["settings"]["managementPermission"] == permissions.read(aid)
    real_update = directory.update_agent_instance
    def update(agent_id, **kwargs):
        assert kwargs["expected_updated_at"] == directory.get_agent(agent_id)["updatedAt"]
        return real_update(agent_id, **kwargs)
    monkeypatch.setattr(directory, "update_agent_instance", update)
    expected = {"preset": "auto_review", "revision": 1}
    assert permissions.update("auto_review", 0) == expected
    assert permissions.read(aid) == expected
    after = directory.get_agent(aid)
    for field in ("permissionPreset", "sandboxMode", "approvalPolicy", "toolPolicy", "memoryPolicy",
                  "configHash", "configRevision"):
        assert after.get(field) == before.get(field), field
    for key, value in before["metadata"].items():
        assert after["metadata"][key] == value
    assert permissions.update("auto_review", 1) == expected
    assert directory.get_agent(aid)["updatedAt"] == after["updatedAt"]
    with pytest.raises(permissions.ManagementPermissionError) as error:
        permissions.update("full_access", 0)
    assert error.value.code == "ASSISTANT_PERMISSION_CONFLICT"
    assert permissions.read(aid) == expected


def test_competing_policy_writers_have_one_winner(personal_env, permissions):
    from concurrent.futures import ThreadPoolExecutor
    aid = personal.create_personal_assistant()["assistant"]["agentId"]
    barrier = threading.Barrier(2)
    def change(preset):
        barrier.wait(timeout=5)
        try:
            return permissions.update(preset, 0)
        except permissions.ManagementPermissionError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, ("auto_review", "full_access")))
    winners = [result for result in results if isinstance(result, dict)]
    assert len(winners) == 1
    assert results.count("ASSISTANT_PERMISSION_CONFLICT") == 1
    assert permissions.read(aid) == winners[0]


def test_reserved_metadata_authority_is_exact_and_cleared_after_failed_cas(personal_env, permissions, monkeypatch):
    aid = personal.create_personal_assistant()["assistant"]["agentId"]
    payload = {permissions.METADATA_KEY: {"preset": "full_access", "revision": 1}}
    real_update = directory.update_agent_instance
    def failed_update(agent_id, **kwargs):
        permissions.assert_metadata_write_allowed(agent_id, kwargs["metadata"])
        for wrong_agent, wrong_metadata in (("foreign", payload), (aid,
                {permissions.METADATA_KEY: {"preset": "auto_review", "revision": 1}}),
                (aid, {permissions.METADATA_KEY: {"preset": "full_access", "revision": True}})):
            with pytest.raises(permissions.ManagementPermissionError):
                permissions.assert_metadata_write_allowed(wrong_agent, wrong_metadata)
        raise directory.AgentStateConflictError("competing write")
    monkeypatch.setattr(directory, "update_agent_instance", failed_update)
    with pytest.raises(permissions.ManagementPermissionError) as error:
        permissions.update("full_access", 0)
    assert error.value.code == "ASSISTANT_PERMISSION_CONFLICT"
    with pytest.raises(permissions.ManagementPermissionError):
        permissions.assert_metadata_write_allowed(aid, payload)
    with pytest.raises(permissions.ManagementPermissionError):
        permissions.assert_metadata_write_allowed(aid, list(payload.items()))
    monkeypatch.setattr(directory, "update_agent_instance", real_update)
    assert permissions.update("full_access", 0) == {"preset": "full_access", "revision": 1}
    with pytest.raises(permissions.ManagementPermissionError):
        permissions.assert_metadata_write_allowed(aid, payload)


@pytest.mark.parametrize("preset,revision", [("other", 0), ("FULL_ACCESS", 0), (None, 0),
    ("full_access", True), ("full_access", "0"), ("full_access", 1.0),
    ("full_access", -1), ("full_access", 2**53)])
def test_owner_rejects_bad_fields_before_any_identity_read(permissions, monkeypatch, preset, revision):
    monkeypatch.setattr(personal, "_active_profile_agent", lambda: pytest.fail("invalid input read identity"))
    with pytest.raises(permissions.ManagementPermissionError) as error:
        permissions.update(preset, revision)
    assert error.value.code == "ASSISTANT_PERMISSION_INVALID"


def test_owner_rejects_missing_foreign_archived_or_conflicting_identity(personal_env, permissions):
    with pytest.raises(permissions.ManagementPermissionError):
        permissions.read("missing")
    aid = personal.create_personal_assistant()["assistant"]["agentId"]
    with pytest.raises(permissions.ManagementPermissionError):
        permissions.read(personal_env["owner"])
    directory.update_agent_instance(aid, status="archived")
    with pytest.raises(permissions.ManagementPermissionError):
        permissions.read(aid)
    with pytest.raises(permissions.ManagementPermissionError):
        permissions.update("full_access", 0)


def test_multiple_profile_identities_fail_closed(personal_env, permissions):
    aid = personal.create_personal_assistant()["assistant"]["agentId"]
    directory.update_agent_instance(personal_env["owner"], metadata={"personalAssistantProfile": personal.PROFILE})
    for operation in (lambda: permissions.read(aid), lambda: permissions.update("full_access", 0)):
        with pytest.raises(permissions.ManagementPermissionError) as error:
            operation()
        assert error.value.code == "ASSISTANT_PERMISSION_UNAVAILABLE"


class PermissionNative:
    def bootstrap(self):
        return {"assistant": {"agentId": "a", "directSessionId": "s"}}

    def shutdown(self):
        return None

    def set_management_permission(self, preset, expected_revision):
        from core.assistant_runtime.native import AssistantSessionError
        self.calls.append((preset, expected_revision))
        if self.failure:
            raise AssistantSessionError(self.failure)
        return {"preset": preset, "revision": expected_revision + 1}

    def __init__(self):
        self.calls = []
        self.failure = None


def test_http_is_private_strict_closed_and_has_typed_response():
    owner = PermissionNative()
    app = create_app(native=owner, token="private-test-token")
    path = "/api/assistant/management-permission"
    body = {"preset": "auto_review", "expectedRevision": 0}
    auth = {"Authorization": "Bearer private-test-token"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, json=body, headers={**auth, "Origin": "https://evil.invalid"}).status_code == 403
        assert client.post(path, json=body, headers={**auth, "Host": "evil.invalid"}).status_code == 403
        for patch in ({"preset": "other"}, {"preset": "FULL_ACCESS"}, {"preset": 1},
                      {"expectedRevision": True}, {"expectedRevision": "0"}, {"expectedRevision": 0.0},
                      {"expectedRevision": -1}, {"expectedRevision": 2**53}, {"agentId": "foreign"}):
            result = client.post(path, json={**body, **patch}, headers=auth)
            assert result.status_code == 422
            assert result.json()["detail"]["code"] == "ASSISTANT_PERMISSION_INVALID"
        assert client.post(path + "?preset=full_access", json=body, headers=auth).status_code == 422
        for invalid in ({}, {"preset": "full_access"}, {"expectedRevision": 0}, None, []):
            result = client.post(path, json=invalid, headers=auth)
            assert result.status_code == 422
            assert result.json()["detail"]["code"] == "ASSISTANT_PERMISSION_INVALID"
        assert not owner.calls
        for code, status in (("INVALID", 422), ("CONFLICT", 409), ("UNAVAILABLE", 503)):
            owner.failure = "ASSISTANT_PERMISSION_" + code
            result = client.post(path, json=body, headers=auth)
            assert result.status_code == status
            assert result.json()["detail"]["code"] == owner.failure
        owner.failure = None
        result = client.post(path, json=body, headers=auth)
        assert result.json() == {"preset": "auto_review", "revision": 1}
        assert result.headers["cache-control"] == "no-store"
    route = next(route for route in app.routes if getattr(route, "path", None) == path)
    assert route.response_model is not None


def test_successful_setter_invalidates_snapshot_and_old_inflight_refresh_cannot_restore_it(monkeypatch):
    from core.assistant_runtime import native
    facade = NativeFacade(None)
    facade._identity_snapshot = {"settings": {"managementPermission": {"preset": "request_approval", "revision": 0}}}
    reading = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(native, "identity", lambda: {})
    def settings():
        reading.set()
        assert release.wait(5)
        return {"managementPermission": {"preset": "request_approval", "revision": 0}}
    monkeypatch.setattr(native, "assistant_settings", settings)
    monkeypatch.setattr(native, "assistant_avatar_revision", lambda: None)
    monkeypatch.setattr(native, "set_management_permission", lambda *args: {"preset": args[0], "revision": 1})
    refresh = threading.Thread(target=facade._identity_snapshot_refresh)
    refresh.start()
    assert reading.wait(5)
    try:
        assert facade.set_management_permission("full_access", 0) == {"preset": "full_access", "revision": 1}
    finally:
        release.set()
        refresh.join(5)
    assert not refresh.is_alive()
    assert facade._identity_snapshot is None


def test_failed_setter_keeps_the_validated_identity_snapshot(monkeypatch):
    from core.assistant_runtime import native
    facade = NativeFacade(None)
    previous = {"settings": {"managementPermission": {"preset": "request_approval", "revision": 0}}}
    facade._identity_snapshot = previous
    def unavailable(*args):
        raise native.AssistantSessionError("ASSISTANT_PERMISSION_UNAVAILABLE")
    monkeypatch.setattr(native, "set_management_permission", unavailable)
    with pytest.raises(native.AssistantSessionError):
        facade.set_management_permission("full_access", 0)
    assert facade._identity_snapshot is previous
    assert facade._identity_generation == 0


@pytest.mark.parametrize("setting", ["management_permission", "model"])
def test_cold_identity_read_racing_a_successful_setter_returns_current_snapshot(monkeypatch, setting):
    from concurrent.futures import ThreadPoolExecutor
    from core.assistant_runtime import host, native, operator_assets

    facade = NativeFacade(None)
    reading = threading.Event()
    release = threading.Event()
    current = {"modelId": "m1", "managementPermission": {"preset": "request_approval", "revision": 0}}
    reads = []
    def settings():
        observed = copy.deepcopy(current)
        reads.append(observed)
        if len(reads) == 1:
            reading.set()
            assert release.wait(5)
        return observed
    def set_permission(preset, revision):
        current["managementPermission"] = {"preset": preset, "revision": revision + 1}
        return dict(current["managementPermission"])
    def set_model(model_id):
        current["modelId"] = model_id
        return {"modelId": model_id}
    monkeypatch.setattr(native, "identity", lambda: {"assistant": {"agentId": "a", "directSessionId": "s"}})
    monkeypatch.setattr(native, "assistant_settings", settings)
    monkeypatch.setattr(native, "assistant_avatar_revision", lambda: None)
    monkeypatch.setattr(native, "set_management_permission", set_permission)
    monkeypatch.setattr(native, "set_model", set_model)
    monkeypatch.setattr(operator_assets, "operator_asset_revisions", lambda: {})
    monkeypatch.setattr(host, "_model_image_input_support", lambda agent_id: None)
    monkeypatch.setattr(host, "_operator_profile", lambda: None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(facade.identity)
        assert reading.wait(5)
        try:
            # Slow native reads never own the snapshot publication lock.
            assert facade._snapshot_lock.acquire(blocking=False)
            facade._snapshot_lock.release()
            if setting == "management_permission":
                assert facade.set_management_permission("full_access", 0) == {"preset": "full_access", "revision": 1}
            else:
                assert facade.set_model("m2") == {"modelId": "m2"}
        finally:
            release.set()
        result = pending.result(timeout=5)
    assert result["settings"]["managementPermission"] == current["managementPermission"]
    assert result["settings"]["modelId"] == current["modelId"]
    assert len(reads) == 2


def test_repeated_cold_snapshot_invalidations_return_bounded_structured_unavailable(monkeypatch):
    from core.assistant_runtime import native

    facade = NativeFacade(None)
    reads = []
    def settings():
        reads.append(len(reads))
        facade.set_management_permission("full_access", reads[-1])
        return {"managementPermission": {"preset": "request_approval", "revision": reads[-1]}}
    monkeypatch.setattr(native, "identity", lambda: {"assistant": {"agentId": "a", "directSessionId": "s"}})
    monkeypatch.setattr(native, "assistant_settings", settings)
    monkeypatch.setattr(native, "assistant_avatar_revision", lambda: None)
    monkeypatch.setattr(native, "set_management_permission", lambda preset, revision: {"preset": preset, "revision": revision + 1})
    # This route does not need bootstrap; use the actual identity method and
    # exception handler while invalidating every native refresh generation.
    client = TestClient(create_app(native=facade, token="private-test-token"), base_url="http://127.0.0.1")
    try:
        response = client.get("/api/assistant", headers={"Authorization": "Bearer private-test-token"})
    finally:
        client.close()
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ASSISTANT_NOT_READY"
    assert reads == [0, 1]
    assert facade._identity_snapshot is None


@pytest.mark.parametrize("replacement", ["profile", "direct_session"])
def test_native_permission_write_rechecks_fixed_subject_after_settings_read(personal_env, permissions, monkeypatch, replacement):
    from concurrent.futures import ThreadPoolExecutor
    from core.assistant_runtime import native

    assistant = personal.create_personal_assistant()["assistant"]
    aid, sid = assistant["agentId"], assistant["directSessionId"]
    other = personal_env["owner"]
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_AGENT_ID", aid)
    monkeypatch.setattr(native, "_SESSION_ID", sid)
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_OFFLINE_MIGRATION", False)
    monkeypatch.setattr(native, "_QUIESCING", False)
    original_settings = native.assistant_settings
    def replace_subject():
        if replacement == "profile":
            directory.update_agent_instance(aid, metadata={"personalAssistantProfile": "retired-profile"})
            directory.update_agent_instance(other, role_key=personal.ROLE, primary_mode="general",
                metadata={"personalAssistantProfile": personal.PROFILE})
        else:
            directory.update_agent_instance(aid, direct_session_id="replacement-session")
    with ThreadPoolExecutor(max_workers=1) as pool:
        def settings_then_replace():
            result = original_settings()
            # Generic directory writers do not acquire personal._LOCK. Make
            # the real cross-thread replacement between the two owner reads.
            pool.submit(replace_subject).result(timeout=5)
            return result
        monkeypatch.setattr(native, "assistant_settings", settings_then_replace)
        with pytest.raises(native.AssistantSessionError) as error:
            native.set_management_permission("full_access", 0)
    # The replaced subject trips management_permissions' own fail-closed
    # profile check, which keeps its unavailable code; the identity-projection
    # fold removed from native.set_management_permission is not on this path.
    assert error.value.code == "ASSISTANT_PERMISSION_UNAVAILABLE"
    for agent_id in (aid, other):
        assert permissions.METADATA_KEY not in directory.get_agent(agent_id)["metadata"]


def test_native_setting_allows_busy_and_pending_but_rechecks_identity(tmp_path):
    from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run
    _run(tmp_path, '''
        import copy
        from core.assistant_runtime import native
        from core.infrastructure.native_runtime import assistant_native_root
        from core.web.services import personal_assistant_service as personal, agent_directory_service as directory
        from core.web.services import session_service as sessions
        from core.web.services.session import tool_approvals, journal_bridge
        assistant = native.bootstrap(assistant_native_root())["assistant"]
        aid, sid = assistant["agentId"], assistant["directSessionId"]
        before = directory.get_agent(aid)
        journal = journal_bridge.load_session_conversation_events_snapshot(sid, project_root=sessions.PROJECT_ROOT)
        with sessions._RUNNING_SESSIONS_LOCK:
            sessions._SESSION_ACTIVE_TURN_IDS[sid] = "busy-turn"
        def forbid_idle(*args):
            raise AssertionError("permission update required an idle Session")
        native._assert_session_idle = forbid_idle
        tool_approvals.list_tool_approval_requests = lambda *args: [{"requestId": "pending", "status": "pending"}]
        assert native.set_management_permission("full_access", 0) == {"preset": "full_access", "revision": 1}
        assert native.assistant_settings()["managementPermission"] == {"preset": "full_access", "revision": 1}
        after = directory.get_agent(aid)
        for field in ("permissionPreset", "configHash", "configRevision", "toolPolicy"):
            assert before.get(field) == after.get(field), field
        assert journal_bridge.load_session_conversation_events_snapshot(sid, project_root=sessions.PROJECT_ROOT) == journal
        native._AGENT_ID = "foreign"
        try:
            native.set_management_permission("request_approval", 1)
        except native.AssistantSessionError as exc:
            # Identity break: the rebuild code, distinguishable from a generic
            # permission-infrastructure failure (asserted right below).
            assert exc.code == "ASSISTANT_IDENTITY_INVALID", exc.code
        else:
            raise AssertionError("foreign identity accepted")
        native._AGENT_ID = aid
        from core.web.services.local_assistant import management_permissions
        real_update = management_permissions.update

        def owner_failure(*args, **kwargs):
            raise RuntimeError("PRIVATE_INFRASTRUCTURE_SENTINEL")

        management_permissions.update = owner_failure
        try:
            native.set_management_permission("full_access", 0)
        except native.AssistantSessionError as exc:
            assert exc.code == "ASSISTANT_PERMISSION_UNAVAILABLE", exc.code
        else:
            raise AssertionError("owner failure was admitted")
        management_permissions.update = real_update
        with sessions._RUNNING_SESSIONS_LOCK:
            sessions._SESSION_ACTIVE_TURN_IDS.pop(sid)
        native.shutdown()
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, '''
        from core.assistant_runtime import native
        from core.infrastructure.native_runtime import assistant_native_root
        native.bootstrap(assistant_native_root())
        assert native.assistant_settings()["managementPermission"] == {"preset": "full_access", "revision": 1}
        native.shutdown()
    ''', config_text=TEST_MODEL_CONFIG)
