from datetime import datetime, timedelta, timezone

import pytest

from core.web.services import cli_agent_task_kernel as task_kernel


@pytest.fixture(autouse=True)
def _isolated_pending_finalizations(monkeypatch):
    monkeypatch.setattr(task_kernel, "_PENDING_FINALIZATIONS", {})


def test_submit_cli_agent_task_locks_one_active_task_per_terminal(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)
    writes = []

    from core.web.services import cli_agent_terminal_service

    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", lambda _session_id, data: writes.append(data) or {})

    terminal = {
        "terminalSessionId": "cli-term-one",
        "adapterId": "mimo_code",
        "label": "MiMo Code",
        "sourceSessionId": "session-1",
        "cwd": str(project_root),
        "mode": "readonly",
        "alive": True,
        "status": "running",
    }

    first = task_kernel.submit_cli_agent_task(
        terminal_session=terminal,
        task="分析当前问题",
        timeout_seconds=60,
        output_limit=8000,
    )
    second = task_kernel.submit_cli_agent_task(
        terminal_session=terminal,
        task="重复分析当前问题",
        timeout_seconds=60,
        output_limit=8000,
    )

    assert first["status"] == "task_sent"
    assert first["internalStatus"] == "sent"
    assert first["semanticStatus"] == "task_sent"
    assert first["code"] == "CLI_AGENT_TASK_SENT"
    assert len(writes) == 1
    assert "分析当前问题" in writes[0]
    assert "VIBELUTION_CLI_DONE:" in writes[0]
    assert "[VIBELUTION_CLI_DONE:" not in writes[0]
    assert second["code"] == "CLI_AGENT_TASK_LOCKED"
    assert second["status"] == "task_locked"
    assert second["terminalSessionId"] == "cli-term-one"


@pytest.mark.parametrize("reader_status", ["running", "completed", "failed"])
def test_send_ack_preserves_task_state_written_by_terminal_reader(monkeypatch, tmp_path, reader_status):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)
    finalized = []
    monkeypatch.setattr(task_kernel, "_finalize_task_result", lambda state, **_kwargs: finalized.append(dict(state)))

    from core.web.services import cli_agent_terminal_service

    terminal = {
        "terminalSessionId": "cli-term-fast-reader",
        "adapterId": "mimo_code",
        "cwd": str(project_root),
        "mode": "readonly",
        "alive": True,
        "status": "running",
    }

    def write_with_reader_progress(_session_id, _data):
        if reader_status == "failed":
            task_kernel.mark_terminal_closed(terminal, status="exited")
        else:
            state = task_kernel._active_task_for_terminal(terminal["terminalSessionId"])
            output = "正在检查项目"
            if reader_status == "completed":
                output += "\n" + state["completionMarker"]
            task_kernel.ingest_terminal_output(terminal, output)
        return {}

    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", write_with_reader_progress)
    result = task_kernel.submit_cli_agent_task(
        terminal_session=terminal, task="检查项目", timeout_seconds=60, output_limit=8000,
    )

    assert result["status"] == reader_status
    assert result["internalStatus"] == reader_status
    assert task_kernel._read_task_state(result["taskId"])["status"] == reader_status
    if reader_status != "running":
        assert result["completedAt"]
        assert len(finalized) == 1
        assert not task_kernel._active_task_for_terminal(terminal["terminalSessionId"])
        assert result["code"] == ("CLI_AGENT_TASK_COMPLETED" if reader_status == "completed" else "CLI_AGENT_TERMINAL_CLOSED")


