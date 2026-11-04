"""Cleanup authorization, stale previews and partial convergence in isolation."""
import json
from types import SimpleNamespace

import anyio
import pytest
from fastapi import HTTPException

from core.assistant_runtime.dispatch import DispatchError
from core.assistant_runtime.management import ManagementAdapter
from core.assistant_runtime.task_cleanup import CleanupExecute, CleanupPreview, TaskCleanup
from core.external_agent.backend_client import BackendClientError, ManagedAgentBackendClient


@pytest.fixture
def scene(tmp_path):
    record = {"schemaVersion": 1, "dispatchId": "dispatch-1", "projectId": "project-1", "projectBinding": "binding",
              "agentId": "worker-1", "nativeTaskId": "eat-1", "requestDigest": "a" * 64,
              "clientRequestId": "launcher-assistant:dispatch-1",
              "title": "整理资料", "receipt": {"taskId": "eat-1", "status": "succeeded", "resultSummary": "x" * 2048}}
    root = tmp_path / "dispatch"
    path = root / "records" / "dispatch-1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record), encoding="utf-8")

    class Client:
        result = {"taskId": "eat-1", "status": "deleted", "releasedBytes": 100, "retained": [], "failures": []}
        calls = 0

        def __init__(self):
            self.reads = []
            self.request_receipt = {"taskId": "eat-1", "status": "succeeded"}
            self.task_receipt = dict(self.request_receipt)

        async def get_task_for_request(self, **kwargs):
            self.reads.append(("request", kwargs))
            return dict(self.request_receipt)

        async def get_task(self, **kwargs):
            self.reads.append(("task", kwargs))
            return dict(self.task_receipt)

        async def _cleanup_capability(self, task_id):
            assert task_id == "eat-1"
            return "bound-capability"

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

        def _project_read_binding(self, _):
            return 1, root

        @staticmethod
        def _binding(_):
            return "binding"

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


@pytest.mark.anyio
@pytest.mark.parametrize("cleanup_pending", [False, True])
async def test_task_not_found_with_bound_capability_does_not_prove_source_deletion(scene, cleanup_pending):
    row = json.loads(scene.path.read_text())
    row["cleanupPending"] = cleanup_pending
    scene.path.write_text(json.dumps(row))
    async def missing(**kwargs):
        # Native owner/authority checks also return TASK_NOT_FOUND.
        raise BackendClientError("private native authority mismatch", code="TASK_NOT_FOUND")

    assert await scene.client._cleanup_capability("eat-1") == "bound-capability"
    scene.client.preview_task_cleanup = missing
    preview = await scene.service.preview(scene.payload)
    assert preview["items"][0]["status"] == "blocked"
    result = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "blocked" and scene.path.exists()
    assert not (scene.root / "deleted" / "dispatch-1.json").exists() and scene.client.calls == 0
    assert "private" not in json.dumps(preview)


@pytest.mark.anyio
async def test_lost_sdk_capability_is_not_proof_that_native_source_is_missing(scene):
    async def unavailable(task_id):
        raise BackendClientError("private capability path", code="TASK_NOT_FOUND")

    async def preview(**kwargs):
        await scene.client._cleanup_capability(kwargs["task_id"])
        pytest.fail("Native cleanup must not be reached without a task capability")

    scene.client._cleanup_capability = unavailable
    scene.client.preview_task_cleanup = preview
    preview = await scene.service.preview(scene.payload)
    assert preview["items"][0]["status"] == "blocked"
    assert "凭据" in preview["items"][0]["reason"] and "private" not in json.dumps(preview)
    assert scene.path.exists() and scene.client.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("value", [None, {}, [], "missing"])
async def test_malformed_native_preview_is_not_proof_that_source_was_deleted(scene, value):
    async def malformed(**kwargs):
        return value

    scene.client.preview_task_cleanup = malformed
    preview = await scene.service.preview(scene.payload)
    assert preview["items"][0]["status"] == "blocked" and scene.path.exists()
    assert scene.client.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["running", "queued", "stop_unconfirmed", None])
async def test_missing_source_without_terminal_proof_stays_visible(scene, status):
    row = json.loads(scene.path.read_text())
    row["receipt"]["status"] = status
    scene.path.write_text(json.dumps(row))

    async def missing(**kwargs):
        raise BackendClientError("missing", code="TASK_NOT_FOUND")

    scene.client.preview_task_cleanup = missing
    preview = await scene.service.preview(scene.payload)
    assert preview["items"][0]["status"] == "blocked"
    assert "无法确认清理范围" in preview["items"][0]["reason"] and scene.path.exists()


