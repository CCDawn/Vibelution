"""Independent host boundary: a browser or stale Launcher cannot drive it."""

from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from core.assistant_runtime.host import create_app


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


class Native:
    assistant: ClassVar = {"agentId": "local-assistant", "directSessionId": "native-session"}

    def bootstrap(self):
        return {"assistant": self.assistant}

    def get_detail(self):
        return {"sessionId": "native-session", "messages": []}

    def submit(self, message, request_id):
        return {"sessionId": "native-session", "acceptedRequestId": request_id}

    def stop(self, turn_id):
        return {"id": "native-session", "activeTurnId": turn_id, "stopRequested": True}

    def continue_turn(self, request_id, continuation):
        return {"turnId": "continued-turn", "clientSubmissionId": request_id}

    def shutdown(self):
        pass

    def approvals(self):
        return [{"sessionId": "native-session", "requestId": "native-approval", "status": "pending"}]

    def resolve_approval(self, request_id, decision):
        from core.web.services.session.tool_approvals import ToolApprovalNotFoundError
        if request_id != "native-approval":
            raise ToolApprovalNotFoundError("private approval identity")
        return {"sessionId": "native-session", "requestId": request_id, "decision": decision}


def test_host_denies_missing_credentials_origins_and_wrong_host():
    app = create_app(native=Native(), token="private-test-token")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/assistant").status_code == 401
        headers = {"Authorization": "Bearer private-test-token"}
        assert client.get("/api/assistant", headers=headers).status_code == 200
        assert client.get("/api/assistant", headers={**headers, "Origin": "https://evil.invalid"}).status_code == 403
        assert client.get("/api/assistant", headers={**headers, "Host": "evil.invalid"}).status_code == 403
        assert client.get("/api/control-token", headers=headers).status_code == 404
        assert client.get("/docs", headers=headers).status_code == 404


@pytest.mark.parametrize("result", [{"schemaVersion": 1, "state": "idle"}, {"schemaVersion": 1, "state": "active"},
                                   {"schemaVersion": 1, "state": "unknown"}, {"schemaVersion": True, "state": "idle"},
                                   {"schemaVersion": 1, "state": "idle", "extra": "private"}, None])
def test_lifecycle_status_is_private_closed_and_never_assumes_idle(result):
    class Owner(Native):
        def lifecycle_status(self):
            return result
    with TestClient(create_app(native=Owner(), token="private-test-token"), base_url="http://127.0.0.1") as client:
        path = "/api/assistant/lifecycle-status"
        headers = {"Authorization": "Bearer private-test-token"}
        assert client.get(path).status_code == 401
        assert client.get(path, headers={**headers, "Origin": "https://evil.invalid"}).status_code == 403
        assert client.get(path + "?sessionId=other", headers=headers).status_code == 422
        valid = type(result) is dict and set(result) == {"schemaVersion", "state"} and type(result["schemaVersion"]) is int
        assert client.get(path, headers=headers).json() == (result if valid else {"schemaVersion": 1, "state": "unknown"})


def test_shutdown_commits_native_admission_before_releasing_the_joint_barrier(tmp_path):
    import time
    from contextlib import contextmanager
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter
    order = []
    class Owner(Native):
        held = False

        @contextmanager
        def session_quiescence(self):
            self.held = True
            order.append("held")
            try:
                yield
            finally:
                self.held = False
                order.append("released")

        def commit_quiescent_shutdown(self):
            assert self.held
            order.append("committed")

        def shutdown(self):
            return {"closed": True}

    owner = Owner()
    service = adapter(tmp_path, ClientProbe())
    app = create_app(native=owner, token="private-test-token", dispatch=service, on_shutdown=lambda: order.append("shutdown"))
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.post("/api/assistant/migration-barrier/prepare").status_code == 200
        for _ in range(100):
            state = client.get("/api/assistant/migration-barrier/status").json()["state"]
            if state != "probing":
                break
            time.sleep(0.01)
        assert state == "ready"
        assert client.post("/api/assistant/shutdown").status_code == 200
        assert order.index("held") < order.index("committed") < order.index("released") < order.index("shutdown")