def test_terminal_output_completion_returns_semantic_segments(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)
    delivered = []

    from core.web.services import cli_agent_terminal_service, session_service

    writes = []
    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", lambda _session_id, data: writes.append(data) or {})
    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", lambda session_id, **kwargs: delivered.append((session_id, kwargs)))
    terminal = {
        "terminalSessionId": "cli-term-two",
        "adapterId": "mimo_code",
        "label": "MiMo Code",
        "sourceSessionId": "session-1",
        "cwd": str(project_root),
        "mode": "readonly",
        "alive": True,
        "status": "running",
    }
    first = task_kernel.submit_cli_agent_task(
        terminal_session=terminal,
        task="跑测试",
        timeout_seconds=60,
        output_limit=8000,
    )

    marker = task_kernel._read_task_state(first["taskId"])["completionMarker"]
    task_kernel.ingest_terminal_output(
        {
            **terminal,
            "cliRunId": "cli-run-two",
            "screenText": "Thought: checking\n\nAnswer: 已完成，测试通过\n" + marker,
        },
        "\x1b[?2026hThought: checking\n\nAnswer: 已完成，测试通过\n" + marker + "\x1b[?2026l",
    )

    assert delivered
    session_id, payload = delivered[0]
    result = payload["task_result"]
    assert session_id == "session-1"
    assert result["status"] == "completed"
    assert result["code"] == "CLI_AGENT_TASK_COMPLETED"
    assert [segment["kind"] for segment in result["resultSegments"]] == ["thought", "answer"]
    assert "[VIBELUTION_CLI_DONE:" not in result["stdoutPreview"]
    assert "\x1b" not in result["stdoutPreview"]


def test_mimo_prompt_echo_completion_text_does_not_complete_task(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)
    delivered = []
    writes = []

    from core.web.services import cli_agent_terminal_service, session_service

    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", lambda _session_id, data: writes.append(data) or {})
    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", lambda session_id, **kwargs: delivered.append((session_id, kwargs)))
    terminal = {
        "terminalSessionId": "cli-term-three",
        "adapterId": "mimo_code",
        "label": "MiMo Code",
        "sourceSessionId": "session-1",
        "cwd": str(project_root),
        "mode": "readonly",
        "alive": True,
        "status": "running",
    }
    result = task_kernel.submit_cli_agent_task(
        terminal_session=terminal,
        task="最后给出结论：拆分是否已经完成",
        timeout_seconds=60,
        output_limit=8000,
    )

    task_kernel.ingest_terminal_output(
        {**terminal, "screenText": "用户任务：最后给出结论：拆分是否已经完成\n正在分析..."},
        writes[0],
    )

    state = task_kernel._read_task_state(result["taskId"])
    assert delivered == []
    assert state["status"] == "running"
    assert state.get("completionReason") is None


@pytest.fixture
def codex_task(monkeypatch, tmp_path):
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", tmp_path / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)
    delivered = []
    writes = []
    from core.web.services import cli_agent_terminal_service, session_service

    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", lambda _session_id, data: writes.append(data) or {})
    monkeypatch.setattr(session_service, "append_cli_agent_task_result_event", lambda session_id, **kwargs: delivered.append((session_id, kwargs)))
    terminal = {
        "terminalSessionId": "cli-term-codex-marker",
        "adapterId": "codex_code",
        "screenText": "OpenAI Codex",
        "sourceSessionId": "session-1",
        "alive": True,
        "status": "running",
    }
    def submit(task):
        result = task_kernel.submit_cli_agent_task(
            terminal_session=terminal, task=task, timeout_seconds=60, output_limit=8000,
        )
        return terminal, result, writes, delivered

    return submit


def test_codex_split_prompt_echo_and_working_output_wait_for_own_marker(codex_task):
    terminal, result, writes, delivered = codex_task("Explain why previous run failed\r\nand produce a recommendation")
    assert len(writes) == 1
    assert writes[0].startswith("\x1b[200~Explain why previous run failed\nand produce a recommendation\n\n")
    assert writes[0].endswith("\x1b[201~\r")
    assert writes[0].count("\r") == 1
    for chunk in ("› Explain why previous run failed", " and produce a recommendation\r\n", "OpenAI Codex\r\nWorking\r\ncompleted\r\n"):
        task_kernel.ingest_terminal_output(terminal, chunk)
        assert task_kernel._read_task_state(result["taskId"])["status"] == "running"
        assert delivered == []
    state = task_kernel._read_task_state(result["taskId"])
    assert state["completionMarker"]
    assert state["completionMarker"] not in writes[0]