@pytest.mark.anyio
async def test_verified_native_tombstone_keeps_prior_deletion_reachable(scene):
    row = json.loads(scene.path.read_text())
    row.update(cleanupPending=True, receipt={"taskId": "eat-1", "status": "running"})
    scene.path.write_text(json.dumps(row))

    async def already_deleted(**kwargs):
        return {"schemaVersion": 1, "taskId": "eat-1", "revision": 3, "status": "ready",
                "fingerprint": "f" * 64, "alreadyDeleted": True, "estimatedBytes": 0,
                "resources": [], "retained": [{"kind": "request_tombstone", "reason": "prevent_request_replay"}]}

    scene.client.preview_task_cleanup = already_deleted
    scene.client.result = {"taskId": "eat-1", "status": "deleted", "alreadyDeleted": True,
                           "releasedBytes": 0, "retained": [], "failures": []}
    preview = await scene.service.preview(scene.payload)
    assert preview["items"][0]["status"] == "ready"
    result = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "deleted" and not scene.path.exists()
    assert scene.client.calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["source_acknowledged", "running", "project_binding", "terminal_status"])
async def test_unstarted_reference_cleanup_rechecks_status_and_binding_before_delete(scene, change):
    row = json.loads(scene.path.read_text())
    row.update(nativeTaskId="", receipt=None, status="failed")
    scene.path.write_text(json.dumps(row))
    preview = await scene.service.preview(scene.payload)
    assert preview["items"][0]["status"] == "ready"
    if change == "source_acknowledged":
        row["nativeTaskId"] = "eat-1"
    elif change == "running":
        row["status"] = "running"
    elif change == "terminal_status":
        row["status"] = "cancelled"
    else:
        row["projectBinding"] = "changed"
    scene.path.write_text(json.dumps(row))
    result = await scene.service.execute(CleanupExecute(**scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "blocked" and scene.path.exists()
    assert not (scene.root / "deleted" / "dispatch-1.json").exists() and scene.client.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled", "timed_out", "running", "stop_unconfirmed", "unknown", None])
@pytest.mark.parametrize("local_only", [False, True])
async def test_unbound_dispatch_cleanup_requires_current_request_terminal_proof(scene, status, local_only):
    row = json.loads(scene.path.read_text())
    row.update(nativeTaskId="", receipt=None, status="failed")
    scene.path.write_text(json.dumps(row))
    scene.client.request_receipt["status"] = status
    scene.client.task_receipt["status"] = status
    payload = scene.payload.model_dump()
    payload["targets"][0]["localOnly"] = local_only
    payload = CleanupPreview(**payload)
    preview = await scene.service.preview(payload)
    expected = status in {"succeeded", "failed", "cancelled", "timed_out"}
    assert preview["items"][0]["status"] == ("ready" if expected else "blocked")
    if expected:
        result = await scene.service.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"]))
        assert result["items"][0]["status"] == "deleted" and not scene.path.exists()
        assert (scene.root / "deleted" / "dispatch-1.json").exists()
    else:
        assert scene.path.exists()
    assert scene.client.calls == 0
    assert scene.client.reads[:2] == [("request", {"client_request_id": "launcher-assistant:dispatch-1"}),
                                    ("task", {"task_id": "eat-1"})]


@pytest.fixture
def team_scene(scene):
    root = scene.root / "management"
    root.mkdir()
    reference = {"projectId": "project-1", "action": "team_run", "requestId": "request-1"}
    path = root / "association.json"
    path.write_text(json.dumps({"schemaVersion": 1, "reference": reference, "fingerprint": "a" * 64}))
    run = {"teamId": "team-1", "flowId": "flow-1", "runId": "run-1", "revision": 3, "status": "completed"}
    response = {**reference, "verified": True, "status": "completed", "teamRun": run}

    async def receipt(project_id, **kwargs):
        return response

    management = SimpleNamespace(_root=root, _locks={}, _key=lambda *_: "association",
        _read=lambda path: json.loads(path.read_text()), receipt=receipt)
    scene.service.dispatch.management = management
    scene.service.dispatch._project_read_binding = lambda _: (1, root)
    payload = CleanupPreview(**scene.identity, targets=[{
        "kind": "team_run", "projectId": "project-1", "requestId": "request-1", "originAction": "team_run"}])
    return SimpleNamespace(service=scene.service, payload=payload, path=path, run=run, response=response,
                           management=management)


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["completed", "failed", "stopped", "running"])
async def test_team_cleanup_resolves_native_identity_without_prior_ui_read(team_scene, status):
    team_scene.run["status"] = status
    preview = await team_scene.service.preview(team_scene.payload)
    if status == "running":
        assert preview["items"][0]["status"] == "blocked" and team_scene.path.exists()
        assert "运行" in preview["items"][0]["reason"]
        return
    assert preview["items"][0]["status"] == "ready"
    result = await team_scene.service.execute(CleanupExecute(**team_scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "deleted" and not team_scene.path.exists()
    assert team_scene.run["status"] == status


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["teamId", "flowId", "runId"])
async def test_team_cleanup_validates_optional_selected_identity(team_scene, field):
    payload = team_scene.payload.model_dump()
    payload["targets"][0][field] = "different"
    preview = await team_scene.service.preview(CleanupPreview(**payload))
    assert preview["items"][0]["status"] == "blocked" and team_scene.path.exists()
    assert "身份" in preview["items"][0]["reason"]


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["runId", "revision", "running", "binding", "unverified"])
async def test_team_cleanup_rechecks_resolved_identity_and_terminal_state(team_scene, change):
    preview = await team_scene.service.preview(team_scene.payload)
    assert preview["items"][0]["status"] == "ready"
    if change in {"runId", "revision"}:
        team_scene.run[change] = "changed"
    elif change == "running":
        team_scene.run["status"] = "running"
    elif change == "unverified":
        team_scene.response["verified"] = False
    else:
        team_scene.service.dispatch._project_read_binding = lambda _: (2, team_scene.path.parent)
    result = await team_scene.service.execute(CleanupExecute(**team_scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "blocked" and team_scene.path.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("code", ["REQUEST_UNAVAILABLE", "OPERATION_UNAVAILABLE", "OPERATION_SOURCE_UNAVAILABLE", "BACKEND_TIMEOUT", "BACKEND_UNAVAILABLE"])
async def test_unavailable_team_source_preserves_unknown_association_and_reports_safe_reason(team_scene, code):
    async def unavailable(*args, **kwargs):
        raise BackendClientError("private path and token", code=code)

    team_scene.management.receipt = unavailable
    preview = await team_scene.service.preview(team_scene.payload)
    assert preview["items"][0]["status"] == "blocked" and team_scene.path.exists()
    assert "private" not in json.dumps(preview)
    assert preview["items"][0]["reason"] != "当前无法确认任务身份、终态或删除范围，请刷新后重试。"


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["completed", "running"])
async def test_flow_cleanup_uses_current_runtime_status_instead_of_start_ack(team_scene, status):
    record = json.loads(team_scene.path.read_text())
    record["reference"]["action"] = "flow_start"
    team_scene.path.write_text(json.dumps(record))
    team_scene.response.update(action="flow_start", flow={
        "action": "flow_start", "verified": True, "teamId": "team-1", "flowId": "flow-1", "runId": "run-1"})
    team_scene.run["status"] = status

    async def runtime(project_id, operation, **kwargs):
        assert (project_id, operation, kwargs) == ("project-1", "get", {
            "kind": "team_run", "resource_id": "run-1", "team_id": "team-1", "flow_id": "flow-1"})
        return {"projectId": project_id, "operation": {"kind": "team_run", "resourceId": "run-1", **team_scene.run}}

    team_scene.management.runtime = runtime
    payload = team_scene.payload.model_dump()
    payload["targets"][0]["originAction"] = "flow_start"
    payload = CleanupPreview(**payload)
    preview = await team_scene.service.preview(payload)
    assert preview["items"][0]["status"] == ("ready" if status == "completed" else "blocked")
    if status == "completed":
        result = await team_scene.service.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"]))
        assert result["items"][0]["status"] == "deleted" and not team_scene.path.exists()
    else:
        assert team_scene.path.exists()


@pytest.mark.anyio
async def test_team_registry_change_during_source_read_cannot_authorize_cleanup(team_scene):
    original = team_scene.management.receipt

    async def changed(*args, **kwargs):
        team_scene.service.dispatch._project_read_binding = lambda _: (2, team_scene.path.parent)
        return await original(*args, **kwargs)

    team_scene.management.receipt = changed
    preview = await team_scene.service.preview(team_scene.payload)
    assert preview["items"][0]["status"] == "blocked" and team_scene.path.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["dispatch", "team_run"])
async def test_lost_cleanup_response_converges_after_service_reload_without_native_replay(scene, team_scene, kind):
    case = scene if kind == "dispatch" else team_scene
    preview = await case.service.preview(case.payload)
    # The host committed deletion, but the caller receives no response body.
    await case.service.execute(CleanupExecute(**case.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert not case.path.exists()
    native_calls = scene.client.calls

    async def unexpected(*args, **kwargs):
        pytest.fail("A matching cleanup receipt must not replay or query the deleted native task")

    scene.client.preview_task_cleanup = unexpected
    team_scene.management.receipt = unexpected
    recovered = TaskCleanup(case.service.dispatch, case.service.identity)
    preview = await recovered.preview(case.payload)
    assert preview["items"][0]["status"] == "ready"
    assert preview["items"][0]["resources"] == [] and preview["estimatedBytes"] == 0
    result = await recovered.execute(CleanupExecute(**case.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "deleted" and result["items"][0]["alreadyDeleted"] is True
    assert result["releasedBytes"] == result["storageDeltaBytes"] == 0
    assert scene.client.calls == native_calls and not case.path.exists()
    if kind == "team_run":
        assert not list(team_scene.management._root.glob("*.json"))
        assert case.service._marker_path(case.payload.targets[0]).parent.name == "cleanup_tombstones"


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["dispatch", "team_run"])
@pytest.mark.parametrize("change", ["legacy", "projectId", "agentId", "directSessionId", "projectBinding", "schemaVersion"])
async def test_deleted_reference_needs_current_identity_and_target_scoped_cleanup_receipt(scene, team_scene, kind, change):
    case = scene if kind == "dispatch" else team_scene
    preview = await case.service.preview(case.payload)
    await case.service.execute(CleanupExecute(**case.payload.model_dump(), fingerprint=preview["fingerprint"]))
    marker = case.service._marker_path(case.payload.targets[0])
    data = json.loads(marker.read_text())
    if change == "legacy":
        data = {"schemaVersion": 1, "requestDigest": "a" * 64}
    elif change == "schemaVersion":
        data[change] = True
    else:
        data[change] = "different"
    marker.write_text(json.dumps(data))
    recovered = TaskCleanup(case.service.dispatch, case.service.identity)
    preview = await recovered.preview(case.payload)
    assert preview["items"][0]["status"] == "blocked" and not case.path.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["dispatch", "team_run"])
@pytest.mark.parametrize("change", ["marker", "record", "binding"])
async def test_already_deleted_plan_rechecks_record_marker_and_binding_under_task_lock(scene, team_scene, kind, change):
    case = scene if kind == "dispatch" else team_scene
    original = case.path.read_bytes()
    preview = await case.service.preview(case.payload)
    await case.service.execute(CleanupExecute(**case.payload.model_dump(), fingerprint=preview["fingerprint"]))
    recovered = TaskCleanup(case.service.dispatch, case.service.identity)
    preview = await recovered.preview(case.payload)
    assert preview["items"][0]["status"] == "ready"
    marker = case.service._marker_path(case.payload.targets[0])
    if change == "record":
        case.path.write_bytes(original)
    elif change == "binding":
        case.service.dispatch._project_read_binding = lambda _: (2, case.path.parent)
    else:
        data = json.loads(marker.read_text())
        data["requestDigest" if kind == "dispatch" else "runId"] = "b" * 64
        marker.write_text(json.dumps(data))
    result = await recovered.execute(CleanupExecute(**case.payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "blocked" and result["releasedBytes"] == 0
    if change == "record":
        assert case.path.read_bytes() == original


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["dispatch", "team_run"])
async def test_cleanup_marker_cannot_override_a_recreated_active_reference(scene, team_scene, kind):
    case = scene if kind == "dispatch" else team_scene
    original = case.path.read_bytes()
    preview = await case.service.preview(case.payload)
    await case.service.execute(CleanupExecute(**case.payload.model_dump(), fingerprint=preview["fingerprint"]))
    case.path.write_bytes(original)
    if kind == "dispatch":
        async def active(**kwargs):
            raise BackendClientError("active", code="TASK_NOT_TERMINAL")
        scene.client.preview_task_cleanup = active
    else:
        team_scene.run["status"] = "running"
    preview = await case.service.preview(case.payload)
    assert preview["items"][0]["status"] == "blocked" and case.path.read_bytes() == original


@pytest.mark.anyio
async def test_completed_team_cleanup_receipt_still_checks_optional_native_identity(team_scene):
    preview = await team_scene.service.preview(team_scene.payload)
    await team_scene.service.execute(CleanupExecute(**team_scene.payload.model_dump(), fingerprint=preview["fingerprint"]))
    payload = team_scene.payload.model_dump()
    payload["targets"][0]["runId"] = "another-run"
    preview = await team_scene.service.preview(CleanupPreview(**payload))
    assert preview["items"][0]["status"] == "blocked" and not team_scene.path.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["dispatch", "team_run"])
async def test_explicit_local_only_removes_proven_reference_and_retries_without_source_reads(scene, team_scene, kind):
    case = scene if kind == "dispatch" else team_scene
    if kind == "dispatch":
        record = json.loads(case.path.read_text())
        record.update(nativeTaskId="", receipt=None, lastError={"code": "UNKNOWN_REQUEST"})
        case.path.write_text(json.dumps(record))

    async def unexpected(*args, **kwargs):
        pytest.fail("Explicit local-only removal must leave every native source untouched")

    if kind == "team_run":
        scene.service.dispatch._call = unexpected
    team_scene.management.receipt = unexpected
    payload = case.payload.model_dump()
    payload["targets"][0]["localOnly"] = True
    payload = CleanupPreview(**payload)
    preview = await case.service.preview(payload)
    assert preview["items"][0]["status"] == "ready"
    result = await case.service.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "deleted" and not case.path.exists()
    assert result["items"][0]["retained"][0]["kind"] == "source_resources" and scene.client.calls == 0
    reads = list(scene.client.reads)
    if kind == "dispatch":
        assert reads == [("request", {"client_request_id": "launcher-assistant:dispatch-1"}),
                         ("task", {"task_id": "eat-1"})] * 2
    marker = json.loads(case.service._marker_path(payload.targets[0]).read_text())
    assert marker["localOnly"] is True and marker["agentId"] == payload.agentId
    if kind == "dispatch":
        assert marker["requestDigest"] == "a" * 64
    recovered = TaskCleanup(case.service.dispatch, case.service.identity)
    preview = await recovered.preview(payload)
    assert preview["items"][0]["status"] == "ready"
    result = await recovered.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["alreadyDeleted"] is True and result["releasedBytes"] == 0
    assert scene.client.reads == reads
    normal = await recovered.preview(case.payload)
    assert normal["items"][0]["status"] == "blocked"


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["dispatch", "team_run"])
@pytest.mark.parametrize("status", ["running", "queued", "stop_unconfirmed", "waiting"])
async def test_local_only_cannot_remove_a_locally_known_active_reference(scene, team_scene, kind, status):
    case = scene if kind == "dispatch" else team_scene
    record = json.loads(case.path.read_text())
    record["receipt"] = {"status": status} if kind == "dispatch" else {"teamRun": {"status": status}}
    case.path.write_text(json.dumps(record))
    payload = case.payload.model_dump()
    payload["targets"][0]["localOnly"] = True
    preview = await case.service.preview(CleanupPreview(**payload))
    assert preview["items"][0]["status"] == "blocked" and case.path.exists()
    assert "运行" in preview["items"][0]["reason"]


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["dispatch", "team_run"])
async def test_local_only_rechecks_activity_before_removing_the_reference(scene, team_scene, kind):
    case = scene if kind == "dispatch" else team_scene
    payload = case.payload.model_dump()
    payload["targets"][0]["localOnly"] = True
    payload = CleanupPreview(**payload)
    preview = await case.service.preview(payload)
    assert preview["items"][0]["status"] == "ready"
    record = json.loads(case.path.read_text())
    record["status"] = "running"
    case.path.write_text(json.dumps(record))
    result = await case.service.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "blocked" and case.path.exists()
    assert not case.service._marker_path(payload.targets[0]).exists()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["dispatch", "team_run"])
