import os
import subprocess
import sys
import time

import psutil
import pytest

from core.infrastructure.owned_process import OwnedProcess

pytestmark = pytest.mark.serial


def _until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment")
def test_retire_descendants_after_root_already_exited(tmp_path):
    marker = tmp_path / "child.pid"
    script = tmp_path / "parent.py"
    script.write_text(
        "import subprocess,sys\nfrom pathlib import Path\n"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],"
        "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))\n"
        f"Path({str(marker)!r}).write_text(str(p.pid))\n",
        encoding="utf8",
    )
    owner = OwnedProcess.spawn([sys.executable, str(script)], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _until(marker.exists)
        child = psutil.Process(int(marker.read_text()))
        owner.process.wait(timeout=5)
        assert child.is_running()
        assert owner.terminate(timeout=3)
        _until(lambda: not child.is_running())
        owner.close()
    finally:
        owner.terminate(timeout=3)
        owner.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job owner crash")
def test_owner_crash_closes_job_and_reaps_tree(tmp_path):
    marker = tmp_path / "owned.pid"
    script = tmp_path / "owner.py"
    script.write_text(
        "import os,sys,subprocess\nfrom pathlib import Path\n"
        "from core.infrastructure.owned_process import OwnedProcess\n"
        "p=OwnedProcess.spawn([sys.executable,'-c','import time;time.sleep(120)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        f"Path({str(marker)!r}).write_text(str(p.pid))\n"
        "os._exit(0)\n",
        encoding="utf8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(__import__("pathlib").Path(__file__).resolve().parents[1])
    from scripts.windowless_subprocess import no_window_subprocess_kwargs
    process = subprocess.Popen([sys.executable, str(script)], env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, **no_window_subprocess_kwargs())
    try:
        output, error = process.communicate(timeout=10)
        assert process.returncode == 0, (output, error)
        assert marker.exists()
        _until(lambda: not psutil.pid_exists(int(marker.read_text())))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job assignment")
def test_assignment_failure_never_runs_suspended_child(tmp_path, monkeypatch):
    from core.infrastructure.windows_process_job import WindowsProcessJob
    marker = tmp_path / "must-not-run"
    spawned = []
    original_popen = subprocess.Popen

    def keep_process(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        spawned.append(process)
        return process

    def fail(self, handle):
        raise OSError("synthetic Job assignment failure")
    monkeypatch.setattr(subprocess, "Popen", keep_process)
    monkeypatch.setattr(WindowsProcessJob, "assign_handle", fail)
    with pytest.raises(OSError, match="synthetic"):
        OwnedProcess.spawn([sys.executable, "-c", f"from pathlib import Path;Path({str(marker)!r}).touch()"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert not marker.exists()
    assert len(spawned) == 1
    assert spawned[0].returncode is not None
    assert spawned[0]._handle.closed


@pytest.mark.skipif(os.name != "nt", reason="Windows process and Job handle disposal")
def test_completed_owners_release_handles_without_waiting_for_garbage_collection():
    owners = []
    current = psutil.Process()
    before = current.num_handles()
    try:
        for _ in range(10):
            owner = OwnedProcess.spawn([sys.executable, "-c", "pass"],
                                       stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            owners.append(owner)
            owner.process.wait(timeout=3)
            owner.close()
            assert owner._job._handle is None
            assert owner.process._handle.closed
        # On Windows each retained Python owner/Popen lock has a kernel handle;
        # they are ordinary object state, separate from the closed process/Job.
        owners.clear()
        del owner
        assert current.num_handles() <= before + 2
    finally:
        for owner in owners:
            owner.close()