def test_dispatch_approval_endpoint_is_private_and_bound():
    class Dispatch:
        calls = []
        async def preview_bound_approval(self, dispatch_id, **kwargs):
            self.calls.append((dispatch_id, kwargs))
            return {"taskId": kwargs["task_id"]}
        async def decide_bound_approval(self, dispatch_id, **kwargs):
            self.calls.append((dispatch_id, kwargs))
            return {"dispatchId": dispatch_id, "taskId": kwargs["task_id"]}
        async def decline_presented_approval(self, dispatch_id, **kwargs):
            self.calls.append((dispatch_id, kwargs))
            return {"dispatchId": dispatch_id, "nativeTaskId": kwargs["task_id"]}
        def list_dispatches(self):
            return []

    dispatch = Dispatch()
    client = TestClient(create_app(native=Native(), token="private-test-token", dispatch=dispatch), base_url="http://127.0.0.1")
    path = "/api/assistant/dispatches/approval/decision"
    body = {"dispatchId": "dispatch-1", "taskId": "task-1", "approvalId": "approval-1", "revision": "a" * 64, "decision": "accept"}
    assert client.post(path, json=body).status_code == 401
    headers = {"Authorization": "Bearer private-test-token"}
    assert client.post(path, json=body, headers={**headers, "Origin": "https://evil.invalid"}).status_code == 403
    assert client.post(path, json={**body, "decision": "acceptAlways"}, headers=headers).status_code == 422
    assert client.post(path, json={**body, "dispatchId": "../other"}, headers=headers).status_code == 422
    for revision in ("", " ", "a" * 64 + "\n"):
        assert client.post(path, json={**body, "revision": revision}, headers=headers).status_code == 422
    preview_body = {key: body[key] for key in ("dispatchId", "taskId", "approvalId")}
    preview = client.post("/api/assistant/dispatches/approval/preview", json=preview_body, headers=headers)
    assert preview.status_code == 200 and preview.headers["cache-control"] == "no-store"
    assert client.post(path, json=body, headers=headers).status_code == 200
    assert dispatch.calls == [("dispatch-1", {"task_id": "task-1", "approval_id": "approval-1"}),
        ("dispatch-1", {"task_id": "task-1", "approval_id": "approval-1", "revision": "a" * 64, "decision": "accept"})]
    fallback = "/api/assistant/dispatches/approval/decline"
    decline_body = {**preview_body, "revision": "policy-1"}
    assert client.post(fallback, json={**decline_body, "decision": "accept"}, headers=headers).status_code == 422
    assert client.post(fallback, json={**decline_body, "revision": ""}, headers=headers).status_code == 422
    assert client.post(fallback, json=decline_body, headers=headers).status_code == 200
    assert dispatch.calls[-1] == ("dispatch-1", {"task_id": "task-1", "approval_id": "approval-1", "expected_revision": "policy-1"})


def test_host_limits_messages_to_own_native_session_and_reuses_request_id():
    app = create_app(native=Native(), token="private-test-token")
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.get("/api/assistant/session").json()["sessionId"] == "native-session"
        body = {"message": "你好", "requestId": "message-1"}
        result = client.post("/api/assistant/messages", json=body)
        assert result.status_code == 200
        assert result.json()["acceptedRequestId"] == "message-1"
        assert client.post("/api/assistant/messages", json={**body, "sessionId": "other-session"}).status_code == 422
        assert client.post("/api/assistant/messages", json={"message": "hello"}).status_code == 422
        assert client.get("/api/sessions/other-session").status_code == 404