async def test_cleanup_preview_cannot_be_reused_with_a_different_removal_mode(scene, team_scene, kind):
    case = scene if kind == "dispatch" else team_scene
    preview = await case.service.preview(case.payload)
    payload = case.payload.model_dump()
    payload["targets"][0]["localOnly"] = True
    with pytest.raises(HTTPException) as error:
        await case.service.execute(CleanupExecute(**payload, fingerprint=preview["fingerprint"]))
    assert error.value.status_code == 409 and case.path.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["dispatch", "team_run"])
async def test_local_only_still_requires_the_exact_local_project_reference(scene, team_scene, kind):
    case = scene if kind == "dispatch" else team_scene
    payload = case.payload.model_dump()
    payload["targets"][0].update(projectId="another-project", localOnly=True)
    preview = await case.service.preview(CleanupPreview(**payload))
    assert preview["items"][0]["status"] == "blocked" and case.path.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("status", [None, "unknown", "unconfirmed"])
@pytest.mark.parametrize("cleanup_pending", [False, True])
async def test_local_only_cannot_drop_lease_reference_without_bound_terminal_receipt(scene, status, cleanup_pending):
    record = json.loads(scene.path.read_text())
    record.update(cleanupPending=cleanup_pending, receipt={"taskId": "eat-1", "status": status})
    scene.path.write_text(json.dumps(record))
    payload = scene.payload.model_dump()
    payload["targets"][0]["localOnly"] = True
    preview = await scene.service.preview(CleanupPreview(**payload))
    assert preview["items"][0]["status"] == "blocked" and scene.path.exists()
    assert "尚未确认已结束" in preview["items"][0]["reason"]
    assert not scene.service._marker_path(scene.payload.targets[0]).exists()


