from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.web.services import research_task_recovery as recovery
from core.web.services import runtime_task_registry as registry


@pytest.fixture
def repair_env(tmp_path, monkeypatch):
    store = registry.RuntimeTaskStore(tmp_path / "runtime")
    monkeypatch.setattr(registry, "default_store", lambda: store)
    events = []
    monkeypatch.setattr(recovery.tasks, "_service", lambda: SimpleNamespace(
        _record_workflow_event=lambda *args, **kwargs: events.append((args, kwargs)),
    ))
    task = {"taskId": "task-1", "sessionId": "session-1", "status": "incomplete",
            "turn": {"turnId": "turn-1"}, "resultRefs": [],
            "failureCode": "task_result_not_recorded", "updatedAt": "2026-10-18T01:00:00Z"}
    monkeypatch.setattr(recovery.tasks, "_read_store", lambda *args: {"tasks": [task]})
    calls = []
    monkeypatch.setattr(recovery.tasks, "reconcile_research_project_agent_task_statuses",
                        lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(recovery.session_service, "load_session_chat_state", lambda *args: {
        "experiment_binding": {"teamId": "team-1", "researchProjectId": "project-1"},
    })
    store.register_task(registry.new_snapshot(
        kind=registry.KIND_RESEARCH_TASK, task_id="task-1", status="running",
        source_session_id="session-1", branch_generation=0,
    ))
    return store, task, calls, events


def test_recovers_legacy_row_after_business_commit_without_guessing_success(repair_env):
    store, task, calls, events = repair_env
    assert recovery.reconcile_registered_research_tasks_once() == {
        "checked": 1, "repaired": 1, "unresolved": 0,
    }
    row = store.get_task("task-1")
    assert row["status"] == "incomplete"
    assert row["failureCode"] == "task_result_not_recorded"
    assert row["sourceTurnId"] == "turn-1"
    assert row["teamId"] == "team-1"
    assert row["completedAt"] == task["updatedAt"]
    assert store.active_task_states() == []
    assert calls == [("team-1", "project-1")]
    assert events
    assert recovery.reconcile_registered_research_tasks_once()["checked"] == 0


@pytest.mark.parametrize("changed", [{"sessionId": "foreign-session"}, {"turn": {"turnId": "other-turn"}}])
def test_mismatched_session_or_turn_cannot_change_registry(repair_env, changed):
    store, task, calls, _ = repair_env
    store.update_task("task-1", lambda row: {**row, "sourceTurnId": "turn-1"})
    task.update(changed)
    result = recovery.reconcile_registered_research_tasks_once()
    assert result["unresolved"] == 1
    assert not calls
    assert store.get_task("task-1")["status"] == "running"


def test_registry_write_failure_is_retried_without_changing_business_verdict(repair_env, monkeypatch):
    store, task, _, events = repair_env
    update = store.update_task

    def fail(*args, **kwargs):
        raise OSError("test disk unavailable")

    monkeypatch.setattr(store, "update_task", fail)
    assert recovery.reconcile_registered_research_tasks_once()["repaired"] == 0
    assert store.get_task("task-1")["status"] == "running"
    assert task["status"] == "incomplete"
    assert events[-1][0][0] == "research_project_agent_task_registry_sync_failed"
    monkeypatch.setattr(store, "update_task", update)
    assert recovery.reconcile_registered_research_tasks_once()["repaired"] == 1


def test_running_task_and_stopped_recovery_do_not_invent_a_terminal_result(repair_env):
    store, task, _, _ = repair_env
    task["status"] = "running"
    task["failureCode"] = ""
    assert recovery.reconcile_registered_research_tasks_once()["repaired"] == 0
    assert store.get_task("task-1")["status"] == "running"
    assert recovery.reconcile_registered_research_tasks_once(should_stop=lambda: True)["checked"] == 0


def test_archive_mode_never_reconciles_or_writes_registered_research_tasks(repair_env, monkeypatch):
    store, _, calls, events = repair_env
    monkeypatch.setenv("VIBELUTION_CHALLENGE_ARCHIVE_MODE", "1")
    before = store.get_task("task-1")
    assert recovery.reconcile_registered_research_tasks_once(rebuild_index=True)["checked"] == 0
    assert store.get_task("task-1") == before
    assert not calls and not events


def test_stop_received_while_waiting_for_task_lock_prevents_business_reconcile(repair_env, monkeypatch):
    store, _, calls, events = repair_env
    stopped = False

    class StopBeforeAcquire:
        def __enter__(self):
            nonlocal stopped
            stopped = True

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(recovery.tasks, "_TASK_LOCK", StopBeforeAcquire())
    recovery.reconcile_registered_research_tasks_once(should_stop=lambda: stopped)
    assert not calls and not events
    assert store.get_task("task-1")["status"] == "running"


def test_recovery_waits_for_session_startup_and_repeats_without_new_processes(monkeypatch):
    calls = []
    monkeypatch.setattr(recovery, "reconcile_registered_research_tasks_once",
                        lambda **kwargs: calls.append("repair"))

    class Jobs:
        def should_stop(self):
            return len(calls) >= 2

        async def run_sync(self, name, callback, **kwargs):
            return callback(**kwargs)

    async def exercise():
        ready = asyncio.get_running_loop().create_future()
        worker = asyncio.create_task(recovery.run_research_task_recovery(
            startup_jobs=Jobs(), session_recovery=ready, interval_seconds=0.01,
        ))
        await asyncio.sleep(0)
        assert calls == []
        ready.set_result(None)
        await asyncio.wait_for(worker, timeout=1)

    asyncio.run(exercise())
    assert calls == ["repair", "repair"]


def test_lifespan_recovery_skips_live_stores_during_unrelated_pytest(monkeypatch):
    from core.web import lifecycle

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "isolated")
    assert lifecycle._start_research_task_recovery_job(None, None) is None


