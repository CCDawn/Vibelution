"""Host consumes an approved preview once and preserves operation recovery."""
from contextlib import contextmanager
from types import SimpleNamespace

from core.assistant_runtime.history_host import HistoryHost
from core.assistant_runtime.main_control import episodic_migration_id, initial_migration_id
from fastapi.testclient import TestClient
from tests.test_assistant_history_host import body, make_host
from tests.test_assistant_history_preview import setup_preview  # noqa: F401


def test_host_consumes_preview_once_and_preserves_recovery_id(tmp_path, monkeypatch):
    from core.assistant_runtime import online_episodic_sync
    class Preview:
        def __init__(self): self.available = set()
        def consume_for_import(self, preview_id, project_id, revision, turn_id):
            assert preview_id in self.available
            self.available.remove(preview_id)
            return (None, None, SimpleNamespace(project_id="source", instance_id="instance"), "old", None, ())
        def discard(self, preview_id): self.available.discard(preview_id)
    preview = Preview()
    host = HistoryHost(tmp_path, "generation", None, preview)
    @contextmanager
    def guard(_generation, _turn, _operation): yield
    monkeypatch.setattr(host, "_sync_guard", guard)
    calls = []
    def sync(**kwargs):
        calls.append(kwargs)
        return {"appliedCount": 1, "conflictCount": 0}
    monkeypatch.setattr(online_episodic_sync, "synchronize_episodic", sync)
    pid, op = "a" * 64, "b" * 32
    preview.available.add(pid)
    first = host.sync_episodic("project", pid, 1, "turn", op)
    assert first["state"] == "complete" and first["migrationId"] == episodic_migration_id("project", pid)
    assert calls[0]["initial_operation_id"] == initial_migration_id("project", "", "personal")
    assert host.sync_episodic("project", pid, 1, "turn", op) == first
    assert len(calls) == 1
    recovery_preview, original = "c" * 64, first["migrationId"]
    preview.available.add(recovery_preview)
    result = host.sync_episodic("project", recovery_preview, 1, "turn", "d" * 32, original)
    assert result["state"] == "confirmed" and result["migrationId"] == original
    assert calls[-1]["sync_id"] == original and calls[-1]["confirmation_only"] is True
    assert host.sync_episodic("project", recovery_preview, 2, "turn", "d" * 32, original)["state"] == "unknown"
    blocked_preview = "e" * 64
    preview.available.add(blocked_preview)
    host._sync_seen = {f"{n:032x}": {"result": None} for n in range(256)}
    assert host.sync_episodic("project", blocked_preview, 1, "turn", "f" * 32)["state"] == "unknown"
    assert blocked_preview not in preview.available


def test_private_endpoint_rejects_paths_and_keeps_original_id(tmp_path, setup_preview, monkeypatch):
    dispatch, _, host, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    original = "episodic-" + "a" * 40
    calls = []
    def sync(*args):
        calls.append(args)
        return {"schemaVersion": 1, "projectId": args[0], "previewId": args[1],
                "migrationId": args[5] or episodic_migration_id(args[0], args[1]),
                "state": "unknown", "code": "unknown", "readyForCutover": False}
    monkeypatch.setattr(host, "sync_episodic", sync)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        endpoint = "/api/assistant/episodic-sync"
        assert client.post(endpoint, json=request).status_code == 401
        headers = {"Authorization": "Bearer private-test-token"}
        assert client.post(endpoint, json={**request, "sourcePath": "C:/secret"}, headers=headers).status_code == 422
        assert client.post(endpoint + "?x=1", json=request, headers=headers).status_code == 422
        response = client.post(endpoint, json={**request, "recoverSyncId": original}, headers=headers)
        assert response.status_code == 200 and response.json()["migrationId"] == original
        assert response.headers["cache-control"] == "no-store" and calls[-1][5] == original
        assert client.post(endpoint, json={**request, "recoverSyncId": "affairs-" + "a" * 40}, headers=headers).status_code == 422
        assert client.post(endpoint, json={**request, "resolveSyncId": original}, headers=headers).status_code == 422
        response = client.post(endpoint, json={**request, "resolveSyncId": original, "reviewToken": "c" * 64}, headers=headers)
        assert response.status_code == 200 and calls[-1][6:] == (original, "c" * 64)


def test_only_proven_prewrite_failures_are_rejected(tmp_path, monkeypatch):
    from core.assistant_runtime import online_episodic_sync
    from core.assistant_runtime.migration_io import MigrationIOError
    class Preview:
        def consume_for_import(self, *_args):
            return (None, None, None, None, None, ())
        def discard(self, _id): pass
    host = HistoryHost(tmp_path, "generation", None, Preview())
    @contextmanager
    def guard(*_args): yield
    monkeypatch.setattr(host, "_sync_guard", guard)
    for index, code in enumerate(("busy", "baseline_unavailable", "unresolved", "row_limit", "cancelled")):
        def rejected(**_args): raise online_episodic_sync.EpisodicSyncPrewrite(code)
        monkeypatch.setattr(online_episodic_sync, "synchronize_episodic", rejected)
        result = host.sync_episodic("project", f"{index:064x}", 1, "turn", f"{index:032x}")
        assert result["state"] == "rejected" and result["code"] == code
    def uncertain(**_args): raise MigrationIOError("episodic_sync_outcome_unknown")
    monkeypatch.setattr(online_episodic_sync, "synchronize_episodic", uncertain)
    assert host.sync_episodic("project", "a" * 64, 1, "turn", "b" * 32)["state"] == "unknown"
    @contextmanager
    def busy(*_args): raise MigrationIOError("affairs_sync_busy"); yield
    monkeypatch.setattr(host, "_sync_guard", busy)
    assert host.sync_episodic("project", "c" * 64, 1, "turn", "d" * 32)["code"] == "busy"


def test_cancellation_waits_for_episodic_owner_to_drain(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from core.assistant_runtime import online_episodic_sync
    class Preview:
        def consume_for_import(self, *_args): return (None, None, None, None, None, ())
        def discard(self, _id): pass
    host = HistoryHost(tmp_path, "generation", None, Preview())
    @contextmanager
    def guard(*_args): yield
    monkeypatch.setattr(host, "_sync_guard", guard)
    entered, release = threading.Event(), threading.Event()
    def pending(**kwargs):
        entered.set()
        assert kwargs["owner"]._revoked.wait(5)
        assert release.wait(5)
        raise RuntimeError("cancelled after admission")
    monkeypatch.setattr(online_episodic_sync, "synchronize_episodic", pending)
    with ThreadPoolExecutor(max_workers=2) as pool:
        operation = pool.submit(host.sync_episodic, "project", "a" * 64, 1, "turn", "b" * 32)
        assert entered.wait(5)
        cancellation = pool.submit(host.cancel_affairs, "b" * 32, "a" * 64)
        assert host._sync_active["owner"]._revoked.wait(5)
        assert not cancellation.done()
        release.set()
        assert operation.result(timeout=5)["state"] == "unknown"
        assert cancellation.result(timeout=5)["cancelled"] is True
