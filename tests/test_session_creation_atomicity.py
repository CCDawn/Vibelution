"""Session creation atomicity regressions."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import list_session_runtime_ids, load_chat_state
from core.web.services import agent_directory_service, session_service
from core.web.services.session import conversation_index, directory_bridge, directory_runtime


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


def _create_idempotent_session_in_competing_process(
    data_home: str,
    workspace_home: str,
    start_gate,
    result_queue,
    role: str,
) -> None:
    import faulthandler

    faulthandler.dump_traceback_later(90.0, exit=True)
    os.environ["VIBELUTION_DATA_HOME"] = data_home
    from core.infrastructure import developer_sandbox as child_developer_sandbox
    from core.web.services import session_service as child_session_service

    child_developer_sandbox.is_developer_mode_enabled = lambda: False
    child_developer_sandbox.resolve_workspace_home = lambda *_args, **_kwargs: Path(workspace_home)
    child_session_service.PROJECT_ROOT = Path(workspace_home).parent
    start_gate.wait(timeout=10.0)
    try:
        created = child_session_service.create_chat_session(
            title="Cross-process retry",
            lightweight=True,
            idempotency_key="cross-process-session-retry-1",
        )
        result_queue.put({"role": role, "sessionId": str(created.get("id") or "")})
    except BaseException as exc:  # pragma: no cover - surfaced in the parent assertion
        result_queue.put({"role": role, "error": f"{type(exc).__name__}: {exc}"})


def test_failed_agent_initialization_does_not_leave_session_runtime_row(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_ensure_conversation_workspace_metadata",
        lambda _conversation: False,
    )
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)

    def fail_agent_initialization(*_args, **_kwargs):
        raise RuntimeError("agent initialization failed")

    monkeypatch.setattr(session_service, "ensure_agent_for_session", fail_agent_initialization)

    with pytest.raises(RuntimeError, match="agent initialization failed"):
        session_service.create_chat_session(title="Atomic create", lightweight=True)

    assert list_session_runtime_ids(tmp_path) == []


def test_session_create_idempotency_replays_persisted_session_after_response_loss(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    first = session_service.create_chat_session(
        title="Retry-safe session",
        lightweight=True,
        idempotency_key="create-session-retry-1",
    )
    replay = session_service.create_chat_session(
        title="Retry-safe session",
        lightweight=True,
        idempotency_key="create-session-retry-1",
    )

    assert replay["id"] == first["id"]
    assert list_session_runtime_ids(tmp_path) == [first["id"]]
    mapping_dir = directory_runtime.conversation_store_path(tmp_path).with_name("session_create_idempotency")
    mapping_path = mapping_dir / f"{hashlib.sha256(b'create-session-retry-1').hexdigest()}.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert mapping["sessionId"] == first["id"]
    assert mapping["state"] == "committed"
    assert "create-session-retry-1" not in mapping_path.name
    assert "Retry-safe session" not in mapping_path.read_text(encoding="utf-8")


def test_session_create_idempotency_conflicts_when_request_changes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    first = session_service.create_chat_session(
        title="Original title",
        lightweight=True,
        idempotency_key="create-session-conflict-1",
    )

    with pytest.raises(session_service.SessionIdempotencyConflictError):
        session_service.create_chat_session(
            title="Different title",
            lightweight=True,
            idempotency_key="create-session-conflict-1",
        )

    assert list_session_runtime_ids(tmp_path) == [first["id"]]


def test_session_create_idempotency_concurrent_same_key_creates_one_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    def create(_index: int) -> str:
        result = session_service.create_chat_session(
            title="Concurrent create",
            lightweight=True,
            idempotency_key="create-session-concurrent-1",
        )
        return str(result["id"])

    with ThreadPoolExecutor(max_workers=6) as executor:
        session_ids = list(executor.map(create, range(6)))

    assert len(set(session_ids)) == 1
    assert list_session_runtime_ids(tmp_path) == [session_ids[0]]


def test_session_create_idempotency_recovers_pending_reservation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    fake_agent = {"agentId": "agent-idempotency-recovery", "status": "active"}
    monkeypatch.setattr(session_service, "get_agent", lambda _agent_id, **_kwargs: fake_agent)
    monkeypatch.setattr(session_service, "_ensure_conversation_workspace_metadata", lambda _conversation: False)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_args, **_kwargs: None)
    from core.web.services.session import directory_bridge

    monkeypatch.setattr(directory_bridge, "sync_conversation_record", lambda *_args, **_kwargs: None)

    original_save = session_service.save_session_chat_state

    def fail_before_session_commit(*_args, **_kwargs):
        raise OSError("simulated process loss before session commit")

    monkeypatch.setattr(session_service, "save_session_chat_state", fail_before_session_commit)
    with pytest.raises(OSError, match="simulated process loss"):
        session_service.create_chat_session(
            agent_id="agent-idempotency-recovery",
            title="Recover pending",
            lightweight=True,
            idempotency_key="create-session-pending-1",
        )

    mapping_dir = directory_runtime.conversation_store_path(tmp_path).with_name("session_create_idempotency")
    mapping_path = mapping_dir / f"{hashlib.sha256(b'create-session-pending-1').hexdigest()}.json"
    pending = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert pending["state"] == "pending"
    assert list_session_runtime_ids(tmp_path) == []

    monkeypatch.setattr(session_service, "save_session_chat_state", original_save)
    recovered = session_service.create_chat_session(
        agent_id="agent-idempotency-recovery",
        title="Recover pending",
        lightweight=True,
        idempotency_key="create-session-pending-1",
    )

    assert recovered["id"] == pending["sessionId"]
    assert list_session_runtime_ids(tmp_path) == [pending["sessionId"]]
    assert json.loads(mapping_path.read_text(encoding="utf-8"))["state"] == "committed"


def test_pending_auto_agent_recovery_does_not_reuse_rebound_agent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_ensure_conversation_workspace_metadata", lambda _conversation: False)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_args, **_kwargs: None)

    idempotency_key = "create-session-rebound-agent-1"
    title = "Recover pending auto Agent"
    original_save = session_service.save_session_chat_state

    def fail_before_session_commit(*_args, **_kwargs):
        raise OSError("simulated process loss before session commit")

    monkeypatch.setattr(session_service, "save_session_chat_state", fail_before_session_commit)
    with pytest.raises(OSError, match="simulated process loss"):
        session_service.create_chat_session(
            title=title,
            lightweight=True,
            idempotency_key=idempotency_key,
        )

    mapping_dir = directory_runtime.conversation_store_path(tmp_path).with_name("session_create_idempotency")
    mapping_path = mapping_dir / f"{hashlib.sha256(idempotency_key.encode()).hexdigest()}.json"
    pending = json.loads(mapping_path.read_text(encoding="utf-8"))
    original_agent_id = str(pending["agentId"])
    original_agent = agent_directory_service.get_agent(original_agent_id)
    assert original_agent["directSessionId"] == pending["sessionId"]
    assert list_session_runtime_ids(tmp_path) == []

    rebound_session_id = "session-rebound-after-crash"
    agent_directory_service.ensure_agent_for_session(
        rebound_session_id,
        existing_agent_id=original_agent_id,
        display_name="Rebound elsewhere after crash",
    )
    assert agent_directory_service.get_agent(original_agent_id)["directSessionId"] == rebound_session_id

    monkeypatch.setattr(session_service, "save_session_chat_state", original_save)
    recovered = session_service.create_chat_session(
        title=title,
        lightweight=True,
        idempotency_key=idempotency_key,
    )

    recovered_agent_id = str(recovered["agentId"])
    recovered_agent = agent_directory_service.get_agent(recovered_agent_id)
    receipt = json.loads(mapping_path.read_text(encoding="utf-8"))
    conversation = session_service.load_session_chat_state(tmp_path, str(recovered["id"]))
    assert recovered["id"] == pending["sessionId"]
    assert recovered_agent_id != original_agent_id
    assert recovered_agent["directSessionId"] == recovered["id"]
    assert agent_directory_service.get_agent(original_agent_id)["directSessionId"] == rebound_session_id
    assert conversation["agentId"] == recovered_agent_id
    assert recovered.get("agentDirectSessionMismatch") is not True
    assert receipt["agentId"] == recovered_agent_id
    assert receipt["state"] == "committed"


def test_session_create_recovers_when_receipt_commit_fails_after_session_save(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    idempotency_key = "create-session-receipt-commit-failure-1"
    original_atomic_write_json = conversation_index.atomic_write_json
    commit_failed = False

    def fail_first_commit(path, payload, **kwargs):
        nonlocal commit_failed
        if payload.get("state") == "committed" and not commit_failed:
            commit_failed = True
            raise OSError("simulated receipt commit failure")
        return original_atomic_write_json(path, payload, **kwargs)

    monkeypatch.setattr(conversation_index, "atomic_write_json", fail_first_commit)
    from core.web.services.session import directory_bridge

    directory_syncs: list[str] = []
    monkeypatch.setattr(
        directory_bridge,
        "sync_conversation_record",
        lambda conversation: directory_syncs.append(str(conversation.get("conversation_id") or "")),
    )
    with pytest.raises(OSError, match="simulated receipt commit failure"):
        session_service.create_chat_session(
            title="Saved before receipt commit failure",
            lightweight=True,
            idempotency_key=idempotency_key,
        )

    mapping_dir = directory_runtime.conversation_store_path(tmp_path).with_name("session_create_idempotency")
    mapping_path = mapping_dir / f"{hashlib.sha256(idempotency_key.encode()).hexdigest()}.json"
    pending = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert pending["state"] == "pending"
    assert commit_failed is True
    assert list_session_runtime_ids(tmp_path) == [pending["sessionId"]]
    assert directory_syncs == [pending["sessionId"]]

    monkeypatch.setattr(conversation_index, "atomic_write_json", original_atomic_write_json)
    replay = session_service.create_chat_session(
        title="Saved before receipt commit failure",
        lightweight=True,
        idempotency_key=idempotency_key,
    )

    assert replay["id"] == pending["sessionId"]
    assert list_session_runtime_ids(tmp_path) == [pending["sessionId"]]
    assert json.loads(mapping_path.read_text(encoding="utf-8"))["state"] == "committed"
    assert directory_syncs == [pending["sessionId"], pending["sessionId"]]


def test_session_create_idempotency_same_key_serializes_across_processes(tmp_path, monkeypatch) -> None:
    data_home = tmp_path / "operator-data"
    workspace_home = tmp_path / "workspace"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    context = multiprocessing.get_context("spawn")
    start_gate = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_create_idempotent_session_in_competing_process,
            args=(str(data_home), str(workspace_home), start_gate, result_queue, role),
        )
        for role in ("first", "second")
    ]
    for process in processes:
        process.start()
    start_gate.set()
    try:
        for process in processes:
            process.join(timeout=120.0)
        assert all(process.exitcode == 0 for process in processes), (
            f"competing idempotent creates crashed: {[process.exitcode for process in processes]}"
        )
        try:
            results = [result_queue.get(timeout=30.0) for _ in processes]
        except queue.Empty as exc:
            raise AssertionError(
                f"a competing idempotent create returned no result: {[process.exitcode for process in processes]}"
            ) from exc
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)

    errors = [str(result.get("error") or "") for result in results if result.get("error")]
    assert not errors, f"cross-process idempotent create failed: {errors}"
    session_ids = {str(result.get("sessionId") or "") for result in results}
    assert len(session_ids) == 1
    session_id = next(iter(session_ids))
    assert session_id
    monkeypatch.setattr(
        developer_sandbox,
        "resolve_workspace_home",
        lambda *_args, **_kwargs: workspace_home,
    )
    assert [
        item["conversation_id"]
        for item in load_chat_state(workspace_home.parent)["conversations"]
    ] == [
        session_id
    ]


def test_pending_idempotent_replay_racing_delete_does_not_resurrect_session(
    tmp_path,
    monkeypatch,
    request,
) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    directory_runtime.initialize_session_directory_runtime(
        project_root=tmp_path,
        migrate_legacy_chat_state=False,
    )
    request.addfinalizer(directory_runtime.shutdown_session_directory_runtime)

    key = "create-session-pending-delete-race-1"
    original_atomic_write_json = conversation_index.atomic_write_json
    receipt_commit_failed = False

    def fail_first_commit(path, payload, **kwargs):
        nonlocal receipt_commit_failed
        if payload.get("state") == "committed" and not receipt_commit_failed:
            receipt_commit_failed = True
            raise OSError("simulated receipt commit failure")
        return original_atomic_write_json(path, payload, **kwargs)

    monkeypatch.setattr(conversation_index, "atomic_write_json", fail_first_commit)
    with pytest.raises(OSError, match="simulated receipt commit failure"):
        session_service.create_chat_session(
            title="Pending replay delete race",
            lightweight=True,
            idempotency_key=key,
        )
    monkeypatch.setattr(conversation_index, "atomic_write_json", original_atomic_write_json)

    receipt_dir = directory_runtime.conversation_store_path(tmp_path).with_name(
        "session_create_idempotency"
    )
    receipt_path = receipt_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"
    pending = json.loads(receipt_path.read_text(encoding="utf-8"))
    session_id = str(pending["sessionId"])
    agent_id = str(pending["agentId"])
    assert pending["state"] == "pending"
    assert agent_directory_service.get_agent(agent_id)["directSessionId"] == session_id

    store = directory_runtime.get_open_directory_store()
    assert store is not None

    def active_directory_session_ids() -> set[str]:
        page = store.repository.list_directory_page(include_hidden=True, limit=200)
        return {
            str(row.get("sessionId") or "")
            for row in page.get("rows") or []
        }

    assert session_id in active_directory_session_ids()

    sync_entered = threading.Event()
    allow_sync = threading.Event()
    original_sync = directory_bridge.sync_conversation_record

    def pause_replay_sync(conversation, *args, **kwargs):
        if str(conversation.get("conversation_id") or "") == session_id:
            sync_entered.set()
            if not allow_sync.wait(15):
                raise TimeoutError("pending replay directory sync gate timed out")
        return original_sync(conversation, *args, **kwargs)

    monkeypatch.setattr(directory_bridge, "sync_conversation_record", pause_replay_sync)
    with ThreadPoolExecutor(max_workers=1) as executor:
        replay_future = executor.submit(
            session_service.create_chat_session,
            title="Pending replay delete race",
            lightweight=True,
            idempotency_key=key,
        )
        try:
            assert sync_entered.wait(10), "pending replay did not reach directory sync"
            session_service.delete_chat_session_lightweight(session_id)
            assert session_id not in active_directory_session_ids()
        finally:
            allow_sync.set()

        with pytest.raises(session_service.SessionIdempotencyReplayGoneError):
            replay_future.result(timeout=20)

    assert session_id not in list_session_runtime_ids(tmp_path)
    assert session_id not in active_directory_session_ids()
    assert agent_directory_service.get_agent(agent_id)["directSessionId"] != session_id
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["state"] == "committed"

    with pytest.raises(session_service.SessionIdempotencyReplayGoneError):
        session_service.create_chat_session(
            title="Pending replay delete race",
            lightweight=True,
            idempotency_key=key,
        )
    assert session_id not in active_directory_session_ids()
    assert agent_directory_service.get_agent(agent_id)["directSessionId"] != session_id