def _recovery_env_with_business_task(
    tmp_path, monkeypatch, task: dict, *, binding: bool = True,
):
    """repair_env 的变体工厂：可配置账本任务与绑定可达性，并隔离兜底扫描根。"""

    store = registry.RuntimeTaskStore(tmp_path / "runtime-closeout")
    monkeypatch.setattr(registry, "default_store", lambda: store)
    events = []
    monkeypatch.setattr(recovery.tasks, "_service", lambda: SimpleNamespace(
        _record_workflow_event=lambda *args, **kwargs: events.append((args, kwargs)),
    ))
    monkeypatch.setattr(recovery.tasks, "_read_store", lambda *args: {"tasks": [task]})
    calls = []
    monkeypatch.setattr(recovery.tasks, "reconcile_research_project_agent_task_statuses",
                        lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(recovery.session_service, "load_session_chat_state", lambda *args: (
        {"experiment_binding": {"teamId": "team-1", "researchProjectId": "project-1"}}
        if binding else {}
    ))
    # 兜底扫描根指向空目录：绑定缺失时不得触碰真实 workspace。
    monkeypatch.setattr(recovery, "_research_task_store_scan_root",
                        lambda: tmp_path / "empty-scan-root")
    store.register_task(registry.new_snapshot(
        kind=registry.KIND_RESEARCH_TASK, task_id=task["taskId"], status="running",
        source_session_id=task["sessionId"], branch_generation=0,
    ))
    return store, calls, events


def test_stock_zombie_running_row_with_completed_ledger_closes_in_one_pass(
    tmp_path, monkeypatch,
):
    """场景 b：注册表 active + 账本已 completed 的存量僵尸，一次调用即收口。"""
    task = {"taskId": "task-done", "sessionId": "session-1", "status": "completed",
            "turn": {"turnId": "turn-1", "status": "completed"},
            "resultRefs": ["plan-9"], "failureCode": "",
            "updatedAt": "2026-10-18T01:00:00Z"}
    store, calls, events = _recovery_env_with_business_task(tmp_path, monkeypatch, task)

    assert recovery.reconcile_registered_research_tasks_once() == {
        "checked": 1, "repaired": 1, "unresolved": 0,
    }

    row = store.get_task("task-done")
    assert row["status"] == "completed"
    assert row["completedAt"] == task["updatedAt"]
    assert row["teamId"] == "team-1"
    assert store.active_task_states() == []
    # 收口发生在 session reconcile 之前，无需触碰 Session 真相。
    assert calls == []
    assert any(e[0][0] == "research_project_agent_task_registry_recovered" for e in events)


def test_unresolved_row_past_grace_is_marked_stale(tmp_path, monkeypatch):
    """场景 c：反查不到且行龄超过宽限期的僵尸行按 stale 收口。"""
    task = {"taskId": "task-zombie", "sessionId": "session-x", "status": "running",
            "turn": {"turnId": "turn-x"}, "resultRefs": [], "failureCode": "",
            "updatedAt": "2026-10-18T01:00:00Z"}
    store, calls, events = _recovery_env_with_business_task(
        tmp_path, monkeypatch, task, binding=False,
    )
    stale_stamp = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    store.update_task("task-zombie", lambda row: {**row, "updatedAt": stale_stamp})

    result = recovery.reconcile_registered_research_tasks_once()

    assert result["unresolved"] == 1
    assert result["repaired"] == 1
    row = store.get_task("task-zombie")
    assert row["status"] == "stale"
    assert row["terminalReason"] == "registry_stale_reconcile"
    assert store.active_task_states() == []
    assert calls == []


def test_unresolved_young_row_stays_running_and_leaves_warning_log(
    tmp_path, monkeypatch, caplog,
):
    """场景 d + e：反查不到但未超龄的行保持不动，且不再无声吞掉。"""
    task = {"taskId": "task-young", "sessionId": "session-y", "status": "running",
            "turn": {"turnId": "turn-y"}, "resultRefs": [], "failureCode": "",
            "updatedAt": "2026-10-18T01:00:00Z"}
    store, calls, _ = _recovery_env_with_business_task(
        tmp_path, monkeypatch, task, binding=False,
    )

    with caplog.at_level(logging.WARNING):
        result = recovery.reconcile_registered_research_tasks_once()

    assert result == {"checked": 0, "repaired": 0, "unresolved": 1}
    row = store.get_task("task-young")
    assert row["status"] == "running"
    assert store.active_task_states() != []
    assert calls == []
    warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING and "task-young" in record.getMessage()
    ]
    assert warnings, "unresolved 行必须留下带 taskId 的 warning 日志"


