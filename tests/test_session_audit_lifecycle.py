"""Real Session lifecycle with the directory and all stores isolated together."""
from __future__ import annotations

from pathlib import Path

from core.infrastructure import developer_sandbox
from core.runtime_manager import evolution_store
from core.ui.chat_state import chat_state_lock_path, load_session_chat_state
from core.web.services import session_service
from core.web.services.session import directory_runtime


def test_create_list_rename_with_initialized_directory_and_isolated_stores(
    tmp_path, monkeypatch, isolate_runtime_manager_evolution_store
):
    drain_background_reads = isolate_runtime_manager_evolution_store
    assert callable(drain_background_reads)
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    assert Path(session_service.PROJECT_ROOT).resolve() == tmp_path.resolve()
    assert chat_state_lock_path(tmp_path).resolve().is_relative_to(tmp_path.resolve())

    stores = (session_service._WORK_RUN_STORE, evolution_store._WORK_RUN_STORE)
    assert all(Path(store.root).resolve().is_relative_to(tmp_path.resolve()) for store in stores)

    directory_runtime.shutdown_session_directory_runtime()
    try:
        status = directory_runtime.initialize_session_directory_runtime(project_root=tmp_path)
        assert status.status == "ready"
        assert directory_runtime.directory_store_project_root() == tmp_path.resolve()

        created = session_service.create_chat_session(
            title="Isolated lifecycle", lightweight=True, idempotency_key="isolated-lifecycle"
        )
        session_id = created["id"]
        replay = session_service.create_chat_session(
            title="Isolated lifecycle", lightweight=True, idempotency_key="isolated-lifecycle"
        )
        assert replay["id"] == session_id
        listed = {item["id"]: item for item in session_service.list_sessions()}
        assert listed[session_id]["title"] == "Isolated lifecycle"

        renamed = session_service.update_chat_session_title(session_id, "Isolated renamed")
        persisted = load_session_chat_state(tmp_path, session_id)
        assert renamed["title"] == persisted["title"] == "Isolated renamed"
        assert persisted["title_source"] == "manual"
        relisted = {item["id"]: item for item in session_service.list_sessions()}
        assert relisted[session_id]["title"] == "Isolated renamed"
    finally:
        try:
            drain_background_reads()
        finally:
            directory_runtime.shutdown_session_directory_runtime()
