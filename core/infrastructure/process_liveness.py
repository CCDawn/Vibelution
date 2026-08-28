"""Shared cross-platform process liveness probe.

``os.kill(pid, 0)`` is not a liveness probe on Windows: signal 0 maps to
``CTRL_C_EVENT``, so CPython calls ``GenerateConsoleCtrlEvent``, which raises
``OSError`` (WinError 87 or 6) for dead *and* live pids alike inside the
console-less runtime processes this project ships (pythonw, ``CREATE_NO_WINDOW``
children).  The kernel API answers authoritatively instead, so every caller in
the codebase that needs "is this pid alive?" should share this helper rather
than re-deriving the mapping per module.
"""

from __future__ import annotations

import os
from typing import Any

_WINDOWS_KERNEL32: Any = None
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE_EXIT_CODE = 259


def _windows_kernel32() -> Any:
    """Lazy kernel32 binding with 64-bit-safe signatures for liveness probes."""
    global _WINDOWS_KERNEL32
    if _WINDOWS_KERNEL32 is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        _WINDOWS_KERNEL32 = kernel32
    return _WINDOWS_KERNEL32


def _windows_pid_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # ERROR_ACCESS_DENIED means something owns this pid; treating it as
        # alive is conservative because stealing its lease/lock would be worse
        # than waiting one more poll cycle.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            # The handle was just opened, so a failed query is ambiguous:
            # keep the lease rather than reclaim it on inconclusive evidence.
            return True
        return int(exit_code.value) == _STILL_ACTIVE_EXIT_CODE
    finally:
        kernel32.CloseHandle(handle)


def is_pid_alive(pid: int) -> bool:
    """Report whether ``pid`` currently owns a live process.

    Never spawns child processes.  ``pid <= 0`` is dead.  On Windows this uses
    kernel32 ``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` +
    ``GetExitCodeProcess`` (``STILL_ACTIVE``), treating ``ACCESS_DENIED`` and an
    inconclusive exit-code query as alive because the probe's callers decide
    whether to reclaim leases, kill work, or run destructive maintenance.
    POSIX keeps the ``os.kill(pid, 0)`` semantics: ``ProcessLookupError`` is
    dead, ``PermissionError`` is alive.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(int(pid))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
