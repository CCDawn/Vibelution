"""Integration tests: runtime task registry fencing and child-session ledger.

Covers the two acceptance surfaces of the unified runtime task registry that
need real consumers:

1. A CLI Agent task that completes after its source session forked
   (branchGeneration advanced) has its result notification dropped by
   completion fencing, with the audit fields persisted on the task snapshot.
2. A child session created through ``create_child_session`` is registered in
   the registry at creation and reaches a terminal registry status when its
   turn returns to the parent session.
"""

from __future__ import annotations

from core.web.services import cli_agent_service, session_service
from core.web.services import cli_agent_task_kernel as task_kernel
from core.web.services import runtime_task_registry as runtime_tasks
from tests.test_agent_config_workspace_service import (
    _fake_config_workspace,
    _use_tmp_project_root,
    config_service,
)
from tests.test_agent_config_workspace_service import (
    session_service as session_service_module,
)


def _submit_fenced_cli_task(monkeypatch, tmp_path, *, start_generation: int):
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        task_kernel,
        "TASK_STATE_DIR",
        tmp_path / ".runtime" / "cli_agents" / "tasks",
    )
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)
    monkeypatch.setattr(
        session_service,
        "session_branch_generation",
        lambda session_id: start_generation,
    )
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        cli_agent_service,
        "_record_event",
        lambda event, outcome="", fields=None: events.append((event, {"outcome": outcome, **(fields or {})})),
    )
    delivered: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        session_service,
        "append_cli_agent_task_result_event",
        lambda session_id, **kwargs: delivered.append((session_id, kwargs)),
    )

    from core.web.services import cli_agent_terminal_service

    monkeypatch.setattr(
        cli_agent_terminal_service,
        "write_cli_agent_terminal_input",
        lambda _session_id, data: {},
    )

    result = task_kernel.submit_cli_agent_task(
        terminal_session={
            "terminalSessionId": "cli-term-fence",
            "adapterId": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-fence",
            "cwd": str(tmp_path),
            "mode": "readonly",
            "alive": True,
            "status": "running",
        },
        task="分叉前的任务",
        timeout_seconds=60,
        output_limit=8000,
    )
    return result, events, delivered


def test_cli_task_completion_after_session_fork_is_fenced_out(monkeypatch, tmp_path):
    result, events, delivered = _submit_fenced_cli_task(monkeypatch, tmp_path, start_generation=2)

    # The task registered with a mandatory integer stamp from the session.
    state = task_kernel._read_task_state(result["taskId"])
    assert state["branchGeneration"] == 2
    assert state["branchGenerationStampSource"] == "session"

    # Session forked while the CLI task was running: generation advanced.
    monkeypatch.setattr(
        session_service,
        "session_branch_generation",
        lambda session_id: 3,
    )
    marker = state["completionMarker"]
    task_kernel.ingest_terminal_output(
        {
            "terminalSessionId": "cli-term-fence",
            "adapterId": "mimo_code",
            "screenText": f"Answer: 完成\n{marker}",
        },
        f"Answer: 完成\n{marker}\n",
    )

    # The late completion is dropped: no session notification at all.
    assert delivered == []
    fenced = task_kernel._read_task_state(result["taskId"])
    assert fenced["status"] == "completed"
    assert fenced["fencingDecision"] == runtime_tasks.FENCING_DECISION_DROPPED
    assert fenced["fencingReason"] == "stale_branch_generation"
    assert fenced["fencingTaskBranchGeneration"] == 2
    assert fenced["fencingCurrentBranchGeneration"] == 3
    assert any(event == "cli_agent.task.result_fenced" for event, _fields in events)


def test_cli_task_completion_without_fork_still_delivers(monkeypatch, tmp_path):
    result, events, delivered = _submit_fenced_cli_task(monkeypatch, tmp_path, start_generation=1)
    state = task_kernel._read_task_state(result["taskId"])

    marker = state["completionMarker"]
    task_kernel.ingest_terminal_output(
        {
            "terminalSessionId": "cli-term-fence",
            "adapterId": "mimo_code",
            "screenText": f"Answer: 完成\n{marker}",
        },
        f"Answer: 完成\n{marker}\n",
    )

    assert delivered and delivered[0][0] == "session-fence"
    assert delivered[0][1]["task_result"]["status"] == "completed"
    assert delivered[0][1]["task_result"]["branchGeneration"] == 1
    fenced = task_kernel._read_task_state(result["taskId"])
    assert fenced["fencingDecision"] == runtime_tasks.FENCING_DECISION_ALLOWED
    assert any(event == "cli_agent.task.result_ready" for event, _fields in events)


def test_child_session_registers_and_reaches_terminal_in_registry(monkeypatch, tmp_path):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    parent = session_service_module.create_chat_session(title="注册表父会话")
    child_result = session_service_module.create_child_session(
        parent["id"],
        user_request="验证子会话进入注册表",
        task_title="注册表子会话",
        auto_start=False,
        switch_to_child=False,
        source="runtime_task_registry_test",
    )
    child_id = child_result["childSession"]["id"]

    store = runtime_tasks.default_store()
    snapshot = store.get_task(child_id)
    assert snapshot is not None
    assert snapshot["kind"] == runtime_tasks.KIND_CHILD_SESSION
    assert snapshot["status"] == "idle"
    assert snapshot["parentSessionId"] == parent["id"]
    assert snapshot["sourceSessionId"] == parent["id"]
    assert isinstance(snapshot["branchGeneration"], int)
    assert store.active_task_ids() == [child_id]

    queued = session_service_module.notify_parent_session_of_child_return(
        child_id,
        turn_id="turn-registry-1",
    )
    assert queued is not None

    terminal = store.get_task(child_id)
    assert terminal["status"] == "completed"
    assert terminal["terminalReason"] == "child_session_return"
    assert store.active_task_ids() == []
