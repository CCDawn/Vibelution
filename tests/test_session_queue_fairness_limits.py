"""Guards for session-queue fairness between startup recovery and user turns.

Regression context (2026-11 queueing incident): the scheduler caps one Agent at
``SESSION_AGENT_MAX_ACTIVE_TURNS`` concurrent sessions, while startup recovery
used to launch ``_SWEEP_MAX_WORKERS`` interrupted sessions at once. With both
numbers at 8, the 9th turn had to queue and the session the operator was
actually looking at ended up behind background recovery work.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from core.web.services.session.limits import (
    RECOVERY_SLOT_RESERVE,
    RECOVERY_TURN_SCHEDULER_PRIORITY,
    SESSION_AGENT_MAX_ACTIVE_TURNS,
    recovery_worker_limit,
)
from core.web.services.session_turn_scheduler import SessionTurnScheduler

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_recovery_pool_never_consumes_every_scheduler_slot() -> None:
    usable = SESSION_AGENT_MAX_ACTIVE_TURNS - RECOVERY_SLOT_RESERVE
    assert usable >= 1
    assert recovery_worker_limit(SESSION_AGENT_MAX_ACTIVE_TURNS) == usable
    assert recovery_worker_limit(SESSION_AGENT_MAX_ACTIVE_TURNS) < SESSION_AGENT_MAX_ACTIVE_TURNS


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (0, 1),
        (1, 1),
        (3, 3),
        (SESSION_AGENT_MAX_ACTIVE_TURNS - RECOVERY_SLOT_RESERVE, SESSION_AGENT_MAX_ACTIVE_TURNS - RECOVERY_SLOT_RESERVE),
        (SESSION_AGENT_MAX_ACTIVE_TURNS, SESSION_AGENT_MAX_ACTIVE_TURNS - RECOVERY_SLOT_RESERVE),
        (64, SESSION_AGENT_MAX_ACTIVE_TURNS - RECOVERY_SLOT_RESERVE),
    ],
)
def test_recovery_worker_limit_is_bounded(requested: int, expected: int) -> None:
    assert recovery_worker_limit(requested) == expected


def test_recovery_turn_priority_sits_between_user_and_proactive() -> None:
    # 用户 turn 默认 0，proactive 主动消息 100；恢复必须排在两者之间。
    assert 0 < RECOVERY_TURN_SCHEDULER_PRIORITY < 100


def test_user_turn_jumps_ahead_of_a_queued_recovery_turn() -> None:
    bucket: deque[dict] = deque()
    SessionTurnScheduler._enqueue_chat_context_locked(
        bucket, {"turn_id": "recovery", "_scheduler_priority": RECOVERY_TURN_SCHEDULER_PRIORITY}
    )
    SessionTurnScheduler._enqueue_chat_context_locked(
        bucket, {"turn_id": "user", "_scheduler_priority": 0}
    )
    assert [item["turn_id"] for item in bucket] == ["user", "recovery"]


def test_startup_recovery_uses_the_reserved_worker_limit() -> None:
    source = (
        _PROJECT_ROOT / "core" / "web" / "services" / "session" / "startup_recovery.py"
    ).read_text(encoding="utf-8")
    assert "recovery_worker_limit(" in source


def test_submit_marks_recovery_turns_with_low_queue_priority() -> None:
    source = (
        _PROJECT_ROOT / "core" / "web" / "services" / "session" / "submit.py"
    ).read_text(encoding="utf-8")
    assert 'context["_scheduler_priority"] = RECOVERY_TURN_SCHEDULER_PRIORITY' in source


def test_scheduler_limit_has_a_single_authority() -> None:
    source = (
        _PROJECT_ROOT / "core" / "web" / "services" / "session_service.py"
    ).read_text(encoding="utf-8")
    # 调度上限必须来自 limits，而不是在 session_service 里再写一个裸数字。
    assert "_SESSION_AGENT_MAX_ACTIVE_TURNS = SESSION_AGENT_MAX_ACTIVE_TURNS" in source
