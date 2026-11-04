# -*- coding: utf-8 -*-
"""Session detail ``queueHold`` projection: stop-frozen queues surface the hold.

An explicit user stop writes a ``queued_turn_hold`` marker that freezes the
session's queued rows until a new message (or an explicit queue op) clears it.
The session detail projection carries that marker as the public ``queueHold``
shape (``{reason, turnId, heldAt}`` or null) so the renderer can say "queue
paused; send a new message to resume" instead of leaving a frozen queue
looking like silently lost work. These tests pin that contract at the shared
service projection layer that both the workbench detail endpoint and the
Launcher assistant native detail reuse.
"""

from __future__ import annotations

import pytest

from core.web.services import session_service
from core.web.services.session import queued_turns
from tests.test_session_pending_question import _patch_queue_side_effects
from tests.test_session_submit import _prepare_default_submit_session


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


@pytest.fixture
def seeded_session(tmp_path, monkeypatch) -> str:
    session_id = _prepare_default_submit_session(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: False)
    return session_id


def test_detail_projects_hold_marker_after_user_stop(seeded_session):
    queued_turns.set_session_queue_hold(seeded_session, turn_id="turn-stop-1")
    detail = session_service.get_session_detail(seeded_session)
    hold = detail.get("queueHold")
    assert isinstance(hold, dict)
    assert hold.get("reason") == "user_stop"
    assert hold.get("turnId") == "turn-stop-1"
    assert str(hold.get("heldAt") or "").strip()


def test_detail_projects_null_without_hold(seeded_session):
    detail = session_service.get_session_detail(seeded_session)
    assert detail.get("queueHold") is None


def test_enqueueing_a_new_message_clears_the_projected_hold(seeded_session, monkeypatch):
    _patch_queue_side_effects(monkeypatch)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: True)
    queued_turns.set_session_queue_hold(seeded_session, turn_id="turn-stop-1")
    queued_turns.enqueue_session_queued_turn(
        seeded_session,
        content="新消息恢复队列",
        attachments=[],
        references=[],
        mental_model_enabled=None,
        runtime_status_enabled=None,
        turn_mode="normal",
        write_intent=None,
        client_submission_id="sub-resume-hold",
    )
    detail = session_service.get_session_detail(seeded_session)
    assert detail.get("queueHold") is None
    assert any(
        str(row.get("content") or "") == "新消息恢复队列"
        for row in detail.get("queuedTurns") or []
    )
