"""Execute Agent CLI commands through the Codex native Windows sandbox."""

from __future__ import annotations

import hashlib
import locale
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from core.logging import debug_logger as _debug_logger
from scripts.windowless_subprocess import no_window_subprocess_kwargs


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_POLL_INTERVAL_SECONDS = 0.2
_WINDOWS_CHAIN_COMMAND_ENV = "VIBELUTION_CODEX_SANDBOX_COMMAND"
_WINDOWS_CHAIN_BUILTINS = {
    "cd",
    "cls",
    "copy",
    "dir",
    "echo",
    "md",
    "mkdir",
    "move",
    "popd",
    "pushd",
    "rd",
    "ren",
    "rename",
    "rmdir",
    "set",
    "type",
    "where",
}
_PYTHON_SITECUSTOMIZE = """\
import os
from pathlib import Path

_sandbox_temp = Path(os.environ["VIBELUTION_CODEX_SANDBOX_TEMP"]).resolve()
_original_mkdir = os.mkdir
_original_chmod = os.chmod


def _inside_sandbox_temp(path):
    try:
        return Path(path).resolve().is_relative_to(_sandbox_temp)
    except (OSError, TypeError, ValueError):
        return False


def _sandbox_mkdir(path, mode=0o777, *args, **kwargs):
    if _inside_sandbox_temp(path):
        mode = 0o777
    return _original_mkdir(path, mode, *args, **kwargs)


def _sandbox_chmod(path, mode, *args, **kwargs):
    if _inside_sandbox_temp(path):
        return None
    return _original_chmod(path, mode, *args, **kwargs)


os.mkdir = _sandbox_mkdir
os.chmod = _sandbox_chmod
"""


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
    from tools.shell_tools import _get_workspace_root

    active_workspace = _get_workspace_root().resolve()
    workspace_root = active_workspace if (active_workspace / ".git").exists() else PROJECT_ROOT
    raw = Path(str(cwd or "").strip()) if str(cwd or "").strip() else workspace_root
    if not raw.is_absolute():
        raw = workspace_root / raw
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


def _has_unquoted_shell_operator(command: str) -> bool:
    quote = ""
    escaped = False
    for character in command:
        if escaped:
            escaped = False
            continue
        if character == "^" and not quote:
            escaped = True
            continue
        if character in {'"', "'"}:
            if quote == character:
                quote = ""
            elif not quote:
                quote = character
            continue
        if not quote and character in {"&", "|", "<", ">"}:
            return True
    return False


def _direct_executable_argv(command: str) -> list[str]:
    if not command.startswith('"') or _has_unquoted_shell_operator(command):
        return []
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        return []
    if not tokens:
        return []
    normalized = [
        token[1:-1]
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
        else token
        for token in tokens
    ]
    executable = normalized[0]
    if not Path(executable).is_absolute() or not executable.lower().endswith(".exe"):
        return []
    return normalized


