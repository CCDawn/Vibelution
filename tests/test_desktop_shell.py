from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.infrastructure.branch_workspace import (
    BranchWorkspaceError,
    BranchWorkspaceLayout,
)
from core.launcher import desktop_shell
from scripts.windowless_subprocess import no_window_subprocess_kwargs


def _write_frontend_release(root: Path, *, frontend_tree: str = "d" * 40) -> Path:
    build_key = "e" * 64
    release = root / "web" / ".vibelution-builds" / "release-current"
    (release / "assets").mkdir(parents=True)
    (release / "index.html").write_text("<main>launcher</main>\n", encoding="utf-8")
    (release / "assets" / "launcher.js").write_text("export const launcher = true;\n", encoding="utf-8")
    metadata = {
        "schemaVersion": 2,
        "buildKey": build_key,
        "frontendTree": frontend_tree,
        "sourceCommit": "f" * 40,
    }
    (release / ".vibelution-build.json").write_text(json.dumps(metadata), encoding="utf-8")
    (release.parent / "active.json").write_text(
        json.dumps({"release": release.name, "buildKey": build_key}), encoding="utf-8"
    )
    return release


def _copy_frontend_release(source: Path, target: Path) -> None:
    for path in source.rglob("*"):
        if path.is_file():
            output = target / path.relative_to(source)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)