@pytest.mark.anyio
async def test_local_only_file_failure_keeps_original_reference_without_scheduling_native_cleanup(scene, monkeypatch):
    from pathlib import Path
    original = Path.unlink
    original_record = scene.path.read_bytes()
    failed = []

    def fail_once(path, *args, **kwargs):
        if path == scene.path and not failed:
            failed.append(True)
            raise PermissionError("private locked path")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)
    payload = scene.payload.model_dump()
    payload["targets"][0]["localOnly"] = True
    payload = CleanupPreview(**payload)
    preview = await scene.service.preview(payload)
    result = await scene.service.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "blocked" and scene.path.read_bytes() == original_record
    assert "private" not in json.dumps(result) and scene.client.calls == 0
    preview = await scene.service.preview(payload)
    result = await scene.service.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "deleted" and not scene.path.exists()
    assert scene.client.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("local_only", [False, True])
async def test_unbound_reference_cleanup_recovers_active_request_before_removal(scene, local_only):
    record = json.loads(scene.path.read_text())
    record.update(nativeTaskId="", receipt=None, status="failed", lastError={"code": "BACKEND_TIMEOUT"})
    scene.path.write_text(json.dumps(record))
    scene.client.request_receipt["status"] = "running"
    scene.client.task_receipt["status"] = "running"
    payload = scene.payload.model_dump()
    payload["targets"][0]["localOnly"] = local_only
    preview = await scene.service.preview(CleanupPreview(**payload))
    assert preview["items"][0]["status"] == "blocked" and scene.path.exists()
    assert "运行" in preview["items"][0]["reason"]
    assert scene.client.reads == [("request", {"client_request_id": "launcher-assistant:dispatch-1"}),
                                  ("task", {"task_id": "eat-1"})]
    assert scene.client.calls == 0 and not scene.service._marker_path(scene.payload.targets[0]).exists()


