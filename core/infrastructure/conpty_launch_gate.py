"""Start a ConPTY command only after the bootstrap belongs to its Windows Job."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys


_READY_TIMEOUT_MS = 5_000
_RELEASE_TIMEOUT_MS = 10_000
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258


def _event_api():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = {
        "CreateEventW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "OpenEventW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetEvent": ([wintypes.HANDLE], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (args, result) in declarations.items():
        method = getattr(api, name)
        method.argtypes, method.restype = args, result
    return api


def _wait(api, handle, timeout_ms):
    result = api.WaitForSingleObject(handle, timeout_ms)
    if result == _WAIT_TIMEOUT:
        raise TimeoutError("ConPTY bootstrap handshake timed out")
    if result != _WAIT_OBJECT_0:
        raise ctypes.WinError(ctypes.get_last_error())


class ConptyLaunchGate:
    def __init__(self, args: list[str], env: dict[str, str]) -> None:
        search_path = next((value for key, value in env.items() if key.upper() == "PATH"), os.defpath)
        executable = shutil.which(args[0], path=search_path)
        if executable is None:
            raise FileNotFoundError(args[0])
        # A venv redirector may launch and assign its own child before we
        # capture it. Use the base console interpreter only for the bootstrap.
        interpreter = Path(sys._base_executable)
        if interpreter.name.lower() == "pythonw.exe":
            interpreter = interpreter.with_name("python.exe")
        self._key = "Local\\Vibelution-ConPTY-" + secrets.token_hex(16)
        self.command = [
            str(interpreter), "-I", "-S", str(Path(__file__).resolve()), self._key, executable, *args[1:],
        ]
        self._api = _event_api()
        self._ready = self._release = None

    def __enter__(self):
        try:
            self._ready = self._create("-ready")
            self._release = self._create("-release")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _create(self, suffix):
        ctypes.set_last_error(0)
        handle = self._api.CreateEventW(None, True, False, self._key + suffix)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS
            self._api.CloseHandle(handle)
            raise FileExistsError("ConPTY bootstrap event already exists")
        return handle

    def release(self):
        # Ready proves the bootstrap already holds its release handle. Both
        # parent handles can close as soon as SetEvent succeeds.
        _wait(self._api, self._ready, _READY_TIMEOUT_MS)
        if not self._api.SetEvent(self._release):
            raise ctypes.WinError(ctypes.get_last_error())

    def __exit__(self, *_exc):
        for handle in (self._ready, self._release):
            if handle:
                self._api.CloseHandle(handle)


def _run_bootstrap(key, args):
    api = _event_api()
    release = api.OpenEventW(_SYNCHRONIZE, False, key + "-release")
    if not release:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        ready = api.OpenEventW(_EVENT_MODIFY_STATE, False, key + "-ready")
        if not ready:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not api.SetEvent(ready):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            api.CloseHandle(ready)
        _wait(api, release, _RELEASE_TIMEOUT_MS)
    finally:
        api.CloseHandle(release)
    # The child and the bootstrap share the PTY. Leave console interrupts
    # available to the actual command while keeping its waiter alive.
    for kind in (signal.SIGINT, signal.SIGBREAK):
        signal.signal(kind, lambda *_args: None)
    return subprocess.call(args)


if __name__ == "__main__":
    try:
        raise SystemExit(_run_bootstrap(sys.argv[1], sys.argv[2:]))
    except OSError:
        sys.stderr.write("ConPTY could not launch its command.\n")
        raise SystemExit(1) from None
