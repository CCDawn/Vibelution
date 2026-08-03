"""Host-specific shell/argv adaptation for the Codex sandbox.

Keeps the platform-specific executable/shell/sandbox argv construction in one
cohesive adapter; the public execution orchestration in
``core.infrastructure.codex_cli_sandbox`` delegates here.
"""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path, PureWindowsPath
from typing import Any, Callable

WINDOWS_COMMAND_ENV = "VIBELUTION_CODEX_SANDBOX_COMMAND"
WORKSPACE_WRITE_SANDBOX_MODE = "workspace_write"
DANGER_FULL_ACCESS_SANDBOX_MODE = "danger_full_access"

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


def windows_command_interpreter() -> str:
    candidate = str(os.environ.get("COMSPEC") or "").strip()
    if candidate and Path(candidate).is_file():
        return candidate
    system_root = str(os.environ.get("SystemRoot") or r"C:\Windows").strip()
    fallback = Path(system_root) / "System32" / "cmd.exe"
    return str(fallback) if fallback.is_file() else "cmd.exe"


def powershell_executable() -> str:
    resolved = shutil.which("powershell.exe")
    if resolved and Path(resolved).is_file():
        return resolved
    system_root = str(os.environ.get("SystemRoot") or r"C:\Windows").strip()
    fallback = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(fallback) if fallback.is_file() else "powershell.exe"


def unix_shell_executable() -> str:
    """Resolve the host Unix shell used as the sandbox command interpreter."""
    resolved = shutil.which("bash")
    if resolved and Path(resolved).is_file():
        return str(Path(resolved).resolve())
    return "/bin/bash"


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


