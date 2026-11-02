"""Cleanup authorization, stale previews and partial convergence in isolation."""
import json
from types import SimpleNamespace

import anyio
import pytest
from fastapi import HTTPException

from core.assistant_runtime.task_cleanup import CleanupExecute, CleanupPreview, TaskCleanup


@pytest.fixture
def scene(tmp_path):
    record = {"schemaVersion": 1, "dispatchId": "dispatch-1", "projectId": "project-1", "projectBinding": "binding",
              "agentId": "worker-1", "nativeTaskId": "eat-1", "requestDigest": "a" * 64,
              "title": "整理资料", "receipt": {"taskId": "eat-1", "status": "succeeded", "resultSummary": "x" * 2048}}
    root = tmp_path / "dispatch"
    path = root / "records" / "dispatch-1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record), encoding="utf-8")

    class Client:
        result = {"taskId": "eat-1", "status": "deleted", "releasedBytes": 100, "retained": [], "failures": []}
        calls = 0

        async def preview_task_cleanup(self, **_):
            return {"schemaVersion": 1, "taskId": "eat-1", "revision": 3, "fingerprint": "f" * 64,
                    "estimatedBytes": 100, "resources": [{"kind": "session_files", "count": 1, "bytes": 100}], "retained": []}

        async def cleanup_task(self, **kwargs):
            assert kwargs == {"task_id": "eat-1", "revision": 3, "fingerprint": "f" * 64}
            self.calls += 1
            return self.result

    client = Client()
    identity = {"agentId": "assistant-1", "directSessionId": "session-1"}

    class Dispatch:
        _root = root

        def _path(self, _):
            return path

        def _read(self, _):
            return json.loads(path.read_text(encoding="utf-8"))

        def _save(self, row):
            path.write_text(json.dumps(row), encoding="utf-8")

        def _dispatch_lock(self, _):
            return anyio.Lock()

        async def _call(self, project, fn):
            assert project == "project-1"
            return await fn(client)

    payload = CleanupPreview(**identity, targets=[{"kind": "dispatch", "projectId": "project-1", "dispatchId": "dispatch-1"}])
    return SimpleNamespace(service=TaskCleanup(Dispatch(), lambda: identity), payload=payload,
                           identity=identity, client=client, path=path, root=root)


@pytest.mark.anyio
async def test_only_confirmed_exact_preview_can_physically_delete(scene):
    preview = await scene.service.preview(scene.payload)
    assert scene.path.exists() and scene.client.calls == 0
    before = scene.path.stat().st_size
    result = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    marker = scene.root / "deleted" / "dispatch-1.json"
    assert not scene.path.exists() and marker.is_file()
    assert "整理资料" not in marker.read_text() and "resultSummary" not in marker.read_text()
    assert result["items"][0]["status"] == "deleted"
    assert result["releasedBytes"] == 100 + before - marker.stat().st_size
    assert scene.client.calls == 1


@pytest.mark.anyio
async def test_changed_target_or_assistant_cannot_use_an_old_preview(scene):
    preview = await scene.service.preview(scene.payload)
    changed = scene.payload.model_dump()
    changed["targets"][0]["projectId"] = "another-project"
    with pytest.raises(HTTPException) as exc:
        await scene.service.execute(CleanupExecute(**changed, fingerprint=preview["fingerprint"]))
    assert exc.value.status_code == 409 and scene.client.calls == 0
    preview = await scene.service.preview(scene.payload)
    scene.identity["agentId"] = "assistant-2"
    with pytest.raises(HTTPException):
        await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert scene.path.exists() and scene.client.calls == 0


@pytest.mark.anyio
async def test_stale_binding_never_calls_native_delete(scene):
    preview = await scene.service.preview(scene.payload)
    row = json.loads(scene.path.read_text())
    row["nativeTaskId"] = "another-task"
    scene.path.write_text(json.dumps(row))
    result = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "blocked" and scene.path.exists()
    assert scene.client.calls == 0


@pytest.mark.anyio
async def test_native_partial_cleanup_stays_visible_and_reports_deleted_bytes(scene):
    scene.client.result = {"taskId": "eat-1", "status": "partial", "releasedBytes": 32, "retained": [],
                           "failures": [{"kind": "session", "reason": "PermissionError"}]}
    preview = await scene.service.preview(scene.payload)
    before = scene.path.stat().st_size
    result = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert scene.path.exists() and result["releasedBytes"] == max(0, 32 + before - scene.path.stat().st_size)
    assert result["items"][0]["status"] == "partial"
    assert result["items"][0]["failures"][0]["code"] == "TASK_RESOURCE_CLEANUP_FAILED"


