# -*- coding: utf-8 -*-
"""pendingQuestion single slot: lifecycle, one-time consumption, rail switch.

Batch-4 human-slot lane. The slot is the structured "the assistant asked its
person something" fact: set once, consumed by the next accepted person
message (``consumedAt`` stamp, idempotent), or dropped by the explicit clear
action. While a slot is pending, ``session_waits_for_person`` reports the
session as waiting for its person regardless of the resting phase.

Batch-5 writer: the settlement layer (``persist._persist_session_turn_result``)
now freezes a completed turn whose final visible reply ends on a question into
the slot — the tests below pin the writer contract (question-ending completed
turns write, statement endings / failed / aborted / pure-tool turns do not,
fresh questions overwrite, person submissions consume) plus the pure helpers
behind it.

Detail projection: the session detail response always carries
``pendingQuestion`` as the public four-field shape (``{id, questionText,
askedAt, turnId}``) or null; the tests at the bottom pin that contract
(consumed slots read null with the key intact, no slot reads null, the
lightweight poll path carries it, the rail switch blanks it, legacy slots
project an empty ``turnId``).
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


# ---------------------------------------------------------------------------
# Batch-5 writer: the settlement layer freezes question-ending turns
# ---------------------------------------------------------------------------


def _persist_turn(session_id: str, turn_id: str, result: dict[str, Any]) -> Any:
    """Drive the single settlement collection point like the worker does."""

    session_service._set_session_running(session_id, True, turn_id=turn_id)
    try:
        return session_service._persist_session_turn_result(
            session_id, result, turn_id=turn_id
        )
    finally:
        session_service._set_session_running(session_id, False, turn_id=turn_id)


def _completed_result(summary: str, **overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "completed",
        "summary": summary,
        "raw_output": summary,
    }
    result.update(overrides)
    return result


def _stored_slot(session_id: str) -> dict[str, Any] | None:
    return pending_question.session_pending_question(session_id)


def test_question_ending_completed_turn_writes_pending_slot(seeded_session):
    receipt = _persist_turn(
        seeded_session,
        "turn-ask-1",
        _completed_result("前三份摘要已经完成。\n\n要把剩余两份并入今晚的批处理吗？"),
    )
    assert receipt is not None and receipt.get("finalStatus") == "completed"
    slot = _stored_slot(seeded_session)
    _assert_pending(slot)
    assert slot["questionText"] == "要把剩余两份并入今晚的批处理吗？"
    assert str(slot["id"]).startswith("pq-")
    # The writer arms the waitsForPerson predicate on its own.
    assert managed_continuation.session_waits_for_person(session_service, seeded_session) is True


def test_statement_ending_completed_turn_writes_no_slot(seeded_session):
    _persist_turn(
        seeded_session,
        "turn-done-1",
        _completed_result("三份摘要全部完成，已写入简报。"),
    )
    assert _stored_slot(seeded_session) is None


def test_english_question_ending_also_writes(seeded_session):
    _persist_turn(
        seeded_session,
        "turn-ask-en",
        _completed_result("Analysis is done.\n\nDo you want me to merge the reports?"),
    )
    slot = _stored_slot(seeded_session)
    _assert_pending(slot)
    assert slot["questionText"] == "Do you want me to merge the reports?"


def test_failed_turn_never_writes_pending_slot(seeded_session):
    # Even a question-shaped failure text must not arm the wait: the turn did
    # not settle into a completed reply.
    _persist_turn(
        seeded_session,
        "turn-fail-1",
        {"status": "failed", "summary": "上游模型调用失败，要重试吗？", "raw_output": "上游模型调用失败，要重试吗？"},
    )
    assert _stored_slot(seeded_session) is None


def test_aborted_and_paused_turns_never_write_pending_slot(seeded_session):
    # Challenge-deadline cancellation (adapter-owned abort): settles cancelled,
    # never a completed reply — no slot even with a question-shaped text.
    _persist_turn(
        seeded_session,
        "turn-stop-1",
        _completed_result(
            "已按请求停止本轮工作，要继续吗？",
            stop_requested=True,
            stop_reason="challenge_logical_task_deadline_exhausted",
        ),
    )
    assert _stored_slot(seeded_session) is None

    _persist_turn(
        seeded_session,
        "turn-pause-1",
        _completed_result("配额到限暂停，恢复后要继续吗？", status="needs_continue"),
    )
    assert _stored_slot(seeded_session) is None


def test_pure_tool_turn_writes_no_slot(seeded_session):
    # completed + no visible reply + tool calls settles into needs_continue —
    # the tool-only turn is not the assistant asking its person.
    receipt = _persist_turn(
        seeded_session,
        "turn-tools-1",
        _completed_result("", tool_calls=[{"name": "run_shell", "arguments": {"command": "ls"}}]),
    )
    assert receipt is not None and receipt.get("finalStatus") == "needs_continue"
    assert _stored_slot(seeded_session) is None


def test_fresh_question_overwrites_previous_slot(seeded_session):
    _persist_turn(seeded_session, "turn-ask-1", _completed_result("结论如下。\n\n要写成简报吗？"))
    first = _stored_slot(seeded_session)
    _assert_pending(first)

    _persist_turn(seeded_session, "turn-ask-2", _completed_result("更新后的结论如下。\n\n要把简报发给全员吗？"))
    second = _stored_slot(seeded_session)
    _assert_pending(second)
    assert second["questionText"] == "要把简报发给全员吗？"
    assert second["id"] != first["id"]
    assert str(second["askedAt"]) >= str(first["askedAt"])


def test_written_slot_is_consumed_by_accepted_person_submit(seeded_session, monkeypatch):
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    _persist_turn(seeded_session, "turn-ask-1", _completed_result("已完成。\n\n要写成简报吗？"))
    _assert_pending(_stored_slot(seeded_session))

    session_service.submit_session_message_lightweight(
        seeded_session, "好，写成简报", client_submission_id="sub-consume-written",
    )
    consumed = _stored_slot(seeded_session)
    assert consumed is not None and str(consumed["consumedAt"] or "").strip()
    assert managed_continuation.session_waits_for_person(session_service, seeded_session) is False


# ---------------------------------------------------------------------------
# Writer helpers: pure text/id/stamp contract
# ---------------------------------------------------------------------------


def test_trailing_question_text_contract():
    assert pending_question.trailing_question_text("第一段。\n\n要继续吗？") == "要继续吗？"
    assert pending_question.trailing_question_text("结尾提问?") == "结尾提问?"
    assert pending_question.trailing_question_text("结尾提问？  \n") == "结尾提问？"
    assert pending_question.trailing_question_text("已完成。") == ""
    assert pending_question.trailing_question_text("要继续吗？\n\n（说明段。）") == ""
    # An empty/pure-tool reply has no question to freeze.
    assert pending_question.trailing_question_text("") == ""
    assert pending_question.trailing_question_text("  \n  ") == ""
    assert pending_question.trailing_question_text(None) == ""


def test_pending_question_id_for_turn_is_stable_and_scoped():
    first = pending_question.pending_question_id_for_turn("session-a", "turn-1")
    assert first == pending_question.pending_question_id_for_turn("session-a", "turn-1")
    assert first != pending_question.pending_question_id_for_turn("session-b", "turn-1")
    assert first != pending_question.pending_question_id_for_turn("session-a", "turn-2")
    assert first.startswith("pq-")
    # Turnless settlements never share one identity.
    assert (
        pending_question.pending_question_id_for_turn("session-a", "")
        != pending_question.pending_question_id_for_turn("session-a", "")
    )


def test_stamp_caps_question_text_and_never_raises():
    conversation: dict[str, Any] = {}
    long_question = "长" * 260 + "？"
    slot = pending_question.stamp_turn_pending_question(
        conversation,
        session_id="session-a",
        turn_id="turn-1",
        visible_text=f"分析完成。\n\n{long_question}",
    )
    assert slot is not None
    assert len(slot["questionText"]) == 200
    # Tail truncation keeps the actual question ending.
    assert slot["questionText"].endswith("？")
    assert conversation["pendingQuestion"]["id"] == slot["id"]

    # Non-question text and hostile inputs are no-ops, never exceptions.
    assert pending_question.stamp_turn_pending_question(
        {}, session_id="s", turn_id="t", visible_text="已完成。"
    ) is None
    assert pending_question.stamp_turn_pending_question(
        None, session_id="s", turn_id="t", visible_text="要继续吗？"
    ) is None
    assert pending_question.stamp_turn_pending_question(
        {}, session_id="s", turn_id="t", visible_text=None
    ) is None


# ---------------------------------------------------------------------------
# Detail projection: the slot surfaces as the public four-field shape
# ---------------------------------------------------------------------------


def _raw_conversation(session_id: str) -> dict[str, Any]:
    return session_service.load_session_chat_state(
        session_service.PROJECT_ROOT, session_id
    ) or {}


def test_written_slot_projects_public_four_field_shape(seeded_session):
    _persist_turn(
        seeded_session,
        "turn-ask-projection",
        _completed_result("已完成。\n\n要把简报发给全员吗？"),
    )
    projected = pending_question.detail_pending_question(_raw_conversation(seeded_session))
    assert projected is not None
    # Exactly the public contract; consumption internals never cross it.
    assert set(projected) == {"id", "questionText", "askedAt", "turnId"}
    assert projected["questionText"] == "要把简报发给全员吗？"
    assert str(projected["id"]).startswith("pq-")
    assert str(projected["askedAt"]).strip()
    # The writer carries the settling turn's id so the question can be tied
    # back to the reply that asked it.
    assert projected["turnId"] == "turn-ask-projection"


def test_detail_keeps_null_pending_question_after_consumption(seeded_session):
    _persist_turn(
        seeded_session,
        "turn-ask-consumed",
        _completed_result("已完成。\n\n要继续吗？"),
    )
    assert pending_question.consume_session_pending_question(seeded_session) is not None
    detail = session_service.get_session_detail(seeded_session)
    # The key stays in the detail contract; the consumed slot never shows.
    assert "pendingQuestion" in detail
    assert detail["pendingQuestion"] is None


def test_detail_carries_null_pending_question_without_slot(seeded_session):
    assert pending_question.session_pending_question(seeded_session) is None
    detail = session_service.get_session_detail(seeded_session)
    assert "pendingQuestion" in detail
    assert detail["pendingQuestion"] is None
    assert pending_question.detail_pending_question(_raw_conversation(seeded_session)) is None


def test_lightweight_detail_poll_still_carries_pending_question(seeded_session):
    # The floating widget and SSE light polls run include_secondary=False;
    # the key must ride along on that path too.
    _persist_turn(
        seeded_session,
        "turn-ask-light",
        _completed_result("已完成。\n\n要写入文档吗？"),
    )
    detail = session_service.get_session_detail(seeded_session, include_secondary=False)
    projected = detail.get("pendingQuestion")
    assert isinstance(projected, dict)
    assert set(projected) == {"id", "questionText", "askedAt", "turnId"}
    assert projected["turnId"] == "turn-ask-light"


def test_rail_off_detail_projection_returns_null(seeded_session, monkeypatch):
    _persist_turn(
        seeded_session,
        "turn-ask-rail-off",
        _completed_result("已完成。\n\n要继续吗？"),
    )
    monkeypatch.setenv(managed_continuation.WAITS_FOR_PERSON_RAIL_ENV, "0")
    assert pending_question.detail_pending_question(_raw_conversation(seeded_session)) is None
    detail = session_service.get_session_detail(seeded_session)
    assert detail.get("pendingQuestion") is None


def test_legacy_slot_without_turn_id_projects_empty_turn_id(seeded_session):
    # set_session_pending_question writes the legacy four-key shape (no
    # turnId): the optional read back-fills "" instead of dropping the field.
    pending_question.set_session_pending_question(
        seeded_session, question_text="旧槽位也要继续吗？"
    )
    assert "turnId" not in _stored_slot(seeded_session)
    projected = pending_question.detail_pending_question(_raw_conversation(seeded_session))
    assert projected is not None
    assert set(projected) == {"id", "questionText", "askedAt", "turnId"}
    assert projected["turnId"] == ""
