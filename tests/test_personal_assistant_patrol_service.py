"""PA 派遣心跳巡检：aged 判定 / 自动催办 / 回执消化唤醒 / 定时摘要卡 / 急停开关。

成本红线全部钉死成断言：催办每派遣 2 轮上限 + 30min 间隔 + idempotency_key
稳定；唤醒 15min 冷却 + 每小时 2 次上限、无回执不唤醒、busy/skipped 不吃
配额（只对真实提交计）；摘要指纹无变化不推、30min 最多轮转一次；总开关
关=空转（不催不唤醒不推卡）。

批三收口环：本文件前半部分在「台账不可用」的回退语义下验证既有行为；
`_LedgerHarness` 一节用真实 sqlite 台账验证台账驱动判定（出窗回执照样
唤醒）、合并唤醒 N 条全落账、先预留后提交状态机（unknown 不重试、
cancelled_pre_admission 可重试）、节流重启安全与催办走台账。
"""

from __future__ import annotations

import json
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
        "sourceSessionId": "session-pa-original",
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
        from core.web.services import personal_assistant_dispatches_service as dispatch_service
        from core.web.services import session_service

        self.target_agents = [{
            "agentId": target_id, "status": "active", "directSessionId": "different-direct",
        } for target_id in {row["targetAgentId"] for row in dispatches or []}]
        self.session = {"id": "session-1", "agentId": "agent-researcher"}
        self.originals = [{
            "messageId": row["messageId"], "sourceAgentId": pa_agent_id,
            "targetAgentId": row["targetAgentId"], "targetSessionId": row["targetSessionId"],
            "threadId": row["threadId"], "status": row["deliveryStatus"],
            "metadata": {"sourceSessionId": row["sourceSessionId"]},
        } for row in dispatches or []]
        monkeypatch.setattr(dispatch_service, "_agent_rows", lambda: self.target_agents)
        monkeypatch.setattr(dispatch_service, "_inbox_path", lambda _row: None)
        monkeypatch.setattr(dispatch_service, "_scan_inbox_reverse", lambda _path, *, predicate, cap, strict:
                            [row for row in self.originals if predicate(row)][:cap])
        monkeypatch.setattr(session_service, "load_session_chat_state", lambda _root, _id: self.session)
        monkeypatch.setattr(patrol, "_load_dispatches", lambda: dict(self.listing))
        monkeypatch.setattr(
            patrol, "_read_pa_pending_messages", lambda _agent_id: list(self.pending_inbox)
        )
        # 批三：默认模拟「台账不可用」，本文件既有用例全部走 JSONL 回退
        # 语义（台账路径由 _LedgerHarness 专测）。
        monkeypatch.setattr(patrol, "_ledger_ready", lambda _agent_id: False)
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


def test_recent_receipt_defers_chase_without_completing_task(monkeypatch):
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
    result = patrol.patrol_once(now=NOW + patrol.FOLLOWUP_INITIAL_AGE_SECONDS - 60)
    assert result["agedMessageIds"] == ["m-done"]
    assert len(harness.followup_calls) == 1
    assert result["digest"]["aggregate"]["inFlightDispatches"] == 1


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


@pytest.mark.parametrize("task_status", ["completed", "failed", "cancelled", "blocked"])
def test_terminal_or_blocked_task_is_not_chased_but_attention_remains(monkeypatch, task_status):
    dispatch = _dispatch("m-state")
    dispatch["taskStatus"] = task_status
    harness = _Harness(monkeypatch, dispatches=[dispatch])
    result = patrol.patrol_once(now=NOW)
    assert harness.followup_calls == []
    aggregate = result["digest"]["aggregate"]
    assert aggregate["inFlightDispatches"] == int(task_status == "blocked")
    assert aggregate["blockedDispatches"] == int(task_status == "blocked")
    assert aggregate["failedDispatches"] == int(task_status == "failed")
    if task_status in {"blocked", "failed"}:
        assert result["digest"]["row"] is not None