def test_host_attachment_transport_uses_fixed_native_owner():
    class AttachmentNative(Native):
        def upload_attachment(self, payload, filename, content_type):
            assert payload == b"fixture" and filename == "note.txt"
            return {"artifactId": "file-1", "filename": filename, "contentType": content_type,
                    "sizeBytes": len(payload), "kind": "user_document", "status": "ready"}

        def read_attachment(self, artifact_id):
            assert artifact_id == "file-1"
            return b"fixture", "text/plain"

        def submit(self, message, request_id, attachment_ids=None):
            return {"acceptedRequestId": request_id, "attachmentIds": attachment_ids}

    app = create_app(native=AttachmentNative(), token="private-test-token")
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        body = {"filename": "note.txt", "contentType": "text/plain", "dataBase64": "Zml4dHVyZQ=="}
        assert client.post("/api/assistant/attachments/upload", json=body).json()["artifactId"] == "file-1"
        assert client.post("/api/assistant/attachments/read", json={"artifactId": "file-1"}).json() == {
            "contentType": "text/plain", "dataBase64": "Zml4dHVyZQ=="}
        result = client.post("/api/assistant/messages", json={"message": "", "requestId": "one", "attachmentIds": ["file-1"]})
        assert result.json() == {"acceptedRequestId": "one", "attachmentIds": ["file-1"]}
        assert client.post("/api/assistant/attachments/upload", json={**body, "sessionId": "other"}).status_code == 422
        assert client.post("/api/assistant/attachments/upload", json={**body, "dataBase64": "!!!!"}).status_code == 422
        assert client.post("/api/assistant/attachments/read", json={"artifactId": "../file"}).status_code == 422


def test_health_does_not_disclose_token_or_project_paths():
    app = create_app(native=Native(), token="private-test-token")
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        result = client.get("/health").json()
        assert result == {"status": "ok", "role": "launcher_assistant", "protocolVersion": 1}
        assert "private-test-token" not in str(result)


def test_project_suspension_is_private_closed_and_preserves_local_session(tmp_path):
    from core.assistant_runtime.dispatch import DispatchService
    root = tmp_path / "project"
    root.mkdir()
    service = DispatchService(tmp_path / "profile", {})
    snapshot = {"schemaVersion": 1, "revision": 4, "projects": {"p": str(root)}}
    service.replace_projects(snapshot)
    with TestClient(create_app(native=Native(), token="private-test-token", dispatch=service),
                    base_url="http://127.0.0.1") as client:
        path = "/api/assistant/project-registry/suspend"
        assert client.post(path, json={}).status_code == 401
        client.headers["Authorization"] = "Bearer private-test-token"
        assert client.post(path, json={}, headers={"Origin": "http://127.0.0.1"}).status_code == 403
        for invalid in ({"projectsSuspended": False}, {"revision": 4}, [], None):
            assert client.post(path, json=invalid).status_code == 422
        assert client.post(path + "?resume=true", json={}).status_code == 422
        assert client.post(path, json={}).json() == {"schemaVersion": 1, "revision": 4, "projectsSuspended": True}
        assert client.get("/api/assistant/session").json()["sessionId"] == "native-session"
        assert client.post("/api/assistant/messages", json={"message": "local chat", "requestId": "local"}).status_code == 200
        assert client.get("/api/assistant/dispatches").json() == {"dispatches": []}
        assert client.put("/api/assistant/project-registry", json=snapshot).status_code == 200
    assert service.project_ids() == ("p",)


def test_ready_publication_failure_drains_native_owner():
    class Owner(Native):
        stopped = False

        def shutdown(self):
            self.stopped = True

    owner = Owner()
    def fail_ready():
        raise OSError("ready publication failed")
    with pytest.raises(OSError), TestClient(create_app(native=owner, token="private-test-token", on_ready=fail_ready)):
        pass
    assert owner.stopped