def _split_unquoted_and_chain(command: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        character = command[index]
        if escaped:
            current.append(character)
            escaped = False
            index += 1
            continue
        if character == "^" and not quote:
            current.append(character)
            escaped = True
            index += 1
            continue
        if character in {'"', "'"}:
            if quote == character:
                quote = ""
            elif not quote:
                quote = character
            current.append(character)
            index += 1
            continue
        if not quote and character == "&":
            if index + 1 >= len(command) or command[index + 1] != "&":
                return []
            segment = "".join(current).strip()
            if not segment:
                return []
            segments.append(segment)
            current = []
            index += 2
            continue
        if not quote and character in {"|", "<", ">"}:
            return []
        current.append(character)
        index += 1
    segment = "".join(current).strip()
    if not segment:
        return []
    segments.append(segment)
    return segments if len(segments) > 1 else []


def _is_native_windows_command_segment(command: str) -> bool:
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        return False
    if not tokens:
        return False
    executable = tokens[0]
    if (
        len(executable) >= 2
        and executable[0] == executable[-1]
        and executable[0] in {'"', "'"}
    ):
        executable = executable[1:-1]
    normalized = executable.strip()
    if not normalized:
        return False
    lowered_name = Path(normalized).name.lower()
    if lowered_name in {"bash", "bash.exe", "sh", "sh.exe", "wsl", "wsl.exe"}:
        return False
    if lowered_name in _WINDOWS_CHAIN_BUILTINS:
        return True
    resolved = shutil.which(normalized)
    if not resolved:
        return False
    resolved_text = str(Path(resolved).resolve()).replace("/", "\\").lower()
    if "\\git\\usr\\bin\\" in resolved_text:
        return False
    return Path(resolved).suffix.lower() in {".exe", ".com", ".cmd", ".bat"}


def _is_native_windows_and_chain(command: str) -> bool:
    segments = _split_unquoted_and_chain(command)
    return bool(segments) and all(
        _is_native_windows_command_segment(segment)
        for segment in segments
    )


def _sandbox_process_environment(
    workdir: Path,
    command_hash: str,
) -> tuple[dict[str, str], Path]:
    temp_root = (workdir / ".runtime" / "codex-cli").resolve()
    if not temp_root.is_relative_to(workdir):
        raise RuntimeError("Codex CLI 沙盒临时目录越出工作区")
    sandbox_temp = (
        temp_root
        / f"{command_hash}-{os.getpid()}-{time.monotonic_ns()}"
    ).resolve()
    if not sandbox_temp.is_relative_to(temp_root):
        raise RuntimeError("Codex CLI 沙盒临时目录解析异常")
    sandbox_temp.mkdir(parents=True, exist_ok=False)
    (sandbox_temp / "sitecustomize.py").write_text(
        _PYTHON_SITECUSTOMIZE,
        encoding="utf-8",
    )

    environment = os.environ.copy()
    for name in ("TMP", "TEMP", "TMPDIR"):
        environment[name] = str(sandbox_temp)
    relative_temp = sandbox_temp.relative_to(workdir).as_posix()
    pytest_options = (
        f"--basetemp={relative_temp}/pytest "
        f"-o cache_dir={relative_temp}/pytest-cache"
    )
    existing_pytest_options = str(environment.get("PYTEST_ADDOPTS") or "").strip()
    environment["PYTEST_ADDOPTS"] = " ".join(
        part for part in (existing_pytest_options, pytest_options) if part
    )
    existing_python_path = str(environment.get("PYTHONPATH") or "").strip()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(sandbox_temp), existing_python_path) if part
    )
    environment["VIBELUTION_CODEX_SANDBOX_TEMP"] = str(sandbox_temp)
    return environment, sandbox_temp


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
) -> list[str]:
    if os.name != "nt":
        raise RuntimeError("当前 Codex CLI 沙盒接入仅支持原生 Windows")
    prefix = [
        executable,
        "sandbox",
        "-c",
        'windows.sandbox="unelevated"',
        "-c",
        'sandbox_mode="workspace-write"',
        "--",
    ]
    direct_argv = _direct_executable_argv(route.command)
    if direct_argv:
        return prefix + direct_argv
    if route.route == "git_bash" and _is_native_windows_and_chain(route.command):
        return prefix + [
            _windows_command_interpreter(),
            "/d",
            "/v:off",
            "/s",
            "/c",
            "call",
            f"%{_WINDOWS_CHAIN_COMMAND_ENV}%",
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

    is_native_windows_chain = (
        route.route == "git_bash" and _is_native_windows_and_chain(route.command)
    )
    argv = _sandbox_argv(
        executable,
        route,
        git_bash_executable=_find_git_bash() if route.route == "git_bash" else "",
    )
    route_label = "windows_native_chain" if is_native_windows_chain else route.route
    _debug_logger.info(
        f"[Codex CLI 沙盒] 启动 commandHash={command_hash} "
        f"route={route_label} cwd={workdir} timeout={timeout_seconds}s"
    )
    started_at = time.monotonic()
    process: subprocess.Popen[str] | None = None
    sandbox_temp: Path | None = None
    try:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        environment, sandbox_temp = _sandbox_process_environment(
            workdir,
            command_hash,
        )
        environment.pop(_WINDOWS_CHAIN_COMMAND_ENV, None)
        if is_native_windows_chain:
            environment[_WINDOWS_CHAIN_COMMAND_ENV] = route.command
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
    finally:
        _cleanup_sandbox_temp(workdir, sandbox_temp)
