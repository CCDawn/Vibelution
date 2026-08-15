import json
import multiprocessing
import os
import threading
import time
from contextlib import contextmanager
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
