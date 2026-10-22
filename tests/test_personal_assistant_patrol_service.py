"""PA 派遣心跳巡检：aged 判定 / 自动催办 / 回执消化唤醒 / 定时摘要卡 / 急停开关。

成本红线全部钉死成断言：催办每派遣 2 轮上限 + 30min 间隔 + idempotency_key
稳定；唤醒 15min 冷却 + 每小时 2 次上限、无回执不唤醒；摘要指纹无变化不推、
30min 最多轮转一次；总开关关=空转（不催不唤醒不推卡）。所有节流状态进程内、
重启（reset）清零。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.web.services import personal_assistant_patrol_service as patrol


NOW = 1_800_000_000.0


def _iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


def _dispatch(
    message_id: str,
    *,
    sent_age_seconds: float = 3600.0,
    receipts: list | None = None,
    summary: str = "调研量子纠错最新进展",
    target_agent_id: str = "agent-researcher",
    now: float = NOW,
) -> dict:
    return {
        "messageId": message_id,
        "threadId": "thread-1",
        "targetAgentId": target_agent_id,
        "targetAgentName": "研究员",
        "targetSessionId": "session-1",
        "summary": summary,
        "deliveryStatus": "pending",
        "sentAt": _iso(now - sent_age_seconds),
        "receipts": receipts if receipts is not None else [],
    }


def _receipt_row(
    message_id: str = "r-1",
    *,
    reply_to: str = "",
    kind: str = "",
    created_age_seconds: float = 60.0,
    now: float = NOW,
) -> dict:
    row = {
        "messageId": message_id,
        "kind": kind or "agent_inbox_reply",
        "status": "pending",
        "promptEligible": True,
        "sourceAgentId": "agent-researcher",
        "sourceAgentName": "研究员",
        "targetAgentId": "agent-pa",
        "summary": "已完成调研",
        "content": "调研结果如下……",
        "createdAt": _iso(now - created_age_seconds),
        "metadata": {"replyToMessageId": reply_to} if reply_to else {},
    }
    return row


@pytest.fixture(autouse=True)
def _clean_patrol_state(monkeypatch):
    patrol.reset_personal_assistant_patrol_for_tests()
    monkeypatch.delenv(patrol.PA_PATROL_ENABLED_ENV, raising=False)
    monkeypatch.delenv(patrol.PA_PATROL_WAKE_ENABLED_ENV, raising=False)
    yield
    patrol.reset_personal_assistant_patrol_for_tests()


class _Harness:
    """Patch the read/submit/wake seams and record every call."""

    def __init__(
        self,
        monkeypatch,
        *,
        dispatches: list[dict] | None = None,
        pending_inbox: list[dict] | None = None,
        pa_agent_id: str = "agent-pa",
    ) -> None:
        self.listing = {
            "assistantAgentId": pa_agent_id,
            "dispatches": dispatches or [],
            "unmatchedReceipts": [],
            "generatedAt": _iso(NOW),
        }
        self.pending_inbox = pending_inbox or []
        self.followup_calls: list[dict] = []
        self.wake_calls: list[dict] = []
        monkeypatch.setattr(patrol, "_load_dispatches", lambda: dict(self.listing))
        monkeypatch.setattr(
            patrol, "_read_pa_pending_messages", lambda _agent_id: list(self.pending_inbox)
        )
        monkeypatch.setattr(
            patrol,
            "_pa_sender",
            lambda: {
                "type": "agent",
                "id": pa_agent_id,
                "agentId": pa_agent_id,
                "displayName": "个人助理",
                "agentCode": "pa",
            },
        )

        def _fake_submit(**kwargs):
            self.followup_calls.append(kwargs)
            return {"accepted": True, "idempotencyKey": kwargs.get("idempotency_key")}

        monkeypatch.setattr(patrol, "_submit_followup_event", _fake_submit)

        def _fake_wake(message):
            self.wake_calls.append({"message": message})
            return {"wakeStatus": "started", "turnId": "turn-1"}

        monkeypatch.setattr(patrol, "_wake_pa", _fake_wake)


# ---------------------------------------------------------------------------
# aged 判定
# ---------------------------------------------------------------------------


def test_aged_dispatch_is_chased_but_fresh_one_is_not(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[
            _dispatch("m-aged", sent_age_seconds=patrol.FOLLOWUP_INITIAL_AGE_SECONDS + 60),
            _dispatch("m-fresh", sent_age_seconds=60.0),
        ],
    )
    result = patrol.patrol_once(now=NOW)
    assert result["agedMessageIds"] == ["m-aged"]
    assert [call["idempotency_key"] for call in harness.followup_calls] == ["pa-followup:m-aged:1"]


def test_aged_threshold_boundary_is_inclusive(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[
            _dispatch("m-exact", sent_age_seconds=patrol.FOLLOWUP_INITIAL_AGE_SECONDS),
        ],
    )
    result = patrol.patrol_once(now=NOW)
    assert result["agedMessageIds"] == ["m-exact"]
    assert len(harness.followup_calls) == 1


def test_dispatch_with_receipt_is_never_chased(monkeypatch):
    receipt = {
        "messageId": "r-1",
        "sourceAgentId": "agent-researcher",
        "summary": "完成",
        "status": "pending",
        "receivedAt": _iso(NOW - 60),
    }
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-done", sent_age_seconds=7200.0, receipts=[receipt])],
    )
    result = patrol.patrol_once(now=NOW)
    assert result["agedMessageIds"] == []
    assert harness.followup_calls == []


def test_dispatch_beyond_chase_window_is_not_chased(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[
            _dispatch("m-ancient", sent_age_seconds=patrol.FOLLOWUP_MAX_AGE_SECONDS + 3600.0),
        ],
    )
    result = patrol.patrol_once(now=NOW)
    assert result["agedMessageIds"] == []
    assert harness.followup_calls == []


def test_dispatch_without_parsable_sent_at_is_never_chased(monkeypatch):
    broken = _dispatch("m-broken", sent_age_seconds=7200.0)
    broken["sentAt"] = "not-a-timestamp"
    harness = _Harness(monkeypatch, dispatches=[broken])
    result = patrol.patrol_once(now=NOW)
    assert result["agedMessageIds"] == []
    assert harness.followup_calls == []


# ---------------------------------------------------------------------------
# 催办节流
# ---------------------------------------------------------------------------


def test_followup_idempotency_key_is_stable_per_round(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=3600.0, summary="原始任务摘要 A")],
    )
    patrol.patrol_once(now=NOW)
    patrol.patrol_once(now=NOW + 60)  # interval gate keeps this a no-op
    assert [call["idempotency_key"] for call in harness.followup_calls] == ["pa-followup:m-1:1"]
    first = harness.followup_calls[0]
    assert first["recipient_agent_ids"] == ["agent-researcher"]
    assert first["wake_target"] is True
    assert first["source"] == patrol.PATROL_SOURCE
    assert first["sender"]["agentId"] == "agent-pa"
    # 催办内容带原派遣摘要，目标知道在催什么。
    assert "原始任务摘要 A" in first["content"]
    assert "m-1" in first["content"]
    assert "第 1 次跟进" in first["content"]


def test_followup_caps_at_two_rounds_with_min_interval(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)],
    )
    step = patrol.FOLLOWUP_MIN_INTERVAL_SECONDS + 60.0
    patrol.patrol_once(now=NOW)                                # round 1
    patrol.patrol_once(now=NOW + 60.0)                         # inside interval → skipped
    patrol.patrol_once(now=NOW + step)                         # round 2
    patrol.patrol_once(now=NOW + 2 * step)                     # budget exhausted → skipped
    assert [call["idempotency_key"] for call in harness.followup_calls] == [
        "pa-followup:m-1:1",
        "pa-followup:m-1:2",
    ]


def test_followup_state_resets_on_restart(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)],
    )
    patrol.patrol_once(now=NOW)
    patrol.patrol_once(now=NOW + patrol.FOLLOWUP_MIN_INTERVAL_SECONDS + 60.0)
    assert len(harness.followup_calls) == 2
    # 进程重启：节流窗口清零，同一派遣从第 1 轮重新开始（key 稳定，由 kernel
    # 幂等账本兜底不双发）。
    patrol.reset_personal_assistant_patrol_for_tests()
    patrol.patrol_once(now=NOW + 2 * (patrol.FOLLOWUP_MIN_INTERVAL_SECONDS + 60.0))
    assert harness.followup_calls[-1]["idempotency_key"] == "pa-followup:m-1:1"


def test_followup_submit_failure_does_not_consume_the_round(monkeypatch):
    _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)],
    )
    attempts = {"n": 0}
    accepted_calls: list[dict] = []

    def _flaky_submit(**kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("kernel unavailable")
        accepted_calls.append(kwargs)
        return {"accepted": True}

    monkeypatch.setattr(patrol, "_submit_followup_event", _flaky_submit)
    patrol.patrol_once(now=NOW)
    assert accepted_calls == []
    patrol.patrol_once(now=NOW + 60.0)
    assert attempts["n"] == 2  # retried next pass, still round 1
    assert accepted_calls[-1]["idempotency_key"] == "pa-followup:m-1:1"


# ---------------------------------------------------------------------------
# 回执消化唤醒
# ---------------------------------------------------------------------------


def test_pending_receipt_wakes_pa_once_then_cooldown_blocks(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=120.0)],
        pending_inbox=[_receipt_row("r-1", reply_to="m-1")],
    )
    result = patrol.patrol_once(now=NOW)
    assert result["wake"]["attempted"] is True
    assert len(harness.wake_calls) == 1
    assert harness.wake_calls[0]["message"]["messageId"] == "r-1"
    # 冷却窗口内第二次巡检不再唤醒。
    result = patrol.patrol_once(now=NOW + 60.0)
    assert result["wake"] == {"attempted": False, "reason": "throttled", "receiptCount": 1}
    assert len(harness.wake_calls) == 1


def test_wake_cooldown_then_hourly_cap(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=120.0)],
        pending_inbox=[_receipt_row("r-1", reply_to="m-1")],
    )
    cooldown = patrol.WAKE_COOLDOWN_SECONDS
    patrol.patrol_once(now=NOW)                     # wake 1
    patrol.patrol_once(now=NOW + cooldown + 1.0)    # wake 2
    patrol.patrol_once(now=NOW + 2 * (cooldown + 1.0))  # hourly cap hit → throttled
    assert len(harness.wake_calls) == 2
    result = patrol.patrol_once(now=NOW + 2 * (cooldown + 1.0))
    assert result["wake"]["reason"] == "throttled"


def test_no_receipt_like_rows_means_no_wake(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)],
        pending_inbox=[
            # 非 reply kind 且 replyToMessageId 对不上 → 不是回执类。
            _receipt_row("r-other", reply_to="unrelated", kind="announcement"),
        ],
    )
    result = patrol.patrol_once(now=NOW)
    assert result["wake"] is None
    assert harness.wake_calls == []


def test_wake_sub_switch_off_keeps_followups_and_stops_wakes(monkeypatch):
    monkeypatch.setenv(patrol.PA_PATROL_WAKE_ENABLED_ENV, "0")
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=patrol.FOLLOWUP_INITIAL_AGE_SECONDS + 60)],
        pending_inbox=[_receipt_row("r-1", reply_to="m-1")],
    )
    result = patrol.patrol_once(now=NOW)
    assert len(harness.followup_calls) == 1  # 催办不受子开关影响
    assert result["wake"] == {"attempted": False, "reason": "wake_disabled", "receiptCount": 1}
    assert harness.wake_calls == []


def test_wake_seam_passes_policy_bypass_flag(monkeypatch):
    """seam 直呼真实 wake API 时必须带 ignore_delegation_wake_policy=True
    （唯一例外路径；allowWakeMessages 全局语义不改）。"""

    from core.web.services.session import agent_sessions as agent_sessions_module

    captured: list[dict] = []

    def _capture_wake(message, **kwargs):
        captured.append({"message": message, **kwargs})
        return {"wakeStatus": "started", "turnId": "turn-1"}

    monkeypatch.setattr(
        agent_sessions_module, "wake_agent_for_inbox_message", _capture_wake
    )
    delivery = patrol._wake_pa({"messageId": "r-1", "targetAgentId": "agent-pa"})
    assert delivery["wakeStatus"] == "started"
    assert len(captured) == 1
    assert captured[0].get("ignore_delegation_wake_policy") is True
    assert captured[0]["message"]["messageId"] == "r-1"


def test_wake_tolerates_busy_skip_and_counts_the_attempt(monkeypatch):
    """busy/skipped 语义原样透传并计入节流窗口（保守侧安全）。"""

    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=120.0)],
        pending_inbox=[_receipt_row("r-1", reply_to="m-1")],
    )

    def _busy_wake(message):
        return {"wakeStatus": "skipped_busy", "reason": "target_session_busy"}

    monkeypatch.setattr(patrol, "_wake_pa", _busy_wake)
    result = patrol.patrol_once(now=NOW)
    assert result["wake"]["delivery"]["wakeStatus"] == "skipped_busy"
    assert harness.wake_calls == []
    # skipped 同样计入窗口：冷却期内不再尝试。
    result = patrol.patrol_once(now=NOW + 60.0)
    assert result["wake"]["reason"] == "throttled"


def test_wake_picks_newest_receipt_and_defaults_landing_fields(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=120.0)],
        pending_inbox=[
            _receipt_row("r-old", reply_to="m-1", created_age_seconds=600.0),
            _receipt_row("r-new", reply_to="m-1", created_age_seconds=10.0),
        ],
    )
    patrol.patrol_once(now=NOW)
    assert len(harness.wake_calls) == 1
    message = harness.wake_calls[0]["message"]
    assert message["messageId"] == "r-new"
    assert message["targetAgentId"] == "agent-pa"


# ---------------------------------------------------------------------------
# 定时摘要卡
# ---------------------------------------------------------------------------


def test_digest_rotates_on_first_signal_and_stays_stable_without_change(monkeypatch):
    _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)],
        pending_inbox=[_receipt_row("r-1", reply_to="m-1")],
    )
    result = patrol.patrol_once(now=NOW)
    assert result["digest"]["rotated"] is True
    first_row = result["digest"]["row"]
    assert first_row["kind"] == "assistant_digest"
    assert first_row["severity"] == "info"
    assert first_row["targetUrl"] == "/personal-assistant"
    assert first_row["id"].startswith("assistant-digest:")
    # 指纹无变化：id 不轮转（不推新通知），行内容保持。
    result = patrol.patrol_once(now=NOW + 60.0)
    assert result["digest"]["rotated"] is False
    assert result["digest"]["row"]["id"] == first_row["id"]


def test_digest_throttles_rotation_within_interval_on_change(monkeypatch):
    _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)],
        pending_inbox=[_receipt_row("r-1", reply_to="m-1")],
    )
    result = patrol.patrol_once(now=NOW)
    first_id = result["digest"]["row"]["id"]
    # 30min 内新增一条未消化回执：内容变了但不得轮转。
    harness2 = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)],
        pending_inbox=[
            _receipt_row("r-1", reply_to="m-1"),
            _receipt_row("r-2", reply_to="m-1"),
        ],
    )
    result = patrol.patrol_once(now=NOW + 60.0)
    assert result["digest"]["aggregate"]["undigestedReceipts"] == 2
    assert result["digest"]["rotated"] is False
    assert result["digest"]["row"]["id"] == first_id
    # 窗口过后指纹再变 → 轮转一次。
    result = patrol.patrol_once(now=NOW + patrol.DIGEST_MIN_INTERVAL_SECONDS + 60.0)
    assert result["digest"]["rotated"] is True
    assert result["digest"]["row"]["id"] != first_id


def test_digest_disappears_when_everything_settles(monkeypatch):
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)],
    )
    patrol.patrol_once(now=NOW)
    assert patrol.collect_assistant_digest_attention()
    # 回执到达 + 派遣清空 → 无信号 → 行清空，通道安静。
    harness.listing["dispatches"] = []
    harness.pending_inbox = []
    patrol.patrol_once(now=NOW + 60.0)
    assert patrol.collect_assistant_digest_attention() == []


def test_digest_freshness_window_hides_stale_rows(monkeypatch):
    _Harness(monkeypatch, dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)])
    patrol.patrol_once(now=NOW)
    assert patrol.collect_assistant_digest_attention()
    monkeypatch.setattr(patrol.time, "time", lambda: NOW + patrol.DIGEST_FRESHNESS_SECONDS + 1.0)
    assert patrol.collect_assistant_digest_attention() == []


def test_digest_source_registered_in_human_attention_lane(monkeypatch):
    from core.web.services import personal_attention_service as attention

    _Harness(monkeypatch, dispatches=[_dispatch("m-1", sent_age_seconds=3600.0)])
    patrol.patrol_once(now=NOW)
    rows = attention._collect_assistant_digest_attention()
    assert rows and rows[0]["kind"] == "assistant_digest"


# ---------------------------------------------------------------------------
# 急停开关
# ---------------------------------------------------------------------------


def test_total_switch_off_is_a_full_no_op(monkeypatch):
    monkeypatch.setenv(patrol.PA_PATROL_ENABLED_ENV, "0")
    harness = _Harness(
        monkeypatch,
        dispatches=[_dispatch("m-1", sent_age_seconds=patrol.FOLLOWUP_INITIAL_AGE_SECONDS + 60)],
        pending_inbox=[_receipt_row("r-1", reply_to="m-1")],
    )
    result = patrol.patrol_once(now=NOW)
    assert result["enabled"] is False
    assert harness.followup_calls == []
    assert harness.wake_calls == []
    assert result["digest"] is None
    assert patrol.collect_assistant_digest_attention() == []


def test_total_switch_accepts_explicit_on_tokens(monkeypatch):
    for token in ("1", "true", "yes", "on", ""):
        monkeypatch.setenv(patrol.PA_PATROL_ENABLED_ENV, token)
        assert patrol.is_pa_patrol_enabled() is True
    for token in ("0", "false", "off", "no", "disabled"):
        monkeypatch.setenv(patrol.PA_PATROL_ENABLED_ENV, token)
        assert patrol.is_pa_patrol_enabled() is False


def test_missing_assistant_degrades_to_quiet_pass(monkeypatch):
    from core.web.services.personal_assistant_dispatches_service import (
        PersonalAssistantMissingError,
    )

    def _raise():
        raise PersonalAssistantMissingError("no assistant")

    monkeypatch.setattr(patrol, "_load_dispatches", _raise)
    result = patrol.patrol_once(now=NOW)
    assert result == {"enabled": True, "wakeEnabled": False, "reason": "no_assistant"}


# ---------------------------------------------------------------------------
# 循环形状
# ---------------------------------------------------------------------------


def test_forever_loop_survives_a_failing_pass(monkeypatch):
    import asyncio

    async def _run():
        calls = {"n": 0}

        def _flaky_once():
            calls["n"] += 1
            raise RuntimeError("boom")

        monkeypatch.setattr(patrol, "patrol_once", _flaky_once)
        task = asyncio.ensure_future(
            patrol.run_personal_assistant_patrol_forever(interval_seconds=0.01)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls["n"] >= 1

    asyncio.run(_run())
