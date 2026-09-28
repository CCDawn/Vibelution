# -*- coding: utf-8 -*-
"""会话详情轮级 changedFiles 投影、fork 首消息投影与 rewind API 测试。

零差异证据：无 fork、无账本检查点的普通会话，详情输出的消息 metadata
不新增任何字段（逐字段断言）。
"""

import pytest
from fastapi.testclient import TestClient

from core.chat import file_change_ledger as fcl
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    self_evolution_control_service,
    session_service,
    supervised_control_service,
)
from tests.helpers.web_chat_state import _seed_chat_state

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

# _seed_chat_state 把第 index 条消息写进 journal，turn id 固定为
# <session_id>-seed-<index:03d>；assistant 是第二条。
ASSISTANT_TURN_ID = "session-live-seed-002"


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


def _conversation(*, messages: list, extra: dict | None = None) -> dict:
    conversation = {
        "conversation_id": "session-live",
        "title": "会话",
        "agent_id": "",
        "updated_at": "2026-09-28T10:00:00",
        "last_turn_status": "ready",
        "messages": messages,
    }
    if extra:
        conversation.update(extra)
    return conversation


def _turn_messages() -> list:
    return [
        {"role": "user", "content": "改一下文件", "timestamp": "2026-09-28T09:59:00"},
        {
            "role": "assistant",
            "content": "已改完",
            "timestamp": "2026-09-28T10:00:00",
        },
    ]


def _seed_ledger_turn(project_root, turn_id: str) -> None:
    target = project_root / "src" / "demo.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("l1\n", encoding="utf-8")
    created = project_root / "src" / "new.txt"
    with fcl.bind_turn_scope("session-live", turn_id, project_root=project_root):
        fcl.capture_pre_write(target)
        fcl.capture_pre_write(created)
        target.write_text("l1\nl2\n", encoding="utf-8")
        created.write_text("n\n", encoding="utf-8")
        fcl.capture_post_write(target)
        fcl.capture_post_write(created)


def _detail_messages() -> list[dict]:
    response = client.get("/api/sessions/session-live")
    assert response.status_code == 200
    return response.json()["messages"]


def _assistant_message(messages: list[dict]) -> dict:
    return next(message for message in messages if message.get("role") == "assistant")


def test_session_detail_surfaces_changed_files_from_ledger(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[_conversation(messages=_turn_messages())],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_ledger_turn(tmp_path, ASSISTANT_TURN_ID)

    assistant = _assistant_message(_detail_messages())
    assert assistant["turnId"] == ASSISTANT_TURN_ID
    changed = assistant["metadata"]["changedFiles"]
    by_path = {item["path"]: item for item in changed}
    assert by_path["src/demo.txt"] == {
        "path": "src/demo.txt",
        "additions": 1,
        "deletions": 0,
        "state": "modified",
    }
    assert by_path["src/new.txt"]["state"] == "created"


def test_session_detail_without_ledger_keeps_metadata_untouched(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[_conversation(messages=_turn_messages())],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    assistant = _assistant_message(_detail_messages())
    # 普通会话零差异：metadata 不因账本投影新增键。
    assert "changedFiles" not in (assistant.get("metadata") or {})


def test_forked_session_stamps_first_message_metadata(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            _conversation(
                messages=_turn_messages(),
                extra={
                    "forkedFrom": {
                        "sessionId": "session-parent",
                        "nodeId": "node-1",
                        "scope": "visible_path",
                        "forkedAt": "2026-09-28T10:00:00",
                    }
                },
            )
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    messages = _detail_messages()
    assert messages[0]["metadata"]["forkedFromSessionId"] == "session-parent"
    for message in messages[1:]:
        assert "forkedFromSessionId" not in (message.get("metadata") or {})


def test_plain_session_has_no_fork_projection(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[_conversation(messages=_turn_messages())],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    for message in _detail_messages():
        assert "forkedFromSessionId" not in (message.get("metadata") or {})


def test_rewind_preview_and_apply_api(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[_conversation(messages=_turn_messages())],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_ledger_turn(tmp_path, ASSISTANT_TURN_ID)
    target = tmp_path / "src" / "demo.txt"
    created = tmp_path / "src" / "new.txt"
    assert target.read_text(encoding="utf-8") == "l1\nl2\n"

    preview_response = client.get(f"/api/sessions/session-live/rewind/{ASSISTANT_TURN_ID}")
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["sessionId"] == "session-live"
    assert preview["turnId"] == ASSISTANT_TURN_ID
    assert preview["canApply"] is True
    assert {item["path"] for item in preview["files"]} == {"src/demo.txt", "src/new.txt"}

    apply_response = client.post(
        "/api/sessions/session-live/rewind",
        json={"turnId": ASSISTANT_TURN_ID},
    )
    assert apply_response.status_code == 200
    applied = apply_response.json()
    assert applied["status"] == "applied"
    assert applied["alreadyApplied"] is False
    assert target.read_text(encoding="utf-8") == "l1\n"
    assert not created.exists()

    replay_response = client.post(
        "/api/sessions/session-live/rewind",
        json={"turnId": ASSISTANT_TURN_ID},
    )
    assert replay_response.status_code == 200
    assert replay_response.json()["alreadyApplied"] is True


def test_rewind_api_unknown_turn_is_404(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[_conversation(messages=_turn_messages())],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    preview_response = client.get("/api/sessions/session-live/rewind/turn-missing")
    assert preview_response.status_code == 404
    apply_response = client.post(
        "/api/sessions/session-live/rewind",
        json={"turnId": "turn-missing"},
    )
    assert apply_response.status_code == 200
    assert apply_response.json()["status"] == "empty"


def test_rewind_apply_rejects_unsafe_batch_with_409(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[_conversation(messages=_turn_messages())],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_ledger_turn(tmp_path, ASSISTANT_TURN_ID)
    target = tmp_path / "src" / "demo.txt"
    # 写入后被再次修改：strict 拒绝整批
    target.write_text("external edit\n", encoding="utf-8")

    conflict_response = client.post(
        "/api/sessions/session-live/rewind",
        json={"turnId": ASSISTANT_TURN_ID},
    )
    assert conflict_response.status_code == 409
    detail = conflict_response.json()["detail"]
    assert detail["unsafeFiles"]
    assert any(
        item["classification"] == "external_modified" for item in detail["unsafeFiles"]
    )
    assert target.read_text(encoding="utf-8") == "external edit\n"

    forced_response = client.post(
        "/api/sessions/session-live/rewind",
        json={"turnId": ASSISTANT_TURN_ID, "force": True},
    )
    assert forced_response.status_code == 200
    forced = forced_response.json()
    # force 按文件应用：安全文件照常恢复，unsafe 文件跳过并上报。
    assert [item["path"] for item in forced["applied"]] == ["src/new.txt"]
    assert any(
        item["classification"] == "external_modified" for item in forced["skipped"]
    )
    assert target.read_text(encoding="utf-8") == "external edit\n"
    assert not (tmp_path / "src" / "new.txt").exists()


def test_rewind_api_validation_error_is_422(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[_conversation(messages=_turn_messages())],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post("/api/sessions/session-live/rewind", json={"turnId": ""})
    assert response.status_code == 422
