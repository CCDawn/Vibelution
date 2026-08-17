from __future__ import annotations

import json
import types
from pathlib import Path

import core.launcher.desktop_shell as desktop_shell


def _write_packaged_shell(root: Path, *, tree_hash: str, asar_mtime: float | None = None) -> None:
    exe = desktop_shell.packaged_desktop_exe(root)
    asar = desktop_shell.packaged_asar_path(root)
    provenance = desktop_shell.packaged_provenance_path(root)
    provenance.parent.mkdir(parents=True)
    exe.write_bytes(b"mz")
    asar.write_bytes(b"asar")
    provenance.write_text(
        json.dumps({"electronTreeHash": tree_hash, "schemaVersion": 1}),
        encoding="utf-8",
    )
    src = root / "desktop" / "electron" / "src"
    src.mkdir(parents=True)
    source_file = src / "main.ts"
    source_file.write_text("export {}\n", encoding="utf-8")
    if asar_mtime is not None:
        import os

        os.utime(asar, (asar_mtime, asar_mtime))
        os.utime(source_file, (asar_mtime - 10, asar_mtime - 10))


def test_inspect_desktop_shell_missing_package_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: "a" * 40)
    status = desktop_shell.inspect_desktop_shell(tmp_path)
    assert status["stale"] is True
    assert status["reason"] == "missing_package"


def test_inspect_desktop_shell_provenance_mismatch_is_stale(tmp_path, monkeypatch):
    _write_packaged_shell(tmp_path, tree_hash="b" * 40)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: "a" * 40)
    status = desktop_shell.inspect_desktop_shell(tmp_path)
    assert status["stale"] is True
    assert status["reason"] == "provenance_mismatch"


