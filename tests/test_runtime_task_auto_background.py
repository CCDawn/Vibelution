"""Unit tests for the runtime task auto-background sweeper (P2-b).

Covers the acceptance surfaces of the timeout-to-background mechanism:

1. A task past the configured threshold is stamped backgrounded once and its
   source session receives the "still running in the background" notice.
2. Tasks that finish before the threshold are left completely untouched.
3. The conservative guard refuses stop-requested, never-started and
   explicitly-disabled tasks and writes a one-shot audit stamp.
4. The notice rides the existing queued-turn channel and is fenced by the
   task's branchGeneration, so a forked session drops it like any completion
   notice.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from core.web.services import runtime_task_auto_background as auto_background
from core.web.services import runtime_task_registry as registry


ENV_NAME = auto_background.AUTO_BACKGROUND_ENV_VAR


def _store(tmp_path, *, generations=None):
    def reader(session_id: str):
        if generations is None:
            return 0
        return generations.get(session_id)

    return registry.RuntimeTaskStore(tmp_path / "runtime_tasks", branch_generation_reader=reader)


def _register_cli_task(
    store,
    task_id: str,
    *,
    status: str = "running",
    source_session_id: str = "session-a",
    age_seconds: float = 0.0,
    **snapshot_kwargs,
):
    snapshot = store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id=task_id,
            status=status,
            source_session_id=source_session_id,
            label="MiMo Code",
            **snapshot_kwargs,
        )
    )
    if age_seconds > 0:
        started = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        started_iso = started.isoformat()

        def _backdate(state):
            state["createdAt"] = started_iso
            state["startedAt"] = started_iso
            return state

        store.update_task(task_id, _backdate)
    return snapshot


def _future_now(seconds: float = 10_000.0) -> float:
    return time.time() + seconds


@pytest.fixture(autouse=True)
def _no_daemon_sweeper(monkeypatch):
    # The register_task hook must never spawn the process-wide daemon from a
    # unit test; the sweeper loop itself is exercised via sweep_runtime_tasks_once.
    monkeypatch.setattr(auto_background, "ensure_auto_background_sweeper", lambda: False)


def test_threshold_parsing_disables_by_default(monkeypatch):
    monkeypatch.delenv(ENV_NAME, raising=False)
    assert auto_background.resolve_threshold_seconds() is None
    monkeypatch.setenv(ENV_NAME, "")
    assert auto_background.resolve_threshold_seconds() is None
    monkeypatch.setenv(ENV_NAME, "not-a-number")
    assert auto_background.resolve_threshold_seconds() is None
    monkeypatch.setenv(ENV_NAME, "0")
    assert auto_background.resolve_threshold_seconds() is None
    monkeypatch.setenv(ENV_NAME, "-3")
    assert auto_background.resolve_threshold_seconds() is None


def test_threshold_parsing_clamps_to_floor(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "30")
    assert auto_background.resolve_threshold_seconds() == 30.0
    monkeypatch.setenv(ENV_NAME, "0.5")
    assert auto_background.resolve_threshold_seconds() == auto_background.MIN_THRESHOLD_SECONDS


def test_sweep_backgrounds_aged_task_and_delivers_notice(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_NAME, "5")
    store = _store(tmp_path, generations={"session-a": 4})
    _register_cli_task(store, "task-bg-1", age_seconds=600)
    captured: list[tuple[str, dict]] = []

    def _deliver(session_id, **kwargs):
        captured.append((session_id, kwargs))
        return {"id": "row-1", "kind": "task_notification", "status": "queued"}

    handled = auto_background.sweep_runtime_tasks_once(
        store, deliver_notice=_deliver, now=_future_now()
    )

    assert [row["taskId"] for row in handled] == ["task-bg-1"]
    assert handled[0]["outcome"] == registry.BACKGROUND_OUTCOME_BACKGROUNDED
    assert handled[0]["noticeStatus"] == "queued"
    state = store.load_state("task-bg-1")
    assert state["status"] == "running"  # task keeps running unchanged
    assert state["backgroundedAt"]
    assert state["backgroundedReason"] == "auto_background_timeout"
    assert state["backgroundedNoticeStatus"] == "queued"
    assert state["backgroundedNoticeTarget"] == "session-a"
    assert len(captured) == 1
    session_id, kwargs = captured[0]
    assert session_id == "session-a"
    assert kwargs["kind"] == "task_notification"
    assert kwargs["source_id"] == "runtime-task-backgrounded:task-bg-1"
    assert kwargs["branch_generation"] == 4  # fencing rides the task stamp
    assert kwargs["task_id"] == "task-bg-1"
    assert "后台继续执行" in kwargs["content"]


def test_sweep_is_idempotent_and_notice_fires_once(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_NAME, "5")
    store = _store(tmp_path, generations={"session-a": 1})
    _register_cli_task(store, "task-bg-2", age_seconds=600)
    calls: list[str] = []

    def _deliver(session_id, **kwargs):
        calls.append(kwargs["source_id"])
        return {"id": "row-1", "status": "queued"}

    first = auto_background.sweep_runtime_tasks_once(
        store, deliver_notice=_deliver, now=_future_now()
    )
    stamped_at = store.load_state("task-bg-2")["backgroundedAt"]
    second = auto_background.sweep_runtime_tasks_once(
        store, deliver_notice=_deliver, now=_future_now()
    )

    assert first[0]["outcome"] == registry.BACKGROUND_OUTCOME_BACKGROUNDED
    assert second[0]["outcome"] == registry.BACKGROUND_OUTCOME_ALREADY
    assert len(calls) == 1
    assert store.load_state("task-bg-2")["backgroundedAt"] == stamped_at


def test_sweep_leaves_young_and_terminal_tasks_untouched(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_NAME, "5")
    store = _store(tmp_path, generations={"session-a": 1})
    _register_cli_task(store, "task-young")  # started just now
    _register_cli_task(store, "task-done", status="completed", age_seconds=600)
    calls: list[tuple[str, dict]] = []

    # A near-real clock: the young task is ~2s old (under the 5s threshold),
    # the terminal task is over it but settled, so neither is handled.
    handled = auto_background.sweep_runtime_tasks_once(
        store,
        deliver_notice=lambda session_id, **kwargs: calls.append((session_id, kwargs)) or {},
        now=time.time() + 2.0,
    )

    assert handled == []
    assert store.load_state("task-young").get("backgroundedAt") is None
    assert store.load_state("task-done").get("backgroundedAt") is None
    assert calls == []


def test_sweep_disabled_without_threshold(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV_NAME, raising=False)
    store = _store(tmp_path)
    _register_cli_task(store, "task-off", age_seconds=600)
    calls: list[tuple[str, dict]] = []

    handled = auto_background.sweep_runtime_tasks_once(
        store,
        deliver_notice=lambda session_id, **kwargs: calls.append((session_id, kwargs)) or {},
        now=_future_now(),
    )

    assert handled == []
    assert calls == []


def test_request_background_refuses_stop_requested_with_one_shot_audit(tmp_path):
    store = _store(tmp_path)
    _register_cli_task(store, "task-stop")
    store.request_stop("task-stop", "model")

    outcome = store.request_background("task-stop")

    assert outcome == f"refused:{registry.BACKGROUND_REFUSAL_STOP_REQUESTED}"
    refused = store.load_state("task-stop")
    assert refused["backgroundingRefusedReason"] == registry.BACKGROUND_REFUSAL_STOP_REQUESTED
    assert refused["backgroundingRefusedAt"]
    assert refused.get("backgroundedAt") is None
    store.request_background("task-stop")
    again = store.load_state("task-stop")
    assert again["backgroundingRefusedAt"] == refused["backgroundingRefusedAt"]
    assert again["updatedAt"] == refused["updatedAt"]


def test_request_background_refuses_idle_child_session(tmp_path):
    store = _store(tmp_path)
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CHILD_SESSION,
            task_id="child-idle",
            status="idle",
            source_session_id="parent-a",
        )
    )

    outcome = store.request_background("child-idle")

    assert outcome == f"refused:{registry.BACKGROUND_REFUSAL_NOT_STARTED}"
    assert (
        store.load_state("child-idle")["backgroundingRefusedReason"]
        == registry.BACKGROUND_REFUSAL_NOT_STARTED
    )


def test_request_background_refuses_disabled_task(tmp_path):
    store = _store(tmp_path)
    _register_cli_task(store, "task-optout", backgrounding_disabled=True)

    outcome = store.request_background("task-optout")

    assert outcome == f"refused:{registry.BACKGROUND_REFUSAL_DISABLED_BY_TASK}"
    assert (
        store.load_state("task-optout")["backgroundingRefusedReason"]
        == registry.BACKGROUND_REFUSAL_DISABLED_BY_TASK
    )


def test_request_background_skips_settled_and_unknown_tasks(tmp_path):
    store = _store(tmp_path)
    _register_cli_task(store, "task-settled", status="completed")

    assert store.request_background("task-settled") == registry.BACKGROUND_OUTCOME_SETTLED
    assert store.load_state("task-settled").get("backgroundedAt") is None
    assert store.request_background("task-missing") == registry.BACKGROUND_OUTCOME_UNKNOWN


def test_register_task_hook_pokes_sweeper_only_when_enabled(monkeypatch, tmp_path):
    store = _store(tmp_path)
    pokes: list[bool] = []
    monkeypatch.setattr(
        auto_background, "ensure_auto_background_sweeper", lambda: pokes.append(True) or True
    )
    monkeypatch.delenv(ENV_NAME, raising=False)

    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-hook-1",
            status="running",
        )
    )
    assert pokes == []  # disabled threshold: hook is a no-op

    monkeypatch.setenv(ENV_NAME, "120")
    store.register_task(
        registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT,
            task_id="task-hook-2",
            status="running",
        )
    )
    assert pokes == [True]  # enabled threshold: registration ensures the sweeper


def test_backgrounded_notice_is_fenced_after_session_fork(monkeypatch, tmp_path):
    """A forked session drops the backgrounded notice like completion notices."""

    from core.web.services import session_service
    from tests.test_agent_config_workspace_service import (
        _fake_config_workspace,
        _use_tmp_project_root,
        config_service,
    )
    from tests.test_agent_config_workspace_service import (
        session_service as session_service_module,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    monkeypatch.setenv(ENV_NAME, "5")

    parent = session_service_module.create_chat_session(title="转后台父会话")
    child = session_service_module.create_child_session(
        parent["id"],
        user_request="验证转后台通知分叉拦截",
        task_title="转后台子会话",
        auto_start=False,
        switch_to_child=False,
        source="p2_auto_background_test",
    )
    child_id = child["childSession"]["id"]
    store = registry.default_store()
    started_iso = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()

    def _activate(state):
        state["status"] = "running"
        state["createdAt"] = started_iso
        state["startedAt"] = started_iso
        return state

    store.update_task(child_id, _activate)
    stamp = store.load_state(child_id)["branchGeneration"]

    # Fork the parent: the rewind generation moves past the task's stamp.
    session_service_module.advance_session_branch_generation(parent["id"])

    delivered: list[tuple[str, dict]] = []

    def _deliver(session_id, **kwargs):
        delivered.append((session_id, kwargs))
        return session_service_module.enqueue_session_runtime_notice(session_id, **kwargs)

    handled = auto_background.sweep_runtime_tasks_once(
        store, deliver_notice=_deliver, now=_future_now()
    )

    assert [row["taskId"] for row in handled] == [child_id]
    assert handled[0]["outcome"] == registry.BACKGROUND_OUTCOME_BACKGROUNDED
    assert handled[0]["noticeStatus"] == "dropped:stale_branch"
    assert delivered and delivered[0][0] == parent["id"]
    assert delivered[0][1]["branch_generation"] == stamp
    # The forked queue holds no backgrounded notice row.
    queued = session_service_module.list_session_queued_turns(parent["id"])
    assert not [
        row for row in queued if str(row.get("sourceId") or "").startswith("runtime-task-backgrounded:")
    ]
    state = store.load_state(child_id)
    assert state["backgroundedAt"]
    assert state["backgroundedNoticeStatus"] == "dropped:stale_branch"


def test_backgrounded_notice_reaches_parent_queue_without_fork(monkeypatch, tmp_path):
    from core.web.services import session_service
    from tests.test_agent_config_workspace_service import (
        _fake_config_workspace,
        _use_tmp_project_root,
        config_service,
    )
    from tests.test_agent_config_workspace_service import (
        session_service as session_service_module,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    monkeypatch.setenv(ENV_NAME, "5")

    parent = session_service_module.create_chat_session(title="转后台父会话二")
    child = session_service_module.create_child_session(
        parent["id"],
        user_request="验证转后台通知入队",
        task_title="转后台子会话二",
        auto_start=False,
        switch_to_child=False,
        source="p2_auto_background_test",
    )
    child_id = child["childSession"]["id"]
    store = registry.default_store()
    started_iso = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()

    def _activate(state):
        state["status"] = "running"
        state["createdAt"] = started_iso
        state["startedAt"] = started_iso
        return state

    store.update_task(child_id, _activate)

    handled = auto_background.sweep_runtime_tasks_once(
        store,
        deliver_notice=session_service_module.enqueue_session_runtime_notice,
        now=_future_now(),
    )

    assert handled[0]["noticeStatus"] == "queued"
    queued = session_service_module.list_session_queued_turns(parent["id"])
    matched = [
        row
        for row in queued
        if str(row.get("sourceId") or "") == f"runtime-task-backgrounded:{child_id}"
    ]
    assert len(matched) == 1
    assert matched[0]["kind"] == "task_notification"
    assert "后台继续执行" in matched[0]["content"]
