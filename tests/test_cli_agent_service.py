import subprocess

from core.ui.chat_state import build_chat_state, load_chat_state, save_chat_state
from core.web.services import cli_agent_service as service
from core.web.services import cli_agent_terminal_service as terminal_service
from core.web.services import session_service


def _configure_roots(monkeypatch, tmp_path):
    project_root = tmp_path / "Vibelution"
    project_root.mkdir()
    monkeypatch.setattr(service, "PROJECT_ROOT", project_root)
    user_config = tmp_path / "Documents" / "Vibelution" / "config" / "cli_agents.json"
    monkeypatch.setattr(service, "USER_CLI_AGENT_CONFIG_PATH", user_config)
    monkeypatch.setattr(service, "CLI_AGENT_REGISTRY_PATH", user_config)
    monkeypatch.setattr(service, "RUN_RECORD_DIR", project_root / ".runtime" / "cli_agents" / "runs")
    monkeypatch.setattr(terminal_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(terminal_service, "RUNTIME_ROOT", project_root / ".runtime" / "cli_agents")
    monkeypatch.setattr(terminal_service, "SESSION_STATE_DIR", project_root / ".runtime" / "cli_agents" / "sessions")
    monkeypatch.setattr(terminal_service, "TRANSCRIPT_DIR", project_root / ".runtime" / "cli_agents" / "transcripts")
    terminal_service.shutdown_cli_agent_terminal_sessions()
    terminal_service._RUNTIMES.clear()
    monkeypatch.setattr(service, "record_runtime_scene_event", lambda *args, **kwargs: {"accepted": False})
    return project_root


def _write_fake_mimo_npm_shim(tmp_path):
    npm_dir = tmp_path / "npm"
    cli_script = npm_dir / "node_modules" / "@mimo-ai" / "cli" / "bin" / "mimo"
    cli_script.parent.mkdir(parents=True)
    cli_script.write_text("console.log('mimo')\n", encoding="utf-8")
    cmd_path = npm_dir / "mimo.cmd"
    cmd_path.write_text(
        """
@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0
IF EXIST "%dp0%\\node.exe" (
  SET "_prog=%dp0%\\node.exe"
) ELSE (
  SET "_prog=node"
)
endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\node_modules\\@mimo-ai\\cli\\bin\\mimo" %*
""".strip(),
        encoding="utf-8",
    )
    return cmd_path, cli_script


def test_codex_readonly_uses_exec_with_readonly_sandbox(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    calls = []

    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\codex.exe" if candidate == "codex.exe" else "")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"type":"message"}\n', stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    result = service.run_cli_agent(
        agent_type="codex_code",
        task="Inspect the repository without changing files.",
        cwd=str(project_root),
        mode="readonly",
        timeout=15,
    )

    assert result["status"] == "ok"
    args, kwargs = calls[0]
    assert args[:2] == [r"C:\tools\codex.exe", "exec"]
    assert "--cd" in args
    assert str(project_root) in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("--ask-for-approval") + 1] == "never"
    assert "--json" in args
    assert args[-1] == "Inspect the repository without changing files."
    assert result["commandPreview"][-1].startswith("<task:")
    assert result["commandPreview"][-1] != args[-1]
    assert kwargs["cwd"] == str(project_root)
    assert kwargs["timeout"] == 15
    assert (service.RUN_RECORD_DIR / f"{result['runId']}.json").exists()


def test_mimo_worktree_mode_requires_sibling_worktree(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")

    result = service.run_cli_agent(
        agent_type="mimo_code",
        task="Make a change.",
        cwd=str(project_root),
        mode="worktree",
    )

    assert result["status"] == "error"
    assert result["code"] == "WORKTREE_REQUIRED"


def test_mimo_worktree_mode_builds_dir_and_agent_args(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    worktree = project_root.parent / "Vibelution-worktrees" / "cli-agent-demo"
    worktree.mkdir(parents=True)
    calls = []

    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"status":"ok"}\n', stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    result = service.run_cli_agent(
        agent_type="mimo_code",
        task="Implement in this worktree.",
        cwd=str(worktree),
        mode="worktree",
        model="mimo-model",
        agent="build",
        allow_unsafe_permissions=True,
    )

    assert result["status"] == "ok"
    args, _kwargs = calls[0]
    assert args[:2] == [r"C:\tools\mimo.cmd", "run"]
    assert args[args.index("--dir") + 1] == str(worktree)
    assert args[args.index("--model") + 1] == "mimo-model"
    assert args[args.index("--agent") + 1] == "build"
    assert "--dangerously-skip-permissions" in args
    assert args[-1] == "Implement in this worktree."


