"""Launcher-only irreversible cleanup, always using isolated disk fixtures."""
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.infrastructure import git_process
from core.web.services.external_agent.service import ExternalAgentAccessError, ExternalAgentConflictError
from core.web.services.external_agent.store import ExternalAgentTaskNotFoundError, ExternalAgentTaskStore
from core.web.services.local_assistant import task_cleanup as cleanup
from core.web.services.local_assistant.service import LocalAssistantTaskService
from tests.test_external_agent_task_service import FakeRuntime, _service

OWNER = "private-owner"


@pytest.fixture
def task(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    root = tmp_path / "sessions"
    root.mkdir()
    directory = root / "session-1"
    directory.mkdir()
    (directory / "turn_journal.jsonl").write_bytes(b"private transcript" * 20)
    (directory / "session_admission.lock").write_bytes(b"0")
    (project / "user.txt").write_text("user source", encoding="utf-8")
    runtime = FakeRuntime()
    dependencies = _service(tmp_path / "unused", runtime).dependencies
    service = LocalAssistantTaskService(cleanup.LocalAssistantCleanupTaskStore(tmp_path / "local"),
        project_root=project, authority_fingerprint=lambda: "a" * 64, dependencies=dependencies)
    record, _ = service.store.create_task(owner_id=OWNER, agent_id="coder", task_digest="task-digest",
        client_request_id="client-request", request_digest="request-digest", permission_profile="workspace_write",
        lease_seconds=30, adapter_connection_id="connection", runtime_revision="a" * 40)
    record = service.store.transition(record["taskId"], status="running", fields={
        "localAuthorityFingerprint": "a" * 64, "localWorkspacePath": str(project),
        "sessionId": "session-1", "turnId": "turn-1", "resultSummary": "private result"})
    record = service.store.transition(record["taskId"], status="succeeded")
    raw = {"conversation_id": "session-1", "agent_id": "coder", "conversation_index_kind": "hidden",
        "metadata": {"source": "external_agent_task", "externalTaskId": record["taskId"]}}
    state = {"raw": raw, "others": [], "agents": [], "phase": "idle", "active": False, "calls": []}
    native = SimpleNamespace(PROJECT_ROOT=project, _CHAT_STATE_LOCK=nullcontext(),
        _safe_session_workspace_token=lambda sid: sid, _agent_session_workspace_roots=lambda: [root],
        _session_submit_admit_lock=lambda sid: nullcontext(),
        load_session_chat_state=lambda project, sid: state["raw"],
        load_chat_state=lambda project: {"conversations": ([state["raw"]] if state["raw"] else []) + state["others"]},
        _delete_session_control_phase=lambda sid, raw: state["phase"],
        _is_session_workspace_intentionally_deleted=lambda sid: (directory / ".session_deleted").is_file(),
        agent_directory_service=SimpleNamespace(agent_session_lifecycle_transaction=lambda: nullcontext(),
            list_agents=lambda **kw: state["agents"]))
    def delete(sid, **kwargs):
        state["calls"].append(sid)
        state["raw"] = None
        (directory / ".session_deleted").write_text('{"deleted":true}', encoding="utf-8")
        return {"deleted": True}
    native.delete_chat_session_lightweight = delete
    monkeypatch.setattr(cleanup, "_native_session_service", lambda service: native)
    monkeypatch.setattr(cleanup, "_delete_session_control_phase", lambda sid, raw: state["phase"])
    from core.web.services.session import admission_lock
    monkeypatch.setattr(admission_lock, "session_has_active_work_run", lambda *args: state["active"])
    monkeypatch.setattr("vibelution_storage.resolve_project_runtime_home", lambda project: tmp_path / "runtime")
    return SimpleNamespace(service=service, record=record, native=native, state=state, directory=directory,
                           root=root, project=project, tmp=tmp_path)


def preview(task):
    return cleanup.preview_task_cleanup(task.service, owner_id=OWNER, task_id=task.record["taskId"])


def execute(task, snapshot=None):
    snapshot = snapshot or preview(task)
    return cleanup.cleanup_task(task.service, owner_id=OWNER, task_id=task.record["taskId"],
        revision=snapshot["revision"], fingerprint=snapshot["fingerprint"])


def _fixture_usage(task, *, include_session=True, workspace=None):
    paths = [task.service.store.task_path(task.record["taskId"]),
             task.service.store.tombstone_path(task.record["taskId"])]
    if include_session:
        paths.append(task.directory)
    if workspace is not None:
        paths.append(workspace)
    return sum(item.stat().st_size for path in paths if path.exists()
               for item in ([path] if path.is_file() else path.rglob("*")) if item.is_file())


def test_deletes_exclusive_files_and_record_preserves_small_guards_and_user_source(task):
    snapshot = preview(task)
    bytes_before = _fixture_usage(task)
    assert snapshot["schemaVersion"] == 1 and snapshot["estimatedBytes"] > 300
    assert task.state["calls"] == []
    result = execute(task, snapshot)
    assert result["releasedBytes"] == max(0, bytes_before - _fixture_usage(task))
    assert result["status"] == "deleted" and result["releasedBytes"] > 300
    assert task.state["calls"] == ["session-1"]
    assert sorted(path.name for path in task.directory.iterdir()) == [".session_deleted", "session_admission.lock"]
    assert (task.project / "user.txt").read_text() == "user source"
    with pytest.raises(ExternalAgentTaskNotFoundError):
        task.service.store.get_task(task.record["taskId"])
    tombstone_path = task.service.store.tombstone_path(task.record["taskId"])
    tombstone = tombstone_path.read_text()
    assert "private" not in tombstone and "resultSummary" not in tombstone and "client-request" not in tombstone
    retained = {item["kind"]: item for item in result["retained"]}
    assert retained["request_tombstone"]["bytes"] == tombstone_path.stat().st_size
    assert retained["session_guards"]["bytes"] == sum(path.stat().st_size for path in task.directory.iterdir())


def test_deleted_request_is_fenced_across_store_reload_without_affecting_external_store(task):
    execute(task)
    store = cleanup.LocalAssistantCleanupTaskStore(task.service.store.root)
    with pytest.raises(ExternalAgentConflictError, match="permanently cleaned"):
        store.find_idempotent(owner_id=OWNER, client_request_id="client-request")
    kwargs = dict(owner_id=OWNER, agent_id="coder", task_digest="digest", client_request_id="client-request",
        request_digest="digest", permission_profile="read_only", lease_seconds=30,
        adapter_connection_id="connection", runtime_revision="a" * 40)
    with pytest.raises(ExternalAgentConflictError):
        store.create_task(**kwargs)
    ordinary = ExternalAgentTaskStore(task.tmp / "ordinary")
    assert ordinary.create_task(**kwargs)[1] is True
    with pytest.raises(ExternalAgentConflictError):
        execute(task, {"revision": 1, "fingerprint": "a" * 64})
    completed = preview(task)
    assert completed["alreadyDeleted"] and completed["status"] == "ready" and completed["resources"] == []
    assert execute(task, completed)["releasedBytes"] == 0


def test_cleanup_receipt_keeps_admitted_authority_when_native_delete_rotates_it(task):
    original_delete = task.native.delete_chat_session_lightweight
    def rotate_after_delete(*args, **kwargs):
        result = original_delete(*args, **kwargs)
        task.service.authority_fingerprint = lambda: "b" * 64
        return result
    task.native.delete_chat_session_lightweight = rotate_after_delete

    assert execute(task)["status"] == "deleted"
    receipt = task.service.store._read_path(task.service.store.tombstone_path(task.record["taskId"]))
    assert receipt["localAuthorityFingerprint"] == "a" * 64
    with pytest.raises(ExternalAgentAccessError):
        preview(task)
    task.service.authority_fingerprint = lambda: "a" * 64
    assert preview(task)["alreadyDeleted"] is True


@pytest.mark.parametrize("change", ["owner", "authority", "running", "stop_unconfirmed"])
def test_rejects_foreign_revoked_or_nonterminal_task(task, change):
    record = task.service.store.get_task(task.record["taskId"])
    if change == "authority":
        task.service.authority_fingerprint = lambda: "b" * 64
    elif change != "owner":
        record["status"] = change
        task.service.store._write_locked(record)
    with pytest.raises((ExternalAgentAccessError, ExternalAgentConflictError)):
        cleanup.preview_task_cleanup(task.service, owner_id="other" if change == "owner" else OWNER,
                                     task_id=task.record["taskId"])
    assert (task.directory / "turn_journal.jsonl").exists()
    assert not task.state["calls"]


@pytest.mark.parametrize("change", ["task", "agent", "visible", "direct", "parent", "child", "active", "queued", "work_run", "shared_task", "external_task"])
def test_session_provenance_and_sharing_block_destructive_cleanup(task, change):
    if change == "task":
        task.state["raw"]["metadata"]["externalTaskId"] = "eat-other"
    elif change == "agent":
        task.state["raw"]["agent_id"] = "other"
    elif change == "visible":
        task.state["raw"]["conversation_index_kind"] = "user_chat"
    elif change == "direct":
        task.state["agents"] = [{"directSessionId": "session-1"}]
    elif change == "parent":
        task.state["raw"]["parent_session_id"] = "another-session"
    elif change == "child":
        task.state["others"] = [{"conversation_id": "child", "parent_session_id": "session-1"}]
    elif change in {"active", "queued"}:
        task.state["phase"] = "running" if change == "active" else "queued"
    elif change == "work_run":
        task.state["active"] = True
    else:
        store = task.service.store if change == "shared_task" else ExternalAgentTaskStore(task.tmp / "runtime" / "external_agents")
        store.tasks_dir.mkdir(parents=True, exist_ok=True)
        (store.tasks_dir / "eat-other.json").write_text(json.dumps({"taskId": "eat-other", "sessionId": "session-1"}))
    snapshot = preview(task)
    assert snapshot["status"] == "blocked" and snapshot["estimatedBytes"] == 0 and snapshot["resources"] == []
    result = execute(task, snapshot)
    assert result["status"] == "blocked" and result["releasedBytes"] == 0
    assert result["failures"][0]["kind"] == "session"
    assert (task.directory / "turn_journal.jsonl").exists()
    assert task.service.store.get_task(task.record["taskId"])["localCleanupStatus"] == "partial"
    assert task.state["calls"] == []


@pytest.mark.parametrize("change", ["file", "revision"])
def test_preview_binds_resource_snapshot_and_revision(task, change):
    snapshot = preview(task)
    if change == "file":
        (task.directory / "turn_journal.jsonl").write_bytes(b"changed")
    else:
        task.service.store.transition(task.record["taskId"], status="succeeded")
    with pytest.raises(ExternalAgentConflictError) as error:
        execute(task, snapshot)
    assert error.value.code == "CLEANUP_STALE"
    assert not task.state["calls"]


def test_reparse_session_directory_rejected_before_admission(task, monkeypatch):
    monkeypatch.setattr(cleanup, "_is_reparse_point", lambda path: path == task.directory)
    task.native._session_submit_admit_lock = lambda sid: pytest.fail("unsafe root reached admission")
    with pytest.raises(ValueError, match="unsafe_resource_link"):
        preview(task)
    assert (task.directory / "turn_journal.jsonl").exists()


def test_native_delete_must_confirm_marker_before_unlink(task):
    task.native.delete_chat_session_lightweight = lambda *args, **kwargs: {"deleted": True}
    result = execute(task)
    assert result["status"] == "blocked"
    assert (task.directory / "turn_journal.jsonl").exists()


def test_rechecks_authority_after_lock_admission(task, monkeypatch):
    @contextmanager
    def rotated():
        task.service.authority_fingerprint = lambda: "b" * 64
        yield
    monkeypatch.setattr(task.service, "_task_lock", lambda task_id: rotated())
    with pytest.raises(ExternalAgentAccessError):
        preview(task)
    assert not task.state["calls"]


def test_native_deletion_runs_inside_admission_chat_and_lifecycle_locks(task):
    held = []
    @contextmanager
    def lock(name):
        held.append(name)
        try:
            yield
        finally:
            assert held.pop() == name
    class ChatLock:
        def __enter__(self):
            held.append("chat")
        def __exit__(self, *args):
            assert held.pop() == "chat"
    task.native._session_submit_admit_lock = lambda sid: lock("admission")
    task.native._CHAT_STATE_LOCK = ChatLock()
    task.native.agent_directory_service.agent_session_lifecycle_transaction = lambda: lock("lifecycle")
    original = task.native.delete_chat_session_lightweight
    def delete(*args, **kwargs):
        assert held == ["admission", "chat", "lifecycle"]
        return original(*args, **kwargs)
    task.native.delete_chat_session_lightweight = delete
    assert execute(task)["status"] == "deleted"
    assert held == []


@pytest.mark.parametrize("failure", ["tombstone", "task_unlink"])
def test_finalization_failure_keeps_original_record_and_retries_without_replaying_task(task, monkeypatch, failure):
    original_json, original_unlink = cleanup._atomic_json, Path.unlink
    def fail_json(*args):
        raise PermissionError("fixture lock")
    def fail_unlink(path, *args, **kwargs):
        if path == task.service.store.task_path(task.record["taskId"]):
            raise PermissionError("fixture lock")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(cleanup, "_atomic_json", fail_json if failure == "tombstone" else original_json)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    result = execute(task)
    assert result["status"] == "partial"
    assert task.service.store.get_task(task.record["taskId"])["localCleanupStatus"] == "partial"
    monkeypatch.setattr(cleanup, "_atomic_json", original_json)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert execute(task)["status"] == "deleted"
    assert task.state["calls"] == ["session-1"]


def test_completed_tombstone_does_not_authorize_another_owner_or_rotated_launcher(task):
    snapshot = preview(task)
    execute(task, snapshot)
    with pytest.raises(ExternalAgentAccessError):
        cleanup.preview_task_cleanup(task.service, owner_id="another-owner", task_id=task.record["taskId"])
    task.service.authority_fingerprint = lambda: "b" * 64
    with pytest.raises(ExternalAgentAccessError):
        preview(task)


def test_task_without_session_can_be_physically_deleted(task):
    task.service.store.transition(task.record["taskId"], status="succeeded", fields={"sessionId": ""})
    snapshot = preview(task)
    bytes_before = _fixture_usage(task, include_session=False)
    result = execute(task, snapshot)
    assert result["status"] == "deleted"
    assert result["releasedBytes"] == max(0, bytes_before - _fixture_usage(task, include_session=False))
    assert not task.state["calls"]
    assert (task.directory / "turn_journal.jsonl").exists()


def test_small_task_never_counts_new_tombstone_bytes_as_released(task):
    record = {key: task.record[key] for key in ("taskId", "revision", "status", "ownerSubjectHash",
                                               "localAuthorityFingerprint", "agentId")}
    task.service.store._write_locked(record)
    snapshot = preview(task)
    bytes_before = _fixture_usage(task, include_session=False)
    result = execute(task, snapshot)
    bytes_after = _fixture_usage(task, include_session=False)
    assert bytes_after >= bytes_before
    assert result["status"] == "deleted" and result["releasedBytes"] == 0


def test_partial_file_failure_keeps_record_retryable_after_native_session_is_gone(task, monkeypatch):
    original = Path.unlink
    def fail(path, *args, **kwargs):
        if path.name == "turn_journal.jsonl":
            raise PermissionError("fixture lock")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail)
    result = execute(task)
    assert result["status"] == "blocked"
    assert task.state["raw"] is None
    assert task.service.store.get_task(task.record["taskId"])["localCleanupSessionDeleted"] is True
    monkeypatch.setattr(Path, "unlink", original)
    assert execute(task)["status"] == "deleted"
    assert task.state["calls"] == ["session-1"]


