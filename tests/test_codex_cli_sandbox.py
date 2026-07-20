from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from core.infrastructure import codex_cli_sandbox
from tools.shell_tools import workspace_root_override


def test_resolver_prefers_user_local_binary_over_windowsapps_path(monkeypatch, tmp_path):
    local_executable = tmp_path / "OpenAI" / "Codex" / "bin" / "current" / "codex.exe"
    local_executable.parent.mkdir(parents=True)
    local_executable.write_bytes(b"codex")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(
        codex_cli_sandbox.shutil,
        "which",
        lambda name: r"C:\Program Files\WindowsApps\OpenAI.Codex\codex.exe",
    )

    resolved = codex_cli_sandbox._resolve_codex_executable()

    assert resolved == str(local_executable.resolve())


def test_relative_cwd_resolves_from_active_session_workspace(tmp_path):
    candidate_worktree = tmp_path / "candidate"
    candidate_worktree.mkdir()

    with workspace_root_override(candidate_worktree):
        resolved = codex_cli_sandbox._resolve_cwd(".")

    assert resolved == candidate_worktree.resolve()


class _CompletedProcess:
    pid = 4242
    returncode = 0

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        return "sandbox ok\n", ""


def test_execute_uses_native_codex_sandbox_without_shell(monkeypatch, tmp_path):
    recorded = {}

    monkeypatch.setattr(codex_cli_sandbox.os, "name", "nt")
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: r"C:\Codex\codex.exe",
    )
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_windows_command_interpreter",
        lambda: r"C:\Windows\System32\cmd.exe",
    )

    def fake_popen(argv, **kwargs):
        recorded["argv"] = argv
        recorded["kwargs"] = kwargs
        recorded["sitecustomize_exists"] = (
            Path(kwargs["env"]["VIBELUTION_CODEX_SANDBOX_TEMP"])
            / "sitecustomize.py"
        ).is_file()
        return _CompletedProcess()

    monkeypatch.setattr(codex_cli_sandbox.subprocess, "Popen", fake_popen)

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        command="dir",
        timeout=5,
        cwd=str(tmp_path),
    )

    assert result == "sandbox ok"
    assert recorded["argv"] == [
        r"C:\Codex\codex.exe",
        "sandbox",
        "-c",
        'windows.sandbox="unelevated"',
        "-c",
        'sandbox_mode="workspace-write"',
        "--",
        r"C:\Windows\System32\cmd.exe",
        "/d",
        "/s",
        "/c",
        "dir",
    ]
    assert recorded["kwargs"]["shell"] is False
    assert recorded["kwargs"]["cwd"] == str(tmp_path)
    assert recorded["kwargs"]["env"]["TMP"].startswith(
        str(tmp_path / ".runtime" / "codex-cli")
    )
    assert "--basetemp=.runtime/codex-cli/" in recorded["kwargs"]["env"]["PYTEST_ADDOPTS"]
    assert recorded["sitecustomize_exists"] is True
    assert not list((tmp_path / ".runtime" / "codex-cli").glob("*"))


def test_sandbox_runs_rewritten_python_command_without_cmd_quote_roundtrip(monkeypatch):
    monkeypatch.setattr(codex_cli_sandbox.os, "name", "nt")
    python_executable = r"C:\Project\.venv\Scripts\python.exe"
    route = SimpleNamespace(
        route="cmd",
        command=f'"{python_executable}" -c "print(123)"',
    )

    argv = codex_cli_sandbox._sandbox_argv(r"C:\Codex\codex.exe", route)

    assert argv[-3:] == [python_executable, "-c", "print(123)"]
    assert "cmd.exe" not in argv


def test_execute_fails_closed_when_native_codex_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_cli_sandbox, "_resolve_codex_executable", lambda: "")

    def unexpected_popen(*args, **kwargs):
        raise AssertionError("missing sandbox must not execute the command")

    monkeypatch.setattr(codex_cli_sandbox.subprocess, "Popen", unexpected_popen)

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        command="echo must-not-run",
        cwd=str(tmp_path),
    )

    assert "Codex CLI 沙盒不可用" in result
    assert "未回退到非沙盒模式" in result


def test_execute_rejects_dangerous_command_before_start(monkeypatch, tmp_path):
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: r"C:\Codex\codex.exe",
    )

    def unexpected_popen(*args, **kwargs):
        raise AssertionError("dangerous command must not reach the sandbox process")

    monkeypatch.setattr(codex_cli_sandbox.subprocess, "Popen", unexpected_popen)

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        command="rmdir /s /q C:\\",
        cwd=str(tmp_path),
    )

    assert "[安全拦截]" in result


class _RunningProcess:
    pid = 4343
    returncode = None

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(cmd="sandbox", timeout=timeout)
        return "", ""

    def wait(self, timeout=None):
        self.returncode = 1


def test_execute_terminates_sandbox_when_cancelled(monkeypatch, tmp_path):
    process = _RunningProcess()
    terminated = {"value": False}

    monkeypatch.setattr(codex_cli_sandbox.os, "name", "nt")
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: r"C:\Codex\codex.exe",
    )
    monkeypatch.setattr(
        codex_cli_sandbox.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    def fake_terminate(target):
        assert target is process
        terminated["value"] = True
        process.returncode = 1

    monkeypatch.setattr(codex_cli_sandbox, "_terminate_process_tree", fake_terminate)

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        command="python -c \"while True: pass\"",
        timeout=30,
        cwd=str(tmp_path),
        _cancel_checker=lambda: "用户停止",
    )

    assert terminated["value"] is True
    assert "[取消]" in result
    assert "用户停止" in result
