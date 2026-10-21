# -*- coding: utf-8 -*-
"""Detail target repair path lock semantics (chat-fix3 lane E).

Regression coverage for the lost-update race where ``get_session_detail``
repaired a stale unlocked row snapshot and wrote the whole row back,
clobbering a concurrent worker commit (lost terminal status, lost runtime
notices). The repair path must hold the facade mutation lock, re-read the
freshest row inside it, and keep pure reads lock-free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import (
    load_session_chat_state,
    save_chat_state,
)
from core.web.services import session_service


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)


def _seed_store(tmp_path: Path, row: dict[str, Any]) -> None:
    save_chat_state(tmp_path, {"version": 1, "conversations": [row]})


def _stub_repairs(monkeypatch: pytest.MonkeyPatch, *, dirty_workspace: bool = True):
    monkeypatch.setattr(
        session_service,
        "_repair_child_root_agent_direct_session_bindings",
        lambda payload, *, agent_by_id: False,
    )
    monkeypatch.setattr(session_service, "_repair_stale_running_conversation", lambda conversation: False)
    monkeypatch.setattr(
        session_service,
        "_ensure_conversation_agent_metadata",
        lambda conversation, *, agent_by_id: False,
    )

    def _workspace_repair(conversation: dict[str, Any]) -> bool:
        if not dirty_workspace:
            return False
        conversation["workspace_path"] = "repaired-workspace"
        return True

    monkeypatch.setattr(session_service, "_ensure_conversation_workspace_metadata", _workspace_repair)
    monkeypatch.setattr(session_service, "_agent_lookup_for_conversations", lambda: {})
    monkeypatch.setattr(session_service, "_agent_directory_stub_hidden_team_member_ids", lambda: set())


def _spy_normalize(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_normalize(raw: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        seen["raw"] = raw
        seen["kwargs"] = kwargs
        return {"id": raw.get("conversation_id")}

    monkeypatch.setattr(session_service, "_normalize_conversation", fake_normalize)
    return seen


class _RecordingLock:
    def __init__(self) -> None:
        self.enters = 0

    def __enter__(self) -> "_RecordingLock":
        self.enters += 1
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_detail_repair_rereads_under_lock_and_keeps_worker_terminal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker terminal commit landing inside the repair window survives.

    The caller's snapshot is stale (``running``, no notices). The first store
    read of the repair path triggers an injected worker commit (read-merge-save
    under the mutation lock, mirroring ``_commit_session_turn_runtime_state``).
    The repair must operate on the re-read row so the write-back keeps the
    worker terminal state instead of restoring the stale snapshot.
    """

    session_id = "session-race"
    stale_row = {
        "conversation_id": session_id,
        "title": "轮询会话",
        "last_turn_status": "running",
    }
    _seed_store(tmp_path, dict(stale_row))
    _stub_repairs(monkeypatch)
    seen = _spy_normalize(monkeypatch)

    real_load = session_service.load_session_chat_state
    real_save = session_service.save_session_chat_state
    worker_committed = {"done": False}

    def load_with_worker_commit(project_root: Path, load_session_id: str):
        if not worker_committed["done"]:
            worker_committed["done"] = True
            worker_view = real_load(project_root, load_session_id) or {}
            merged = dict(worker_view)
            merged["last_turn_status"] = "ready"
            merged["runtime_notices"] = [{"kind": "turn_finished", "message": "worker terminal"}]
            with session_service._CHAT_STATE_LOCK:
                real_save(project_root, load_session_id, merged)
        return real_load(project_root, load_session_id)

    monkeypatch.setattr(session_service, "load_session_chat_state", load_with_worker_commit)

    target = session_service._load_conversation_detail_target(
        session_id,
        # The caller's stale unlocked snapshot, as get_session_detail supplies it.
        payload={"conversations": [dict(stale_row)]},
        repair=True,
        agent_by_id={},
    )

    # The repair path re-read the store under the lock, so the injected worker
    # commit actually landed (the old unlocked repair never re-read here).
    assert worker_committed["done"] is True
    assert seen["raw"]["last_turn_status"] == "ready"
    assert seen["raw"]["runtime_notices"][0]["kind"] == "turn_finished"
    assert seen["kwargs"]["ensure_workspace"] is True
    assert target == {"id": session_id}

    persisted = load_session_chat_state(tmp_path, session_id)
    assert persisted["last_turn_status"] == "ready"
    assert persisted["runtime_notices"][0]["kind"] == "turn_finished"
    assert persisted["workspace_path"] == "repaired-workspace"


def test_pure_read_detail_target_does_not_take_mutation_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """repair=False is the hot poll path: no lock, no store traffic, no save."""

    row = {
        "conversation_id": "session-read",
        "title": "读会话",
        "last_turn_status": "ready",
    }
    _stub_repairs(monkeypatch, dirty_workspace=False)
    seen = _spy_normalize(monkeypatch)
    lock = _RecordingLock()
    monkeypatch.setattr(session_service, "_CHAT_STATE_LOCK", lock)
    loads: list[str] = []
    monkeypatch.setattr(
        session_service,
        "load_session_chat_state",
        lambda root, session_id: loads.append(session_id) or dict(row),
    )
    saves: list[str] = []
    monkeypatch.setattr(
        session_service,
        "save_session_chat_state",
        lambda root, session_id, conversation, **kwargs: saves.append(session_id),
    )

    target = session_service._load_conversation_detail_target(
        "session-read",
        payload={"conversations": [dict(row)]},
        repair=False,
        agent_by_id={},
        lightweight=True,
    )

    assert lock.enters == 0
    assert loads == []
    assert saves == []
    assert target == {"id": "session-read"}
    assert seen["kwargs"]["ensure_workspace"] is False


def test_repair_clean_row_takes_mutation_lock_once_without_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean repair pass holds the lock for one bounded read and never writes."""

    row = {
        "conversation_id": "session-clean",
        "title": "干净会话",
        "last_turn_status": "ready",
        "workspace_path": "already-set",
    }
    _stub_repairs(monkeypatch, dirty_workspace=False)
    seen = _spy_normalize(monkeypatch)
    lock = _RecordingLock()
    monkeypatch.setattr(session_service, "_CHAT_STATE_LOCK", lock)
    loads: list[str] = []
    monkeypatch.setattr(
        session_service,
        "load_session_chat_state",
        lambda root, session_id: loads.append(session_id) or dict(row),
    )
    saves: list[str] = []
    monkeypatch.setattr(
        session_service,
        "save_session_chat_state",
        lambda root, session_id, conversation, **kwargs: saves.append(session_id),
    )

    target = session_service._load_conversation_detail_target(
        "session-clean",
        payload={"conversations": [dict(row)]},
        repair=True,
        agent_by_id={},
    )

    assert lock.enters == 1
    assert loads == ["session-clean"]
    assert saves == []
    assert target == {"id": "session-clean"}