def _split_windows_command_line(command: str) -> list[str]:
    """Parse one Windows command line using CRT-compatible quote rules."""

    args: list[str] = []
    index = 0
    length = len(command)
    while index < length:
        while index < length and command[index].isspace():
            index += 1
        if index >= length:
            break
        current: list[str] = []
        in_quotes = False
        while index < length:
            if command[index].isspace() and not in_quotes:
                break
            backslashes = 0
            while index < length and command[index] == "\\":
                backslashes += 1
                index += 1
            if index < length and command[index] == '"':
                current.extend("\\" for _ in range(backslashes // 2))
                if backslashes % 2:
                    current.append('"')
                else:
                    in_quotes = not in_quotes
                index += 1
                continue
            current.extend("\\" for _ in range(backslashes))
            if index >= length:
                break
            current.append(command[index])
            index += 1
        if in_quotes:
            return []
        args.append("".join(current))
    return args


def _direct_executable_argv(command: str) -> list[str]:
    if _has_unquoted_shell_operator(command):
        return []
    tokens = _split_windows_command_line(command)
    if not tokens:
        return []
    executable = tokens[0]
    explicit_relative = executable.startswith((".\\", "./"))
    if (
        not (
            Path(executable).is_absolute()
            or PureWindowsPath(executable).is_absolute()
            or explicit_relative
        )
        or not executable.lower().endswith(".exe")
    ):
        return []
    return tokens


def _explicit_powershell_argv(
    command: str,
    *,
    powershell_executable_fn: Callable[[], str] = powershell_executable,
) -> list[str]:
    """Preserve a model-issued PowerShell command as one native argv payload.

    ``cmd /c`` changes the quoting boundary for ``powershell -Command`` under
    ``codex sandbox`` and can make PowerShell echo the command text rather than
    execute it. Only recognize the explicit ``-Command``/``-c`` form; opaque
    forms such as ``-EncodedCommand`` continue through the existing route and
    security checks.
    """

    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        return []
    normalized = [
        token[1:-1]
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
        else token
        for token in tokens
    ]
    if not normalized:
        return []
    executable = Path(normalized[0]).name.lower()
    if executable not in {"powershell", "powershell.exe"}:
        return []
    command_index = next(
        (
            index
            for index, value in enumerate(normalized[1:], start=1)
            if value.lower() in {"-command", "-c"}
        ),
        -1,
    )
    if command_index < 0 or command_index >= len(normalized) - 1:
        return []
    command_payload = " ".join(normalized[command_index + 1 :]).strip()
    if not command_payload:
        return []
    return [
        powershell_executable_fn(),
        *normalized[1:command_index],
        normalized[command_index],
        command_payload,
    ]


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


def _is_native_windows_command_segment(command: str, *, which: Callable[[str], str | None]) -> bool:
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
    resolved = which(normalized)
    if not resolved:
        return False
    resolved_text = str(Path(resolved).resolve()).replace("/", "\\").lower()
    if "\\git\\usr\\bin\\" in resolved_text:
        return False
    return Path(resolved).suffix.lower() in {".exe", ".com", ".cmd", ".bat"}


def _is_native_windows_and_chain(command: str, *, which: Callable[[str], str | None]) -> bool:
    segments = _split_unquoted_and_chain(command)
    return bool(segments) and all(
        _is_native_windows_command_segment(segment, which=which)
        for segment in segments
    )


def _is_native_windows_command(command: str, *, which: Callable[[str], str | None]) -> bool:
    if _is_native_windows_and_chain(command, which=which):
        return True
    if _has_unquoted_shell_operator(command):
        return False
    return _is_native_windows_command_segment(command, which=which)


class ShellAdapter:
    """One cohesive adapter for host executable/shell/sandbox argv construction."""

    def __init__(
        self,
        *,
        platform: str,
        windows_command_interpreter_fn: Callable[[], str],
        powershell_executable_fn: Callable[[], str],
        unix_shell_executable_fn: Callable[[], str],
        which: Callable[[str], str | None],
    ) -> None:
        self.platform = str(platform or "").lower()
        self._windows_command_interpreter_fn = windows_command_interpreter_fn
        self._powershell_executable_fn = powershell_executable_fn
        self._unix_shell_executable_fn = unix_shell_executable_fn
        self._which = which

    def sandbox_argv(
        self,
        executable: str,
        route: Any,
        *,
        git_bash_executable: str = "",
        sandbox_mode: str = WORKSPACE_WRITE_SANDBOX_MODE,
    ) -> list[str]:
        if self.platform == "windows":
            return self._windows_sandbox_argv(
                executable,
                route,
                git_bash_executable=git_bash_executable,
                sandbox_mode=sandbox_mode,
            )
        return self._unix_sandbox_argv(executable, route, sandbox_mode=sandbox_mode)

    def describe_route(self, route: Any) -> tuple[bool, str, str]:
        """Return ``(is_native_windows_command, command_env_var, route_label)``."""
        route_name = str(getattr(route, "route", "") or "")
        if self.platform != "windows":
            return False, "", route_name
        command = str(getattr(route, "command", "") or "")
        is_native = route_name == "git_bash" and _is_native_windows_command(
            command,
            which=self._which,
        )
        if not is_native:
            return False, "", route_name
        label = (
            "windows_native_chain"
            if bool(_split_unquoted_and_chain(command))
            else "windows_native"
        )
        return True, WINDOWS_COMMAND_ENV, label

    def _sandbox_prefix(self, executable: str, sandbox_mode: str) -> list[str]:
        if sandbox_mode == WORKSPACE_WRITE_SANDBOX_MODE:
            if not str(executable or "").strip():
                raise RuntimeError("Codex CLI sandbox executable is required")
            return [executable, "sandbox"]
        if sandbox_mode == DANGER_FULL_ACCESS_SANDBOX_MODE:
            return []
        raise RuntimeError(f"Unsupported Agent sandbox mode: {sandbox_mode}")

    def _windows_sandbox_argv(
        self,
        executable: str,
        route: Any,
        *,
        git_bash_executable: str,
        sandbox_mode: str,
    ) -> list[str]:
        prefix = self._sandbox_prefix(executable, sandbox_mode)
        if sandbox_mode == WORKSPACE_WRITE_SANDBOX_MODE:
            prefix += [
                "-c",
                'windows.sandbox="unelevated"',
                "-c",
                'sandbox_mode="workspace-write"',
                "--",
            ]
        command = str(getattr(route, "command", "") or "")
        route_name = str(getattr(route, "route", "") or "")
        direct_argv = _direct_executable_argv(command)
        if direct_argv:
            return prefix + direct_argv
        explicit_powershell_argv = _explicit_powershell_argv(
            command,
            powershell_executable_fn=self._powershell_executable_fn,
        )
        if explicit_powershell_argv:
            return prefix + explicit_powershell_argv
        if route_name == "git_bash" and _is_native_windows_command(
            command,
            which=self._which,
        ):
            return prefix + [
                self._windows_command_interpreter_fn(),
                "/d",
                "/v:off",
                "/s",
                "/c",
                "call",
                f"%{WINDOWS_COMMAND_ENV}%",
            ]
        if route_name == "powershell":
            return prefix + [
                self._powershell_executable_fn(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ]
        if route_name == "git_bash" and git_bash_executable:
            return prefix + [git_bash_executable, "-c", command]
        return prefix + [
            self._windows_command_interpreter_fn(),
            "/d",
            "/s",
            "/c",
            command,
        ]

    def _unix_sandbox_argv(
        self,
        executable: str,
        route: Any,
        *,
        sandbox_mode: str,
    ) -> list[str]:
        prefix = self._sandbox_prefix(executable, sandbox_mode)
        if sandbox_mode == WORKSPACE_WRITE_SANDBOX_MODE:
            prefix += [
                "-c",
                'sandbox_mode="workspace-write"',
                "--",
            ]
        command = str(getattr(route, "command", "") or "")
        shell = self._unix_shell_executable_fn()
        return prefix + [shell, "-c", command]


def create_shell_adapter(
    *,
    platform: str,
    windows_command_interpreter_fn: Callable[[], str] | None = None,
    powershell_executable_fn: Callable[[], str] | None = None,
    unix_shell_executable_fn: Callable[[], str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> ShellAdapter:
    """Build the host shell adapter with injectable platform functions."""
    return ShellAdapter(
        platform=platform,
        windows_command_interpreter_fn=windows_command_interpreter_fn
        or windows_command_interpreter,
        powershell_executable_fn=powershell_executable_fn or powershell_executable,
        unix_shell_executable_fn=unix_shell_executable_fn or unix_shell_executable,
        which=which or shutil.which,
    )
