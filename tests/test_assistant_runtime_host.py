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


def test_dispatch_approval_endpoint_is_private_decline_only_and_bound():
    class Dispatch:
        calls = []
        async def decline_presented_approval(self, dispatch_id, **kwargs):
            self.calls.append((dispatch_id, kwargs))
            return {"dispatchId": dispatch_id, "nativeTaskId": kwargs["task_id"]}
        def list_dispatches(self):
            return []

    dispatch = Dispatch()
    client = TestClient(create_app(native=Native(), token="private-test-token", dispatch=dispatch), base_url="http://127.0.0.1")
    path = "/api/assistant/dispatches/approval/decline"
    body = {"dispatchId": "dispatch-1", "taskId": "task-1", "approvalId": "approval-1", "revision": "fp-1"}
    assert client.post(path, json=body).status_code == 401
    headers = {"Authorization": "Bearer private-test-token"}
    assert client.post(path, json=body, headers={**headers, "Origin": "https://evil.invalid"}).status_code == 403
    assert client.post(path, json={**body, "decision": "accept"}, headers=headers).status_code == 422
    assert client.post(path, json={**body, "dispatchId": "../other"}, headers=headers).status_code == 422
    for revision in ("", " ", "fp-1\n"):
        assert client.post(path, json={**body, "revision": revision}, headers=headers).status_code == 422
    assert client.post(path, json=body, headers=headers).status_code == 200
    assert dispatch.calls == [("dispatch-1", {"task_id": "task-1", "approval_id": "approval-1", "expected_revision": "fp-1"})]


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
    ("", {"displayName": "", "avatarPreset": "default"}),
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
    from tools import pa_assistant_actions

    path = tmp_path / "profile.toml"
    path.write_text('[user_profile]\ndisplay_name = "First"\navatar_preset = "circle"\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(path))
    assistant = {"agentId": "a", "directSessionId": "s", "displayName": "Assistant"}
    monkeypatch.setattr(native, "identity", lambda: {"assistant": dict(assistant)})
    monkeypatch.setattr(pa_assistant_actions, "execute", lambda *args, **kwargs: {"ok": True})
    facade = host.NativeFacade(None)
    assert facade.identity()["operatorProfile"] == {"displayName": "First", "avatarPreset": "circle"}
    path.write_text('[user_profile]\ndisplay_name = "Second"\navatar_preset = "codex"\n', encoding="utf-8")
    result = facade.identity()
    assert result["assistant"] == assistant
    assert result["operatorProfile"] == {"displayName": "Second", "avatarPreset": "codex"}
    assert result["operatorAssetsVersion"] == 1
    def unavailable(*args):
        raise ValueError("PRIVATE_PATH_OR_CONFIG_SENTINEL")
    monkeypatch.setattr(public_config, "read_existing_config_snapshot", unavailable)
    assert facade.identity() == {"assistant": assistant, "settings": {"ok": True}, "operatorAssetsVersion": 1, "attachmentVersion": 1}