def _mock_frontend_inspection(monkeypatch, root: Path, *, current: bool = True, release: Path | None = None) -> None:
    active = release or (root / "web" / ".vibelution-builds" / "release-current")
    metadata = json.loads((active / ".vibelution-build.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        desktop_shell,
        "inspect_frontend_build",
        lambda project_root: {
            "current": current,
            "dist": str(active),
            "provenance": metadata,
            "buildInputs": {"frontendTree": metadata["frontendTree"]},
        },
    )


def _write_packaged_shell(root: Path, *, tree_hash: str, asar_mtime: float | None = None) -> None:
    exe = desktop_shell.packaged_desktop_exe(root)
    asar = desktop_shell.packaged_asar_path(root)
    provenance = desktop_shell.packaged_provenance_path(root)
    provenance.parent.mkdir(parents=True)
    exe.write_bytes(b"mz")
    asar.write_bytes(b"asar")
    frontend_release = _write_frontend_release(root)
    packaged_frontend = desktop_shell.packaged_frontend_dist(root)
    _copy_frontend_release(frontend_release, packaged_frontend)
    provenance.write_text(json.dumps({
        "electronTreeHash": tree_hash,
        "frontendTreeHash": "d" * 40,
        "frontendContentSha256": desktop_shell._frontend_directory_content_sha256(packaged_frontend),
        "frontendBuildKey": "e" * 64,
        "frontendSourceCommit": "f" * 40,
        "sourceCommit": "a" * 40,
        "schemaVersion": 1,
    }), encoding="utf-8")
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
    assert status["activeFrontendReleaseUsable"] is False
    assert status["launchBlocking"] is True


def test_frontend_directory_digest_uses_shared_path_and_byte_sha256_format(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_bytes(b"export{};\n")
    (tmp_path / "index.html").write_bytes(b"<main>v</main>\n")

    assert desktop_shell._frontend_directory_content_sha256(tmp_path) == (
        "62e27c13de01ec035463d06ba40958d43b95919fcc7927dedab721b91998100b"
    )


def test_inspect_desktop_shell_provenance_mismatch_is_stale(tmp_path, monkeypatch):
    _write_packaged_shell(tmp_path, tree_hash="b" * 40)
    _mock_frontend_inspection(monkeypatch, tmp_path)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: "a" * 40)
    status = desktop_shell.inspect_desktop_shell(tmp_path)
    assert status["stale"] is True
    assert status["reason"] == "provenance_mismatch"
    assert status["launchBlocking"] is True


def test_inspect_desktop_shell_missing_current_electron_tree_is_not_current(tmp_path, monkeypatch):
    _write_packaged_shell(tmp_path, tree_hash="a" * 40, asar_mtime=2_000_000_000)
    _mock_frontend_inspection(monkeypatch, tmp_path)
    monkeypatch.setattr(
        desktop_shell,
        "_git_tree_hash",
        lambda root, spec: "" if spec == "HEAD:desktop/electron" else "a" * 40,
    )

    status = desktop_shell.inspect_desktop_shell(tmp_path)

    assert status["stale"] is True
    assert status["reason"] == "current_electron_tree_unavailable"
    assert status["launchBlocking"] is True


def test_inspect_desktop_shell_current_when_hashes_match(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    _mock_frontend_inspection(monkeypatch, tmp_path)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    status = desktop_shell.inspect_desktop_shell(tmp_path)
    assert status["stale"] is False
    assert status["reason"] == "current"
    assert status["activeFrontendReleaseUsable"] is True
    assert status["launchBlocking"] is False
    assert status["packagedSourceCommit"] == "a" * 40
    assert status["currentCommit"] == tree
    assert status["packagedFrontendContentSha256"] == status["expectedFrontendContentSha256"]


def test_inspect_desktop_shell_source_newer_than_asar(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=1_000_000)
    _mock_frontend_inspection(monkeypatch, tmp_path)
    newer = tmp_path / "desktop" / "electron" / "src" / "main.ts"
    newer.write_text("export const next = 1;\n", encoding="utf-8")
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    status = desktop_shell.inspect_desktop_shell(tmp_path)
    assert status["stale"] is True
    assert status["reason"] == "source_newer_than_asar"
    assert status["launchBlocking"] is True


def test_inspect_desktop_shell_package_frontend_bytes_must_match_provenance(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    _mock_frontend_inspection(monkeypatch, tmp_path)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    (desktop_shell.packaged_frontend_dist(tmp_path) / "index.html").write_text("<main>tampered</main>\n", encoding="utf-8")

    status = desktop_shell.inspect_desktop_shell(tmp_path)

    assert status["stale"] is True
    assert status["reason"] == "frontend_package_content_mismatch"


def test_inspect_desktop_shell_requires_current_frontend_build_inputs(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    _mock_frontend_inspection(monkeypatch, tmp_path, current=False)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)

    status = desktop_shell.inspect_desktop_shell(tmp_path)

    assert status["stale"] is True
    assert status["reason"] == "frontend_source_stale"


def test_inspect_desktop_shell_missing_current_frontend_tree_is_not_current(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    monkeypatch.setattr(
        desktop_shell,
        "inspect_frontend_build",
        lambda project_root: {
            "current": True,
            "dist": str(tmp_path / "web" / ".vibelution-builds" / "release-current"),
            "provenance": {},
            "buildInputs": {},
        },
    )

    status = desktop_shell.inspect_desktop_shell(tmp_path)

    assert status["stale"] is True
    assert status["reason"] == "current_frontend_tree_unavailable"


def test_inspect_desktop_shell_compares_package_to_latest_active_frontend_bytes(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    release = tmp_path / "web" / ".vibelution-builds" / "release-current"
    _mock_frontend_inspection(monkeypatch, tmp_path, release=release)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    (release / "index.html").write_bytes(b"<main>new active frontend</main>\n")

    status = desktop_shell.inspect_desktop_shell(tmp_path)

    assert status["stale"] is True
    assert status["reason"] == "frontend_release_mismatch"


def test_inspect_desktop_shell_requires_packaged_frontend_content_proof(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    _mock_frontend_inspection(monkeypatch, tmp_path)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    provenance_path = desktop_shell.packaged_provenance_path(tmp_path)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance.pop("frontendContentSha256")
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    status = desktop_shell.inspect_desktop_shell(tmp_path)

    assert status["stale"] is True
    assert status["reason"] == "missing_frontend_provenance"


def _build_shell_with_frontend_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str) -> None:
    """Construct a packaged shell whose inspect waterfall lands on ``reason``."""

    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    release = tmp_path / "web" / ".vibelution-builds" / "release-current"
    if reason == "missing_frontend_provenance":
        _mock_frontend_inspection(monkeypatch, tmp_path)
        provenance_path = desktop_shell.packaged_provenance_path(tmp_path)
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance.pop("frontendContentSha256")
        provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    elif reason == "frontend_package_content_mismatch":
        _mock_frontend_inspection(monkeypatch, tmp_path)
        (desktop_shell.packaged_frontend_dist(tmp_path) / "index.html").write_text(
            "<main>tampered</main>\n", encoding="utf-8"
        )
    elif reason == "frontend_source_stale":
        _mock_frontend_inspection(monkeypatch, tmp_path, current=False)
    elif reason == "frontend_inspection_failed":
        def _raise(project_root):
            raise RuntimeError("frontend inspection exploded")

        monkeypatch.setattr(desktop_shell, "inspect_frontend_build", _raise)
    elif reason == "current_frontend_tree_unavailable":
        monkeypatch.setattr(
            desktop_shell,
            "inspect_frontend_build",
            lambda project_root: {
                "current": True,
                "dist": str(release),
                "provenance": {},
                "buildInputs": {},
            },
        )
    elif reason == "frontend_release_mismatch":
        _mock_frontend_inspection(monkeypatch, tmp_path)
        (release / "index.html").write_bytes(b"<main>new active frontend</main>\n")
    elif reason == "frontend_source_mismatch":
        _mock_frontend_inspection(monkeypatch, tmp_path)
        provenance_path = desktop_shell.packaged_provenance_path(tmp_path)
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["frontendTreeHash"] = "e" * 40
        provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    else:
        raise AssertionError(f"unsupported frontend reason: {reason}")


@pytest.mark.parametrize("reason", sorted(desktop_shell.FRONTEND_ONLY_STALE_REASONS))
def test_inspect_desktop_shell_frontend_reasons_follow_active_release_availability(tmp_path, monkeypatch, reason):
    _build_shell_with_frontend_reason(tmp_path, monkeypatch, reason)

    status = desktop_shell.inspect_desktop_shell(tmp_path)

    assert status["stale"] is True
    assert status["reason"] == reason
    assert status["activeFrontendReleaseUsable"] is True
    assert status["launchBlocking"] is False

    # Without a usable workspace active release the packaged launcher window
    # would serve the stale packaged snapshot, so the same reason blocks again.
    (tmp_path / "web" / ".vibelution-builds" / "active.json").unlink()
    blocked = desktop_shell.inspect_desktop_shell(tmp_path)
    assert blocked["stale"] is True
    assert blocked["reason"] == reason
    assert blocked["activeFrontendReleaseUsable"] is False
    assert blocked["launchBlocking"] is True


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
    monkeypatch.setattr(desktop_shell, "_new_scheduled_helper_job", lambda: None)
    monkeypatch.setattr(desktop_shell, "_resume_scheduled_helper", lambda _process: None)
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
    assert flags & desktop_shell.CREATE_SUSPENDED
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
    monkeypatch.setattr(desktop_shell, "_new_scheduled_helper_job", lambda: None)
    monkeypatch.setattr(desktop_shell, "_resume_scheduled_helper", lambda _process: None)
    result = desktop_shell.schedule_desktop_shell_refresh(wait_pid=44, project_root=tmp_path, force=True)
    assert result["scheduled"] is True
    assert result["helperPid"] == 654
    assert desktop_shell.recent_desktop_shell_refresh_failure(tmp_path) is None


def test_run_desktop_shell_refresh_packaged_kind_promotes_even_from_unpackaged_shell(tmp_path, monkeypatch):
    """shell_kind=packaged must walk rebuild/promote, never the unpackaged path.

    The unpackaged rebuild-and-start defect: a running unpackaged shell
    scheduled its replacement with shell_kind=unpackaged, so the helper
    re-ensured the unpackaged bundle and the freshly built packaged shell was
    never promoted. The Electron side now forces "packaged" for that intent.
    """
    calls: list[str] = []

    def fail_unpackaged(*_args, **_kwargs):
        raise AssertionError("shell_kind=packaged must not take the unpackaged ensure/launch path")

    def fake_rebuild(*_args, **_kwargs):
        calls.append("rebuild")
        return {"rebuilt": True}

    def fake_launch_packaged(*, project_root, then_lifecycle=""):
        calls.append(f"launch_packaged:{then_lifecycle}")
        return {"launched": True, "pid": 11}

    monkeypatch.setattr(desktop_shell, "ensure_unpackaged_electron", fail_unpackaged)
    monkeypatch.setattr(desktop_shell, "launch_desktop_shell", fail_unpackaged)
    monkeypatch.setattr(desktop_shell, "rebuild_desktop_shell", fake_rebuild)
    monkeypatch.setattr(desktop_shell, "launch_packaged_desktop_shell", fake_launch_packaged)

    result = desktop_shell.run_desktop_shell_refresh(
        wait_pid=0,
        then_lifecycle="rebuild-and-start",
        project_root=tmp_path,
        shell_kind="packaged",
    )
    assert result["refreshed"] is True
    assert calls == ["rebuild", "launch_packaged:rebuild-and-start"]


def test_run_desktop_shell_refresh_default_kind_keeps_packaged_promotion(tmp_path, monkeypatch):
    """Empty shell_kind (tray restart-all) keeps the packaged promotion path."""
    calls: list[str] = []

    def fake_rebuild(*_args, **_kwargs):
        calls.append("rebuild")
        return {"rebuilt": True}

    def fake_launch_packaged(*, project_root, then_lifecycle=""):
        calls.append(f"launch_packaged:{then_lifecycle}")
        return {"launched": True, "pid": 12}

    monkeypatch.setattr(desktop_shell, "rebuild_desktop_shell", fake_rebuild)
    monkeypatch.setattr(desktop_shell, "launch_packaged_desktop_shell", fake_launch_packaged)

    result = desktop_shell.run_desktop_shell_refresh(wait_pid=0, project_root=tmp_path)
    assert result["refreshed"] is True
    assert calls == ["rebuild", "launch_packaged:"]


def test_run_desktop_shell_refresh_unpackaged_kind_keeps_unpackaged_relaunch(tmp_path, monkeypatch):
    """Plain unpackaged relaunch semantics stay pinned (restart keeps its kind)."""
    calls: list[str] = []

    def fake_ensure(*_args, **_kwargs):
        calls.append("ensure_unpackaged")
        return {"rebuilt": False}

    def fake_launch(*_args, prefer="", then_lifecycle="", **_kwargs):
        calls.append(f"launch:{prefer}:{then_lifecycle}")
        return {"launched": True, "pid": 13}

    def fail_rebuild(*_args, **_kwargs):
        raise AssertionError("shell_kind=unpackaged must not rebuild the packaged shell")

    monkeypatch.setattr(desktop_shell, "ensure_unpackaged_electron", fake_ensure)
    monkeypatch.setattr(desktop_shell, "launch_desktop_shell", fake_launch)
    monkeypatch.setattr(desktop_shell, "rebuild_desktop_shell", fail_rebuild)

    result = desktop_shell.run_desktop_shell_refresh(
        wait_pid=0,
        then_lifecycle="restart",
        project_root=tmp_path,
        shell_kind="unpackaged",
    )
    assert result["refreshed"] is True
    assert result["kind"] == "unpackaged"
    assert calls == ["ensure_unpackaged", "launch:unpackaged:restart"]


@pytest.mark.skipif(
    os.name != "nt",
    reason="no_window_subprocess_kwargs intentionally drops creationflags on "
    "POSIX, where the console-free spawn policy does not apply",
)
def test_schedule_desktop_shell_refresh_forwards_shell_kind(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            self.pid = 322

    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    monkeypatch.setattr(desktop_shell.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(desktop_shell, "_new_scheduled_helper_job", lambda: None)
    monkeypatch.setattr(desktop_shell, "_resume_scheduled_helper", lambda _process: None)
    result = desktop_shell.schedule_desktop_shell_refresh(
        wait_pid=44,
        then_lifecycle="rebuild-and-start",
        project_root=tmp_path,
        python_executable=str(python),
        shell_kind="packaged",
    )
    args = captured["args"]
    assert args[args.index("--shell-kind") + 1] == "packaged"
    assert args[args.index("--then-lifecycle") + 1] == "rebuild-and-start"
    assert result["scheduled"] is True
    assert result["helperPid"] == 322


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


def test_desktop_shell_package_build_uses_direct_owned_builder_entry(tmp_path, monkeypatch):
    ran: dict[str, object] = {}

    def fake_owned(command, **kwargs):
        ran["command"] = command
        ran["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(desktop_shell, "_node_command", lambda: r"C:\nodejs\node.exe")
    monkeypatch.setattr(desktop_shell, "_run_owned_process", fake_owned)
    session = desktop_shell._run_desktop_shell_package_build(
        tmp_path,
        mode="dir",
        deadline=desktop_shell.time.monotonic() + 30,
    )
    command = ran["command"]
    kwargs = ran["kwargs"]
    assert command[0] == r"C:\nodejs\node.exe"
    assert command[1].endswith("buildDesktopPackage.js")
    assert command[-2:] == ["--mode", "dir"]
    assert kwargs["env"]["VIBELUTION_DESKTOP_BUILD_ROOT"] == str(session)
    assert kwargs["env"]["VIBELUTION_DESKTOP_BUILD_MANAGED"] == "1"
    assert kwargs["deadline"] > desktop_shell.time.monotonic()
    shutil.rmtree(session, ignore_errors=True)


def test_package_build_retirement_failure_keeps_lock_and_stage_until_retry(tmp_path, monkeypatch):
    class FakeProcess:
        returncode = 0

        def wait(self, timeout=None):
            return 0

    class FakeOwner:
        def __init__(self):
            self.process = FakeProcess()
            self.fail_close = True
            self.close_calls = 0

        def close(self, *, timeout):
            self.close_calls += 1
            if self.fail_close:
                raise RuntimeError("synthetic process tree still active")

    owner = FakeOwner()
    monkeypatch.setattr(desktop_shell, "_node_command", lambda: "node")
    monkeypatch.setattr(desktop_shell, "uuid4", lambda: types.SimpleNamespace(hex="retirement"))

    def spawn(_command, **kwargs):
        session = Path(kwargs["env"]["VIBELUTION_DESKTOP_BUILD_ROOT"])
        session.mkdir(parents=True)
        return owner

    monkeypatch.setattr(desktop_shell.OwnedProcess, "spawn", spawn)
    with pytest.raises(desktop_shell.BuildProcessRetirementError, match="could not be confirmed"):
        desktop_shell.build_desktop_shell_package(tmp_path)

    session = tmp_path / "dist" / ".desktop-shell-build-retirement"
    lock = desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE)
    assert session.is_dir()
    assert lock.is_file()
    assert owner.close_calls == desktop_shell.DESKTOP_SHELL_BUILD_CLOSE_RETRIES

    owner.fail_close = False
    desktop_shell._ensure_desktop_shell_build_lock(
        tmp_path,
        deadline=desktop_shell.time.monotonic() + 5,
    )
    assert owner.close_calls == desktop_shell.DESKTOP_SHELL_BUILD_CLOSE_RETRIES + 1
    assert not session.exists()
    assert desktop_shell._desktop_shell_lock_owned_by_current_process(
        tmp_path,
        lock_relative=desktop_shell.PREBUILD_LOCK_RELATIVE,
    )
    desktop_shell._release_desktop_shell_refresh_lock(
        tmp_path,
        lock_relative=desktop_shell.PREBUILD_LOCK_RELATIVE,
    )


@pytest.mark.parametrize(
    ("mode", "relative_output"),
    [
        ("dir", desktop_shell.PACKAGED_EXE_RELATIVE.parent),
        ("staging", desktop_shell.STAGING_WIN_UNPACKED_RELATIVE),
    ],
)
def test_package_build_reports_published_windows_output(tmp_path, monkeypatch, mode, relative_output):
    tree = "a" * 40
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    _stub_desktop_shell_package_build(monkeypatch, tmp_path, tree_hash=tree)

    result = desktop_shell.build_desktop_shell_package(tmp_path, mode=mode)

    destination = tmp_path / relative_output
    assert result["output"] == str(destination)
    assert (destination / "Vibelution.exe").is_file()
    assert not Path(result["output"]).name.startswith(".desktop-shell-build-")


def test_package_build_reports_published_linux_output(tmp_path, monkeypatch):
    def fake_build(project_root, *, mode, deadline):
        assert mode == "linux-arm64"
        assert desktop_shell._desktop_shell_lock_owned_by_current_process(
            Path(project_root), lock_relative=desktop_shell.PREBUILD_LOCK_RELATIVE
        )
        session = Path(project_root) / "dist" / ".linux-package-session"
        output = session / "builder-output"
        output.mkdir(parents=True)
        (output / "marker").write_text("published", encoding="utf-8")
        return session

    monkeypatch.setattr(desktop_shell, "_run_desktop_shell_package_build", fake_build)
    result = desktop_shell.build_desktop_shell_package(tmp_path, mode="linux-arm64")

    destination = tmp_path / "dist" / "desktop-linux-arm64"
    assert result["output"] == str(destination)
    assert (destination / "marker").read_text(encoding="utf-8") == "published"
    assert not (tmp_path / "dist" / ".linux-package-session").exists()


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
    _mock_frontend_inspection(monkeypatch, tmp_path)
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


def test_resolve_desktop_shell_launch_launches_packaged_with_advisory_frontend_stale(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    _mock_frontend_inspection(monkeypatch, tmp_path)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    release = tmp_path / "web" / ".vibelution-builds" / "release-current"
    (release / "index.html").write_bytes(b"<main>new active frontend</main>\n")

    spec = desktop_shell.resolve_desktop_shell_launch(tmp_path, then_lifecycle="start", open_workbench=True)

    assert spec["kind"] == "packaged"
    # Advisory frontend staleness keeps the packaged exe but must not be
    # reported as "current"; downstream status shows the real reason.
    assert spec["reason"] == "frontend_release_mismatch"
    assert spec["args"][0] == str(desktop_shell.packaged_desktop_exe(tmp_path))


def test_resolve_desktop_shell_launch_falls_back_when_launch_blocking(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash="b" * 40, asar_mtime=2_000_000_000)
    electron_exe = _write_unpackaged_electron(tmp_path, tree_hash=tree, main_mtime=2_000_000_000)
    _mock_frontend_inspection(monkeypatch, tmp_path)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)

    spec = desktop_shell.resolve_desktop_shell_launch(tmp_path, open_workbench=True)

    assert spec["kind"] == "unpackaged"
    assert spec["args"][:2] == [str(electron_exe), str(desktop_shell.unpackaged_main_js(tmp_path))]


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

    def fake_owned(command, **kwargs):
        calls.append([str(part) for part in command])
        stage = Path(kwargs.get("env", {}).get("VIBELUTION_ELECTRON_DIST", ""))
        assert kwargs["env"]["VIBELUTION_DESKTOP_BUILD_MANAGED"] == "1"
        assert Path(kwargs["env"]["VIBELUTION_DESKTOP_BUILD_ROOT"]) == stage
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
    monkeypatch.setattr(desktop_shell, "_run_owned_process", fake_owned)
    result = desktop_shell.ensure_unpackaged_electron(tmp_path)
    assert all("package:dir" not in " ".join(command) for command in calls)
    assert any("--outDir" in command for command in calls)
    # esbuild CLI rejects space-separated values for value flags (e.g. "--outfile x"),
    # so the launcher must pass them joined, matching the npm build:preload script.
    esbuild_call = next(command for command in calls if any(part.startswith("--outfile") for part in command))
    assert any(part.startswith("--outfile=") for part in esbuild_call)
    assert "--platform=node" in esbuild_call and "--format=cjs" in esbuild_call
    assert not list((tmp_path / "desktop" / "electron").glob(".build-stage-*"))
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
    _mock_frontend_inspection(monkeypatch, tmp_path)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    spec = desktop_shell.resolve_desktop_shell_launch(tmp_path, then_lifecycle="start", open_workbench=True)
    assert spec["kind"] == "packaged"
    assert "--hidden-presentation" not in spec["args"]


def test_resolve_desktop_shell_launch_forwards_hidden_presentation(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_packaged_shell(tmp_path, tree_hash=tree, asar_mtime=2_000_000_000)
    _mock_frontend_inspection(monkeypatch, tmp_path)
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
    _mock_frontend_inspection(monkeypatch, integration)
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


def _write_prebuild_lock(tmp_path: Path, *, pid: int) -> Path:
    lock = desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": pid, "startedAt": "2026-10-01T00:00:00Z"}), encoding="utf-8")
    return lock


def _write_refresh_lock(tmp_path: Path, *, pid: int) -> Path:
    lock = desktop_shell._refresh_lock_path(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": pid, "startedAt": "2026-10-01T00:00:00Z"}), encoding="utf-8")
    return lock


def _write_staged_shell(root: Path, *, tree_hash: str) -> Path:
    staging_unpacked = root / desktop_shell.STAGING_WIN_UNPACKED_RELATIVE
    provenance_dir = staging_unpacked / "resources" / "app.asar.unpacked"
    provenance_dir.mkdir(parents=True)
    (staging_unpacked / "Vibelution.exe").write_bytes(b"mz")
    (staging_unpacked / "main.js").write_text("new", encoding="utf-8")
    (provenance_dir / "package-provenance.json").write_text(
        json.dumps({"electronTreeHash": tree_hash}), encoding="utf-8"
    )
    return staging_unpacked


def _write_built_shell_session(root: Path, *, tree_hash: str, name: str = "package-build") -> Path:
    session = root / "dist" / f".{name}"
    built = session / "builder-output" / "win-unpacked"
    provenance_dir = built / "resources" / "app.asar.unpacked"
    provenance_dir.mkdir(parents=True)
    (built / "Vibelution.exe").write_bytes(b"mz")
    (built / "main.js").write_text("new", encoding="utf-8")
    (built / "resources" / "app.asar").write_bytes(b"asar")
    (provenance_dir / "package-provenance.json").write_text(
        json.dumps({"electronTreeHash": tree_hash}), encoding="utf-8"
    )
    return session


def _stub_desktop_shell_package_build(monkeypatch, root: Path, *, tree_hash: str) -> None:
    def fake_build(project_root, *, mode, deadline):
        assert desktop_shell._desktop_shell_lock_owned_by_current_process(
            Path(project_root), lock_relative=desktop_shell.PREBUILD_LOCK_RELATIVE
        )
        return _write_built_shell_session(
            Path(project_root), tree_hash=tree_hash, name=f"package-build-{mode}"
        )

    monkeypatch.setattr(
        desktop_shell,
        "_run_desktop_shell_package_build",
        fake_build,
    )


def _write_live_win_unpacked(root: Path) -> Path:
    live = root / "dist" / "desktop" / "win-unpacked"
    live.mkdir(parents=True, exist_ok=True)
    (live / "Vibelution.exe").write_bytes(b"mz")
    (live / "main.js").write_text("old", encoding="utf-8")
    return live


def test_prebuild_lock_is_independent_of_refresh_lock(tmp_path):
    assert desktop_shell._acquire_desktop_shell_refresh_lock(
        tmp_path, lock_relative=desktop_shell.PREBUILD_LOCK_RELATIVE
    ) is True
    assert desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()
    assert not desktop_shell._refresh_lock_path(tmp_path).is_file()
    assert desktop_shell._acquire_desktop_shell_refresh_lock(tmp_path) is True

    desktop_shell._release_desktop_shell_refresh_lock(tmp_path)
    assert not desktop_shell._refresh_lock_path(tmp_path).is_file()
    assert desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()

    desktop_shell._release_desktop_shell_refresh_lock(
        tmp_path, lock_relative=desktop_shell.PREBUILD_LOCK_RELATIVE
    )
    assert not desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()


@pytest.mark.skipif(
    os.name != "nt",
    reason="pythonw resolution and Windows spawn flags",
)
def test_schedule_desktop_shell_prebuild_spawns_pythonw_helper_and_transfers_lock(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.pid = 4321

    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    pythonw = tmp_path / "pythonw.exe"
    pythonw.write_text("", encoding="utf-8")
    monkeypatch.setattr(desktop_shell.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(desktop_shell, "_new_scheduled_helper_job", lambda: None)
    monkeypatch.setattr(desktop_shell, "_resume_scheduled_helper", lambda _process: None)

    result = desktop_shell.schedule_desktop_shell_prebuild(tmp_path, python_executable=str(python))

    args = captured["args"]
    assert args[0] == str(pythonw)
    assert args[args.index("--action") + 1] == "prebuild-desktop-shell"
    assert args[args.index("--workspace") + 1] == str(tmp_path)
    assert captured["kwargs"]["stdin"] is desktop_shell.subprocess.DEVNULL
    flags = int(captured["kwargs"].get("creationflags") or 0)
    assert flags & int(getattr(desktop_shell.subprocess, "CREATE_NO_WINDOW", 0x08000000))
    assert flags & desktop_shell.CREATE_NEW_PROCESS_GROUP
    assert flags & desktop_shell.CREATE_BREAKAWAY_FROM_JOB
    assert flags & desktop_shell.CREATE_SUSPENDED
    assert result["scheduled"] is True
    assert result["helperPid"] == 4321
    lock_payload = json.loads(
        desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).read_text(encoding="utf-8")
    )
    assert lock_payload["pid"] == 4321
    desktop_shell._release_desktop_shell_refresh_lock(
        tmp_path, lock_relative=desktop_shell.PREBUILD_LOCK_RELATIVE
    )


@pytest.mark.parametrize(
    ("kind", "lock_relative"),
    [
        ("refresh", desktop_shell.REFRESH_LOCK_RELATIVE),
        ("prebuild", desktop_shell.PREBUILD_LOCK_RELATIVE),
    ],
)
def test_scheduled_helper_hands_off_lock_before_resume(tmp_path, monkeypatch, kind, lock_relative):
    events: list[str] = []

    class FakePopen:
        pid = 8412
        _handle = 18

    class FakeJob:
        def assign_handle(self, _handle):
            events.append("job-assign")

        def set_kill_on_job_close(self, enabled):
            events.append(f"kill-on-close-{enabled}")

        def close(self):
            events.append("job-close")

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", lambda *_args, **_kwargs: FakePopen())
    monkeypatch.setattr(desktop_shell, "_new_scheduled_helper_job", FakeJob)
    assign = desktop_shell._assign_desktop_shell_refresh_helper

    def record_handoff(
        root,
        helper_pid,
        *,
        lock_relative=desktop_shell.REFRESH_LOCK_RELATIVE,
        lock_token,
    ):
        events.append("handoff")
        return assign(root, helper_pid, lock_relative=lock_relative, lock_token=lock_token)

    def record_resume(process):
        payload = json.loads(
            desktop_shell._refresh_lock_path(tmp_path, lock_relative).read_text(encoding="utf-8")
        )
        assert payload["pid"] == process.pid
        events.append("resume")

    monkeypatch.setattr(desktop_shell, "_assign_desktop_shell_refresh_helper", record_handoff)
    monkeypatch.setattr(desktop_shell, "_resume_scheduled_helper", record_resume)

    if kind == "refresh":
        result = desktop_shell.schedule_desktop_shell_refresh(wait_pid=44, project_root=tmp_path)
    else:
        result = desktop_shell.schedule_desktop_shell_prebuild(tmp_path)

    assert result["scheduled"] is True
    assert events == ["job-assign", "handoff", "resume", "kill-on-close-False", "job-close"]


def test_scheduled_helper_claim_transfers_parent_lock_and_refreshes_started_at(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "pid": 8411,
                "startedAt": "2026-10-01T00:00:00+00:00",
                "ownerToken": "claim-token",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_shell.os, "getpid", lambda: 8412)
    monkeypatch.setattr(desktop_shell.os, "getppid", lambda: 8411)

    assert desktop_shell._claim_scheduled_desktop_shell_helper_lock(
        tmp_path,
        lock_relative=desktop_shell.REFRESH_LOCK_RELATIVE,
        lock_token="claim-token",
    ) is True

    claimed = json.loads(lock_path.read_text(encoding="utf-8"))
    assert claimed["pid"] == 8412
    assert claimed["ownerToken"] == "claim-token"
    assert claimed["startedAt"] != "2026-10-01T00:00:00+00:00"


@pytest.mark.parametrize(
    ("holder_pid", "token"),
    [(8410, "claim-token"), (8411, "replaced-token")],
)
def test_scheduled_helper_claim_rejects_wrong_parent_or_replaced_owner(
    tmp_path,
    monkeypatch,
    holder_pid,
    token,
):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps(
        {"pid": holder_pid, "startedAt": "2026-10-01T00:00:00+00:00", "ownerToken": "claim-token"}
    )
    lock_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(desktop_shell.os, "getpid", lambda: 8412)
    monkeypatch.setattr(desktop_shell.os, "getppid", lambda: 8411)

    assert desktop_shell._claim_scheduled_desktop_shell_helper_lock(
        tmp_path,
        lock_relative=desktop_shell.REFRESH_LOCK_RELATIVE,
        lock_token=token,
    ) is False
    assert lock_path.read_text(encoding="utf-8") == original


def test_scheduled_helper_claim_retries_only_transient_busy_breaker(tmp_path, monkeypatch):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"pid": 8411, "startedAt": "2026-10-01T00:00:00+00:00", "ownerToken": "claim-token"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_shell.os, "getpid", lambda: 8412)
    monkeypatch.setattr(desktop_shell.os, "getppid", lambda: 8411)
    monkeypatch.setattr(desktop_shell.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(desktop_shell, "SCHEDULED_HELPER_LOCK_CLAIM_RETRY_SECONDS", 0.2)
    real_breaker = desktop_shell._refresh_lock_breaker
    attempts = 0

    @contextmanager
    def busy_twice(path):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            yield False
            return
        with real_breaker(path) as acquired:
            yield acquired

    monkeypatch.setattr(desktop_shell, "_refresh_lock_breaker", busy_twice)
    assert desktop_shell._claim_scheduled_desktop_shell_helper_lock(
        tmp_path,
        lock_relative=desktop_shell.REFRESH_LOCK_RELATIVE,
        lock_token="claim-token",
    ) is True
    assert attempts == 3
    assert json.loads(lock_path.read_text(encoding="utf-8"))["pid"] == 8412


def test_scheduled_helper_retirement_releases_updated_pid_but_preserves_new_token(tmp_path):
    lock_path = desktop_shell._refresh_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"pid": 8412, "ownerToken": "retiring-token", "startedAt": "updated"}),
        encoding="utf-8",
    )
    assert desktop_shell._release_scheduled_helper_lock(
        tmp_path,
        lock_relative=desktop_shell.REFRESH_LOCK_RELATIVE,
        lock_token="retiring-token",
    ) is True
    assert not lock_path.exists()

    lock_path.write_text(
        json.dumps({"pid": 9200, "ownerToken": "new-token", "startedAt": "new-owner"}),
        encoding="utf-8",
    )
    assert desktop_shell._release_scheduled_helper_lock(
        tmp_path,
        lock_relative=desktop_shell.REFRESH_LOCK_RELATIVE,
        lock_token="retiring-token",
    ) is True
    assert json.loads(lock_path.read_text(encoding="utf-8"))["ownerToken"] == "new-token"


@pytest.mark.parametrize(
    ("kind", "lock_relative"),
    [
        ("refresh", desktop_shell.REFRESH_LOCK_RELATIVE),
        ("prebuild", desktop_shell.PREBUILD_LOCK_RELATIVE),
    ],
)
def test_scheduled_helper_handoff_failure_retires_process_before_releasing_lock(
    tmp_path,
    monkeypatch,
    kind,
    lock_relative,
):
    class FakePopen:
        pid = 8413

        def __init__(self):
            self.returncode = None
            self.terminate_calls = 0
            self.kill_calls = 0

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminate_calls += 1
            self.returncode = -15

        def kill(self):
            self.kill_calls += 1
            self.returncode = -9

        def wait(self, timeout=None):
            if self.returncode is None:
                raise desktop_shell.subprocess.TimeoutExpired("helper", timeout)
            return self.returncode

    process = FakePopen()
    spawn_count = 0

    def spawn(*_args, **_kwargs):
        nonlocal spawn_count
        spawn_count += 1
        return process

    def fail_handoff(*_args, **_kwargs):
        raise OSError("synthetic lock handoff failure")

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", spawn)
    monkeypatch.setattr(desktop_shell, "_new_scheduled_helper_job", lambda: None)
    monkeypatch.setattr(desktop_shell, "_assign_desktop_shell_refresh_helper", fail_handoff)
    monkeypatch.setattr(
        desktop_shell,
        "_resume_scheduled_helper",
        lambda _process: (_ for _ in ()).throw(AssertionError("failed handoff must not resume helper")),
    )

    if kind == "refresh":
        schedule = lambda: desktop_shell.schedule_desktop_shell_refresh(wait_pid=44, project_root=tmp_path)
    else:
        schedule = lambda: desktop_shell.schedule_desktop_shell_prebuild(tmp_path)

    with pytest.raises(RuntimeError, match="helper could not be started safely"):
        schedule()

    assert process.terminate_calls == 1
    assert process.poll() is not None
    assert not desktop_shell._refresh_lock_path(tmp_path, lock_relative).exists()
    assert spawn_count == 1


@pytest.mark.parametrize("retire_job_tree", [True, False])
def test_clear_kill_on_job_close_failure_retires_before_unlocking(tmp_path, monkeypatch, retire_job_tree):
    events: list[str] = []

    class FakePopen:
        pid = 8415
        _handle = 19

        def __init__(self):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            if retire_job_tree:
                self.returncode = -15

        def kill(self):
            if retire_job_tree:
                self.returncode = -9

        def wait(self, timeout=None):
            if self.returncode is None:
                raise desktop_shell.subprocess.TimeoutExpired("helper", timeout)
            return self.returncode

    process = FakePopen()

    class FakeJob:
        def __init__(self):
            self.active = 1

        def assign_handle(self, _handle):
            events.append("job-assign")

        def set_kill_on_job_close(self, enabled):
            events.append(f"kill-on-close-{enabled}")
            if not enabled:
                raise OSError("synthetic Job detach failure")

        def active_count(self):
            return self.active

        def terminate(self):
            events.append("job-terminate")
            if retire_job_tree:
                self.active = 0
                process.returncode = -9

        def close(self):
            events.append("job-close")

    job = FakeJob()
    monkeypatch.setattr(desktop_shell, "SCHEDULED_HELPER_RETIRE_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(desktop_shell.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(desktop_shell, "_new_scheduled_helper_job", lambda: job)
    monkeypatch.setattr(desktop_shell, "_resume_scheduled_helper", lambda _process: events.append("resume"))

    if retire_job_tree:
        with pytest.raises(RuntimeError, match="helper could not be started safely"):
            desktop_shell.schedule_desktop_shell_refresh(wait_pid=44, project_root=tmp_path)
        assert process.poll() is not None
        assert not desktop_shell._refresh_lock_path(tmp_path).exists()
    else:
        with pytest.raises(desktop_shell.ScheduledHelperRetirementError, match="lock remains held"):
            desktop_shell.schedule_desktop_shell_refresh(wait_pid=44, project_root=tmp_path)
        assert desktop_shell._refresh_lock_path(tmp_path).is_file()
        job.active = 0
        process.returncode = -9
        assert desktop_shell._retry_pending_scheduled_helper_retirements(tmp_path) is True
        assert not desktop_shell._refresh_lock_path(tmp_path).exists()

    assert events.index("resume") < events.index("kill-on-close-False")
    assert events.index("kill-on-close-False") < events.index("kill-on-close-True")


@pytest.mark.parametrize(
    ("kind", "lock_relative"),
    [
        ("refresh", desktop_shell.REFRESH_LOCK_RELATIVE),
        ("prebuild", desktop_shell.PREBUILD_LOCK_RELATIVE),
    ],
)
def test_unconfirmed_helper_retirement_keeps_lock_and_blocks_reschedule(
    tmp_path,
    monkeypatch,
    kind,
    lock_relative,
):
    class FakePopen:
        pid = 8414

        def __init__(self):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            return None

        def kill(self):
            return None

        def wait(self, timeout=None):
            if self.returncode is None:
                raise desktop_shell.subprocess.TimeoutExpired("helper", timeout)
            return self.returncode

    process = FakePopen()
    spawn_count = 0
    monkeypatch.setattr(desktop_shell, "SCHEDULED_HELPER_RETIRE_TIMEOUT_SECONDS", 0.02)

    def spawn(*_args, **_kwargs):
        nonlocal spawn_count
        spawn_count += 1
        return process

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", spawn)
    monkeypatch.setattr(desktop_shell, "_new_scheduled_helper_job", lambda: None)
    monkeypatch.setattr(
        desktop_shell,
        "_assign_desktop_shell_refresh_helper",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic handoff failure")),
    )

    if kind == "refresh":
        schedule = lambda: desktop_shell.schedule_desktop_shell_refresh(wait_pid=44, project_root=tmp_path)
    else:
        schedule = lambda: desktop_shell.schedule_desktop_shell_prebuild(tmp_path)

    with pytest.raises(desktop_shell.ScheduledHelperRetirementError, match="lock remains held"):
        schedule()

    lock_path = desktop_shell._refresh_lock_path(tmp_path, lock_relative)
    assert lock_path.is_file()
    blocked = schedule()
    assert blocked["scheduled"] is False
    assert blocked["reason"] == "helper_retirement_pending"
    assert spawn_count == 1
    assert lock_path.is_file()

    process.returncode = -9
    assert desktop_shell._retry_pending_scheduled_helper_retirements(tmp_path) is True
    assert not lock_path.exists()


def test_pending_helper_retirement_keeps_handles_open_until_lock_release_succeeds(tmp_path, monkeypatch):
    class FakeHandle:
        closed = False

        def Close(self):
            self.closed = True

    class FakePopen:
        pid = 8416

        def __init__(self):
            self.returncode = None
            self._handle = FakeHandle()

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            if self.returncode is None:
                raise desktop_shell.subprocess.TimeoutExpired("helper", timeout)
            return self.returncode

    class FakeJob:
        def __init__(self):
            self.active = 1
            self.closed = False

        def assign_handle(self, _handle):
            pass

        def set_kill_on_job_close(self, enabled):
            if not enabled:
                raise OSError("synthetic Job detach failure")

        def active_count(self):
            return self.active

        def terminate(self):
            self.active = 0

        def close(self):
            self.closed = True

    process = FakePopen()
    job = FakeJob()
    release_attempts = 0
    release_lock = desktop_shell._release_scheduled_helper_lock

    def fail_first_release(*args, **kwargs):
        nonlocal release_attempts
        release_attempts += 1
        if release_attempts == 1:
            return False
        return release_lock(*args, **kwargs)

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(desktop_shell, "_new_scheduled_helper_job", lambda: job)
    monkeypatch.setattr(
        desktop_shell,
        "_resume_scheduled_helper",
        lambda _process: None,
    )
    monkeypatch.setattr(desktop_shell, "_release_scheduled_helper_lock", fail_first_release)

    with pytest.raises(desktop_shell.ScheduledHelperRetirementError, match="lock remains held"):
        desktop_shell.schedule_desktop_shell_refresh(wait_pid=44, project_root=tmp_path)

    assert process.poll() is not None
    assert process._handle.closed is False
    assert job.closed is False
    assert desktop_shell._refresh_lock_path(tmp_path).is_file()

    assert desktop_shell._retry_pending_scheduled_helper_retirements(tmp_path) is True
    assert process._handle is None
    assert job.closed is True
    assert not desktop_shell._refresh_lock_path(tmp_path).exists()


def test_concurrent_pending_helper_retries_retire_and_close_owner_once(tmp_path, monkeypatch):
    retire_started = threading.Event()
    allow_retire_to_finish = threading.Event()
    second_retire_started = threading.Event()
    second_call_started = threading.Event()
    counts = {"retire": 0, "release": 0, "close": 0}
    owner = desktop_shell._ScheduledHelperOwner(process=object(), job=object())

    def retire(_owner, *, timeout):
        assert _owner is owner
        assert timeout == desktop_shell.SCHEDULED_HELPER_RETIRE_TIMEOUT_SECONDS
        counts["retire"] += 1
        if counts["retire"] == 1:
            retire_started.set()
            assert allow_retire_to_finish.wait(timeout=2)
        else:
            second_retire_started.set()
        return True

    def release(_project_root, **_kwargs):
        counts["release"] += 1
        return True

    def close(_owner):
        assert _owner is owner
        counts["close"] += 1
        return True

    monkeypatch.setattr(desktop_shell, "_retire_scheduled_helper_owner", retire)
    monkeypatch.setattr(desktop_shell, "_release_scheduled_helper_lock", release)
    monkeypatch.setattr(desktop_shell, "_close_scheduled_helper_owner", close)
    desktop_shell._register_pending_scheduled_helper_retirement(
        tmp_path,
        owner,
        lock_relative=desktop_shell.REFRESH_LOCK_RELATIVE,
        lock_token="owner-token",
    )

    results: list[bool] = []
    errors: list[BaseException] = []

    def retry(*, signal_start: threading.Event | None = None):
        try:
            if signal_start is not None:
                signal_start.set()
            results.append(desktop_shell._retry_pending_scheduled_helper_retirements(tmp_path))
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=retry, name="scheduled-helper-retry-first")
    second = threading.Thread(
        target=retry,
        kwargs={"signal_start": second_call_started},
        name="scheduled-helper-retry-second",
    )
    first.start()
    try:
        assert retire_started.wait(timeout=1)
        second.start()
        assert second_call_started.wait(timeout=1)
        assert not second_retire_started.wait(timeout=0.1)
    finally:
        allow_retire_to_finish.set()
        first.join(timeout=2)
        if second.ident is not None:
            second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert results == [True, True]
    assert counts == {"retire": 1, "release": 1, "close": 1}


@pytest.mark.skipif(os.name != "nt", reason="real suspended process rollback is Windows-specific")
def test_refresh_handoff_failure_never_runs_isolated_suspended_helper(tmp_path, monkeypatch):
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    if not pythonw.is_file():
        pytest.skip("the active interpreter has no sibling pythonw.exe")
    entry = tmp_path / "scripts" / "vibelution_desktop_entry.py"
    entry.parent.mkdir(parents=True)
    marker = tmp_path / "helper-started.txt"
    entry.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('started', encoding='utf-8')\n"
        "import time\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    real_popen = desktop_shell.subprocess.Popen
    spawned: list[subprocess.Popen] = []

    def capture_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        spawned.append(process)
        return process

    def delayed_handoff_failure(*_args, **_kwargs):
        time.sleep(0.2)
        raise OSError("synthetic isolated handoff failure")

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", capture_popen)
    monkeypatch.setattr(desktop_shell, "_assign_desktop_shell_refresh_helper", delayed_handoff_failure)

    with pytest.raises(RuntimeError, match="helper could not be started safely"):
        desktop_shell.schedule_desktop_shell_refresh(
            wait_pid=0,
            project_root=tmp_path,
            python_executable=str(python),
        )

    assert len(spawned) == 1
    assert spawned[0].poll() is not None
    assert not marker.exists()


def test_schedule_desktop_shell_prebuild_skips_while_refresh_lock_held(tmp_path, monkeypatch):
    _write_refresh_lock(tmp_path, pid=99140)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("prebuild helper must not spawn while refresh holds its lock")

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", fail_if_called)
    result = desktop_shell.schedule_desktop_shell_prebuild(tmp_path)
    assert result["scheduled"] is False
    assert result["reason"] == "refresh_in_progress"


def test_schedule_desktop_shell_prebuild_skips_when_prebuild_lock_held(tmp_path, monkeypatch):
    _write_prebuild_lock(tmp_path, pid=99141)
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: True)
    # The holder process predates the lock, so it is the real holder.
    monkeypatch.setattr(desktop_shell, "_process_create_time", lambda pid: 0.0)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("prebuild helper must not spawn while another prebuild runs")

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", fail_if_called)
    result = desktop_shell.schedule_desktop_shell_prebuild(tmp_path)
    assert result["scheduled"] is False
    assert result["reason"] == "prebuild_in_progress"


def test_schedule_desktop_shell_prebuild_skips_during_cooldown(tmp_path, monkeypatch):
    desktop_shell._record_shell_failure_marker(
        desktop_shell._prebuild_failure_path(tmp_path),
        reason="prebuild_failed",
        detail="boom",
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("prebuild helper must not spawn during cooldown")

    monkeypatch.setattr(desktop_shell.subprocess, "Popen", fail_if_called)
    result = desktop_shell.schedule_desktop_shell_prebuild(tmp_path)
    assert result["scheduled"] is False
    assert result["reason"] == "prebuild_cooldown"


def test_run_desktop_shell_prebuild_skips_when_shell_current(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_shell, "inspect_desktop_shell", lambda root: {"stale": False, "reason": "current"})

    def fail_run(*_args, **_kwargs):
        raise AssertionError("current shell must not trigger a staging build")

    monkeypatch.setattr(desktop_shell.subprocess, "run", fail_run)
    result = desktop_shell.run_desktop_shell_prebuild(tmp_path)
    assert result["ok"] is True
    assert result["skipped"] == "current"
    assert not desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()


def test_run_desktop_shell_prebuild_skips_while_refresh_lock_held(tmp_path, monkeypatch):
    _write_refresh_lock(tmp_path, pid=99142)
    monkeypatch.setattr(
        desktop_shell,
        "inspect_desktop_shell",
        lambda root: (_ for _ in ()).throw(AssertionError("refresh takes precedence over prebuild")),
    )
    result = desktop_shell.run_desktop_shell_prebuild(tmp_path)
    assert result["ok"] is True
    assert result["skipped"] == "refresh_in_progress"
    assert not desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()


def test_run_desktop_shell_prebuild_stages_valid_build(tmp_path, monkeypatch):
    monkeypatch.setattr(
        desktop_shell,
        "inspect_desktop_shell",
        lambda root: {"stale": True, "reason": "provenance_mismatch"},
    )
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: "a" * 40)
    _stub_desktop_shell_package_build(monkeypatch, tmp_path, tree_hash="a" * 40)
    result = desktop_shell.run_desktop_shell_prebuild(tmp_path)
    assert result["ok"] is True
    assert result["staged"] is True
    assert (tmp_path / desktop_shell.STAGING_WIN_UNPACKED_RELATIVE / "Vibelution.exe").is_file()
    assert not desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()
    assert (
        desktop_shell._recent_shell_failure_marker(
            desktop_shell._prebuild_failure_path(tmp_path),
            cooldown_seconds=desktop_shell.PREBUILD_COOLDOWN_SECONDS,
        )
        is None
    )


def test_run_desktop_shell_prebuild_discards_staging_on_provenance_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        desktop_shell,
        "inspect_desktop_shell",
        lambda root: {"stale": True, "reason": "provenance_mismatch"},
    )
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: "a" * 40)
    _stub_desktop_shell_package_build(monkeypatch, tmp_path, tree_hash="b" * 40)
    result = desktop_shell.run_desktop_shell_prebuild(tmp_path)
    assert result["ok"] is False
    assert not (tmp_path / desktop_shell.STAGING_OUTPUT_DIR_RELATIVE).exists()
    marker = desktop_shell._recent_shell_failure_marker(
        desktop_shell._prebuild_failure_path(tmp_path),
        cooldown_seconds=desktop_shell.PREBUILD_COOLDOWN_SECONDS,
    )
    assert marker is not None
    assert marker["reason"] == "prebuild_failed"
    assert not desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()


def test_run_desktop_shell_prebuild_failure_records_cooldown_and_releases_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(
        desktop_shell,
        "inspect_desktop_shell",
        lambda root: {"stale": True, "reason": "provenance_mismatch"},
    )
    monkeypatch.setattr(
        desktop_shell,
        "_run_desktop_shell_package_build",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = desktop_shell.run_desktop_shell_prebuild(tmp_path)
    assert result["ok"] is False
    marker = desktop_shell._recent_shell_failure_marker(
        desktop_shell._prebuild_failure_path(tmp_path),
        cooldown_seconds=desktop_shell.PREBUILD_COOLDOWN_SECONDS,
    )
    assert marker is not None
    assert marker["reason"] == "prebuild_failed"
    assert not desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()


def test_npm_failure_detail_combines_both_streams():
    result = types.SimpleNamespace(
        returncode=1,
        stdout="step output\nnpm ERR! real failure",
        stderr="dist\\preload.cjs 1.7kb\n\nDone in 6ms",
    )
    detail = desktop_shell._npm_failure_detail(result)
    assert "npm ERR! real failure" in detail
    assert "Done in 6ms" in detail


def test_stage_desktop_shell_failure_detail_carries_stdout_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        desktop_shell,
        "_run_desktop_shell_package_build",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("npm ERR! write:provenance refused\n--\nDone in 6ms")
        ),
    )
    with pytest.raises(RuntimeError) as excinfo:
        desktop_shell._stage_desktop_shell(tmp_path)
    assert "write:provenance refused" in str(excinfo.value)
    assert "Done in 6ms" in str(excinfo.value)


def test_run_desktop_shell_prebuild_releases_lock_when_build_explodes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        desktop_shell,
        "inspect_desktop_shell",
        lambda root: {"stale": True, "reason": "provenance_mismatch"},
    )

    monkeypatch.setattr(
        desktop_shell,
        "_run_desktop_shell_package_build",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("npm vanished")),
    )
    result = desktop_shell.run_desktop_shell_prebuild(tmp_path)
    assert result["ok"] is False
    assert "npm vanished" in result["message"]
    marker = desktop_shell._recent_shell_failure_marker(
        desktop_shell._prebuild_failure_path(tmp_path),
        cooldown_seconds=desktop_shell.PREBUILD_COOLDOWN_SECONDS,
    )
    assert marker is not None
    assert not desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()


def test_try_promote_staged_desktop_shell_rejects_mismatched_and_incomplete_staging(tmp_path, monkeypatch):
    tree = "a" * 40
    live = _write_live_win_unpacked(tmp_path)
    _write_staged_shell(tmp_path, tree_hash="b" * 40)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)

    assert desktop_shell._try_promote_staged_desktop_shell(tmp_path) is False
    assert (live / "main.js").read_text(encoding="utf-8") == "old"

    shutil.rmtree(tmp_path / desktop_shell.STAGING_OUTPUT_DIR_RELATIVE)
    assert desktop_shell._try_promote_staged_desktop_shell(tmp_path) is False
    assert (live / "main.js").read_text(encoding="utf-8") == "old"