@pytest.mark.parametrize("cache_bytes", [7, 4096])
def test_partial_deletion_reports_net_bytes_including_new_failure_fields_and_guards(task, monkeypatch, cache_bytes):
    (task.directory / "a-cache.bin").write_bytes(b"x" * cache_bytes)
    original = Path.unlink
    def fail(path, *args, **kwargs):
        if path.name == "turn_journal.jsonl":
            raise PermissionError("fixture lock")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail)
    snapshot = preview(task)
    bytes_before = _fixture_usage(task)
    result = execute(task, snapshot)
    assert result["status"] == "partial"
    assert result["releasedBytes"] == max(0, bytes_before - _fixture_usage(task))
    assert result["releasedBytes"] < cache_bytes
    assert task.service.store.task_path(task.record["taskId"]).exists()


@pytest.mark.parametrize("stage", ["before", "after"])
def test_unavailable_byte_accounting_reports_zero_and_failure(task, monkeypatch, stage):
    original = cleanup._accounting_bytes
    calls = 0
    def measure(surfaces):
        nonlocal calls
        calls += 1
        if calls == (1 if stage == "before" else 2):
            raise PermissionError("fixture statistics denied")
        return original(surfaces)
    monkeypatch.setattr(cleanup, "_accounting_bytes", measure)
    result = execute(task)
    assert result["releasedBytes"] == 0
    assert {"kind": "accounting", "reason": "cleanup_accounting_unavailable"} in result["failures"]
    if stage == "before":
        assert not task.state["calls"]
        assert task.service.store.get_task(task.record["taskId"])["revision"] == task.record["revision"]


