from pathlib import Path
import subprocess

from core.infrastructure import git_process


def test_resolve_git_executable_prefers_direct_windows_git(monkeypatch, tmp_path):
    install_root = tmp_path / "Git"
    cmd_git = install_root / "cmd" / "git.exe"
    direct_git = install_root / "mingw64" / "bin" / "git.exe"
    cmd_git.parent.mkdir(parents=True)
    direct_git.parent.mkdir(parents=True)
    cmd_git.write_text("", encoding="utf-8")
    direct_git.write_text("", encoding="utf-8")

    monkeypatch.setattr(git_process, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(git_process.shutil, "which", lambda name: str(cmd_git) if name == "git" else None)
    git_process.resolve_git_executable.cache_clear()

    try:
        assert Path(git_process.resolve_git_executable()) == direct_git
    finally:
        git_process.resolve_git_executable.cache_clear()


def test_resolve_git_executable_falls_back_to_discovered_git(monkeypatch, tmp_path):
    cmd_git = tmp_path / "Git" / "cmd" / "git.exe"
    cmd_git.parent.mkdir(parents=True)
    cmd_git.write_text("", encoding="utf-8")

    monkeypatch.setattr(git_process, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(git_process.shutil, "which", lambda name: str(cmd_git) if name == "git" else None)
    git_process.resolve_git_executable.cache_clear()

    try:
        assert Path(git_process.resolve_git_executable()) == cmd_git
    finally:
        git_process.resolve_git_executable.cache_clear()


def test_no_console_subprocess_kwargs_hides_windows_process(monkeypatch):
    class DummyStartupInfo:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = -1

    monkeypatch.setattr(git_process, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(git_process.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(git_process.subprocess, "STARTUPINFO", DummyStartupInfo, raising=False)
    monkeypatch.setattr(git_process.subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(git_process.subprocess, "SW_HIDE", 0, raising=False)

    kwargs = git_process.no_console_subprocess_kwargs()

    assert kwargs["creationflags"] & 0x08000000
    assert kwargs["startupinfo"].dwFlags & 0x00000001
    assert kwargs["startupinfo"].wShowWindow == 0


def test_run_git_uses_resolved_executable_and_no_console(monkeypatch, tmp_path):
    calls = []
    resolved_git = str(tmp_path / "Git" / "mingw64" / "bin" / "git.exe")
    monkeypatch.setattr(git_process, "resolve_git_executable", lambda: resolved_git)
    monkeypatch.setattr(git_process, "_is_windows_platform", lambda: True)
    monkeypatch.setattr(git_process.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

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
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", lambda: {})

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
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", lambda: {})
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
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", lambda: {})

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
    monkeypatch.setattr(git_process, "no_console_subprocess_kwargs", lambda: {})

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
