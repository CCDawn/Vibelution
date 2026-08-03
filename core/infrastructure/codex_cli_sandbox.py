"""Execute Agent CLI commands through the automatically selected native sandbox.

The host platform, Codex CLI executable and shell are resolved automatically at
startup/first use; Agent-facing contracts (``exec_command`` / ``cli_tool`` /
``write_stdin``) never select Windows, Linux, Shell or Codex backend.  Public
session/cwd/security/timeout/cancel orchestration stays here; platform-specific
executable/shell/sandbox argv lives in ``core.infrastructure.codex_sandbox``.
"""

from __future__ import annotations

import hashlib
import locale
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from core.logging import debug_logger as _debug_logger
from core.infrastructure.codex_sandbox.environment import (
    sandbox_process_environment as _adapter_sandbox_process_environment,
)
from core.infrastructure.codex_sandbox.platform import host_platform as _host_platform
from core.infrastructure.codex_sandbox.process import (
    sandbox_popen_kwargs as _sandbox_popen_kwargs,
    terminate_process_tree as _adapter_terminate_process_tree,
)
from core.infrastructure.codex_sandbox.resolver import (
    resolve_codex_executable as _resolve_codex_executable_impl,
)
from core.infrastructure.codex_sandbox.shell import (
    create_shell_adapter,
    powershell_executable as _powershell_executable,
    unix_shell_executable as _unix_shell_executable,
    windows_command_interpreter as _windows_command_interpreter,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_POLL_INTERVAL_SECONDS = 0.2
_TERMINAL_SESSION_MAX_OUTPUT_CHARS = 120_000
_TERMINAL_SESSION_TTL_SECONDS = 15 * 60
_TERMINAL_SESSION_MAX_LIFETIME_SECONDS = 15 * 60
_WORKSPACE_WRITE_SANDBOX_MODE = "workspace_write"
_DANGER_FULL_ACCESS_SANDBOX_MODE = "danger_full_access"


def _current_agent_sandbox_mode() -> str:
    """Read the immutable turn permission snapshot; default to sandboxed."""
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
    except Exception:
        runtime = {}
    permissions = (
        runtime.get("runtimePermissions")
        if isinstance(runtime, dict)
        and isinstance(runtime.get("runtimePermissions"), dict)
        else {}
    )
    sandbox_mode = str(permissions.get("sandboxMode") or "").strip()
    if sandbox_mode == _DANGER_FULL_ACCESS_SANDBOX_MODE:
        return sandbox_mode
    return _WORKSPACE_WRITE_SANDBOX_MODE


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
    if status in {"completed", "started"}:
        _debug_logger.info(message)
    else:
        _debug_logger.warning(message)


def _resolve_codex_executable() -> str:
    """Resolve the native Codex executable for the live host (fail closed)."""
    return _resolve_codex_executable_impl(
        platform=_host_platform(),
        environ=os.environ,
        which=shutil.which,
    )


def _resolve_cwd(cwd: str | None) -> Path:
    from tools.shell_tools import _get_workspace_root, get_workspace_root_override

    active_workspace = _get_workspace_root().resolve()
    workspace_root = active_workspace if (active_workspace / ".git").exists() else PROJECT_ROOT
    raw = Path(str(cwd or "").strip()) if str(cwd or "").strip() else workspace_root
    if not raw.is_absolute():
        raw = workspace_root / raw
    resolved = raw.resolve()
    if (
        get_workspace_root_override() is not None
        and _current_agent_sandbox_mode() != _DANGER_FULL_ACCESS_SANDBOX_MODE
        and resolved != workspace_root
        and not resolved.is_relative_to(workspace_root)
    ):
        raise PermissionError(
            f"工作目录超出 Agent 工作区边界: {resolved}; allowed={workspace_root}"
        )
    return resolved




def _sandbox_process_environment(
    workdir: Path,
    command_hash: str,
    *,
    environment_policy: str = "default",
) -> tuple[dict[str, str], Path]:
    """Build the sandbox child environment for the live host platform."""
    return _adapter_sandbox_process_environment(
        workdir,
        command_hash,
        environment_policy=environment_policy,
        platform=_host_platform(),
    )


def _cleanup_sandbox_temp(workdir: Path, sandbox_temp: Path | None) -> None:
    if sandbox_temp is None:
        return
    temp_root = (workdir / ".runtime" / "codex-cli").resolve()
    resolved = sandbox_temp.resolve()
    if resolved == temp_root or not resolved.is_relative_to(temp_root):
        return
    shutil.rmtree(resolved, ignore_errors=True)


def _sandbox_argv(
    executable: str,
    route: Any,
    *,
    git_bash_executable: str = "",
    sandbox_mode: str = _WORKSPACE_WRITE_SANDBOX_MODE,
) -> list[str]:
    """Build the sandbox argv for the live host platform (auto-selected)."""
    return create_shell_adapter(
        platform=_host_platform(),
        windows_command_interpreter_fn=_windows_command_interpreter,
        powershell_executable_fn=_powershell_executable,
        unix_shell_executable_fn=_unix_shell_executable,
        which=shutil.which,
    ).sandbox_argv(
        executable,
        route,
        git_bash_executable=git_bash_executable,
        sandbox_mode=sandbox_mode,
    )


def _describe_sandbox_route(route: Any) -> tuple[bool, str, str]:
    """Return ``(is_native_windows_command, command_env_var, route_label)``."""
    return create_shell_adapter(
        platform=_host_platform(),
        windows_command_interpreter_fn=_windows_command_interpreter,
        powershell_executable_fn=_powershell_executable,
        unix_shell_executable_fn=_unix_shell_executable,
        which=shutil.which,
    ).describe_route(route)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate the sandbox process tree for the live host platform."""
    _adapter_terminate_process_tree(process, platform=_host_platform())


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


def _clamp_terminal_timeout(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(minimum, min(normalized, maximum))


class _SandboxTerminalSession:
    """One sandboxed process with bounded, pollable output and stdin support.

    The session is intentionally in-memory.  A backend restart makes a live child
    process unavailable rather than attempting to reattach to an unsafe shell.
    """

    def __init__(
        self,
        *,
        session_id: str,
        process: Any,
        command_hash: str,
        workdir: Path,
        sandbox_temp: Path,
        timeout_seconds: int,
    ) -> None:
        self.session_id = session_id
        self.process = process
        self.command_hash = command_hash
        self.workdir = workdir
        self.sandbox_temp = sandbox_temp
        self.started_at = time.monotonic()
        self.idle_timeout_seconds = timeout_seconds
        self.hard_deadline = self.started_at + _TERMINAL_SESSION_MAX_LIFETIME_SECONDS
        self.deadline = min(
            self.started_at + self.idle_timeout_seconds,
            self.hard_deadline,
        )
        self.last_accessed_at = self.started_at
        self._status = "running"
        self._lock = threading.RLock()
        self._output_ready = threading.Event()
        self._stdout_pending = ""
        self._stderr_pending = ""
        self._total_output_chars = 0
        self._output_truncated = False
        self._outcome_logged = False
        self._final_snapshot: dict[str, Any] | None = None
        self._reader_threads = [
            threading.Thread(target=self._reader_loop, args=("stdout",), daemon=True, name=f"codex-sandbox-out-{session_id}"),
            threading.Thread(target=self._reader_loop, args=("stderr",), daemon=True, name=f"codex-sandbox-err-{session_id}"),
        ]

    def start(self) -> None:
        for reader in self._reader_threads:
            reader.start()

    def _reader_loop(self, stream_name: str) -> None:
        stream = getattr(self.process, stream_name, None)
        if stream is None:
            return
        while True:
            try:
                chunk = str(stream.read(1) or "")
            except Exception:
                return
            if not chunk:
                return
            with self._lock:
                self._total_output_chars += len(chunk)
                attribute = "_stdout_pending" if stream_name == "stdout" else "_stderr_pending"
                existing = str(getattr(self, attribute) or "")
                combined = existing + chunk
                if len(combined) > _TERMINAL_SESSION_MAX_OUTPUT_CHARS:
                    combined = combined[-_TERMINAL_SESSION_MAX_OUTPUT_CHARS :]
                    self._output_truncated = True
                setattr(self, attribute, combined)
                self._output_ready.set()

    def _is_alive(self) -> bool:
        try:
            return self.process.poll() is None
        except Exception:
            return False

    def _expire_if_needed(self) -> None:
        if self._status != "running" or time.monotonic() < self.deadline:
            return
        self._status = "timeout"
        _terminate_process_tree(self.process)

    def refresh_client_lease(self) -> None:
        """Keep a live process available across model and approval round trips."""

        now = time.monotonic()
        with self._lock:
            self.last_accessed_at = now
            if (
                self._status == "running"
                and now < self.hard_deadline
                and self._is_alive()
            ):
                self.deadline = min(
                    now + self.idle_timeout_seconds,
                    self.hard_deadline,
                )

    def _terminal_status(self) -> str:
        self._expire_if_needed()
        if self._status != "running":
            return self._status
        if self._is_alive():
            return "running"
        return "completed"

    def _drain_output(self, *, max_output_chars: int) -> tuple[str, str, bool, int]:
        with self._lock:
            stdout = self._stdout_pending
            stderr = self._stderr_pending
            self._stdout_pending = ""
            self._stderr_pending = ""
            self._output_ready.clear()
            total = self._total_output_chars
            truncated = self._output_truncated
        limit = _clamp_terminal_timeout(max_output_chars, default=12000, minimum=256, maximum=60000)
        combined_length = len(stdout) + len(stderr)
        if combined_length > limit:
            keep_stdout = min(len(stdout), max(0, limit // 2))
            keep_stderr = max(0, limit - keep_stdout)
            stdout = stdout[:keep_stdout]
            stderr = stderr[-keep_stderr:] if keep_stderr else ""
            truncated = True
        return stdout, stderr, truncated, total

    def _log_terminal_outcome_once(self, status: str, exit_code: int | None) -> None:
        if status == "running" or self._outcome_logged:
            return
        self._outcome_logged = True
        _log_outcome(
            self.command_hash,
            status,
            reason="terminal_session_exit",
            started_at=self.started_at,
            exit_code=exit_code,
        )
        _cleanup_sandbox_temp(self.workdir, self.sandbox_temp)

    def snapshot(self, *, max_output_chars: int) -> dict[str, Any]:
        self.last_accessed_at = time.monotonic()
        status = self._terminal_status()
        if status != "running" and self._final_snapshot is not None:
            return dict(self._final_snapshot)
        if status != "running":
            for reader in self._reader_threads:
                if reader.ident is not None and reader.is_alive():
                    reader.join(timeout=1.0)
        stdout, stderr, truncated, original_length = self._drain_output(max_output_chars=max_output_chars)
        try:
            exit_code = self.process.returncode if not self._is_alive() else None
        except Exception:
            exit_code = None
        self._log_terminal_outcome_once(status, exit_code)
        formatted_output = _format_output(stdout, stderr, exit_code) if (stdout or stderr or status != "running") else ""
        outcome_status = "running"
        if status == "completed":
            outcome_status = "success" if exit_code in (None, 0) else "nonzero_exit"
        elif status in {"timeout", "cancelled", "failed"}:
            outcome_status = status
        payload: dict[str, Any] = {
            "status": status,
            "terminalSessionId": self.session_id,
            "sessionOpen": status == "running",
            "exitCode": exit_code,
            "outcomeStatus": outcome_status,
            "stdout": stdout,
            "stderr": stderr,
            "formattedOutput": formatted_output,
            "durationMs": int((time.monotonic() - self.started_at) * 1000),
            "timedOut": status == "timeout",
            "truncated": bool(truncated),
            "originalLength": original_length,
        }
        if status in {"failed", "timeout", "cancelled"} or outcome_status == "nonzero_exit":
            payload["failureClass"] = "timeout" if status == "timeout" else "process_exit"
        result = {key: value for key, value in payload.items() if value not in {None, ""}}
        if status != "running":
            self._final_snapshot = dict(result)
        return result

    def wait_for_update(
        self,
        *,
        yield_time_ms: int,
        max_output_chars: int,
        cancel_checker: Callable[[], str] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + _clamp_terminal_timeout(
            yield_time_ms,
            default=10_000,
            minimum=0,
            maximum=30_000,
        ) / 1000.0
        while True:
            cancellation_reason = ""
            if callable(cancel_checker):
                try:
                    cancellation_reason = str(cancel_checker() or "").strip()
                except Exception:
                    cancellation_reason = ""
            if cancellation_reason:
                self._status = "cancelled"
                _terminate_process_tree(self.process)
                payload = self.snapshot(max_output_chars=max_output_chars)
                payload["cancelReason"] = cancellation_reason
                return payload
            if self._terminal_status() != "running" or self._output_ready.is_set() or time.monotonic() >= deadline:
                return self.snapshot(max_output_chars=max_output_chars)
            self._output_ready.wait(timeout=min(0.1, max(0.0, deadline - time.monotonic())))

    def send_input(self, chars: str) -> str:
        if self._terminal_status() != "running":
            return "terminal_not_running"
        if not chars:
            return ""
        stdin = getattr(self.process, "stdin", None)
        if stdin is None:
            return "stdin_unavailable"
        try:
            stdin.write(chars)
            stdin.flush()
        except Exception:
            return "stdin_write_failed"
        return ""


_SANDBOX_TERMINAL_SESSIONS: dict[str, _SandboxTerminalSession] = {}
_SANDBOX_TERMINAL_SESSIONS_LOCK = threading.RLock()


def _prune_sandbox_terminal_sessions() -> None:
    now = time.monotonic()
    with _SANDBOX_TERMINAL_SESSIONS_LOCK:
        stale_ids: list[str] = []
        for session_id, session in _SANDBOX_TERMINAL_SESSIONS.items():
            status = session._terminal_status()
            if status == "running":
                continue
            try:
                exit_code = session.process.returncode
            except Exception:
                exit_code = None
            session._log_terminal_outcome_once(status, exit_code)
            if now - session.last_accessed_at > _TERMINAL_SESSION_TTL_SECONDS:
                stale_ids.append(session_id)
        for session_id in stale_ids:
            _SANDBOX_TERMINAL_SESSIONS.pop(session_id, None)


def _terminal_error_payload(code: str, message: str, *, session_id: str = "") -> dict[str, Any]:
    payload = {
        "status": "failed",
        "code": code,
        "message": message,
        "failureClass": code.lower(),
    }
    if session_id:
        payload["terminalSessionId"] = session_id
    return payload


def start_codex_sandbox_terminal_session(
    command: str = "",
    *,
    timeout: int = 60,
    cwd: str | None = None,
    yield_time_ms: int = 10_000,
    max_output_chars: int = 12_000,
    _cancel_checker: Callable[[], str] | None = None,
    _environment_policy: str = "default",
) -> dict[str, Any]:
    """Start one sandboxed command and return a bounded Codex-style process snapshot."""

    normalized_command = str(command or "").strip()
    if not normalized_command:
        return _terminal_error_payload("MISSING_COMMAND", "exec_command 需要提供 cmd 参数。")
    command_hash = hashlib.sha256(normalized_command.encode("utf-8")).hexdigest()[:12]
    from tools.shell_tools import _find_git_bash, _is_command_dangerous, classify_shell_command

    sandbox_mode = _current_agent_sandbox_mode()
    is_dangerous, message = _is_command_dangerous(normalized_command)
    if is_dangerous and sandbox_mode != _DANGER_FULL_ACCESS_SANDBOX_MODE:
        _log_outcome(command_hash, "blocked", reason="dangerous_command")
        return _terminal_error_payload("DANGEROUS_COMMAND", message)
    try:
        workdir = _resolve_cwd(cwd)
    except PermissionError as exc:
        _log_outcome(command_hash, "blocked", reason="cwd_outside_sandbox")
        return _terminal_error_payload("CWD_OUTSIDE_SANDBOX", str(exc))
    if not workdir.is_dir():
        _log_outcome(command_hash, "unavailable", reason="invalid_cwd")
        return _terminal_error_payload("INVALID_CWD", f"工作目录不存在: {workdir}")
    route = classify_shell_command(normalized_command)
    if route.blocked:
        _log_outcome(command_hash, "blocked", reason=route.reason or "shell_route")
        return _terminal_error_payload("SHELL_ROUTE_BLOCKED", str(route.error or "命令路由被拦截。"))
    executable = (
        _resolve_codex_executable()
        if sandbox_mode == _WORKSPACE_WRITE_SANDBOX_MODE
        else ""
    )
    if sandbox_mode == _WORKSPACE_WRITE_SANDBOX_MODE and not executable:
        _log_outcome(command_hash, "unavailable", reason="codex_executable_missing")
        return _terminal_error_payload("CODEX_SANDBOX_UNAVAILABLE", "未找到原生 Codex CLI 可执行文件（codex.exe / codex）；命令未执行。")
    timeout_seconds = _clamp_terminal_timeout(timeout, default=60, minimum=1, maximum=_TERMINAL_SESSION_MAX_LIFETIME_SECONDS)
    is_native_windows_command, command_env_name, _route_label = _describe_sandbox_route(
        route
    )
    argv = _sandbox_argv(
        executable,
        route,
        git_bash_executable=_find_git_bash() if route.route == "git_bash" else "",
        sandbox_mode=sandbox_mode,
    )
    sandbox_temp: Path | None = None
    try:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        environment, sandbox_temp = _sandbox_process_environment(
            workdir,
            command_hash,
            environment_policy=_environment_policy,
        )
        environment.pop(command_env_name, None)
        if is_native_windows_command:
            environment[command_env_name] = route.command
        process = subprocess.Popen(
            argv,
            shell=False,
            cwd=str(workdir),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=encoding,
            errors="replace",
            **_sandbox_popen_kwargs(platform=_host_platform()),
        )
    except (FileNotFoundError, PermissionError) as exc:
        _cleanup_sandbox_temp(workdir, sandbox_temp)
        _log_outcome(command_hash, "unavailable", reason=type(exc).__name__)
        return _terminal_error_payload("SANDBOX_START_FAILED", "Codex CLI 沙盒启动失败；命令未回退到非沙盒模式。")
    except Exception as exc:
        _cleanup_sandbox_temp(workdir, sandbox_temp)
        _log_outcome(command_hash, "failed", reason=type(exc).__name__)
        return _terminal_error_payload("SANDBOX_START_FAILED", f"Codex CLI 沙盒启动失败: {type(exc).__name__}")
    if sandbox_temp is None:
        _terminate_process_tree(process)
        return _terminal_error_payload("SANDBOX_TEMP_UNAVAILABLE", "沙盒临时目录不可用。")
    _prune_sandbox_terminal_sessions()
    session_id = f"sandbox-{uuid.uuid4().hex[:16]}"
    session = _SandboxTerminalSession(
        session_id=session_id,
        process=process,
        command_hash=command_hash,
        workdir=workdir,
        sandbox_temp=sandbox_temp,
        timeout_seconds=timeout_seconds,
    )
    with _SANDBOX_TERMINAL_SESSIONS_LOCK:
        _SANDBOX_TERMINAL_SESSIONS[session_id] = session
    session.start()
    _log_outcome(command_hash, "started", reason="terminal_session_started", started_at=session.started_at)
    return session.wait_for_update(
        yield_time_ms=yield_time_ms,
        max_output_chars=max_output_chars,
        cancel_checker=_cancel_checker,
    )


def write_codex_sandbox_terminal_stdin(
    terminal_session_id: str = "",
    chars: str = "",
    *,
    yield_time_ms: int = 1_000,
    max_output_chars: int = 12_000,
    _cancel_checker: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Send stdin to a live sandbox command or poll its bounded output."""

    session_id = str(terminal_session_id or "").strip()
    if not session_id:
        return _terminal_error_payload("MISSING_SESSION_ID", "write_stdin 需要提供 session_id 参数。")
    with _SANDBOX_TERMINAL_SESSIONS_LOCK:
        session = _SANDBOX_TERMINAL_SESSIONS.get(session_id)
    if session is not None:
        session.refresh_client_lease()
    _prune_sandbox_terminal_sessions()
    with _SANDBOX_TERMINAL_SESSIONS_LOCK:
        session = _SANDBOX_TERMINAL_SESSIONS.get(session_id)
    if session is None:
        return _terminal_error_payload("TERMINAL_SESSION_NOT_FOUND", "终端会话不存在、已过期或后端已重启。", session_id=session_id)
    normalized_chars = str(chars or "")
    if not normalized_chars:
        return session.wait_for_update(
            yield_time_ms=yield_time_ms,
            max_output_chars=max_output_chars,
            cancel_checker=_cancel_checker,
        )
    input_error = session.send_input(normalized_chars)
    if input_error:
        message = {
            "terminal_not_running": "终端会话已结束，不能继续写入。",
            "stdin_unavailable": "终端会话不支持标准输入。",
            "stdin_write_failed": "写入终端标准输入失败。",
        }.get(input_error, "终端输入不可用。")
        payload = session.snapshot(max_output_chars=max_output_chars)
        payload.update(_terminal_error_payload("TERMINAL_STDIN_UNAVAILABLE", message, session_id=session_id))
        return payload
    return session.wait_for_update(
        yield_time_ms=yield_time_ms,
        max_output_chars=max_output_chars,
        cancel_checker=_cancel_checker,
    )


def execute_codex_sandbox_command(
    command: str = "",
    timeout: int = 60,
    cwd: str | None = None,
    _cancel_checker: Callable[[], str] | None = None,
    _environment_policy: str = "default",
) -> str:
    """Run one shell command in the automatically selected native sandbox."""

    normalized_command = str(command or "").strip()
    if not normalized_command:
        return "[错误] 命令不能为空"
    command_hash = hashlib.sha256(normalized_command.encode("utf-8")).hexdigest()[:12]

    from tools.shell_tools import _is_command_dangerous
    from tools.shell_tools import _find_git_bash
    from tools.shell_tools import classify_shell_command

    sandbox_mode = _current_agent_sandbox_mode()
    is_dangerous, message = _is_command_dangerous(normalized_command)
    if is_dangerous and sandbox_mode != _DANGER_FULL_ACCESS_SANDBOX_MODE:
        _log_outcome(command_hash, "blocked", reason="dangerous_command")
        return f"[安全拦截] {message}\n该危险命令已被系统安全策略禁止执行。"

    try:
        workdir = _resolve_cwd(cwd)
    except PermissionError as exc:
        _log_outcome(command_hash, "blocked", reason="cwd_outside_sandbox")
        return f"[安全拦截] {exc}"
    if not workdir.is_dir():
        _log_outcome(command_hash, "unavailable", reason="invalid_cwd")
        return f"[错误] 工作目录不存在: {workdir}"

    route = classify_shell_command(normalized_command)
    if route.blocked:
        _log_outcome(command_hash, "blocked", reason=route.reason or "shell_route")
        return route.error

    executable = (
        _resolve_codex_executable()
        if sandbox_mode == _WORKSPACE_WRITE_SANDBOX_MODE
        else ""
    )
    if sandbox_mode == _WORKSPACE_WRITE_SANDBOX_MODE and not executable:
        _log_outcome(command_hash, "unavailable", reason="codex_executable_missing")
        return (
            "[错误] Codex CLI 沙盒不可用：未找到原生 Codex CLI（codex.exe / codex）。"
            "命令未执行，也未回退到非沙盒模式。"
        )

    try:
        timeout_seconds = max(int(timeout), 1)
    except (TypeError, ValueError):
        timeout_seconds = 60

    is_native_windows_command, command_env_name, route_label = _describe_sandbox_route(
        route
    )
    argv = _sandbox_argv(
        executable,
        route,
        git_bash_executable=_find_git_bash() if route.route == "git_bash" else "",
        sandbox_mode=sandbox_mode,
    )
    _debug_logger.info(
        f"[Codex CLI 沙盒] 启动 commandHash={command_hash} "
        f"route={route_label} sandboxMode={sandbox_mode} "
        f"cwd={workdir} timeout={timeout_seconds}s"
    )
    started_at = time.monotonic()
    process: subprocess.Popen[str] | None = None
    sandbox_temp: Path | None = None
    try:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        environment, sandbox_temp = _sandbox_process_environment(
            workdir,
            command_hash,
            environment_policy=_environment_policy,
        )
        environment.pop(command_env_name, None)
        if is_native_windows_command:
            environment[command_env_name] = route.command
        process = subprocess.Popen(
            argv,
            shell=False,
            cwd=str(workdir),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=encoding,
            errors="replace",
            **_sandbox_popen_kwargs(platform=_host_platform()),
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
            "[错误] Codex CLI 沙盒启动失败：Codex CLI 或命令解释器不存在。"
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
    finally:
        _cleanup_sandbox_temp(workdir, sandbox_temp)