def test_replaced_session_root_cannot_be_counted_as_released_space(task, monkeypatch):
    original = cleanup._delete_session_files
    def replace(*args):
        original(*args)
        task.directory.rename(task.root / "old-session-root")
        task.directory.mkdir()
        (task.directory / "unrelated.txt").write_text("preserve")
    monkeypatch.setattr(cleanup, "_delete_session_files", replace)
    result = execute(task)
    assert result["releasedBytes"] == 0
    assert any(item["kind"] == "accounting" for item in result["failures"])
    assert (task.directory / "unrelated.txt").read_text() == "preserve"


def test_native_session_lifecycle_really_removes_sqlite_runtime_payload(task, monkeypatch):
    from core.web.services import session_service as native
    from core.web.services.session import conversation_index
    from core.web.services.session.agent_sessions import _delete_session_control_phase
    from core.ui.chat_state import save_chat_state
    from tests.test_session_delete_lock_contention import _use_tmp_project_root
    _use_tmp_project_root(task.project, monkeypatch)
    monkeypatch.setattr(cleanup, "_native_session_service", lambda service: native)
    monkeypatch.setattr(cleanup, "_delete_session_control_phase", _delete_session_control_phase)
    monkeypatch.setattr(native, "_agent_session_workspace_roots", lambda: [task.root])
    monkeypatch.setattr(native, "_ensure_session_workspace", lambda sid: task.directory)
    monkeypatch.setattr(native, "_session_workspace_dir_if_present", lambda sid: task.directory)
    monkeypatch.setattr(conversation_index, "_session_workspace_dir_if_present", lambda sid: task.directory)
    monkeypatch.setattr(native, "get_agent", lambda *args, **kwargs: None)
    monkeypatch.setattr(native.agent_directory_service, "list_agents", lambda **kwargs: [])
    raw = {**task.state["raw"], "title": "private task", "last_turn_status": "completed",
           "messages": [{"role": "user", "content": "private full text"}]}
    save_chat_state(task.project, {"version": 1, "active_conversation_id": "session-keep", "conversations": [raw,
        {"conversation_id": "session-keep", "title": "Keep", "last_turn_status": "ready"}]})
    assert native.load_session_chat_state(task.project, "session-1") is not None
    result = execute(task)
    assert result["failures"] == []
    assert result["status"] == "deleted", result
    assert native.load_session_chat_state(task.project, "session-1") is None
    assert native.load_session_chat_state(task.project, "session-keep") is not None
    assert not (task.directory / "turn_journal.jsonl").exists()