@pytest.mark.parametrize("task_status", ["running", "awaiting_confirmation", "awaiting_result", ""])
def test_old_progress_receipt_keeps_actionable_task_followable(monkeypatch, task_status):
    dispatch = _dispatch("m-progress", receipts=[{"receivedAt": _iso(NOW - 1800)}])
    dispatch["taskStatus"] = task_status
    harness = _Harness(monkeypatch, dispatches=[dispatch])
    result = patrol.patrol_once(now=NOW)
    assert len(harness.followup_calls) == 1
    assert result["digest"]["aggregate"]["inFlightDispatches"] == 1


def test_latest_receipt_wins_and_does_not_extend_original_send_window(monkeypatch):
    dispatch = _dispatch("m-progress", receipts=[
        {"receivedAt": _iso(NOW - 1801)}, {"receivedAt": "invalid"},
        {"receivedAt": _iso(NOW - 1)},
    ])
    harness = _Harness(monkeypatch, dispatches=[dispatch])
    assert patrol.patrol_once(now=NOW)["agedMessageIds"] == []
    dispatch["sentAt"] = _iso(NOW - patrol.FOLLOWUP_MAX_AGE_SECONDS - 1)
    assert patrol.patrol_once(now=NOW + 1800)["agedMessageIds"] == []
    assert harness.followup_calls == []


def test_revoked_dispatch_never_chases_target(monkeypatch):
    dispatch = _dispatch("m-revoked")
    dispatch["deliveryStatus"] = "revoked"
    harness = _Harness(monkeypatch, dispatches=[dispatch])
    result = patrol.patrol_once(now=NOW)
    assert result["agedMessageIds"] == []
    assert harness.followup_calls == []
    assert harness.wake_calls == []
    assert result["digest"]["aggregate"]["inFlightDispatches"] == 0


@pytest.mark.parametrize("invalid", [
    "missing_session", "foreign_session", "archived_session", "missing_agent", "archived_agent",
    "replaced_direct", "revoked_original", "missing_original", "duplicate_original", "foreign_source",
    "foreign_target", "changed_session", "changed_thread", "missing_session_id",
    "missing_source_session", "missing_original_source_session", "foreign_source_session",
])
def test_target_authority_failures_do_not_send_or_consume_round(monkeypatch, invalid):
    dispatch = _dispatch("m-unsafe")
    harness = _Harness(monkeypatch, dispatches=[dispatch])
    if invalid == "missing_session":
        harness.session = None
    elif invalid == "foreign_session":
        harness.session["agentId"] = "other"
    elif invalid == "archived_session":
        harness.session["archive_state"] = {"status": "archived"}
    elif invalid == "missing_agent":
        harness.target_agents = []
    elif invalid == "archived_agent":
        harness.target_agents[0]["status"] = "archived"
    elif invalid == "replaced_direct":
        harness.target_agents[0]["metadata"] = {"previousDirectSessionId": "session-1"}
    elif invalid == "revoked_original":
        harness.originals[0]["status"] = "revoked"
    elif invalid == "missing_original":
        harness.originals = []
    elif invalid == "duplicate_original":
        harness.originals *= 2
    elif invalid == "foreign_source":
        harness.originals[0]["sourceAgentId"] = "impostor"
    elif invalid == "foreign_target":
        harness.originals[0]["targetAgentId"] = "other"
    elif invalid == "changed_session":
        harness.originals[0]["targetSessionId"] = "other"
    elif invalid == "changed_thread":
        harness.originals[0]["threadId"] = "other"
    elif invalid == "missing_session_id":
        dispatch["targetSessionId"] = ""
    elif invalid == "missing_source_session":
        dispatch["sourceSessionId"] = ""
    elif invalid == "missing_original_source_session":
        harness.originals[0]["metadata"].pop("sourceSessionId")
    elif invalid == "foreign_source_session":
        harness.originals[0]["metadata"]["sourceSessionId"] = "other-source-session"
    result = patrol.patrol_once(now=NOW)
    assert result["followupsSent"] == []
    assert harness.followup_calls == []
    assert patrol._patrol_state.followups == {}