def test_workspace_scan_fallback_locates_ledger_when_binding_missing(tmp_path, monkeypatch):
    """绑定缺失时按 taskId 兜底扫描各团队账本（含 legacy 布局）并完成收口。"""
    teams_root = tmp_path / "teams"
    formal_workspace = (
        teams_root / "team-scan" / "research_projects" / "project-scan" / "workspace"
    )
    formal_workspace.mkdir(parents=True)
    (formal_workspace / "research_project_agent_tasks.json").write_text(
        json.dumps({"tasks": [
            {"taskId": "task-scan", "sessionId": "session-s1", "status": "completed",
             "turn": {"turnId": "turn-s1", "status": "completed"},
             "resultRefs": [], "failureCode": "", "updatedAt": "2026-10-18T01:00:00Z"},
        ]}),
        encoding="utf-8",
    )
    legacy_team_root = teams_root / "team-legacy"
    legacy_team_root.mkdir(parents=True)
    (legacy_team_root / "research_project_agent_tasks.json").write_text(
        json.dumps({"tasks": [
            {"taskId": "task-legacy", "sessionId": "session-s2", "status": "failed",
             "turn": {"turnId": "turn-s2", "status": "failed"},
             "resultRefs": [], "failureCode": "", "updatedAt": "2026-10-18T01:00:00Z"},
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(recovery, "_research_task_store_scan_root", lambda: teams_root)
    store = registry.RuntimeTaskStore(tmp_path / "runtime-scan")
    monkeypatch.setattr(registry, "default_store", lambda: store)
    events = []
    monkeypatch.setattr(recovery.tasks, "_service", lambda: SimpleNamespace(
        _record_workflow_event=lambda *args, **kwargs: events.append((args, kwargs)),
    ))
    monkeypatch.setattr(recovery.tasks, "_read_store",
                        lambda *args: pytest.fail("绑定缺失时应走扫描而非盲读固定账本"))
    monkeypatch.setattr(recovery.session_service, "load_session_chat_state", lambda *args: {})
    for task_id, session_id in (("task-scan", "session-s1"), ("task-legacy", "session-s2")):
        store.register_task(registry.new_snapshot(
            kind=registry.KIND_RESEARCH_TASK, task_id=task_id, status="running",
            source_session_id=session_id, branch_generation=0,
        ))

    assert recovery.reconcile_registered_research_tasks_once() == {
        "checked": 2, "repaired": 2, "unresolved": 0,
    }

    assert store.get_task("task-scan")["status"] == "completed"
    assert store.get_task("task-scan")["teamId"] == "team-scan"
    assert store.get_task("task-legacy")["status"] == "failed"
    assert store.get_task("task-legacy")["researchProjectId"] == "legacy-default"
    assert store.active_task_states() == []


def test_stale_grace_env_override_and_parse_fallback(monkeypatch):
    """宽限期阈值：环境变量可覆盖，解析失败或非正值回退默认 24h。"""
    now = datetime.now(timezone.utc)
    half_hour_old = {"updatedAt": (now - timedelta(minutes=30)).isoformat()}
    two_hours_old = {"updatedAt": (now - timedelta(hours=2)).isoformat()}
    day_old = {"updatedAt": (now - timedelta(hours=25)).isoformat()}

    monkeypatch.setenv(recovery.STALE_GRACE_ENV_VAR, "1")
    assert recovery._row_exceeds_stale_grace(two_hours_old) is True
    assert recovery._row_exceeds_stale_grace(half_hour_old) is False

    monkeypatch.setenv(recovery.STALE_GRACE_ENV_VAR, "not-a-number")
    assert recovery._row_exceeds_stale_grace(two_hours_old) is False
    assert recovery._row_exceeds_stale_grace(day_old) is True

    monkeypatch.setenv(recovery.STALE_GRACE_ENV_VAR, "0")
    assert recovery._row_exceeds_stale_grace(day_old) is True
    assert recovery._row_exceeds_stale_grace(half_hour_old) is False

    monkeypatch.delenv(recovery.STALE_GRACE_ENV_VAR, raising=False)
    assert recovery._row_exceeds_stale_grace(day_old) is True
    assert recovery._row_exceeds_stale_grace(two_hours_old) is False
    # 时间戳全坏时保守视为未超龄。
    assert recovery._row_exceeds_stale_grace({"updatedAt": "garbage"}) is False
