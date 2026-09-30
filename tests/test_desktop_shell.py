from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.infrastructure.branch_workspace import (
    BranchWorkspaceError,
    BranchWorkspaceLayout,
)
from core.launcher import desktop_shell
from scripts.windowless_subprocess import no_window_subprocess_kwargs


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


def test_refresh_lock_reclaims_dead_holder_without_unlink_race(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"pid": 99123, "startedAt": "2026-08-22T00:00:00Z"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: False)

    assert desktop_shell._acquire_desktop_shell_refresh_lock(tmp_path) is True
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["pid"] == desktop_shell.os.getpid()
    assert not list(lock_path.parent.glob(f"{lock_path.name}.stale-*"))


def test_refresh_lock_keeps_live_holder_and_foreign_release_is_ignored(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"pid": 99124, "startedAt": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: True)
    # The holder process predates the lock, so it is the real holder, not a
    # recycled PID.
    monkeypatch.setattr(desktop_shell, "_process_create_time", lambda pid: 0.0)

    assert desktop_shell._acquire_desktop_shell_refresh_lock(tmp_path) is False
    desktop_shell._release_desktop_shell_refresh_lock(tmp_path)
    assert lock_path.is_file()


def test_refresh_lock_stale_when_holder_pid_is_dead(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"pid": 99127, "startedAt": "2026-09-30T07:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: False)

    assert desktop_shell._refresh_lock_is_stale(lock_path) is True


def test_refresh_lock_live_holder_predating_lock_is_not_stale(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"pid": 99128, "startedAt": "2026-09-30T07:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: True)
    started_epoch = datetime(2026, 9, 30, 7, 0, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(desktop_shell, "_process_create_time", lambda pid: started_epoch - 100.0)

    assert desktop_shell._refresh_lock_is_stale(lock_path) is False


def test_refresh_lock_keeps_holder_created_within_reuse_tolerance(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"pid": 99129, "startedAt": "2026-09-30T07:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: True)
    started_epoch = datetime(2026, 9, 30, 7, 0, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(desktop_shell, "_process_create_time", lambda pid: started_epoch + 2.0)

    assert desktop_shell._refresh_lock_is_stale(lock_path) is False


def test_refresh_lock_stale_when_create_time_exceeds_reuse_tolerance(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"pid": 99130, "startedAt": "2026-09-30T07:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: True)
    started_epoch = datetime(2026, 9, 30, 7, 0, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(desktop_shell, "_process_create_time", lambda pid: started_epoch + 10.0)

    assert desktop_shell._refresh_lock_is_stale(lock_path) is True


def test_refresh_lock_conservative_when_holder_create_time_unknown(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"pid": 99131, "startedAt": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(desktop_shell, "_process_create_time", lambda pid: None)

    assert desktop_shell._refresh_lock_is_stale(lock_path) is False


def test_refresh_lock_conservative_when_live_holder_has_no_started_at(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(json.dumps({"pid": 99132}), encoding="utf-8")
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(desktop_shell, "_process_create_time", lambda pid: None)

    assert desktop_shell._refresh_lock_is_stale(lock_path) is False


def test_refresh_lock_reclaims_recycled_pid_created_after_lock(tmp_path, monkeypatch):
    """A live PID created after the lock was taken is a recycled PID.

    Regression for the 2026-09-30 leak: a hard-killed scheduler left the lock
    behind, Windows handed its PID to an unrelated conhost.exe, and the
    refresh lock then blocked restarts forever.
    """

    pytest.importorskip("psutil")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        **no_window_subprocess_kwargs(),
    )
    try:
        import psutil

        child_create_time = psutil.Process(child.pid).create_time()
        lock_path = desktop_shell._refresh_lock_path(tmp_path)
        lock_path.parent.mkdir(parents=True)
        stale_started_at = (
            datetime.fromtimestamp(child_create_time, tz=timezone.utc) - timedelta(seconds=60)
        ).isoformat()
        lock_path.write_text(
            json.dumps({"pid": child.pid, "startedAt": stale_started_at}),
            encoding="utf-8",
        )
        monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: True)

        assert desktop_shell._refresh_lock_is_stale(lock_path) is True
        assert desktop_shell._acquire_desktop_shell_refresh_lock(tmp_path) is True
    finally:
        child.kill()
        child.wait(timeout=10)


def test_process_create_time_uses_psutil(monkeypatch):
    class FakeProcess:
        def create_time(self) -> float:
            return 1234.5

    class FakePsutil:
        @staticmethod
        def Process(pid: int) -> FakeProcess:
            assert pid == 42
            return FakeProcess()

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)
    assert desktop_shell._process_create_time(42) == 1234.5
    assert desktop_shell._process_create_time(0) is None


def test_process_create_time_returns_none_without_psutil(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert desktop_shell._process_create_time(42) is None


def test_refresh_lock_does_not_quarantine_fresh_lock_after_stale_observation(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"pid": 99125, "startedAt": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    calls = 0

    def stale_check_with_racing_fresh_lock(path):
        nonlocal calls
        calls += 1
        path.write_text(
            json.dumps({"pid": 99126, "startedAt": "2026-08-22T00:00:00Z"}),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(desktop_shell, "_refresh_lock_is_stale", stale_check_with_racing_fresh_lock)

    assert desktop_shell._quarantine_stale_refresh_lock(lock_path) is False
    assert calls == 1
    assert json.loads(lock_path.read_text(encoding="utf-8"))["pid"] == 99126


@pytest.mark.skipif(
    os.name != "nt",
    reason="no_window_subprocess_kwargs intentionally drops creationflags on "
    "POSIX, where the console-free spawn policy does not apply",
)
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
    assert "--local-debugging" in args
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
    assert "--local-debugging" in spec["args"]
    assert spec["args"][0] == str(desktop_shell.packaged_desktop_exe(tmp_path))
    assert spec["cwd"] == str(tmp_path)
    assert spec["args"][spec["args"].index("--workspace") + 1] == str(tmp_path)
    assert "--project" not in spec["args"]
    assert "--open-workbench" in spec["args"]
    assert spec["args"][-1] == "start"


def test_resolve_desktop_shell_launch_uses_unpackaged_when_packaged_missing(tmp_path, monkeypatch):
    tree = "a" * 40
    electron_exe = _write_unpackaged_electron(tmp_path, tree_hash=tree, main_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    spec = desktop_shell.resolve_desktop_shell_launch(tmp_path, open_workbench=True)
    assert spec["kind"] == "unpackaged"
    assert "--local-debugging" in spec["args"]
    assert spec["args"][:2] == [str(electron_exe), str(desktop_shell.unpackaged_main_js(tmp_path))]
    assert spec["cwd"] == str(tmp_path)
    assert spec["args"][spec["args"].index("--workspace") + 1] == str(tmp_path)
    assert "--project" not in spec["args"]
    assert "--open-workbench" in spec["args"]


def test_live_shell_owns_rebuild_decision_before_relaunch(tmp_path, monkeypatch):
    from core.launcher import desktop_shell_owner
    exe = _write_unpackaged_electron(tmp_path, tree_hash="a" * 40, main_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell_owner, "read_desktop_shell_owner", lambda root: {"owner": "electron", "pid": 123, "executable": str(exe)})
    monkeypatch.setattr(desktop_shell_owner, "_identity_status", lambda owner: "match")
    monkeypatch.setattr(desktop_shell, "ensure_unpackaged_electron", lambda root: (_ for _ in ()).throw(AssertionError("Entry must not consume the live shell rebuild signal")))
    spec = desktop_shell.resolve_desktop_shell_launch(tmp_path, then_lifecycle="restart")
    assert spec["reason"] == "forward_to_live_shell"
    assert spec["args"][-1] == "restart"
    assert "--local-debugging" in spec["args"]


def test_branch_launch_does_not_consume_live_shell_rebuild_signal(tmp_path, monkeypatch):
    from core.launcher import desktop_shell_owner

    branch = tmp_path / ".worktrees" / "task"
    exe = _write_unpackaged_electron(tmp_path, tree_hash="a" * 40, main_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "resolve_desktop_shell_launch_roots", lambda root: (tmp_path, branch))
    monkeypatch.setattr(desktop_shell_owner, "read_desktop_shell_owner", lambda root: {
        "owner": "electron", "pid": 123, "executable": str(exe),
    })
    monkeypatch.setattr(desktop_shell_owner, "_identity_status", lambda owner: "match")

    def unexpected_build(root):
        raise AssertionError("Branch entry must not replace the live shared shell bundle")

    monkeypatch.setattr(desktop_shell, "ensure_unpackaged_electron", unexpected_build)
    spec = desktop_shell.resolve_desktop_shell_launch(branch, then_lifecycle="start")
    assert spec["reason"] == "forward_to_live_shell"
    assert spec["args"][spec["args"].index("--project") + 1] == str(branch)
    assert spec["args"][-1] == "start"


def test_ensure_unpackaged_electron_rebuilds_stale_bundle(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_unpackaged_electron(tmp_path, tree_hash="b" * 40, main_mtime=2_000_000_000)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        stage = Path(kwargs.get("env", {}).get("VIBELUTION_ELECTRON_DIST", ""))
        if "--outDir" in command:
            out = Path(command[command.index("--outDir") + 1])
            out.mkdir(parents=True, exist_ok=True)
            main_js = out / "main.js"
            main_js.write_text("new-main\n", encoding="utf-8")
            os.utime(main_js, (2_000_000_100, 2_000_000_100))
        outfile_arg = next((part for part in command if part.startswith("--outfile")), None)
        if outfile_arg is not None:
            if "=" in outfile_arg:
                outfile = Path(outfile_arg.split("=", 1)[1])
            else:
                outfile = Path(command[command.index(outfile_arg) + 1])
            outfile.parent.mkdir(parents=True, exist_ok=True)
            outfile.write_text("preload\n", encoding="utf-8")
        if str(command[-1]).endswith("buildWorkbenchJob.js"):
            native = stage / "native"
            native.mkdir(parents=True, exist_ok=True)
            (native / "workbench_job.node").write_bytes(b"node")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    monkeypatch.setattr(desktop_shell, "_node_command", lambda: r"C:\nodejs\node.exe")
    monkeypatch.setattr(desktop_shell.subprocess, "run", fake_run)
    result = desktop_shell.ensure_unpackaged_electron(tmp_path)
    assert all("package:dir" not in " ".join(command) for command in calls)
    assert any("--outDir" in command for command in calls)
    # esbuild CLI rejects space-separated values for value flags (e.g. "--outfile x"),
    # so the launcher must pass them joined, matching the npm build:preload script.
    esbuild_call = next(command for command in calls if any(part.startswith("--outfile") for part in command))
    assert any(part.startswith("--outfile=") for part in esbuild_call)
    assert "--platform=node" in esbuild_call and "--format=cjs" in esbuild_call
    assert not (tmp_path / "desktop" / "electron" / ".build-stage").exists()
    assert desktop_shell.unpackaged_main_js(tmp_path).read_text(encoding="utf-8") == "new-main\n"
    assert result["rebuilt"] is True
    assert result["reason"] == "current"


def test_publish_staged_electron_dist_keeps_live_dist_when_rename_is_busy(tmp_path, monkeypatch):
    electron = tmp_path / "desktop" / "electron"
    dist = electron / "dist"
    dist.mkdir(parents=True)
    (dist / "main.js").write_text("old\n", encoding="utf-8")
    stage = electron / ".build-stage"
    stage.mkdir()
    (stage / "main.js").write_text("new\n", encoding="utf-8")

    def locked(src, dest):
        if Path(src) == dist:
            error = PermissionError(13, "in use", str(src))
            error.winerror = 32
            raise error
        os.rename(src, dest)

    monkeypatch.setattr(desktop_shell, "_rename_dir", locked)
    with pytest.raises(desktop_shell.UnpackagedElectronPublishBusy):
        desktop_shell._publish_staged_electron_dist(stage, dist)
    assert (dist / "main.js").read_text(encoding="utf-8") == "old\n"
    assert not (electron / ".dist-incoming").exists()


def test_ensure_latest_launcher_rebuilds_electron_and_frontend(tmp_path, monkeypatch):
    monkeypatch.setattr(
        desktop_shell,
        "ensure_unpackaged_electron",
        lambda root: {"ensured": True, "rebuilt": False, "reason": "current"},
    )
    monkeypatch.setattr(
        "core.runtime_manager.daemon._preflight_frontend_build_for_restart",
        lambda command_id, *, project_root: {"ok": True, "skipped": True, "reason": "frontend build is current"},
    )
    result = desktop_shell.ensure_latest_launcher(tmp_path)
    assert result["ok"] is True
    assert result["electron"]["rebuilt"] is False
    assert result["frontend"]["skipped"] is True


def test_ensure_latest_launcher_raises_when_frontend_preflight_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        desktop_shell,
        "ensure_unpackaged_electron",
        lambda root: {"ensured": True, "rebuilt": True, "reason": "current"},
    )
    monkeypatch.setattr(
        "core.runtime_manager.daemon._preflight_frontend_build_for_restart",
        lambda command_id, *, project_root: {"ok": False, "skipped": False, "reason": "tsc failed"},
    )
    try:
        desktop_shell.ensure_latest_launcher(tmp_path)
    except RuntimeError as exc:
        assert "tsc failed" in str(exc)
    else:
        raise AssertionError("expected frontend preflight failure to raise")


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

    def missing_git(_requested):
        raise BranchWorkspaceError("not a git checkout")

    monkeypatch.setattr(
        "core.infrastructure.branch_workspace.resolve_branch_workspace",
        missing_git,
    )
    result = desktop_shell.launch_desktop_shell(project_root=tmp_path, open_workbench=True)
    assert result["kind"] == "unpackaged"
    assert captured["args"][0] == str(electron_exe)
    assert "--open-workbench" in captured["args"]
    assert "startupinfo" not in captured["kwargs"]
    flags = int(captured["kwargs"].get("creationflags") or 0)
    assert flags & int(getattr(desktop_shell.subprocess, "CREATE_NO_WINDOW", 0x08000000)) == 0
    assert result["pid"] == 88


def _task_workspace_layout(*, checkout: Path, integration: Path, worktree: Path) -> BranchWorkspaceLayout:
    return BranchWorkspaceLayout(
        checkout=checkout,
        worktree_root=worktree,
        integration_root=integration,
        git_common_dir=integration / ".git",
        branch_pool=integration / ".worktrees",
        retired_pool=integration / ".worktrees" / "_retired",
        legacy_siblings=(),
        role="task",
        slug="task",
    )


def test_desktop_shell_electron_args_default_keeps_hidden_presentation_off(tmp_path):
    base = dict(shell_root=tmp_path, slot_root=None, open_workbench=True, lifecycle="start")
    default_args = desktop_shell._desktop_shell_electron_args("electron", ["main.js"], **base)
    explicit_off = desktop_shell._desktop_shell_electron_args(
        "electron", ["main.js"], hidden_presentation=False, **base
    )
    hidden_args = desktop_shell._desktop_shell_electron_args(
        "electron", ["main.js"], hidden_presentation=True, **base
    )
    assert default_args == explicit_off
    assert "--hidden-presentation" not in default_args
    assert hidden_args == default_args + ["--hidden-presentation"]


def test_resolve_desktop_shell_launch_default_omits_hidden_presentation(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    spec = desktop_shell.resolve_desktop_shell_launch(tmp_path, then_lifecycle="start", open_workbench=True)
    assert spec["kind"] == "packaged"
    assert "--hidden-presentation" not in spec["args"]


def test_resolve_desktop_shell_launch_forwards_hidden_presentation(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    packaged = desktop_shell.resolve_desktop_shell_launch(
        tmp_path, then_lifecycle="start", open_workbench=True, hidden_presentation=True
    )
    assert packaged["kind"] == "packaged"
    assert packaged["args"][-2:] == ["start", "--hidden-presentation"]

    from core.launcher import desktop_shell_owner
    exe = _write_unpackaged_electron(tmp_path, tree_hash=tree, main_mtime=2_000_000_000)
    monkeypatch.setattr(
        desktop_shell_owner,
        "read_desktop_shell_owner",
        lambda root: {"owner": "electron", "pid": 123, "executable": str(exe)},
    )
    monkeypatch.setattr(desktop_shell_owner, "_identity_status", lambda owner: "match")
    live = desktop_shell.resolve_desktop_shell_launch(tmp_path, then_lifecycle="restart", hidden_presentation=True)
    assert live["reason"] == "forward_to_live_shell"
    assert "--hidden-presentation" in live["args"]


def test_launch_desktop_shell_forwards_hidden_presentation_to_electron_argv(tmp_path, monkeypatch):
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
    monkeypatch.setattr(
        "core.infrastructure.branch_workspace.resolve_branch_workspace",
        lambda _requested: (_ for _ in ()).throw(BranchWorkspaceError("not a git checkout")),
    )
    result = desktop_shell.launch_desktop_shell(
        project_root=tmp_path, open_workbench=True, hidden_presentation=True
    )
    assert result["kind"] == "unpackaged"
    assert captured["args"][0] == str(electron_exe)
    assert "--hidden-presentation" in captured["args"]
    assert "--open-workbench" in captured["args"]


def test_resolve_desktop_shell_launch_roots_falls_back_without_git(tmp_path):
    shell_root, slot_root = desktop_shell.resolve_desktop_shell_launch_roots(tmp_path)
    assert shell_root == tmp_path
    assert slot_root is None


def test_resolve_desktop_shell_launch_forwards_worktree_as_project_slot(tmp_path, monkeypatch):
    integration = tmp_path / "repo"
    worktree = integration / ".worktrees" / "task"
    worktree.mkdir(parents=True)
    tree = "a" * 40
    _write_packaged_shell(integration, tree_hash=tree, asar_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    monkeypatch.setattr(
        "core.infrastructure.branch_workspace.resolve_branch_workspace",
        lambda requested: _task_workspace_layout(
            checkout=Path(requested),
            integration=integration,
            worktree=worktree,
        ),
    )

    shell_root, slot_root = desktop_shell.resolve_desktop_shell_launch_roots(worktree)
    assert shell_root == integration
    assert slot_root == worktree

    spec = desktop_shell.resolve_desktop_shell_launch(worktree, then_lifecycle="start", open_workbench=True)
    args = spec["args"]
    assert spec["kind"] == "packaged"
    assert spec["cwd"] == str(integration)
    assert args[0] == str(desktop_shell.packaged_desktop_exe(integration))
    assert args[args.index("--workspace") + 1] == str(integration)
    assert args[args.index("--project") + 1] == str(worktree)
    assert "--open-workbench" in args
    assert args[-1] == "start"