def test_followup_metadata_survives_native_kernel_inbox_projection(monkeypatch):
    from core.agent_kernel import service as kernel
    from core.web.services import personal_assistant_dispatches_service as dispatches

    harness = _Harness(monkeypatch, dispatches=[_dispatch("m-origin")])
    patrol.patrol_once(now=NOW)
    call = harness.followup_calls[0]
    assert call["metadata"]["targetSessionId"] == "session-1"  # original != current direct
    assert call["sender"]["sessionId"] == "session-pa-original"
    assert call["metadata"]["sourceSessionId"] == "session-pa-original"
    assert "paFollowupOfMessageId" not in call["metadata"]
    stored = kernel._kernel_inbox_metadata(
        {"eventId": "e-followup", "metadata": call["metadata"]}, {"taskId": "t-followup"},
    )
    stored = json.loads(json.dumps(stored))  # native JSON persistence round-trip
    assert stored["targetSessionId"] == "session-1"
    assert stored["sourceSessionId"] == "session-pa-original"
    custom = dispatches._metadata({"metadata": stored})
    assert custom["paFollowupOfMessageId"] == "m-origin"
    assert custom["paFollowupRound"] == 1
    assert "agent_message_tool" in call["content"]
    assert '"dispatchMessageId": "m-origin"' in call["content"]
    assert "completed 必须提供 evidenceRefs" in call["content"]


def test_followup_wake_prompt_exposes_exact_original_reply_session(monkeypatch):
    from core.web.services.session.agent_sessions import _format_agent_inbox_wake_prompt

    harness = _Harness(monkeypatch, dispatches=[_dispatch("m-addressable")])
    patrol.patrol_once(now=NOW)
    call = harness.followup_calls[0]
    # Native wake formatting serializes message body, not source-session metadata.
    # The receiver must get a concrete tool target from that actual prompt.
    prompt = _format_agent_inbox_wake_prompt({
        "messageId": "m-followup", "kind": patrol.PATROL_SOURCE,
        "sourceAgentId": "agent-pa", "sourceAgentName": "个人助理",
        "content": call["content"], "summary": call["metadata"]["messageSummary"],
        "metadata": {"sourceSessionId": "metadata-is-not-in-the-prompt"},
    })
    assert "target_session=session-pa-original" in prompt
    assert "metadata-is-not-in-the-prompt" not in prompt
    assert "agent_message_tool" in prompt
    assert '"replyToMessageId": "m-addressable"' in prompt
    assert '"dispatchMessageId": "m-addressable"' in prompt
    assert "completed 必须提供 evidenceRefs" in prompt


def test_nested_reply_to_is_a_receipt(monkeypatch):
    row = _receipt_row(kind="agent_message")
    row["metadata"] = {"agentToolMetadataJson": json.dumps({"replyToMessageId": "m-1"})}
    harness = _Harness(monkeypatch, dispatches=[_dispatch("m-1")], pending_inbox=[row])
    assert patrol.patrol_once(now=NOW)["wake"]["attempted"] is True
    assert len(harness.wake_calls) == 1


@pytest.mark.parametrize("revoked_after_listing", [False, True])
def test_followup_rechecks_native_inbox_without_session_repair(tmp_path, monkeypatch, revoked_after_listing):
    from core.web.services import personal_assistant_dispatches_service as dispatches
    from core.web.services import session_service

    scan = dispatches._scan_inbox_reverse
    harness = _Harness(monkeypatch, dispatches=[_dispatch("m-disk")])
    original = harness.originals[0]
    if revoked_after_listing:
        original["status"] = "revoked"
    inbox = tmp_path / "agent_inbox_messages.jsonl"
    inbox.write_text(json.dumps(original) + "\n", encoding="utf-8")
    before = inbox.read_bytes()
    monkeypatch.setattr(dispatches, "_scan_inbox_reverse", scan)
    monkeypatch.setattr(dispatches, "_inbox_path", lambda _row: inbox)

    def _no_repair(*_args, **_kwargs):
        pytest.fail("follow-up must use a side-effect-free persisted session read")

    monkeypatch.setattr(session_service, "get_session_detail", _no_repair)
    result = patrol.patrol_once(now=NOW)
    assert len(result["followupsSent"]) == int(not revoked_after_listing)
    assert len(harness.followup_calls) == int(not revoked_after_listing)
    assert inbox.read_bytes() == before


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


