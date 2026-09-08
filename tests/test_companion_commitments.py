from datetime import UTC, datetime, timedelta

import pytest

from core.agent_plugins.virtual_human_life.calendar import (
    effective_calendar_events,
    project_calendar_for_date,
)
from core.agent_plugins.virtual_human_life.commitments import (
    apply_commitment_action,
    project_commitments,
)

NOW = datetime(2026, 9, 8, 8, 0, tzinfo=UTC)


def _apply(
    ledger: list[dict],
    *,
    action: str,
    commitment_id: str = "commitment-1",
    operation_id: str = "operation-1",
    session_id: str = "session-1",
    source_turn_id: str = "turn-1",
    now: datetime = NOW,
    title: str = "一起吃晚饭",
    start_at: str = "2026-09-08T19:00:00+08:00",
    end_at: str = "2026-09-08T20:00:00+08:00",
    timezone_name: str = "Asia/Shanghai",
    reason: str = "",
) -> tuple[list[dict], dict]:
    return apply_commitment_action(
        ledger,
        action=action,
        commitment_id=commitment_id,
        operation_id=operation_id,
        agent_id="agent-1",
        session_id=session_id,
        source_turn_id=source_turn_id,
        now=now,
        title=title,
        start_at=start_at,
        end_at=end_at,
        timezone_name=timezone_name,
        reason=reason,
    )


def test_propose_is_pending_and_never_a_formal_calendar_event() -> None:
    ledger, result = _apply([], action="propose")

    assert result["accepted"] is True
    assert result["commitmentState"] == "pending"
    assert ledger[-1]["operation"] == "commitment_proposed"
    assert ledger[-1]["expiresAt"] == ledger[-1]["startAt"]
    assert effective_calendar_events(ledger) == []
    assert project_calendar_for_date(ledger, "2026-09-08")["occurrences"] == []
    projection = project_commitments(ledger, session_id="session-1", now=NOW)
    assert [item["commitmentId"] for item in projection["pending"]] == ["commitment-1"]
    assert projection["confirmed"] == []


def test_confirm_requires_a_later_turn_and_promotes_only_candidate() -> None:
    ledger, _ = _apply([], action="propose")

    with pytest.raises(ValueError):
        _apply(
            ledger,
            action="confirm",
            operation_id="operation-confirm-same-turn",
            source_turn_id="turn-1",
        )

    ledger, result = _apply(
        ledger,
        action="confirm",
        operation_id="operation-confirm-1",
        source_turn_id="turn-2",
    )
    assert result["commitmentState"] == "confirmed"
    assert ledger[-1]["operation"] == "upsert"
    assert ledger[-1]["kind"] == "commitment"
    assert ledger[-1]["sourceSessionId"] == "session-1"
    assert ledger[-1]["sourceTurnId"] == "turn-2"
    assert ledger[-1]["operationId"] == "operation-confirm-1"
    assert len(effective_calendar_events(ledger)) == 1
    assert effective_calendar_events(ledger)[0]["kind"] == "commitment"
    projection = project_commitments(ledger, session_id="session-1", now=NOW)
    assert [item["commitmentId"] for item in projection["confirmed"]] == [
        "commitment-1"
    ]
    assert projection["pending"] == []

    replay, replay_result = _apply(
        ledger,
        action="confirm",
        operation_id="operation-confirm-1",
        source_turn_id="turn-2",
    )
    assert replay == ledger
    assert replay_result["idempotent"] is True
    with pytest.raises(ValueError):
        _apply(
            ledger,
            action="confirm",
            operation_id="operation-confirm-1",
            source_turn_id="turn-2",
            title="不同约定",
        )


