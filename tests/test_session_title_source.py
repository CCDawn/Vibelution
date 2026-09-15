from __future__ import annotations

import pytest

from core.ui.chat_state import load_session_chat_state, save_chat_state
from core.web.services import session_service


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


def _seed(tmp_path, **overrides):
    row = {
        "conversation_id": "session-a",
        "title": "默认对话",
        "session_kind": "main",
        "last_turn_status": "ready",
    }
    row.update(overrides)
    save_chat_state(tmp_path, {"version": 1, "conversations": [row]})


def _patch_writes(monkeypatch):
    monkeypatch.setattr(
        session_service, "_is_session_workspace_intentionally_deleted", lambda *_a, **_k: False
    )
    monkeypatch.setattr(session_service, "_conversation_is_read_only", lambda *_a, **_k: False)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_a, **_k: {"accepted": True})
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.touch_directory_session_safe",
        lambda *_a, **_k: None,
    )


def test_placeholder_source_allows_generation_and_marks_auto(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed(tmp_path, title="新会话", title_source="placeholder")
    _patch_writes(monkeypatch)

    assert session_service.apply_generated_session_title("session-a", "会话标题生成") is True
    row = load_session_chat_state(tmp_path, "session-a")
    assert row["title"] == "会话标题生成"
    assert row["title_source"] == "auto"


def test_manual_source_blocks_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed(tmp_path, title="我命名的会话", title_source="manual")
    _patch_writes(monkeypatch)

    assert session_service.apply_generated_session_title("session-a", "自动标题") is False
    assert load_session_chat_state(tmp_path, "session-a")["title"] == "我命名的会话"


def test_agent_named_session_without_source_still_blocks_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed(tmp_path, title="科研协调")
    _patch_writes(monkeypatch)

    assert session_service.apply_generated_session_title("session-a", "自动标题") is False


def test_legacy_placeholder_without_source_still_allows_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed(tmp_path, title="默认对话")
    _patch_writes(monkeypatch)

    assert session_service.apply_generated_session_title("session-a", "旧数据标题") is True


def test_manual_rename_records_manual_source_and_locks_out_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed(tmp_path, title="新会话", title_source="placeholder")
    _patch_writes(monkeypatch)

    session_service.update_chat_session_title("session-a", "手动命名")
    row = load_session_chat_state(tmp_path, "session-a")
    assert row["title"] == "手动命名"
    assert row["title_source"] == "manual"
    assert session_service.apply_generated_session_title("session-a", "自动标题") is False
