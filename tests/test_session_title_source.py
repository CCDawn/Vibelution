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


def _patch_creation(monkeypatch):
    _patch_writes(monkeypatch)
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.sync_conversation_record",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(session_service, "_ensure_session_agent_prompt_snapshot", lambda *_a, **_k: None)


def _created_session_id(created):
    return str((created or {}).get("id") or (created or {}).get("conversation_id") or "")


def _create_agent(*, display_name):
    from core.web.services import agent_directory_service

    return agent_directory_service.create_agent_instance(
        display_name=display_name,
        prompt_template_id="prompt-chat-default",
    )


def test_create_session_without_title_starts_as_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _patch_creation(monkeypatch)

    created = session_service.create_chat_session(title="")
    session_id = _created_session_id(created)
    assert session_id
    row = load_session_chat_state(tmp_path, session_id)
    assert row["title_source"] == "placeholder"
    assert session_service.apply_generated_session_title(session_id, "生成标题") is True
    assert load_session_chat_state(tmp_path, session_id)["title"] == "生成标题"


def test_create_session_agent_display_name_fallback_starts_as_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _patch_creation(monkeypatch)
    agent = _create_agent(display_name="科研协调")
    agent_id = str(agent.get("agentId") or "")

    created = session_service.create_chat_session(title="", agent_id=agent_id)
    session_id = _created_session_id(created)
    row = load_session_chat_state(tmp_path, session_id)
    assert row["title"] == "科研协调"
    assert row["title_source"] == "placeholder"
    assert session_service.apply_generated_session_title(session_id, "量子计算综述") is True


def test_create_session_explicit_title_stays_manual(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _patch_creation(monkeypatch)

    created = session_service.create_chat_session(title="固定房间标题")
    session_id = _created_session_id(created)
    row = load_session_chat_state(tmp_path, session_id)
    assert row["title_source"] == "manual"
    assert session_service.apply_generated_session_title(session_id, "自动标题") is False


def test_create_session_declared_placeholder_title_can_be_generated(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _patch_creation(monkeypatch)

    created = session_service.create_chat_session(title="新 Agent", title_source="placeholder")
    session_id = _created_session_id(created)
    row = load_session_chat_state(tmp_path, session_id)
    assert row["title"] == "新 Agent"
    assert row["title_source"] == "placeholder"
    assert session_service.apply_generated_session_title(session_id, "代码助手") is True


def test_ensure_agent_direct_session_starts_as_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _patch_creation(monkeypatch)
    agent = _create_agent(display_name="团队协调者")
    agent_id = str(agent.get("agentId") or "")

    repaired = session_service.ensure_agent_direct_session(agent_id=agent_id, title="团队协调者")
    session_id = _created_session_id(repaired)
    row = load_session_chat_state(tmp_path, session_id)
    assert row["title"] == "团队协调者"
    assert row["title_source"] == "placeholder"
    assert session_service.apply_generated_session_title(session_id, "实验规划") is True


def test_reset_agent_direct_session_replacement_starts_as_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _patch_creation(monkeypatch)
    agent = _create_agent(display_name="重置协调者")
    agent_id = str(agent.get("agentId") or "")
    _seed(tmp_path, title="旧会话", agent_id=agent_id, conversation_index_kind="personal_agent")

    result = session_service.reset_agent_direct_session_lightweight(
        "session-a", agent_id=agent_id, title="重置协调者"
    )
    replacement_id = str(
        result.get("replacementDirectSessionId") or result.get("nextActiveSessionId") or ""
    )
    assert replacement_id
    row = load_session_chat_state(tmp_path, replacement_id)
    assert row["title_source"] == "placeholder"
    assert session_service.apply_generated_session_title(replacement_id, "写作助手") is True


def test_make_empty_conversation_default_title_stays_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _patch_creation(monkeypatch)

    placeholder = session_service._make_empty_conversation(
        "session-default", title="新会话", timestamp="2026-09-15T00:00:00"
    )
    manual = session_service._make_empty_conversation(
        "session-named", title="我命名的会话", timestamp="2026-09-15T00:00:00"
    )
    assert placeholder["title_source"] == "placeholder"
    assert manual["title_source"] == "manual"