@pytest.mark.parametrize("task,answer", [
    ("Reply exactly completed", "completed"),
    ("completed", "completed"),
    ("Inspect the source", "Answer: You asked me to Inspect the source. The analysis is completed."),
])
def test_codex_own_marker_completes_once_across_chunks_and_preserves_answer(codex_task, task, answer):
    terminal, result, writes, delivered = codex_task(task)
    state = task_kernel._read_task_state(result["taskId"])
    marker = state["completionMarker"]
    assert marker
    task_kernel.ingest_terminal_output(terminal, answer + "\r\n")
    assert task_kernel._read_task_state(result["taskId"])["status"] == "running"
    task_kernel.ingest_terminal_output(terminal, marker[:len(marker) // 2])
    assert delivered == []
    task_kernel.ingest_terminal_output(terminal, marker[len(marker) // 2:] + "\r\n")
    task_kernel.ingest_terminal_output(terminal, marker + "\r\n")
    assert task_kernel._read_task_state(result["taskId"])["status"] == "completed"
    assert len(delivered) == 1
    completed = delivered[0][1]["task_result"]
    assert answer in completed["stdoutPreview"]
    assert marker not in completed["stdoutPreview"]


@pytest.mark.parametrize("marker", ["", "[VIBELUTION_CLI_DONE:task-own]"])
@pytest.mark.parametrize("output", ["OpenAI Codex\n› Inspect the source", "Working", "completed", "failed"])
def test_codex_current_and_legacy_tasks_never_idle_complete(marker, output):
    task_state = {
        "adapterId": "codex_code", "status": "running", "completionMarker": marker,
        "task": "Inspect the source", "sentInput": "Inspect the source\r\n", "output": output,
        "createdAt": "1970-01-01T00:00:01+00:00", "lastOutputAt": "1970-01-01T00:00:01+00:00",
        "timeoutSeconds": 60,
    }
    assert task_kernel._task_timeout_or_idle_status(task_state, now=31.0) == ""
    assert task_kernel._task_timeout_or_idle_status(task_state, now=61.0) == "timeout"


def test_codex_legacy_task_without_marker_still_fails_on_terminal_exit(codex_task):
    terminal, result, writes, delivered = codex_task("Inspect the source")
    state = task_kernel._read_task_state(result["taskId"])
    state["completionMarker"] = ""
    task_kernel._write_task_state(state)
    task_kernel.ingest_terminal_output(terminal, "completed\r\n")
    assert delivered == []

    task_kernel.mark_terminal_closed(terminal, status="exited")

    state = task_kernel._read_task_state(result["taskId"])
    assert state["status"] == "failed"
    assert state["code"] == "CLI_AGENT_TERMINAL_CLOSED"
    assert len(delivered) == 1


def test_mimo_marker_protocol_idle_completes_non_echo_output_without_marker(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")

    old_epoch_iso = "1970-01-01T00:00:01+00:00"
    task_state = {
        "adapterId": "mimo_code",
        "status": "running",
        "task": "分析原因",
        "sentInput": "分析原因\r\n",
        "output": "Answer: 已分析完成，没有结束标记",
        "createdAt": old_epoch_iso,
        "lastOutputAt": old_epoch_iso,
        "timeoutSeconds": 3600,
    }

    assert task_kernel._task_timeout_or_idle_status(task_state, now=31.0) == "completed"


def test_mimo_marker_protocol_does_not_idle_complete_prompt_echo(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")

    old_epoch_iso = "1970-01-01T00:00:01+00:00"
    sent_input = "分析原因\n\n完成本任务后，请在最终回复最后单独输出结束标记。"
    task_state = {
        "adapterId": "mimo_code",
        "status": "running",
        "task": "分析原因",
        "sentInput": sent_input,
        "output": sent_input,
        "createdAt": old_epoch_iso,
        "lastOutputAt": old_epoch_iso,
        "timeoutSeconds": 3600,
    }

    assert task_kernel._task_timeout_or_idle_status(task_state, now=31.0) == ""


def test_task_timeout_or_idle_status_reports_timeout_when_elapsed_exceeds_limit(monkeypatch, tmp_path):
    task_state = {
        "adapterId": "codex_code",
        "status": "running",
        "output": "",
        "createdAt": "2026-06-14T10:00:00+00:00",
        "timeoutSeconds": 5,
    }

    assert task_kernel._task_timeout_or_idle_status(task_state, now=1781431400.0) == "timeout"


def test_task_timeout_or_idle_status_reports_completed_after_idle_for_non_marker_protocol(monkeypatch, tmp_path):
    base = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)
    created_at = base.isoformat()
    task_state = {
        "adapterId": "claude_code",
        "status": "running",
        "output": "Answer: 正在持续分析中",
        "createdAt": created_at,
        "lastOutputAt": (base + timedelta(seconds=10)).isoformat(),
        "timeoutSeconds": 3600,
    }

    assert task_kernel._task_timeout_or_idle_status(task_state, now=(base + timedelta(seconds=50)).timestamp()) == "completed"


def test_task_timeout_or_idle_status_with_epoch_zero_timestamp_still_completes_after_idle(monkeypatch, tmp_path):
    task_state = {
        "adapterId": "claude_code",
        "status": "running",
        "output": "Answer: 任务继续输出中",
        "createdAt": "1970-01-01T00:00:00+00:00",
        "lastOutputAt": "1970-01-01T00:00:10+00:00",
        "timeoutSeconds": 3600,
    }

    assert task_kernel._task_timeout_or_idle_status(task_state, now=50.0) == "completed"


def test_submit_cli_agent_task_send_failure_fails_task_and_returns_error_like_result(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)

    from core.web.services import cli_agent_terminal_service

    def failing_write(*_args, **_kwargs):
        raise RuntimeError("terminal pipe closed")

    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", failing_write)

    terminal = {
        "terminalSessionId": "cli-term-fail",
        "adapterId": "mimo_code",
        "label": "MiMo Code",
        "sourceSessionId": "session-1",
        "cwd": str(project_root),
        "mode": "readonly",
        "alive": True,
        "status": "running",
    }

    result = task_kernel.submit_cli_agent_task(
        terminal_session=terminal,
        task="请尝试写一个函数",
        timeout_seconds=60,
        output_limit=8000,
    )

    assert result["status"] == "failed"
    assert result["code"] == "CLI_AGENT_TASK_SEND_FAILED"
    assert result["internalStatus"] == "failed"
    assert result["semanticStatus"] == "failed"
    assert result["timedOut"] is False


def test_submit_cli_agent_task_rejects_stale_terminal_without_writing(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)

    from core.web.services import cli_agent_terminal_service

    def unexpected_write(*_args, **_kwargs):
        raise AssertionError("stale terminal must not receive task input")

    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", unexpected_write)

    result = task_kernel.submit_cli_agent_task(
        terminal_session={
            "terminalSessionId": "cli-term-stale",
            "adapterId": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-1",
            "cwd": str(project_root),
            "mode": "readonly",
            "alive": False,
            "status": "stale",
            "interactionState": "resumable",
            "canInput": False,
            "canResume": True,
            "resumeAction": "resume_session",
            "stateReason": "backend_startup",
        },
        task="继续分析",
        timeout_seconds=60,
        output_limit=8000,
    )

    assert result["status"] == "failed"
    assert result["semanticStatus"] == "failed"
    assert result["internalStatus"] == "terminal_unavailable"
    assert result["code"] == "CLI_AGENT_TERMINAL_NOT_RUNNING"
    assert result["terminalSessionId"] == "cli-term-stale"
    assert result["terminalStatus"] == "stale"
    assert result["terminalAlive"] is False
    assert result["canInput"] is False
    assert result["canResume"] is True
    assert result["resumeAction"] == "resume_session"
    assert result["taskId"] == ""
    assert result["resultSource"] == "terminal_state"
    assert "需要先恢复" in result["stdoutPreview"]


def test_submit_cli_agent_task_reports_user_closed_terminal_as_closed(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)

    result = task_kernel.submit_cli_agent_task(
        terminal_session={
            "terminalSessionId": "cli-term-closed",
            "adapterId": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-1",
            "cwd": str(project_root),
            "mode": "readonly",
            "alive": False,
            "status": "closed",
            "userClosed": True,
            "interactionState": "closed",
            "canInput": False,
            "canResume": False,
            "stateReason": "user_closed",
        },
        task="继续分析",
        timeout_seconds=60,
        output_limit=8000,
    )

    assert result["status"] == "closed"
    assert result["semanticStatus"] == "closed"
    assert result["code"] == "CLI_AGENT_TERMINAL_CLOSED"
    assert result["terminalStatus"] == "closed"
    assert result["canResume"] is False
    assert "已关闭" in result["message"]


def test_mark_terminal_closed_marks_active_task_as_failed_and_completes_to_session(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)

    from core.web.services import cli_agent_terminal_service, session_service

    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", lambda _session_id, data: {})

    delivered = []
    monkeypatch.setattr(
        session_service,
        "append_cli_agent_task_result_event",
        lambda session_id, **kwargs: delivered.append((session_id, kwargs)),
    )

    terminal = {
        "terminalSessionId": "cli-term-close",
        "adapterId": "codex_code",
        "label": "Codex Code",
        "sourceSessionId": "session-1",
        "cwd": str(project_root),
        "mode": "readonly",
        "alive": True,
        "status": "running",
    }
    first = task_kernel.submit_cli_agent_task(
        terminal_session=terminal,
        task="执行一项需要长时间运行的任务",
        timeout_seconds=600,
        output_limit=8000,
    )

    task_kernel.mark_terminal_closed({"terminalSessionId": "cli-term-close"}, status="exited")

    state = task_kernel._read_task_state(first["taskId"])
    assert state["status"] == "failed"
    assert state["code"] == "CLI_AGENT_TERMINAL_CLOSED"
    assert state["completionReason"] == "exited"
    assert delivered
    assert delivered[0][0] == "session-1"
    payload = delivered[0][1]["task_result"]
    assert payload["status"] == "failed"
    assert payload["code"] == "CLI_AGENT_TERMINAL_CLOSED"


def test_finalize_result_drops_sealed_task_wake_with_audit(monkeypatch, tmp_path):
    from core.web.services import cli_agent_service, runtime_task_registry, session_service

    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", tmp_path / "rt-tasks")
    store = task_kernel._task_store()
    events: list[dict] = []
    wakes: list[str] = []
    monkeypatch.setattr(cli_agent_service, "_record_event", lambda event, **fields: events.append({"event": event, **fields}))
    monkeypatch.setattr(
        session_service,
        "append_cli_agent_task_result_event",
        lambda session_id, **kwargs: wakes.append(session_id) or {"id": session_id},
    )

    def _register(task_id):
        return store.register_task(
            runtime_task_registry.new_snapshot(
                kind=runtime_task_registry.KIND_CLI_AGENT,
                task_id=task_id,
                status="running",
                source_session_id="session-x",
            )
        )

    def _finalize(task_id, *, sealed):
        if sealed:
            store.seal_and_request_stop(task_id, reason="parent_turn_cancelled")
        task_state = dict(store.load_state(task_id))
        task_state["status"] = "completed"
        task_state["completionReason"] = "protocol_pattern"
        task_kernel._finalize_task_result(task_state, reason="protocol_pattern")
        return store.load_state(task_id)

    # Sealed by the cascade: the wake never fires, the drop is audited.
    _register("task-seal-final-1")
    sealed_state = _finalize("task-seal-final-1", sealed=True)
    assert wakes == []
    assert events[-1]["event"] == "cli_agent.task.result_fenced"
    assert events[-1]["outcome"] == "sealed_dropped"
    assert sealed_state["notificationDropDecision"] == "dropped"
    assert sealed_state["notificationDropReason"] == "sealed"

    # Unsealed: fencing passes and the completion wake fires as before.
    _register("task-seal-final-2")
    open_state = _finalize("task-seal-final-2", sealed=False)
    assert wakes == ["session-x"]
    assert events[-1]["event"] == "cli_agent.task.result_ready"
    assert "notificationDropDecision" not in open_state

    # Stacking: fencing drops first, the sealed channel is not even reached.
    _register("task-seal-final-3")
    # Rewind happened after registration: the reader now reports a newer
    # generation, so fencing drops before the sealed channel is reached.
    store._branch_generation_reader = lambda _session_id: 42
    fenced_state = _finalize("task-seal-final-3", sealed=True)
    assert wakes == ["session-x"]
    assert events[-1]["event"] == "cli_agent.task.result_fenced"
    assert events[-1]["outcome"] == "fenced_dropped"
    assert fenced_state["fencingReason"] == "stale_branch_generation"


def test_cli_owner_notification_sealing_reports_failure_and_continues(monkeypatch, tmp_path):
    from core.web.services import runtime_task_registry as registry

    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", tmp_path / "actual-cli-tasks")
    store = task_kernel._task_store()
    for name in ("broken", "healthy"):
        store.register_task(registry.new_snapshot(
            kind=registry.KIND_CLI_AGENT, task_id=name, status="running", source_session_id="session-owner",
        ))
    seal = store.seal_and_request_stop

    def sometimes_fail(task_id, **kwargs):
        if task_id == "broken":
            raise OSError("simulated isolated write failure")
        return seal(task_id, **kwargs)

    monkeypatch.setattr(store, "seal_and_request_stop", sometimes_fail)

    report = task_kernel.seal_cli_agent_task_notifications(
        {"session-owner": 2, "": 0}, turn_id="stop-turn", cascaded_from="session-root",
    )

    rows = {row["taskId"]: row for row in report}
    assert rows["broken"]["sealed"] is False
    assert rows["broken"]["error"] == "OSError"
    assert rows["healthy"]["sealed"] is True
    assert rows["healthy"]["cascadeDepth"] == 2
    assert store.load_state("healthy")["notificationSealedByTurnId"] == "stop-turn"
    assert store.load_state("broken")["notificationSealed"] is False


def test_stale_marker_completion_preserves_a_later_parent_seal(codex_task):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    terminal, submitted, writes, delivered = codex_task("Inspect")
    store = task_kernel._task_store()
    completed_copy = dict(store.load_state(submitted["taskId"]))
    completed_copy["output"] = completed_copy["completionMarker"]
    detected = task_kernel.protocols.detect_task_status(
        "codex_code", completed_copy["output"], completion_marker=completed_copy["completionMarker"],
    )
    assert detected == "completed"
    task_kernel._complete_task_state(completed_copy, status=detected, code="CLI_AGENT_TASK_COMPLETED", reason="protocol_pattern")
    copied = threading.Event()
    release = threading.Event()

    def finalize_after_seal():
        copied.set()
        assert release.wait(10)
        task_kernel._finalize_task_result(completed_copy, reason="protocol_pattern")

    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(finalize_after_seal)
        assert copied.wait(10)
        try:
            report = task_kernel.seal_cli_agent_task_notifications(
                {"session-1": 0}, turn_id="stopped-turn", cascaded_from="session-1",
            )
            assert report[0]["sealed"] is True
            sealed = store.load_state(submitted["taskId"])
        finally:
            release.set()
        future.result(timeout=10)

    settled = store.load_state(submitted["taskId"])
    assert settled["status"] == "completed"
    for key in ("notificationSealed", "notificationSealedAt", "notificationSealedReason", "notificationSealedByTurnId", "cascadeStop", "stopInitiator", "stopRequestedAt"):
        assert settled[key] == sealed[key]
    assert settled["notificationDropReason"] == "sealed"
    assert delivered == []


def test_actual_marker_removed_from_active_index_is_sealed_before_finalize(monkeypatch, codex_task):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    terminal, submitted, writes, delivered = codex_task("Inspect")
    store = task_kernel._task_store()
    task_id = submitted["taskId"]
    marker = store.load_state(task_id)["completionMarker"]
    entered = threading.Event()
    release = threading.Event()
    real_finalize = task_kernel._finalize_task_result

    def paused_finalize(state, **kwargs):
        entered.set()
        assert release.wait(10)
        return real_finalize(state, **kwargs)

    monkeypatch.setattr(task_kernel, "_finalize_task_result", paused_finalize)
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(task_kernel.ingest_terminal_output, terminal, marker)
        assert entered.wait(10)
        try:
            assert store.load_state(task_id)["status"] == "completed"
            assert task_id not in store.active_task_ids()
            report = task_kernel.seal_cli_agent_task_notifications(
                {"session-1": 0}, turn_id="stopped-turn", cascaded_from="session-1",
            )
            assert [row["taskId"] for row in report] == [task_id]
            assert store.load_state(task_id)["notificationSealed"] is True
        finally:
            release.set()
        future.result(timeout=10)

    settled = store.load_state(task_id)
    assert settled["notificationDropReason"] == "sealed"
    assert delivered == []
    assert task_id not in task_kernel._PENDING_FINALIZATIONS
    assert task_kernel.seal_cli_agent_task_notifications(
        {"session-1": 0}, turn_id="later-stop", cascaded_from="session-1",
    ) == []
    assert store.load_state(task_id) == settled


@pytest.mark.parametrize("settlement", ["closed", "send_failed", "watchdog"])
def test_each_terminal_settlement_tracks_only_its_pending_callback(monkeypatch, codex_task, settlement):
    from core.web.services import cli_agent_terminal_service

    terminal, submitted, writes, delivered = codex_task("Inspect")
    store = task_kernel._task_store()
    real_finalize = task_kernel._finalize_task_result
    seen = []

    def check_pending_before_finalize(state, **kwargs):
        task_id = state["taskId"]
        assert task_kernel._PENDING_FINALIZATIONS[task_id] == "session-1"
        assert task_id not in store.active_task_ids()
        seen.append(task_id)
        return real_finalize(state, **kwargs)

    monkeypatch.setattr(task_kernel, "_finalize_task_result", check_pending_before_finalize)
    if settlement == "closed":
        task_kernel.mark_terminal_closed(terminal)
    elif settlement == "send_failed":
        def fail_send(*args):
            raise OSError("simulated send failure")
        monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", fail_send)
        task_kernel.submit_cli_agent_task(
            terminal_session={**terminal, "terminalSessionId": "another-terminal"},
            task="Inspect", timeout_seconds=60, output_limit=2000,
        )
    else:
        class EndWatch(Exception):
            pass
        def stop_watch(*args):
            raise EndWatch()
        monkeypatch.setattr(task_kernel, "_task_timeout_or_idle_status", lambda *args, **kwargs: "timeout")
        monkeypatch.setattr(task_kernel.time, "sleep", stop_watch)
        with pytest.raises(EndWatch):
            task_kernel._watch_active_tasks()

    assert len(seen) == 1
    assert task_kernel._PENDING_FINALIZATIONS == {}
