# -*- coding: utf-8 -*-
"""会话 workspaceRoot 绝对根投影测试。

``workspacePath`` 保持相对路径契约（workspace/sessions/<token>）不变；
新增 ``workspaceRoot`` 把相对根解析为绝对路径（PROJECT_ROOT 基准），
绝对输入原样透传。桌面桥 openPath 只收绝对路径，markdown 的
workspace 文件链接依赖该字段激活。
"""

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    self_evolution_control_service,
    session_service,
    supervised_control_service,
)
from tests.helpers.web_chat_state import _seed_chat_state

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


def _conversation(*, workspace_path: str | None = None) -> dict:
    conversation = {
        "conversation_id": "session-wsroot",
        "title": "工作区根",
        "agent_id": "",
        "updated_at": "2026-09-29T10:00:00",
        "last_turn_status": "ready",
        "messages": [
            {"role": "user", "content": "看下文件", "timestamp": "2026-09-29T09:59:00"},
            {"role": "assistant", "content": "好的", "timestamp": "2026-09-29T10:00:00"},
        ],
    }
    if workspace_path is not None:
        conversation["workspacePath"] = workspace_path
    return conversation


def test_detail_workspace_root_resolves_relative_against_project_root(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, conversations=[_conversation()])
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    body = client.get("/api/sessions/session-wsroot").json()
    # 相对契约不变；新增根为绝对路径。
    assert body["workspacePath"] == "workspace/sessions/session-wsroot"
    assert body["workspaceRoot"] == str(tmp_path / "workspace" / "sessions" / "session-wsroot")


def test_summary_workspace_root_passthrough_absolute(tmp_path, monkeypatch):
    # 绝对根直接透传、空值省略：对纯 helper 断言，避免依赖目录接口的存储细节。
    from core.web.services.session import projection as session_projection

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    resolver = session_projection._session_workspace_root_value
    absolute = str(tmp_path / "elsewhere")
    assert resolver(absolute) == absolute
    assert resolver(str(tmp_path / "w" / "s")) == str(tmp_path / "w" / "s")
    assert resolver("") == ""
    assert resolver(None) == ""
    assert resolver("   ") == ""
