from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Sequence
from typing import Any

from core.infrastructure import no_console_git
from core.logging import debug as _debug_logger

DEFAULT_GIT_TIMEOUT_SECONDS = 30.0
DEFAULT_GIT_LOCK_RETRIES = 2
GIT_PROCESS_OUTPUT_LOG_LIMIT = 500
GIT_PROCESS_CWD_LOG_LIMIT = 160


def resolve_git_executable() -> str:
    """Resolve a Git executable that can run without the Git for Windows cmd wrapper."""

    return no_console_git.resolve_git_executable()


def git_command(args: Sequence[str]) -> list[str]:
    return [resolve_git_executable(), *[str(arg) for arg in args]]


def no_console_subprocess_kwargs() -> dict[str, Any]:
    return no_console_git.no_console_subprocess_kwargs()


def safe_git_args_for_log(args: Sequence[str]) -> list[str]:
    """Return git argv suitable for diagnostics: redact message/file payloads and credential URLs."""

    safe_args: list[str] = []
    redact_next = False
    for arg in args:
        text = str(arg or "")
        if redact_next:
            safe_args.append("[redacted]")
            redact_next = False
            continue
        if _looks_like_credential_url(text):
            safe_args.append("[redacted-url]")
        else:
            safe_args.append(text)
        if text in {"-m", "--message", "-F", "--file"}:
            redact_next = True
    return safe_args


def run_git(
    args: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float | None = DEFAULT_GIT_TIMEOUT_SECONDS,
    check: bool = False,
    retries: int = DEFAULT_GIT_LOCK_RETRIES,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    run_kwargs = dict(kwargs)
    # Always force no-console kwargs last so callers cannot strip CREATE_NO_WINDOW.
    run_kwargs.update(no_console_subprocess_kwargs())
    # Force-overwrite pager/editor/prompt env (setdefault loses to empty or cmd.exe GIT_EDITOR).
    git_exe = resolve_git_executable()
    caller_env = run_kwargs.pop("env", None)
    run_kwargs["env"] = no_console_git.apply_no_console_git_env(
        dict(caller_env) if caller_env is not None else None,
        git_exe=git_exe,
    )
    if "stdin" not in run_kwargs:
        run_kwargs["stdin"] = subprocess.DEVNULL
    command = [git_exe, *[str(arg) for arg in args]]
    cwd_text = str(cwd) if cwd is not None else ""
    attempts = max(0, int(retries or 0)) + 1
    for attempt in range(attempts):
        try:
            result = subprocess.run(
                command,
                cwd=cwd_text or None,
                timeout=timeout,
                check=False,
                **run_kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            _observe_git_process_result(
                "timeout",
                "git_process.command.timeout",
                message="Git command timed out.",
                level="error",
                outcome="failed",
                args=args,
                cwd=cwd_text,
                timeout_seconds=timeout,
                attempt=attempt,
                attempts=attempts,
                output=getattr(exc, "output", "") or "",
                stderr=getattr(exc, "stderr", "") or "",
            )
            raise
        if result.returncode != 0 and _is_git_lock_contention(result) and attempt < attempts - 1:
            _observe_git_process_result(
                "lock",
                "git_process.lock_retry",
                message="Git index lock contention; retrying.",
                level="warning",
                outcome="retrying",
                args=args,
                cwd=cwd_text,
                timeout_seconds=timeout,
                attempt=attempt,
                attempts=attempts,
                returncode=result.returncode,
                output=result.stdout,
                stderr=result.stderr,
            )
            time.sleep(0.2 * (attempt + 1))
            continue
        if result.returncode != 0:
            _observe_git_process_result(
                "command",
                "git_process.command.failed",
                message="Git command failed.",
                level="error",
                outcome="failed",
                args=args,
                cwd=cwd_text,
                timeout_seconds=timeout,
                attempt=attempt,
                attempts=attempts,
                returncode=result.returncode,
                output=result.stdout,
                stderr=result.stderr,
            )
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                command,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result
    raise RuntimeError("run_git retry loop exhausted unexpectedly")


_CREDENTIAL_URL_PATTERN = re.compile(
    r"(?i)\b(?:https?|git|ssh)://[^/\s'\"]+:[^/\s'\"]+@"
)


def _looks_like_credential_url(value: str) -> bool:
    return bool(_CREDENTIAL_URL_PATTERN.search(str(value or "")))


def _truncate_log_text(value: Any, *, limit: int) -> str:
    text = _redact_credential_urls(_process_output_text(value).replace("\r", " ").strip())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def _redact_credential_urls(text: str) -> str:
    return _CREDENTIAL_URL_PATTERN.sub(
        lambda match: f"{match.group(0).split('://', 1)[0].lower()}://[redacted-url]@",
        str(text or ""),
    )


def _observe_git_process_result(
    phase: str,
    event_code: str,
    *,
    message: str,
    level: str,
    outcome: str,
    args: Sequence[str],
    cwd: str,
    timeout_seconds: float | None,
    attempt: int,
    attempts: int,
    returncode: int | None = None,
    output: Any = "",
    stderr: Any = "",
) -> None:
    fields = {
        "args": safe_git_args_for_log(args),
        "cwd": _truncate_log_text(cwd, limit=GIT_PROCESS_CWD_LOG_LIMIT),
        "timeoutSeconds": timeout_seconds,
        "attempt": int(attempt) + 1,
        "attempts": int(attempts),
        "returnCode": returncode,
        "stdout": _truncate_log_text(output, limit=GIT_PROCESS_OUTPUT_LOG_LIMIT),
        "stderr": _truncate_log_text(stderr, limit=GIT_PROCESS_OUTPUT_LOG_LIMIT),
    }
    log_message = (
        f"{message} event={event_code} args={fields['args']!r} "
        f"returnCode={returncode} attempt={fields['attempt']}/{fields['attempts']}"
    )
    if level == "error":
        _debug_logger.error(log_message, tag="GIT")
    else:
        _debug_logger.warning(log_message, tag="GIT")
    _record_git_process_scene_event(
        phase,
        event_code,
        message=message,
        level=level,
        outcome=outcome,
        fields=fields,
    )


def _record_git_process_scene_event(
    phase: str,
    event_code: str,
    *,
    message: str,
    level: str,
    outcome: str,
    fields: dict[str, Any],
) -> None:
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "git_process",
            phase,
            event_code,
            message=message,
            level=level,
            outcome=outcome,
            fields=fields,
            lifecycle=False,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail git
        _debug_logger.warning(
            f"runtime scene event record failed (git_process/{phase}/{event_code}): "
            f"{type(exc).__name__}: {exc}",
            tag="SCENE",
        )


def _is_git_lock_contention(result: subprocess.CompletedProcess[Any]) -> bool:
    text = " ".join(
        part
        for part in (
            _process_output_text(getattr(result, "stderr", "")),
            _process_output_text(getattr(result, "stdout", "")),
        )
        if part
    ).lower()
    return "index.lock" in text or "another git process" in text


def _process_output_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)
