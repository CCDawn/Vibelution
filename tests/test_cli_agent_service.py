import queue
import json
from types import SimpleNamespace
import subprocess
import sqlite3

import pytest

from core.ui.chat_state import build_chat_state, load_chat_state, save_chat_state
from core.web.services import cli_agent_service as service
from core.web.services import cli_agent_terminal_service as terminal_service
from core.web.services import session_service
from core.web.services.terminal_screen_buffer import TerminalScreenBuffer


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


def _write_fake_claude_native_cmd_shim(tmp_path):
    npm_dir = tmp_path / "npm"
    cli_exe = npm_dir / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    cli_exe.parent.mkdir(parents=True)
    cli_exe.write_text("", encoding="utf-8")
    cmd_path = npm_dir / "claude.cmd"
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
"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*
""".strip(),
        encoding="utf-8",
    )
    return cmd_path, cli_exe


def _write_mimocode_session_db(path, *, cwd, session_id="ses_test", created=10_000, updated=10_000):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "create table session ("
            "id text primary key, "
            "project_id text, "
            "directory text not null, "
            "title text not null, "
            "time_created integer not null, "
            "time_updated integer not null"
            ")",
        )
        connection.execute(
            "insert into session (id, project_id, directory, title, time_created, time_updated) "
            "values (?, ?, ?, ?, ?, ?)",
            (session_id, "project-1", str(cwd), "CLI resume", created, updated),
        )
        connection.commit()
    finally:
        connection.close()


def _write_cli_agent_config_with_mimo_db(path, db_path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
{
  "adapters": {
    "mimo_code": {
      "terminal": {
        "sessionDiscovery": {
          "source": "mimocode_sqlite",
          "databasePath": "__DB__",
          "createdGraceMs": 5000,
          "pollAttempts": 1,
          "pollIntervalSeconds": 0.1
        }
      }
    }
  }
}
""".strip().replace("__DB__", db_path.as_posix()),
        encoding="utf-8",
    )