def test_missing_cli_agent_executable_returns_error(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: "")

    result = service.run_cli_agent(
        agent_type="codex_code",
        task="Inspect only.",
        cwd=str(project_root),
    )

    assert result["status"] == "error"
    assert result["code"] == "CLI_AGENT_NOT_FOUND"
    assert result["executableCandidates"] == ["codex.exe", "codex"]


def test_windows_subprocess_kwargs_hide_console(monkeypatch):
    class StartupInfo:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = 0

    monkeypatch.setattr(service.os, "name", "nt", raising=False)
    monkeypatch.setattr(service.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(service.subprocess, "STARTUPINFO", StartupInfo, raising=False)
    monkeypatch.setattr(service.subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(service.subprocess, "SW_HIDE", 0, raising=False)

    kwargs = service._subprocess_no_window_kwargs()

    assert kwargs["creationflags"] & 0x08000000
    assert kwargs["startupinfo"].dwFlags & 1


def test_list_cli_agent_adapters_reports_availability(monkeypatch, tmp_path):
    _configure_roots(monkeypatch, tmp_path)

    def fake_which(candidate):
        return r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else ""

    monkeypatch.setattr(service.shutil, "which", fake_which)

    adapters = {item["id"]: item for item in service.list_cli_agent_adapters()}

    assert adapters["mimo_code"]["available"] is True
    assert adapters["codex_code"]["available"] is False
    assert adapters["mimo_code"]["configPath"].endswith("cli_agents.json")
    assert adapters["mimo_code"]["terminal"]["enabled"] is True
    assert adapters["mimo_code"]["terminal"]["capabilities"]["pty"] is True


def test_mimo_cli_terminal_launch_uses_tui_project_protocol(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    mimo_cmd, mimo_script = _write_fake_mimo_npm_shim(tmp_path)
    node_exe = r"C:\tools\node.exe"

    def fake_which(candidate):
        if candidate == "mimo.cmd":
            return str(mimo_cmd)
        if candidate == "node.exe":
            return node_exe
        return ""

    monkeypatch.setattr(terminal_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(service.shutil, "which", fake_which)

    command = terminal_service._build_terminal_command(
        agent_type="mimo_code",
        task="列出根目录",
        cwd=str(project_root),
        mode="readonly",
        model="",
        agent="",
        cli_session_id="",
    )

    assert command["args"] == [node_exe, str(mimo_script), str(project_root)]
    assert all(not str(item).lower().endswith(".cmd") for item in command["args"])
    assert "code" not in command["args"]
    assert "--dir" not in command["args"]
    assert command["resumed"] is False
    assert command["initialInput"] == "列出根目录\r\n"


def test_mimo_cli_terminal_resume_uses_session_option(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    mimo_cmd, mimo_script = _write_fake_mimo_npm_shim(tmp_path)
    node_exe = r"C:\tools\node.exe"

    def fake_which(candidate):
        if candidate == "mimo.cmd":
            return str(mimo_cmd)
        if candidate == "node.exe":
            return node_exe
        return ""

    monkeypatch.setattr(terminal_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(service.shutil, "which", fake_which)

    command = terminal_service._build_terminal_command(
        agent_type="mimo_code",
        task="继续上次任务",
        cwd=str(project_root),
        mode="readonly",
        model="",
        agent="",
        cli_session_id="MIMO-123",
    )

    assert command["args"] == [node_exe, str(mimo_script), str(project_root), "--session", "MIMO-123"]
    assert all(not str(item).lower().endswith(".cmd") for item in command["args"])
    assert "resume" not in command["args"]
    assert "--dir" not in command["args"]
    assert command["resumed"] is True
    assert command["initialInput"] == ""


def test_cli_agent_terminal_resume_uses_user_level_protocol(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    service.CLI_AGENT_REGISTRY_PATH.parent.mkdir(parents=True)
    service.CLI_AGENT_REGISTRY_PATH.write_text(
        """
{
  "adapters": {
    "mimo_code": {
      "terminal": {
        "resume": {"argv": ["{exe}", "resume", "{cliSessionId}", "--cwd", "{cwd}"]},
        "sessionId": {"regex": "会话:([A-Z0-9]+)"}
      }
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")

    command = terminal_service._build_terminal_command(
        agent_type="mimo_code",
        task="继续上次任务",
        cwd=str(project_root),
        mode="readonly",
        model="",
        agent="",
        cli_session_id="MIMO-123",
    )

    assert command["args"] == [r"C:\tools\mimo.cmd", "resume", "MIMO-123", "--cwd", str(project_root)]
    assert command["resumed"] is True
    assert command["initialInput"] == ""
    assert command["sessionIdRegex"] == "会话:([A-Z0-9]+)"


def test_cli_agent_terminal_ensure_writes_runtime_state_without_project_config(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")

    class FakeProcess:
        def isalive(self):
            return True

    monkeypatch.setattr(terminal_service, "_spawn_terminal_process", lambda *args, **kwargs: (FakeProcess(), "conpty"))
    monkeypatch.setattr(terminal_service._TerminalRuntime, "start", lambda self: None)
    monkeypatch.setattr(terminal_service, "_send_initial_task", lambda *args, **kwargs: None)

    session = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task="列出 Python 文件",
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
    )

    assert session["transport"] == "conpty"
    assert session["alive"] is True
    assert session["transcriptPath"].startswith(".runtime/cli_agents/transcripts/")
    assert (terminal_service.SESSION_STATE_DIR / f"{session['terminalSessionId']}.json").exists()
    assert not (project_root / "workspace" / "cli_agents" / "cli_agents.json").exists()


def test_cli_agent_terminal_reuses_active_lock_for_same_session_adapter_and_cwd(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")
    spawned = []

    class FakeProcess:
        def isalive(self):
            return True

    def fake_spawn(*args, **kwargs):
        spawned.append((args, kwargs))
        return FakeProcess(), "conpty"

    monkeypatch.setattr(terminal_service, "_spawn_terminal_process", fake_spawn)
    monkeypatch.setattr(terminal_service._TerminalRuntime, "start", lambda self: None)
    monkeypatch.setattr(terminal_service, "_send_initial_task", lambda *args, **kwargs: None)

    first = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task="第一次调用",
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
    )
    second = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task="第二次调用",
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-2",
        source_run_id="run-2",
    )

    assert len(spawned) == 1
    assert second["terminalSessionId"] == first["terminalSessionId"]
    assert second["cliRunId"] == first["cliRunId"]
    assert second["lockKey"] == first["lockKey"]
    assert second["reusedActiveLock"] is True
    assert second["linkedSourceRunIds"] == ["run-1", "run-2"]


def test_cli_agent_lifecycle_close_event_persists_once(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_record_session_cycle_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *args, **kwargs: {"accepted": True})
    save_chat_state(
        tmp_path,
        build_chat_state(
            [{"role": "user", "content": "打开 MiMo Code", "timestamp": "2026-06-14T10:00:00"}],
            conversation_id="session-1",
            title="CLI 会话",
        ),
    )
    terminal_session = {
        "terminalSessionId": "term-1",
        "cliRunId": "cli-run-1",
        "adapterId": "mimo_code",
        "label": "MiMo Code",
        "sourceMessageId": "message-1",
        "sourceRunId": "run-1",
        "linkedSourceRunIds": ["run-1", "run-2"],
        "cwd": str(tmp_path),
        "cliSessionId": "MIMO-1",
    }

    first = session_service.append_cli_agent_lifecycle_event(
        "session-1",
        event="closed",
        terminal_session=terminal_session,
    )
    second = session_service.append_cli_agent_lifecycle_event(
        "session-1",
        event="closed",
        terminal_session=terminal_session,
    )

    state = load_chat_state(tmp_path)
    messages = state["conversations"][0]["messages"]
    lifecycle_messages = [
        item for item in messages
        if (item.get("metadata") or {}).get("kind") == "cli_agent_lifecycle"
    ]
    assert first is not None
    assert second is not None
    assert first["metadata"]["lifecycleKey"] == second["metadata"]["lifecycleKey"]
    assert len(lifecycle_messages) == 1
    assert lifecycle_messages[0]["content"] == "MiMo Code 已关闭。"
    assert lifecycle_messages[0]["metadata"]["cliRunId"] == "cli-run-1"
    assert lifecycle_messages[0]["metadata"]["linkedSourceRunIds"] == ["run-1", "run-2"]


def test_cli_agent_terminal_reads_only_bounded_transcript_tail(tmp_path):
    transcript = tmp_path / "terminal.log"
    transcript.write_bytes(("old" * 10000 + "\x1b[2J最后一屏").encode("utf-8"))

    tail = terminal_service._read_transcript_tail(transcript, limit=8)

    assert len(tail) <= 8
    assert "最后一屏" in tail
    assert "oldold" not in tail


def test_cli_agent_terminal_trims_large_tui_transcript(monkeypatch, tmp_path):
    transcript = tmp_path / "terminal.log"
    monkeypatch.setattr(terminal_service, "MAX_TRANSCRIPT_BYTES", 200)
    monkeypatch.setattr(terminal_service, "TRANSCRIPT_TRIM_TARGET_BYTES", 120)

    terminal_service._append_transcript_chunk(transcript, "\x1b[?2026h" + "A" * 180)
    terminal_service._append_transcript_chunk(transcript, "\x1b[5;76H" + "B" * 180)

    data = transcript.read_text(encoding="utf-8", errors="replace")
    assert transcript.stat().st_size <= 200
    assert data.endswith("B" * 120)
    assert "A" * 80 not in data
