from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from core.infrastructure import git_process
from core.infrastructure import no_console_git as ncg


@pytest.mark.parametrize("root_exits", [False, True])
@pytest.mark.skipif(os.name != "nt", reason="Windows Job and inherited PIPE regression")
@pytest.mark.serial
def test_run_git_owned_timeout_retires_root_and_pipe_holding_child(monkeypatch, tmp_path, root_exits):
    marker = tmp_path / "owned-pids.json"
    ready = marker.with_suffix(".ready")
    script = tmp_path / "parent.py"
    child_code = (
        "import sys,time;from pathlib import Path;"
        "print('child-out',flush=True);print('child-err',file=sys.stderr,flush=True);"
        "Path(sys.argv[1]).with_suffix('.ready').touch();time.sleep(30)"
    )
    script.write_text(
        "import json,os,subprocess,sys,time\n"
        "from pathlib import Path\n"
        f"child = subprocess.Popen([sys.executable, '-S', '-c', {child_code!r}, "
        "sys.argv[1]], stdin=subprocess.DEVNULL, "
        "creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))\n"
        "print('root-out', flush=True)\n"
        "Path(sys.argv[1]).write_text(json.dumps([os.getpid(), child.pid]))\n"
        "if sys.argv[2] == 'False': time.sleep(30)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: sys.executable)
    monkeypatch.setattr(git_process, "_record_git_process_scene_event", lambda *args, **kwargs: None)
    # Measure tree retirement independently of the existing CLI logger's cold import.
    monkeypatch.setattr(git_process._debug_logger, "error", lambda *args, **kwargs: None)
    timeout = 1.5
    command = [sys.executable, "-S", str(script), str(marker), str(root_exits)]
    owner = git_process.OwnedProcess.spawn(
        command, cwd=tmp_path, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Hand over a real, ready Job tree so cold Python startup cannot consume
        # the timeout before the fixture has even created its pipe-holding child.
        deadline = time.monotonic() + 15
        while not (marker.exists() and ready.exists()):
            assert time.monotonic() < deadline, "parent/child fixture did not become ready"
            time.sleep(0.02)
        if root_exits:
            owner.process.wait(timeout=5)
        monkeypatch.setattr(git_process.OwnedProcess, "spawn", lambda *args, **kwargs: owner)
        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired) as raised:
            git_process.run_git(
                command[1:],
                cwd=tmp_path,
                timeout=timeout,
                capture_output=True,
                text=True,
                own_process_tree=True,
                retries=0,
            )
        elapsed = time.monotonic() - started
        assert elapsed < timeout + 2 * git_process.GIT_PROCESS_CLEANUP_TIMEOUT_SECONDS + 0.75
        assert raised.value.timeout == timeout
        assert "root-out" in git_process._process_output_text(raised.value.stdout)
        assert "child-out" in git_process._process_output_text(raised.value.stdout)
        assert "child-err" in git_process._process_output_text(raised.value.stderr)
        pids = json.loads(marker.read_text())
        assert len(pids) == 2
        assert owner.process.returncode is not None
        assert all(not psutil.pid_exists(pid) for pid in {owner.pid, *pids})
    finally:
        owner.abort(timeout=2)
        owner.process.communicate(timeout=2)
        owner.abort(timeout=0)


def test_run_git_owned_timeout_never_drains_without_a_deadline(monkeypatch, tmp_path):
    calls = []
    closed = []
    timeout_error = subprocess.TimeoutExpired(["git.exe", "worktree", "add"], 0.5, output=b"partial")

    def communicate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise timeout_error
        raise subprocess.TimeoutExpired(timeout_error.cmd, kwargs["timeout"])

    def spawn(command, **kwargs):
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.PIPE
        assert kwargs["stdin"] == subprocess.DEVNULL
        if os.name == "nt":
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        return SimpleNamespace(
            process=SimpleNamespace(communicate=communicate),
            close=lambda **kwargs: closed.append(kwargs),
        )

    monkeypatch.setattr(git_process.OwnedProcess, "spawn", spawn)
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: "git.exe")
    monkeypatch.setattr(git_process, "_record_git_process_scene_event", lambda *args, **kwargs: None)
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        git_process.run_git(
            ["worktree", "add"], cwd=tmp_path, timeout=0.5,
            capture_output=True, own_process_tree=True, retries=0,
        )
    assert raised.value is timeout_error
    assert raised.value.stdout == b"partial"
    assert calls == [
        {"input": None, "timeout": 0.5},
        {"timeout": git_process.GIT_PROCESS_CLEANUP_TIMEOUT_SECONDS},
    ]
    assert closed == [{"timeout": git_process.GIT_PROCESS_CLEANUP_TIMEOUT_SECONDS}]


