"""Waitable, console-free process trees with ownership independent of root PID."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from typing import Any

from scripts.windowless_subprocess import no_window_subprocess_kwargs
from .windows_process_job import WindowsProcessJob


class OwnedProcess:
    def __init__(self, process: subprocess.Popen[Any], job: WindowsProcessJob | None) -> None:
        self.process = process
        self.pid = process.pid
        self._job = job
        self._lock = threading.Lock()
        self._closed = False

    @classmethod
    def spawn(cls, args: Any, **kwargs: Any) -> "OwnedProcess":
        job = WindowsProcessJob() if os.name == "nt" else None
        process = None
        try:
            if job is not None:
                flags = int(kwargs.pop("creationflags", 0))
                if flags & (0x01000000 | 0x8):
                    raise ValueError("Owned children cannot detach or break away")
                kwargs.update(no_window_subprocess_kwargs(creationflags=flags | 0x4))
            else:
                kwargs["start_new_session"] = True
            process = subprocess.Popen(args, **kwargs)
            if job is not None:
                job.assign_handle(process._handle)
                # Same suspended/assign/resume sequence as scripts/run_tests.py.
                import psutil
                psutil.Process(process.pid).resume()
            return cls(process, job)
        except BaseException:
            try:
                if process is not None:
                    process.kill()
                    process.wait(timeout=5)
            finally:
                try:
                    if job is not None:
                        job.close()
                finally:
                    if process is not None:
                        try:
                            for pipe in (process.stdin, process.stdout, process.stderr):
                                if pipe is not None:
                                    pipe.close()
                        finally:
                            if job is not None:
                                process._handle.Close()
            raise

    def _active(self) -> bool:
        if self._job is not None:
            return self._job.active_count() > 0
        try:
            os.killpg(self.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def terminate(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        force_at = time.monotonic() + min(1.0, max(0.0, timeout) / 2)
        if not self._lock.acquire(timeout=max(0.0, timeout)):
            return False
        try:
            if self._closed:
                return True
            if self._job is not None:
                if self._job.active_count():
                    self._job.terminate()
            else:
                try:
                    os.killpg(self.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            while True:
                self.process.poll()  # Reap the root even when descendants remain.
                if not self._active() and self.process.poll() is not None:
                    return True
                if self._job is None and time.monotonic() >= force_at:
                    try:
                        os.killpg(self.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if time.monotonic() >= deadline:
                    return False
                time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
        except OSError:
            return False
        finally:
            self._lock.release()

    def close(self, *, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        if not self.terminate(timeout=timeout):
            raise RuntimeError("Owned process tree has not finished retiring")
        if not self._lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise RuntimeError("Owned process retirement is still in progress")
        try:
            if self._closed:
                return
            if self._job is not None:
                self._job.close()
                # Popen retains this handle after wait/poll; release it once
                # both root and Job have retired instead of waiting for GC.
                self.process._handle.Close()
            self._closed = True
        finally:
            self._lock.release()