@pytest.mark.anyio
async def test_native_storage_growth_is_deducted_from_host_release(scene):
    scene.client.result = {"taskId": "eat-1", "status": "deleted", "releasedBytes": 0,
                           "storageDeltaBytes": -17, "retained": [], "failures": []}
    before = scene.path.stat().st_size
    preview = await scene.service.preview(scene.payload)
    result = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    marker = scene.root / "deleted" / "dispatch-1.json"
    assert result["releasedBytes"] == max(0, before - marker.stat().st_size - 17)


@pytest.mark.anyio
async def test_preview_is_single_use_and_rejects_duplicate_targets(scene):
    duplicate = scene.payload.model_dump()
    duplicate["targets"] *= 2
    with pytest.raises(HTTPException) as exc:
        await scene.service.preview(CleanupPreview(**duplicate))
    assert exc.value.status_code == 422
    preview = await scene.service.preview(scene.payload)
    command = CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"])
    await scene.service.execute(command)
    with pytest.raises(HTTPException):
        await scene.service.execute(command)
    assert scene.client.calls == 1


@pytest.mark.anyio
async def test_native_unavailable_is_blocked_without_leaking_exception(scene):
    async def unavailable(**_):
        raise RuntimeError("secret private path and token")
    scene.client.preview_task_cleanup = unavailable
    preview = await scene.service.preview(scene.payload)
    assert preview["items"][0]["status"] == "blocked"
    assert "secret" not in json.dumps(preview) and scene.path.exists()


@pytest.mark.anyio
async def test_native_deleted_then_local_unlink_failure_remains_retryable_after_refresh(scene, monkeypatch):
    from pathlib import Path
    original = Path.unlink
    failures = []

    def fail_once(path, *args, **kwargs):
        if path == scene.path and not failures:
            failures.append(True)
            raise PermissionError("locked")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)
    preview = await scene.service.preview(scene.payload)
    first = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert first["items"][0]["status"] == "partial" and scene.path.exists()
    row = json.loads(scene.path.read_text())
    assert row["cleanupPending"] is True
    # A later receipt refresh sees native deletion. This must not consume or
    # erase the operator's durable cleanup recovery state.
    row["lastError"] = {"code": "TASK_NOT_FOUND"}
    scene.path.write_text(json.dumps(row))
    scene.client.result = {"taskId": "eat-1", "status": "deleted", "alreadyDeleted": True,
                           "releasedBytes": 0, "retained": [], "failures": []}
    preview = await scene.service.preview(scene.payload)
    second = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert second["items"][0]["status"] == "deleted" and not scene.path.exists()
    assert scene.client.calls == 2


@pytest.mark.anyio
async def test_dropped_native_response_persists_cleanup_recovery(scene):
    async def lost_response(**_):
        raise TimeoutError("native response dropped")
    scene.client.cleanup_task = lost_response
    preview = await scene.service.preview(scene.payload)
    result = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "blocked"
    assert scene.path.exists() and json.loads(scene.path.read_text())["cleanupPending"] is True


@pytest.mark.anyio
async def test_cleaned_dispatch_id_is_consumed_even_without_any_sdk_credentials(tmp_path):
    from core.assistant_runtime.dispatch import DispatchError
    from core.infrastructure.atomic_io import atomic_write_json
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await service.dispatch("project-a", agent_id="coder", task="original task", dispatch_id="consumed")
    record = service._read("consumed")
    atomic_write_json(service._root / "deleted" / "consumed.json", {"schemaVersion": 1, "requestDigest": record["requestDigest"]})
    service._path("consumed").unlink()
    # Reconstruct from disk with no SDK state; no permission identity or request
    # capability remains that could incidentally prevent a second start.
    assert not (service._root / "credentials").exists()
    fresh_probe = ClientProbe()
    reconstructed = adapter(tmp_path, fresh_probe)
    with pytest.raises(DispatchError) as exc:
        await reconstructed.dispatch("project-a", agent_id="coder", task="original task", dispatch_id="consumed")
    assert exc.value.code == "DISPATCH_ALREADY_CLEANED"
    assert not fresh_probe.calls and reconstructed.list_dispatches() == []