def test_try_promote_staged_desktop_shell_yields_to_running_prebuild(tmp_path, monkeypatch):
    """A live prebuild helper owns the staging tree; promotion must not race it.

    electron-builder's copy order is unspecified, so exe and provenance can be
    visible while the rest of the package is still being written. With the
    helper holding the prebuild lock, promotion must yield (False) and leave
    both the live tree and the staging untouched.
    """

    tree = "a" * 40
    live = _write_live_win_unpacked(tmp_path)
    staged = _write_staged_shell(tmp_path, tree_hash=tree)
    _write_prebuild_lock(tmp_path, pid=99150)
    monkeypatch.setattr(desktop_shell, "_pid_alive", lambda pid: True)
    # The holder predates the lock, so it is the real helper, not a recycled PID.
    monkeypatch.setattr(desktop_shell, "_process_create_time", lambda pid: 0.0)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)

    assert desktop_shell._try_promote_staged_desktop_shell(tmp_path) is False
    assert (live / "main.js").read_text(encoding="utf-8") == "old"
    assert (staged / "main.js").read_text(encoding="utf-8") == "new"
    assert desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()
    assert not (tmp_path / desktop_shell.PREVIOUS_WIN_UNPACKED_RELATIVE).exists()


def test_rebuild_desktop_shell_waits_for_prebuild_then_promotes_without_parallel_package_build(tmp_path, monkeypatch):
    tree = "a" * 40
    live = _write_live_win_unpacked(tmp_path)
    _write_staged_shell(tmp_path, tree_hash=tree)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    monkeypatch.setattr(
        desktop_shell,
        "inspect_desktop_shell",
        lambda root: {"stale": False, "reason": "current", "currentElectronTree": tree},
    )
    attempts = {"count": 0}

    def acquire_after_prebuild_finishes(root, *, lock_relative=desktop_shell.REFRESH_LOCK_RELATIVE):
        assert lock_relative == desktop_shell.PREBUILD_LOCK_RELATIVE
        attempts["count"] += 1
        return attempts["count"] >= 2

    monkeypatch.setattr(desktop_shell, "_acquire_desktop_shell_refresh_lock", acquire_after_prebuild_finishes)
    monkeypatch.setattr(
        desktop_shell,
        "_run_desktop_shell_package_build",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not build beside prebuild")),
        raising=False,
    )
    monkeypatch.setattr(
        desktop_shell.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not build beside prebuild")),
    )
    result = desktop_shell.rebuild_desktop_shell(tmp_path)
    assert result["rebuilt"] is True
    assert result["promotedFromStaging"] is True
    assert attempts["count"] == 2
    assert (live / "main.js").read_text(encoding="utf-8") == "new"