def _git_fixture(root, *args):
    # Never inherit repository-local Git variables into an isolated fixture.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = git_process.run_git(["-c", "user.name=Fixture Human", "-c", "user.email=fixture@example.test", *args],
        cwd=root, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize("state", ["merged", "dirty", "ignored", "unmerged", "locked", "shared"])
def test_only_clean_merged_exact_task_worktree_is_deleted(task, state):
    _git_fixture(task.project, "init", "-b", "main")
    _git_fixture(task.project, "add", "user.txt")
    _git_fixture(task.project, "commit", "-m", "fixture")
    path = task.project / ".worktrees" / ("assistant-" + task.record["taskId"])
    branch = "codex/assistant-" + task.record["taskId"]
    _git_fixture(task.project, "worktree", "add", "-b", branch, str(path))
    task.service.store.transition(task.record["taskId"], status="succeeded", fields={"localWorkspacePath": str(path)})
    if state == "dirty":
        (path / "user.txt").write_text("uncommitted user changes")
    elif state == "ignored":
        exclude = task.project / ".git" / "info" / "exclude"
        exclude.write_text("scratch.bin\n")
        (path / "scratch.bin").write_bytes(b"unknown user cache")
    elif state == "unmerged":
        (path / "user.txt").write_text("unmerged user commit")
        _git_fixture(path, "add", "user.txt")
        _git_fixture(path, "commit", "-m", "unmerged")
    elif state == "locked":
        _git_fixture(task.project, "worktree", "lock", str(path))
    elif state == "shared":
        (task.service.store.tasks_dir / "eat-other.json").write_text(json.dumps({
            "taskId": "eat-other", "localWorkspacePath": str(path)}))
    result = execute(task)
    assert result["status"] == ("deleted" if state in {"merged", "shared"} else "blocked")
    assert path.exists() is (state != "merged")
    assert (task.project / "user.txt").read_text() == "user source"
    if state == "shared":
        assert any(item["kind"] == "workspace" for item in result["retained"])
    elif state != "merged":
        assert any(item["kind"] == "workspace" for item in result["failures"])
        assert task.service.store.get_task(task.record["taskId"])
        assert task.state["calls"] == []
        assert (task.directory / "turn_journal.jsonl").exists()
        if state == "ignored":
            (path / "scratch.bin").unlink()
            assert execute(task)["status"] == "deleted"
            assert not path.exists()


