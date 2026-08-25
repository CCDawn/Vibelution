from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from tests.helpers.managed_processes import managed_processes


def _wait_for_file(path: Path, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def _wait_for_pid_exit(pid: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid):
            return
        time.sleep(0.01)
    raise AssertionError(f"process {pid} is still alive")


def test_managed_processes_terminates_descendants_when_body_fails(tmp_path: Path) -> None:
    grandchild_pid_path = tmp_path / "grandchild.pid"
    wrapper = "\n".join(
        [
            "import subprocess",
            "import sys",
            "import time",
            "from pathlib import Path",
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])",
            "Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')",
            "time.sleep(300)",
        ]
    )

    process: subprocess.Popen[str] | None = None
    grandchild_pid = 0
    with pytest.raises(RuntimeError, match="barrier failed"):
        with managed_processes() as processes:
            process = subprocess.Popen(
                [sys.executable, "-c", wrapper, str(grandchild_pid_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if os.name == "nt"
                else 0,
            )
            processes.append(process)
            _wait_for_file(grandchild_pid_path)
            grandchild_pid = int(grandchild_pid_path.read_text(encoding="utf-8"))
            raise RuntimeError("barrier failed")

    assert process is not None
    assert process.poll() is not None
    _wait_for_pid_exit(grandchild_pid)
