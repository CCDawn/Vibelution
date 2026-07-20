"""Execute Agent CLI commands through the Codex native Windows sandbox."""

from __future__ import annotations

import hashlib
import locale
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from core.logging import debug_logger as _debug_logger
from scripts.windowless_subprocess import no_window_subprocess_kwargs


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_POLL_INTERVAL_SECONDS = 0.2


def _log_outcome(
    command_hash: str,
    status: str,
    *,
    reason: str,
    started_at: float | None = None,
    exit_code: int | None = None,
) -> None:
    fields = [
        f"commandHash={command_hash}",
        f"status={status}",
        f"reason={reason}",
    ]
    if exit_code is not None:
        fields.append(f"exitCode={exit_code}")
    if started_at is not None:
        fields.append(f"durationMs={int((time.monotonic() - started_at) * 1000)}")
    message = f"[Codex CLI 沙盒] 结果 {' '.join(fields)}"
    if status == "completed":
        _debug_logger.info(message)
    else:
        _debug_logger.warning(message)


def _resolve_codex_executable() -> str:
    """Resolve a native Codex executable without relying on shell wrappers."""

    local_bin = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    if local_bin.is_dir():
        try:
            candidates = sorted(
                local_bin.glob("*/codex.exe"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            candidates = []
        if candidates:
            return str(candidates[0].resolve())

    resolved = shutil.which("codex.exe")
    if resolved and Path(resolved).is_file():
        return str(Path(resolved).resolve())
    return ""


def _resolve_cwd(cwd: str | None) -> Path:
    raw = Path(str(cwd or "").strip()) if str(cwd or "").strip() else PROJECT_ROOT
    if not raw.is_absolute():
        raw = PROJECT_ROOT / raw
    return raw.resolve()


def _windows_command_interpreter() -> str:
    candidate = str(os.environ.get("COMSPEC") or "").strip()
    if candidate and Path(candidate).is_file():
        return candidate
    system_root = str(os.environ.get("SystemRoot") or r"C:\Windows").strip()
    fallback = Path(system_root) / "System32" / "cmd.exe"
    return str(fallback) if fallback.is_file() else "cmd.exe"


def _powershell_executable() -> str:
    resolved = shutil.which("powershell.exe")
    if resolved and Path(resolved).is_file():
        return resolved
    system_root = str(os.environ.get("SystemRoot") or r"C:\Windows").strip()
    fallback = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(fallback) if fallback.is_file() else "powershell.exe"


def _sandbox_argv(
    executable: str,
    route: Any,
    *,
    git_bash_executable: str = "",
) -> list[str]:
    if os.name != "nt":
        raise RuntimeError("当前 Codex CLI 沙盒接入仅支持原生 Windows")
    prefix = [
        executable,
        "sandbox",
        "-c",
        'sandbox_mode="workspace-write"',
        "--",
    ]
    if route.route == "powershell":
        return prefix + [
            _powershell_executable(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            route.command,
        ]
    if route.route == "git_bash" and git_bash_executable:
        return prefix + [git_bash_executable, "-c", route.command]
    return prefix + [
        _windows_command_interpreter(),
        "/d",
        "/s",
        "/c",
        route.command,
    ]


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            **no_window_subprocess_kwargs(),
        )
    except Exception:
        try:
            process.terminate()
        except Exception:
            pass
    try:
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _collect_output(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=2)
    except Exception:
        stdout, stderr = "", ""
    return str(stdout or ""), str(stderr or "")


def _format_output(stdout: str, stderr: str, returncode: int | None) -> str:
    parts = []
    if stdout:
        parts.append(stdout.strip())
    if stderr:
        parts.append(f"[STDERR]\n{stderr.strip()}")
    if not parts:
        parts.append("[命令执行完成，无输出]")
    output = "\n\n".join(parts)
    code = int(returncode or 0)
    if code == 0:
        return output
    has_error_keywords = any(
        keyword in output.lower()
        for keyword in (
            "error",
            "exception",
            "failed",
            "fail",
            "traceback",
            "syntaxerror",
            "indentationerror",
        )
    )
    prefix = "EXEC FAILURE" if has_error_keywords else "WARNING"
    return f"[{prefix} | Exit Code: {code}]\n{output}"


def execute_codex_sandbox_command(
    command: str = "",
    timeout: int = 60,
    cwd: str | None = None,
    _cancel_checker: Callable[[], str] | None = None,
) -> str:
    """Run one shell command in the Codex workspace-write Windows sandbox."""

    normalized_command = str(command or "").strip()
    if not normalized_command:
        return "[错误] 命令不能为空"
    command_hash = hashlib.sha256(normalized_command.encode("utf-8")).hexdigest()[:12]

    from tools.shell_tools import _is_command_dangerous
    from tools.shell_tools import _find_git_bash
    from tools.shell_tools import classify_shell_command

    is_dangerous, message = _is_command_dangerous(normalized_command)
    if is_dangerous:
        _log_outcome(command_hash, "blocked", reason="dangerous_command")
        return f"[安全拦截] {message}\n该危险命令已被系统安全策略禁止执行。"

    workdir = _resolve_cwd(cwd)
    if not workdir.is_dir():
        _log_outcome(command_hash, "unavailable", reason="invalid_cwd")
        return f"[错误] 工作目录不存在: {workdir}"

    route = classify_shell_command(normalized_command)
    if route.blocked:
        _log_outcome(command_hash, "blocked", reason=route.reason or "shell_route")
        return route.error

    executable = _resolve_codex_executable()
    if not executable:
        _log_outcome(command_hash, "unavailable", reason="codex_executable_missing")
        return (
            "[错误] Codex CLI 沙盒不可用：未找到原生 codex.exe。"
            "命令未执行，也未回退到非沙盒模式。"
        )

    try:
        timeout_seconds = max(int(timeout), 1)
    except (TypeError, ValueError):
        timeout_seconds = 60

    argv = _sandbox_argv(
        executable,
        route,
        git_bash_executable=_find_git_bash() if route.route == "git_bash" else "",
    )
    _debug_logger.info(
        f"[Codex CLI 沙盒] 启动 commandHash={command_hash} "
        f"cwd={workdir} timeout={timeout_seconds}s"
    )
    started_at = time.monotonic()
    process: subprocess.Popen[str] | None = None
    try:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        process = subprocess.Popen(
            argv,
            shell=False,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=encoding,
            errors="replace",
            **no_window_subprocess_kwargs(),
        )
        deadline = started_at + timeout_seconds
        while True:
            cancellation_reason = ""
            if callable(_cancel_checker):
                try:
                    cancellation_reason = str(_cancel_checker() or "").strip()
                except Exception:
                    cancellation_reason = ""
            if cancellation_reason:
                _terminate_process_tree(process)
                stdout, stderr = _collect_output(process)
                preview = _format_output(stdout, stderr, process.returncode)
                suffix = "" if preview == "[命令执行完成，无输出]" else f"\n\n{preview}"
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                _log_outcome(
                    command_hash,
                    "cancelled",
                    reason="stop_requested",
                    started_at=started_at,
                    exit_code=process.returncode,
                )
                return (
                    f"[取消] 命令已因停止请求终止：{cancellation_reason} "
                    f"({elapsed_ms}ms){suffix}"
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_tree(process)
                _collect_output(process)
                _log_outcome(
                    command_hash,
                    "timeout",
                    reason="deadline_exceeded",
                    started_at=started_at,
                    exit_code=process.returncode,
                )
                return (
                    f"[超时] 命令执行超过 {timeout_seconds} 秒被强制终止。\n"
                    "请检查命令是否陷入死循环。"
                )
            try:
                stdout, stderr = process.communicate(
                    timeout=min(_POLL_INTERVAL_SECONDS, remaining)
                )
                result = _format_output(
                    str(stdout or ""),
                    str(stderr or ""),
                    process.returncode,
                )
                _log_outcome(
                    command_hash,
                    "completed",
                    reason="process_exit",
                    started_at=started_at,
                    exit_code=process.returncode,
                )
                return result
            except subprocess.TimeoutExpired:
                continue
    except FileNotFoundError:
        _log_outcome(
            command_hash,
            "unavailable",
            reason="sandbox_process_missing",
            started_at=started_at,
        )
        return (
            "[错误] Codex CLI 沙盒启动失败：codex.exe 或命令解释器不存在。"
            "命令未执行，也未回退到非沙盒模式。"
        )
    except PermissionError:
        _log_outcome(
            command_hash,
            "unavailable",
            reason="sandbox_process_permission_denied",
            started_at=started_at,
        )
        return (
            "[权限错误] 无法启动 Codex CLI 沙盒。"
            "命令未执行，也未回退到非沙盒模式。"
        )
    except Exception as exc:
        _log_outcome(
            command_hash,
            "failed",
            reason=type(exc).__name__,
            started_at=started_at,
        )
        if process is not None:
            _terminate_process_tree(process)
        return (
            f"[执行错误] Codex CLI 沙盒启动失败: {type(exc).__name__}: {exc}\n"
            "命令未执行，也未回退到非沙盒模式。"
        )
