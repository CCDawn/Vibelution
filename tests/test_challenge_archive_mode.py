"""挑战杯封存模式（VIBELUTION_CHALLENGE_ARCHIVE_MODE）开关行为测试。

覆盖：
- archive_mode 开关解析优先级（env 显式 > operator config > 默认关）；
- auto-advance kill switch 被封存模式覆盖（automation_policy_executor）；
- awaiting-approval reaper 在封存下停用；
- start_production_workflow_runtime 封存下不启动（默认关行为不变）；
- outbox pump hypothesis recovery 循环封存下不起；
- lifecycle 启动任务（meeting-driver recovery / workflow runtime）封存下
  不创建、默认关正常创建。
"""

from __future__ import annotations

from typing import Any

import pytest

from core.web.services.team_workflow.research_runtime import archive_mode
from core.web.services.team_workflow.research_runtime.archive_mode import (
    CHALLENGE_ARCHIVE_MODE_ENV,
    challenge_archive_mode_enabled,
)

_ARCHIVE_ENVS_TO_CLEAR = (
    CHALLENGE_ARCHIVE_MODE_ENV,
    "VIBELUTION_AUTO_ADVANCE_DISABLED",
    "VIBELUTION_AWAITING_APPROVAL_REAPER",
)


@pytest.fixture(autouse=True)
def _clean_archive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env in _ARCHIVE_ENVS_TO_CLEAR:
        monkeypatch.delenv(env, raising=False)


# ---------------------------------------------------------------------------
# archive_mode 解析优先级
# ---------------------------------------------------------------------------


def test_archive_mode_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺省（无 env、config 不可达）必须为关：历史行为零变化。"""

    assert challenge_archive_mode_enabled() is False


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "TRUE"])
def test_archive_mode_env_truthy(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(CHALLENGE_ARCHIVE_MODE_ENV, raw)
    assert challenge_archive_mode_enabled() is True


@pytest.mark.parametrize("raw", ["0", "false", "off", "no"])
def test_archive_mode_env_falsy_explicit_off(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(CHALLENGE_ARCHIVE_MODE_ENV, raw)
    assert challenge_archive_mode_enabled() is False


def _install_config_stub(
    monkeypatch: pytest.MonkeyPatch, *, archive_value: bool | Exception
) -> None:
    """把 config.settings 单例换成只带 research.challenge_archive_mode 的桩。"""

    import config.settings as settings_mod

    class _StubResearch:
        challenge_archive_mode: bool = False

    class _StubConfig:
        research: Any = _StubResearch()

    class _StubSettings:
        def __init__(self) -> None:
            self._config: Any = None

        @property
        def config(self) -> Any:
            if isinstance(archive_value, Exception):
                raise archive_value
            _StubResearch.challenge_archive_mode = bool(archive_value)
            return _StubConfig()

    monkeypatch.setattr(settings_mod, "_settings", _StubSettings())
    # pytest 下开关恒不读 config（测试隔离）；这里显式移除该标记来覆盖
    # config 回落分支本身。
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


def test_archive_mode_falls_back_to_operator_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_config_stub(monkeypatch, archive_value=True)
    assert challenge_archive_mode_enabled() is True

    _install_config_stub(monkeypatch, archive_value=False)
    assert challenge_archive_mode_enabled() is False


def test_archive_mode_config_failure_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_config_stub(monkeypatch, archive_value=RuntimeError("config broken"))
    assert challenge_archive_mode_enabled() is False


def test_archive_mode_pytest_never_reads_live_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pytest 下 config 回落必须恒 False：真机活配置不得污染测试行为。"""

    import config.settings as settings_mod

    class _Exploding:
        def __getattribute__(self, name: str) -> Any:
            raise AssertionError("archive mode must not read live config under pytest")

    class _StubSettings:
        config = _Exploding()

    monkeypatch.setattr(settings_mod, "_settings", _StubSettings())
    assert challenge_archive_mode_enabled() is False


# ---------------------------------------------------------------------------
# auto-advance kill switch 覆盖封存
# ---------------------------------------------------------------------------


def test_kill_switch_covers_archive_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: True)
    assert automation_policy_executor.kill_switch_enabled() is True

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: False)
    assert automation_policy_executor.kill_switch_enabled() is False


def test_kill_switch_env_still_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        automation_policy_executor,
    )

    monkeypatch.setenv("VIBELUTION_AUTO_ADVANCE_DISABLED", "1")
    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: False)
    assert automation_policy_executor.kill_switch_enabled() is True


def test_auto_advance_sweep_gated_by_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """closure sweep 归 auto-advance 语义：kill switch（含封存）下不扫。"""

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

    # 封存开：kill switch 早退，sweep 不执行。
    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: True)
    sweep(None)  # 早退发生在任何 self 访问之前，None 作为 self 安全
    assert calls == []

    # 仅 AUTO_ADVANCE_DISABLED（无封存）同样必须拦住这条 auto-advance 路径。
    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: False)
    monkeypatch.setenv("VIBELUTION_AUTO_ADVANCE_DISABLED", "1")
    sweep(None)
    assert calls == []

    # 两者皆关：sweep 正常执行（mock 版，不触碰真实工作区）。
    monkeypatch.delenv("VIBELUTION_AUTO_ADVANCE_DISABLED", raising=False)
    sweep(None)
    assert calls == ["sweep"]


