#!/usr/bin/env python3
"""stage_session_replay 回归：失败任务的 replay 决策契约。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.web.services.team_workflow.source_collection.stage_session_replay as replay_module


class _FakeSessionService:
    def __init__(self, session_detail):
        self._session_detail = session_detail

    def get_session_detail(self, session_id):
        return self._session_detail


class _FakeService:
    class TeamWorkflowOrchestrationError(RuntimeError):
        pass

    SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES = {
        "queued",
        "running",
        "completed",
        "needs_review",
        "blocked",
        "failed",
        "cancelled",
        "interrupted",
    }
    SOURCE_COLLECTION_STAGE_SESSION_TASK_ACTIVE_STATUSES = {"queued", "running"}

    @staticmethod
    def _trim_text(value, max_length=0):
        text = str(value or "").strip()
        return text[:max_length] if max_length else text

    @staticmethod
    def utc_now_iso():
        return "2026-09-02T00:00:00Z"

    def __init__(self, session_detail=None):
        self.session_service = _FakeSessionService(session_detail)
        self.events = []
        self.upserts = []

    def _record_workflow_event(self, event_type, team_id, fields=None, **kwargs):
        self.events.append((event_type, str(team_id), dict(fields or {})))

    def _upsert_source_collection_stage_session_task(self, team_id, run_id, task):
        self.upserts.append(dict(task))


def _task(**overrides):
    task = {
        "taskId": "stagetask-1",
        "sessionId": "session-1",
        "status": "failed",
        "failureCode": "context_budget_exhausted",
        "failureMessage": "上下文预算超出硬上限（context_budget_exhausted）。",
        "turn": {"accepted": True, "turnId": "turn-1", "status": "failed"},
    }
    task.update(overrides)
    return task


def _prepare(monkeypatch, fake, task):
    monkeypatch.setattr(replay_module, "_service", lambda: fake)
    return replay_module.prepare_source_collection_stage_task_replay(
        "team-1",
        "run-1",
        task,
    )


def test_failed_context_budget_task_retries_with_new_session(monkeypatch):
    """failed + context_budget 分类命中 → formal_retry_same_task（换新会话），
    不再把失败轮 summary 反喂进旧会话历史。"""
    fake = _FakeService(session_detail={"sessionId": "session-1"})
    result = _prepare(monkeypatch, fake, _task())

    assert result["action"] == "formal_retry_same_task"
    assert result["recoveryReason"] == replay_module.CONTEXT_BUDGET_RETRY_NEW_SESSION
    assert result["task"]["taskId"] == "stagetask-1"
    assert any(
        event_type == "source_collection.stage_session_task_context_budget_retry"
        for event_type, _team_id, _fields in fake.events
    )


def test_failed_without_diagnostics_summary_retries_with_new_session(monkeypatch):
    """历史死循环形态（without_diagnostics 兜底文案）同样换新会话。"""
    fake = _FakeService(session_detail={"sessionId": "session-1"})
    result = _prepare(
        monkeypatch,
        fake,
        _task(
            failureCode="",
            failureMessage="",
            summary="当前轮执行失败：Agent 未返回结构化失败诊断，请按 Trace 检查运行场景。",
        ),
    )

    assert result["action"] == "formal_retry_same_task"


def test_other_failed_tasks_keep_reuse(monkeypatch):
    """其余失败形态保持既有 reuse 语义（回归）。"""
    fake = _FakeService(session_detail={"sessionId": "session-1"})
    result = _prepare(
        monkeypatch,
        fake,
        _task(
            failureCode="failed_provider",
            failureMessage="Provider timeout after retries.",
            summary="Agent 私聊执行失败。",
        ),
    )

    assert result["action"] == "reuse"
    assert result["task"]["taskId"] == "stagetask-1"


def test_queued_pre_submit_task_still_resumes(monkeypatch):
    """queued 且无 accepted turn 的既有 resume 语义不变（回归）。"""
    fake = _FakeService(session_detail={"sessionId": "session-1"})
    result = _prepare(
        monkeypatch,
        fake,
        _task(
            status="queued",
            failureCode="",
            failureMessage="",
            turn={"accepted": False, "turnId": ""},
        ),
    )

    assert result["action"] == "resume_same_task"


def test_marker_in_turn_summary_also_matches(monkeypatch):
    """分类文本落在 turn.summary 时同样命中（保守文本匹配的覆盖面）。"""
    fake = _FakeService(session_detail={"sessionId": "session-1"})
    result = _prepare(
        monkeypatch,
        fake,
        _task(
            failureCode="",
            failureMessage="",
            summary="",
            turn={
                "accepted": True,
                "turnId": "turn-1",
                "status": "failed",
                "summary": "上下文预算超出硬上限（context_budget_exhausted）。",
            },
        ),
    )

    assert result["action"] == "formal_retry_same_task"


if __name__ == "__main__":
    pytest.main([__file__])


def test_turn_terminal_failure_shape_retries_with_new_session(monkeypatch):
    """turn 终态失败传播写入的失败形态（failed + 结构化 failureCode +
    failureMessage 摘要）必须命中 formal_retry_same_task，毒会话不再被复用。"""
    fake = _FakeService(session_detail={"sessionId": "session-1"})
    propagated = _task(
        failureCode="context_budget_exhausted",
        failureMessage=(
            "Agent turn ended in terminal status 'failed_runtime'. "
            "Reason: context_budget_exhausted. Stage task marked failed so the "
            "formal replay can pick a recovery path."
        ),
    )
    result = _prepare(monkeypatch, fake, propagated)

    assert result["action"] == "formal_retry_same_task"
    assert result["recoveryReason"] == replay_module.CONTEXT_BUDGET_RETRY_NEW_SESSION


def test_reconcile_keeps_explicit_failure_over_writeback_status(monkeypatch):
    """writeback 早已写入 needs_review 的任务被显式标 failed+failureCode 后，
    状态 reconcile 不得把它翻回 needs_review（否则 replay 永远看到非终态）。"""
    import core.web.services.team_workflow.source_collection.stage_reconcile as reconcile_module

    fake = _FakeService(session_detail={"sessionId": "session-1"})
    monkeypatch.setattr(reconcile_module, "_service", lambda: fake)
    task = _task(
        writeback={"status": "needs_review"},
        turn={"accepted": True, "turnId": "turn-1", "status": "needs_review"},
    )

    reconciled = (
        reconcile_module._reconcile_source_collection_stage_session_task_turn_status(
            task
        )
    )

    assert reconciled is task
    assert reconciled["status"] == "failed"
    assert reconciled["failureCode"] == "context_budget_exhausted"


def test_reconcile_legacy_flip_without_failure_code_unchanged(monkeypatch):
    """无 failureCode 的历史 failed 任务保持既有 reconcile 翻转语义（回归）。"""
    import core.web.services.team_workflow.source_collection.stage_reconcile as reconcile_module

    fake = _FakeService(session_detail={"sessionId": "session-1"})
    monkeypatch.setattr(reconcile_module, "_service", lambda: fake)
    task = _task(
        failureCode="",
        writeback={"status": "needs_review"},
        turn={"accepted": True, "turnId": "turn-1", "status": "failed"},
    )

    reconciled = (
        reconcile_module._reconcile_source_collection_stage_session_task_turn_status(
            task
        )
    )

    assert reconciled is not task
    assert reconciled["status"] == "needs_review"
    assert reconciled["turn"]["status"] == "needs_review"


def test_turn_journal_completed_result_preserves_completed_status(monkeypatch):
    """A completed native turn is execution evidence, not an interruption."""
    import core.web.services.team_workflow.source_collection.stage_reconcile as reconcile_module

    fake = _FakeService(session_detail={"sessionId": "session-1"})
    monkeypatch.setattr(reconcile_module, "_service", lambda: fake)
    result = reconcile_module._source_collection_stage_session_task_turn_journal_result(
        "session-1",
        "turn-1",
        events=[
            SimpleNamespace(
                turn_id="turn-1",
                event_type="turn_completed",
                status="completed",
                payload={"summary": "本轮执行完成。"},
                event_id="event-completed",
                timestamp="2026-09-06T12:00:00Z",
            )
        ],
    )

    assert result["status"] == "completed"
    assert result["eventId"] == "event-completed"
    assert result["summary"] == "本轮执行完成。"


def test_turn_journal_needs_continue_result_stays_interrupted(monkeypatch):
    """A paused completion event remains resumable instead of becoming done."""
    import core.web.services.team_workflow.source_collection.stage_reconcile as reconcile_module

    fake = _FakeService(session_detail={"sessionId": "session-1"})
    monkeypatch.setattr(reconcile_module, "_service", lambda: fake)
    result = reconcile_module._source_collection_stage_session_task_turn_journal_result(
        "session-1",
        "turn-1",
        events=[
            SimpleNamespace(
                turn_id="turn-1",
                event_type="turn_completed",
                status="needs_continue",
                payload={"summary": "本轮暂停，等待继续。"},
                event_id="event-needs-continue",
                timestamp="2026-09-06T12:00:00Z",
            )
        ],
    )

    assert result["status"] == "interrupted"
    assert result["eventId"] == "event-needs-continue"


@pytest.mark.parametrize(
    ("terminal_status", "expected_status"),
    [("completed", "completed"), ("ready", "interrupted")],
)
def test_completion_snapshot_maps_completed_without_reclassifying_ready(
    monkeypatch, terminal_status, expected_status
):
    """Only an explicit completed terminal snapshot is completed evidence."""
    import core.web.services.team_workflow.source_collection.stage_reconcile as reconcile_module

    fake = _FakeService(session_detail={"sessionId": "session-1"})
    fake.session_service.get_session_turn_completion_snapshot = lambda session_id, turn_id: {
        "sessionId": session_id,
        "turnId": turn_id,
        "terminal": True,
        "terminalStatus": terminal_status,
        "completionSource": "turn_journal",
        "assistantText": "本轮已有最终回复。",
        "isRunning": False,
    }
    monkeypatch.setattr(reconcile_module, "_service", lambda: fake)

    result = reconcile_module._source_collection_stage_session_task_completion_snapshot_result(
        "session-1", "turn-1"
    )

    assert result["status"] == expected_status


def test_context_budget_replay_accepts_interrupted_task(monkeypatch):
    """continuation 耗尽/needs_continue 的 turn 会被 reconcile 归一成 interrupted，
    但 failure summary 仍携带 context_budget 证据：interrupted 必须同样换新会话，
    否则每次重试都复用已超限的中毒会话（事故：同一会话 a4/a5 连续两轮死于
    同一上下文硬上限前置闸）。"""
    fake = _FakeService(session_detail={"sessionId": "session-1"})
    result = _prepare(
        monkeypatch,
        fake,
        _task(
            status="interrupted",
            failureCode="agent_turn_continuation_exhausted",
            failureMessage=(
                "连续 3 级 continuation 全部被前置闸拒绝，无进展。"
                "上下文预算超出硬上限（context_budget_exhausted）。"
            ),
        ),
    )

    assert result["action"] == "formal_retry_same_task"
    assert result["recoveryReason"] == replay_module.CONTEXT_BUDGET_RETRY_NEW_SESSION
    assert result["task"]["taskId"] == "stagetask-1"
    assert any(
        event_type == "source_collection.stage_session_task_context_budget_retry"
        for event_type, _team_id, _fields in fake.events
    )


def test_interrupted_without_context_marker_keeps_reuse(monkeypatch):
    """interrupted 但 summary 无 context budget 标记 → 保持既有 reuse 语义（回归）。"""
    fake = _FakeService(session_detail={"sessionId": "session-1"})
    result = _prepare(
        monkeypatch,
        fake,
        _task(
            status="interrupted",
            failureCode="agent_turn_continuation_exhausted",
            failureMessage="Continuation exhausted without progress.",
            summary="连续续跑无进展，任务已暂停。",
        ),
    )

    assert result["action"] == "reuse"
    assert result["task"]["taskId"] == "stagetask-1"


def test_interrupted_on_context_budget_loop_upgrades_to_formal_retry() -> None:
    """An interrupted task with context-budget evidence re-opens on a fresh
    session; marker-less interrupted tasks keep the resume-in-place semantics.

    Incident: the context-saturated extraction session was reused across
    retries because the lineage-based auto-formal-retry gate did not
    recognize the interrupted-with-context-marker form, so every retry
    replayed the poisoned history and died on the same front gate
    (a5 -> a6 on session-20260909-004717-003871).
    """
    from core.web.services.team_workflow.source_collection import stage_session

    saturated = {
        "status": "interrupted",
        "summary": "context budget exceeded the hard cap (context_budget_exhausted)",
    }
    assert stage_session._interrupted_on_context_budget_loop(saturated) is True

    mid_work_interrupt = {"status": "interrupted", "summary": "read interrupted by operator"}
    assert stage_session._interrupted_on_context_budget_loop(mid_work_interrupt) is False
    assert stage_session._interrupted_on_context_budget_loop(None) is False
    assert "interrupted" not in stage_session._AUTO_FORMAL_RETRY_STATUSES
    for retained in ("error", "failed", "incomplete", "timed_out", "timeout", "blocked"):
        assert retained in stage_session._AUTO_FORMAL_RETRY_STATUSES