@pytest.fixture
def unbound_scene(scene):
    record = json.loads(scene.path.read_text())
    record.update(nativeTaskId="", receipt=None, status="failed", lastError={"code": "BACKEND_TIMEOUT"})
    scene.path.write_text(json.dumps(record))
    return scene


@pytest.mark.anyio
@pytest.mark.parametrize("local_only", [False, True])
@pytest.mark.parametrize("stage", ["diagnostics", "request", "task"])
@pytest.mark.parametrize("code", ["UNKNOWN_REQUEST", "TASK_NOT_FOUND", "BACKEND_TIMEOUT", "BACKEND_UNAVAILABLE"])
async def test_unbound_cleanup_never_treats_request_or_credential_failure_as_non_admission(unbound_scene, local_only, stage, code):
    scene = unbound_scene

    async def unavailable(*args, **kwargs):
        raise BackendClientError("private credential and path", code=code)

    if stage == "diagnostics":
        scene.service.dispatch._call = unavailable
    elif stage == "request":
        scene.client.get_task_for_request = unavailable
    else:
        scene.client.get_task = unavailable
    payload = scene.payload.model_dump()
    payload["targets"][0]["localOnly"] = local_only
    preview = await scene.service.preview(CleanupPreview(**payload))
    assert preview["items"][0]["status"] == "blocked" and scene.path.exists()
    assert "private" not in json.dumps(preview) and scene.client.calls == 0
    assert not scene.service._marker_path(scene.payload.targets[0]).exists()
    if code in {"UNKNOWN_REQUEST", "TASK_NOT_FOUND"}:
        assert "受理或结束" in preview["items"][0]["reason"]


