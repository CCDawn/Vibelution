# -*- coding: utf-8 -*-
"""pendingQuestion single slot: lifecycle, one-time consumption, rail switch.

Batch-4 human-slot lane. The slot is the structured "the assistant asked its
person something" fact: set once, consumed by the next accepted person
message (``consumedAt`` stamp, idempotent), or dropped by the explicit clear
action. While a slot is pending, ``session_waits_for_person`` reports the
session as waiting for its person regardless of the resting phase. No writer
exists yet (see the module docstring in ``pending_question.py``) — these
tests pin the storage contract the future writer must keep.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.chat.conversation_ledger import append_conversation_event
from core.chat.turn_journal import EVENT_USER_MESSAGE
from core.infrastructure import developer_sandbox
from core.web.services import session_service
from core.web.services.session import managed_continuation, pending_question, queued_turns
from tests.test_session_submit import _prepare_default_submit_session


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


@pytest.fixture
def seeded_session(tmp_path, monkeypatch) -> str:
    session_id = _prepare_default_submit_session(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: False)
    return session_id


def _patch_queue_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _sid, **_kw: None)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _sid: None)


def _assert_pending(slot: dict[str, Any] | None) -> None:
    assert slot is not None
    assert str(slot.get("id") or "").startswith("pq-")
    assert str(slot.get("questionText") or "").strip()
    assert str(slot.get("askedAt") or "").strip()
    assert str(slot.get("consumedAt") or "") == ""


def test_slot_lifecycle_set_then_consume_is_one_time(seeded_session):
    slot = pending_question.set_session_pending_question(
        seeded_session, question_text="需要我把三份摘要合并成一页吗？"
    )
    _assert_pending(slot)
    assert pending_question.session_pending_question(seeded_session) == slot
    assert pending_question.conversation_pending_question(
        session_service.load_session_chat_state(session_service.PROJECT_ROOT, seeded_session)
    ) == slot

    consumed = pending_question.consume_session_pending_question(seeded_session)
    assert consumed is not None
    assert str(consumed["consumedAt"] or "").strip()
    assert consumed["consumedBy"] == "human_message"
    # One-time consumption: replayed hooks and parallel submissions cannot
    # double-consume.
    assert pending_question.consume_session_pending_question(seeded_session) is None
    assert pending_question.conversation_pending_question(
        session_service.load_session_chat_state(session_service.PROJECT_ROOT, seeded_session)
    ) is None
    stored = pending_question.session_pending_question(seeded_session)
    assert stored is not None and str(stored["consumedAt"] or "").strip()


def test_clear_is_the_explicit_reset(seeded_session):
    pending_question.set_session_pending_question(seeded_session, question_text="要继续吗？")
    assert pending_question.clear_session_pending_question(seeded_session) is True
    assert pending_question.session_pending_question(seeded_session) is None
    # Clearing an absent slot is a no-op.
    assert pending_question.clear_session_pending_question(seeded_session) is False


def test_accepted_raw_submit_consumes_pending_slot(seeded_session, tmp_path, monkeypatch):
    scheduled: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(dict(context)))
    pending_question.set_session_pending_question(
        seeded_session, question_text="要把结论写成简报吗？"
    )
    reply = session_service.submit_session_message_lightweight(
        seeded_session,
        "好，写成简报",
        client_submission_id="sub-answer-question",
    )
    assert reply.get("turnId")
    stored = pending_question.session_pending_question(seeded_session)
    assert stored is not None and str(stored["consumedAt"] or "").strip()


def test_machine_sourced_submit_does_not_consume(seeded_session, monkeypatch):
    scheduled: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(dict(context)))
    pending_question.set_session_pending_question(
        seeded_session, question_text="要把结论写成简报吗？"
    )
    submitted = session_service.submit_session_message(
        seeded_session,
        "机器回执：任务已完成",
        message_source="agent_inbox",
        message_metadata={"kind": "agent_inbox_message"},
        client_submission_id="sub-machine-1",
        include_started_turn_id=True,
    )
    # Full submit returns the session detail; a started turn proves acceptance.
    assert str(submitted.get("startedTurnId") or "").strip()
    stored = pending_question.session_pending_question(seeded_session)
    _assert_pending(stored)


def test_queued_user_row_consumes_pending_slot_on_arrival(seeded_session, monkeypatch):
    _patch_queue_side_effects(monkeypatch)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: True)
    pending_question.set_session_pending_question(
        seeded_session, question_text="附件里的数据要全部重跑吗？"
    )
    row = queued_turns.enqueue_session_queued_turn(
        seeded_session,
        content="全部重跑",
        attachments=[],
        references=[],
        mental_model_enabled=False,
        runtime_status_enabled=False,
        turn_mode="",
        write_intent=False,
        client_submission_id="sub-queued-answer",
    )
    assert row.get("status") == "queued"
    stored = pending_question.session_pending_question(seeded_session)
    assert stored is not None and str(stored["consumedAt"] or "").strip()


def test_rail_off_disables_predicate_contribution_and_consume_hooks(
    seeded_session, tmp_path, monkeypatch
):
    scheduled: list[dict] = []
    monkeypatch.setenv(managed_continuation.WAITS_FOR_PERSON_RAIL_ENV, "0")
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(dict(context)))
    pending_question.set_session_pending_question(seeded_session, question_text="要继续吗？")

    # The slot stops counting in the predicate (session is ready — not resting).
    assert managed_continuation.session_waits_for_person(session_service, seeded_session) is False

    # The submit-side consume hook is skipped: the slot stays pending.
    session_service.submit_session_message_lightweight(
        seeded_session, "继续", client_submission_id="sub-rail-off-1",
    )
    _assert_pending(pending_question.session_pending_question(seeded_session))