def test_wake_busy_skip_does_not_consume_quota(monkeypatch):
    """busy/skipped 可证未起 turn：语义原样透传，但不再白白吃配额，
    下一轮照常重试（批三：只对真实提交计）。"""

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
    # 无预留（回退路径）也不吃配额：冷却期内仍重试。
    result = patrol.patrol_once(now=NOW + 60.0)
    assert result["wake"]["attempted"] is True
    # 真实提交（started）才计入：冷却窗口随后生效。
    monkeypatch.setattr(
        patrol, "_wake_pa", lambda message: {"wakeStatus": "started", "turnId": "t"}
    )
    assert patrol.patrol_once(now=NOW + 120.0)["wake"]["attempted"] is True
    throttled = patrol.patrol_once(now=NOW + 180.0)
    assert throttled["wake"] == {"attempted": False, "reason": "throttled", "receiptCount": 1}


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


# ---------------------------------------------------------------------------
# 台账路径（批三收口环）：真实 sqlite 台账驱动的判定 / 合并唤醒 / 预留状态机
# ---------------------------------------------------------------------------

from tests.test_personal_assistant_dispatch_ledger import (  # noqa: E402
    _agent_row as _ledger_agent_row,
    _write_inbox as _ledger_write_inbox,
)
from tests.test_personal_assistant_service import (  # noqa: E402
    finance_env as _finance_env,
)
from tests.test_personal_assistant_service import personal_env  # noqa: E402,F401

# fixture 解析需要本模块命名空间持有 finance_env 名字（personal_env 依赖它）。
finance_env = _finance_env

PA_ID = "agent-pa"
TARGET_ID = "agent-researcher"


def _seed_ledger_agents(personal_env) -> None:
    from core.web.services import agent_directory_service as directory

    state = directory.load_state()
    state["agents"] = [
        _ledger_agent_row(PA_ID, is_assistant=True),
        _ledger_agent_row(TARGET_ID),
    ]
    directory.save_state(state)


def _ledger_dispatch(message_id: str, *, created_at: str, status: str = "pending") -> dict:
    return {
        "eventId": f"event-{message_id}",
        "messageId": message_id,
        "threadId": f"thread-{message_id}",
        "kind": "agent_message",
        "status": status,
        "sourceAgentId": PA_ID,
        "sourceAgentName": "个人助理",
        "targetAgentId": TARGET_ID,
        "targetAgentName": "研究员",
        "targetSessionId": "target-session",
        "summary": "派遣摘要",
        "createdAt": created_at,
        "metadata": {"sourceSessionId": "pa-source-session"},
    }


def _ledger_receipt(
    message_id: str,
    *,
    reply_to: str = "",
    created_at: str,
    thread_id: str = "",
    kind: str = "agent_inbox_message",
    status: str = "pending",
) -> dict:
    return {
        "eventId": f"event-{message_id}",
        "messageId": message_id,
        "threadId": thread_id,
        "kind": kind,
        "status": status,
        "promptEligible": True,
        "sourceAgentId": TARGET_ID,
        "sourceAgentName": "研究员",
        "targetAgentId": PA_ID,
        "targetSessionId": "pa-session",
        "summary": "回执摘要",
        "content": f"{message_id} 的回执正文",
        "createdAt": created_at,
        "metadata": {"replyToMessageId": reply_to} if reply_to else {},
    }


