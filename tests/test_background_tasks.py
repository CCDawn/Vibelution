import json
import os
import sys
import time
import threading

import psutil
import pytest

from core.infrastructure.background_tasks import BackgroundTaskManager

pytestmark = pytest.mark.serial


@pytest.fixture(autouse=True)
def isolated_events(monkeypatch):
    from core.infrastructure import background_tasks
    monkeypatch.setattr(background_tasks, "_record_event", lambda *args, **kwargs: None)


def wait_for(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    assert predicate()


def command(script):
    return f'"{sys.executable}" "{script}"'


def cleanup(manager, pid_file=None):
    if pid_file is not None and pid_file.exists():
        try:
            process = psutil.Process(int(pid_file.read_text()))
            process.kill()
            process.wait(timeout=3)
        except psutil.NoSuchProcess:
            pass
    if hasattr(manager, "shutdown"):
        assert manager.shutdown(timeout=4)["closed"]
    else:
        manager._executor.shutdown(wait=True, cancel_futures=True)


def test_running_cancel_confirms_exit_and_preserves_cancelled(tmp_path):
    pid = tmp_path / "pid"
    late = tmp_path / "late"
    script = tmp_path / "held.py"
    script.write_text(f"import os,time\nfrom pathlib import Path\nPath({str(pid)!r}).write_text(str(os.getpid()))\ntime.sleep(20)\nPath({str(late)!r}).touch()\n", encoding="utf8")
    manager = BackgroundTaskManager(max_workers=1)
    try:
        task = json.loads(manager.start_task(command(script)))['task_id']
        wait_for(pid.exists)
        result = json.loads(manager.stop_task(task))
        assert result["status"] == "cancelled"
        assert not psutil.pid_exists(int(pid.read_text()))
        assert json.loads(manager.get_task_output(task))["status"] == "cancelled"
        assert not late.exists()
    finally:
        cleanup(manager, pid)


def test_streams_are_drained_but_retained_output_is_bounded(tmp_path):
    script = tmp_path / "output.py"
    script.write_text("import sys\nsys.stdout.write('x'*1048576)\nsys.stderr.write('y'*1048576)\n", encoding="utf8")
    manager = BackgroundTaskManager(output_limit_bytes=1024)
    try:
        task = json.loads(manager.start_task(command(script)))['task_id']
        result = wait_for(lambda: (r if (r := json.loads(manager.get_task_output(task))).get("status") == "completed" else None))
        assert len(result["output"].encode()) <= 1024
        assert len(result["stderr"].encode()) <= 1024
        assert result["output_truncated"] and result["stderr_truncated"]
        assert result["stdout_bytes"] == result["stderr_bytes"] == 1048576
        assert "_future" not in manager._tasks[task]
    finally:
        cleanup(manager)


def test_finished_history_is_bounded(tmp_path):
    script = tmp_path / "done.py"
    script.write_text("print('done')\n", encoding="utf8")
    manager = BackgroundTaskManager(max_history=3)
    try:
        for _ in range(7):
            task = json.loads(manager.start_task(command(script)))['task_id']
            wait_for(lambda: json.loads(manager.get_task_output(task)).get("status") == "completed")
        assert json.loads(manager.list_tasks())["count"] <= 3
        assert all("_future" not in record for record in manager._tasks.values())
    finally:
        cleanup(manager)


def test_queued_cancel_never_starts_and_admission_is_bounded(tmp_path):
    pid = tmp_path / "pid"
    marker = tmp_path / "not-started"
    held = tmp_path / "held.py"
    held.write_text(f"import os,time\nfrom pathlib import Path\nPath({str(pid)!r}).write_text(str(os.getpid()))\ntime.sleep(20)\n", encoding="utf8")
    queued = tmp_path / "queued.py"
    queued.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf8")
    manager = BackgroundTaskManager(max_workers=1, max_pending=1)
    try:
        active = json.loads(manager.start_task(command(held)))['task_id']
        wait_for(pid.exists)
        waiting = json.loads(manager.start_task(command(queued)))['task_id']
        assert json.loads(manager.start_task(command(queued)))["code"] == "QUEUE_FULL"
        assert json.loads(manager.stop_task(waiting))["status"] == "cancelled"
        assert json.loads(manager.stop_task(active))["status"] == "cancelled"
        assert not marker.exists()
    finally:
        cleanup(manager, pid)


def test_shutdown_rejects_new_work_and_is_idempotent():
    manager = BackgroundTaskManager()
    result = manager.shutdown(timeout=1)
    assert result["closed"]
    assert manager.shutdown(timeout=1)["closed"]
    assert json.loads(manager.start_task("synthetic"))["code"] == "SHUTTING_DOWN"


def test_timeout_retires_real_command_tree(tmp_path):
    pid = tmp_path / "pid"
    script = tmp_path / "timeout.py"
    script.write_text(f"import os,time\nfrom pathlib import Path\nPath({str(pid)!r}).write_text(str(os.getpid()))\ntime.sleep(20)\n", encoding="utf8")
    manager = BackgroundTaskManager()
    try:
        task = json.loads(manager.start_task(command(script), timeout=1))["task_id"]
        wait_for(pid.exists)
        wait_for(lambda: json.loads(manager.get_task_output(task)).get("status") == "failed")
        assert not psutil.pid_exists(int(pid.read_text()))
        assert "超时" in json.loads(manager.get_task_output(task))["output"]
    finally:
        cleanup(manager, pid)


def test_shutdown_during_spawn_retains_ownership_until_late_child_retires(monkeypatch, tmp_path):
    from core.infrastructure import background_tasks
    entered, release = threading.Event(), threading.Event()
    original_spawn = background_tasks.OwnedProcess.spawn
    owners = []

    def delayed_spawn(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        owner = original_spawn(*args, **kwargs)
        owners.append(owner)
        return owner

    monkeypatch.setattr(background_tasks.OwnedProcess, "spawn", delayed_spawn)
    script = tmp_path / "held.py"
    script.write_text("import time\ntime.sleep(20)\n", encoding="utf8")
    manager = BackgroundTaskManager()
    try:
        task = json.loads(manager.start_task(command(script)))["task_id"]
        assert entered.wait(2)
        started = time.monotonic()
        result = manager.shutdown(timeout=.05)
        assert not result["closed"] and result["remaining"] == [task]
        assert time.monotonic() - started < .5
        release.set()
        wait_for(lambda: json.loads(manager.get_task_output(task)).get("status") == "cancelled")
        assert owners and not psutil.pid_exists(owners[0].pid)
    finally:
        release.set()
        cleanup(manager)


def test_expired_history_is_removed_without_timer(tmp_path):
    script = tmp_path / "done.py"
    script.write_text("print('done')\n", encoding="utf8")
    manager = BackgroundTaskManager(history_ttl_seconds=.15)
    try:
        task = json.loads(manager.start_task(command(script)))["task_id"]
        wait_for(lambda: json.loads(manager.get_task_output(task)).get("status") == "completed")
        time.sleep(.2)
        assert json.loads(manager.get_task_output(task))["code"] == "NOT_FOUND"
        assert not manager._tasks
    finally:
        cleanup(manager)


def test_shutdown_recovers_all_running_commands_with_one_deadline(tmp_path):
    pid_files = [tmp_path / f"pid-{i}" for i in range(3)]
    manager = BackgroundTaskManager(max_workers=3)
    try:
        for i, pid in enumerate(pid_files):
            script = tmp_path / f"held-{i}.py"
            script.write_text(f"import os,time\nfrom pathlib import Path\nPath({str(pid)!r}).write_text(str(os.getpid()))\ntime.sleep(20)\n", encoding="utf8")
            manager.start_task(command(script))
        wait_for(lambda: all(pid.exists() for pid in pid_files))
        started = time.monotonic()
        assert manager.shutdown(timeout=2)["closed"]
        assert time.monotonic() - started < 2.5
        assert all(not psutil.pid_exists(int(pid.read_text())) for pid in pid_files)
        assert all(not thread.name.startswith("background-output-") for thread in threading.enumerate())
    finally:
        for pid in pid_files:
            cleanup(manager, pid)


def test_global_shutdown_does_not_create_unused_manager_and_allows_new_lifespan(monkeypatch):
    from core.infrastructure import background_tasks
    monkeypatch.setattr(background_tasks, "_bg_task_manager", None)
    monkeypatch.setattr(background_tasks, "_manager_closing", False)
    assert background_tasks.shutdown_background_tasks()["closed"]
    assert background_tasks._bg_task_manager is None
    with pytest.raises(RuntimeError, match="shutting down"):
        background_tasks.get_background_task_manager()
    background_tasks.begin_background_task_lifecycle()
    first = background_tasks.get_background_task_manager()
    assert background_tasks.shutdown_background_tasks()["closed"]
    background_tasks.begin_background_task_lifecycle()
    second = background_tasks.get_background_task_manager()
    try:
        assert first is not second
        assert json.loads(first.start_task("synthetic"))["code"] == "SHUTTING_DOWN"
    finally:
        background_tasks.shutdown_background_tasks()


def test_failed_owner_close_retains_record_and_can_be_retried(monkeypatch, tmp_path):
    from core.infrastructure import background_tasks
    original_close = background_tasks.OwnedProcess.close
    attempts = []

    def fail_once(owner, **kwargs):
        attempts.append(owner)
        if len(attempts) == 1:
            raise OSError("synthetic close failure")
        return original_close(owner, **kwargs)

    monkeypatch.setattr(background_tasks.OwnedProcess, "close", fail_once)
    pid = tmp_path / "pid"
    script = tmp_path / "held.py"
    script.write_text(f"import os,time\nfrom pathlib import Path\nPath({str(pid)!r}).write_text(str(os.getpid()))\ntime.sleep(20)\n", encoding="utf8")
    manager = BackgroundTaskManager()
    try:
        task = json.loads(manager.start_task(command(script)))["task_id"]
        wait_for(pid.exists)
        assert json.loads(manager.stop_task(task, timeout=.2))["status"] == "running"
        wait_for(lambda: manager._tasks[task]["cleanup_pending"])
        assert manager._tasks[task]["_owner"] is attempts[0]
        assert json.loads(manager.stop_task(task))["status"] == "cancelled"
        assert not psutil.pid_exists(int(pid.read_text()))
        assert manager._tasks[task]["_owner"] is None
    finally:
        cleanup(manager, pid)
