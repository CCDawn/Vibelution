"""Stale "starting" queued-turn recovery (crash between claim and settle).

A queued turn claimed by ``_claim_next_queued_turn`` is parked in "starting"
until its turn settles. If the process dies in between, no drain ever picks
the row again because selection only takes "queued" rows. These tests lock
the recovery path: stale "starting" rows are reset to "queued" before
selection, fresh ones are never touched, and the reset is a no-op without
side effects when nothing is stale.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state, save_chat_state
from core.web.services import session_service
from core.web.services.session import queued_turns

SESSION_ID = "session-a"


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


@pytest.fixture
def published_sessions(tmp_path, monkeypatch) -> list[str]:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: False)
    published: list[str] = []
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda session_id, **_kwargs: published.append(str(session_id)),
    )
    return published


def _timestamp(age: timedelta | None) -> str:
    moment = datetime.now(timezone.utc) if age is None else datetime.now(timezone.utc) - age
    return moment.isoformat(timespec="seconds")


def _turn_row(turn_id: str, *, status: str = "queued", age: timedelta | None = None) -> dict[str, Any]:
    timestamp = _timestamp(age)
    return {
        "id": turn_id,
        "clientSubmissionId": f"sub-{turn_id}",
        "content": f"content-{turn_id}",
        "attachments": [],
        "references": [],
        "mentalModelEnabled": False,
        "runtimeStatusEnabled": False,
        "turnMode": "",
        "writeIntent": False,
        "status": status,
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }


def _seed_conversation(tmp_path, rows: list[dict[str, Any]]) -> None:
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": SESSION_ID,
            "conversations": [
                {
                    "conversation_id": SESSION_ID,
                    "title": "Queue recovery",
                    "queued_turns": rows,
                }
            ],
        },
    )


def _persisted_rows(tmp_path) -> list[dict[str, Any]]:
    conversation = load_session_chat_state(tmp_path, SESSION_ID)
    return queued_turns.session_queued_turn_rows(conversation)


def test_reset_stale_starting_rows_resets_only_stale_rows(published_sessions):
    stale_age = timedelta(seconds=queued_turns.STARTING_CLAIM_STALE_SECONDS + 60)
    rows = [
        _turn_row("turn-stale", status="starting", age=stale_age),
        _turn_row("turn-fresh", status="starting", age=timedelta(minutes=1)),
        _turn_row("turn-queued", status="queued"),
    ]
    stale_timestamp = rows[0]["updatedAt"]
    fresh_timestamp = rows[1]["updatedAt"]

    changed = queued_turns._reset_stale_starting_rows(session_service, rows)

    assert changed is True
    assert [row["status"] for row in rows] == ["queued", "starting", "queued"]
    # The reset refreshes updatedAt so the next pass sees a fresh row.
    assert rows[0]["updatedAt"] != stale_timestamp
    # The fresh "starting" row keeps its original timestamp.
    assert rows[1]["updatedAt"] == fresh_timestamp


def test_stale_starting_row_is_reset_and_claimed_before_selection(tmp_path, published_sessions):
    _seed_conversation(
        tmp_path,
        [_turn_row("turn-stale", status="starting", age=timedelta(minutes=11))],
    )

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    # Selection only takes "queued" rows, so a claim proves the stale row was
    # reset to "queued" first; it is then re-claimed like any other turn.
    assert claimed is not None
    assert claimed["id"] == "turn-stale"
    rows = _persisted_rows(tmp_path)
    assert [(row["id"], row["status"]) for row in rows] == [("turn-stale", "starting")]
    assert published_sessions == [SESSION_ID]


def test_unparseable_starting_timestamp_is_treated_as_stale(tmp_path, published_sessions):
    row = _turn_row("turn-stale", status="starting")
    row["updatedAt"] = "not-a-timestamp"
    _seed_conversation(tmp_path, [row])

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is not None
    assert claimed["id"] == "turn-stale"


def test_fresh_starting_row_is_untouched_and_blocks_claim(tmp_path, published_sessions):
    _seed_conversation(
        tmp_path,
        [_turn_row("turn-live", status="starting", age=timedelta(minutes=1))],
    )
    seeded_timestamp = _persisted_rows(tmp_path)[0]["updatedAt"]

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is None
    rows = _persisted_rows(tmp_path)
    assert [(row["id"], row["status"]) for row in rows] == [("turn-live", "starting")]
    # Untouched: no reset write refreshed the row.
    assert rows[0]["updatedAt"] == seeded_timestamp
    assert published_sessions == []


def test_fresh_starting_row_does_not_block_next_queued_turn(tmp_path, published_sessions):
    _seed_conversation(
        tmp_path,
        [
            _turn_row("turn-live", status="starting", age=timedelta(minutes=1)),
            _turn_row("turn-next", status="queued"),
        ],
    )

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is not None
    assert claimed["id"] == "turn-next"
    rows = _persisted_rows(tmp_path)
    assert [(row["id"], row["status"]) for row in rows] == [
        ("turn-live", "starting"),
        ("turn-next", "starting"),
    ]
    # One publish covers the claim; the untouched fresh row adds no noise.
    assert published_sessions == [SESSION_ID]


def test_reset_is_noop_without_starting_rows(published_sessions):
    rows = [
        _turn_row("turn-queued", status="queued"),
        _turn_row("turn-blocked", status="blocked", age=timedelta(hours=1)),
    ]
    snapshot = [dict(row) for row in rows]

    changed = queued_turns._reset_stale_starting_rows(session_service, rows)

    assert changed is False
    assert rows == snapshot
    assert published_sessions == []


def test_claim_without_starting_rows_keeps_single_claim_publish(tmp_path, published_sessions):
    _seed_conversation(tmp_path, [_turn_row("turn-1", status="queued")])

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is not None
    assert claimed["id"] == "turn-1"
    assert published_sessions == [SESSION_ID]


def test_claim_skips_paused_rows(tmp_path, published_sessions):
    # A paused head row holds its place but never claims; drain takes the next
    # "queued" row behind it.
    _seed_conversation(
        tmp_path,
        [
            _turn_row("turn-paused", status="paused"),
            _turn_row("turn-next", status="queued"),
        ],
    )

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is not None
    assert claimed["id"] == "turn-next"
    rows = _persisted_rows(tmp_path)
    assert [(row["id"], row["status"]) for row in rows] == [
        ("turn-paused", "paused"),
        ("turn-next", "starting"),
    ]
    assert published_sessions == [SESSION_ID]


def test_all_paused_queue_claims_nothing(tmp_path, published_sessions):
    _seed_conversation(
        tmp_path,
        [
            _turn_row("turn-a", status="paused"),
            _turn_row("turn-b", status="paused"),
        ],
    )

    claimed = queued_turns._claim_next_queued_turn(SESSION_ID)

    assert claimed is None
    rows = _persisted_rows(tmp_path)
    assert [(row["id"], row["status"]) for row in rows] == [
        ("turn-a", "paused"),
        ("turn-b", "paused"),
    ]
    # Nothing changed, so there is nothing to publish.
    assert published_sessions == []


@pytest.fixture
def retry_clock(monkeypatch):
    class Clock(datetime):
        moment = datetime.now(timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.moment if tz is not None else cls.moment.replace(tzinfo=None)

    timers = []

    class Timer:
        def __init__(self, delay, callback, args=()):
            self.delay = delay
            self.callback = callback
            self.args = args
            self.daemon = False
            self.started = False
            self.cancelled = False
            timers.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

        def fire(self):
            if not self.cancelled:
                self.callback(*self.args)

    monkeypatch.setattr(queued_turns, "datetime", Clock)
    monkeypatch.setattr(queued_turns.threading, "Timer", Timer)
    monkeypatch.setattr(queued_turns, "_PENDING_STARTING_RETRIES", {})
    return Clock, timers


def test_fresh_starting_retry_waits_then_claims_once(tmp_path, published_sessions, retry_clock, monkeypatch):
    clock, timers = retry_clock
    row = _turn_row("orphan", status="starting", age=timedelta(minutes=1))
    _seed_conversation(tmp_path, [row])
    claimed = []
    monkeypatch.setattr(
        session_service, "_schedule_session_queued_turn_drain",
        lambda session_id: claimed.append(queued_turns._claim_next_queued_turn(session_id)),
    )
    for _ in range(3):
        queued_turns.schedule_session_queued_turn_stale_retry(SESSION_ID, updated_at=row["updatedAt"])
    assert len(timers) == 1
    assert timers[0].started and timers[0].daemon
    assert 0 < timers[0].delay <= queued_turns.STARTING_CLAIM_STALE_SECONDS + 1
    assert queued_turns._claim_next_queued_turn(SESSION_ID) is None
    assert _persisted_rows(tmp_path)[0]["updatedAt"] == row["updatedAt"]

    clock.moment += timedelta(seconds=queued_turns.STARTING_CLAIM_STALE_SECONDS + 2)
    timers[0].fire()
    timers[0].fire()
    assert len(claimed) == 1
    assert claimed[0]["id"] == "orphan"
    assert queued_turns._PENDING_STARTING_RETRIES == {}


def test_retry_does_not_reclaim_a_live_session(tmp_path, published_sessions, retry_clock, monkeypatch):
    clock, timers = retry_clock
    row = _turn_row("live", status="starting", age=timedelta(minutes=1))
    _seed_conversation(tmp_path, [row])
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: True)
    claims = []
    monkeypatch.setattr(
        session_service, "_schedule_session_queued_turn_drain",
        lambda session_id: claims.append(queued_turns._claim_next_queued_turn(session_id)),
    )
    queued_turns.schedule_session_queued_turn_stale_retry(SESSION_ID, updated_at=row["updatedAt"])
    clock.moment += timedelta(seconds=queued_turns.STARTING_CLAIM_STALE_SECONDS + 2)
    timers[0].fire()
    assert claims == [None]
    assert _persisted_rows(tmp_path)[0]["updatedAt"] == row["updatedAt"]
    assert published_sessions == []
    assert queued_turns._PENDING_STARTING_RETRIES == {}


def test_retry_retires_settled_claim_without_a_drain(tmp_path, published_sessions, retry_clock, monkeypatch):
    clock, timers = retry_clock
    row = _turn_row("settled", status="starting", age=timedelta(minutes=1))
    _seed_conversation(tmp_path, [row])
    drains = []
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", drains.append)
    queued_turns.schedule_session_queued_turn_stale_retry(SESSION_ID, updated_at=row["updatedAt"])
    _seed_conversation(tmp_path, [])
    clock.moment += timedelta(seconds=queued_turns.STARTING_CLAIM_STALE_SECONDS + 2)
    timers[0].fire()
    assert drains == []
    assert len(timers) == 1
    assert queued_turns._PENDING_STARTING_RETRIES == {}


def test_retry_rechecks_a_replaced_claim_at_its_new_expiry(tmp_path, published_sessions, retry_clock, monkeypatch):
    clock, timers = retry_clock
    old = _turn_row("old", status="starting", age=timedelta(minutes=1))
    _seed_conversation(tmp_path, [old])
    drains = []
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", drains.append)
    queued_turns.schedule_session_queued_turn_stale_retry(SESSION_ID, updated_at=old["updatedAt"])
    clock.moment += timedelta(seconds=queued_turns.STARTING_CLAIM_STALE_SECONDS + 2)
    new = _turn_row("new", status="starting")
    new["updatedAt"] = clock.moment.isoformat()
    _seed_conversation(tmp_path, [new])
    timers[0].fire()
    assert drains == []
    assert len(timers) == 2
    assert queued_turns._PENDING_STARTING_RETRIES[SESSION_ID][0] == new["updatedAt"]
    assert _persisted_rows(tmp_path)[0]["updatedAt"] == new["updatedAt"]


def test_empty_claim_drain_still_schedules_continuation(tmp_path, published_sessions, monkeypatch):
    """R1：空领取的 drain 也必须调度自续。

    并发入队的唤醒可能刚被单飞窗口（空领取 → finally 丢弃标记）静默丢弃，
    空闲会话上的机发行没有 settle 兜底，漏醒即停滞到下次用户动作或重启。
    自续自身带运行过滤与滚动窗上限，无条件调度是安全的。
    """

    _seed_conversation(
        tmp_path,
        [_turn_row("turn-live", status="starting", age=timedelta(minutes=1))],
    )
    scheduled: list[str] = []
    monkeypatch.setattr(
        queued_turns,
        "_schedule_session_queued_turn_drain_continuation",
        lambda session_id: scheduled.append(str(session_id)),
    )

    drained = queued_turns.drain_session_queued_turns(SESSION_ID)

    # 新鲜 starting 行阻塞领取 → 空领取返回 False，但自续仍须被调度
    assert drained is False
    assert scheduled == [SESSION_ID]


def _seed_hold_conversation(tmp_path, rows: list[dict[str, Any]]) -> None:
    """Seed rows plus a user-stop queue hold marker on the same conversation."""

    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": SESSION_ID,
            "conversations": [
                {
                    "conversation_id": SESSION_ID,
                    "title": "Held queue",
                    "queued_turns": rows,
                    "queued_turn_hold": {
                        "reason": "user_stop",
                        "turnId": "turn-running",
                        "heldAt": _timestamp(None),
                    },
                }
            ],
        },
    )


def _persisted_hold(tmp_path) -> dict[str, Any] | None:
    conversation = load_session_chat_state(tmp_path, SESSION_ID)
    hold = conversation.get(queued_turns.QUEUED_TURN_HOLD_KEY)
    return hold if isinstance(hold, dict) and hold else None


def test_queue_hold_blocks_drain_until_user_action(tmp_path, published_sessions, monkeypatch):
    """用户显式停止后，排阘认不再自动续跑：drain 直接返回且行保持原状。"""

    continuations: list[str] = []
    monkeypatch.setattr(
        queued_turns,
        "_schedule_session_queued_turn_drain_continuation",
        lambda session_id: continuations.append(str(session_id)),
    )
    _seed_hold_conversation(tmp_path, [_turn_row("turn-1")])

    drained = queued_turns.drain_session_queued_turns(SESSION_ID)

    assert drained is False
    assert [(row["id"], row["status"]) for row in _persisted_rows(tmp_path)] == [("turn-1", "queued")]
    assert _persisted_hold(tmp_path) is not None
    assert published_sessions == []
    # 冻结的队列也不该再排自续定时器：那是给「空闲但可能还有行」的场景用的。
    assert continuations == []


def test_user_enqueue_clears_hold(tmp_path, published_sessions, monkeypatch):
    """用户再发新消息是最明确的续跑意图：清除 hold 并调度 drain。"""

    _seed_hold_conversation(tmp_path, [_turn_row("turn-1")])
    scheduled: list[str] = []
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", scheduled.append)
    monkeypatch.setattr(queued_turns, "_record_queued_turn_steer_admission", lambda *args, **kwargs: None)
    monkeypatch.setattr(queued_turns, "capture_model_parameters", lambda *args, **kwargs: {})

    row = queued_turns.enqueue_session_queued_turn(
        SESSION_ID,
        content="resume please",
        attachments=[],
        references=[],
        mental_model_enabled=False,
        runtime_status_enabled=False,
        turn_mode="",
        write_intent=False,
        client_submission_id="sub-resume",
    )

    assert row["content"] == "resume please"
    assert _persisted_hold(tmp_path) is None
    assert [item["id"] for item in _persisted_rows(tmp_path)] == ["turn-1", row["id"]]
    assert scheduled == [SESSION_ID]


def test_queue_edit_clears_hold(tmp_path, published_sessions, monkeypatch):
    """编辑排队行同样是显式用户动作：清除 hold。"""

    _seed_hold_conversation(tmp_path, [_turn_row("turn-1")])
    scheduled: list[str] = []
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", scheduled.append)

    rows = queued_turns.update_session_queued_turn(SESSION_ID, "turn-1", content="edited")

    assert [item["content"] for item in rows] == ["edited"]
    assert _persisted_hold(tmp_path) is None


def test_send_now_clears_hold(tmp_path, published_sessions, monkeypatch):
    """send-now 明确要求停止后立即跑某行：清 hold + 请求停止。"""

    _seed_hold_conversation(tmp_path, [_turn_row("turn-1")])
    stops: list[tuple[str, dict]] = []
    scheduled: list[str] = []
    monkeypatch.setattr(
        session_service,
        "request_stop_session_turn",
        lambda session_id, **kwargs: stops.append((session_id, kwargs)) or {"id": session_id},
    )
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", scheduled.append)

    outcome = queued_turns.send_now_session_queued_turn(SESSION_ID, "turn-1", expected_turn_id="turn-running")

    assert outcome["stopRequested"] is True
    persisted = _persisted_rows(tmp_path)
    assert len(persisted) == 1 and persisted[0].get("sendNow") is True
    assert _persisted_hold(tmp_path) is None
    assert stops == [(SESSION_ID, {"expected_turn_id": "turn-running", "fast_ack": True})]
    assert scheduled == [SESSION_ID]


def test_runtime_notice_keeps_hold(tmp_path, published_sessions, monkeypatch):
    """机器回传只入队不清 hold：自动通知不能悄悄解冻用户停下的队列。"""

    _seed_hold_conversation(tmp_path, [])
    scheduled: list[str] = []
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", scheduled.append)

    queued_turns.enqueue_session_runtime_notice(
        SESSION_ID,
        kind=queued_turns.KIND_TASK_NOTIFICATION,
        content="child task finished",
        source_id="notice-1",
    )

    rows = _persisted_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["kind"] == queued_turns.KIND_TASK_NOTIFICATION
    assert _persisted_hold(tmp_path) is not None
    assert queued_turns.session_queue_hold_active(SESSION_ID) is True
    assert queued_turns.drain_session_queued_turns(SESSION_ID) is False
    assert scheduled == [SESSION_ID]


def test_stop_route_freezes_queue_with_hold_marker(tmp_path, published_sessions, monkeypatch):
    """裸停止按钮（stop 路由）在停止信号之后落排队冻结标记。"""

    from core.web.routes import sessions as sessions_routes

    _seed_conversation(tmp_path, [_turn_row("turn-1")])
    acks: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        sessions_routes,
        "request_stop_session_turn",
        lambda session_id, **kwargs: acks.append((session_id, kwargs))
        or {"id": session_id, "activeTurnId": "turn-running", "stopRequested": True},
    )

    payload = sessions_routes.session_stop_turn(
        SESSION_ID, sessions_routes.SessionStopPayload(turnId="turn-run")
    )

    assert payload["stopRequested"] is True
    assert acks == [(SESSION_ID, {"expected_turn_id": "turn-run", "fast_ack": True})]
    hold = _persisted_hold(tmp_path)
    assert isinstance(hold, dict) and hold["reason"] == "user_stop"
    assert hold["turnId"] == "turn-run"
