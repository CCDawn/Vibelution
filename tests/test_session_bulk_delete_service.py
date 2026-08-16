"""Bulk session delete service regressions."""

from __future__ import annotations

import pytest

from core.web.services import agent_directory_service, session_service
from core.web.services.session import session_bulk_delete


@pytest.fixture()
def isolated_project(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_bulk_delete_treats_missing_sessions_as_idempotent_success(isolated_project):
    direct = session_service.create_chat_session(title="Bulk Keep")
    direct_id = str(direct.get("id") or direct.get("sessionId") or "").strip()
    missing_id = "session-missing-bulk"

    result = session_bulk_delete.bulk_delete_chat_sessions([direct_id, missing_id])

    assert result["summary"]["successCount"] == 2
    assert result["summary"]["skippedCount"] == 0
    assert {item["sessionId"] for item in result["success"]} == {direct_id, missing_id}
    assert session_service.get_session_detail(direct_id) is None


def test_bulk_delete_rejects_over_limit():
    too_many = [f"session-{index}" for index in range(session_bulk_delete.MAX_BULK_SESSION_IDS + 1)]
    with pytest.raises(session_service.SessionValidationError) as exc_info:
        session_bulk_delete.bulk_delete_chat_sessions(too_many)
    assert str(session_bulk_delete.MAX_BULK_SESSION_IDS) in str(exc_info.value)