def test_routes_require_control_launcher_and_task_owner_and_validate_fingerprint(task, monkeypatch):
    from core.web.routes import local_assistant_tasks
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    monkeypatch.setattr(local_assistant_tasks, "verify_launcher_authority", lambda value: value == "launcher-secret")
    monkeypatch.setattr(local_assistant_tasks, "local_service", lambda: task.service)
    # The route pins the credential digest just like the real principal.
    task.service.authority_fingerprint = lambda: cleanup.hashlib.sha256(b"launcher-secret").hexdigest()
    task.service.store.transition(task.record["taskId"], status="succeeded", fields={
        "localAuthorityFingerprint": task.service.authority_fingerprint()})
    app = FastAPI()
    app.include_router(local_assistant_tasks.router, prefix="/api")
    client = TestClient(app)
    path = "/api/local-assistant/v1/external-agent/tasks/" + task.record["taskId"] + "/cleanup"
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), "X-Vibelution-Management-Subject": "launcher-local",
        "X-Vibelution-Management-Capability": "launcher-secret", "X-Vibelution-External-Agent-Task-Capability": OWNER}
    assert client.post(path + "/preview").status_code == 403
    missing = {key: value for key, value in headers.items() if key != "X-Vibelution-External-Agent-Task-Capability"}
    assert client.post(path + "/preview", headers=missing).status_code == 403
    wrong = {**headers, "X-Vibelution-External-Agent-Task-Capability": "another-owner"}
    assert client.post(path + "/preview", headers=wrong).status_code == 404
    response = client.post(path + "/preview", headers=headers)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    snapshot = response.json()
    assert client.post(path, headers=headers, json={"revision": snapshot["revision"], "fingerprint": "x"}).status_code == 422
    stale = {"revision": snapshot["revision"], "fingerprint": "0" * 64}
    assert client.post(path, headers=headers, json=stale).status_code == 409
    assert client.post(path, headers=headers, json={"revision": snapshot["revision"], "fingerprint": snapshot["fingerprint"]}).json()["status"] == "deleted"