def test_inspect_desktop_shell_current_when_hashes_match(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    status = desktop_shell.inspect_desktop_shell(tmp_path)
    assert status["stale"] is False
    assert status["reason"] == "current"


def test_inspect_desktop_shell_source_newer_than_asar(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=1_000_000)
    newer = tmp_path / "desktop" / "electron" / "src" / "main.ts"
    newer.write_text("export const next = 1;\n", encoding="utf-8")
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    status = desktop_shell.inspect_desktop_shell(tmp_path)
    assert status["stale"] is True
    assert status["reason"] == "source_newer_than_asar"


def test_schedule_desktop_shell_refresh_spawns_pythonw_helper(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.pid = 321

    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    pythonw = tmp_path / "pythonw.exe"
    pythonw.write_text("", encoding="utf-8")
    monkeypatch.setattr(desktop_shell.subprocess, "Popen", FakePopen)
    result = desktop_shell.schedule_desktop_shell_refresh(
        wait_pid=44,
        then_lifecycle="start",
        project_root=tmp_path,
        python_executable=str(python),
    )
    args = captured["args"]
    assert args[0] == str(pythonw)
    assert "--action" in args
    assert args[args.index("--action") + 1] == "refresh-desktop-shell"
    assert args[args.index("--wait-pid") + 1] == "44"
    assert args[args.index("--then-lifecycle") + 1] == "start"
    assert captured["kwargs"]["stdin"] is desktop_shell.subprocess.DEVNULL
    flags = int(captured["kwargs"].get("creationflags") or 0)
    assert flags & int(getattr(desktop_shell.subprocess, "CREATE_NO_WINDOW", 0x08000000))
    assert result["helperPid"] == 321
    assert result["scheduled"] is True


def test_schedule_desktop_shell_refresh_skips_during_recent_failure(tmp_path, monkeypatch):
    desktop_shell.record_desktop_shell_refresh_failure(
        tmp_path,
        reason="rebuild_failed",
        detail="EBUSY",
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("refresh helper should not spawn during cooldown")

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", fail_if_called)
    result = desktop_shell.schedule_desktop_shell_refresh(wait_pid=44, project_root=tmp_path)
    assert result["scheduled"] is False
    assert result["reason"] == "refresh_cooldown"


def test_schedule_desktop_shell_refresh_force_bypasses_recent_failure(tmp_path, monkeypatch):
    desktop_shell.record_desktop_shell_refresh_failure(
        tmp_path,
        reason="rebuild_failed",
        detail="EBUSY",
    )

    class FakePopen:
        def __init__(self, args, **kwargs):
            self.pid = 654

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", FakePopen)
    result = desktop_shell.schedule_desktop_shell_refresh(wait_pid=44, project_root=tmp_path, force=True)
    assert result["scheduled"] is True
    assert result["helperPid"] == 654
    assert desktop_shell.recent_desktop_shell_refresh_failure(tmp_path) is None


def test_recent_desktop_shell_refresh_failure_blocks_inspect(tmp_path):
    desktop_shell.record_desktop_shell_refresh_failure(
        tmp_path,
        reason="rebuild_failed",
        detail="EBUSY",
    )
    status = desktop_shell.inspect_desktop_shell(tmp_path)
    assert status["refreshBlocked"] is True
    assert status["refreshBlockedReason"] == "rebuild_failed"


def test_launch_packaged_desktop_shell_does_not_hide_gui(tmp_path, monkeypatch):
    exe = desktop_shell.packaged_desktop_exe(tmp_path)
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"mz")
    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.pid = 77

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", FakePopen)
    result = desktop_shell.launch_packaged_desktop_shell(project_root=tmp_path, then_lifecycle="start")
    args = captured["args"]
    assert args[0] == str(exe)
    assert "--workspace" in args
    assert args[-1] == "start"
    assert "startupinfo" not in captured["kwargs"]
    assert result["pid"] == 77


def test_rebuild_desktop_shell_uses_node_npm_cli(tmp_path, monkeypatch):
    ran: dict[str, object] = {}

    def fake_run(command, **kwargs):
        ran["command"] = command
        ran["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(desktop_shell, "_node_command", lambda: r"C:\nodejs\node.exe")
    monkeypatch.setattr(
        desktop_shell,
        "_npm_cli_script_for_node",
        lambda command: r"C:\nodejs\node_modules\npm\bin\npm-cli.js",
    )
    monkeypatch.setattr(
        desktop_shell,
        "inspect_desktop_shell",
        lambda root: {"stale": False, "reason": "current", "currentElectronTree": "abc"},
    )
    monkeypatch.setattr(desktop_shell.subprocess, "run", fake_run)
    result = desktop_shell.rebuild_desktop_shell(project_root=tmp_path)
    command = ran["command"]
    assert command[0] == r"C:\nodejs\node.exe"
    assert command[1].endswith("npm-cli.js")
    assert command[-2:] == ["run", "package:dir"]
    assert "npm.cmd" not in " ".join(command)
    assert result["rebuilt"] is True


def test_pid_alive_uses_psutil_not_os_kill(monkeypatch):
    killed: list[object] = []

    def fake_kill(*args, **kwargs):
        killed.append(args)
        raise AssertionError("os.kill must not be used to probe PIDs on Windows")

    monkeypatch.setattr(desktop_shell.os, "kill", fake_kill)
    monkeypatch.setattr(desktop_shell.os, "name", "nt")

    class FakePsutil:
        @staticmethod
        def pid_exists(pid: int) -> bool:
            return pid == 42

    monkeypatch.setitem(__import__("sys").modules, "psutil", FakePsutil)
    assert desktop_shell._pid_alive(42) is True
    assert desktop_shell._pid_alive(9) is False
    assert killed == []


def _write_unpackaged_electron(root: Path, *, tree_hash: str, main_mtime: float | None = None) -> Path:
    electron_exe = root / desktop_shell.UNPACKAGED_ELECTRON_EXE_RELATIVE
    electron_exe.parent.mkdir(parents=True)
    electron_exe.write_bytes(b"mz")
    main_js = desktop_shell.unpackaged_main_js(root)
    main_js.parent.mkdir(parents=True, exist_ok=True)
    main_js.write_text("export {}\n", encoding="utf-8")
    desktop_shell._write_unpackaged_provenance(root, tree_hash)
    src = root / "desktop" / "electron" / "src"
    src.mkdir(parents=True, exist_ok=True)
    source_file = src / "main.ts"
    source_file.write_text("export {}\n", encoding="utf-8")
    if main_mtime is not None:
        import os

        os.utime(main_js, (main_mtime, main_mtime))
        os.utime(source_file, (main_mtime - 10, main_mtime - 10))
    return electron_exe


def test_inspect_unpackaged_electron_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: "a" * 40)
    status = desktop_shell.inspect_unpackaged_electron(tmp_path)
    assert status["stale"] is True
    assert status["reason"] == "missing_binary"


def test_resolve_desktop_shell_launch_prefers_current_packaged(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    spec = desktop_shell.resolve_desktop_shell_launch(tmp_path, then_lifecycle="start", open_workbench=True)
    assert spec["kind"] == "packaged"
    assert spec["args"][0] == str(desktop_shell.packaged_desktop_exe(tmp_path))
    assert "--open-workbench" in spec["args"]
    assert spec["args"][-1] == "start"


def test_resolve_desktop_shell_launch_uses_unpackaged_when_packaged_missing(tmp_path, monkeypatch):
    tree = "a" * 40
    electron_exe = _write_unpackaged_electron(tmp_path, tree_hash=tree, main_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    spec = desktop_shell.resolve_desktop_shell_launch(tmp_path, open_workbench=True)
    assert spec["kind"] == "unpackaged"
    assert spec["args"][:2] == [str(electron_exe), str(desktop_shell.unpackaged_main_js(tmp_path))]
    assert "--workspace" in spec["args"]
    assert "--open-workbench" in spec["args"]


def test_ensure_unpackaged_electron_rebuilds_stale_bundle(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_unpackaged_electron(tmp_path, tree_hash="b" * 40, main_mtime=2_000_000_000)
    ran: dict[str, object] = {}

    def fake_run(command, **kwargs):
        ran["command"] = command
        ran["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    monkeypatch.setattr(desktop_shell, "_node_command", lambda: r"C:\nodejs\node.exe")
    monkeypatch.setattr(
        desktop_shell,
        "_npm_cli_script_for_node",
        lambda command: r"C:\nodejs\node_modules\npm\bin\npm-cli.js",
    )
    monkeypatch.setattr(desktop_shell.subprocess, "run", fake_run)
    result = desktop_shell.ensure_unpackaged_electron(tmp_path)
    command = ran["command"]
    assert command[-2:] == ["run", "build"]
    assert "package:dir" not in command
    assert result["rebuilt"] is True
    assert result["reason"] == "current"


def test_launch_desktop_shell_does_not_hide_unpackaged_gui(tmp_path, monkeypatch):
    tree = "a" * 40
    electron_exe = _write_unpackaged_electron(tmp_path, tree_hash=tree, main_mtime=2_000_000_000)
    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.pid = 88

    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    monkeypatch.setattr(desktop_shell.subprocess, "Popen", FakePopen)
    result = desktop_shell.launch_desktop_shell(project_root=tmp_path, open_workbench=True)
    assert result["kind"] == "unpackaged"
    assert captured["args"][0] == str(electron_exe)
    assert "--open-workbench" in captured["args"]
    assert "startupinfo" not in captured["kwargs"]
    flags = int(captured["kwargs"].get("creationflags") or 0)
    assert flags & int(getattr(desktop_shell.subprocess, "CREATE_NO_WINDOW", 0x08000000)) == 0
    assert result["pid"] == 88
