from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from core.infrastructure.owned_process import OwnedProcess
from core.web.services import cli_agent_service
from core.web.services import cli_agent_terminal_service as terminal_service


pytestmark = pytest.mark.serial


@pytest.fixture
def terminal_runtime_environment(monkeypatch, tmp_path):
    result = terminal_service.shutdown_cli_agent_terminal_sessions()
    assert result["closed"]
    terminal_service.begin_cli_agent_terminal_lifecycle()
    monkeypatch.setattr(terminal_service, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(terminal_service, "SESSION_STATE_DIR", tmp_path / "runtime" / "sessions")
    monkeypatch.setattr(terminal_service, "TRANSCRIPT_DIR", tmp_path / "runtime" / "transcripts")
    monkeypatch.setattr(terminal_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli_agent_service, "_record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        terminal_service.cli_agent_task_kernel,
        "mark_terminal_closed",
        lambda *args, **kwargs: None,
    )
    yield tmp_path
    result = terminal_service.shutdown_cli_agent_terminal_sessions()
    assert result["closed"]
    assert not terminal_service._RUNTIMES


def _make_runtime(tmp_path: Path, process, transport: str, session_id: str):
    state = {
        "terminalSessionId": session_id,
        "adapterId": "test-cli",
        "label": "Test CLI",
        "status": "running",
        "alive": True,
        "rows": 24,
        "cols": 80,
        "updatedAt": terminal_service._now_iso(),
    }
    return terminal_service._TerminalRuntime(
        state=state,
        process=process,
        transport=transport,
        transcript_path=tmp_path / "runtime" / "transcripts" / f"{session_id}.txt",
        session_id_regex="",
    )


def _publish_and_start(runtime):
    with terminal_service._RUNTIMES_LOCK:
        terminal_service._RUNTIMES[str(runtime.state["terminalSessionId"])] = runtime
    runtime.start()


def _wait_until(predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    return predicate()


def test_root_exit_retires_descendant_holding_pipe_and_reader(terminal_runtime_environment):
    tmp_path = terminal_runtime_environment
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import subprocess,sys; "
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}], "
        "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)); "
        "print('CHILD:'+str(child.pid), flush=True); sys.stdin.readline()"
    )
    owner = OwnedProcess.spawn(
        [sys.executable, "-c", parent_code],
        cwd=str(tmp_path),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    owner.process._vibelution_terminal_process_owner = owner
    runtime = _make_runtime(tmp_path, owner.process, "pipe", "terminal-inherited-pipe")
    _publish_and_start(runtime)

    def child_pid_from_transcript():
        if not runtime.transcript_path.exists():
            return None
        transcript = runtime.transcript_path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"CHILD:(\d+)\r?\n", transcript)
        return int(match.group(1)) if match else None

    child_pid = _wait_until(child_pid_from_transcript)
    assert child_pid is not None
    assert owner.process.poll() is None
    assert runtime.reader_thread.is_alive(), "the child should hold the inherited stdout pipe open"
    child = psutil.Process(child_pid)
    assert child.is_running()

    owner.process.stdin.write("\n")
    owner.process.stdin.flush()
    assert _wait_until(lambda: owner.process.poll() is not None, timeout=3)
    runtime.reader_thread.join(timeout=5)
    runtime.lifecycle_thread.join(timeout=1)
    assert not runtime.reader_thread.is_alive()
    assert not runtime.lifecycle_thread.is_alive()

    def child_stopped():
        try:
            status = child.status()
            return status in {
                psutil.STATUS_ZOMBIE,
                getattr(psutil, "STATUS_TERMINATED", "terminated"),
                getattr(psutil, "STATUS_DEAD", "dead"),
            } or not child.is_running()
        except psutil.NoSuchProcess:
            return True

    assert child_stopped()
    assert "terminal-inherited-pipe" not in terminal_service._RUNTIMES
    assert owner._closed is True

    result = terminal_service.shutdown_cli_agent_terminal_sessions()
    assert result["closed"] is True, result