@pytest.mark.parametrize("drain_times_out", [False, True])
@pytest.mark.parametrize("abort_raises", [False, True])
def test_run_git_owned_close_failure_preserves_timeout_and_bounded_drain(
    monkeypatch, tmp_path, drain_times_out, abort_raises,
):
    communicated = []
    closed = []
    aborted = []
    events = []
    timeout_error = subprocess.TimeoutExpired(["git.exe", "worktree", "add"], 0.5, output=b"partial")

    def communicate(**kwargs):
        communicated.append(kwargs)
        if len(communicated) == 1:
            raise timeout_error
        if drain_times_out:
            raise subprocess.TimeoutExpired(timeout_error.cmd, kwargs["timeout"])
        return b"drained-out", b"drained-err"

    def close(**kwargs):
        closed.append(kwargs)
        raise RuntimeError("synthetic close failure")

    def abort(**kwargs):
        aborted.append(kwargs)
        if abort_raises:
            raise OSError("synthetic abort failure")

    owner = SimpleNamespace(process=SimpleNamespace(communicate=communicate), close=close, abort=abort)
    monkeypatch.setattr(git_process.OwnedProcess, "spawn", lambda *args, **kwargs: owner)
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: "git.exe")
    monkeypatch.setattr(git_process._debug_logger, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        git_process, "_record_git_process_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        git_process.run_git(
            ["worktree", "add"], cwd=tmp_path, timeout=0.5,
            capture_output=True, own_process_tree=True, retries=0,
        )
    assert raised.value is timeout_error
    assert communicated == [
        {"input": None, "timeout": 0.5},
        {"timeout": git_process.GIT_PROCESS_CLEANUP_TIMEOUT_SECONDS},
    ]
    assert closed == [{"timeout": git_process.GIT_PROCESS_CLEANUP_TIMEOUT_SECONDS}]
    assert aborted == [{"timeout": git_process.GIT_PROCESS_CLEANUP_TIMEOUT_SECONDS}, {"timeout": 0.0}]
    assert raised.value.git_process_owner is owner
    assert any("RuntimeError" in note for note in raised.value.__notes__)
    if abort_raises:
        assert any("abort failed" in note and "OSError" in note for note in raised.value.__notes__)
    assert events[0][0][1] == "git_process.command.timeout"
    if drain_times_out:
        assert raised.value.stdout == b"partial"
    else:
        assert raised.value.stdout == b"drained-out"
        assert raised.value.stderr == b"drained-err"


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("combine_stderr", [False, True])
@pytest.mark.serial
def test_run_git_owned_preserves_output_and_check(monkeypatch, tmp_path, text, combine_stderr):
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: sys.executable)
    monkeypatch.setattr(git_process, "_record_git_process_scene_event", lambda *args, **kwargs: None)
    output_kwargs = (
        {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
        if combine_stderr else {"capture_output": True}
    )
    with pytest.raises(subprocess.CalledProcessError) as raised:
        git_process.run_git(
            ["-c", "import sys;print('out');print('err',file=sys.stderr);sys.exit(3)"],
            cwd=tmp_path, timeout=5, own_process_tree=True, check=True, retries=0,
            text=text, **output_kwargs,
        )
    assert raised.value.returncode == 3
    expected_type = str if text else bytes
    assert isinstance(raised.value.stdout, expected_type)
    assert "out" in git_process._process_output_text(raised.value.stdout)
    if combine_stderr:
        assert "err" in git_process._process_output_text(raised.value.stdout)
        assert raised.value.stderr is None
    else:
        assert isinstance(raised.value.stderr, expected_type)
        assert "err" in git_process._process_output_text(raised.value.stderr)


@pytest.mark.serial
def test_run_git_owned_can_redirect_output_to_files(monkeypatch, tmp_path):
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: sys.executable)
    with (tmp_path / "output").open("wb") as output:
        result = git_process.run_git(
            ["-c", "import sys;print('out');print('err',file=sys.stderr)"],
            cwd=tmp_path, own_process_tree=True, stdout=output, stderr=output, retries=0,
        )
    assert result.returncode == 0
    assert result.stdout is None and result.stderr is None
    assert set((tmp_path / "output").read_text().splitlines()) == {"out", "err"}


