from core.web.services import cli_agent_task_kernel as task_kernel


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


def test_mimo_marker_required_protocol_does_not_idle_complete_without_marker(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")

    old_epoch_iso = "2026-06-14T10:00:00+00:00"
    task_state = {
        "adapterId": "mimo_code",
        "status": "running",
        "output": "Answer: 还在执行，没有结束标记",
        "createdAt": old_epoch_iso,
        "lastOutputAt": old_epoch_iso,
        "timeoutSeconds": 3600,
    }

    assert task_kernel._task_timeout_or_idle_status(task_state, now=1781431400.0) == ""