def _seed_dispatch_and_receipts(personal_env, receipt_ids: list[str]) -> str:
    dispatch_id = "m-1"
    _ledger_write_inbox(personal_env, TARGET_ID, [
        _ledger_dispatch(dispatch_id, created_at=_iso(NOW - 120)),
    ])
    _ledger_write_inbox(personal_env, PA_ID, [
        _ledger_receipt(
            receipt_id,
            reply_to=dispatch_id,
            created_at=_iso(NOW - 60 + index),
        )
        for index, receipt_id in enumerate(receipt_ids)
    ])
    return dispatch_id


class _LedgerHarness:
    """Real ledger + real JSONL inboxes; only the action seams are faked."""

    def __init__(self, monkeypatch, *, pa_agent_id: str = PA_ID) -> None:
        self.pa_agent_id = pa_agent_id
        self.wake_calls: list[dict] = []
        self.followup_calls: list[dict] = []
        self.sessions: dict[str, dict] = {
            "target-session": {"id": "target-session", "agentId": TARGET_ID},
        }
        monkeypatch.setattr(patrol, "_pa_sender", lambda: {
            "type": "agent", "id": pa_agent_id, "agentId": pa_agent_id,
            "displayName": "个人助理", "agentCode": "pa",
        })

        def _fake_wake(message):
            self.wake_calls.append({"message": message})
            return {
                "wakeStatus": "started",
                "turnId": "turn-1",
                "targetSessionId": str(message.get("targetSessionId") or ""),
            }

        monkeypatch.setattr(patrol, "_wake_pa", _fake_wake)

        def _fake_submit(**kwargs):
            self.followup_calls.append(kwargs)
            return {"accepted": True}

        monkeypatch.setattr(patrol, "_submit_followup_event", _fake_submit)

        from core.web.services import session_service

        monkeypatch.setattr(
            session_service,
            "load_session_chat_state",
            lambda _root, session_id: self.sessions.get(session_id),
        )


def _wake_attempt_rows() -> list[tuple]:
    import sqlite3

    from core.web.services import personal_assistant_dispatch_ledger as ledger

    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        return list(connection.execute(
            "SELECT state, submitted_at_ms, receipt_ids FROM wake_attempts "
            "ORDER BY reserved_at_ms"
        ))
    finally:
        connection.close()