def test_changed_candidate_can_be_rejected_without_cancelling_confirmed_event() -> None:
    ledger, _ = _apply([], action="propose")
    ledger, _ = _apply(
        ledger,
        action="confirm",
        operation_id="operation-confirm-1",
        source_turn_id="turn-2",
    )
    changed_start = "2026-09-09T19:00:00+08:00"
    changed_end = "2026-09-09T20:00:00+08:00"
    ledger, _ = _apply(
        ledger,
        action="propose",
        operation_id="operation-propose-change",
        source_turn_id="turn-3",
        title="改到明晚吃饭",
        start_at=changed_start,
        end_at=changed_end,
    )
    ledger, result = _apply(
        ledger,
        action="reject",
        operation_id="operation-reject-change",
        source_turn_id="turn-4",
        title="改到明晚吃饭",
        start_at=changed_start,
        end_at=changed_end,
    )
    assert result["commitmentState"] == "rejected"
    replay, replay_result = _apply(
        ledger,
        action="reject",
        operation_id="operation-reject-change",
        source_turn_id="turn-4",
        title="改到明晚吃饭",
        start_at=changed_start,
        end_at=changed_end,
    )
    assert replay == ledger
    assert replay_result["idempotent"] is True
    with pytest.raises(ValueError):
        _apply(
            ledger,
            action="reject",
            operation_id="operation-reject-change",
            source_turn_id="turn-4",
            title="改到明晚聚餐",
            start_at=changed_start,
            end_at=changed_end,
        )
    events = effective_calendar_events(ledger)
    assert len(events) == 1
    assert events[0]["title"] == "一起吃晚饭"
    projection = project_commitments(ledger, session_id="session-1", now=NOW)
    assert projection["confirmed"][0]["title"] == "一起吃晚饭"
    assert any(
        item["commitmentState"] == "rejected" for item in projection["recentTerminal"]
    )

    ledger, _ = _apply(
        ledger,
        action="propose",
        operation_id="operation-propose-change-2",
        source_turn_id="turn-5",
        title="改到明晚吃饭",
        start_at=changed_start,
        end_at=changed_end,
    )
    ledger, _ = _apply(
        ledger,
        action="confirm",
        operation_id="operation-confirm-change",
        source_turn_id="turn-6",
        title="改到明晚吃饭",
        start_at=changed_start,
        end_at=changed_end,
    )
    events = effective_calendar_events(ledger)
    assert len(events) == 1
    assert events[0]["title"] == "改到明晚吃饭"
    assert events[0]["startAt"].startswith("2026-09-09T11:00:00")


def test_cancel_and_complete_use_calendar_cancel_without_faking_life_event() -> None:
    ledger, _ = _apply([], action="propose")
    ledger, _ = _apply(
        ledger,
        action="confirm",
        operation_id="operation-confirm-1",
        source_turn_id="turn-2",
    )
    ledger, result = _apply(
        ledger,
        action="cancel",
        operation_id="operation-cancel-1",
        source_turn_id="turn-3",
        reason="临时有事",
        title="",
        start_at="",
        end_at="",
    )
    assert result["commitmentState"] == "cancelled"
    assert ledger[-1]["operation"] == "cancel"
    assert effective_calendar_events(ledger) == []
    assert not any("LifeEvent" in row or "lifeEvent" in row for row in ledger)
    replay, replay_result = _apply(
        ledger,
        action="cancel",
        operation_id="operation-cancel-1",
        source_turn_id="turn-3",
        reason="临时有事",
        title="",
        start_at="",
        end_at="",
    )
    assert replay == ledger
    assert replay_result["idempotent"] is True
    with pytest.raises(ValueError):
        _apply(
            ledger,
            action="cancel",
            operation_id="operation-cancel-1",
            source_turn_id="turn-3",
            reason="换一个理由",
            title="",
            start_at="",
            end_at="",
        )
    projection = project_commitments(ledger, session_id="session-1", now=NOW)
    assert projection["confirmed"] == []
    assert any(
        item["commitmentState"] == "cancelled" for item in projection["recentTerminal"]
    )

    ledger, _ = _apply(
        ledger,
        action="propose",
        operation_id="operation-propose-2",
        source_turn_id="turn-4",
        start_at="2026-09-09T19:00:00+08:00",
        end_at="2026-09-09T20:00:00+08:00",
    )
    ledger, _ = _apply(
        ledger,
        action="confirm",
        operation_id="operation-confirm-2",
        source_turn_id="turn-5",
        start_at="2026-09-09T19:00:00+08:00",
        end_at="2026-09-09T20:00:00+08:00",
    )
    ledger, result = _apply(
        ledger,
        action="complete",
        operation_id="operation-complete-1",
        source_turn_id="turn-6",
        title="",
        start_at="",
        end_at="",
    )
    assert result["commitmentState"] == "completed"
    assert ledger[-1]["operation"] == "cancel"
    assert effective_calendar_events(ledger) == []
    assert not any("outcome" in row for row in ledger)
    replay, replay_result = _apply(
        ledger,
        action="complete",
        operation_id="operation-complete-1",
        source_turn_id="turn-6",
        title="",
        start_at="",
        end_at="",
    )
    assert replay == ledger
    assert replay_result["idempotent"] is True
    with pytest.raises(ValueError):
        _apply(
            ledger,
            action="complete",
            operation_id="operation-complete-1",
            source_turn_id="turn-6",
            reason="换一个理由",
            title="",
            start_at="",
            end_at="",
        )


