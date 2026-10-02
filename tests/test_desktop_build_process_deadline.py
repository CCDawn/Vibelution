"""Exercise the build owner without rebuilding or refreshing a desktop shell."""
import json
import os
import sys
import time

import psutil
import pytest

from core.launcher import desktop_shell

pytestmark = pytest.mark.serial


def test_build_deadline_retires_helper_and_descendant(tmp_path, monkeypatch):
    pid_file = tmp_path / "build-pids.json"
    script = tmp_path / "build-helper.py"
    script.write_text(
        "import os,sys,subprocess,time,json\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
        "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))\n"
        f"Path({str(pid_file)!r}).write_text(json.dumps([os.getpid(),child.pid]))\n"
        "print('controlled build output',flush=True)\ntime.sleep(30)\n",
        encoding="utf8",
    )
    monkeypatch.setattr(desktop_shell, "DESKTOP_SHELL_BUILD_CLEANUP_RESERVE_SECONDS", .5)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="deadline"):
            desktop_shell._run_owned_process(
                [sys.executable, str(script)], cwd=tmp_path,
                deadline=started + 1.2, label="controlled build helper",
            )
        assert pid_file.exists(), "the helper must have run before the timeout"
        pids = json.loads(pid_file.read_text())
        assert all(not psutil.pid_exists(pid) for pid in pids)
        assert time.monotonic() - started < 1.7
        assert not desktop_shell._pending_build_retirement_for(tmp_path)
    finally:
        if pid_file.exists():
            for pid in json.loads(pid_file.read_text()):
                try:
                    process = psutil.Process(pid)
                    # Cleanup only this synthetic script's still-living processes.
                    if str(script) in process.cmdline() or "import time;time.sleep(30)" in process.cmdline():
                        process.kill()
                        process.wait(timeout=2)
                except psutil.NoSuchProcess:
                    pass