def _receipt_digested_at(message_id: str) -> str | None:
    import sqlite3

    from core.web.services import personal_assistant_dispatch_ledger as ledger

    connection = sqlite3.connect(str(ledger.ledger_database_path()))
    try:
        row = connection.execute(
            "SELECT digested_at, status FROM receipts WHERE message_id=?",
            (message_id,),
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else row[0]


def test_ledger_merged_wake_digs_all_receipts_in_one_turn(monkeypatch, personal_env):
    """合并唤醒：N 条未消化回执一轮 turn 消化，digested_at 全部落账。"""

    _seed_ledger_agents(personal_env)
    _seed_dispatch_and_receipts(personal_env, ["r-1", "r-2", "r-3"])
    harness = _LedgerHarness(monkeypatch)

    result = patrol.patrol_once(now=NOW)

    assert result["wake"]["attempted"] is True
    assert len(harness.wake_calls) == 1  # 一轮 turn，不是三条
    message = harness.wake_calls[0]["message"]
    assert message["messageId"] == "r-3"  # carrier = 最新一条
    for receipt_id in ("r-1", "r-2", "r-3"):
        assert receipt_id in message["content"]
    assert "合并" in message["content"]
    # 硬约束：N 条 digested_at 全部落账，不留半消化态。
    assert result["wake"]["digestedReceiptIds"] == ["r-1", "r-2", "r-3"]
    for receipt_id in ("r-1", "r-2", "r-3"):
        assert _receipt_digested_at(receipt_id) is not None
    states = [row[0] for row in _wake_attempt_rows()]
    assert states == ["accepted"]
    # 非 carrier 回执随轮 consume（carrier 由真实 wake 内部消费）。
    assert sorted(result["wake"]["consumedReceiptIds"]) == ["r-1", "r-2"]
    # 全部消化后：不再唤醒。
    assert patrol.patrol_once(now=NOW + 60.0)["wake"] is None


def test_ledger_wakes_receipt_outside_legacy_window(monkeypatch, personal_env):
    """出窗回执照样可见照样唤醒（批三核心目标）：计数窗口现算已死。"""

    _seed_ledger_agents(personal_env)
    dispatch_id = _seed_dispatch_and_receipts(personal_env, ["r-old"])
    # 250 条更新的无关行把 r-old 推出 200 条的 JSONL 读取窗口。
    fillers = [
        _ledger_receipt(
            f"noise-{index:03d}",
            created_at=_iso(NOW - 50 + index * 0.1),
            kind="announcement",
        )
        for index in range(250)
    ]
    _ledger_write_inbox(personal_env, PA_ID, [
        _ledger_receipt("r-old", reply_to=dispatch_id, created_at=_iso(NOW - 60)),
        *fillers,
    ])
    _LedgerHarness(monkeypatch)

    # 旧判定（计数窗口）看不见它。
    assert patrol.find_undigested_receipts(PA_ID, {dispatch_id}) == []
    result = patrol.patrol_once(now=NOW)

    assert result["wake"]["attempted"] is True
    assert result["wake"]["mergedReceiptIds"] == ["r-old"]
    assert _receipt_digested_at("r-old") is not None


def test_ledger_wake_unknown_never_retries_but_new_receipts_wake(monkeypatch, personal_env):
    """unknown（结果不可证）永不重试；新回执照常唤醒且不带旧批次。"""

    _seed_ledger_agents(personal_env)
    _seed_dispatch_and_receipts(personal_env, ["r-1"])
    harness = _LedgerHarness(monkeypatch)

    def _boom(message):
        raise RuntimeError("kernel exploded")

    monkeypatch.setattr(patrol, "_wake_pa", _boom)
    result = patrol.patrol_once(now=NOW)
    assert result["wake"]["delivery"]["wakeStatus"] == "error"
    states = [(row[0], row[1] is not None) for row in _wake_attempt_rows()]
    assert states == [("unknown", True)]  # 计配额（真实提交与否不可证）

    # r-1 被不可重试意图覆盖：冷却过后也不再为它唤醒。
    assert patrol.patrol_once(now=NOW + patrol.WAKE_COOLDOWN_SECONDS + 1)["wake"] is None
    assert _receipt_digested_at("r-1") is None  # 仍未消化，摘要卡可见

    # 新回执到达：只唤醒新批次，不带 r-1。
    _ledger_write_inbox(personal_env, PA_ID, [
        _ledger_receipt("r-1", reply_to="m-1", created_at=_iso(NOW - 60)),
        _ledger_receipt("r-2", reply_to="m-1", created_at=_iso(NOW + 60)),
    ])
    def _recovered_wake(message):
        harness.wake_calls.append({"message": message})
        return {"wakeStatus": "started", "turnId": "turn-1", "targetSessionId": ""}

    monkeypatch.setattr(patrol, "_wake_pa", _recovered_wake)
    result = patrol.patrol_once(now=NOW + 2 * patrol.WAKE_COOLDOWN_SECONDS)
    assert result["wake"]["attempted"] is True
    assert result["wake"]["mergedReceiptIds"] == ["r-2"]
    message = harness.wake_calls[-1]["message"]
    assert message["messageId"] == "r-2"
    assert "r-1" not in message["content"]


def test_ledger_wake_skipped_is_retryable_without_quota(monkeypatch, personal_env):
    """cancelled_pre_admission 可重试且不吃配额；真实提交才落节流戳。"""

    _seed_ledger_agents(personal_env)
    _seed_dispatch_and_receipts(personal_env, ["r-1"])
    harness = _LedgerHarness(monkeypatch)

    def _busy(message):
        harness.wake_calls.append({"message": message})
        return {"wakeStatus": "skipped_busy", "reason": "target_session_busy"}

    monkeypatch.setattr(patrol, "_wake_pa", _busy)
    assert patrol.patrol_once(now=NOW)["wake"]["delivery"]["wakeStatus"] == "skipped_busy"
    assert patrol.patrol_once(now=NOW + 60.0)["wake"]["attempted"] is True  # 可重试
    states = [row[0] for row in _wake_attempt_rows()]
    assert states == ["cancelled_pre_admission", "cancelled_pre_admission"]

    from core.web.services import personal_assistant_dispatch_ledger as ledger

    assert ledger.recent_wake_submissions(
        window_ms=int(patrol.WAKE_HOUR_WINDOW_SECONDS * 1000), now_ms=int(NOW * 1000)
    ) == []  # skipped 从不吃配额

    def _started(message):
        harness.wake_calls.append({"message": message})
        return {"wakeStatus": "started", "turnId": "turn-1", "targetSessionId": ""}

    monkeypatch.setattr(patrol, "_wake_pa", _started)
    result = patrol.patrol_once(now=NOW + 120.0)
    assert result["wake"]["attempted"] is True
    assert len(harness.wake_calls) == 3
    assert _receipt_digested_at("r-1") is not None


def test_ledger_wake_throttle_survives_restart(monkeypatch, personal_env):
    """节流持久化：accepted 戳在台账，进程重启（内存清零）不风暴。"""

    _seed_ledger_agents(personal_env)
    _seed_dispatch_and_receipts(personal_env, ["r-1"])
    _LedgerHarness(monkeypatch)

    assert patrol.patrol_once(now=NOW)["wake"]["attempted"] is True
    # 真实提交只记台账（内存镜像冗余）；模拟进程重启：
    patrol.reset_personal_assistant_patrol_for_tests()
    assert patrol._in_memory_wake_stamps(patrol._patrol_state) == []
    stamps = patrol._wake_throttle_stamps(
        patrol._patrol_state, ledger_ready=True, now=NOW + 60.0
    )
    assert len(stamps) == 1  # 戳来自台账，重启不清零

    # 新回执在冷却期内到达 → 台账节流仍然压制，不风暴。
    _ledger_write_inbox(personal_env, PA_ID, [
        _ledger_receipt("r-1", reply_to="m-1", created_at=_iso(NOW - 60)),
        _ledger_receipt("r-2", reply_to="m-1", created_at=_iso(NOW + 60)),
    ])
    result = patrol.patrol_once(now=NOW + patrol.WAKE_COOLDOWN_SECONDS - 30)
    assert result["wake"] == {"attempted": False, "reason": "throttled", "receiptCount": 1}
    # 冷却过后放行。
    result = patrol.patrol_once(now=NOW + patrol.WAKE_COOLDOWN_SECONDS + 1)
    assert result["wake"]["attempted"] is True


def test_ledger_followup_pairs_via_ledger_without_jsonl_rescan(monkeypatch, personal_env):
    """催办 strict 正读走台账信封列，不再每轮全文件扫描。"""

    from core.web.services import personal_assistant_dispatches_service as dispatches

    _seed_ledger_agents(personal_env)
    _ledger_write_inbox(personal_env, TARGET_ID, [
        _ledger_dispatch("m-aged", created_at=_iso(NOW - 3600)),
    ])
    harness = _LedgerHarness(monkeypatch)

    def _forbid_scan(*_args, **_kwargs):
        pytest.fail("ledger verdict must replace the strict JSONL rescan")

    monkeypatch.setattr(dispatches, "_scan_inbox_reverse", _forbid_scan)
    result = patrol.patrol_once(now=NOW)

    assert result["followupsSent"] == [{"messageId": "m-aged", "round": 1}]
    assert len(harness.followup_calls) == 1
    assert harness.followup_calls[0]["idempotency_key"] == "pa-followup:m-aged:1"