@pytest.mark.parametrize("construct_fails", [False, True])
def test_cancelled_startup_waits_for_patrol_constructor_and_releases_owner(tmp_path, monkeypatch, construct_fails):
    import asyncio
    import threading
    from core.assistant_runtime import host, patrol, reminders, legacy_reminder_receipts

    entered, release = threading.Event(), threading.Event()
    closed = []

    class FakePatrol:
        def __init__(self, *args):
            entered.set()
            assert release.wait(10)
            if construct_fails:
                raise RuntimeError("construction failed")

        def close(self):
            closed.append("patrol")

    class Store:
        def __init__(self, *args):
            pass

        def close(self):
            pass

    class Owner(host.NativeFacade):
        def bootstrap(self):
            self.assistant = Native.assistant
            return {"assistant": self.assistant}

        def shutdown(self):
            closed.append("native")
            return {"closed": True}

    monkeypatch.setattr(patrol, "LauncherPatrol", FakePatrol)
    monkeypatch.setattr(reminders, "LauncherReminders", Store)
    monkeypatch.setattr(legacy_reminder_receipts, "LegacyReminderReceipts", Store)
    app = create_app(native=Owner(tmp_path), token="private-test-token", dispatch=object())

    async def run():
        context = app.router.lifespan_context(app)
        starting = asyncio.create_task(context.__aenter__())
        assert await asyncio.to_thread(entered.wait, 10)
        starting.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await starting

    asyncio.run(run())
    assert closed == (["native"] if construct_fails else ["patrol", "native"])


def test_startup_recovery_can_use_the_bound_action_owner():
    from core.assistant_runtime.actions import execute_action
    class Dispatch:
        def project_ids(self):
            return ("authorized-project",)
        async def available_projects(self, **kwargs):
            return {"projects": [{"projectId": "authorized-project"}]}
        async def heartbeat(self):
            pass
    class Recovering(Native):
        def bootstrap(self):
            assert execute_action("projects", {}) == {"projects": [{"projectId": "authorized-project"}]}
            return super().bootstrap()
    with TestClient(create_app(native=Recovering(), token="private-test-token", dispatch=Dispatch())):
        pass


def test_approval_transport_has_one_native_session_and_single_call_decisions():
    app = create_app(native=Native(), token="private-test-token")
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.get("/api/assistant/approvals").json()[0]["sessionId"] == "native-session"
        payload = {"requestId": "native-approval", "decision": "accept"}
        assert client.post("/api/assistant/approvals/decision", json=payload).json()["decision"] == "accept"
        assert client.post("/api/assistant/approvals/decision", json={**payload, "sessionId": "other"}).status_code == 422
        assert client.post("/api/assistant/approvals/decision", json={**payload, "decision": "acceptAlways"}).status_code == 422
        missing = client.post("/api/assistant/approvals/decision", json={**payload, "requestId": "other-approval"})
        assert missing.status_code == 404 and "private" not in missing.text


CONTINUATION = {"turnId": "old-turn", "headId": "old-head", "ledgerSeq": 3, "agentId": "local-assistant"}