@pytest.mark.skipif(os.name != "nt" or terminal_service.PtyProcess is None, reason="ConPTY is available only on Windows with pywinpty")
def test_conpty_runtime_is_closed_with_its_job_and_reader(terminal_runtime_environment):
    tmp_path = terminal_runtime_environment
    process, transport = terminal_service._spawn_terminal_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=str(tmp_path),
        rows=24,
        cols=80,
    )
    assert transport == "conpty"
    runtime = _make_runtime(tmp_path, process, transport, "terminal-conpty-close")
    _publish_and_start(runtime)

    result = terminal_service.shutdown_cli_agent_terminal_sessions()

    assert result["closed"] is True, result
    assert runtime.process_owner._closed is True
    assert process.closed is True
    assert process.fd == -1
    assert process.fileobj.fileno() == -1
    assert process._server.fileno() == -1
    assert process.pty is None
    assert not runtime.reader_thread.is_alive()
    assert not runtime.lifecycle_thread.is_alive()
    assert not process._thread.is_alive()


def test_conpty_job_is_created_before_pty_process(monkeypatch):
    spawned = []

    class FakePtyProcess:
        @staticmethod
        def spawn(*args, **kwargs):
            spawned.append((args, kwargs))
            raise AssertionError("PTY process must not start if Job setup fails")

    def fail_job_creation():
        raise OSError("simulated Job Object creation failure")

    monkeypatch.setattr(terminal_service, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(terminal_service, "PtyProcess", FakePtyProcess)
    monkeypatch.setattr(terminal_service, "WindowsProcessJob", fail_job_creation)

    with pytest.raises(OSError, match="simulated Job Object creation failure"):
        terminal_service._spawn_terminal_process(
            [sys.executable, "-c", "pass"], cwd=".", rows=24, cols=80
        )

    assert not spawned


def test_failed_conpty_adoption_keeps_known_tree_for_shutdown_retry(monkeypatch, terminal_runtime_environment):
    tmp_path = terminal_runtime_environment
    child_assignment_failures = 0
    forced_cleanup_failures = 0
    monkeypatch.setattr(terminal_service, "TERMINAL_SHUTDOWN_TIMEOUT_SECONDS", 0.05)

    class FakeJob:
        def __init__(self):
            self.members = {}
            self.closed = False

        def active_count(self):
            active = 0
            for pid, creation_time in self.members.items():
                try:
                    process = psutil.Process(pid)
                    if (
                        abs(process.create_time() - creation_time) <= 0.01
                        and process.is_running()
                        and process.status() != psutil.STATUS_ZOMBIE
                    ):
                        active += 1
                except psutil.NoSuchProcess:
                    continue
            return active

        def terminate(self):
            for pid, creation_time in list(self.members.items()):
                try:
                    process = psutil.Process(pid)
                    if abs(process.create_time() - creation_time) <= 0.01 and process.is_running():
                        process.kill()
                except psutil.NoSuchProcess:
                    continue

        def close(self):
            self.closed = True

    class FakePtyProcess:
        @staticmethod
        def spawn(args, *, cwd, env, dimensions):
            child_code = "import time; time.sleep(60)"
            parent_code = (
                "import subprocess,sys,time; "
                f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}], "
                "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)); "
                "print(child.pid, flush=True); time.sleep(60)"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", parent_code],
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            child_pid = int(proc.stdout.readline().strip())
            return SimpleNamespace(
                pid=proc.pid,
                child_pid=child_pid,
                _proc=proc,
                pty=SimpleNamespace(cancel_io=lambda: None),
                fileobj=proc.stdout,
                _server=SimpleNamespace(close=lambda: None),
                fd=7,
                closed=False,
                isalive=lambda: proc.poll() is None,
            )

    monkeypatch.setattr(terminal_service, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(terminal_service, "PtyProcess", FakePtyProcess)
    monkeypatch.setattr(terminal_service, "WindowsProcessJob", FakeJob)

    def controlled_assign(owner, process):
        nonlocal child_assignment_failures
        pid = int(process.pid)
        creation_time = float(process.create_time())
        if owner._known_identities.get(pid) != creation_time:
            return False
        if pid == getattr(owner.process, "child_pid", None) and child_assignment_failures < 2:
            child_assignment_failures += 1
            return False
        owner._identities[pid] = creation_time
        owner.job.members[pid] = creation_time
        return True

    monkeypatch.setattr(terminal_service._ConptyProcessOwner, "_assign_process", controlled_assign)
    original_terminate_known = terminal_service._ConptyProcessOwner._terminate_known_processes

    def fail_first_known_cleanup(owner):
        nonlocal forced_cleanup_failures
        if forced_cleanup_failures == 0:
            forced_cleanup_failures += 1
            return False
        return original_terminate_known(owner)

    monkeypatch.setattr(terminal_service._ConptyProcessOwner, "_terminate_known_processes", fail_first_known_cleanup)

    with pytest.raises(terminal_service.CliAgentTerminalError, match="ownership could not be confirmed"):
        terminal_service._spawn_terminal_process(
            [sys.executable, "-c", "pass"], cwd=str(tmp_path), rows=24, cols=80
        )

    assert len(terminal_service._PENDING_CONPTY_OWNERS) == 1
    owner_key, owner = next(iter(terminal_service._PENDING_CONPTY_OWNERS.items()))
    root_pid = owner.pid
    child_pid = owner.process.child_pid
    assert root_pid in owner._known_identities
    assert child_pid in owner._known_identities
    assert owner.initial_adoption_complete is False
    assert owner._identities.get(root_pid) == owner._known_identities[root_pid]
    assert child_assignment_failures == 2
    assert forced_cleanup_failures == 1
    assert psutil.Process(root_pid).is_running()
    assert psutil.Process(child_pid).is_running()

    with pytest.raises(RuntimeError, match="failed ConPTY spawn"):
        terminal_service.begin_cli_agent_terminal_lifecycle()

    spawn_calls = []
    _prepare_ensure_for_spawn_race(
        monkeypatch,
        tmp_path,
        lambda *args, **kwargs: spawn_calls.append((args, kwargs)),
    )
    with pytest.raises(terminal_service.CliAgentTerminalError, match="previous CLI Agent terminal spawn"):
        terminal_service.ensure_cli_agent_terminal_session(
            agent_type="test-cli",
            cwd=str(tmp_path),
            mode="readonly",
            source_session_id="session-test",
        )
    assert not spawn_calls

    monkeypatch.setattr(terminal_service, "TERMINAL_SHUTDOWN_TIMEOUT_SECONDS", 2.0)
    result = terminal_service.shutdown_cli_agent_terminal_sessions()

    assert result["closed"] is True
    assert result["remaining"] == []
    assert terminal_service._PENDING_CONPTY_OWNERS == {}
    assert owner.job.closed is True
    assert owner._closed is True

    def process_alive(pid):
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    assert not process_alive(root_pid)
    assert not process_alive(child_pid)


def test_pywinpty_transport_close_failure_is_not_reported_as_retired():
    class BrokenEndpoint:
        def close(self):
            raise OSError("simulated socket close failure")

    process = SimpleNamespace(pty=None, fileobj=BrokenEndpoint(), _server=None, fd=7, closed=False)

    assert terminal_service._close_pywinpty_transport(process, time.monotonic() + 1) is False
    assert process.fd == 7
    assert process.closed is False


def test_conpty_does_not_claim_a_reused_pid_after_native_root_exit(monkeypatch):
    class Job:
        terminated = 0

        def active_count(self):
            return 0

        def terminate(self):
            self.terminated += 1

        def close(self):
            return None

    process_lookups = []
    monkeypatch.setattr(psutil, "Process", lambda pid: process_lookups.append(pid))
    native_process = SimpleNamespace(pid=456789, pty=SimpleNamespace(cancel_io=lambda: None), isalive=lambda: False)
    job = Job()

    owner = terminal_service._ConptyProcessOwner(native_process, job)

    assert owner.initial_adoption_complete is False
    assert owner.request_stop() is False
    assert process_lookups == []
    assert owner._known_identities == {}
    assert job.terminated == 0


def test_conpty_unknown_tree_snapshot_cannot_authorize_root_termination(monkeypatch):
    class Job:
        terminated = 0

        def active_count(self):
            return 0

        def terminate(self):
            self.terminated += 1

        def close(self):
            return None

    class Root:
        pid = 456790

        def create_time(self):
            return 1234.5

        def children(self, *, recursive):
            raise psutil.NoSuchProcess(self.pid)

    monkeypatch.setattr(psutil, "Process", lambda pid: Root())
    native_process = SimpleNamespace(pid=456790, pty=SimpleNamespace(cancel_io=lambda: None), isalive=lambda: True)
    job = Job()

    owner = terminal_service._ConptyProcessOwner(native_process, job)

    assert owner.initial_adoption_complete is False
    assert owner._known_tree_complete is False
    assert owner.request_stop() is False
    assert owner._known_tree_complete is False
    assert job.terminated == 0


def test_shutdown_keeps_pending_runtime_and_pipe_open_until_reader_finishes(monkeypatch, terminal_runtime_environment):
    tmp_path = terminal_runtime_environment
    monkeypatch.setattr(terminal_service, "TERMINAL_SHUTDOWN_TIMEOUT_SECONDS", 0.05)
    reader_release = threading.Event()
    stream_closed = threading.Event()
    owner_closed = threading.Event()

    class Stream:
        def close(self):
            stream_closed.set()

    class Process:
        stdin = Stream()
        stdout = Stream()
        stderr = None

        def poll(self):
            return None

        def terminate(self):
            return None

    class Owner:
        def request_stop(self):
            return True

        def wait_until_stopped(self, deadline):
            return True

        def close(self, deadline):
            owner_closed.set()
            return True

    process = Process()
    process._vibelution_terminal_process_owner = Owner()
    runtime = _make_runtime(tmp_path, process, "pipe", "terminal-reader-pending")
    runtime.reader_thread = threading.Thread(target=reader_release.wait, daemon=True)
    runtime.reader_thread.start()
    with terminal_service._RUNTIMES_LOCK:
        terminal_service._RUNTIMES["terminal-reader-pending"] = runtime

    result = terminal_service.shutdown_cli_agent_terminal_sessions()

    assert result["closed"] is False
    assert result["remaining"] == ["terminal-reader-pending"]
    assert terminal_service._RUNTIMES["terminal-reader-pending"] is runtime
    assert not stream_closed.is_set()
    assert not owner_closed.is_set()

    reader_release.set()
    runtime.reader_thread.join(timeout=1)
    retry = terminal_service.shutdown_cli_agent_terminal_sessions()

    assert retry["closed"] is True
    assert stream_closed.is_set()
    assert owner_closed.is_set()
    assert "terminal-reader-pending" not in terminal_service._RUNTIMES


def _prepare_ensure_for_spawn_race(monkeypatch, tmp_path, fake_spawn):
    monkeypatch.setattr(cli_agent_service, "_normalize_id", lambda value: str(value or "").strip().lower())
    monkeypatch.setattr(terminal_service, "_scope_cwd", lambda cwd, *, mode: str(tmp_path))
    monkeypatch.setattr(terminal_service, "_stable_terminal_session_id", lambda **kwargs: "terminal-late-spawn")
    monkeypatch.setattr(terminal_service, "_stable_cli_lock_key", lambda **kwargs: "test-lock")
    monkeypatch.setattr(terminal_service, "_stable_cli_run_id", lambda **kwargs: "test-run")
    monkeypatch.setattr(terminal_service, "_read_state", lambda session_id: {})
    monkeypatch.setattr(terminal_service, "_find_related_terminal_state", lambda **kwargs: {})
    monkeypatch.setattr(terminal_service, "_find_active_related_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(terminal_service, "_source_bound_attach_should_not_resume_stale_state", lambda *args, **kwargs: False)
    monkeypatch.setattr(terminal_service, "_find_active_locked_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        terminal_service,
        "_build_terminal_command",
        lambda **kwargs: {
            "adapterId": "test-cli",
            "label": "Test CLI",
            "args": [sys.executable],
            "cwd": str(tmp_path),
            "mode": "readonly",
            "sessionIdRegex": "",
            "preview": [],
            "resumed": False,
            "initialInput": "",
        },
    )
    monkeypatch.setattr(
        terminal_service,
        "_initial_state",
        lambda **kwargs: {
            "terminalSessionId": "terminal-late-spawn",
            "adapterId": "test-cli",
            "label": "Test CLI",
            "status": "starting",
            "alive": False,
            "rows": 24,
            "cols": 80,
            "updatedAt": terminal_service._now_iso(),
        },
    )
    monkeypatch.setattr(terminal_service, "_spawn_terminal_process", fake_spawn)
    monkeypatch.setattr(terminal_service, "_supersede_related_terminal_states", lambda *args, **kwargs: None)
    monkeypatch.setattr(terminal_service, "_transcript_path", lambda session_id: tmp_path / "transcripts" / f"{session_id}.txt")
    monkeypatch.setattr(terminal_service, "_relative_to_project", lambda path: str(path))
    monkeypatch.setattr(terminal_service._TerminalRuntime, "start", lambda self: None)
    monkeypatch.setattr(terminal_service, "_send_initial_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(terminal_service, "_schedule_session_id_discovery", lambda *args, **kwargs: None)


def test_spawn_returning_after_shutdown_broadcast_is_retired_before_publication(monkeypatch, terminal_runtime_environment):
    tmp_path = terminal_runtime_environment
    spawn_entered = threading.Event()
    release_spawn = threading.Event()
    spawned: list[OwnedProcess] = []

    def blocking_spawn(*args, **kwargs):
        spawn_entered.set()
        assert release_spawn.wait(3)
        owner = OwnedProcess.spawn(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=str(tmp_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        owner.process._vibelution_terminal_process_owner = owner
        spawned.append(owner)
        return owner.process, "pipe"

    _prepare_ensure_for_spawn_race(monkeypatch, tmp_path, blocking_spawn)
    errors: list[BaseException] = []

    def create_session():
        try:
            terminal_service.ensure_cli_agent_terminal_session(
                agent_type="test-cli",
                cwd=str(tmp_path),
                mode="readonly",
                source_session_id="session-test",
            )
        except BaseException as exc:  # captured for assertion in the test thread
            errors.append(exc)

    ensure_thread = threading.Thread(target=create_session, daemon=True)
    ensure_thread.start()
    assert spawn_entered.wait(1)
    shutdown_result: list[dict] = []
    shutdown_thread = threading.Thread(
        target=lambda: shutdown_result.append(terminal_service.shutdown_cli_agent_terminal_sessions()),
        daemon=True,
    )
    shutdown_thread.start()
    assert _wait_until(terminal_service._TERMINAL_SHUTDOWN_EVENT.is_set, timeout=1)
    release_spawn.set()
    ensure_thread.join(timeout=5)
    shutdown_thread.join(timeout=5)

    assert not ensure_thread.is_alive()
    assert not shutdown_thread.is_alive()
    assert errors and isinstance(errors[0], terminal_service.CliAgentTerminalError)
    assert errors[0].code == "TERMINAL_SESSION_NOT_RUNNING"
    assert len(spawned) == 1
    assert spawned[0].process.poll() is not None
    assert shutdown_result and shutdown_result[0]["closed"] is True
    assert "terminal-late-spawn" not in terminal_service._RUNTIMES


def test_ensure_does_not_replace_runtime_with_pending_cleanup(monkeypatch, terminal_runtime_environment):
    tmp_path = terminal_runtime_environment
    reader_release = threading.Event()
    cleanup_allowed = threading.Event()
    process_closed = threading.Event()
    spawn_calls = []

    class Process:
        stdin = None
        stdout = None
        stderr = None

        def poll(self):
            return 0

    class Owner:
        def request_stop(self):
            return True

        def wait_until_stopped(self, deadline):
            return cleanup_allowed.is_set()

        def close(self, deadline):
            process_closed.set()
            return cleanup_allowed.is_set()

    process = Process()
    process._vibelution_terminal_process_owner = Owner()
    runtime = _make_runtime(tmp_path, process, "pipe", "terminal-cleanup-pending")
    runtime.reader_thread = threading.Thread(target=reader_release.wait, daemon=True)
    runtime.reader_thread.start()
    with terminal_service._RUNTIMES_LOCK:
        terminal_service._RUNTIMES["terminal-late-spawn"] = runtime

    def unexpected_spawn(*args, **kwargs):
        spawn_calls.append((args, kwargs))
        raise AssertionError("a replacement process must wait for the old runtime to retire")

    _prepare_ensure_for_spawn_race(monkeypatch, tmp_path, unexpected_spawn)

    with pytest.raises(terminal_service.CliAgentTerminalError) as exc_info:
        terminal_service.ensure_cli_agent_terminal_session(
            agent_type="test-cli",
            cwd=str(tmp_path),
            mode="readonly",
            source_session_id="session-test",
        )

    assert exc_info.value.code == "TERMINAL_SESSION_NOT_RUNNING"
    assert "still being cleaned up" in exc_info.value.message
    assert not spawn_calls
    assert terminal_service._RUNTIMES["terminal-late-spawn"] is runtime
    assert not process_closed.is_set()

    cleanup_allowed.set()
    reader_release.set()
    runtime.reader_thread.join(timeout=1)
    result = terminal_service.shutdown_cli_agent_terminal_sessions()
    assert result["closed"] is True
    assert process_closed.is_set()
    assert "terminal-late-spawn" not in terminal_service._RUNTIMES
