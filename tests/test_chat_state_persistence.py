import json
import multiprocessing
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import (
    chat_state_path,
    load_chat_state,
    load_session_chat_state,
    save_chat_state,
    save_session_chat_state,
)
from core.web.services import session_service
from core.web.services.session.live_output import SessionLiveOutputState


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


def test_save_chat_state_uses_valid_replace_target(tmp_path):
    payload = {"version": 1, "conversations": [{"conversation_id": "default", "messages": []}]}
    expected = {
        "version": 1,
        "active_conversation_id": "",
        "state_revision": 1,
        "updated_at": "",
        "conversations": [{"conversation_id": "default"}],
    }

    save_chat_state(tmp_path, payload)

    path = chat_state_path(tmp_path)
    assert load_chat_state(tmp_path) == expected
    assert not path.exists()
    assert payload["conversations"][0]["messages"] == []
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_save_session_chat_state_does_not_drop_siblings(tmp_path):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "conversations": [
                {"conversation_id": "session-a", "title": "A"},
                {"conversation_id": "session-b", "title": "B"},
            ],
        },
    )

    save_session_chat_state(
        tmp_path,
        "session-a",
        {"conversation_id": "session-a", "title": "A2"},
    )

    assert load_session_chat_state(tmp_path, "session-a")["title"] == "A2"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    document = load_chat_state(tmp_path)
    assert [item["conversation_id"] for item in document["conversations"]] == [
        "session-a",
        "session-b",
    ]


def test_load_chat_state_backs_up_corrupt_json(tmp_path):
    path = chat_state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version": 1, "conversations": [', encoding="utf-8")

    assert load_chat_state(tmp_path) == {}

    backups = list(path.parent.glob(f"{path.name}.corrupt.*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"version": 1, "conversations": ['
    assert path.read_text(encoding="utf-8") == '{"version": 1, "conversations": ['


def test_load_conversations_runs_inside_chat_state_transaction(monkeypatch, tmp_path):
    events: list[str] = []

    @contextmanager
    def fake_transaction(project_root):
        events.append(f"enter:{project_root}")
        yield
        events.append(f"exit:{project_root}")

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "chat_state_transaction", fake_transaction)
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda _project_root: {
            "version": 1,
            "active_conversation_id": "default",
            "conversations": [{"conversation_id": "default", "title": "Default", "messages": []}],
        },
    )

    active_id, conversations = session_service._load_conversations(
        repair=False,
        agent_by_id={},
        lightweight=True,
    )

    assert active_id == "default"
    assert len(conversations) == 1
    # The facade mutation lock owns the outer cross-process transaction; the
    # existing helper's narrower transaction remains safely nested inside it.
    assert events == [
        f"enter:{tmp_path}",
        f"enter:{tmp_path}",
        f"exit:{tmp_path}",
        f"exit:{tmp_path}",
    ]


def test_session_mutation_lock_holds_file_transaction_for_full_mutation(monkeypatch, tmp_path):
    """The session facade lock must cover a load/mutate/save sequence cross-process."""

    events: list[str] = []

    @contextmanager
    def fake_transaction(project_root):
        events.append(f"enter:{project_root}")
        yield
        events.append(f"exit:{project_root}")

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "chat_state_transaction", fake_transaction)

    with session_service._CHAT_STATE_LOCK:
        events.append("mutate")

    assert events == [f"enter:{tmp_path}", "mutate", f"exit:{tmp_path}"]


def _create_session_in_competing_process(
    data_home: str,
    workspace_home: str,
    agent_id: str,
    role: str,
    start_gate,
    result_queue,
) -> None:
    """Create one session after a shared start gate so both writers overlap."""
    os.environ["VIBELUTION_DATA_HOME"] = data_home
    from core.infrastructure import developer_sandbox as child_developer_sandbox
    from core.web.services import session_service as child_session_service

    child_developer_sandbox.is_developer_mode_enabled = lambda: False
    child_developer_sandbox.resolve_workspace_home = lambda *args, **kwargs: Path(workspace_home)
    child_session_service.PROJECT_ROOT = Path(workspace_home).parent
    start_gate.wait(timeout=10.0)
    try:
        created = child_session_service.create_chat_session(
            title=f"Concurrent {role}",
            agent_id=agent_id,
            activate=True,
            conversation_index_kind="team_agent",
        )
        result_queue.put({"role": role, "sessionId": str(created.get("id") or "")})
    except BaseException as exc:  # pragma: no cover - surfaced in the parent assertion
        result_queue.put({"role": role, "error": f"{type(exc).__name__}: {exc}"})


def test_cross_process_session_creates_do_not_overwrite_chat_index(tmp_path, monkeypatch):
    """A concurrent session create must retain both rows, not only the last writer."""
    data_home = tmp_path / "operator-data"
    workspace_home = tmp_path / "workspace"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    context = multiprocessing.get_context("spawn")
    start_gate = context.Event()
    result_queue = context.Queue()
    first = context.Process(
        target=_create_session_in_competing_process,
        args=(
            str(data_home),
            str(workspace_home),
            "",
            "first",
            start_gate,
            result_queue,
        ),
    )
    second = context.Process(
        target=_create_session_in_competing_process,
        args=(
            str(data_home),
            str(workspace_home),
            "",
            "second",
            start_gate,
            result_queue,
        ),
    )
    first.start()
    second.start()
    start_gate.set()
    try:
        first.join(timeout=15.0)
        second.join(timeout=15.0)
        assert first.exitcode == 0
        assert second.exitcode == 0
        results = [result_queue.get(timeout=3.0), result_queue.get(timeout=3.0)]
    finally:
        for process in (first, second):
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)

    assert not [result for result in results if result.get("error")]
    created_ids = {str(result.get("sessionId") or "") for result in results}
    assert all(created_ids)
    monkeypatch.setattr(
        developer_sandbox,
        "resolve_workspace_home",
        lambda *args, **kwargs: workspace_home,
    )
    state = load_chat_state(tmp_path)
    indexed_ids = {
        str(item.get("conversation_id") or "")
        for item in state.get("conversations", [])
        if isinstance(item, dict)
    }
    assert created_ids <= indexed_ids