@pytest.mark.parametrize("ending", ["cancel", "lease", "deadline"])
def test_preparation_terminal_keeps_cleanup_authority_and_confirmed_workspace(tmp_path, ending):
    from tests.test_local_assistant_tasks import local_service, start
    service, _, runtime, _ = local_service(tmp_path)
    service.store = cleanup.LocalAssistantCleanupTaskStore(service.store.root)
    calls = []

    def prepare(task_id):
        calls.append(task_id)
        row = service.store.get_task(task_id)
        assert not row.get("localAuthorityFingerprint")  # Must still prepare.
        assert row["localCleanupWorkspaceState"] == "preparing"
        if ending == "cancel":
            service.cancel_task(owner_id="private-task-owner", task_id=task_id)
            blocked = cleanup.preview_task_cleanup(service, owner_id="private-task-owner", task_id=task_id)
            assert blocked["status"] == "blocked"
            assert any(item["reason"] == "workspace_preparation_active" for item in blocked["retained"])
        else:
            key = "leaseExpiresAt" if ending == "lease" else "deadlineAt"
            service.store.transition(task_id, status=row["status"], fields={key: "2000-01-01T00:00:00Z"})
        return service.project_root  # Explicitly shared; never remove user source.

    service.workspace_factory = prepare
    result = start(service)
    assert result["status"] == ("cancelled" if ending == "cancel" else "timed_out")
    assert len(calls) == 1 and runtime.create_calls == runtime.submit_calls == []
    row = service.store.get_task(result["taskId"])
    assert not row.get("localAuthorityFingerprint")
    assert row["localCleanupAuthorityFingerprint"] == "a" * 64
    assert row["localCleanupWorkspacePath"] == str(service.project_root)
    snapshot = cleanup.preview_task_cleanup(service, owner_id="private-task-owner", task_id=result["taskId"])
    assert snapshot["status"] == "ready"
    outcome = cleanup.cleanup_task(service, owner_id="private-task-owner", task_id=result["taskId"],
        revision=snapshot["revision"], fingerprint=snapshot["fingerprint"])
    assert outcome["status"] == "deleted" and service.project_root.exists()
    assert cleanup.preview_task_cleanup(service, owner_id="private-task-owner", task_id=result["taskId"])["alreadyDeleted"]


