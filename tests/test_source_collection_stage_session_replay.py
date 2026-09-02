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
