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

    assert first["status"] == "sent"
    assert first["code"] == "CLI_AGENT_TASK_SENT"
    assert writes == ["分析当前问题\r\n"]
    assert second["code"] == "CLI_AGENT_TASK_LOCKED"
    assert second["terminalSessionId"] == "cli-term-one"


def test_terminal_output_completion_returns_semantic_segments(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(task_kernel, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(task_kernel, "TASK_STATE_DIR", project_root / ".runtime" / "cli_agents" / "tasks")
    monkeypatch.setattr(task_kernel, "_ensure_watcher_started", lambda: None)
    delivered = []

    from core.web.services import cli_agent_terminal_service, session_service

    monkeypatch.setattr(cli_agent_terminal_service, "write_cli_agent_terminal_input", lambda *_args, **_kwargs: {})
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
    task_kernel.submit_cli_agent_task(
        terminal_session=terminal,
        task="跑测试",
        timeout_seconds=60,
        output_limit=8000,
    )

    task_kernel.ingest_terminal_output(
        {**terminal, "cliRunId": "cli-run-two"},
        "Thought: checking\n\nAnswer: 已完成，测试通过\n",
    )

    assert delivered
    session_id, payload = delivered[0]
    result = payload["task_result"]
    assert session_id == "session-1"
    assert result["status"] == "completed"
    assert result["code"] == "CLI_AGENT_TASK_COMPLETED"
    assert [segment["kind"] for segment in result["resultSegments"]] == ["thought", "answer"]
