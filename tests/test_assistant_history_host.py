import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from core.assistant_runtime import migration_history as history
from core.assistant_runtime.history_host import HistoryHost
from core.assistant_runtime.host import create_app
from tests.test_assistant_history_preview import setup_preview  # noqa: F401
from tests.test_assistant_runtime_host import Native


def make_host(tmp_path, setup_preview):
    dispatch, _, _ = setup_preview
    profile = tmp_path / "assistant-profile"
    profile.mkdir(exist_ok=True)
    history_host = HistoryHost(profile, "generation-1", dispatch, dispatch.history_preview)
    app = create_app(native=Native(), token="private-test-token", dispatch=dispatch, history_control=history_host)
    return dispatch, profile, history_host, app


def body(dispatch, operation="1" * 32, *, turn="turn-1"):
    preview = dispatch.history_preview.preview("registered:1", turn_id=turn)
    return {"projectId": "registered:1", "previewId": preview["previewId"],
            "turnId": turn, "revision": 1, "operationId": operation}


def test_legacy_reminder_source_private_point_in_time_binding(tmp_path, setup_preview):
    dispatch, _, history_host, app = make_host(tmp_path, setup_preview)
    request = {"projectId": "registered:1", "revision": 1}
    headers = {"Authorization": "Bearer private-test-token"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        endpoint = "/api/assistant/legacy-reminders/source"
        assert client.post(endpoint, json=request).status_code == 401
        assert client.post(endpoint, json={**request, "agentId": "forged"}, headers=headers).status_code == 422
        assert client.post(endpoint + "?x=1", json=request, headers=headers).status_code == 422
        response = client.post(endpoint, json=request, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        value = response.json()
        assert value["projectId"] == "registered:1" and value["revision"] == 1
        assert value["sourceScope"]["agentId"] == "agent-pa"
        assert len(value["sourceIdentityDigest"]) == len(value["authorityDigest"]) == 64
        assert set(value["projectDirectory"]) == {"device", "inode", "birthtimeNs"}
        assert not dispatch.history_preview._previews
        assert client.post(endpoint, json={**request, "revision": 0}, headers=headers).status_code == 409
        dispatch.suspend_projects()
        assert client.post(endpoint, json=request, headers=headers).status_code == 409
        assert not dispatch.history_preview._previews


def test_legacy_reminder_source_discards_preview_on_changed_authority(tmp_path, setup_preview, monkeypatch):
    from core.assistant_runtime.migration_io import MigrationIOError
    dispatch, _, history_host, _ = make_host(tmp_path, setup_preview)
    original = dispatch.history_preview.verify_preview
    calls = 0
    def changed(token):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise MigrationIOError("history_preview_changed")
        return original(token)
    monkeypatch.setattr(dispatch.history_preview, "verify_preview", changed)
    with pytest.raises(MigrationIOError, match="history_preview_changed"):
        history_host.legacy_reminder_source("registered:1", 1)
    assert not dispatch.history_preview._previews


def test_legacy_reminder_source_changes_version_when_registry_changes(tmp_path, setup_preview):
    dispatch, _, history_host, _ = make_host(tmp_path, setup_preview)
    workspace = setup_preview[1]
    first = history_host.legacy_reminder_source("registered:1", 1)
    registry = workspace / "agents/agents.json"
    registry.write_text(registry.read_text(encoding="utf-8") + " ", encoding="utf-8")
    second = history_host.legacy_reminder_source("registered:1", 1)
    assert first["sourceScope"] == second["sourceScope"]
    assert first["sourceIdentityDigest"] == second["sourceIdentityDigest"]
    assert first["authorityDigest"] != second["authorityDigest"]
    assert not dispatch.history_preview._previews


def test_private_host_import_uses_native_source_and_preview_once(tmp_path, setup_preview):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/assistant/history-import", json=request).status_code == 401
        headers = {"Authorization": "Bearer private-test-token"}
        assert client.post("/api/assistant/history-import", json={**request, "approved": True}, headers=headers).status_code == 422
        result = client.post("/api/assistant/history-import", json=request, headers=headers).json()
        assert result == {"schemaVersion": 1, "projectId": "registered:1", "previewId": request["previewId"],
                          "state": "published", "code": "imported", "historyCount": 1, "readyForCutover": False}
        assert len(history.list_history(profile)) == 1
        assert client.post("/api/assistant/history-import", json=request, headers=headers).json()["code"] == "preview_invalid"


def test_turn_mismatch_and_cancel_before_request_never_publish(tmp_path, setup_preview):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    headers = {"Authorization": "Bearer private-test-token"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        request = body(dispatch)
        assert client.post("/api/assistant/history-import", json={**request, "turnId": "other-turn"}).json()["code"] == "preview_invalid"
        request = body(dispatch, operation="2" * 32)
        assert client.post("/api/assistant/history-import/cancel", json={"operationId": request["operationId"], "previewId": request["previewId"]}).json()["cancelled"]
        assert client.post("/api/assistant/history-import", json=request).json()["code"] == "cancelled"
        assert client.post("/api/assistant/history-import", json={**request, "operationId": "3" * 32}).json()["code"] == "preview_invalid"
        assert not (profile / "history_archive").exists()


def test_cancel_fences_inflight_before_confirmation(tmp_path, setup_preview, monkeypatch):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    reached, resume = threading.Event(), threading.Event()
    original = history._load_archive

    def pause(directory, **kwargs):
        result = original(directory, **kwargs)
        if directory.name.endswith(".pending") and directory.name.startswith(".history-"):
            reached.set()
            assert resume.wait(10)
        return result

    monkeypatch.setattr(history, "_load_archive", pause)
    headers = {"Authorization": "Bearer private-test-token"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, "/api/assistant/history-import", json=request)
            assert reached.wait(10)
            try:
                result = client.post("/api/assistant/history-import/cancel", json={"operationId": request["operationId"], "previewId": request["previewId"]})
                assert result.json()["cancelled"]
            finally:
                resume.set()
            assert future.result(timeout=10).json()["state"] == "unknown"
    assert history.list_history(profile) == []


def test_project_revocation_fences_inflight_before_confirmation(tmp_path, setup_preview, monkeypatch):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    reached, resume = threading.Event(), threading.Event()
    original = history._load_archive

    def pause(directory, **kwargs):
        result = original(directory, **kwargs)
        if directory.name.endswith(".pending") and directory.name.startswith(".history-"):
            reached.set()
            assert resume.wait(10)
        return result

    monkeypatch.setattr(history, "_load_archive", pause)
    headers = {"Authorization": "Bearer private-test-token"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, "/api/assistant/history-import", json=request)
            assert reached.wait(10)
            try:
                response = client.put("/api/assistant/project-registry", json={"schemaVersion": 1, "revision": 2, "projects": {}})
                assert response.status_code == 200
            finally:
                resume.set()
            assert future.result(timeout=10).json()["state"] == "unknown"
    assert history.list_history(profile) == []


def test_source_change_during_import_never_confirms(tmp_path, setup_preview, monkeypatch):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    _, workspace, _ = setup_preview
    request = body(dispatch)
    reached, resume = threading.Event(), threading.Event()
    original = history._load_archive

    def pause(directory, **kwargs):
        result = original(directory, **kwargs)
        if directory.name.endswith(".pending") and directory.name.startswith(".history-"):
            reached.set()
            assert resume.wait(10)
        return result

    monkeypatch.setattr(history, "_load_archive", pause)
    headers = {"Authorization": "Bearer private-test-token"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, "/api/assistant/history-import", json=request)
            assert reached.wait(10)
            try:
                journal = workspace / "sessions/direct/turn_journal.jsonl"
                journal.write_bytes(journal.read_bytes() + b"\n")
            finally:
                resume.set()
            assert future.result(timeout=10).json()["state"] == "unknown"
    assert history.list_history(profile) == []


def test_final_confirmation_pins_source_and_authority_files(tmp_path, setup_preview, monkeypatch):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    _, workspace, _ = setup_preview
    project = dispatch._admitted_projects()["registered:1"]
    guarded = [workspace / "agents/agents.json", workspace / "sessions/direct/turn_journal.jsonl",
               project / ".vibelution/project.json", tmp_path / "operator/config.toml"]
    request = body(dispatch)
    blocked = []
    original = history.publish_directory

    def assert_pinned(pending, final, identity):
        if final.name == ".confirmed":
            for path in guarded:
                try:
                    with path.open("ab") as stream:
                        stream.write(b"unsafe")
                except OSError:
                    blocked.append(path)
        return original(pending, final, identity)

    monkeypatch.setattr(history, "publish_directory", assert_pinned)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        result = client.post("/api/assistant/history-import", json=request).json()
    assert result["state"] == "published"
    assert blocked == guarded
    assert len(history.list_history(profile)) == 1


def test_busy_import_discards_second_preview(tmp_path, setup_preview, monkeypatch):
    dispatch, _, _, app = make_host(tmp_path, setup_preview)
    first, second = body(dispatch), body(dispatch, operation="2" * 32)
    reached, resume = threading.Event(), threading.Event()
    original = history._load_archive

    def pause(directory, **kwargs):
        result = original(directory, **kwargs)
        if directory.name.endswith(".pending") and directory.name.startswith(".history-"):
            reached.set()
            assert resume.wait(10)
        return result

    monkeypatch.setattr(history, "_load_archive", pause)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, "/api/assistant/history-import", json=first)
            assert reached.wait(10)
            try:
                assert client.post("/api/assistant/history-import", json=second).json()["code"] == "busy"
            finally:
                resume.set()
            assert future.result(timeout=10).json()["state"] == "published"
        assert client.post("/api/assistant/history-import", json={**second, "operationId": "3" * 32}).json()["code"] == "preview_invalid"


def test_cancel_waits_for_confirmation_already_in_progress(tmp_path, setup_preview, monkeypatch):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    reached, resume, cancel_started = threading.Event(), threading.Event(), threading.Event()
    original = history.publish_directory

    def pause(pending, final, identity):
        if final.name == ".confirmed":
            reached.set()
            assert resume.wait(10)
        return original(pending, final, identity)

    monkeypatch.setattr(history, "publish_directory", pause)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            importing = pool.submit(client.post, "/api/assistant/history-import", json=request)
            assert reached.wait(10)
            def cancel():
                cancel_started.set()
                return client.post("/api/assistant/history-import/cancel", json={"operationId": request["operationId"], "previewId": request["previewId"]})
            cancelling = pool.submit(cancel)
            try:
                assert cancel_started.wait(10)
                assert not cancelling.done()
            finally:
                resume.set()
            assert cancelling.result(timeout=10).json()["cancelled"]
            assert importing.result(timeout=10).json()["state"] in {"published", "unknown"}
    assert len(history.list_history(profile)) == 1


def test_native_stop_before_delayed_import_retires_turn_preview(tmp_path, setup_preview):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.post("/api/assistant/stop", json={"turnId": "turn-1"}).status_code == 202
        assert client.post("/api/assistant/history-import", json=request).json()["code"] == "preview_invalid"
        assert client.post("/api/assistant/history-import", json={**request, "operationId": "2" * 32}).json()["code"] == "preview_invalid"
        assert not (profile / "history_archive").exists()
        assert dispatch.history_preview.preview("registered:1", turn_id="another-turn")["authorized"] is False
        with pytest.raises(history.MigrationIOError, match="history_turn_stopped"):
            dispatch.history_preview.preview("registered:1", turn_id="turn-1")


def test_native_stop_during_copy_fences_history_publication(tmp_path, setup_preview, monkeypatch):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    reached, resume = threading.Event(), threading.Event()
    original = history._load_archive

    def pause(directory, **kwargs):
        result = original(directory, **kwargs)
        if directory.name.endswith(".pending") and directory.name.startswith(".history-"):
            reached.set()
            assert resume.wait(10)
        return result

    monkeypatch.setattr(history, "_load_archive", pause)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, "/api/assistant/history-import", json=request)
            assert reached.wait(10)
            try:
                assert client.post("/api/assistant/stop", json={"turnId": "turn-1"}).status_code == 202
            finally:
                resume.set()
            assert future.result(timeout=10).json()["state"] == "unknown"
        assert client.post("/api/assistant/history-import", json={**request, "operationId": "2" * 32}).json()["code"] == "preview_invalid"
    assert history.list_history(profile) == []


def test_native_stop_after_confirmation_preserves_already_published_history(tmp_path, setup_preview):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.post("/api/assistant/history-import", json=request).json()["state"] == "published"
        assert client.post("/api/assistant/stop", json={"turnId": "turn-1"}).status_code == 202
        assert client.post("/api/assistant/history-import", json={**request, "operationId": "2" * 32}).json()["code"] == "preview_invalid"
    assert len(history.list_history(profile)) == 1


def test_stop_waits_for_final_commit_already_in_progress(tmp_path, setup_preview, monkeypatch):
    dispatch, profile, _, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    reached, resume, native_called = threading.Event(), threading.Event(), threading.Event()
    original_publish = history.publish_directory
    original_stop = Native.stop

    def pause(pending, final, identity):
        if final.name == ".confirmed":
            reached.set()
            assert resume.wait(10)
        return original_publish(pending, final, identity)

    def native_stop(self, turn):
        native_called.set()
        return original_stop(self, turn)

    monkeypatch.setattr(history, "publish_directory", pause)
    monkeypatch.setattr(Native, "stop", native_stop)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            importing = pool.submit(client.post, "/api/assistant/history-import", json=request)
            assert reached.wait(10)
            stopping = pool.submit(client.post, "/api/assistant/stop", json={"turnId": "turn-1"})
            try:
                assert not native_called.wait(0.2)
            finally:
                resume.set()
            assert stopping.result(timeout=10).status_code == 202
            assert importing.result(timeout=10).json()["state"] in {"published", "unknown"}
    assert len(history.list_history(profile)) == 1


def test_preview_still_being_scanned_cannot_reappear_after_stop(tmp_path, setup_preview, monkeypatch):
    from core.assistant_runtime import history_preview
    dispatch, _, _, app = make_host(tmp_path, setup_preview)
    reached, resume = threading.Event(), threading.Event()
    original = history_preview.read_stable_file

    def pause(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path.name == "agents.json":
            reached.set()
            assert resume.wait(10)
        return result

    monkeypatch.setattr(history_preview, "read_stable_file", pause)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(dispatch.history_preview.preview, "registered:1", turn_id="turn-1")
            assert reached.wait(10)
            try:
                assert client.post("/api/assistant/stop", json={"turnId": "turn-1"}).status_code == 202
            finally:
                resume.set()
            with pytest.raises(history.MigrationIOError, match="history_turn_stopped"):
                future.result(timeout=10)


def test_failed_native_stop_does_not_revoke_preview(tmp_path, setup_preview):
    from core.assistant_runtime.native import AssistantSessionError
    dispatch, profile, history_host, _ = make_host(tmp_path, setup_preview)

    class ConflictNative(Native):
        def stop(self, turn_id):
            raise AssistantSessionError("SESSION_CONFLICT")

    app = create_app(native=ConflictNative(), token="private-test-token", dispatch=dispatch, history_control=history_host)
    request = body(dispatch)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.post("/api/assistant/stop", json={"turnId": "turn-1"}).status_code == 409
        assert client.post("/api/assistant/history-import", json=request).json()["state"] == "published"
    assert len(history.list_history(profile)) == 1


def test_stop_notifies_broker_after_turn_preview_is_fenced(tmp_path, setup_preview):
    dispatch, _, history_host, _ = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    seen = []

    class Broker:
        appearance_enabled = False

        def cancel_history_imports(self, turn_id):
            with pytest.raises(history.MigrationIOError, match="history_preview_expired"):
                dispatch.history_preview.verify_preview(request["previewId"])
            seen.append(turn_id)

        def close(self):
            pass

    app = create_app(native=Native(), token="private-test-token", dispatch=dispatch,
                     main_control=Broker(), history_control=history_host)
    with TestClient(app, base_url="http://127.0.0.1", headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.post("/api/assistant/stop", json={"turnId": "turn-1"}).status_code == 202
    assert seen == ["turn-1"]