# ---------------------------------------------------------------------------
# awaiting-approval reaper
# ---------------------------------------------------------------------------


def test_reaper_disabled_under_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.web.services.team_workflow.research_runtime import reaper

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: True)
    assert reaper.reaper_enabled() is False


def test_reaper_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.web.services.team_workflow.research_runtime import reaper

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: False)
    assert reaper.reaper_enabled() is True

    monkeypatch.setenv("VIBELUTION_AWAITING_APPROVAL_REAPER", "0")
    assert reaper.reaper_enabled() is False


def test_reaper_entry_skips_under_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.web.services.team_workflow.research_runtime import reaper

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: True)
    summary = reaper.reap_awaiting_approval_meetings(respect_throttle=False)
    assert summary["status"] == "skipped"
    assert summary["reason"] == "kill_switch_off"


# ---------------------------------------------------------------------------
# start_production_workflow_runtime
# ---------------------------------------------------------------------------


def test_start_production_runtime_skips_under_archive(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        production_workflow_runtime,
        start_production_workflow_runtime,
        stop_production_workflow_runtime,
    )

    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv(CHALLENGE_ARCHIVE_MODE_ENV, "1")
    stop_production_workflow_runtime()

    assert start_production_workflow_runtime() == "archive_mode"
    assert production_workflow_runtime() is None
    # shutdown 侧对未启动 runtime 幂等。
    stop_production_workflow_runtime()
    assert production_workflow_runtime() is None


def test_start_production_runtime_default_off_starts_normally(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开关默认关：启动路径与历史版本一致（真实构建 + ready）。"""

    from core.web.services.team_workflow.research_runtime.runtime_factory import (
        production_workflow_runtime,
        start_production_workflow_runtime,
        stop_production_workflow_runtime,
    )

    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    assert challenge_archive_mode_enabled() is False
    stop_production_workflow_runtime()

    assert start_production_workflow_runtime() == "ready"
    assert production_workflow_runtime() is not None
    stop_production_workflow_runtime()
    assert production_workflow_runtime() is None


# ---------------------------------------------------------------------------
# outbox pump hypothesis recovery 循环
# ---------------------------------------------------------------------------


class _StubRuntime:
    def __init__(self) -> None:
        self.recovery_calls: list[int] = []

    def run_hypothesis_recovery_once(self, limit: int = 4) -> int:
        self.recovery_calls.append(limit)
        return 0


def test_hypothesis_recovery_loop_skips_under_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime.outbox_pump import (
        WorkflowOutboxPump,
    )

    monkeypatch.setenv(CHALLENGE_ARCHIVE_MODE_ENV, "1")
    pump = WorkflowOutboxPump(workers=1)
    stub = _StubRuntime()
    pump._runtime = stub

    # 封存下循环直接返回：一次恢复都不跑、不阻塞。
    pump._hypothesis_recovery_loop()
    assert stub.recovery_calls == []


def test_hypothesis_recovery_loop_runs_when_not_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from core.web.services.team_workflow.research_runtime.outbox_pump import (
        WorkflowOutboxPump,
    )

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: False)
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
# lifecycle 启动任务门
# ---------------------------------------------------------------------------


class _FakeStartupJobs:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start_thread(self, name: str, fn: Any, **kwargs: Any) -> str:
        self.started.append(name)
        return f"task:{name}"


def test_lifecycle_meeting_recovery_job_skips_under_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web import lifecycle

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: True)
    jobs = _FakeStartupJobs()
    assert lifecycle._start_meeting_driver_recovery_job(jobs) is None
    assert jobs.started == []


def test_lifecycle_meeting_recovery_job_starts_when_not_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web import lifecycle

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: False)
    jobs = _FakeStartupJobs()
    task = lifecycle._start_meeting_driver_recovery_job(jobs)
    assert task == "task:startup-meeting-driver-recovery"
    assert jobs.started == ["startup-meeting-driver-recovery"]


def test_lifecycle_workflow_runtime_job_skips_under_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web import lifecycle

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: True)
    jobs = _FakeStartupJobs()
    assert lifecycle._start_workflow_runtime_job(jobs) is None
    assert jobs.started == []


def test_lifecycle_workflow_runtime_job_starts_when_not_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web import lifecycle

    monkeypatch.setattr(archive_mode, "challenge_archive_mode_enabled", lambda: False)
    jobs = _FakeStartupJobs()
    task = lifecycle._start_workflow_runtime_job(jobs)
    assert task == "task:startup-workflow-runtime"
    assert jobs.started == ["startup-workflow-runtime"]
