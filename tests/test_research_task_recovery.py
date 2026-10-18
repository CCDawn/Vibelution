from __future__ import annotations

import asyncio
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
