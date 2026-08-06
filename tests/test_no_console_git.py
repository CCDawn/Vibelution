"""no_console_git must prefer real git.exe and hide waitable spawns."""

from __future__ import annotations

from pathlib import Path

from core.infrastructure import no_console_git as ncg


def test_resolve_git_executable_prefers_large_binary(tmp_path: Path, monkeypatch) -> None:
    trampoline = tmp_path / "cmd" / "git.exe"
    real = tmp_path / "mingw64" / "bin" / "git.exe"
    trampoline.parent.mkdir(parents=True)
    real.parent.mkdir(parents=True)
    trampoline.write_bytes(b"x" * 40_000)
    real.write_bytes(b"y" * 500_000)

    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LocalAppData", raising=False)
    monkeypatch.setattr(ncg, "_is_windows", lambda: True)
    monkeypatch.setattr(ncg.shutil, "which", lambda _name: str(trampoline))
    ncg.clear_git_executable_cache()

    try:
        resolved = Path(ncg.resolve_git_executable())
        assert resolved == real.resolve()
    finally:
        ncg.clear_git_executable_cache()


def test_resolve_git_executable_rewrites_cmd_trampoline(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "Git"
    trampoline = install / "cmd" / "git.exe"
    real = install / "mingw64" / "bin" / "git.exe"
    trampoline.parent.mkdir(parents=True)
    real.parent.mkdir(parents=True)
    trampoline.write_bytes(b"x" * 40_000)
    real.write_bytes(b"y" * 500_000)

    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LocalAppData", raising=False)
    monkeypatch.setattr(ncg, "_is_windows", lambda: True)
    monkeypatch.setattr(ncg.shutil, "which", lambda _name: str(trampoline))
    ncg.clear_git_executable_cache()

    try:
        resolved = Path(ncg.resolve_git_executable())
        assert resolved == real.resolve()
    finally:
        ncg.clear_git_executable_cache()


def test_run_git_uses_create_no_window_on_windows(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(*_args, **kwargs):
        captured.update(kwargs)
        return type("R", (), {"returncode": 0, "stdout": "main\n", "stderr": ""})()

    monkeypatch.setattr(ncg, "_is_windows", lambda: True)
    monkeypatch.setattr(ncg.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(ncg.subprocess, "run", fake_run)
    monkeypatch.setattr(ncg, "resolve_git_executable", lambda: r"C:\Git\mingw64\bin\git.exe")

    ncg.run_git(["branch", "--show-current"], cwd=".")
    assert captured["creationflags"] == 0x08000000
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["env"]["GCM_INTERACTIVE"] == "never"