def test_failed_preparation_keeps_unknown_resources_visible_without_retagging_on_replay(tmp_path):
    from tests.test_local_assistant_tasks import local_service, start
    service, _, runtime, _ = local_service(tmp_path)
    service.store = cleanup.LocalAssistantCleanupTaskStore(service.store.root)
    created = []

    def prepare(task_id):
        created.append(task_id)
        raise TimeoutError("fixture preparation failed before returning its path")

    service.workspace_factory = prepare
    with pytest.raises(TimeoutError):
        start(service)
    row = service.store.get_task(created[0])
    assert row["status"] == "failed" and row["localCleanupWorkspaceState"] == "unknown"
    snapshot = cleanup.preview_task_cleanup(service, owner_id="private-task-owner", task_id=created[0])
    assert snapshot["status"] == "blocked"
    assert any(item["reason"] == "workspace_preparation_unconfirmed" for item in snapshot["retained"])
    service.authority_fingerprint = lambda: "b" * 64
    start(service)  # Existing task identity must not gain new cleanup authority.
    assert service.store.get_task(created[0])["localCleanupAuthorityFingerprint"] == "a" * 64
    with pytest.raises(ExternalAgentAccessError):
        cleanup.preview_task_cleanup(service, owner_id="private-task-owner", task_id=created[0])
    assert len(created) == 1 and runtime.create_calls == runtime.submit_calls == []
