"""Legacy Launcher cleanup contracts using isolated Session/task fixtures."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.services.external_agent.service import ExternalAgentAccessError, ExternalAgentConflictError
from core.web.services.external_agent.store import ExternalAgentTaskConflictError, ExternalAgentTaskStore
from core.web.services.local_assistant import legacy_cleanup, task_cleanup as cleanup
from tests.test_external_agent_task_service import FakeRuntime, _service
from tests.test_local_assistant_task_cleanup import OWNER, task as local_task

CLIENT_REQUEST_ID = "launcher-assistant:legacy-dispatch"


@pytest.fixture
def legacy_task(local_task, monkeypatch):
    task = local_task
    task.local_service = task.service
    store = legacy_cleanup.LegacyAssistantCleanupTaskStore(task.tmp / "runtime" / "external_agents")
    record = dict(task.record)
    record.pop("localAuthorityFingerprint")
    record.pop("localWorkspacePath")
    record.update(clientRequestId=CLIENT_REQUEST_ID, error={"code": "FIXTURE", "message": "private error"})
    store._write_locked(record)
    task.local_service.store.task_path(record["taskId"]).unlink()
    task.service = legacy_cleanup.LegacyAssistantCleanupService(store, project_root=task.project,
        authority_fingerprint=task.local_service.authority_fingerprint, dependencies=task.local_service.dependencies)
    task.record = record
    # The API builder imports this resolver directly; pin that binding as well
    # as the engine's dynamic resolver already pinned by the reused fixture.
    monkeypatch.setattr(legacy_cleanup, "resolve_project_runtime_home", lambda project: task.tmp / "runtime")
    return task


def preview(task):
    return cleanup.preview_task_cleanup(task.service, owner_id=OWNER, task_id=task.record["taskId"])


def execute(task, snapshot=None):
    snapshot = snapshot or preview(task)
    return cleanup.cleanup_task(task.service, owner_id=OWNER, task_id=task.record["taskId"],
        revision=snapshot["revision"], fingerprint=snapshot["fingerprint"])


def request_kwargs(task, **patch):
    return {"owner_id": OWNER, "agent_id": task.record["agentId"], "task_digest": task.record["taskDigest"],
        "client_request_id": CLIENT_REQUEST_ID, "request_digest": task.record["requestDigest"],
        "permission_profile": "workspace_write", "lease_seconds": 30, "adapter_connection_id": "connection",
        "runtime_revision": "a" * 40, **patch}


def logical_bytes(task):
    # The completion stub and original record are the same path, counted once.
    paths = [task.service.store.task_path(task.record["taskId"]), *task.directory.rglob("*")]
    return sum(path.stat().st_size for path in paths if path.is_file())


def test_cleanup_removes_exclusive_session_files_and_keeps_content_free_terminal_stub(legacy_task):
    task = legacy_task
    snapshot = preview(task)
    before = logical_bytes(task)
    assert snapshot["status"] == "ready" and snapshot["estimatedBytes"] > 300
    assert task.state["calls"] == []

    result = execute(task, snapshot)

    assert result["status"] == "deleted" and result["releasedBytes"] > 0
    assert result["releasedBytes"] == max(0, before - logical_bytes(task))
    assert task.state["calls"] == ["session-1"]
    assert sorted(path.name for path in task.directory.iterdir()) == [".session_deleted", "session_admission.lock"]
    path = task.service.store.task_path(task.record["taskId"])
    assert path.is_file() and task.service.store.tombstone_path(task.record["taskId"]) == path
    stub = ExternalAgentTaskStore(task.service.store.root).get_task(task.record["taskId"])
    assert stub["status"] == "succeeded" and stub["localCleanupComplete"] is True
    assert stub["ownerSubjectHash"] == task.record["ownerSubjectHash"]
    assert stub["clientRequestId"] == CLIENT_REQUEST_ID and stub["requestDigest"] == "request-digest"
    assert not {"sessionId", "turnId", "resultSummary", "error", "localWorkspacePath"}.intersection(stub)
    assert "private result" not in path.read_text() and "private error" not in path.read_text()
    assert (task.project / "user.txt").read_text() == "user source"


@pytest.fixture
def absent_legacy_task(legacy_task, monkeypatch):
    from core.web.services.session import directory_runtime

    task = legacy_task
    task.state["raw"] = None
    (task.directory / "turn_journal.jsonl").unlink()
    task.directory_row = None
    task.directory_children = []
    task.directory_runtime_row = None
    task.pin_current = True
    task.pin_generation = 1
    task.directory_store = SimpleNamespace(repository=SimpleNamespace(
        get_session=lambda *args, **kwargs: task.directory_row,
        get_session_runtime_state=lambda *args: task.directory_runtime_row,
        list_child_sessions=lambda *args: task.directory_children))
    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: task.directory_store)
    monkeypatch.setattr(directory_runtime, "pin_open_directory_store", lambda root:
        SimpleNamespace(store=task.directory_store, generation=task.pin_generation) if task.directory_store else None)
    monkeypatch.setattr(directory_runtime, "directory_store_pin_is_current", lambda pin:
        task.pin_current and pin.store is task.directory_store)
    return task


def test_absent_native_session_with_only_guards_cleans_legacy_record_without_native_mutation(absent_legacy_task):
    task = absent_legacy_task
    snapshot = preview(task)
    assert snapshot["status"] == "ready"
    assert [row["kind"] for row in snapshot["resources"]] == ["task_record"]

    result = execute(task, snapshot)

    assert result["status"] == "deleted" and result["releasedBytes"] > 0
    assert task.state["calls"] == [] and task.state["raw"] is None
    assert sorted(path.name for path in task.directory.iterdir()) == ["session_admission.lock"]
    stub = task.service.store.get_task(task.record["taskId"])
    assert stub["localCleanupComplete"] is True and "sessionId" not in stub
    assert execute(task)["alreadyDeleted"] is True


@pytest.mark.parametrize("change", ["content", "directory_row", "directory_unavailable", "directory_child",
    "family_child", "direct", "work_run", "shared_task", "runtime_row", "pin_changed", "running", "stopping"])
def test_absent_session_requires_no_content_and_complete_exclusive_absence_proof(absent_legacy_task, change):
    task = absent_legacy_task
    if change == "content":
        (task.directory / "unowned.txt").write_text("unowned content")
    elif change == "directory_row":
        task.directory_row = {"agentId": "coder"}
    elif change == "directory_unavailable":
        task.directory_store = None
    elif change == "directory_child":
        task.directory_children = [{"sessionId": "child"}]
    elif change == "family_child":
        task.state["others"] = [{"conversation_id": "child", "parent_session_id": "session-1"}]
    elif change == "direct":
        task.state["agents"] = [{"directSessionId": "session-1"}]
    elif change == "work_run":
        task.state["active"] = True
    elif change == "runtime_row":
        task.directory_runtime_row = {"conversation_id": "session-1"}
    elif change == "pin_changed":
        task.pin_current = False
    elif change in {"running", "stopping"}:
        task.state["phase"] = change
    else:
        store = ExternalAgentTaskStore(task.tmp / "runtime" / "local_assistant_tasks")
        other, _ = store.create_task(**request_kwargs(task, client_request_id="another-request"))
        store.transition(other["taskId"], status="running", fields={"sessionId": "session-1"})

    assert preview(task)["status"] == "blocked"
    assert execute(task)["status"] == "blocked"
    assert task.state["calls"] == []
    assert not task.service.store.get_task(task.record["taskId"]).get("localCleanupComplete")


def test_absent_session_proof_is_fingerprinted_and_cannot_delete_a_reappeared_session(absent_legacy_task):
    task = absent_legacy_task
    snapshot = preview(task)
    assert snapshot["status"] == "ready"
    task.state["raw"] = {"conversation_id": "session-1", "agent_id": "coder", "conversation_index_kind": "hidden",
        "metadata": {"source": "external_agent_task", "externalTaskId": task.record["taskId"]}}

    with pytest.raises(ExternalAgentConflictError) as error:
        execute(task, snapshot)

    assert error.value.code == "CLEANUP_STALE" and task.state["calls"] == []


def test_absent_session_compatibility_does_not_change_local_task_policy(absent_legacy_task):
    task = absent_legacy_task
    record = {**task.record, "localAuthorityFingerprint": "a" * 64}
    task.local_service.store._write_locked(record)

    result = cleanup.preview_task_cleanup(task.local_service, owner_id=OWNER, task_id=record["taskId"])

    assert result["status"] == "blocked" and task.state["calls"] == []


def test_absent_session_preview_is_stale_after_directory_store_generation_changes(absent_legacy_task):
    task = absent_legacy_task
    snapshot = preview(task)
    task.pin_generation += 1

    with pytest.raises(ExternalAgentConflictError) as error:
        execute(task, snapshot)

    assert error.value.code == "CLEANUP_STALE" and task.state["calls"] == []
    assert not task.service.store.get_task(task.record["taskId"]).get("localCleanupComplete")


def test_absent_session_rechecks_directory_pin_after_accounting_before_any_write(absent_legacy_task, monkeypatch):
    task = absent_legacy_task
    snapshot = preview(task)
    original = cleanup._accounting_snapshot

    def accounting(*args):
        result = original(*args)
        task.pin_current = False
        return result

    monkeypatch.setattr(cleanup, "_accounting_snapshot", accounting)
    with pytest.raises(ExternalAgentConflictError) as error:
        execute(task, snapshot)

    assert error.value.code == "CLEANUP_OWNER_CHANGED" and task.state["calls"] == []
    record = task.service.store.get_task(task.record["taskId"])
    assert not record.get("localCleanupComplete") and not record.get("localCleanupSessionDeleted")


def test_original_external_store_replays_same_request_and_rejects_changed_digest_after_cleanup(legacy_task):
    task = legacy_task
    execute(task)
    store = ExternalAgentTaskStore(task.service.store.root)

    replay, created = store.create_task(**request_kwargs(task))

    assert created is False and replay["taskId"] == task.record["taskId"]
    assert replay["status"] == "succeeded" and replay["localCleanupComplete"] is True
    with pytest.raises(ExternalAgentTaskConflictError, match="another request"):
        store.create_task(**request_kwargs(task, request_digest="changed-request-digest"))
    assert len(list(store.tasks_dir.glob("eat-*.json"))) == 1
    assert task.state["calls"] == ["session-1"]


def test_retry_reports_already_deleted_without_releasing_bytes_or_deleting_session_again(legacy_task):
    task = legacy_task
    execute(task)
    before = logical_bytes(task)

    snapshot = preview(task)
    result = execute(task, snapshot)

    assert snapshot["alreadyDeleted"] is True and snapshot["status"] == "ready"
    assert snapshot["resources"] == [] and snapshot["estimatedBytes"] == 0
    assert result["status"] == "deleted" and result["alreadyDeleted"] is True and result["releasedBytes"] == 0
    assert logical_bytes(task) == before and task.state["calls"] == ["session-1"]


def test_authority_rotation_during_native_delete_cannot_reassign_completed_receipt(legacy_task):
    task = legacy_task
    original_delete = task.native.delete_chat_session_lightweight

    def delete_and_rotate(*args, **kwargs):
        result = original_delete(*args, **kwargs)
        task.service.authority_fingerprint = lambda: "b" * 64
        return result

    task.native.delete_chat_session_lightweight = delete_and_rotate

    result = execute(task)

    assert result["status"] == "deleted" and task.state["calls"] == ["session-1"]
    stub = task.service.store.get_task(task.record["taskId"])
    assert stub["localCleanupComplete"] is True and stub["localAuthorityFingerprint"] == "a" * 64
    with pytest.raises(ExternalAgentAccessError):
        preview(task)
    with pytest.raises(ExternalAgentAccessError):
        cleanup.cleanup_task(task.service, owner_id=OWNER, task_id=task.record["taskId"],
            revision=stub["cleanupRevision"], fingerprint=stub["cleanupFingerprint"])
    task.service.authority_fingerprint = lambda: "a" * 64
    snapshot = preview(task)
    assert snapshot["alreadyDeleted"] is True
    retry = execute(task, snapshot)
    assert retry["alreadyDeleted"] is True and retry["releasedBytes"] == 0
    assert task.state["calls"] == ["session-1"]


@pytest.mark.parametrize("change", ["revision", "session_content"])
def test_execute_rejects_preview_after_task_or_session_snapshot_changes(legacy_task, change):
    task = legacy_task
    snapshot = preview(task)
    if change == "revision":
        task.service.store.transition(task.record["taskId"], status="succeeded")
    else:
        (task.directory / "turn_journal.jsonl").write_bytes(b"changed session content")
    before = logical_bytes(task)

    with pytest.raises(ExternalAgentConflictError) as error:
        execute(task, snapshot)

    assert error.value.code == "CLEANUP_STALE"
    assert logical_bytes(task) == before and task.state["calls"] == []
    assert (task.directory / "turn_journal.jsonl").is_file()
    assert not task.service.store.get_task(task.record["taskId"]).get("localCleanupComplete")


@pytest.mark.parametrize("failure", ["session_unlink", "finish_cleanup"])
def test_partial_cleanup_preserves_original_record_and_retries_only_remaining_files(legacy_task, monkeypatch, failure):
    task = legacy_task
    journal = task.directory / "turn_journal.jsonl"
    cache = task.directory / "00-cache.bin"
    cache.write_bytes(b"x" * 4096)
    record_path = task.service.store.task_path(task.record["taskId"])
    original_unlink, original_json = Path.unlink, legacy_cleanup._atomic_json
    unlinks = []
    finalizations = []

    def unlink(path, *args, **kwargs):
        if path in (cache, journal):
            unlinks.append(path)
        if failure == "session_unlink" and path == journal and unlinks.count(journal) == 1:
            raise PermissionError("fixture session lock")
        return original_unlink(path, *args, **kwargs)

    def finalize(path, payload):
        finalizations.append(path)
        if failure == "finish_cleanup" and len(finalizations) == 1:
            raise PermissionError("fixture receipt lock")
        return original_json(path, payload)

    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(legacy_cleanup, "_atomic_json", finalize)
    snapshot = preview(task)
    before = logical_bytes(task)

    partial = execute(task, snapshot)

    assert partial["status"] == "partial" and partial["releasedBytes"] > 0
    assert partial["releasedBytes"] == max(0, before - logical_bytes(task))
    assert task.state["raw"] is None and task.state["calls"] == ["session-1"]
    record = task.service.store.get_task(task.record["taskId"])
    assert record_path.is_file() and record["localCleanupStatus"] == "partial"
    assert record["localCleanupSessionDeleted"] is True and not record.get("localCleanupComplete")
    assert record["sessionId"] == "session-1" and record["resultSummary"] == "private result"
    assert record["error"]["message"] == "private error"
    assert not cache.exists() and journal.exists() is (failure == "session_unlink")
    assert {"kind": "session" if failure == "session_unlink" else "task_record", "reason": "PermissionError"} in partial["failures"]

    retry_snapshot = preview(task)
    assert retry_snapshot["status"] == "ready" and not retry_snapshot.get("alreadyDeleted", False)
    retry = execute(task, retry_snapshot)

    assert retry["status"] == "deleted" and task.state["calls"] == ["session-1"]
    assert unlinks.count(cache) == 1 and unlinks.count(journal) == (2 if failure == "session_unlink" else 1)
    assert len(finalizations) == (1 if failure == "session_unlink" else 2)
    stub = task.service.store.get_task(task.record["taskId"])
    assert stub["localCleanupComplete"] is True
    assert not {"sessionId", "resultSummary", "error"}.intersection(stub)
    replay = execute(task)
    assert replay["alreadyDeleted"] is True and replay["releasedBytes"] == 0
    assert task.state["calls"] == ["session-1"]


def test_ordinary_service_replay_uses_terminal_stub_without_touching_native_session_dependencies(legacy_task):
    task = legacy_task
    original_task = "legacy task"
    digest = lambda value: "sha256:" + sha256(value.encode("utf-8")).hexdigest()
    record = task.service.store.get_task(task.record["taskId"])
    record.update(taskDigest=digest(original_task), requestDigest=digest(json.dumps({
        "agentId": "coder", "taskDigest": digest(original_task), "permissionProfile": "workspace_write", "title": "",
    }, sort_keys=True, ensure_ascii=False)))
    task.service.store._write_locked(record)
    execute(task)
    runtime = FakeRuntime()
    service = _service(task.service.store.root, runtime)

    def unexpected_native(*args, **kwargs):
        pytest.fail("cleaned request replay must not access native Session dependencies")

    service.dependencies = replace(service.dependencies, create_session=unexpected_native,
        submit_message=unexpected_native, get_session_detail=unexpected_native, list_approvals=unexpected_native,
        resolve_approval=unexpected_native, stop_turn=unexpected_native)
    kwargs = {"owner_id": OWNER, "adapter_connection_id": "connection", "capabilities": set(), "agent_id": "coder",
        "task": original_task, "permission_profile": "workspace_write", "client_request_id": CLIENT_REQUEST_ID,
        "title": "", "runtime_revision": "a" * 40}

    replay = service.start_task(**kwargs)

    assert replay["taskId"] == task.record["taskId"] and replay["status"] == "succeeded"
    assert replay["shouldPoll"] is False and replay["resultSummary"] == "" and replay["error"] is None
    with pytest.raises(ExternalAgentConflictError) as error:
        service.start_task(**{**kwargs, "task": "different task"})
    assert error.value.code == "TASK_CONFLICT"
    assert runtime.create_calls == [] and runtime.submit_calls == [] and task.state["calls"] == ["session-1"]
    assert len(list(service.store.tasks_dir.glob("eat-*.json"))) == 1


@pytest.mark.parametrize("store_name", ["local_assistant_tasks", "external_agents"])
def test_other_task_in_either_store_sharing_session_blocks_cleanup(legacy_task, store_name):
    task = legacy_task
    store = ExternalAgentTaskStore(task.tmp / "runtime" / store_name)
    other, _ = store.create_task(**request_kwargs(task, client_request_id="other-client-request"))
    store.transition(other["taskId"], status="running", fields={"sessionId": "session-1"})

    snapshot = preview(task)
    result = execute(task, snapshot)

    assert snapshot["status"] == "blocked" and snapshot["resources"] == []
    assert result["status"] == "blocked" and result["releasedBytes"] == 0
    assert {"kind": "session", "reason": "session_shared_by_task"} in result["failures"]
    assert (task.directory / "turn_journal.jsonl").is_file() and task.state["calls"] == []
    assert not task.service.store.get_task(task.record["taskId"]).get("localCleanupComplete")


@pytest.mark.parametrize("request_id", ["external-client", "launcher-assistant-other:dispatch", "launcher-assistant:", "launcher-assistant: "])
def test_non_launcher_or_empty_legacy_request_prefix_cannot_authorize_cleanup(legacy_task, request_id):
    task = legacy_task
    record = task.service.store.get_task(task.record["taskId"])
    record["clientRequestId"] = request_id
    task.service.store._write_locked(record)

    with pytest.raises(ExternalAgentAccessError):
        preview(task)

    assert (task.directory / "turn_journal.jsonl").is_file() and task.state["calls"] == []


@pytest.mark.parametrize("change", ["foreign_owner", "missing_authority", "running", "queued", "awaiting_approval", "cancelling", "stop_unconfirmed"])
def test_foreign_owner_missing_authority_and_nonterminal_tasks_are_rejected(legacy_task, change):
    task = legacy_task
    if change == "missing_authority":
        task.service.authority_fingerprint = lambda: ""
    elif change != "foreign_owner":
        record = task.service.store.get_task(task.record["taskId"])
        record["status"] = change
        task.service.store._write_locked(record)

    with pytest.raises((ExternalAgentAccessError, ExternalAgentConflictError)):
        cleanup.preview_task_cleanup(task.service, owner_id="other-owner" if change == "foreign_owner" else OWNER,
            task_id=task.record["taskId"])

    assert (task.directory / "turn_journal.jsonl").is_file() and task.state["calls"] == []


@pytest.mark.parametrize("change", ["visible", "agent", "task", "source"])
def test_session_visibility_agent_and_provenance_must_match_legacy_task(legacy_task, change):
    task = legacy_task
    if change == "visible":
        task.state["raw"]["conversation_index_kind"] = "user_chat"
    elif change == "agent":
        task.state["raw"]["agent_id"] = "other-agent"
    elif change == "task":
        task.state["raw"]["metadata"]["externalTaskId"] = "eat-other"
    else:
        task.state["raw"]["metadata"]["source"] = "ordinary_chat"

    snapshot = preview(task)
    result = execute(task, snapshot)

    assert snapshot["status"] == "blocked" and result["status"] == "blocked"
    assert result["releasedBytes"] == 0 and task.state["calls"] == []
    assert (task.directory / "turn_journal.jsonl").is_file()


@pytest.mark.parametrize("field", ["localWorkspacePath", "localCleanupWorkspacePath", "workspacePath", "workingDirectory"])
def test_external_record_and_session_workspace_paths_never_authorize_workspace_deletion(legacy_task, monkeypatch, field):
    task = legacy_task
    workspace = task.project / ".worktrees" / ("assistant-" + task.record["taskId"])
    workspace.mkdir(parents=True)
    sentinel = workspace / "user-source.txt"
    sentinel.write_text("unowned workspace data", encoding="utf-8")
    record = task.service.store.get_task(task.record["taskId"])
    record[field] = str(workspace)
    task.service.store._write_locked(record)
    task.state["raw"]["working_directory"] = str(workspace)
    monkeypatch.setattr(cleanup, "_git", lambda *args, **kwargs: pytest.fail("legacy records cannot authorize Git cleanup"))

    result = execute(task)

    assert result["status"] == "deleted" and task.state["calls"] == ["session-1"]
    assert sentinel.read_text() == "unowned workspace data"
    assert {"kind": "workspace", "reason": "legacy_workspace_not_owned"} in result["retained"]


def test_legacy_routes_require_control_launcher_owner_and_prefix_and_support_cleanup_retry(legacy_task, monkeypatch):
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import local_assistant_tasks

    task = legacy_task
    monkeypatch.setattr(local_assistant_tasks, "verify_launcher_authority", lambda value: value == "launcher-secret")
    monkeypatch.setattr(local_assistant_tasks, "local_service", lambda: task.local_service)
    task.local_service.authority_fingerprint = lambda: cleanup.hashlib.sha256(b"launcher-secret").hexdigest()
    app = FastAPI()
    app.include_router(local_assistant_tasks.router, prefix="/api")
    path = "/api/local-assistant/v1/external-agent/legacy-tasks/" + task.record["taskId"] + "/cleanup"
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), "X-Vibelution-Management-Subject": "launcher-local",
        "X-Vibelution-Management-Capability": "launcher-secret", "X-Vibelution-External-Agent-Task-Capability": OWNER}
    with TestClient(app) as client:
        rejected_body = {"revision": 1, "fingerprint": "a" * 64}
        for missing in (CONTROL_TOKEN_HEADER, "X-Vibelution-Management-Subject", "X-Vibelution-Management-Capability",
                        "X-Vibelution-External-Agent-Task-Capability"):
            for suffix in ("/preview", ""):
                assert client.post(path + suffix, headers={key: value for key, value in headers.items() if key != missing},
                    json=rejected_body).status_code == 403
        for key in (CONTROL_TOKEN_HEADER, "X-Vibelution-Management-Subject", "X-Vibelution-Management-Capability"):
            for suffix in ("/preview", ""):
                assert client.post(path + suffix, headers={**headers, key: "invalid-fixture-credential"},
                    json=rejected_body).status_code == 403
        wrong = {**headers, "X-Vibelution-External-Agent-Task-Capability": "another-owner"}
        assert client.post(path + "/preview", headers=wrong).status_code == 404
        assert client.post(path, headers=wrong, json=rejected_body).status_code == 404
        record = task.service.store.get_task(task.record["taskId"])
        task.service.store._write_locked({**record, "clientRequestId": "ordinary-external-client"})
        assert client.post(path + "/preview", headers=headers).status_code == 404
        assert client.post(path, headers=headers, json=rejected_body).status_code == 404
        assert task.state["calls"] == [] and (task.directory / "turn_journal.jsonl").is_file()
        task.service.store._write_locked(record)

        response = client.post(path + "/preview", headers=headers)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        snapshot = response.json()
        assert snapshot["status"] == "ready"
        body = {"revision": snapshot["revision"], "fingerprint": snapshot["fingerprint"]}
        assert client.post(path, headers=headers, json={**body, "fingerprint": "x"}).status_code == 422
        assert client.post(path, headers=headers, json={**body, "fingerprint": "0" * 64}).status_code == 409
        result = client.post(path, headers=headers, json=body)
        assert result.status_code == 200 and result.json()["status"] == "deleted"
        assert result.headers["Cache-Control"] == "no-store"
        again = client.post(path + "/preview", headers=headers)
        assert again.status_code == 200 and again.json()["alreadyDeleted"] is True
        assert again.json()["resources"] == []
        retry = client.post(path, headers=headers, json={key: again.json()[key] for key in ("revision", "fingerprint")})
        assert retry.status_code == 200 and retry.json()["releasedBytes"] == 0
        assert client.post(path + "/preview", headers=wrong).status_code == 404
    assert task.state["calls"] == ["session-1"]
    replay, created = ExternalAgentTaskStore(task.service.store.root).create_task(**request_kwargs(task))
    assert created is False and replay["taskId"] == task.record["taskId"]