def test_projection_awaits_outcome_after_window_and_ignores_unmanaged_calendar_rows() -> (
    None
):
    ordinary = {
        "operation": "upsert",
        "eventId": "ordinary-1",
        "agentId": "agent-1",
        "title": "普通日历项",
        "startAt": "2026-09-07T10:00:00+00:00",
        "endAt": "2026-09-07T11:00:00+00:00",
        "timezone": "Asia/Shanghai",
    }
    ledger, _ = _apply(
        [ordinary],
        action="propose",
        now=NOW - timedelta(days=1),
        start_at="2026-09-07T19:00:00+08:00",
        end_at="2026-09-07T20:00:00+08:00",
    )
    ledger, _ = _apply(
        ledger,
        action="confirm",
        operation_id="operation-confirm-1",
        source_turn_id="turn-2",
        now=NOW - timedelta(days=1),
        start_at="2026-09-07T19:00:00+08:00",
        end_at="2026-09-07T20:00:00+08:00",
    )
    projection = project_commitments(ledger, session_id="session-1", now=NOW)
    assert projection["confirmed"] == []
    assert [item["commitmentId"] for item in projection["awaitingOutcome"]] == [
        "commitment-1"
    ]
    assert any(
        item["eventId"] == "ordinary-1" for item in effective_calendar_events(ledger)
    )


def test_actions_are_idempotent_and_reject_identity_or_state_violations() -> None:
    ledger, _ = _apply([], action="propose")
    same, result = _apply([], action="propose")
    assert same == ledger
    assert result["accepted"] is True

    with pytest.raises(ValueError):
        _apply(
            ledger,
            action="propose",
            operation_id="operation-1",
            title="不同内容",
        )
    with pytest.raises(ValueError):
        _apply(
            ledger,
            action="confirm",
            operation_id="operation-cross-session",
            session_id="session-2",
            source_turn_id="turn-2",
        )
    with pytest.raises(ValueError):
        _apply(
            ledger,
            action="complete",
            operation_id="operation-complete-unconfirmed",
            source_turn_id="turn-2",
        )
    with pytest.raises(ValueError):
        _apply(
            ledger,
            action="confirm",
            operation_id="operation-confirm-expired",
            source_turn_id="turn-2",
            now=NOW + timedelta(days=1),
        )


def test_commitment_append_preserves_unrelated_calendar_ledger_rows() -> None:
    ordinary = [
        {
            "operation": "upsert",
            "eventId": f"ordinary-{index}",
            "agentId": "agent-1",
            "title": "长期日历项",
            "startAt": "2026-09-08T01:00:00+00:00",
            "endAt": "2026-09-08T02:00:00+00:00",
            "timezone": "Asia/Shanghai",
        }
        for index in range(2050)
    ]

    result, _ = _apply(ordinary, action="propose")

    assert len(result) == 2051
    assert result[0]["eventId"] == "ordinary-0"
    assert result[2049]["eventId"] == "ordinary-2049"