def test_resolve_git_executable_prefers_direct_windows_git(monkeypatch, tmp_path):
    install_root = tmp_path / "Git"
    cmd_git = install_root / "cmd" / "git.exe"
    direct_git = install_root / "mingw64" / "bin" / "git.exe"
    cmd_git.parent.mkdir(parents=True)
    direct_git.parent.mkdir(parents=True)
    cmd_git.write_bytes(b"x" * 40_000)
    direct_git.write_bytes(b"y" * 500_000)

    monkeypatch.setattr(ncg, "_is_windows", lambda: True)
    monkeypatch.setattr(ncg.shutil, "which", lambda name: str(cmd_git) if name in {"git", "git.exe"} else None)
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LocalAppData", raising=False)
    ncg.clear_git_executable_cache()

    try:
        assert Path(git_process.resolve_git_executable()) == direct_git.resolve()
    finally:
        ncg.clear_git_executable_cache()


def test_resolve_git_executable_falls_back_to_discovered_git(monkeypatch, tmp_path):
    cmd_git = tmp_path / "Git" / "cmd" / "git.exe"
    cmd_git.parent.mkdir(parents=True)
    cmd_git.write_bytes(b"x" * 40_000)

    monkeypatch.setattr(ncg, "_is_windows", lambda: True)
    monkeypatch.setattr(ncg.shutil, "which", lambda name: str(cmd_git) if name in {"git", "git.exe"} else None)
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LocalAppData", raising=False)
    ncg.clear_git_executable_cache()

    try:
        assert Path(git_process.resolve_git_executable()) == cmd_git
    finally:
        ncg.clear_git_executable_cache()


