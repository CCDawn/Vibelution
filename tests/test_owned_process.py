import os
import subprocess
import sys
import time
from types import SimpleNamespace

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


class _AbortJob:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.closed = False
        self.terminate_calls = 0
        self.close_calls = 0

    def active_count(self):
        return 0 if self.closed else 1

    def terminate(self):
        self.terminate_calls += 1
        if self.failure == "terminate":
            raise OSError("synthetic terminate failure")

    def close(self):
        self.close_calls += 1
        if self.failure == "close":
            raise OSError("synthetic Job close failure")
        self.closed = True


def _fake_abort_owner(*, failure=None):
    handle = SimpleNamespace(closed=False)
    handle.Close = lambda: setattr(handle, "closed", True)
    process = SimpleNamespace(pid=1, returncode=None, _handle=handle)
    process.poll = lambda: process.returncode
    return OwnedProcess(process, _AbortJob(failure=failure))


def test_abort_releases_job_without_claiming_retirement_and_reaps_only_exited_root():
    owner = _fake_abort_owner()
    assert owner.abort(timeout=0) is None
    assert owner._job.closed
    assert owner._job.active_count() == 0
    assert not owner.process._handle.closed
    assert not owner._closed
    assert owner._active()
    assert owner.terminate(timeout=0) is False
    with pytest.raises(RuntimeError, match="has not finished retiring"):
        owner.close(timeout=0)

    owner.process.returncode = 1
    owner.abort(timeout=0)
    assert owner.process._handle.closed
    assert owner._active()
    assert owner.terminate(timeout=0) is False
    assert not owner._closed


@pytest.mark.parametrize("failure", ["terminate", "close"])
def test_abort_failure_keeps_retirement_unconfirmed_and_still_disposes_exited_root(failure):
    owner = _fake_abort_owner(failure=failure)
    owner.process.returncode = 1
    with pytest.raises(OSError, match="synthetic"):
        owner.abort(timeout=0)
    assert owner._job.close_calls == 1
    assert owner._job.closed is (failure == "terminate")
    assert owner.process._handle.closed
    assert owner.terminate(timeout=0) is False
    assert not owner._closed


def test_abort_lock_contention_has_a_deadline():
    owner = _fake_abort_owner()
    owner._lock.acquire()
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="abort is still in progress"):
            owner.abort(timeout=0.02)
        assert time.monotonic() - started < 0.5
        assert not owner._aborted
        assert not owner._job.closed
    finally:
        owner._lock.release()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job abort after failed retirement")
@pytest.mark.parametrize("root_exits", [False, True])
def test_abort_after_close_failure_retires_real_pipe_holding_tree(tmp_path, monkeypatch, root_exits):
    marker = tmp_path / "aborted-child.pid"
    script = tmp_path / "parent.py"
    script.write_text(
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],"
        "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))\n"
        f"Path({str(marker)!r}).write_text(str(p.pid))\n"
        "print('ready',flush=True)\n"
        f"if not {root_exits!r}: time.sleep(120)\n",
        encoding="utf-8",
    )
    owner = OwnedProcess.spawn(
        [sys.executable, str(script)], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        _until(marker.exists)
        child = psutil.Process(int(marker.read_text()))
        if root_exits:
            owner.process.wait(timeout=5)
        with monkeypatch.context() as patch:
            patch.setattr(owner, "terminate", lambda **kwargs: False)
            with pytest.raises(RuntimeError, match="has not finished retiring"):
                owner.close(timeout=0)
        assert owner._job._handle is not None
        assert owner.abort(timeout=1) is None
        assert owner._job._handle is None
        output, _error = owner.process.communicate(timeout=2)
        owner.abort(timeout=0)
        assert b"ready" in output
        _until(lambda: not child.is_running())
        assert owner.process.returncode is not None
        assert owner.process._handle.closed
        assert owner.terminate(timeout=0) is False
        assert not owner._closed
        with pytest.raises(RuntimeError, match="has not finished retiring"):
            owner.close(timeout=0)
    finally:
        owner.abort(timeout=2)
        owner.process.communicate(timeout=2)
        owner.abort(timeout=0)