def test_create_chat_session_upserts_one_row_without_full_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "conversations": [
                {"conversation_id": "session-a", "title": "A", "last_turn_status": "ready"},
            ],
        },
    )
    full_saves: list[str] = []
    original_save_chat_state = session_service.save_chat_state
    monkeypatch.setattr(
        session_service,
        "save_chat_state",
        lambda *args, **kwargs: full_saves.append("save") or original_save_chat_state(*args, **kwargs),
    )

    created = session_service.create_chat_session(
        title="B",
        activate=True,
        conversation_index_kind="team_agent",
        lightweight=True,
    )

    created_id = str(created.get("id") or "")
    assert created_id
    assert full_saves == []
    assert load_session_chat_state(tmp_path, "session-a")["title"] == "A"
    assert load_session_chat_state(tmp_path, created_id)["title"] == "B"
    document = load_chat_state(tmp_path)
    assert document["active_conversation_id"] == created_id
    assert {item["conversation_id"] for item in document["conversations"]} == {
        "session-a",
        created_id,
    }


def _wait_until(predicate, *, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_stale_full_replace_cannot_clobber_parallel_session_row(tmp_path, monkeypatch):
    """A long-held full replace must not overwrite a later session-row upsert."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "conversations": [
                {
                    "conversation_id": "session-a",
                    "title": "A",
                    "last_turn_status": "ready",
                },
                {
                    "conversation_id": "session-b",
                    "title": "B",
                    "last_turn_status": "ready",
                },
            ],
        },
    )

    persist_holds_lock = threading.Event()
    persist_may_save = threading.Event()
    persist_errors: list[BaseException] = []
    submit_errors: list[BaseException] = []

    def persist_stale_snapshot() -> None:
        try:
            with session_service._CHAT_STATE_LOCK:
                stale = load_chat_state(tmp_path)
                persist_holds_lock.set()
                assert persist_may_save.wait(timeout=2.0)
                save_chat_state(tmp_path, stale)
        except BaseException as exc:  # pragma: no cover - surfaced below
            persist_errors.append(exc)

    def submit_running_row() -> None:
        try:
            assert persist_holds_lock.wait(timeout=2.0)
            save_session_chat_state(
                tmp_path,
                "session-b",
                {
                    "conversation_id": "session-b",
                    "title": "B",
                    "last_turn_status": "running",
                },
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            submit_errors.append(exc)

    persist_thread = threading.Thread(target=persist_stale_snapshot)
    submit_thread = threading.Thread(target=submit_running_row)
    persist_thread.start()
    assert persist_holds_lock.wait(timeout=2.0)
    submit_thread.start()
    assert _wait_until(submit_thread.is_alive, timeout=1.0)
    time.sleep(0.1)
    persist_may_save.set()
    persist_thread.join(timeout=3.0)
    submit_thread.join(timeout=3.0)

    assert persist_errors == []
    assert submit_errors == []
    assert not persist_thread.is_alive()
    assert not submit_thread.is_alive()
    assert load_session_chat_state(tmp_path, "session-b")["last_turn_status"] == "running"
    assert load_session_chat_state(tmp_path, "session-a")["title"] == "A"


def test_stale_full_replace_cannot_prune_parallel_new_session_row(tmp_path, monkeypatch):
    """A stale replace snapshot must not delete a session row upserted while it held the lock."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "conversations": [
                {"conversation_id": "session-a", "title": "A"},
            ],
        },
    )

    persist_holds_lock = threading.Event()
    persist_may_save = threading.Event()
    persist_errors: list[BaseException] = []
    submit_errors: list[BaseException] = []

    def persist_stale_snapshot() -> None:
        try:
            with session_service._CHAT_STATE_LOCK:
                stale = load_chat_state(tmp_path)
                persist_holds_lock.set()
                assert persist_may_save.wait(timeout=2.0)
                save_chat_state(tmp_path, stale)
        except BaseException as exc:  # pragma: no cover - surfaced below
            persist_errors.append(exc)

    def create_session_c() -> None:
        try:
            assert persist_holds_lock.wait(timeout=2.0)
            save_session_chat_state(
                tmp_path,
                "session-c",
                {"conversation_id": "session-c", "title": "C"},
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            submit_errors.append(exc)

    persist_thread = threading.Thread(target=persist_stale_snapshot)
    submit_thread = threading.Thread(target=create_session_c)
    persist_thread.start()
    assert persist_holds_lock.wait(timeout=2.0)
    submit_thread.start()
    assert _wait_until(submit_thread.is_alive, timeout=1.0)
    time.sleep(0.1)
    persist_may_save.set()
    persist_thread.join(timeout=3.0)
    submit_thread.join(timeout=3.0)

    assert persist_errors == []
    assert submit_errors == []
    assert not persist_thread.is_alive()
    assert not submit_thread.is_alive()
    assert load_session_chat_state(tmp_path, "session-c")["title"] == "C"
    assert load_session_chat_state(tmp_path, "session-a")["title"] == "A"


def test_load_conversations_repair_writes_only_dirty_session_rows(tmp_path, monkeypatch):
    """List repair must upsert dirty runtime rows instead of replacing the table."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "conversations": [
                {
                    "conversation_id": "session-a",
                    "title": "A",
                    "last_turn_status": "running",
                },
                {
                    "conversation_id": "session-b",
                    "title": "B",
                    "last_turn_status": "ready",
                },
            ],
        },
    )

    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "reconcile_stale_chat_turn_work_runs", lambda **_kwargs: [])
    monkeypatch.setattr(session_service, "_release_stale_chat_turn_work_run", lambda **_kwargs: None)
    monkeypatch.setattr(session_service, "_ensure_conversation_agent_metadata", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_ensure_conversation_workspace_metadata", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_repair_child_root_agent_direct_session_bindings", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_ensure_session_workspace", lambda *_args, **_kwargs: None)
    _patch_stale_running_owner_stubs(monkeypatch)

    full_saves: list[str] = []
    original_save_chat_state = session_service.save_chat_state
    monkeypatch.setattr(
        session_service,
        "save_chat_state",
        lambda *args, **kwargs: full_saves.append("save") or original_save_chat_state(*args, **kwargs),
    )
    session_saves: list[str] = []
    original_save_session = session_service.save_session_chat_state

    def _spy_save_session(project_root, session_id, conversation, **kwargs):
        session_saves.append(str(session_id))
        return original_save_session(project_root, session_id, conversation, **kwargs)

    monkeypatch.setattr(session_service, "save_session_chat_state", _spy_save_session)

    _active_id, conversations = session_service._load_conversations(
        repair=True,
        agent_by_id={},
        hidden_team_member_agent_ids=set(),
        lightweight=True,
        defer_hidden_previews=True,
    )

    by_id = {str(item.get("id") or ""): item for item in conversations}
    assert full_saves == []
    assert session_saves == ["session-a"]
    assert by_id["session-a"]["lastTurnStatus"] == "ready"
    assert by_id["session-b"]["lastTurnStatus"] == "ready"
    assert by_id["session-b"]["title"] == "B"
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "ready"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    assert load_session_chat_state(tmp_path, "session-b")["last_turn_status"] == "ready"


class _StubWorkRunStore:
    """Minimal WorkRunStore stand-in so tests never read the real machine state."""

    def __init__(self, active=None):
        self._active = active

    def load_active_snapshot(self, run_kind):
        return self._active


class _StubTurnScheduler:
    def __init__(self, queued=()):
        self._queued = set(queued)

    def queued_session_turn_ids(self):
        return set(self._queued)

    def clear(self):
        self._queued.clear()


def _patch_stale_running_owner_stubs(monkeypatch, *, active=None, queued=()):
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", _StubWorkRunStore(active))
    monkeypatch.setattr(session_service, "_SESSION_TURN_SCHEDULER", _StubTurnScheduler(queued))


def _seed_single_runtime_row(tmp_path, *, session_id: str = "session-a", status: str = "running") -> None:
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "conversations": [
                {"conversation_id": session_id, "title": "A", "last_turn_status": status},
            ],
        },
    )


def test_stale_running_repair_skipped_when_scheduler_holds_queued_turn(tmp_path, monkeypatch):
    """A queued turn lives in the scheduler, not the running set; repair must not touch it."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_single_runtime_row(tmp_path, status="queued")
    _patch_stale_running_owner_stubs(
        monkeypatch,
        active=None,
        queued={("session-a", "turn-1")},
    )
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    conversation = load_session_chat_state(tmp_path, "session-a")
    repaired = session_service._repair_stale_running_conversation(conversation)

    assert repaired is False
    assert conversation["last_turn_status"] == "queued"
    assert "runtime_notices" not in conversation
    assert full_saves == []
    assert session_saves == []
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "queued"


def test_stale_running_repair_skipped_for_recent_work_run_snapshot(tmp_path, monkeypatch):
    """Non-owner process: empty in-process sets plus a freshly updated open work-run
    snapshot must stay hands-off instead of flipping a possibly-live turn to ready."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_single_runtime_row(tmp_path, status="running")
    active = {
        "runId": "turn-1",
        "sessionId": "session-a",
        "status": "running",
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    _patch_stale_running_owner_stubs(monkeypatch, active=active)
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    conversation = load_session_chat_state(tmp_path, "session-a")
    repaired = session_service._repair_stale_running_conversation(conversation)

    assert repaired is False
    assert conversation["last_turn_status"] == "running"
    assert "runtime_notices" not in conversation
    assert full_saves == []
    assert session_saves == []
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "running"


def test_stale_running_repair_audited_after_work_run_grace_expiry(tmp_path, monkeypatch):
    """Once the open snapshot outlives the grace window the turn is judged dead;
    the write-back must carry an audit event naming who judged and what changed."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_single_runtime_row(tmp_path, status="running")
    stale_updated_at = (datetime.now() - timedelta(seconds=600)).isoformat(timespec="seconds")
    active = {
        "runId": "turn-1",
        "sessionId": "session-a",
        "status": "running",
        "updatedAt": stale_updated_at,
    }
    _patch_stale_running_owner_stubs(monkeypatch, active=active)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "reconcile_stale_chat_turn_work_runs", lambda **_kwargs: [])
    release_calls: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_release_stale_chat_turn_work_run",
        lambda **kwargs: release_calls.append(dict(kwargs)),
    )
    audit_events: list[dict] = []

    def _spy_scene_event(component, phase, event_code, *, fields=None, **kwargs):
        audit_events.append({"eventCode": event_code, "fields": dict(fields or {})})
        return {"eventCode": event_code}

    monkeypatch.setattr(session_service, "record_runtime_scene_event", _spy_scene_event)

    conversation = load_session_chat_state(tmp_path, "session-a")
    payload = session_service._repair_stale_running_conversations({"conversations": [conversation]})

    assert conversation["last_turn_status"] == "ready"
    assert payload["conversations"][0]["last_turn_status"] == "ready"
    notices = conversation.get("runtime_notices") or []
    assert any(item.get("kind") == "turn_recovered" for item in notices)
    audit = [item for item in audit_events if item["eventCode"] == "conversation.stale_running_repaired"]
    assert len(audit) == 1
    assert audit[0]["fields"]["sessionId"] == "session-a"
    assert audit[0]["fields"]["previousStatus"] == "running"
    assert audit[0]["fields"]["newStatus"] == "ready"
    assert release_calls and release_calls[0]["session_id"] == "session-a"
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "ready"