@pytest.mark.anyio
@pytest.mark.parametrize("local_only", [False, True])
@pytest.mark.parametrize("request_id", [None, "other", "launcher-assistant:other"])
async def test_unbound_cleanup_requires_the_original_dispatch_request_identity(unbound_scene, local_only, request_id):
    scene = unbound_scene
    record = json.loads(scene.path.read_text())
    record["clientRequestId"] = request_id
    scene.path.write_text(json.dumps(record))
    payload = scene.payload.model_dump()
    payload["targets"][0]["localOnly"] = local_only
    preview = await scene.service.preview(CleanupPreview(**payload))
    assert preview["items"][0]["status"] == "blocked" and scene.path.exists()
    assert "原请求标识" in preview["items"][0]["reason"] and scene.client.reads == []


@pytest.mark.anyio
@pytest.mark.parametrize("local_only", [False, True])
@pytest.mark.parametrize("value", [None, {}, {"taskId": ""}, {"taskId": "../foreign"}])
async def test_unbound_cleanup_rejects_unverifiable_request_responses(unbound_scene, local_only, value):
    scene = unbound_scene

    async def malformed(**kwargs):
        return value

    scene.client.get_task_for_request = malformed
    payload = scene.payload.model_dump()
    payload["targets"][0]["localOnly"] = local_only
    preview = await scene.service.preview(CleanupPreview(**payload))
    assert preview["items"][0]["status"] == "blocked" and scene.path.exists()
    assert scene.client.reads == [] and scene.client.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("local_only", [False, True])
@pytest.mark.parametrize("change", ["active", "task_id", "agent_id"])
async def test_unbound_cleanup_rechecks_authoritative_task_identity_and_state_before_removing_reference(unbound_scene, local_only, change):
    scene = unbound_scene
    payload = scene.payload.model_dump()
    payload["targets"][0]["localOnly"] = local_only
    payload = CleanupPreview(**payload)
    preview = await scene.service.preview(payload)
    assert preview["items"][0]["status"] == "ready"
    if change == "active":
        scene.client.task_receipt["status"] = "running"
    elif change == "task_id":
        scene.client.request_receipt["taskId"] = scene.client.task_receipt["taskId"] = "eat-other"
    else:
        scene.client.task_receipt["agentId"] = "other-agent"
    result = await scene.service.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "blocked" and scene.path.exists()
    assert scene.client.calls == 0 and not scene.service._marker_path(scene.payload.targets[0]).exists()


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["project_lock", "request"])
async def test_unbound_cleanup_read_budget_includes_project_admission_and_preserves_reference(unbound_scene, monkeypatch, stage):
    import time
    from core.assistant_runtime import task_cleanup
    scene = unbound_scene
    monkeypatch.setattr(task_cleanup, "_REQUEST_PROOF_BUDGET", 0.03)

    async def slow(*args, **kwargs):
        await anyio.sleep(1)

    if stage == "project_lock":
        scene.service.dispatch._call = slow
    else:
        scene.client.get_task_for_request = slow
    started = time.monotonic()
    preview = await scene.service.preview(scene.payload)
    assert time.monotonic() - started < 1
    assert preview["items"][0]["status"] == "blocked" and scene.path.exists()
    assert "未及时响应" in preview["items"][0]["reason"] and scene.client.calls == 0


