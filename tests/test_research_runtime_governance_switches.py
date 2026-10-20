"""科研运行时通用治理开关（env kill switch）与默认行为测试。

封存模式（challenge archive mode）治理链已整体退役：运行时默认即通用
行为。这里守住两件仍然存在的通用事实：

- 默认（不设任何 env）production runtime 正常启动、hypothesis recovery
  循环正常运转、reaper 默认启用、lifecycle 启动任务正常创建；
- 两个通用 env kill switch 依旧有效：
  ``VIBELUTION_AUTO_ADVANCE_DISABLED``（auto-advance 全链路 kill，含
  closure sweep）与 ``VIBELUTION_AWAITING_APPROVAL_REAPER``（关闭
  awaiting-approval reaper）。
"""

from __future__ import annotations

from typing import Any

import pytest

_GOVERNANCE_ENVS_TO_CLEAR = (
    "VIBELUTION_AUTO_ADVANCE_DISABLED",
    "VIBELUTION_AWAITING_APPROVAL_REAPER",
)


@pytest.fixture(autouse=True)
def _clean_governance_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env in _GOVERNANCE_ENVS_TO_CLEAR:
        monkeypatch.delenv(env, raising=False)


# ---------------------------------------------------------------------------
# 默认行为：production runtime 正常启动
# ---------------------------------------------------------------------------


def test_start_production_runtime_default_starts_normally(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认（不设任何治理 env）启动路径正常：真实构建 + ready。"""

    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        production_workflow_runtime,
        start_production_workflow_runtime,
        stop_production_workflow_runtime,
    )

    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    stop_production_workflow_runtime()

    assert start_production_workflow_runtime() == "ready"
    assert production_workflow_runtime() is not None
    stop_production_workflow_runtime()
    assert production_workflow_runtime() is None


# ---------------------------------------------------------------------------
# auto-advance kill switch（仅 env 控制）
# ---------------------------------------------------------------------------


def test_kill_switch_env_blocks_auto_advance_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """closure sweep 归 auto-advance 语义：env kill switch 下不扫。"""

    import core.web.services.team_workflow.research_runtime.hypothesis_first_chain as chain
    from core.web.services.team_workflow.research_runtime import runtime_factory
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        WorkflowRuntime,
    )

    calls: list[str] = []

    def _recorder() -> dict[str, int]:
        calls.append("sweep")
        return {"adjudicated": 0, "formalRuns": 0}

    monkeypatch.setattr(chain, "sweep_auto_advance_closure", _recorder)
    monkeypatch.setattr(runtime_factory, "_auto_advance_sweep_due", lambda now: True)

    sweep = WorkflowRuntime._sweep_auto_advance_closure_best_effort

    # env kill switch 命中：sweep 不执行。
    monkeypatch.setenv("VIBELUTION_AUTO_ADVANCE_DISABLED", "1")
    sweep(None)  # 早退发生在任何 self 访问之前，None 作为 self 安全
    assert calls == []

    # env 未设置：sweep 正常执行（mock 版，不触碰真实工作区）。
    monkeypatch.delenv("VIBELUTION_AUTO_ADVANCE_DISABLED", raising=False)
    sweep(None)
    assert calls == ["sweep"]


def test_kill_switch_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """kill switch 只认显式 truthy；falsy/未设置都视为开（不禁用）。"""

    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )

    monkeypatch.delenv("VIBELUTION_AUTO_ADVANCE_DISABLED", raising=False)
    assert automation_policy_executor.kill_switch_enabled() is False

    monkeypatch.setenv("VIBELUTION_AUTO_ADVANCE_DISABLED", "1")
    assert automation_policy_executor.kill_switch_enabled() is True

    monkeypatch.setenv("VIBELUTION_AUTO_ADVANCE_DISABLED", "false")
    assert automation_policy_executor.kill_switch_enabled() is False


# ---------------------------------------------------------------------------
# awaiting-approval reaper
# ---------------------------------------------------------------------------


def test_reaper_enabled_by_default_and_env_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import reaper

    assert reaper.reaper_enabled() is True

    monkeypatch.setenv("VIBELUTION_AWAITING_APPROVAL_REAPER", "0")
    assert reaper.reaper_enabled() is False


def test_reaper_entry_skips_under_env_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import reaper

    monkeypatch.setenv("VIBELUTION_AWAITING_APPROVAL_REAPER", "off")
    summary = reaper.reap_awaiting_approval_meetings(respect_throttle=False)
    assert summary["status"] == "skipped"
    assert summary["reason"] == "kill_switch_off"


# ---------------------------------------------------------------------------
# outbox pump hypothesis recovery 循环
# ---------------------------------------------------------------------------


class _StubRuntime:
    def __init__(self) -> None:
        self.recovery_calls: list[int] = []

    def run_hypothesis_recovery_once(self, limit: int = 4) -> int:
        self.recovery_calls.append(limit)
        return 0


def test_hypothesis_recovery_loop_runs_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from core.web.services.team_workflow.research_runtime.outbox_pump import (
        WorkflowOutboxPump,
    )

    pump = WorkflowOutboxPump(workers=1)
    stub = _StubRuntime()
    pump._runtime = stub

    thread = threading.Thread(target=pump._hypothesis_recovery_loop, daemon=True)
    thread.start()
    for _ in range(100):
        if stub.recovery_calls:
            break
        threading.Event().wait(0.05)
    pump._stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(stub.recovery_calls) >= 1


# ---------------------------------------------------------------------------
# lifecycle 启动任务门（默认正常创建）
# ---------------------------------------------------------------------------


class _FakeStartupJobs:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start_thread(self, name: str, fn: Any, **kwargs: Any) -> str:
        self.started.append(name)
        return f"task:{name}"


def test_lifecycle_meeting_recovery_job_starts_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web import lifecycle

    jobs = _FakeStartupJobs()
    task = lifecycle._start_meeting_driver_recovery_job(jobs)
    assert task == "task:startup-meeting-driver-recovery"
    assert jobs.started == ["startup-meeting-driver-recovery"]


def test_lifecycle_workflow_runtime_job_starts_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web import lifecycle

    jobs = _FakeStartupJobs()
    task = lifecycle._start_workflow_runtime_job(jobs)
    assert task == "task:startup-workflow-runtime"
    assert jobs.started == ["startup-workflow-runtime"]