def test_stale_running_repair_grace_env_zero_disables_freshness_gate(tmp_path, monkeypatch):
    """The cross-process freshness gate is configurable; 0 is the explicit opt-out."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("VIBELUTION_SESSION_STALE_RUNNING_REPAIR_GRACE_SECONDS", "0")
    _seed_single_runtime_row(tmp_path, status="running")
    active = {
        "runId": "turn-1",
        "sessionId": "session-a",
        "status": "running",
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    _patch_stale_running_owner_stubs(monkeypatch, active=active)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "_release_stale_chat_turn_work_run", lambda **_kwargs: None)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *args, **kwargs: {})

    conversation = load_session_chat_state(tmp_path, "session-a")
    repaired = session_service._repair_stale_running_conversation(conversation)

    assert repaired is True
    assert conversation["last_turn_status"] == "ready"


def test_completion_snapshot_read_path_writes_nothing_for_live_owner(tmp_path, monkeypatch):
    """GET completion snapshot must present the persisted fact and never write the
    store while owner evidence (fresh open work-run) says the turn may be alive."""

    from core.web.services.session import turn_diagnostics

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_single_runtime_row(tmp_path, status="running")
    active = {
        "runId": "turn-1",
        "sessionId": "session-a",
        "status": "running",
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    _patch_stale_running_owner_stubs(monkeypatch, active=active)
    monkeypatch.setattr(session_service, "reconcile_stale_chat_turn_work_runs", lambda **_kwargs: [])
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "_RUNNING_SESSION_IDS", set())
    monkeypatch.setattr(session_service, "_SESSION_ACTIVE_TURN_IDS", {})
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    snapshot = turn_diagnostics.get_session_turn_completion_snapshot("session-a", "turn-1")

    assert snapshot["lastTurnStatus"] == "running"
    assert snapshot["terminal"] is False
    assert full_saves == []
    assert session_saves == []
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "running"


def _seed_two_runtime_rows(tmp_path, *, status_a: str = "running") -> None:
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "conversations": [
                {
                    "conversation_id": "session-a",
                    "title": "A",
                    "last_turn_status": status_a,
                },
                {
                    "conversation_id": "session-b",
                    "title": "B",
                    "last_turn_status": "ready",
                },
            ],
        },
    )


def _spy_runtime_saves(monkeypatch) -> tuple[list[str], list[str]]:
    full_saves: list[str] = []
    original_save_chat_state = session_service.save_chat_state
    monkeypatch.setattr(
        session_service,
        "save_chat_state",
        lambda *args, **kwargs: full_saves.append("save") or original_save_chat_state(*args, **kwargs),
    )
    session_saves: list[str] = []
    original_save_session = session_service.save_session_chat_state

    def _spy_save_session(project_root, session_id, conversation, **kwargs):
        session_saves.append(str(session_id))
        return original_save_session(project_root, session_id, conversation, **kwargs)

    monkeypatch.setattr(session_service, "save_session_chat_state", _spy_save_session)
    return full_saves, session_saves


def test_persist_interrupted_snapshot_writes_only_target_session_row(tmp_path, monkeypatch):
    """Stop snapshot must upsert the stopped session instead of replacing the table."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path)
    monkeypatch.setattr(session_service, "_snapshot_session_live_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(session_service, "_latest_assistant_message_is_stop", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(session_service, "_clear_session_live_output", lambda *_args, **_kwargs: None)
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    session_service._persist_session_interrupted_snapshot(
        "session-a",
        {
            "turnId": "turn-a",
            "stopReason": "stop",
            "stopRequestedAt": "2026-08-15T12:00:00",
        },
        lang="zh",
    )

    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "ready"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    assert load_session_chat_state(tmp_path, "session-b")["last_turn_status"] == "ready"


def test_persist_recovered_live_output_writes_only_target_session_row(tmp_path, monkeypatch):
    """Recovered live output must upsert one session row instead of replacing the table."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(session_service, "_find_turn_scoped_assistant_message", lambda *_args, **_kwargs: None)
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    session_service._persist_recovered_live_output_to_chat_state(
        "session-a",
        "turn-a",
        SessionLiveOutputState(session_id="session-a", turn_id="turn-a", content="partial"),
    )

    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "ready"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    assert load_session_chat_state(tmp_path, "session-b")["last_turn_status"] == "ready"


def _stub_schedule_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(session_service, "_set_session_turn_progress_live_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_persist_chat_turn_work_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.touch_directory_session_safe",
        lambda *_args, **_kwargs: None,
    )


def test_mark_session_turn_queued_writes_only_target_session_row(tmp_path, monkeypatch):
    """Queue status must upsert the waiting session instead of replacing the table."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    _stub_schedule_side_effects(monkeypatch)
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    session_service._mark_session_turn_queued(
        {"session_id": "session-a", "turn_id": "turn-a", "agent_id": "agent-a"},
        queue_position=1,
    )

    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "queued"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    assert load_session_chat_state(tmp_path, "session-b")["last_turn_status"] == "ready"


def test_mark_session_turn_dequeued_writes_only_target_session_row(tmp_path, monkeypatch):
    """Dequeue status must upsert the admitted session instead of replacing the table."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="queued")
    _stub_schedule_side_effects(monkeypatch)
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    session_service._mark_session_turn_dequeued(
        {"session_id": "session-a", "turn_id": "turn-a", "agent_id": "agent-a"},
    )

    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "running"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    assert load_session_chat_state(tmp_path, "session-b")["last_turn_status"] == "ready"


def test_ensure_session_mutable_loads_one_row_without_full_document(tmp_path, monkeypatch):
    """A missing in-memory conversation must not assemble the compatibility document."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(session_service, "_is_session_workspace_intentionally_deleted", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_conversation_is_read_only", lambda *_args, **_kwargs: False)
    full_loads: list[str] = []
    original_load = session_service.load_chat_state
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda *args, **kwargs: full_loads.append("load") or original_load(*args, **kwargs),
    )

    loaded = session_service._ensure_session_mutable("session-a")

    assert full_loads == []
    assert loaded["title"] == "A"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_update_chat_session_title_writes_only_target_session_row(tmp_path, monkeypatch):
    """Title updates must upsert the renamed session instead of replacing the table."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(session_service, "_is_session_workspace_intentionally_deleted", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_conversation_is_read_only", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_load_conversation_detail_target", lambda *_args, **_kwargs: {"id": "session-a", "title": "A2"})
    monkeypatch.setattr(session_service, "_build_lightweight_session_detail", lambda target: target)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_args, **_kwargs: {"accepted": True})
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.touch_directory_session_safe",
        lambda *_args, **_kwargs: None,
    )
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    session_service.update_chat_session_title("session-a", "A2")

    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-a")["title"] == "A2"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_load_conversation_detail_target_never_full_replaces_siblings(tmp_path, monkeypatch):
    """A one-row detail payload must not prune sibling runtime rows on repair writeback."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="running")
    monkeypatch.setattr(session_service, "_repair_child_root_agent_direct_session_bindings", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_repair_stale_running_conversation", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(session_service, "_ensure_conversation_agent_metadata", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_ensure_conversation_workspace_metadata", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        session_service,
        "_normalize_conversation",
        lambda raw, **_kwargs: {"id": str(raw.get("conversation_id") or "")},
    )
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)
    only_a = {"conversations": [dict(load_session_chat_state(tmp_path, "session-a"))]}

    session_service._load_conversation_detail_target(
        "session-a",
        payload=only_a,
        persist_session_row=False,
    )

    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_materialize_direct_session_writes_only_target_session_row(tmp_path, monkeypatch):
    """Agent-directory materialize must upsert the new row instead of replacing the table."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(
        "core.web.services.session.directory_runtime.is_legacy_discard_in_progress",
        lambda: False,
    )
    monkeypatch.setattr(session_service, "_is_session_workspace_intentionally_deleted", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        session_service,
        "_agent_for_direct_session",
        lambda session_id: {
            "agentId": "agent-x",
            "displayName": "X",
            "updatedAt": "2026-08-16T00:00:00Z",
        }
        if session_id == "session-new"
        else None,
    )
    monkeypatch.setattr(
        session_service,
        "_agent_directory_conversation_record",
        lambda agent, *, session_id: {
            "conversation_id": session_id,
            "agent_id": agent["agentId"],
            "title": agent["displayName"],
            "updated_at": "2026-08-16T00:00:00Z",
        },
    )
    monkeypatch.setattr(session_service, "_agent_directory_stub_hidden_from_user_index", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_record_agent_directory_conversation_materialized_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.sync_conversation_record",
        lambda *_args, **_kwargs: None,
    )
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    changed = session_service._ensure_agent_directory_conversation_materialized(
        "session-new",
        source="test_chat_state_persistence",
    )

    assert changed is True
    assert full_saves == []
    assert session_saves == ["session-new"]
    assert load_session_chat_state(tmp_path, "session-new")["title"] == "X"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_recover_missing_conversation_writes_only_target_session_row(tmp_path, monkeypatch):
    """Workspace recovery must upsert the recovered session instead of replacing the table."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(
        "core.web.services.session.directory_runtime.is_legacy_discard_in_progress",
        lambda: False,
    )
    monkeypatch.setattr(session_service, "_ensure_agent_directory_conversation_materialized", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_is_session_workspace_intentionally_deleted", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_session_workspace_has_recoverable_activity", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(session_service, "_recover_stage_task_workspace_conversation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "get_agent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_recover_agent_id_from_session_journal", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        session_service,
        "_make_empty_conversation",
        lambda session_id, title="", timestamp="", **_kwargs: {
            "conversation_id": session_id,
            "title": title or session_id,
            "updated_at": timestamp or "2026-08-16T00:00:00Z",
        },
    )
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.sync_conversation_record",
        lambda *_args, **_kwargs: None,
    )
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    recovered = session_service._ensure_session_conversation_record(
        "session-orphan",
        source="test_chat_state_persistence",
    )

    assert recovered is True
    assert full_saves == []
    assert session_saves == ["session-orphan"]
    assert load_session_chat_state(tmp_path, "session-orphan")["title"] == "session-orphan"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_initialized_session_reasoning_effort_loads_one_row(tmp_path, monkeypatch):
    """Reasoning snapshot must read the target runtime row, not the compatibility document."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "conversations": [
                {"conversation_id": "session-a", "title": "A", "reasoning_effort": "high"},
                {"conversation_id": "session-b", "title": "B"},
            ],
        },
    )
    monkeypatch.setattr(session_service, "_ensure_session_conversation_record", lambda *_args, **_kwargs: True)
    full_loads: list[str] = []
    original_load = session_service.load_chat_state
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda *args, **kwargs: full_loads.append("load") or original_load(*args, **kwargs),
    )

    initialized, effort = session_service._initialized_session_reasoning_effort("session-a")

    assert initialized is True
    assert effort == "high"
    assert full_loads == []
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_latest_unfinished_task_goal_loads_one_row(tmp_path, monkeypatch):
    """Resume-goal lookup must read one runtime row instead of assembling the document."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    save_session_chat_state(
        tmp_path,
        "session-a",
        {
            **load_session_chat_state(tmp_path, "session-a"),
            "active_task": {"status": "running", "goal": "Finish the paper"},
        },
    )
    monkeypatch.setattr(session_service, "_normalize_session_active_task", lambda task: task)
    monkeypatch.setattr(session_service, "_is_task_tool_backed_active_task", lambda _task: True)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(session_service, "_is_effective_user_message", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(session_service, "_latest_effective_user_message_with_index", lambda *_args, **_kwargs: ("", -1))
    monkeypatch.setattr(session_service, "_should_prefer_history_goal_over_active_task", lambda *_args, **_kwargs: False)
    full_loads: list[str] = []
    original_load = session_service.load_chat_state
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda *args, **kwargs: full_loads.append("load") or original_load(*args, **kwargs),
    )

    goal, source = session_service._latest_unfinished_task_goal_with_source("session-a")

    assert goal == "Finish the paper"
    assert source == "active_task"
    assert full_loads == []
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def _stub_compat_shell_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)
    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda: {})
    monkeypatch.setattr(session_service, "_is_session_workspace_intentionally_deleted", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_conversation_is_read_only", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_args, **_kwargs: {"accepted": True})
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.sync_conversation_record",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.sync_conversation_records",
        lambda *_args, **_kwargs: None,
    )