def test_no_console_subprocess_kwargs_hides_windows_process(monkeypatch):
    class DummyStartupInfo:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = -1

    monkeypatch.setattr(ncg, "_is_windows", lambda: True)
    monkeypatch.setattr(ncg.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(ncg.subprocess, "STARTUPINFO", DummyStartupInfo, raising=False)
    monkeypatch.setattr(ncg.subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(ncg.subprocess, "SW_HIDE", 0, raising=False)

    kwargs = git_process.no_console_subprocess_kwargs()

    assert kwargs["creationflags"] & 0x08000000
    assert kwargs["startupinfo"].dwFlags & 0x00000001
    assert kwargs["startupinfo"].wShowWindow == 0


def test_run_git_uses_resolved_executable_and_no_console(monkeypatch, tmp_path):
    calls = []
    resolved_git = str(tmp_path / "Git" / "mingw64" / "bin" / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(ncg, "_is_windows", lambda: True)
    monkeypatch.setattr(ncg.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(git_process.subprocess, "run", fake_run)

    git_process.run_git(["status", "--porcelain=1"], cwd=tmp_path, capture_output=True, text=True)

    assert calls[0][0] == [resolved_git, "status", "--porcelain=1"]
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert calls[0][1]["timeout"] == git_process.DEFAULT_GIT_TIMEOUT_SECONDS
    assert calls[0][1]["check"] is False
    assert calls[0][1]["creationflags"] & 0x08000000


def test_run_git_check_true_raises_called_process_error(monkeypatch, tmp_path):
    resolved_git = str(tmp_path / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", dict)

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=128, stdout="out", stderr="fatal")

    monkeypatch.setattr(git_process.subprocess, "run", fake_run)

    try:
        git_process.run_git(["status"], cwd=tmp_path, check=True)
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 128
        assert exc.cmd == [resolved_git, "status"]
        assert exc.output == "out"
        assert exc.stderr == "fatal"
    else:
        raise AssertionError("run_git(check=True) should raise on non-zero returncode")


def test_run_git_retries_index_lock_contention(monkeypatch, tmp_path):
    calls = []
    resolved_git = str(tmp_path / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", dict)
    monkeypatch.setattr(git_process.time, "sleep", lambda _seconds: None)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(args=args, returncode=128, stdout=b"", stderr=b"fatal: Unable to create '.git/index.lock'")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(git_process.subprocess, "run", fake_run)

    result = git_process.run_git(["status"], cwd=tmp_path, capture_output=True, retries=2)

    assert result.returncode == 0
    assert len(calls) == 2


def test_run_git_does_not_retry_non_lock_failure(monkeypatch, tmp_path):
    calls = []
    resolved_git = str(tmp_path / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", dict)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="fatal: not a git repository")

    monkeypatch.setattr(git_process.subprocess, "run", fake_run)

    result = git_process.run_git(["status"], cwd=tmp_path, retries=2)

    assert result.returncode == 1
    assert len(calls) == 1


def test_run_git_passes_custom_timeout_and_propagates_timeout(monkeypatch, tmp_path):
    calls = []
    resolved_git = str(tmp_path / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", dict)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(git_process.subprocess, "run", fake_run)

    try:
        git_process.run_git(["fetch"], cwd=tmp_path, timeout=1.5)
    except subprocess.TimeoutExpired as exc:
        assert exc.timeout == 1.5
    else:
        raise AssertionError("run_git should propagate subprocess.TimeoutExpired")

    assert calls[0][1]["timeout"] == 1.5
    assert len(calls) == 1


def test_safe_git_args_for_log_redacts_commit_message_and_credential_url() -> None:
    assert git_process.safe_git_args_for_log(
        ["commit", "-m", "secret message", "https://user:token@github.com/org/repo.git"]
    ) == ["commit", "-m", "[redacted]", "[redacted-url]"]


def test_run_git_records_failed_command_without_secrets(monkeypatch, tmp_path):
    events = []
    resolved_git = str(tmp_path / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", dict)
    monkeypatch.setattr(git_process, "_record_git_process_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(
        git_process.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="fatal: Authentication failed for 'https://user:token@example.com/repo.git'",
        ),
    )

    result = git_process.run_git(
        ["push", "https://user:token@example.com/repo.git"],
        cwd=tmp_path,
        retries=0,
    )

    assert result.returncode == 1
    assert events
    _args, kwargs = events[0]
    assert _args[1] == "git_process.command.failed"
    assert kwargs["fields"]["args"] == ["push", "[redacted-url]"]
    assert "token" not in kwargs["fields"]["stderr"]
    assert kwargs["fields"]["returnCode"] == 1


def test_run_git_records_lock_retry_then_success(monkeypatch, tmp_path):
    events = []
    calls = []
    resolved_git = str(tmp_path / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", dict)
    monkeypatch.setattr(git_process.time, "sleep", lambda _seconds: None)

    def capture(phase, event_code, **kwargs):
        events.append({"phase": phase, "event": event_code, **kwargs})

    monkeypatch.setattr(git_process, "_record_git_process_scene_event", capture)

    def fake_run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return subprocess.CompletedProcess(args=args, returncode=128, stdout="", stderr="fatal: Unable to create '.git/index.lock'")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(git_process.subprocess, "run", fake_run)

    result = git_process.run_git(["status"], cwd=tmp_path, retries=2)

    assert result.returncode == 0
    assert [event["event"] for event in events] == ["git_process.lock_retry"]


def test_run_git_records_timeout_before_raising(monkeypatch, tmp_path):
    events = []
    resolved_git = str(tmp_path / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", dict)
    monkeypatch.setattr(git_process, "_record_git_process_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(git_process.subprocess, "run", fake_run)

    try:
        git_process.run_git(["fetch"], cwd=tmp_path, timeout=1.5, retries=0)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("run_git should propagate subprocess.TimeoutExpired")

    assert events[0][0][1] == "git_process.command.timeout"


def test_run_git_does_not_record_merge_base_is_ancestor_false(monkeypatch, tmp_path):
    events = []
    resolved_git = str(tmp_path / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", dict)
    monkeypatch.setattr(
        git_process,
        "_record_git_process_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    monkeypatch.setattr(
        git_process.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=""),
    )

    result = git_process.run_git(
        ["merge-base", "--is-ancestor", "abc123", "main"],
        cwd=tmp_path,
        retries=0,
    )

    assert result.returncode == 1
    assert events == []


def test_run_git_still_records_unexpected_merge_base_failure(monkeypatch, tmp_path):
    events = []
    resolved_git = str(tmp_path / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", dict)
    monkeypatch.setattr(
        git_process,
        "_record_git_process_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    monkeypatch.setattr(
        git_process.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=128,
            stdout="",
            stderr="fatal: Not a valid object name abc123",
        ),
    )

    result = git_process.run_git(
        ["merge-base", "--is-ancestor", "abc123", "main"],
        cwd=tmp_path,
        retries=0,
    )

    assert result.returncode == 128
    assert events
    assert events[0][0][1] == "git_process.command.failed"
