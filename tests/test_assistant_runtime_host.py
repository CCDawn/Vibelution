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

    def submit(self, message, request_id, attachment_ids=None, references=None):
        return {"sessionId": "native-session", "acceptedRequestId": request_id,
                "references": list(references or [])}

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


class QueuedNative(Native):
    def __init__(self):
        self.calls = []
        self.rows = [{"id": "queued-one", "content": "next", "status": "paused", "kind": "user",
                      "attachments": [{"artifactId": "native-file"}], "references": [], "nativeExtra": {"kept": True}}]

    def update_queued_turn(self, queued_turn_id, **kwargs):
        self.calls.append(("update", queued_turn_id, kwargs))
        return {"queuedTurns": self.rows}

    def remove_queued_turn(self, queued_turn_id):
        self.calls.append(("remove", queued_turn_id))
        return {"queuedTurns": self.rows}

    def send_now_queued_turn(self, queued_turn_id, **kwargs):
        self.calls.append(("send-now", queued_turn_id, kwargs))
        return {"queuedTurns": self.rows, "stopRequested": True}


def test_host_queue_commands_forward_only_to_the_fixed_native_owner_and_advertise_support():
    native = QueuedNative()
    with TestClient(create_app(native=native, token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.get("/api/assistant").json()["followupQueueVersion"] == 1
        result = client.post("/api/assistant/queued-turns/update", json={"queuedTurnId": "queued-one",
                             "content": "edited", "position": 2, "status": "paused"})
        assert result.status_code == 200 and result.json() == {"queuedTurns": native.rows}
        result = client.post("/api/assistant/queued-turns/remove", json={"queuedTurnId": "queued-one"})
        assert result.status_code == 200 and result.json() == {"queuedTurns": native.rows}
        result = client.post("/api/assistant/queued-turns/send-now", json={"queuedTurnId": "queued-one",
                                                                                    "expectedTurnId": "observed-turn"})
        assert result.status_code == 202 and result.json() == {"queuedTurns": native.rows, "stopRequested": True}
        client.post("/api/assistant/queued-turns/send-now", json={"queuedTurnId": "queued-one"})
    assert native.calls[:3] == [("update", "queued-one", {"content": "edited", "position": 2, "status": "paused"}),
                                ("remove", "queued-one"),
                                ("send-now", "queued-one", {"expected_turn_id": "observed-turn"})]
    assert native.calls[3][:2] == ("send-now", "queued-one")
    assert native.calls[3][2]["expected_turn_id"].startswith("assistant-idle-")


def test_host_does_not_advertise_queue_writes_when_any_native_operation_is_missing():
    native = QueuedNative()
    native.send_now_queued_turn = None
    with TestClient(create_app(native=native, token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        assert "followupQueueVersion" not in client.get("/api/assistant").json()


@pytest.mark.parametrize("path", ["update", "remove", "send-now"])
def test_host_queue_commands_keep_private_authority_and_reject_extra_identity(path):
    native = QueuedNative()
    body = {"queuedTurnId": "queued-one"}
    url = f"/api/assistant/queued-turns/{path}"
    headers = {"Authorization": "Bearer private-test-token"}
    with TestClient(create_app(native=native, token="private-test-token"), base_url="http://127.0.0.1") as client:
        assert client.post(url, json=body).status_code == 401
        assert client.post(url, json=body, headers={**headers, "Origin": "https://evil.invalid"}).status_code == 403
        for identity in ["sessionId", "agentId", "projectRoot", "scope", "url"]:
            assert client.post(url, json={**body, identity: "foreign"}, headers=headers).status_code == 422
        assert client.post(url + "?sessionId=foreign", json=body, headers=headers).status_code == 422
        for invalid in [None, "", "../foreign", "queued-one\n", "q" * 161, 7]:
            assert client.post(url, json={"queuedTurnId": invalid}, headers=headers).status_code == 422
    assert not native.calls


@pytest.mark.parametrize("path,fields", [
    ("update", {"content": None}), ("update", {"content": 3}), ("update", {"content": "x" * 64001}),
    ("update", {"position": True}), ("update", {"position": "1"}), ("update", {"position": 0}),
    ("update", {"position": 1.5}), ("update", {"position": 2**53}), ("update", {"position": None}),
    ("update", {"status": "starting"}), ("update", {"status": None}),
    ("send-now", {"expectedTurnId": None}), ("send-now", {"expectedTurnId": ""}),
    ("send-now", {"expectedTurnId": 3}), ("send-now", {"expectedTurnId": "../foreign"}),
    ("send-now", {"expectedTurnId": "turn\n"}), ("send-now", {"expectedTurnId": "t" * 161}),
    ("remove", {"content": "injected"}), ("send-now", {"status": "queued"}),
])
def test_host_queue_field_validation_happens_before_native_calls(path, fields):
    native = QueuedNative()
    with TestClient(create_app(native=native, token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        result = client.post(f"/api/assistant/queued-turns/{path}", json={"queuedTurnId": "queued-one", **fields})
        assert result.status_code == 422
    assert not native.calls


def test_queue_native_conflict_is_bounded_without_leaking_private_error():
    from core.assistant_runtime.native import AssistantSessionError

    class ConflictNative(QueuedNative):
        def send_now_queued_turn(self, *args, **kwargs):
            raise AssistantSessionError("SESSION_CONFLICT")

    with TestClient(create_app(native=ConflictNative(), token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        result = client.post("/api/assistant/queued-turns/send-now", json={"queuedTurnId": "queued-one"})
        assert result.status_code == 409 and result.json()["detail"]["code"] == "SESSION_CONFLICT"


def test_idle_send_now_has_no_turn_scoped_cancellation_or_history_stop_boundary():
    class Owner(QueuedNative):
        def get_detail(self):
            return {"id": "native-session", "activeTurnId": None}

    class HistoryControl:
        def stop_native_turn(self, *args, **kwargs):
            pytest.fail("idle send-now has no exact Turn to stop in the history boundary")

        def close(self):
            pass

    class MainControl:
        appearance_enabled = True
        initial_migration_enabled = True

        def begin_initial_fence(self, *args):
            pytest.fail("idle send-now must not fence an unspecified Turn")

        def cancel_image_imports(self, *args):
            pytest.fail("idle send-now must not cancel unrelated image waiters")

        def cancel_history_imports(self, *args):
            pytest.fail("idle send-now must not cancel unrelated history waiters")

        def close(self):
            pass

    native = Owner()
    with TestClient(create_app(native=native, token="private-test-token", main_control=MainControl(),
                              history_control=HistoryControl()), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        for _ in range(2):
            result = client.post("/api/assistant/queued-turns/send-now", json={"queuedTurnId": "queued-one"})
            assert result.status_code == 202 and result.json()["stopRequested"] is True
    fences = []
    for operation, queued_turn_id, kwargs in native.calls:
        assert operation == "send-now" and queued_turn_id == "queued-one"
        fence = kwargs["expected_turn_id"]
        assert fence.startswith("assistant-idle-")
        suffix = fence.removeprefix("assistant-idle-")
        assert len(suffix) == 32 and all(ch in "0123456789abcdef" for ch in suffix)
        fences.append(fence)
    assert len(fences) == 2 and fences[0] != fences[1]


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

        def submit(self, message, request_id, attachment_ids=None, references=None):
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


def test_host_forwards_control_continuation_only_with_fixed_message_and_snapshot():
    from core.assistant_runtime.control_continuation import CONTROL_CONTINUATION_MESSAGE

    calls = []
    class ControlNative(Native):
        def submit(self, message, request_id, **kwargs):
            calls.append((message, request_id, kwargs))
            return {"acceptedRequestId": request_id}

    expected = {**CONTINUATION, "sessionId": "native-session"}
    body = {"message": CONTROL_CONTINUATION_MESSAGE, "requestId": "control-1", "controlContinuation": expected}
    with TestClient(create_app(native=ControlNative(), token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        response = client.post("/api/assistant/messages", json=body)
        assert response.status_code == 200 and response.json()["acceptedRequestId"] == "control-1"
        for changes in [
            {"message": "continue freely"}, {"attachmentIds": ["file-1"]}, {"references": [{"messageId": "m"}]},
            {"controlContinuation": None}, {"controlContinuation": {**expected, "ledgerSeq": True}},
            {"controlContinuation": {**expected, "ledgerSeq": "3"}},
            {"controlContinuation": {**expected, "sessionId": " "}},
            {"controlContinuation": {**expected, "headId": " head "}},
            {"controlContinuation": {**expected, "extra": True}},
            {"controlContinuation": {key: value for key, value in expected.items() if key != "sessionId"}},
        ]:
            assert client.post("/api/assistant/messages", json={**body, **changes}).status_code == 422
    assert calls == [(CONTROL_CONTINUATION_MESSAGE, "control-1", {"control_continuation": expected})]


def test_fixed_session_stop_and_continue_forward_once_without_renderer_session_selection():
    calls = []

    class Owner(Native):
        def stop(self, turn_id):
            calls.append(("stop", turn_id))
            return super().stop(turn_id)

        def continue_turn(self, request_id, continuation):
            calls.append(("continue", request_id, continuation))
            return super().continue_turn(request_id, continuation)

        def switch_head(self, node_id):
            calls.append(("head", node_id))
            return {"id": "native-session", "messages": []}

        def regenerate(self, message_id, request_id):
            calls.append(("regenerate", message_id, request_id))
            return {"id": "native-session", "messages": []}

        def guidance(self, content, mode):
            calls.append(("guidance", content, mode))
            return {"id": "native-session"}

    with TestClient(create_app(native=Owner(), token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        result = client.post("/api/assistant/stop", json={"turnId": "old-turn"})
        assert result.status_code == 202 and result.json()["stopRequested"] is True
        result = client.post("/api/assistant/continue", json={"requestId": "continue-1", "continuation": CONTINUATION})
        assert result.status_code == 202 and result.json()["turnId"] == "continued-turn"
        result = client.post("/api/assistant/head", json={"nodeId": "target-node"})
        assert result.status_code == 202 and result.json()["id"] == "native-session"
        result = client.post("/api/assistant/messages/regenerate", json={"messageId": "target-message", "requestId": "regen-1"})
        assert result.status_code == 202 and result.json()["id"] == "native-session"
        result = client.post("/api/assistant/guidance", json={"content": "hold on", "mode": "interrupt"})
        assert result.status_code == 202 and result.json()["id"] == "native-session"
        result = client.post("/api/assistant/messages", json={"message": "see this", "requestId": "send-refs",
            "references": [{"kind": "message", "referenceId": "message:m1", "sourceSessionId": "native-session",
                            "sourceMessageId": "m1", "quote": "quoted text"}]})
        assert result.status_code == 200 and result.json()["acceptedRequestId"] == "send-refs"
        assert result.json()["references"][0]["referenceId"] == "message:m1"
    assert calls == [("stop", "old-turn"), ("continue", "continue-1", CONTINUATION), ("head", "target-node"),
                     ("regenerate", "target-message", "regen-1"), ("guidance", "hold on", "interrupt")]


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
    ("head", {}), ("head", {"nodeId": " "}), ("head", {"nodeId": 1}), ("head", {"nodeId": ""}),
    ("head", {"nodeId": "x", "sessionId": "other"}),
    ("head", {"nodeId": "x" * 201}),
    ("messages/regenerate", {}), ("messages/regenerate", {"messageId": " ", "requestId": "r"}),
    ("messages/regenerate", {"messageId": "m"}), ("messages/regenerate", {"messageId": "m", "requestId": ""}),
    ("messages/regenerate", {"messageId": "m", "requestId": "bad id"}),
    ("messages/regenerate", {"messageId": "m", "requestId": "r", "sessionId": "other"}),
    ("guidance", {}), ("guidance", {"content": " ", "mode": "safe"}),
    ("guidance", {"content": "hold on"}), ("guidance", {"content": "hold on", "mode": "unsafe"}),
    ("guidance", {"content": "hold on", "mode": 7}),
    ("guidance", {"content": "hold on", "mode": "safe", "sessionId": "other"}),
    ("messages", {"message": "m", "requestId": "r", "references": "chip"}),
    ("messages", {"message": "m", "requestId": "r", "references": [{} for _ in range(9)]}),
    ("messages", {"message": "m", "requestId": "r", "references": ["plain"]}),
])
def test_session_commands_reject_invalid_payload_before_native_call(path, payload):
    class Owner(Native):
        def stop(self, *args):
            pytest.fail("invalid stop reached native owner")

        def continue_turn(self, *args):
            pytest.fail("invalid continuation reached native owner")

        def switch_head(self, *args):
            pytest.fail("invalid head switch reached native owner")

        def regenerate(self, *args):
            pytest.fail("invalid regenerate reached native owner")

        def guidance(self, *args):
            pytest.fail("invalid guidance reached native owner")

    with TestClient(create_app(native=Owner(), token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.post(f"/api/assistant/{path}", json=payload).status_code == 422


@pytest.mark.parametrize("code,status", [
    ("ASSISTANT_NOT_READY", 503), ("ASSISTANT_STOPPING", 503),
    ("ASSISTANT_IDENTITY_INVALID", 409), ("SESSION_NOT_FOUND", 404),
    ("SESSION_CONFLICT", 409), ("SESSION_INVALID", 422),
    ("ASSISTANT_QUIESCING", 503), ("ASSISTANT_QUIESCENCE_BUSY", 503),
    ("ATTACHMENT_NOT_FOUND", 404), ("OFFLINE_MIGRATION_READ_ONLY", 503),
])
@pytest.mark.parametrize("path", ["stop", "continue", "head", "messages/regenerate", "guidance"])
def test_session_command_errors_have_bounded_codes(code, status, path):
    from core.assistant_runtime.native import AssistantSessionError

    class Owner(Native):
        def stop(self, *args):
            raise AssistantSessionError(code)

        def continue_turn(self, *args):
            raise AssistantSessionError(code)

        def switch_head(self, *args):
            raise AssistantSessionError(code)

        def regenerate(self, *args):
            raise AssistantSessionError(code)

        def guidance(self, *args):
            raise AssistantSessionError(code)

    payload = {"turnId": "old-turn"} if path == "stop" else (
        {"requestId": "c", "continuation": CONTINUATION} if path == "continue" else (
            {"nodeId": "target"} if path == "head" else (
                {"messageId": "m", "requestId": "r"} if path == "messages/regenerate"
                else {"content": "hold on", "mode": "safe"})))
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
    monkeypatch.setattr(native, "switch_head", lambda node: calls.append(("head", node)) or {"id": "s"})
    monkeypatch.setattr(native, "regenerate", lambda message, request: calls.append(("regenerate", message, request)) or {"id": "s"})
    monkeypatch.setattr(native, "guidance", lambda content, mode: calls.append(("guidance", content, mode)) or {"id": "s"})
    facade = NativeFacade(None)
    assert facade.stop("old")["stopRequested"]
    assert facade.continue_turn("c", CONTINUATION)["turnId"] == "new"
    assert facade.switch_head("target")["id"] == "s"
    assert facade.regenerate("m", "r")["id"] == "s"
    assert facade.guidance("hold on", "safe")["id"] == "s"
    assert calls == [("stop", "old"), ("continue", "c", CONTINUATION), ("head", "target"),
                     ("regenerate", "m", "r"), ("guidance", "hold on", "safe")]


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


def _identity_snapshot_test_facade(monkeypatch):
    """A facade whose lock-bound native reads and lock-free extras are fixtures."""
    import threading

    from core.assistant_runtime import host, native, operator_assets
    from core.assistant_runtime.host import NativeFacade

    monkeypatch.setattr(operator_assets, "operator_asset_revisions",
                        lambda: {"avatar": None, "background": None})
    monkeypatch.setattr(host, "_model_image_input_support", lambda agent_id: None)
    monkeypatch.setattr(host, "_operator_profile", lambda: None)
    state = {"reads": [], "models": ["m1"], "gate": threading.Event(), "gate_open": True}

    def identity():
        assert state["gate_open"] or state["gate"].wait(5), "background identity refresh never ran"
        state["reads"].append("identity")
        return {"assistant": {"agentId": "a", "directSessionId": "s"}, "sessionId": "s"}

    def settings():
        state["reads"].append("settings")
        return {"ok": True, "modelId": state["models"][-1]}

    monkeypatch.setattr(native, "identity", identity)
    monkeypatch.setattr(native, "assistant_settings", settings)
    monkeypatch.setattr(native, "assistant_avatar_revision", lambda: state["reads"].append("avatar"))
    return NativeFacade(None), state


def test_identity_snapshot_serves_cached_status_without_native_lock_or_reads(monkeypatch):
    import threading
    import time

    from core.assistant_runtime import host, native

    monkeypatch.setattr(host, "IDENTITY_SNAPSHOT_TTL_SECONDS", 60.0)
    facade, state = _identity_snapshot_test_facade(monkeypatch)
    first = facade.identity()
    assert state["reads"] == ["identity", "settings", "avatar"]
    assert first["settings"]["modelId"] == "m1"
    # A held native lock (polled chat detail, submit) must not delay a cached
    # lightweight status read, and a cache hit performs no native reads at all.
    locked = threading.Event()
    release = threading.Event()

    def hold_native_lock():
        with native._LOCK:
            locked.set()
            assert release.wait(5)

    holder = threading.Thread(target=hold_native_lock, daemon=True)
    holder.start()
    assert locked.wait(1)
    try:
        started = time.perf_counter()
        second = facade.identity()
        elapsed = time.perf_counter() - started
    finally:
        release.set()
        holder.join(5)
    assert elapsed < 1.0
    assert second["assistant"] == first["assistant"]
    assert second["settings"]["modelId"] == "m1"
    assert state["reads"] == ["identity", "settings", "avatar"]


def test_set_model_invalidates_the_identity_snapshot_only_after_success(monkeypatch):
    from core.assistant_runtime import host
    from core.assistant_runtime.native import AssistantSessionError

    monkeypatch.setattr(host, "IDENTITY_SNAPSHOT_TTL_SECONDS", 60.0)
    facade, state = _identity_snapshot_test_facade(monkeypatch)

    def set_model(model_id):
        if model_id == "busy":
            raise AssistantSessionError("ASSISTANT_MODEL_BUSY")
        state["models"].append(model_id)
        return {"modelId": model_id}

    from core.assistant_runtime import native
    monkeypatch.setattr(native, "set_model", set_model)
    assert facade.identity()["settings"]["modelId"] == "m1"
    assert facade.identity()["settings"]["modelId"] == "m1"  # served from the snapshot
    assert len(state["reads"]) == 3
    with pytest.raises(AssistantSessionError):
        facade.set_model("busy")
    assert len(state["reads"]) == 3  # failed writes keep the validated snapshot
    assert facade.set_model("m2") == {"modelId": "m2"}
    assert facade.identity()["settings"]["modelId"] == "m2"
    assert len(state["reads"]) == 6  # exactly one recompute after the successful write
    assert facade.identity()["settings"]["modelId"] == "m2"
    assert len(state["reads"]) == 6  # and the refreshed snapshot is cached again


def test_stale_identity_snapshot_is_served_immediately_and_refreshed_in_background(monkeypatch):
    import time

    from core.assistant_runtime import host

    monkeypatch.setattr(host, "IDENTITY_SNAPSHOT_TTL_SECONDS", 0.0)  # every read is stale
    facade, state = _identity_snapshot_test_facade(monkeypatch)
    assert facade.identity()["settings"]["modelId"] == "m1"
    state["models"].append("m2")
    state["gate_open"] = False
    state["gate"].clear()  # the native read is now unreachable (simulated lock hold)
    try:
        started = time.perf_counter()
        stale = facade.identity()
        elapsed = time.perf_counter() - started
    finally:
        state["gate_open"] = True
        state["gate"].set()
    assert elapsed < 1.0
    assert stale["settings"]["modelId"] == "m1"  # last validated snapshot, not a queue
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if facade.identity()["settings"]["modelId"] == "m2":
            break
        time.sleep(0.01)
    assert facade.identity()["settings"]["modelId"] == "m2"


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