def test_select_chat_session_writes_only_target_session_row(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    save_session_chat_state(tmp_path, "session-a", load_session_chat_state(tmp_path, "session-a"), activate=True)
    _stub_compat_shell_side_effects(monkeypatch)
    monkeypatch.setattr(session_service, "_ensure_conversation_workspace_metadata", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_ensure_conversation_agent_metadata", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        session_service,
        "_normalize_conversation",
        lambda raw, **_kwargs: {"id": str(raw.get("conversation_id") or ""), "title": raw.get("title")},
    )
    monkeypatch.setattr(
        session_service,
        "_build_lightweight_session_detail",
        lambda target: {"id": target.get("id"), "title": target.get("title")},
    )
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    detail = session_service.select_chat_session("session-b", lightweight=True)

    assert detail["id"] == "session-b"
    assert full_saves == []
    assert session_saves == ["session-b"]
    assert load_chat_state(tmp_path)["active_conversation_id"] == "session-b"
    assert load_session_chat_state(tmp_path, "session-a")["title"] == "A"


def test_ensure_agent_direct_session_upserts_one_row_without_full_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    _stub_compat_shell_side_effects(monkeypatch)
    monkeypatch.setattr(
        session_service,
        "get_agent",
        lambda agent_id, **_kwargs: {"agentId": agent_id, "displayName": "Direct", "directSessionId": ""},
    )
    monkeypatch.setattr(session_service, "_ensure_conversation_workspace_metadata", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_bind_conversation_to_agent_instance", lambda *_args, **_kwargs: None)
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    created = session_service.ensure_agent_direct_session(agent_id="agent-direct")

    created_id = str(created.get("id") or "")
    assert created_id
    assert full_saves == []
    assert session_saves == [created_id]
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    assert load_session_chat_state(tmp_path, created_id)["title"] == "Direct"


def test_create_child_session_writes_only_parent_and_child_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    _stub_compat_shell_side_effects(monkeypatch)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(session_service, "_latest_user_message_id", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(session_service, "_append_session_conversation_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_record_child_session_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "get_session_detail", lambda session_id, **_kwargs: {"id": session_id})
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    result = session_service.create_child_session(
        "session-a",
        user_request="split this work",
        task_title="Child",
        auto_start=False,
        switch_to_child=False,
    )

    child_id = str(result.get("childSessionId") or "")
    assert child_id
    assert full_saves == []
    assert "session-a" in session_saves
    assert child_id in session_saves
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    assert load_session_chat_state(tmp_path, child_id)["title"] == "Child"


def test_archive_agent_sessions_upserts_archived_rows_without_dropping_siblings(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    save_session_chat_state(
        tmp_path,
        "session-a",
        {
            **load_session_chat_state(tmp_path, "session-a"),
            "agent_id": "agent-x",
            "agentId": "agent-x",
        },
        activate=True,
    )
    _stub_compat_shell_side_effects(monkeypatch)
    monkeypatch.setattr(session_service, "_ensure_agent_direct_session_not_reassigned", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        session_service,
        "_normalize_conversation",
        lambda raw, **_kwargs: {"id": str(raw.get("conversation_id") or ""), "sessionKind": "main"},
    )
    monkeypatch.setattr(session_service, "_conversation_phase", lambda *_args, **_kwargs: "ready")
    monkeypatch.setattr(session_service, "_record_agent_session_lifecycle_event", lambda *_args, **_kwargs: None)
    full_saves, _session_saves = _spy_runtime_saves(monkeypatch)

    result = session_service.archive_agent_sessions("agent-x", direct_session_id="session-a")

    assert result["archivedCount"] == 1
    assert full_saves == []
    archived = load_session_chat_state(tmp_path, "session-a")
    assert archived["archive_state"]["status"] == "archived"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    assert load_chat_state(tmp_path)["active_conversation_id"] == "session-b"


def test_mark_direct_session_agent_deleted_writes_only_target_session_row(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    _stub_compat_shell_side_effects(monkeypatch)
    monkeypatch.setattr(session_service, "_record_direct_session_agent_deleted_event", lambda *_args, **_kwargs: None)
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    result = session_service.mark_direct_session_agent_deleted("session-a", agent_id="agent-x")

    assert result["changed"] is True
    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-a")["agentStatusCode"] == "deleted_agent"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_remember_uploaded_attachment_writes_only_target_session_row(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    _stub_compat_shell_side_effects(monkeypatch)
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    session_service._remember_session_uploaded_attachment(
        "session-a",
        {"artifactId": "art-1", "filename": "shot.png", "path": "secret"},
    )

    assert full_saves == []
    assert session_saves == ["session-a"]
    uploaded = load_session_chat_state(tmp_path, "session-a")["uploaded_attachments"]
    assert uploaded[0]["artifactId"] == "art-1"
    assert "path" not in uploaded[0]
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_append_cli_agent_lifecycle_event_writes_only_target_session_row(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    _stub_compat_shell_side_effects(monkeypatch)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(session_service, "_append_session_conversation_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_record_session_cycle_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_record_cli_agent_lifecycle_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_normalize_messages", lambda _session_id, messages: list(messages))
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    event = session_service.append_cli_agent_lifecycle_event(
        "session-a",
        event="closed",
        terminal_session={"terminalSessionId": "term-1", "label": "CLI Agent"},
    )

    assert event is not None
    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_get_session_stream_initial_state_does_not_assemble_compat_document(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda: {})
    monkeypatch.setattr(
        session_service,
        "_load_conversation_detail_target",
        lambda session_id, **_kwargs: {"id": session_id, "title": "A"},
    )
    monkeypatch.setattr(session_service, "_build_session_summary", lambda *_args, **_kwargs: {"id": "session-a"})
    monkeypatch.setattr(session_service, "_session_stream_initial_latest_message_payload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_session_ledger_sequence", lambda *_args, **_kwargs: 1)
    full_loads: list[str] = []
    original_load = session_service.load_chat_state
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda *args, **kwargs: full_loads.append("load") or original_load(*args, **kwargs),
    )

    payload = session_service.get_session_stream_initial_state("session-a")

    assert payload["sessionId"] == "session-a"
    assert full_loads == []


def test_get_active_session_detail_does_not_assemble_compat_document(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    save_session_chat_state(tmp_path, "session-a", load_session_chat_state(tmp_path, "session-a"), activate=True)
    monkeypatch.setattr(session_service, "get_session_detail", lambda session_id, **_kwargs: {"id": session_id})
    full_loads: list[str] = []
    original_load = session_service.load_chat_state
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda *args, **kwargs: full_loads.append("load") or original_load(*args, **kwargs),
    )

    detail = session_service.get_active_session_detail()

    assert detail == {"id": "session-a"}
    assert full_loads == []


def test_ensure_session_agent_prompt_snapshot_writes_only_target_session_row(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(
        session_service.prompt_template_service,
        "get_agent_prompt_snapshot_versions",
        lambda *_args, **_kwargs: {
            "builtinContentVersion": 1,
            "chatBasePromptVersion": 1,
            "corePromptSchemaVersion": 1,
        },
    )
    monkeypatch.setattr(
        session_service.prompt_template_service,
        "build_agent_prompt_snapshot",
        lambda *_args, **_kwargs: {"agentId": "agent-x", "promptTemplateId": "tpl", "content": "frozen"},
    )
    monkeypatch.setattr(session_service, "_record_session_prompt_snapshot_event", lambda *_args, **_kwargs: None)
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    snapshot = session_service._ensure_session_agent_prompt_snapshot(
        "session-a",
        {"agentId": "agent-x", "promptTemplateId": "tpl", "primaryMode": "chat"},
    )

    assert snapshot["content"] == "frozen"
    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-a")["agentPromptSnapshot"]["content"] == "frozen"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_ensure_session_agent_prompt_snapshot_builds_outside_chat_state_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(
        session_service.prompt_template_service,
        "get_agent_prompt_snapshot_versions",
        lambda *_args, **_kwargs: {
            "builtinContentVersion": 1,
            "chatBasePromptVersion": 1,
            "corePromptSchemaVersion": 1,
        },
    )
    lock_depth = {"value": 0}
    build_lock_depth: list[int] = []
    real_lock = session_service._CHAT_STATE_LOCK

    class HoldRecorder:
        def __enter__(self):
            lock_depth["value"] += 1
            return real_lock.__enter__()

        def __exit__(self, exc_type, exc, tb):
            lock_depth["value"] -= 1
            return real_lock.__exit__(exc_type, exc, tb)

    def fake_build(*_args, **_kwargs):
        build_lock_depth.append(lock_depth["value"])
        return {"agentId": "agent-x", "promptTemplateId": "tpl", "content": "frozen"}

    monkeypatch.setattr(session_service, "_CHAT_STATE_LOCK", HoldRecorder())
    monkeypatch.setattr(session_service.prompt_template_service, "build_agent_prompt_snapshot", fake_build)
    monkeypatch.setattr(session_service, "_record_session_prompt_snapshot_event", lambda *_args, **_kwargs: None)

    snapshot = session_service._ensure_session_agent_prompt_snapshot(
        "session-a",
        {"agentId": "agent-x", "promptTemplateId": "tpl", "primaryMode": "chat"},
    )

    assert snapshot["content"] == "frozen"
    assert build_lock_depth == [0]


def test_ensure_session_agent_prompt_snapshot_stops_before_build(tmp_path, monkeypatch):
    from core.orchestration.context_engine import AgentContextInterrupted

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(
        session_service.prompt_template_service,
        "get_agent_prompt_snapshot_versions",
        lambda *_args, **_kwargs: {
            "builtinContentVersion": 1,
            "chatBasePromptVersion": 1,
            "corePromptSchemaVersion": 1,
        },
    )
    monkeypatch.setattr(
        session_service.prompt_template_service,
        "build_agent_prompt_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("build should not run after stop")),
    )
    monkeypatch.setattr(session_service, "_record_session_prompt_snapshot_event", lambda *_args, **_kwargs: None)
    checks = {"count": 0}

    def interrupt_checker():
        checks["count"] += 1
        return "operator requested stop" if checks["count"] > 1 else ""

    with pytest.raises(AgentContextInterrupted) as exc_info:
        session_service._ensure_session_agent_prompt_snapshot(
            "session-a",
            {"agentId": "agent-x", "promptTemplateId": "tpl", "primaryMode": "chat"},
            interrupt_checker=interrupt_checker,
        )

    assert exc_info.value.stage == "prepare_prompt_snapshot.before_build"
    assert load_session_chat_state(tmp_path, "session-a").get("agentPromptSnapshot") is None


def test_turn_completion_snapshot_does_not_assemble_compat_document(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(session_service, "reconcile_stale_chat_turn_work_runs", lambda **_kwargs: [])
    monkeypatch.setattr(session_service, "_repair_stale_running_conversation", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(session_service, "_find_turn_scoped_assistant_message", lambda *_args, **_kwargs: None)
    full_loads: list[str] = []
    original_load = session_service.load_chat_state
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda *args, **kwargs: full_loads.append("load") or original_load(*args, **kwargs),
    )

    snapshot = session_service.get_session_turn_completion_snapshot("session-a", "turn-a")

    assert snapshot["sessionId"] == "session-a"
    assert snapshot["lastTurnStatus"] == "ready"
    assert full_loads == []
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_turn_completion_snapshot_ignores_tool_result_compatibility_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    monkeypatch.setattr(session_service, "reconcile_stale_chat_turn_work_runs", lambda **_kwargs: [])
    monkeypatch.setattr(session_service, "_repair_stale_running_conversation", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda *_args, **_kwargs: [])
    tool_shell = {
        "role": "assistant",
        "content": "batch_web_search_tool",
        "toolCalls": [
            {"name": "batch_web_search_tool", "id": "call-1", "status": "failed"},
        ],
        "metadata": {"kind": "tool_result", "turnId": "turn-tool-error"},
    }
    monkeypatch.setattr(
        session_service,
        "_find_turn_scoped_assistant_message",
        lambda *_args, **_kwargs: tool_shell,
    )

    snapshot = session_service.get_session_turn_completion_snapshot("session-a", "turn-tool-error")

    assert snapshot["assistantText"] == ""
    assert snapshot["assistantMessageFound"] is False
    assert snapshot["assistantTurnId"] == ""


def test_turn_completion_snapshot_projects_continuation_progress_evidence(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="paused_limit")
    monkeypatch.setattr(
        session_service,
        "reconcile_stale_chat_turn_work_runs",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        session_service,
        "_repair_stale_running_conversation",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        session_service,
        "_session_ledger_visible_messages",
        lambda *_args, **_kwargs: [],
    )
    assistant = {
        "role": "assistant",
        "content": "连续多轮没有产生新的任务进展。",
        "turnId": "turn-progress",
        "metadata": {
            "continuation_pause_reason": "runaway_no_progress",
            "continuation_no_progress_count": 3,
            "continuation_progress_advanced": True,
        },
    }
    monkeypatch.setattr(
        session_service,
        "_find_turn_scoped_assistant_message",
        lambda *_args, **_kwargs: assistant,
    )

    snapshot = session_service.get_session_turn_completion_snapshot(
        "session-a",
        "turn-progress",
    )

    assert snapshot["continuationPauseReason"] == "runaway_no_progress"
    assert snapshot["continuationNoProgressCount"] == 3
    assert snapshot["continuationProgressAdvanced"] is True


def test_settle_stale_chat_turn_writes_only_target_session_row(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path)
    monkeypatch.setattr(session_service, "_persist_chat_turn_work_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_set_session_running", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_clear_session_turn_control", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_append_session_runtime_notice", lambda notices, notice: [notice])
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    from core.web.services.session import turn_diagnostics

    result = turn_diagnostics._settle_stale_chat_turn_work_run(
        {"runId": "turn-a", "sessionId": "session-a", "status": "running"},
        reason="absolute_stale",
    )

    assert result is not None
    assert full_saves == []
    assert session_saves == ["session-a"]
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "failed_runtime"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_reset_agent_direct_session_saves_replacement_without_full_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_two_runtime_rows(tmp_path, status_a="ready")
    _stub_compat_shell_side_effects(monkeypatch)
    monkeypatch.setattr(session_service, "get_agent", lambda *_args, **_kwargs: {"agentId": "agent-x", "displayName": "X"})
    monkeypatch.setattr(session_service, "_ensure_agent_directory_conversation_materialized", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_repair_stale_running_conversation", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        session_service,
        "_normalize_conversation",
        lambda raw, **_kwargs: {"id": str(raw.get("conversation_id") or "")},
    )
    monkeypatch.setattr(session_service, "_conversation_phase", lambda *_args, **_kwargs: "ready")
    monkeypatch.setattr(session_service, "_record_session_delete_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_ensure_conversation_workspace_metadata", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        session_service.agent_directory_service,
        "update_agent_instance",
        lambda *_args, **_kwargs: None,
    )
    delete_calls: list[str] = []
    monkeypatch.setattr(
        session_service,
        "_delete_chat_session_state",
        lambda session_id, **_kwargs: delete_calls.append(str(session_id)) or {"nextActiveSessionId": "replacement"},
    )
    full_saves, session_saves = _spy_runtime_saves(monkeypatch)

    result = session_service.reset_agent_direct_session_lightweight("session-a", agent_id="agent-x", title="Replacement")

    replacement_id = str(result.get("replacementDirectSessionId") or "")
    assert replacement_id
    assert delete_calls == ["session-a"]
    assert full_saves == []
    assert session_saves == [replacement_id]
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"
    assert load_session_chat_state(tmp_path, replacement_id)["title"] == "Replacement"
