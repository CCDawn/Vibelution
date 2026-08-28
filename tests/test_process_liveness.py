from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from core.infrastructure import process_liveness
from core.infrastructure.process_liveness import is_pid_alive


def _terminated_child_pid() -> int:
    hidden = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden,
    )
    process.terminate()
    process.wait(timeout=15)
    return process.pid


def test_reports_the_current_process_as_alive() -> None:
    assert is_pid_alive(os.getpid()) is True


def test_reports_a_terminated_process_as_dead() -> None:
    assert is_pid_alive(_terminated_child_pid()) is False


def test_rejects_non_positive_pids() -> None:
    assert is_pid_alive(0) is False
    assert is_pid_alive(-1) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel32 probe branch")
def test_windows_access_denied_stays_conservatively_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenProcess ACCESS_DENIED（pid 被占用但不可查）保守按活。"""
    fake = SimpleNamespace(
        OpenProcess=lambda *_args, **_kwargs: 0,
        GetExitCodeProcess=lambda *_args, **_kwargs: 0,
        CloseHandle=lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(process_liveness, "_windows_kernel32", lambda: fake)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5)  # ERROR_ACCESS_DENIED
    assert is_pid_alive(12345) is True


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel32 probe branch")
def test_windows_inconclusive_exit_code_query_stays_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """句柄刚打开就查询失败属于证据不足，保守按活而不是抢着回收。"""
    fake = SimpleNamespace(
        OpenProcess=lambda *_args, **_kwargs: 4242,
        GetExitCodeProcess=lambda *_args, **_kwargs: 0,
        CloseHandle=lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(process_liveness, "_windows_kernel32", lambda: fake)
    assert is_pid_alive(12345) is True


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel32 probe branch")
@pytest.mark.parametrize("exit_code", [259, 0])
def test_windows_exit_code_decides_liveness(
    monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    """STILL_ACTIVE(259) 判活，其余退出码判死。"""

    def fake_get_exit_code_process(_handle: int, pointer: object) -> int:
        pointer._obj.value = exit_code  # type: ignore[attr-defined]
        return 1

    fake = SimpleNamespace(
        OpenProcess=lambda *_args, **_kwargs: 4242,
        GetExitCodeProcess=fake_get_exit_code_process,
        CloseHandle=lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(process_liveness, "_windows_kernel32", lambda: fake)
    assert is_pid_alive(12345) is (exit_code == 259)


@pytest.mark.parametrize(
    ("kill_effect", "expected"),
    [
        (None, True),
        (ProcessLookupError(), False),
        (PermissionError("denied"), True),
    ],
)
def test_posix_signal_zero_semantics(
    monkeypatch: pytest.MonkeyPatch,
    kill_effect: Exception | None,
    expected: bool,
) -> None:
    """POSIX 保留 os.kill(pid, 0) 语义：ESRCH 判死、EPERM 判活。"""
    monkeypatch.setattr(os, "name", "posix")

    def fake_kill(pid: int, sig: int) -> None:
        assert sig == 0
        if kill_effect is not None:
            raise kill_effect

    monkeypatch.setattr(os, "kill", fake_kill)
    assert is_pid_alive(12345) is expected