@pytest.fixture
def management_scene(scene):
    writes, reads = [], []
    run = {"teamId": "team-1", "flowId": "flow-1", "runId": "run-1", "revision": 3, "status": "completed"}

    class Client:
        async def management_action(self, **values):
            writes.append(values)
            return self.result(values)

        async def management_receipt(self, **values):
            reads.append(values)
            return self.result(values)

        @staticmethod
        def result(values):
            return {"action": values["action"], "requestId": values["request_id"], "verified": True,
                    "status": "completed", "teamRun": dict(run),
                    "flow": {**run, "action": "flow_start", "verified": True}}

        async def management_runtime(self, operation, **values):
            assert operation == "get" and values["resource_id"] == run["runId"]
            return {"operation": {"kind": "team_run", "resourceId": run["runId"], **run}}

    client = Client()

    async def call(project_id, operation):
        assert project_id in {"project-1", "project-2"}
        return await operation(client)

    profile = scene.root / "profile"
    projects = {"project-1": scene.root, "project-2": scene.root / "other"}
    adapter = ManagementAdapter(profile, projects, call, read_binding=scene.service.dispatch._project_read_binding)
    scene.service.dispatch.management = adapter
    return SimpleNamespace(adapter=adapter, service=scene.service, identity=scene.identity,
                           client=client, writes=writes, reads=reads, profile=profile, projects=projects)


async def _cleanup_management(case, action, local_only):
    await case.adapter.invoke("project-1", action=action, request_id="request-1", parameters={"goal": "private body"})
    payload = CleanupPreview(**case.identity, targets=[{"kind": "team_run", "projectId": "project-1",
        "requestId": "request-1", "originAction": action, "localOnly": local_only}])
    preview = await case.service.preview(payload)
    assert preview["items"][0]["status"] == "ready"
    result = await case.service.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"]))
    assert result["items"][0]["status"] == "deleted"
    marker = case.service._marker_path(payload.targets[0])
    path = case.adapter._root / (case.adapter._key("project-1", action, "request-1") + ".json")
    assert marker.is_file() and not path.exists()
    return marker, path


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["team_run", "flow_start"])
@pytest.mark.parametrize("local_only", [False, True])
async def test_cleaned_management_identity_cannot_replay_after_reload(management_scene, action, local_only):
    case = management_scene
    marker, path = await _cleanup_management(case, action, local_only)
    original = marker.read_bytes()
    read_count = len(case.reads)
    case.identity.update(agentId="assistant-new", directSessionId="session-new")
    restarted = ManagementAdapter(case.profile, case.projects, case.adapter._call)
    for parameters in ({"goal": "private body"}, {"goal": "changed body"}):
        with pytest.raises(DispatchError) as denied:
            await restarted.invoke("project-1", action=action, request_id="request-1", parameters=parameters)
        assert denied.value.code == "MANAGEMENT_ALREADY_CLEANED"
    assert len(case.writes) == 1 and len(case.reads) == read_count
    assert marker.read_bytes() == original and not path.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("local_only", [False, True])
async def test_cleaned_management_request_cannot_rebind_missing_sdk_credentials(management_scene, monkeypatch, local_only):
    case = management_scene
    marker, path = await _cleanup_management(case, "team_run", local_only)
    state = case.profile / "missing-sdk-state.json"
    sdk = ManagedAgentBackendClient(case.projects["project-1"], state_path=state)
    assert sdk._state["management"] == {} and not state.exists()
    sdk_calls = []

    async def unexpected(*args, **kwargs):
        sdk_calls.append((args, kwargs))
        pytest.fail("A cleaned request must not enter the SDK binding or native admission path")

    monkeypatch.setattr(sdk, "_request_json", unexpected)

    async def call(project_id, operation):
        return await operation(sdk)

    restarted = ManagementAdapter(case.profile, case.projects, call)
    with pytest.raises(DispatchError) as denied:
        await restarted.invoke("project-1", action="team_run", request_id="request-1", parameters={"goal": "private body"})
    assert denied.value.code == "MANAGEMENT_ALREADY_CLEANED"
    assert sdk_calls == [] and sdk._state["management"] == {} and not state.exists()
    assert marker.is_file() and not path.exists() and len(case.writes) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["team_run", "flow_start"])
async def test_management_replay_waiting_for_cleanup_rechecks_fence_under_same_lock(management_scene, monkeypatch, action):
    case = management_scene
    await case.adapter.invoke("project-1", action=action, request_id="request-1", parameters={"goal": "private body"})
    payload = CleanupPreview(**case.identity, targets=[{"kind": "team_run", "projectId": "project-1",
        "requestId": "request-1", "originAction": action}])
    preview = await case.service.preview(payload)
    reading, release = anyio.Event(), anyio.Event()
    original = case.client.management_receipt

    async def paused(**values):
        reading.set()
        await release.wait()
        return await original(**values)

    monkeypatch.setattr(case.client, "management_receipt", paused)
    results = []

    async def cleanup():
        results.append(await case.service.execute(CleanupExecute(**payload.model_dump(), fingerprint=preview["fingerprint"])))

    async def replay():
        with pytest.raises(DispatchError) as denied:
            await case.adapter.invoke("project-1", action=action, request_id="request-1", parameters={"goal": "private body"})
        assert denied.value.code == "MANAGEMENT_ALREADY_CLEANED"

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(cleanup)
            await reading.wait()
            tasks.start_soon(replay)
            lock = case.adapter._locks[case.adapter._key("project-1", action, "request-1")]
            while lock.statistics().tasks_waiting != 1:
                await anyio.sleep(0)
            release.set()
    assert results[0]["items"][0]["status"] == "deleted" and len(case.writes) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("content", ["{}", "not json", '{"schemaVersion":0,"agentId":"old-assistant"}',
    '{"projectId":"other","requestId":"other","originAction":"flow_start"}'])
