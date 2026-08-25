from __future__ import annotations

import subprocess
from contextlib import contextmanager
from typing import Any, Iterator


def terminate_processes(
    processes: list[subprocess.Popen[Any]],
    *,
    terminate_timeout: float = 2.0,
    kill_timeout: float = 2.0,
) -> None:
    live = [process for process in processes if process.poll() is None]
    if not live:
        return

    try:
        import psutil

        targets: list[psutil.Process] = []
        seen: set[int] = set()
        for process in live:
            try:
                root = psutil.Process(process.pid)
                candidates = [*reversed(root.children(recursive=True)), root]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            for candidate in candidates:
                if candidate.pid not in seen:
                    seen.add(candidate.pid)
                    targets.append(candidate)
        for target in targets:
            try:
                target.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(targets, timeout=terminate_timeout)
        for target in alive:
            try:
                target.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if alive:
            psutil.wait_procs(alive, timeout=kill_timeout)
    except ImportError:
        for process in live:
            try:
                process.terminate()
            except OSError:
                pass

    for process in live:
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=kill_timeout)
        except (OSError, subprocess.TimeoutExpired):
            pass


@contextmanager
def managed_processes() -> Iterator[list[subprocess.Popen[Any]]]:
    processes: list[subprocess.Popen[Any]] = []
    try:
        yield processes
    finally:
        terminate_processes(processes)
