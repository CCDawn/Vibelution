"""Persistent state helpers for the runtime manager."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .constants import DEFAULT_URL, PID_PATH, STATE_PATH, ensure_runtime_manager_dirs


WRITE_RETRY_TIMEOUT_SECONDS = 5.0
WRITE_FALLBACK_TIMEOUT_SECONDS = 5.0
READ_RETRY_ATTEMPTS = 5
READ_RETRY_DELAY_SECONDS = 0.05
_WRITE_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def default_state() -> dict[str, Any]:
    now = now_iso()
    return {
        "version": 1,
        "stateVersion": 0,
        "runtimeState": "idle",
        "managerPid": 0,
        "startedAt": now,
        "updatedAt": now,
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
            "sessionId": "",
            "backendPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "browserManaged": True,
            "url": DEFAULT_URL,
            "lastReason": "",
            "lastTransitionAt": now,
            "statusLine": "Workbench is closed.",
            "failureMessage": "",
        },
        "command": {
            "activeCommandId": "",
            "activeType": "",
            "requestedBy": "",
            "startedAt": "",
        },
        "lastError": {
            "scope": "",
            "message": "",
            "at": "",
        },
    }


def _write_retry_delay(attempt: int) -> float:
    return min(0.05 * attempt, 0.25)


def _write_text_in_place(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _retry_in_place_write(path: Path, text: str, *, timeout_seconds: float) -> None:
    attempt = 0
    deadline: float | None = None
    while True:
        try:
            _write_text_in_place(path, text)
            return
        except OSError as exc:
            attempt += 1
            if deadline is None:
                deadline = time.monotonic() + timeout_seconds
            if time.monotonic() >= deadline:
                raise exc
            time.sleep(_write_retry_delay(attempt))


def _log_atomic_write_failure(path: Path, exc: OSError) -> None:
    print(
        f"[runtime-manager] state write skipped after retries for {path}: {type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def _atomic_write_text(path: Path, text: str, *, suppress_write_failure: bool = False) -> bool:
    ensure_runtime_manager_dirs()
    with _WRITE_LOCK:
        fd = -1
        temp_path: str | None = None
        try:
            try:
                fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(text)
            except OSError as exc:
                try:
                    if fd >= 0:
                        os.close(fd)
                except OSError:
                    pass
                try:
                    _retry_in_place_write(path, text, timeout_seconds=WRITE_FALLBACK_TIMEOUT_SECONDS)
                    return True
                except OSError as fallback_exc:
                    if suppress_write_failure:
                        _log_atomic_write_failure(path, fallback_exc)
                        return False
                    raise exc from fallback_exc

            deadline = time.monotonic() + WRITE_RETRY_TIMEOUT_SECONDS
            attempt = 0
            last_replace_error: PermissionError | None = None
            while True:
                try:
                    os.replace(temp_path, path)
                    return True
                except PermissionError as exc:
                    last_replace_error = exc
                    attempt += 1
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(_write_retry_delay(attempt))

            try:
                _retry_in_place_write(path, text, timeout_seconds=WRITE_FALLBACK_TIMEOUT_SECONDS)
                return True
            except OSError as exc:
                if suppress_write_failure:
                    _log_atomic_write_failure(path, exc)
                    return False
                if last_replace_error is not None:
                    raise last_replace_error from exc
                raise
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


def _read_text_with_retry(path, *, encoding: str) -> str:
    for attempt in range(READ_RETRY_ATTEMPTS):
        try:
            return path.read_text(encoding=encoding)
        except OSError:
            if attempt + 1 >= READ_RETRY_ATTEMPTS:
                raise
            time.sleep(READ_RETRY_DELAY_SECONDS)
    raise OSError(f"Unable to read {path}")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return default_state()
    for attempt in range(READ_RETRY_ATTEMPTS):
        try:
            payload = json.loads(_read_text_with_retry(STATE_PATH, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if attempt + 1 >= READ_RETRY_ATTEMPTS:
                return default_state()
            time.sleep(READ_RETRY_DELAY_SECONDS)
            continue
        if isinstance(payload, dict):
            return payload
        return default_state()
    return default_state()


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(state)
    payload["stateVersion"] = int(payload.get("stateVersion") or 0) + 1
    payload["updatedAt"] = now_iso()
    _atomic_write_text(STATE_PATH, json.dumps(payload, ensure_ascii=False, indent=2), suppress_write_failure=True)
    return payload


def save_pid(pid: int) -> None:
    ensure_runtime_manager_dirs()
    _atomic_write_text(PID_PATH, str(int(pid)), suppress_write_failure=True)


def load_pid() -> int:
    if not PID_PATH.exists():
        return 0
    try:
        return int(_read_text_with_retry(PID_PATH, encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def clear_pid(expected_pid: int | None = None) -> None:
    if expected_pid is not None and load_pid() != int(expected_pid):
        return
    try:
        PID_PATH.unlink(missing_ok=True)
    except OSError:
        pass