def test_try_promote_staged_desktop_shell_releases_prebuild_lock_on_every_exit(tmp_path, monkeypatch):
    tree = "a" * 40
    lock_path = desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE)
    live = _write_live_win_unpacked(tmp_path)
    # Failure path (staging provenance does not match HEAD).
    _write_staged_shell(tmp_path, tree_hash="b" * 40)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)

    assert desktop_shell._try_promote_staged_desktop_shell(tmp_path) is False
    assert not lock_path.is_file()

    # Success path (matching staging swaps in).
    shutil.rmtree(tmp_path / desktop_shell.STAGING_OUTPUT_DIR_RELATIVE)
    _write_staged_shell(tmp_path, tree_hash=tree)
    assert desktop_shell._try_promote_staged_desktop_shell(tmp_path) is True
    assert (live / "main.js").read_text(encoding="utf-8") == "new"
    assert not lock_path.is_file()
    assert not (tmp_path / desktop_shell.PREVIOUS_WIN_UNPACKED_RELATIVE).exists()


def test_rebuild_desktop_shell_promotes_valid_staging_without_npm(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_live_win_unpacked(tmp_path)
    _write_staged_shell(tmp_path, tree_hash=tree)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    monkeypatch.setattr(
        desktop_shell,
        "inspect_desktop_shell",
        lambda root: {"stale": False, "reason": "current", "currentElectronTree": tree},
    )

    def fail_run(*_args, **_kwargs):
        raise AssertionError("valid staging must be promoted without an npm rebuild")

    monkeypatch.setattr(desktop_shell.subprocess, "run", fail_run)
    result = desktop_shell.rebuild_desktop_shell(tmp_path)
    assert result["rebuilt"] is True
    assert result["promotedFromStaging"] is True
    live = tmp_path / "dist" / "desktop" / "win-unpacked"
    assert (live / "main.js").read_text(encoding="utf-8") == "new"
    assert not (tmp_path / desktop_shell.PREVIOUS_WIN_UNPACKED_RELATIVE).exists()
    assert not (tmp_path / desktop_shell.STAGING_OUTPUT_DIR_RELATIVE).exists()


def test_rebuild_desktop_shell_falls_back_to_npm_when_promoted_still_stale(tmp_path, monkeypatch):
    tree = "a" * 40
    _write_live_win_unpacked(tmp_path)
    _write_staged_shell(tmp_path, tree_hash=tree)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    inspections = {"count": 0}

    def fake_inspect(root):
        inspections["count"] += 1
        if inspections["count"] == 1:
            return {"stale": True, "reason": "frontend_release_mismatch", "currentElectronTree": tree}
        return {"stale": False, "reason": "current", "currentElectronTree": tree}

    monkeypatch.setattr(desktop_shell, "inspect_desktop_shell", fake_inspect)
    _stub_desktop_shell_package_build(monkeypatch, tmp_path, tree_hash=tree)
    result = desktop_shell.rebuild_desktop_shell(tmp_path)
    assert result["rebuilt"] is True
    assert "promotedFromStaging" not in result
    assert inspections["count"] == 2


def test_rebuild_desktop_shell_promote_sharing_violation_falls_back_to_npm(tmp_path, monkeypatch):
    tree = "a" * 40
    live = _write_live_win_unpacked(tmp_path)
    staged = _write_staged_shell(tmp_path, tree_hash=tree)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda root, spec: tree)
    monkeypatch.setattr(
        desktop_shell,
        "inspect_desktop_shell",
        lambda root: {"stale": False, "reason": "current", "currentElectronTree": tree},
    )
    real_rename = os.rename

    def locked_rename(src, dest):
        if Path(src) == staged:
            error = PermissionError(13, "in use", str(src))
            error.winerror = 32
            raise error
        real_rename(src, dest)

    monkeypatch.setattr(desktop_shell, "_rename_dir", locked_rename)
    _stub_desktop_shell_package_build(monkeypatch, tmp_path, tree_hash=tree)
    result = desktop_shell.rebuild_desktop_shell(tmp_path)
    assert result["rebuilt"] is True
    # The staged rename failed without damaging the live tree; the independent
    # package build then replaced it successfully.
    assert (live / "main.js").read_text(encoding="utf-8") == "new"
    assert (staged / "main.js").read_text(encoding="utf-8") == "new"
    assert not (tmp_path / desktop_shell.PREVIOUS_WIN_UNPACKED_RELATIVE).exists()
    # The promotion lock must not outlive the failed promote either.
    assert not desktop_shell._refresh_lock_path(tmp_path, desktop_shell.PREBUILD_LOCK_RELATIVE).is_file()
