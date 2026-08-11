import json
import multiprocessing
import os
from contextlib import contextmanager

import pytest

from core.ui.chat_state import chat_state_path, load_chat_state, save_chat_state
from core.web.services import session_service


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


def test_save_chat_state_uses_valid_replace_target(tmp_path):
    payload = {"version": 1, "conversations": [{"conversation_id": "default", "messages": []}]}
    expected = {
        "version": 1,
        "state_revision": 1,
        "conversations": [{"conversation_id": "default"}],
    }

    save_chat_state(tmp_path, payload)

    path = chat_state_path(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert payload["conversations"][0]["messages"] == []
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


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
    agent_id: str,
    role: str,
    first_loaded,
    second_loaded,
    first_saved,
    result_queue,
) -> None:
    """Force the pre-fix stale-snapshot ordering across independent processes."""
    os.environ["VIBELUTION_DATA_HOME"] = data_home
    from core.web.services import session_service as child_session_service

    original_load = child_session_service.load_chat_state
    original_save = child_session_service.save_chat_state

    def controlled_load(project_root):
        state = original_load(project_root)
        if role == "first":
            first_loaded.set()
            second_loaded.wait(timeout=1.0)
        else:
            first_loaded.wait(timeout=2.0)
            second_loaded.set()
            first_saved.wait(timeout=2.0)
        return state

    def controlled_save(project_root, state):
        original_save(project_root, state)
        if role == "first":
            first_saved.set()

    child_session_service.load_chat_state = controlled_load
    child_session_service.save_chat_state = controlled_save
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
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    context = multiprocessing.get_context("spawn")
    first_loaded = context.Event()
    second_loaded = context.Event()
    first_saved = context.Event()
    result_queue = context.Queue()
    first = context.Process(
        target=_create_session_in_competing_process,
        args=(
            str(data_home),
            "",
            "first",
            first_loaded,
            second_loaded,
            first_saved,
            result_queue,
        ),
    )
    second = context.Process(
        target=_create_session_in_competing_process,
        args=(
            str(data_home),
            "",
            "second",
            first_loaded,
            second_loaded,
            first_saved,
            result_queue,
        ),
    )
    first.start()
    assert first_loaded.wait(timeout=10.0)
    second.start()
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
    state_path = data_home / "workspace" / "chat" / "chat_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    indexed_ids = {
        str(item.get("conversation_id") or "")
        for item in state.get("conversations", [])
        if isinstance(item, dict)
    }
    assert created_ids <= indexed_ids