def test_fixed_session_stop_and_continue_forward_once_without_renderer_session_selection():
    calls = []

    class Owner(Native):
        def stop(self, turn_id):
            calls.append(("stop", turn_id))
            return super().stop(turn_id)

        def continue_turn(self, request_id, continuation):
            calls.append(("continue", request_id, continuation))
            return super().continue_turn(request_id, continuation)

    with TestClient(create_app(native=Owner(), token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        result = client.post("/api/assistant/stop", json={"turnId": "old-turn"})
        assert result.status_code == 202 and result.json()["stopRequested"] is True
        result = client.post("/api/assistant/continue", json={"requestId": "continue-1", "continuation": CONTINUATION})
        assert result.status_code == 202 and result.json()["turnId"] == "continued-turn"
    assert calls == [("stop", "old-turn"), ("continue", "continue-1", CONTINUATION)]


@pytest.mark.parametrize("path,payload", [
    ("stop", {}), ("stop", {"turnId": " "}), ("stop", {"turnId": 1}),
    ("stop", {"turnId": "x", "sessionId": "other"}),
    ("continue", {"requestId": "c", "continuation": CONTINUATION, "message": "custom"}),
    ("continue", {"requestId": "c", "continuation": CONTINUATION, "sessionId": "other"}),
    ("continue", {"requestId": "c"}), ("continue", {"requestId": "", "continuation": CONTINUATION}),
    ("continue", {"requestId": "c", "continuation": {**CONTINUATION, "ledgerSeq": True}}),
    ("continue", {"requestId": "c", "continuation": {**CONTINUATION, "ledgerSeq": "3"}}),
    ("continue", {"requestId": "c", "continuation": {**CONTINUATION, "headId": " "}}),
    ("continue", {"requestId": "c", "continuation": {**CONTINUATION, "sessionId": "other"}}),
    ("continue", {"requestId": "c", "continuation": {key: value for key, value in CONTINUATION.items() if key != "agentId"}}),
])
def test_session_commands_reject_invalid_payload_before_native_call(path, payload):
    class Owner(Native):
        def stop(self, *args):
            pytest.fail("invalid stop reached native owner")

        def continue_turn(self, *args):
            pytest.fail("invalid continuation reached native owner")

    with TestClient(create_app(native=Owner(), token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.post(f"/api/assistant/{path}", json=payload).status_code == 422


@pytest.mark.parametrize("code,status", [
    ("ASSISTANT_NOT_READY", 503), ("ASSISTANT_STOPPING", 503),
    ("ASSISTANT_IDENTITY_INVALID", 409), ("SESSION_NOT_FOUND", 404),
    ("SESSION_CONFLICT", 409), ("SESSION_INVALID", 422),
])
@pytest.mark.parametrize("path", ["stop", "continue"])
def test_session_command_errors_have_bounded_codes(code, status, path):
    from core.assistant_runtime.native import AssistantSessionError

    class Owner(Native):
        def stop(self, *args):
            raise AssistantSessionError(code)

        def continue_turn(self, *args):
            raise AssistantSessionError(code)

    payload = {"turnId": "old-turn"} if path == "stop" else {"requestId": "c", "continuation": CONTINUATION}
    with TestClient(create_app(native=Owner(), token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        response = client.post(f"/api/assistant/{path}", json=payload)
        assert response.status_code == status
        assert response.json()["detail"]["code"] == code


def test_native_facade_forwards_commands_to_fixed_native_owner(monkeypatch):
    from core.assistant_runtime import native
    from core.assistant_runtime.host import NativeFacade

    calls = []
    monkeypatch.setattr(native, "stop", lambda turn: calls.append(("stop", turn)) or {"stopRequested": True})
    monkeypatch.setattr(native, "continue_turn", lambda request, expected: calls.append(("continue", request, expected)) or {"turnId": "new"})
    facade = NativeFacade(None)
    assert facade.stop("old")["stopRequested"]
    assert facade.continue_turn("c", CONTINUATION)["turnId"] == "new"
    assert calls == [("stop", "old"), ("continue", "c", CONTINUATION)]


def test_main_only_project_snapshot_updates_same_owner_and_rejects_browser_origin(tmp_path):
    from core.assistant_runtime.dispatch import DispatchService
    class Owner(Native):
        boots = 0
        def bootstrap(self):
            self.boots += 1
            return super().bootstrap()
    native = Owner()
    service = DispatchService(tmp_path / "profile", {"p:old": tmp_path / "project"})
    with TestClient(create_app(native=native, token="private-test-token", dispatch=service), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        payload = {"schemaVersion": 1, "revision": 4, "projects": {"p:new": str(tmp_path / "project")}}
        assert client.put("/api/assistant/project-registry", json=payload, headers={"Origin": "http://127.0.0.1"}).status_code == 403
        assert service.project_ids() == ("p:old",)
        response = client.put("/api/assistant/project-registry", json=payload)
        assert response.json() == {"schemaVersion": 1, "revision": 4, "projectCount": 1}
        assert service.project_ids() == ("p:new",) and native.boots == 1
        assert client.put("/api/assistant/project-registry", json={**payload, "projects": {}}).status_code == 409
        assert client.put("/api/assistant/project-registry", json={**payload, "root": "forged"}).status_code == 422


@pytest.mark.parametrize(("document", "expected"), [
    ("", {"displayName": "ENV_NAME_SENTINEL", "avatarPreset": "default"}),
    ('[user_profile]\ndisplay_name = "   "\n', {"displayName": "ENV_NAME_SENTINEL", "avatarPreset": "default"}),
    ('[user_profile]\ndisplay_name = "' + "🙂" * 120 + '"\navatar_preset = "initial"\n',
     {"displayName": "🙂" * 120, "avatarPreset": "initial"}),
    ('[user_profile]\ndisplay_name = "Temp operator"\navatar_preset = "spark"\nbio = "BIO_SENTINEL"\npreferences = ["PREFERENCE_SENTINEL"]\navatar_image_path = "PATH_SENTINEL"\n[llm]\nsecret = "SECRET_SENTINEL"\n',
     {"displayName": "Temp operator", "avatarPreset": "spark"}),
    ('[user_profile]\ndisplay_name = 42\n', None),
    ('[user_profile]\ndisplay_name = "' + "x" * 121 + '"\n', None),
    ('[user_profile]\ndisplay_name = "line\\nfeed"\n', None),
    ('[user_profile]\navatar_preset = "SPARK"\n', None),
    ('[user_profile]\navatar_preset = false\n', None),
    ('user_profile = []\n', None),
    ('invalid TOML [', None),
])
def test_operator_profile_is_a_read_only_two_field_projection(tmp_path, monkeypatch, document, expected):
    from config import public_config
    from core.assistant_runtime.host import _operator_profile

    path = tmp_path / "existing.toml"
    path.write_text(document, encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(path))
    monkeypatch.setenv("VIBELUTION_USER_NAME", "ENV_NAME_SENTINEL")
    def forbidden(*args, **kwargs):
        raise AssertionError("profile read must not initialize, normalize or cache configuration")
    for name in ("load_public_config", "get_public_config_snapshot", "ensure_global_config_initialized",
                 "upgrade_legacy_capability_cache_if_needed"):
        monkeypatch.setattr(public_config, name, forbidden)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert _operator_profile() == expected
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_operator_profile_missing_file_is_not_initialized(tmp_path, monkeypatch):
    from core.assistant_runtime.host import _operator_profile

    missing = tmp_path / "missing" / "config.toml"
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(missing))
    assert _operator_profile() is None
    assert not missing.parent.exists()


def test_native_status_rereads_operator_profile_and_keeps_identity_on_read_failure(tmp_path, monkeypatch):
    from core.assistant_runtime import native, host
    from config import public_config

    path = tmp_path / "profile.toml"
    path.write_text('[user_profile]\ndisplay_name = "First"\navatar_preset = "circle"\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(path))
    assistant = {"agentId": "a", "directSessionId": "s", "displayName": "Assistant"}
    monkeypatch.setattr(native, "identity", lambda: {"assistant": dict(assistant)})
    monkeypatch.setattr(native, "assistant_settings", lambda: {"ok": True})
    monkeypatch.setattr(host, "_model_image_input_support", lambda agent_id: True if agent_id == "a" else None)
    facade = host.NativeFacade(None)
    assert facade.identity()["operatorProfile"] == {"displayName": "First", "avatarPreset": "circle"}
    path.write_text('[user_profile]\ndisplay_name = "Second"\navatar_preset = "codex"\n', encoding="utf-8")
    result = facade.identity()
    assert result["assistant"] == assistant
    assert result["operatorProfile"] == {"displayName": "Second", "avatarPreset": "codex"}
    assert result["settings"] == {"ok": True, "supportsImageInput": True}
    assert result["operatorAssetsVersion"] == 1
    assert result["assistantAvatarVersion"] == 1
    assert result["assistantAvatarRevision"] is None
    def unavailable(*args):
        raise ValueError("PRIVATE_PATH_OR_CONFIG_SENTINEL")
    monkeypatch.setattr(public_config, "read_existing_config_snapshot", unavailable)
    assert facade.identity() == {"assistant": assistant, "settings": {"ok": True, "supportsImageInput": True},
                                 "operatorAssetsVersion": 1,
                                 "operatorAssetRevisions": {"avatar": None, "background": None}, "attachmentVersion": 1,
                                 "assistantAvatarVersion": 1, "assistantAvatarRevision": None}


def test_model_image_input_support_degrades_to_unknown_without_touching_services(monkeypatch):
    from core.assistant_runtime import host
    from core.web.services import agent_directory_service, session_service

    def forbidden(*args, **kwargs):
        raise AssertionError("capability read must not initialize owners")
    monkeypatch.setattr(agent_directory_service, "get_agent_parameter_snapshot", forbidden)
    assert host._model_image_input_support("") is None
    assert host._model_image_input_support(None) is None  # type: ignore[arg-type]

    monkeypatch.setattr(agent_directory_service, "get_agent_parameter_snapshot",
                        lambda agent_id, *, include_archived: {"agentId": agent_id})
    monkeypatch.setattr(session_service, "_resolve_image_attachment_capability",
                        lambda *, agent_instance: {"supports_image_input": False, "model_id": "m"})
    assert host._model_image_input_support("a") is False
    monkeypatch.setattr(session_service, "_resolve_image_attachment_capability",
                        lambda *, agent_instance: {"supports_image_input": "unknown", "model_id": "m"})
    assert host._model_image_input_support("a") is None

    def broken_snapshot(*args, **kwargs):
        raise RuntimeError("SERVICE_UNAVAILABLE_SENTINEL")
    monkeypatch.setattr(agent_directory_service, "get_agent_parameter_snapshot", broken_snapshot)
    assert host._model_image_input_support("a") is None


def test_model_route_is_private_closed_and_preserves_bounded_failures():
    from core.assistant_runtime.native import AssistantSessionError

    calls = []
    class Owner(Native):
        def set_model(self, model_id):
            calls.append(model_id)
            if model_id == "busy":
                raise AssistantSessionError("ASSISTANT_MODEL_BUSY")
            if model_id == "unknown":
                raise AssistantSessionError("ASSISTANT_MODEL_INVALID")
            return {"modelId": model_id}
    with TestClient(create_app(native=Owner(), token="private-test-token"), base_url="http://127.0.0.1") as client:
        path = "/api/assistant/model"
        auth = {"Authorization": "Bearer private-test-token"}
        assert client.post(path, json={"modelId": "local/other"}).status_code == 401
        assert client.post(path, json={"modelId": "local/other"}, headers={**auth, "Origin": "https://evil.invalid"}).status_code == 403
        for body in ({"modelId": ""}, {"modelId": 1}, {"modelId": "local/other\n"},
                     {"modelId": "local/other", "agentId": "foreign"},
                     {"modelId": "local/other", "sessionId": "foreign"}):
            assert client.post(path, json=body, headers=auth).status_code == 422
        assert client.post(path + "?agentId=foreign", json={"modelId": "local/other"}, headers=auth).status_code == 422
        assert not calls
        assert client.post(path, json={"modelId": "busy"}, headers=auth).status_code == 409
        assert client.post(path, json={"modelId": "unknown"}, headers=auth).status_code == 422
        assert client.post(path, json={"modelId": "local/other"}, headers=auth).json() == {"modelId": "local/other"}


def test_host_history_cursor_is_bounded_and_stays_on_the_owned_session():
    class PagedNative(Native):
        def get_detail(self, before_message_index=None):
            return {"id": "native-session", "messages": [], "before": before_message_index}

    with TestClient(create_app(native=PagedNative(), token="private-test-token"), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": "Bearer private-test-token"}
        response = client.get("/api/assistant/session?before_message_index=61", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"id": "native-session", "messages": [], "before": 61}
        for invalid in ("0", "-1", "1.5", "2147483648"):
            assert client.get(f"/api/assistant/session?before_message_index={invalid}", headers=headers).status_code == 422
