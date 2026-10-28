"""Windows mutex shared with Electron for a verified legacy affairs ledger.

This is a serialization primitive, not source quiescence or cutover authority.
Only trusted in-process callers may supply a preview-backed observation.
Abandoned reports uncertainty; its absence cannot prove a clean previous run,
because Windows may destroy the named object when its last handle closes.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
from threading import Lock, current_thread

_guard = Lock()
_owned: dict[str, "ReminderMutexLease"] = {}
_PREFIX = "Local\\Vibelution.ReminderSource.v1."


class ReminderMutexError(RuntimeError):
    pass


class ReminderMutexLease:
    def __init__(self, api, handle, key, abandoned):
        self._api, self._handle, self._key = api, handle, key
        self._thread = current_thread()
        self._verify = None
        self.abandoned = abandoned

    def check(self):
        with _guard:
            if (self._handle is None or current_thread() is not self._thread
                    or not self._thread.is_alive() or _owned.get(self._key) is not self):
                raise ReminderMutexError("reminder_mutex_release_unavailable")
        if self._verify is not None:
            self._verify()

    def release(self):
        with _guard:
            if (self._handle is None or current_thread() is not self._thread
                    or not self._thread.is_alive() or _owned.get(self._key) is not self):
                raise ReminderMutexError("reminder_mutex_release_unavailable")
            if not self._api.ReleaseMutex(self._handle):
                raise ReminderMutexError("reminder_mutex_release_unavailable")
            closed = self._api.CloseHandle(self._handle)
            self._handle = None
            del _owned[self._key]
            if not closed:
                raise ReminderMutexError("reminder_mutex_close_unavailable")

    def __enter__(self):
        self.check()
        return self

    def __exit__(self, *args):
        self.release()


def _try_digest(key: str) -> ReminderMutexLease | None:
    """Internal transport primitive; callers must bind key to verified identity."""
    if os.name != "nt" or type(key) is not str or re.fullmatch(r"[a-f0-9]{64}", key) is None:
        raise ReminderMutexError("reminder_mutex_invalid")
    with _guard:
        previous = _owned.get(key)
        if previous is not None and previous._thread.is_alive():
            return None
        handle = None
        acquired = False
        try:
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            api.CreateMutexW.restype = wintypes.HANDLE
            api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            api.WaitForSingleObject.restype = wintypes.DWORD
            api.ReleaseMutex.argtypes = [wintypes.HANDLE]
            api.ReleaseMutex.restype = wintypes.BOOL
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.CloseHandle.restype = wintypes.BOOL
            # Keep the previous dead thread's handle open until this new handle
            # acquires the same kernel object; otherwise abandonment can vanish.
            handle = api.CreateMutexW(None, False, _PREFIX + key)
            if not handle:
                raise ReminderMutexError("reminder_mutex_unavailable")
            result = api.WaitForSingleObject(handle, 0)
            if result == 258:  # WAIT_TIMEOUT
                if not api.CloseHandle(handle):
                    raise ReminderMutexError("reminder_mutex_close_unavailable")
                handle = None
                return None
            if result not in (0, 0x80):
                raise ReminderMutexError("reminder_mutex_unavailable")
            acquired = True
            lease = ReminderMutexLease(api, handle, key, previous is not None or result == 0x80)
            if previous is not None:
                if previous._handle is None or not previous._api.CloseHandle(previous._handle):
                    raise ReminderMutexError("reminder_mutex_close_unavailable")
                previous._handle = None
            _owned[key] = lease
            return lease
        except BaseException:
            if handle:
                if acquired:
                    api.ReleaseMutex(handle)
                api.CloseHandle(handle)
            raise


def trusted_reminder_source_mutex_key(observation) -> str:
    """Export a digest only from the live trusted registered-source observation.

    A main-only authenticated adapter may transport it with the observation's
    own revalidation capability. It is not a self-authenticating token.
    """
    from core.assistant_runtime.reminder_source_identity import ReminderSourceObservation
    if type(observation) is not ReminderSourceObservation:
        raise ReminderMutexError("reminder_mutex_invalid")
    observation._check()
    key = observation._ledger
    if type(key) is not str or re.fullmatch(r"[a-f0-9]{64}", key) is None:
        raise ReminderMutexError("reminder_mutex_invalid")
    return key


def try_acquire_reminder_source_mutex(observation) -> ReminderMutexLease | None:
    """Acquire only from the trusted live registered-source observation."""
    lease = _try_digest(trusted_reminder_source_mutex_key(observation))
    if lease is not None:
        try:
            observation._check()
            lease._verify = observation._check
        except BaseException:
            lease.release()
            raise
    return lease


__all__ = ["ReminderMutexError", "ReminderMutexLease", "trusted_reminder_source_mutex_key", "try_acquire_reminder_source_mutex"]