def _write_cli_agent_config_with_claude_project(path, project_dir):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
{
  "adapters": {
    "claude_code": {
      "terminal": {
        "sessionDiscovery": {
          "source": "claude_code_project_jsonl",
          "projectDir": "__PROJECT_DIR__",
          "createdGraceMs": 5000,
          "pollAttempts": 1,
          "pollIntervalSeconds": 0.1
        }
      }
    }
  }
}
""".strip().replace("__PROJECT_DIR__", project_dir.as_posix()),
        encoding="utf-8",
    )


def test_codex_readonly_uses_exec_with_readonly_sandbox(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    spawned = []
    writes = []

    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\codex.exe" if candidate == "codex.exe" else "")

    class FakeProcess:
        def isalive(self):
            return True

        def write(self, data):
            writes.append(data)

    def fake_spawn(args, **kwargs):
        spawned.append((args, kwargs))
        return FakeProcess(), "conpty"

    monkeypatch.setattr(terminal_service, "_spawn_terminal_process", fake_spawn)
    monkeypatch.setattr(terminal_service._TerminalRuntime, "start", lambda self: None)
    monkeypatch.setattr(terminal_service, "_schedule_session_id_discovery", lambda *args, **kwargs: None)

    result = service.run_cli_agent(
        agent_type="codex_code",
        task="Inspect the repository without changing files.",
        cwd=str(project_root),
        mode="readonly",
        timeout=15,
    )

    assert result["status"] == "task_sent"
    assert result["internalStatus"] == "sent"
    assert result["code"] == "CLI_AGENT_TASK_SENT"
    args, kwargs = spawned[0]
    assert args == [r"C:\tools\codex.exe", "--cd", str(project_root)]
    assert kwargs["cwd"] == str(project_root)
    assert writes == ["Inspect the repository without changing files.\r\n"]
    assert result["terminalSessionId"].startswith("cli-term-")
    assert result["taskId"].startswith("cli-task-")


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
    spawned = []
    writes = []

    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")

    class FakeProcess:
        def isalive(self):
            return True

        def write(self, data):
            writes.append(data)

    def fake_spawn(args, **kwargs):
        spawned.append((args, kwargs))
        return FakeProcess(), "conpty"

    monkeypatch.setattr(terminal_service, "_spawn_terminal_process", fake_spawn)
    monkeypatch.setattr(terminal_service._TerminalRuntime, "start", lambda self: None)
    monkeypatch.setattr(terminal_service, "_schedule_session_id_discovery", lambda *args, **kwargs: None)

    result = service.run_cli_agent(
        agent_type="mimo_code",
        task="Implement in this worktree.",
        cwd=str(worktree),
        mode="worktree",
        model="mimo-model",
        agent="build",
        allow_unsafe_permissions=True,
    )

    assert result["status"] == "task_sent"
    assert result["internalStatus"] == "sent"
    assert result["code"] == "CLI_AGENT_TASK_SENT"
    args, kwargs = spawned[0]
    assert args == [r"C:\tools\mimo.cmd", str(worktree)]
    assert kwargs["cwd"] == str(worktree)
    assert len(writes) == 1
    assert "Implement in this worktree." in writes[0]
    assert "VIBELUTION_CLI_DONE:" in writes[0]
    assert "[VIBELUTION_CLI_DONE:" not in writes[0]


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


def test_run_cli_agent_timeout_returns_timeout_payload(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    adapters = service._load_adapter_definitions()
    adapters["codex_code"]["terminal"] = {"enabled": False}
    monkeypatch.setattr(service, "_load_adapter_definitions", lambda: adapters)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\codex.exe" if candidate == "codex.exe" else "")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 1), output="long stdout output", stderr="long stderr output")

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    result = service.run_cli_agent(
        agent_type="codex_code",
        task="执行一个可能超时的任务",
        cwd=str(project_root),
        mode="readonly",
        timeout=5,
    )

    assert result["status"] == "timeout"
    assert result["code"] == "CLI_AGENT_TIMEOUT"
    assert result["timedOut"] is True
    assert result["timeoutSeconds"] == 5
    assert result["stdoutPreview"] == "long stdout output"
    assert result["stderrPreview"] == "long stderr output"
    assert result["logPath"].startswith(".runtime/cli_agents/runs/")
    assert result["durationMs"] >= 0


def test_run_cli_agent_launch_failure_returns_error_payload(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    adapters = service._load_adapter_definitions()
    adapters["codex_code"]["terminal"] = {"enabled": False}
    monkeypatch.setattr(service, "_load_adapter_definitions", lambda: adapters)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\codex.exe" if candidate == "codex.exe" else "")

    def fake_run(*_args, **_kwargs):
        raise OSError("launch failed")

    monkeypatch.setattr(service.subprocess, "run", fake_run)

    result = service.run_cli_agent(
        agent_type="codex_code",
        task="执行一个需要启动进程的任务",
        cwd=str(project_root),
    )

    assert result["status"] == "error"
    assert result["code"] == "CLI_AGENT_LAUNCH_FAILED"
    assert "launch failed" in result["message"]
    assert result["logPath"].startswith(".runtime/cli_agents/runs/")


def test_resolve_run_cwd_rejects_missing_directory(tmp_path, monkeypatch):
    _configure_roots(monkeypatch, tmp_path)
    missing = tmp_path / "Vibelution" / "no-such-dir"

    result = service._resolve_run_cwd(str(missing), mode="readonly")

    assert result["ok"] is False
    assert result["code"] == "CWD_NOT_FOUND"


def test_resolve_run_cwd_rejects_outside_allowed_roots(tmp_path, monkeypatch):
    project_root = _configure_roots(monkeypatch, tmp_path)
    outside = project_root.parent / "outside-project-root"
    outside.mkdir()

    result = service._resolve_run_cwd(str(outside), mode="readonly")

    assert result["ok"] is False
    assert result["code"] == "CWD_OUTSIDE_ALLOWED_ROOTS"


def test_build_command_args_rejects_unknown_adapter_id(tmp_path):
    try:
        service._build_command_args(
            {"id": "unsupported"},
            executable="agent",
            cwd=tmp_path,
            task="run",
            task_hash="abc123456789",
            mode="readonly",
            model="",
            agent="",
            allow_unsafe_permissions=False,
        )
    except ValueError as exc:
        assert str(exc) == "Unsupported adapter id: unsupported"
    else:
        raise AssertionError("expected ValueError for unsupported adapter id")


def test_terminal_runtime_publish_replaces_oldest_event_when_queue_is_full(tmp_path):
    runtime = terminal_service._TerminalRuntime(
        state={"terminalSessionId": "cli-term-1", "rows": 28, "cols": 100},
        process=SimpleNamespace(),
        transport="conpty",
        transcript_path=tmp_path / "transcript.txt",
        session_id_regex=r"",
    )
    bounded = queue.Queue(maxsize=1)
    runtime.subscribers = [bounded]
    bounded.put_nowait({"type": "old_event"})

    runtime._publish({"type": "new_event"})

    assert bounded.qsize() == 1
    assert bounded.get_nowait()["type"] == "new_event"
def test_cli_agent_run_tool_does_not_reuse_persisted_running_state_without_runtime(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    state_dir = project_root / ".runtime" / "cli_agents" / "sessions"
    state_dir.mkdir(parents=True)
    (state_dir / "cli-term-active.json").write_text(
        """
{
  "terminalSessionId": "cli-term-active",
  "adapterId": "codex_code",
  "agentType": "codex_code",
  "label": "Codex Code",
  "cliRunId": "cli-run-active",
  "lockKey": "cli-lock-active",
  "cwd": "__CWD__",
  "status": "running",
  "alive": true,
  "updatedAt": "2026-06-14T10:00:00+00:00"
}
""".strip().replace("__CWD__", str(project_root).replace("\\", "\\\\")),
        encoding="utf-8",
    )
    monkeypatch.setattr(service.shutil, "which", lambda candidate: "")

    result = service.run_cli_agent(
        agent_type="codex_code",
        task="继续处理当前问题",
        cwd=str(project_root),
    )

    assert result["status"] == "error"
    assert result["code"] == "CLI_AGENT_NOT_FOUND"
    assert result.get("terminalReuse") is None


def test_cli_agent_run_tool_does_not_reuse_stale_terminal_state(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    state_dir = project_root / ".runtime" / "cli_agents" / "sessions"
    state_dir.mkdir(parents=True)
    (state_dir / "cli-term-stale.json").write_text(
        """
{
  "terminalSessionId": "cli-term-stale",
  "adapterId": "codex_code",
  "agentType": "codex_code",
  "label": "Codex Code",
  "cliRunId": "cli-run-stale",
  "lockKey": "cli-lock-stale",
  "cwd": "__CWD__",
  "status": "stale",
  "alive": false,
  "updatedAt": "2026-06-14T10:00:00+00:00"
}
""".strip().replace("__CWD__", str(project_root).replace("\\", "\\\\")),
        encoding="utf-8",
    )
    monkeypatch.setattr(service.shutil, "which", lambda candidate: "")

    result = service.run_cli_agent(
        agent_type="codex_code",
        task="继续处理当前问题",
        cwd=str(project_root),
    )

    assert result["status"] == "error"
    assert result["code"] == "CLI_AGENT_NOT_FOUND"
    assert result.get("terminalReuse") is None


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
        if candidate == "mimo.cmd":
            return r"C:\tools\mimo.cmd"
        if candidate == "claude.cmd":
            return r"C:\tools\claude.cmd"
        return ""

    monkeypatch.setattr(service.shutil, "which", fake_which)

    adapters = {item["id"]: item for item in service.list_cli_agent_adapters()}

    assert adapters["mimo_code"]["available"] is True
    assert adapters["codex_code"]["available"] is False
    assert adapters["claude_code"]["available"] is True
    assert adapters["mimo_code"]["configPath"].endswith("cli_agents.json")
    assert adapters["mimo_code"]["terminal"]["enabled"] is True
    assert adapters["mimo_code"]["terminal"]["capabilities"]["pty"] is True
    assert adapters["claude_code"]["terminal"]["capabilities"]["resume"] is True


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


def test_claude_cli_terminal_launch_uses_cwd_and_plan_permission(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\claude.cmd" if candidate == "claude.cmd" else "")

    command = terminal_service._build_terminal_command(
        agent_type="claude_code",
        task="只读审查当前项目",
        cwd=str(project_root),
        mode="readonly",
        model="",
        agent="",
        cli_session_id="",
    )

    assert command["args"] == [r"C:\tools\claude.cmd", "--permission-mode", "plan"]
    assert command["cwd"] == str(project_root)
    assert command["resumed"] is False
    assert command["initialInput"] == "只读审查当前项目\r\n"


def test_claude_cli_terminal_launch_worktree_mode_with_allow_unsafe_appends_dangerous_permission_flag(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    worktree_root = project_root.parent / f"{project_root.name}-worktrees" / "unsafe-permission-task"
    worktree_root.mkdir(parents=True)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\claude.cmd" if candidate == "claude.cmd" else "")

    command = terminal_service._build_terminal_command(
        agent_type="claude_code",
        task="继续修改",
        cwd=str(worktree_root),
        mode="worktree",
        model="",
        agent="",
        cli_session_id="",
        allow_unsafe_permissions=True,
    )

    assert command["args"] == [
        r"C:\tools\claude.cmd",
        "--permission-mode",
        "auto",
        "--dangerously-skip-permissions",
    ]


def test_claude_cli_terminal_real_cmd_shim_uses_native_exe_without_node(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    claude_cmd, claude_exe = _write_fake_claude_native_cmd_shim(tmp_path)
    node_exe = r"C:\tools\node.exe"

    def fake_which(candidate):
        if candidate == "claude.cmd":
            return str(claude_cmd)
        if candidate == "node.exe":
            return node_exe
        return ""

    monkeypatch.setattr(terminal_service.os, "name", "nt", raising=False)
    monkeypatch.setattr(service.shutil, "which", fake_which)

    command = terminal_service._build_terminal_command(
        agent_type="claude_code",
        task="只读审查当前项目",
        cwd=str(project_root),
        mode="readonly",
        model="",
        agent="",
        cli_session_id="",
    )

    assert command["args"] == [str(claude_exe), "--permission-mode", "plan"]
    assert node_exe not in command["args"]
    assert all(not str(item).lower().endswith(".cmd") for item in command["args"])


def test_claude_cli_terminal_resume_uses_session_option(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    worktree = project_root.parent / "Vibelution-worktrees" / "claude-task"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\claude.cmd" if candidate == "claude.cmd" else "")
    session_id = "6d9ae669-28b4-42a0-8767-0e78f406a2b1"

    command = terminal_service._build_terminal_command(
        agent_type="claude_code",
        task="继续修改",
        cwd=str(worktree),
        mode="worktree",
        model="",
        agent="",
        cli_session_id=session_id,
    )

    assert command["args"] == [r"C:\tools\claude.cmd", "--resume", session_id, "--permission-mode", "auto"]
    assert command["cwd"] == str(worktree)
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


def test_mimo_cli_terminal_discovers_session_id_from_user_level_sqlite(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    db_path = tmp_path / "mimocode" / "mimocode.db"
    _write_mimocode_session_db(db_path, cwd=project_root, session_id="ses_current", created=10_500, updated=11_000)
    _write_cli_agent_config_with_mimo_db(service.CLI_AGENT_REGISTRY_PATH, db_path)

    spec = service._load_adapter_definitions()["mimo_code"]["terminal"]["sessionDiscovery"]

    discovered = terminal_service._discover_cli_session_id_for_state(
        {"cwd": str(project_root), "processStartedAtMs": 10_000},
        spec,
        existing=False,
    )

    assert discovered == "ses_current"


def test_claude_cli_terminal_discovers_session_id_from_project_jsonl(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    session_id = "6d9ae669-28b4-42a0-8767-0e78f406a2b1"
    project_dir = tmp_path / ".claude" / "projects" / terminal_service._claude_project_dir_name(str(project_root))
    project_dir.mkdir(parents=True)
    (project_dir / f"{session_id}.jsonl").write_text(
        '{"type":"mode","sessionId":"6d9ae669-28b4-42a0-8767-0e78f406a2b1"}\n',
        encoding="utf-8",
    )
    spec = {
        "source": "claude_code_project_jsonl",
        "projectDir": str(project_dir),
        "idRegex": r"^[0-9a-fA-F-]{36}$",
        "maxRows": 10,
    }

    discovered = terminal_service._discover_cli_session_id_for_state(
        {"cwd": str(project_root), "processStartedAtMs": 0},
        spec,
        existing=False,
    )

    assert discovered == session_id


def test_cli_agent_terminal_ensure_resumes_discovered_claude_session_after_restart(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    session_id = "6d9ae669-28b4-42a0-8767-0e78f406a2b1"
    project_dir = tmp_path / ".claude" / "projects" / "vibelution"
    project_dir.mkdir(parents=True)
    (project_dir / f"{session_id}.jsonl").write_text(
        '{"type":"mode","sessionId":"6d9ae669-28b4-42a0-8767-0e78f406a2b1"}\n',
        encoding="utf-8",
    )
    _write_cli_agent_config_with_claude_project(service.CLI_AGENT_REGISTRY_PATH, project_dir)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\claude.cmd" if candidate == "claude.cmd" else "")

    task = "继续 Claude Code 会话"
    terminal_session_id = terminal_service._stable_terminal_session_id(
        adapter_id="claude_code",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
        cwd=str(project_root),
        mode="readonly",
        task=task,
    )
    terminal_service._write_state(
        {
            "terminalSessionId": terminal_session_id,
            "adapterId": "claude_code",
            "agentType": "claude_code",
            "label": "Claude Code",
            "sourceSessionId": "session-1",
            "sourceMessageId": "message-1",
            "sourceRunId": "run-1",
            "cwd": str(project_root),
            "mode": "readonly",
            "task": task,
            "processStartedAtMs": 0,
            "status": "exited",
            "alive": False,
            "cliSessionId": "",
        },
    )
    spawned = []

    class FakeProcess:
        def isalive(self):
            return True

    def fake_spawn(args, **kwargs):
        spawned.append(args)
        return FakeProcess(), "conpty"

    monkeypatch.setattr(terminal_service, "_spawn_terminal_process", fake_spawn)
    monkeypatch.setattr(terminal_service._TerminalRuntime, "start", lambda self: None)
    monkeypatch.setattr(terminal_service, "_send_initial_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(terminal_service, "_schedule_session_id_discovery", lambda *args, **kwargs: None)

    session = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="claude_code",
        task=task,
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
    )

    assert session["cliSessionId"] == session_id
    assert session["cliSessionIdSource"] == "session_discovery_existing"
    assert session["resumed"] is True
    assert spawned == [[r"C:\tools\claude.cmd", "--resume", session_id, "--permission-mode", "plan"]]


def test_cli_agent_terminal_ensure_resumes_discovered_existing_session_after_restart(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    db_path = tmp_path / "mimocode" / "mimocode.db"
    _write_mimocode_session_db(db_path, cwd=project_root, session_id="ses_restart", created=10_500, updated=11_000)
    _write_cli_agent_config_with_mimo_db(service.CLI_AGENT_REGISTRY_PATH, db_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")

    task = "继续审查 CLI 会话恢复"
    terminal_session_id = terminal_service._stable_terminal_session_id(
        adapter_id="mimo_code",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
        cwd=str(project_root),
        mode="readonly",
        task=task,
    )
    terminal_service._write_state(
        {
            "terminalSessionId": terminal_session_id,
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-1",
            "sourceMessageId": "message-1",
            "sourceRunId": "run-1",
            "cwd": str(project_root),
            "mode": "readonly",
            "task": task,
            "processStartedAtMs": 10_000,
            "status": "exited",
            "alive": False,
            "cliSessionId": "",
        },
    )
    spawned = []

    class FakeProcess:
        def isalive(self):
            return True

    def fake_spawn(args, **kwargs):
        spawned.append(args)
        return FakeProcess(), "conpty"

    monkeypatch.setattr(terminal_service, "_spawn_terminal_process", fake_spawn)
    monkeypatch.setattr(terminal_service._TerminalRuntime, "start", lambda self: None)
    monkeypatch.setattr(terminal_service, "_send_initial_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(terminal_service, "_schedule_session_id_discovery", lambda *args, **kwargs: None)

    session = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task=task,
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
    )

    assert session["cliSessionId"] == "ses_restart"
    assert session["cliSessionIdSource"] == "session_discovery_existing"
    assert session["resumed"] is True
    assert spawned == [[r"C:\tools\mimo.cmd", str(project_root), "--session", "ses_restart"]]


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


def test_cli_agent_terminal_input_and_resize_return_lightweight_ack(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")
    writes = []
    sizes = []

    class FakeProcess:
        def isalive(self):
            return True

        def write(self, data):
            writes.append(data)

        def setwinsize(self, rows, cols):
            sizes.append((rows, cols))

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

    input_ack = terminal_service.write_cli_agent_terminal_input(session["terminalSessionId"], "\x1b[A")
    resize_ack = terminal_service.resize_cli_agent_terminal_session(session["terminalSessionId"], 32, 120)

    assert writes == ["\x1b[A"]
    assert sizes == [(32, 120)]
    assert input_ack["code"] == "CLI_AGENT_TERMINAL_INPUT_ACCEPTED"
    assert resize_ack["code"] == "CLI_AGENT_TERMINAL_RESIZE_ACCEPTED"
    assert input_ack["terminalSessionId"] == session["terminalSessionId"]
    assert resize_ack["rows"] == 32
    assert resize_ack["cols"] == 120
    assert "transcriptTail" not in input_ack
    assert "screenReplay" not in resize_ack


def test_cli_agent_terminal_output_event_streams_chunk_without_session_snapshot(monkeypatch, tmp_path):
    from core.web.services import cli_agent_task_kernel

    monkeypatch.setattr(cli_agent_task_kernel, "ingest_terminal_output", lambda *args, **kwargs: None)

    class FakeProcess:
        def isalive(self):
            return True

    runtime = terminal_service._TerminalRuntime(
        state={
            "terminalSessionId": "cli-term-one",
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "status": "running",
            "alive": True,
            "rows": 10,
            "cols": 40,
        },
        process=FakeProcess(),
        transport="conpty",
        transcript_path=tmp_path / "terminal.log",
        session_id_regex="",
    )
    subscriber = runtime.subscribe()

    runtime._record_output("hello")

    event = subscriber.get_nowait()
    assert event == {"type": "terminal_output", "chunk": "hello"}


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


def test_cli_agent_terminal_reuses_active_lock_across_source_sessions(monkeypatch, tmp_path):
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
        source_session_id="session-2",
        source_message_id="message-2",
        source_run_id="run-2",
    )

    assert len(spawned) == 1
    assert second["terminalSessionId"] == first["terminalSessionId"]
    assert second["cliRunId"] == first["cliRunId"]
    assert second["lockKey"] == first["lockKey"]
    assert second["linkedSourceRunIds"] == ["run-1", "run-2"]


def test_cli_agent_terminal_view_rebinds_stale_history_to_live_runtime(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    task = "继续分析 CLI 在线状态"
    stale_id = terminal_service._stable_terminal_session_id(
        adapter_id="mimo_code",
        source_session_id="session-old",
        source_message_id="message-old",
        source_run_id="run-old",
        cwd=str(project_root),
        mode="readonly",
        task=task,
    )
    live_id = "cli-term-live-rebind"

    class FakeProcess:
        def isalive(self):
            return True

    live_runtime = terminal_service._TerminalRuntime(
        state={
            "terminalSessionId": live_id,
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-live",
            "sourceMessageId": "message-live",
            "sourceRunId": "run-live",
            "linkedSourceMessageIds": ["message-live"],
            "linkedSourceRunIds": ["run-live"],
            "cliRunId": "cli-run-live",
            "lockKey": "cli-lock-live",
            "cwd": str(project_root),
            "mode": "readonly",
            "status": "running",
            "alive": True,
            "rows": 32,
            "cols": 120,
            "updatedAt": "2026-06-15T08:40:00+00:00",
        },
        process=FakeProcess(),
        transport="conpty",
        transcript_path=terminal_service._transcript_path(live_id),
        session_id_regex="",
    )
    terminal_service._RUNTIMES[live_id] = live_runtime
    terminal_service._write_state(
        {
            "terminalSessionId": stale_id,
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-old",
            "sourceMessageId": "message-old",
            "sourceRunId": "run-old",
            "cliRunId": "cli-run-old",
            "lockKey": "cli-lock-old",
            "cwd": str(project_root),
            "mode": "readonly",
            "task": task,
            "cliSessionId": "ses_old",
            "status": "stale",
            "alive": False,
            "staleReason": "backend_startup",
            "updatedAt": "2026-06-15T08:30:00+00:00",
        }
    )
    monkeypatch.setattr(
        terminal_service,
        "_spawn_terminal_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("view rebind must not spawn")),
    )

    session = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task=task,
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-old",
        source_message_id="message-old",
        source_run_id="run-old",
        intent="view",
    )

    stale_state = terminal_service._read_state(stale_id)
    assert session["terminalSessionId"] == live_id
    assert session["interactionState"] == "live"
    assert session["canInput"] is True
    assert session["reusedActiveLock"] is True
    assert session["reboundFromTerminalSessionId"] == stale_id
    assert session["linkedSourceRunIds"] == ["run-live", "run-old"]
    assert stale_state["status"] == "closed"
    assert stale_state["alive"] is False
    assert stale_state["closeReason"] == "superseded_by_idempotent_terminal"
    assert stale_state["supersededByTerminalSessionId"] == live_id


def test_cli_agent_terminal_detail_and_events_rebind_old_id_to_live_runtime(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    old_id = "cli-term-old-history"
    live_id = "cli-term-live-events"

    class FakeProcess:
        def isalive(self):
            return True

    terminal_service._write_state(
        {
            "terminalSessionId": old_id,
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "cliRunId": "cli-run-old",
            "lockKey": "cli-lock-old",
            "cwd": str(project_root),
            "mode": "readonly",
            "status": "stale",
            "alive": False,
            "staleReason": "backend_startup",
            "updatedAt": "2026-06-15T08:30:00+00:00",
        }
    )
    terminal_service._RUNTIMES[live_id] = terminal_service._TerminalRuntime(
        state={
            "terminalSessionId": live_id,
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "cliRunId": "cli-run-live",
            "lockKey": "cli-lock-live",
            "cwd": str(project_root),
            "mode": "readonly",
            "status": "running",
            "alive": True,
            "rows": 32,
            "cols": 120,
            "updatedAt": "2026-06-15T08:40:00+00:00",
        },
        process=FakeProcess(),
        transport="conpty",
        transcript_path=terminal_service._transcript_path(live_id),
        session_id_regex="",
    )

    detail = terminal_service.get_cli_agent_terminal_session(old_id)
    stream = terminal_service.stream_cli_agent_terminal_events(old_id)
    first_event = next(stream)
    stream.close()

    payload = json.loads(first_event.split("data: ", 1)[1].strip())
    assert detail["terminalSessionId"] == live_id
    assert detail["interactionState"] == "live"
    assert detail["reboundFromTerminalSessionId"] == old_id
    assert payload["type"] == "terminal_snapshot"
    assert payload["session"]["terminalSessionId"] == live_id
    assert payload["session"]["interactionState"] == "live"


def test_cli_agent_terminal_ensure_supersedes_legacy_duplicate_states(monkeypatch, tmp_path):
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
        task="第一次调用",
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
    )
    terminal_service._write_state(
        {
            "terminalSessionId": "cli-term-legacy",
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-1",
            "sourceRunId": "run-legacy",
            "cliRunId": session["cliRunId"],
            "lockKey": session["lockKey"],
            "cwd": str(project_root),
            "status": "running",
            "alive": True,
            "updatedAt": "2026-06-14T10:00:00+00:00",
        }
    )

    reused = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task="第二次调用",
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-2",
        source_run_id="run-2",
    )

    legacy = terminal_service._read_state("cli-term-legacy")
    assert reused["terminalSessionId"] == session["terminalSessionId"]
    assert legacy["status"] == "closed"
    assert legacy["alive"] is False
    assert legacy["closeReason"] == "superseded_by_idempotent_terminal"
    assert legacy["supersededByTerminalSessionId"] == session["terminalSessionId"]


def test_cli_agent_terminal_restart_ensure_supersedes_legacy_duplicate_states(monkeypatch, tmp_path):
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
        task="第一次调用",
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
    )
    terminal_service._write_state(
        {
            "terminalSessionId": "cli-term-legacy-restart",
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-1",
            "sourceRunId": "run-legacy",
            "cliRunId": session["cliRunId"],
            "lockKey": session["lockKey"],
            "cwd": str(project_root),
            "status": "running",
            "alive": True,
            "updatedAt": "2026-06-14T10:00:00+00:00",
        }
    )
    terminal_service._RUNTIMES.clear()

    resumed = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task="第二次调用",
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-2",
        source_run_id="run-2",
    )

    legacy = terminal_service._read_state("cli-term-legacy-restart")
    assert resumed["terminalSessionId"] == session["terminalSessionId"]
    assert legacy["status"] == "closed"
    assert legacy["alive"] is False
    assert legacy["closeReason"] == "superseded_by_idempotent_terminal"
    assert legacy["supersededByTerminalSessionId"] == session["terminalSessionId"]


def test_cli_agent_terminal_idempotent_after_backend_restart(monkeypatch, tmp_path):
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
    terminal_service._RUNTIMES.clear()
    second = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task="第二次调用",
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-2",
        source_run_id="run-2",
    )

    assert len(spawned) == 2
    assert second["terminalSessionId"] == first["terminalSessionId"]
    assert second["cliRunId"] == first["cliRunId"]
    assert second["lockKey"] == first["lockKey"]
    assert second["linkedSourceRunIds"] == ["run-1", "run-2"]


def test_cli_agent_terminal_stop_closes_related_duplicate_states(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    common = {
        "adapterId": "mimo_code",
        "agentType": "mimo_code",
        "label": "MiMo Code",
        "sourceSessionId": "session-1",
        "cliRunId": "cli-run-same",
        "lockKey": "cli-lock-same",
        "cwd": str(project_root),
        "status": "running",
        "alive": True,
        "updatedAt": "2026-06-14T10:00:00+00:00",
    }
    terminal_service._write_state({**common, "terminalSessionId": "cli-term-old-a", "sourceRunId": "run-1"})
    terminal_service._write_state({**common, "terminalSessionId": "cli-term-old-b", "sourceRunId": "run-2"})

    closed = terminal_service.stop_cli_agent_terminal_session("cli-term-old-a")

    first = terminal_service._read_state("cli-term-old-a")
    second = terminal_service._read_state("cli-term-old-b")
    assert closed["status"] == "closed"
    assert set(closed["closedTerminalSessionIds"]) == {"cli-term-old-a", "cli-term-old-b"}
    assert first["userClosed"] is True
    assert second["userClosed"] is True
    assert first["status"] == "closed"
    assert second["status"] == "closed"


def test_cli_agent_related_state_prefers_open_scope_over_closed_with_cli_session(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    terminal_service._write_state(
        {
            "terminalSessionId": "cli-term-closed",
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "cwd": str(project_root),
            "mode": "readonly",
            "cliSessionId": "ses-old",
            "status": "closed",
            "alive": False,
            "userClosed": True,
            "updatedAt": "2026-06-15T02:00:00+00:00",
        }
    )
    terminal_service._write_state(
        {
            "terminalSessionId": "cli-term-open",
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "cwd": str(project_root),
            "mode": "readonly",
            "status": "stale",
            "alive": False,
            "updatedAt": "2026-06-15T01:00:00+00:00",
        }
    )

    state = terminal_service._find_related_terminal_state(
        cli_run_id="",
        lock_key="",
        adapter_id="mimo_code",
        source_session_id="session-1",
        cwd=str(project_root),
        mode="readonly",
    )

    assert state["terminalSessionId"] == "cli-term-open"


def test_cli_agent_public_state_exposes_tui_interrupted_separately():
    state = terminal_service._public_state(
        {
            "terminalSessionId": "cli-term-interrupted",
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "cwd": r"C:\project",
            "mode": "readonly",
            "status": "running",
            "alive": True,
            "screenText": "Build · MiMo Auto\ninterrupted\n",
        }
    )

    assert state["interactionState"] == "live"
    assert state["canInput"] is True
    assert state["tuiState"] == "interrupted"
    assert state["semanticStatus"] == "attached"


def test_cli_agent_terminal_startup_reconcile_marks_orphan_running_state_stale(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    terminal_service._write_state(
        {
            "terminalSessionId": "cli-term-orphan",
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "cliRunId": "cli-run-orphan",
            "lockKey": "cli-lock-orphan",
            "cwd": str(project_root),
            "status": "running",
            "alive": True,
            "updatedAt": "2026-06-14T10:00:00+00:00",
        }
    )
    terminal_service._RUNTIMES.clear()

    result = terminal_service.reconcile_cli_agent_terminal_states_on_startup(reason="test_startup")

    state = terminal_service._read_state("cli-term-orphan")
    assert result["staleCount"] == 1
    assert state["status"] == "stale"
    assert state["alive"] is False
    assert state["staleReason"] == "test_startup"


def test_cli_agent_terminal_source_bound_attach_does_not_resume_stale_session(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")
    task = "继续审查启动弹窗"
    terminal_session_id = terminal_service._stable_terminal_session_id(
        adapter_id="mimo_code",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
        cwd=str(project_root),
        mode="readonly",
        task=task,
    )
    terminal_service._write_state(
        {
            "terminalSessionId": terminal_session_id,
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-1",
            "sourceMessageId": "message-1",
            "sourceRunId": "run-1",
            "cliRunId": "cli-run-stale",
            "lockKey": "cli-lock-stale",
            "cwd": str(project_root),
            "mode": "readonly",
            "task": task,
            "cliSessionId": "ses_restart",
            "cliSessionIdSource": "session_discovery_existing",
            "status": "stale",
            "alive": False,
            "staleReason": "backend_startup",
            "updatedAt": "2026-06-15T01:40:00+00:00",
        }
    )
    spawned = []

    def fake_spawn(*args, **kwargs):
        spawned.append((args, kwargs))
        raise AssertionError("source-bound stale terminal attach must not spawn a CLI process")

    monkeypatch.setattr(terminal_service, "_spawn_terminal_process", fake_spawn)

    session = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task=task,
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
    )

    assert spawned == []
    assert session["terminalSessionId"] == terminal_session_id
    assert session["status"] == "stale"
    assert session["alive"] is False
    assert session["cliSessionId"] == "ses_restart"
    assert session["interactionState"] == "resumable"
    assert session["canInput"] is False
    assert session["canResume"] is True
    assert session["resumeAction"] == "resume_session"
    assert session["displayMode"] == "readonly_replay"


def test_cli_agent_terminal_input_on_stale_session_returns_resume_details(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    terminal_service._write_state(
        {
            "terminalSessionId": "cli-term-stale-input",
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "cwd": str(project_root),
            "mode": "readonly",
            "cliSessionId": "ses_restart",
            "status": "stale",
            "alive": False,
            "staleReason": "backend_startup",
            "updatedAt": "2026-06-15T01:40:00+00:00",
        }
    )

    with pytest.raises(terminal_service.CliAgentTerminalError) as exc_info:
        terminal_service.write_cli_agent_terminal_input("cli-term-stale-input", "hello\r")

    assert exc_info.value.code == "TERMINAL_SESSION_NOT_RUNNING"
    assert exc_info.value.details["terminalSessionId"] == "cli-term-stale-input"
    assert exc_info.value.details["interactionState"] == "resumable"
    assert exc_info.value.details["canInput"] is False
    assert exc_info.value.details["canResume"] is True
    assert exc_info.value.details["resumeAction"] == "resume_session"


def test_cli_agent_terminal_resume_intent_spawns_stale_session(monkeypatch, tmp_path):
    project_root = _configure_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda candidate: r"C:\tools\mimo.cmd" if candidate == "mimo.cmd" else "")
    task = "继续审查启动弹窗"
    terminal_session_id = terminal_service._stable_terminal_session_id(
        adapter_id="mimo_code",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
        cwd=str(project_root),
        mode="readonly",
        task=task,
    )
    terminal_service._write_state(
        {
            "terminalSessionId": terminal_session_id,
            "adapterId": "mimo_code",
            "agentType": "mimo_code",
            "label": "MiMo Code",
            "sourceSessionId": "session-1",
            "sourceMessageId": "message-1",
            "sourceRunId": "run-1",
            "cliRunId": "cli-run-stale",
            "lockKey": "cli-lock-stale",
            "cwd": str(project_root),
            "mode": "readonly",
            "task": task,
            "cliSessionId": "ses_restart",
            "cliSessionIdSource": "session_discovery_existing",
            "status": "stale",
            "alive": False,
            "staleReason": "backend_startup",
            "updatedAt": "2026-06-15T01:40:00+00:00",
        }
    )
    transcript_path = terminal_service._transcript_path(terminal_session_id)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("旧尺寸历史画面\r\n\x1b[57;6H", encoding="utf-8")
    spawned = []

    class FakeProcess:
        def isalive(self):
            return True

    def fake_spawn(args, **kwargs):
        spawned.append({"args": list(args), "kwargs": dict(kwargs)})
        return FakeProcess(), "conpty"

    monkeypatch.setattr(terminal_service, "_spawn_terminal_process", fake_spawn)
    monkeypatch.setattr(terminal_service._TerminalRuntime, "start", lambda self: None)
    monkeypatch.setattr(terminal_service, "_send_initial_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(terminal_service, "_schedule_session_id_discovery", lambda *args, **kwargs: None)

    session = terminal_service.ensure_cli_agent_terminal_session(
        agent_type="mimo_code",
        task=task,
        cwd=str(project_root),
        mode="readonly",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
        intent="resume",
        rows=55,
        cols=180,
    )

    assert spawned == [
        {
            "args": [r"C:\tools\mimo.cmd", str(project_root), "--session", "ses_restart"],
            "kwargs": {"cwd": str(project_root), "rows": 55, "cols": 180},
        }
    ]
    assert session["terminalSessionId"] == terminal_session_id
    assert session["status"] == "running"
    assert session["alive"] is True
    assert session["resumed"] is True
    assert session["transcriptTail"] == ""
    assert session["transcriptTailReplayable"] is False
    assert session["transcriptTailRenderReason"] == "live_runtime_no_history_replay"
    assert session["interactionState"] == "live"
    assert session["canInput"] is True
    assert session["canResume"] is False


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
        "lockKey": "cli-lock-1",
        "adapterId": "mimo_code",
        "label": "MiMo Code",
        "sourceMessageId": "message-1",
        "sourceRunId": "run-1",
        "linkedSourceRunIds": ["run-1", "run-2"],
        "cwd": str(tmp_path),
        "mode": "readonly",
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
    assert lifecycle_messages[0]["metadata"]["lockKey"] == "cli-lock-1"
    assert lifecycle_messages[0]["metadata"]["mode"] == "readonly"
    assert lifecycle_messages[0]["metadata"]["linkedSourceRunIds"] == ["run-1", "run-2"]
    sidecar_path = tmp_path / "workspace" / "sessions" / "session-1" / "logs" / "cli_agent_lifecycle.jsonl"
    assert sidecar_path.exists()
    assert len(sidecar_path.read_text(encoding="utf-8").splitlines()) == 1


def test_cli_agent_lifecycle_sidecar_restores_detail_after_message_truncation(monkeypatch, tmp_path):
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
        "sourceRunId": "run-1",
        "cwd": str(tmp_path),
    }
    session_service.append_cli_agent_lifecycle_event(
        "session-1",
        event="closed",
        terminal_session=terminal_session,
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"] = [
        item for item in state["conversations"][0]["messages"]
        if (item.get("metadata") or {}).get("kind") != "cli_agent_lifecycle"
    ]
    save_chat_state(tmp_path, state)

    detail = session_service.get_session_detail("session-1")

    lifecycle_messages = [
        item for item in detail["messages"]
        if (item.get("metadata") or {}).get("kind") == "cli_agent_lifecycle"
    ]
    assert len(lifecycle_messages) == 1
    assert lifecycle_messages[0]["metadata"]["lifecycleKey"] == "cli_agent_lifecycle:closed:cli-run-1"


def test_cli_agent_lifecycle_link_event_persists_cli_session_id(monkeypatch, tmp_path):
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

    event = session_service.append_cli_agent_lifecycle_event(
        "session-1",
        event="linked",
        terminal_session={
            "terminalSessionId": "term-1",
            "cliRunId": "cli-run-1",
            "adapterId": "mimo_code",
            "label": "MiMo Code",
            "sourceRunId": "run-1",
            "cwd": str(tmp_path),
            "cliSessionId": "ses_linked",
            "cliSessionIdSource": "session_discovery",
        },
    )

    state = load_chat_state(tmp_path)
    lifecycle_message = [
        item for item in state["conversations"][0]["messages"]
        if (item.get("metadata") or {}).get("kind") == "cli_agent_lifecycle"
    ][0]
    assert event is not None
    assert lifecycle_message["content"] == "MiMo Code 已连接 CLI 会话。"
    assert lifecycle_message["metadata"]["event"] == "linked"
    assert lifecycle_message["metadata"]["cliSessionId"] == "ses_linked"
    assert lifecycle_message["metadata"]["cliSessionIdSource"] == "session_discovery"
    assert lifecycle_message["metadata"]["folded"] is True


def test_cli_agent_terminal_reads_only_bounded_transcript_tail(tmp_path):
    transcript = tmp_path / "terminal.log"
    transcript.write_bytes(("old" * 10000 + "\x1b[2J最后一屏").encode("utf-8"))

    tail = terminal_service._read_transcript_tail(transcript, limit=8)

    assert len(tail) <= 8
    assert "最后一屏" in tail
    assert "oldold" not in tail


def test_cli_agent_terminal_scope_includes_mode(tmp_path):
    readonly = terminal_service._stable_terminal_session_id(
        adapter_id="mimo_code",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
        cwd=str(tmp_path),
        mode="readonly",
        task="同一个任务",
    )
    worktree = terminal_service._stable_terminal_session_id(
        adapter_id="mimo_code",
        source_session_id="session-1",
        source_message_id="message-1",
        source_run_id="run-1",
        cwd=str(tmp_path),
        mode="worktree",
        task="同一个任务",
    )
    assert readonly != worktree


def test_cli_agent_terminal_marks_plain_transcript_tail_replayable(tmp_path):
    transcript = tmp_path / "terminal.log"
    transcript.write_text("line 1\nline 2\n", encoding="utf-8")

    snapshot = terminal_service._read_transcript_snapshot(transcript, limit=120)

    assert snapshot["transcriptTail"].splitlines() == ["line 1", "line 2"]
    assert snapshot["transcriptTailReplayable"] is True
    assert snapshot["transcriptTailRenderReason"] == "raw_transcript_tail"


def test_cli_agent_terminal_blocks_unsafe_tui_transcript_tail_replay(tmp_path):
    transcript = tmp_path / "terminal.log"
    spinner_tail = "".join(
        f"\x1b[?2026h\x1b[?25l\x1b[34;6H\x1b[38;2;128;128;128m⠋\x1b[0m\x1b[57;6H\x1b[?25h\x1b[?2026l"
        for _ in range(40)
    )
    transcript.write_text(spinner_tail, encoding="utf-8")

    snapshot = terminal_service._read_transcript_snapshot(transcript, limit=120000)

    assert snapshot["transcriptTail"] == ""
    assert snapshot["transcriptTailReplayable"] is False
    assert snapshot["transcriptTailRenderReason"] == "unsafe_tui_control_tail"


def test_cli_agent_terminal_unsafe_tui_snapshot_does_not_send_raw_replay(tmp_path):
    transcript = tmp_path / "terminal.log"
    cursor_noise = "".join(f"\x1b[{row};5H" for row in range(1, 28))
    transcript.write_text(cursor_noise + "\x1b[2J\x1b[3;4H结论：模块拆分未完成", encoding="utf-8")

    snapshot = terminal_service._read_transcript_snapshot(transcript, limit=120000, rows=10, cols=40)

    assert snapshot["transcriptTail"] == ""
    assert snapshot["transcriptTailReplayable"] is False
    assert snapshot["transcriptTailRenderReason"] == "unsafe_tui_control_tail"
    assert "screenText" not in snapshot


def test_cli_agent_terminal_unsafe_tui_snapshot_blocks_leading_csi_fragment(tmp_path):
    transcript = tmp_path / "terminal.log"
    cursor_noise = "".join(f"\x1b[{row};5H" for row in range(1, 28))
    transcript.write_text(
        "2026h" + cursor_noise + "\x1b[2J\x1b[3;4H结论：模块拆分未完成",
        encoding="utf-8",
    )

    snapshot = terminal_service._read_transcript_snapshot(transcript, limit=120000, rows=10, cols=40)

    assert snapshot["transcriptTail"] == ""
    assert snapshot["transcriptTailReplayable"] is False
    assert snapshot["transcriptTailRenderReason"] == "unsafe_tui_control_tail"


def test_cli_agent_terminal_unsafe_tui_snapshot_blocks_leading_parameter_fragment(tmp_path):
    transcript = tmp_path / "terminal.log"
    cursor_noise = "".join(f"\x1b[{row};5H" for row in range(1, 28))
    transcript.write_text(
        ";10;1\n" + cursor_noise + "\x1b[2J\x1b[3;4H结论：模块拆分未完成",
        encoding="utf-8",
    )

    snapshot = terminal_service._read_transcript_snapshot(transcript, limit=120000, rows=10, cols=40)

    assert snapshot["transcriptTail"] == ""
    assert snapshot["transcriptTailReplayable"] is False
    assert snapshot["transcriptTailRenderReason"] == "unsafe_tui_control_tail"


def test_terminal_screen_buffer_keeps_split_escape_sequences_out_of_screen_text():
    buffer = TerminalScreenBuffer(rows=8, cols=40)

    buffer.feed("\x1b[?")
    snapshot = buffer.feed("2026h")
    assert snapshot.text == ""

    buffer.feed("\x1b[2")
    buffer.feed("J\x1b[3;")
    snapshot = buffer.feed("4H结论：模块拆分未完成")

    assert "2026h" not in snapshot.text
    assert "3;4H" not in snapshot.text
    assert "结论：模块拆分未完成" in snapshot.text

    snapshot = buffer.feed("\x1b[>4;1m可读内容")
    assert ">4;1m" not in snapshot.text
    assert "可读内容" in snapshot.text


def test_cli_agent_terminal_preserves_current_screen_when_transcript_snapshot_is_empty(tmp_path):
    transcript = tmp_path / "terminal.log"
    transcript.write_text("\x1b[?2026h\x1b[?25l\x1b[57;6H\x1b[?25h\x1b[?2026l" * 40, encoding="utf-8")
    state = {
        "screenText": "已有可见画面",
        "screenReplay": "\x1b[2J\x1b[H已有可见画面",
        "screenQuality": "screen_buffer",
        "screenRows": 10,
        "screenCols": 40,
        "screenParserVersion": terminal_service.SCREEN_BUFFER_PARSER_VERSION,
    }

    merged = terminal_service._merge_transcript_snapshot(
        state,
        terminal_service._read_transcript_snapshot(transcript, limit=120000, rows=10, cols=40),
    )

    assert merged["transcriptTail"] == ""
    assert merged["transcriptTailReplayable"] is False
    assert merged["screenText"] == "已有可见画面"
    assert merged["screenParserVersion"] == terminal_service.SCREEN_BUFFER_PARSER_VERSION


def test_cli_agent_live_snapshot_prefers_screen_without_reading_transcript_tail(monkeypatch, tmp_path):
    transcript = tmp_path / "terminal.log"
    transcript.write_text("line 1\nline 2\n", encoding="utf-8")
    state = {
        "rows": 10,
        "cols": 40,
        "screenText": "当前屏幕",
        "screenReplay": "\x1b[2J\x1b[H当前屏幕",
        "screenParserVersion": terminal_service.SCREEN_BUFFER_PARSER_VERSION,
    }

    def fail_read_tail(*args, **kwargs):
        raise AssertionError("live screen snapshots should not read transcript tail")

    monkeypatch.setattr(terminal_service, "_read_transcript_tail", fail_read_tail)

    snapshot = terminal_service._read_transcript_snapshot_for_state(
        transcript,
        state,
        include_transcript_tail=False,
    )

    assert snapshot["transcriptTail"] == ""
    assert snapshot["transcriptTailReplayable"] is False
    assert snapshot["transcriptTailRenderReason"] == "screen_snapshot_preferred"


def test_cli_agent_terminal_discards_legacy_screen_when_transcript_snapshot_is_empty(tmp_path):
    transcript = tmp_path / "terminal.log"
    transcript.write_text("\x1b[?2026h\x1b[?25l\x1b[57;6H\x1b[?25h\x1b[?2026l" * 40, encoding="utf-8")
    state = {
        "screenText": "38;2;255;255;255m旧污染画面",
        "screenReplay": "\x1b[2J\x1b[H38;2;255;255;255m旧污染画面",
        "screenQuality": "screen_buffer",
        "screenRows": 10,
        "screenCols": 40,
    }

    merged = terminal_service._merge_transcript_snapshot(
        state,
        terminal_service._read_transcript_snapshot(transcript, limit=120000, rows=10, cols=40),
    )

    assert merged["transcriptTail"] == ""
    assert merged["transcriptTailReplayable"] is False
    assert merged["screenText"] == ""
    assert not terminal_service._screen_initial_text(state)


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