async def test_existing_management_cleanup_marker_is_consumed_even_if_legacy_or_invalid(management_scene, content):
    case = management_scene
    key = case.adapter._key("project-1", "team_run", "request-1")
    marker = case.adapter._root / "cleanup_tombstones" / (key + ".json")
    marker.parent.mkdir(parents=True)
    marker.write_text(content, encoding="utf-8")
    with pytest.raises(DispatchError) as denied:
        await case.adapter.invoke("project-1", action="team_run", request_id="request-1", parameters={})
    assert denied.value.code == "MANAGEMENT_ALREADY_CLEANED"
    assert marker.read_text(encoding="utf-8") == content and case.writes == case.reads == []
    assert not (case.adapter._root / (key + ".json")).exists()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["directory", "dangling_marker", "linked_marker", "linked_parent"])
async def test_management_cleanup_marker_links_and_nonfiles_never_admit_new_writes(management_scene, kind):
    case = management_scene
    key = case.adapter._key("project-1", "team_run", "request-1")
    marker = case.adapter._root / "cleanup_tombstones" / (key + ".json")
    marker.parent.mkdir(parents=True)
    outside = case.profile / "outside"
    if kind == "directory":
        marker.mkdir()
    else:
        if kind == "linked_marker":
            outside.write_text("{}", encoding="utf-8")
        elif kind == "linked_parent":
            outside.mkdir()
            marker.parent.rmdir()
        try:
            if kind == "linked_parent":
                marker.parent.symlink_to(outside, target_is_directory=True)
            else:
                marker.symlink_to(outside)
        except OSError:
            pytest.skip("This host does not permit creation of fixture symlinks")
    with pytest.raises(DispatchError) as denied:
        await case.adapter.invoke("project-1", action="team_run", request_id="request-1", parameters={})
    assert denied.value.code == ("MANAGEMENT_STATE_INVALID" if kind == "linked_parent" else "MANAGEMENT_ALREADY_CLEANED")
    assert case.writes == case.reads == [] and not (case.adapter._root / (key + ".json")).exists()


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["marker_denied", "parent_denied", "parent_reparse", "parent_non_directory"])
async def test_management_cleanup_fence_cannot_treat_unsafe_or_unreadable_path_as_absent(management_scene, monkeypatch, fault):
    from pathlib import Path

    case = management_scene
    key = case.adapter._key("project-1", "team_run", "request-1")
    marker = case.adapter._root / "cleanup_tombstones" / (key + ".json")
    marker.parent.mkdir(parents=True)
    target = marker if fault == "marker_denied" else marker.parent
    original = Path.lstat

    def unavailable(path, *args, **kwargs):
        if path == target:
            if fault.endswith("denied"):
                raise PermissionError("private local path must not escape")
            info = original(path, *args, **kwargs)
            return SimpleNamespace(st_mode=info.st_mode if fault == "parent_reparse" else 0,
                                   st_file_attributes=0x400 if fault == "parent_reparse" else 0)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", unavailable)
    with pytest.raises(DispatchError) as denied:
        await case.adapter.invoke("project-1", action="team_run", request_id="request-1", parameters={})
    assert denied.value.code == "MANAGEMENT_STATE_INVALID" and "private" not in str(denied.value)
    assert case.writes == case.reads == [] and not (case.adapter._root / (key + ".json")).exists()


@pytest.mark.anyio
async def test_management_cleanup_fence_preserves_other_request_scopes_and_receipt_reads(management_scene):
    case = management_scene
    await case.adapter.invoke("project-1", action="team_run", request_id="request-1", parameters={})
    # A crash after the marker write can leave the original association behind.
    key = case.adapter._key("project-1", "team_run", "request-1")
    marker = case.adapter._root / "cleanup_tombstones" / (key + ".json")
    marker.parent.mkdir()
    marker.write_text("{}", encoding="utf-8")
    with pytest.raises(DispatchError) as denied:
        await case.adapter.invoke("project-1", action="team_run", request_id="request-1", parameters={})
    assert denied.value.code == "MANAGEMENT_ALREADY_CLEANED"
    result = await case.adapter.receipt("project-1", action="team_run", request_id="request-1")
    assert result["verified"] is True and len(case.writes) == 1 and len(case.reads) == 1
    for project_id, action, request_id in (("project-2", "team_run", "request-1"),
            ("project-1", "flow_start", "request-1"), ("project-1", "team_run", "request-2")):
        await case.adapter.invoke(project_id, action=action, request_id=request_id, parameters={})
        await case.adapter.invoke(project_id, action=action, request_id=request_id, parameters={})
    assert len(case.writes) == 4 and len(case.reads) == 4
    assert all(row["require_existing_subject"] is False for row in case.writes)
