# -*- coding: utf-8 -*-
"""Regression: supervised continuation submits must tolerate a busy session.

``needs_continue`` 触发产品自动续跑时，监督 harness 的手工续跑提交会与
其撞车吃到 SessionBusyError（swte-e997ff8c7691 实弹定案：真实自改在产出
diff 后被续跑竞态终止）。忙碌应等待重试而非立刻判失败。
"""

from __future__ import annotations

import pytest

from core.web.services import supervised_conversation_harness_adapter as adapter
from core.web.services.session_service import SessionBusyError


def test_busy_session_retries_until_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def flaky_submit(session_id, prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise SessionBusyError("当前会话仍在运行")
        return {"turnId": "turn-ok"}

    sleeps: list[float] = []
    monkeypatch.setattr(adapter, "submit_session_message", flaky_submit)
    monkeypatch.setattr(adapter.time, "sleep", sleeps.append)

    accepted = adapter._submit_continuation_with_busy_retry(
        "session-1",
        "继续",
        mental_model_enabled=None,
        message_metadata={"supervisedEvolution": True},
    )

    assert accepted == {"turnId": "turn-ok"}
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_busy_session_raises_after_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_busy(session_id, prompt, **kwargs):
        raise SessionBusyError("当前会话仍在运行")

    monkeypatch.setattr(adapter, "submit_session_message", always_busy)
    monkeypatch.setattr(adapter.time, "sleep", lambda seconds: None)

    with pytest.raises(SessionBusyError):
        adapter._submit_continuation_with_busy_retry(
            "session-1",
            "继续",
            mental_model_enabled=None,
            message_metadata={},
        )


def test_other_errors_propagate_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def rejects(session_id, prompt, **kwargs):
        calls["n"] += 1
        raise ValueError("unrelated failure")

    monkeypatch.setattr(adapter, "submit_session_message", rejects)
    monkeypatch.setattr(adapter.time, "sleep", lambda seconds: None)

    with pytest.raises(ValueError):
        adapter._submit_continuation_with_busy_retry(
            "session-1",
            "继续",
            mental_model_enabled=None,
            message_metadata={},
        )
    assert calls["n"] == 1
