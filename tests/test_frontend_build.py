from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import scripts.vibelution_launcher as launcher
from core.launcher import frontend_build, maintenance_reset
from core.launcher.branch_instance_lifecycle import _bundled_frontend_ready
from core.runtime_manager import daemon, hot_restart_backup


def _write_project(root: Path, *, source: str = "export const app = 1;\n") -> Path:
    web = root / "web"
    (web / "src").mkdir(parents=True)
    (web / "node_modules").mkdir()
    (web / "src" / "App.tsx").write_text(source, encoding="utf-8")
    (web / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    (web / "package.json").write_text('{"private":true}', encoding="utf-8")
    (web / "package-lock.json").write_text('{"lockfileVersion":3}', encoding="utf-8")
    (web / "tsconfig.json").write_text('{"compilerOptions":{}}', encoding="utf-8")
    (web / "vite.config.ts").write_text("export default {}", encoding="utf-8")
    return web


def _stub_build_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(frontend_build, "_run_version", lambda _command: "v1")
    monkeypatch.setattr(frontend_build, "_run_version_command", lambda _command: "v1")
    monkeypatch.setattr(
        frontend_build,
        "_capture_git",
        lambda _root, args: "a" * 40 if args[-1] == "HEAD" else "tree-a",
    )


def _release(root: Path, name: str, *, schema: int = 2, key: str = "old") -> Path:
    path = frontend_build.frontend_releases_dir(root) / name
    path.mkdir(parents=True)
    (path / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    (path / "assets").mkdir()
    (path / "assets" / "app.js").write_text("old", encoding="utf-8")
    (path / ".vibelution-build.json").write_text(
        json.dumps({"schemaVersion": schema, "buildKey": key, "frontendTree": "tree-old"}), encoding="utf-8"
    )
    return path


def _activate(root: Path, name: str, *, key: str = "old") -> None:
    path = frontend_build.active_release_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schemaVersion": 2, "release": name, "buildKey": key}), encoding="utf-8")


def _successful_runner(command: list[str], *, cwd: Path, label: str) -> str:
    if label == "vite build":
        stage = Path(command[-1])
        (stage / "assets").mkdir()
        (stage / "assets" / "app.js").write_text("new", encoding="utf-8")
        (stage / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    return "ok"


def test_build_key_tracks_production_inputs_but_not_git_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)

    before = frontend_build.build_inputs(tmp_path)
    changed_audit = {**before, "sourceCommit": "b" * 40, "frontendTree": "tree-b"}
    assert frontend_build.compute_build_key(before) == frontend_build.compute_build_key(changed_audit)

    (tmp_path / "web" / "src" / "App.tsx").write_text("export const app = 2;\n", encoding="utf-8")
    after_source = frontend_build.build_inputs(tmp_path)
    assert frontend_build.compute_build_key(after_source) != frontend_build.compute_build_key(before)

    (tmp_path / "web" / "src" / "App.test.ts").write_text("test('x', () => {})\n", encoding="utf-8")
    after_test = frontend_build.build_inputs(tmp_path)
    assert frontend_build.compute_build_key(after_test) == frontend_build.compute_build_key(after_source)

    (tmp_path / "web" / "package-lock.json").write_text('{"lockfileVersion":4}', encoding="utf-8")
    after_lock = frontend_build.build_inputs(tmp_path)
    assert frontend_build.compute_build_key(after_lock) != frontend_build.compute_build_key(after_test)

    monkeypatch.setenv("VITE_BUILD_SIGNATURE", "one")
    after_vite_environment = frontend_build.build_inputs(tmp_path)
    monkeypatch.setenv("VITE_BUILD_SIGNATURE", "two")
    changed_vite_environment = frontend_build.build_inputs(tmp_path)
    assert frontend_build.compute_build_key(after_vite_environment) != frontend_build.compute_build_key(changed_vite_environment)


def test_schema_one_release_is_not_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    key = frontend_build.compute_build_key(frontend_build.build_inputs(tmp_path))
    _release(tmp_path, "release-old", schema=1, key=key)
    _activate(tmp_path, "release-old", key=key)

    assert frontend_build.inspect_frontend_build(tmp_path)["current"] is False


def test_failed_build_keeps_previous_active_release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")

    def fail_vite(command: list[str], *, cwd: Path, label: str) -> str:
        if label == "vite build":
            raise RuntimeError("vite failed")
        return "ok"

    monkeypatch.setattr(frontend_build, "_run_checked", fail_vite)
    with pytest.raises(RuntimeError, match="vite failed"):
        frontend_build.ensure_frontend_build(tmp_path)

    assert json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))["release"] == "release-old"
    assert frontend_build.resolve_active_frontend_dist(tmp_path).name == "release-old"


def test_publish_switches_only_after_complete_staging_release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)

    result = frontend_build.ensure_frontend_build(tmp_path)

    assert result["rebuilt"] is True
    active = json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))
    assert active["release"] == f"release-{result['buildKey']}"
    active_dist = frontend_build.resolve_active_frontend_dist(tmp_path)
    assert (active_dist / "assets" / "app.js").read_text(encoding="utf-8") == "new"
    assert frontend_build.inspect_frontend_build(tmp_path)["current"] is True


def test_publish_retries_transient_directory_sharing_violation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)
    original_replace = frontend_build.os.replace
    replacement_calls: list[tuple[Path, Path]] = []
    sleep_delays: list[float] = []
    attempts = 0

    def replace_with_transient_sharing_violation(source: Path | str, destination: Path | str) -> None:
        nonlocal attempts
        source_path = Path(source)
        destination_path = Path(destination)
        replacement_calls.append((source_path, destination_path))
        if source_path.name.startswith("stage-") and destination_path.name.startswith("release-"):
            attempts += 1
            if attempts <= 2:
                raise PermissionError("sharing violation")
        original_replace(source, destination)

    monkeypatch.setattr(frontend_build.os, "replace", replace_with_transient_sharing_violation)
    monkeypatch.setattr(frontend_build.time, "sleep", sleep_delays.append)

    result = frontend_build.ensure_frontend_build(tmp_path)

    active = json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))
    release = frontend_build.frontend_releases_dir(tmp_path) / active["release"]
    assert attempts == 3
    assert (release / "assets" / "app.js").read_text(encoding="utf-8") == "new"
    assert active["release"] == f"release-{result['buildKey']}"
    assert sleep_delays == [0.05, 0.1]
    assert max(sleep_delays) <= 0.25
    assert replacement_calls[-1][1] == frontend_build.active_release_path(tmp_path)


def test_publish_permission_timeout_copies_verified_release_before_activating(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)
    original_replace = frontend_build.os.replace
    sleep_delays: list[float] = []
    monkeypatch.setattr(frontend_build, "FRONTEND_PUBLISH_RETRY_TIMEOUT_SECONDS", 0.0)

    def replace_with_persistent_sharing_violation(source: Path | str, destination: Path | str) -> None:
        if Path(source).name.startswith("stage-") and Path(destination).name.startswith("release-"):
            raise PermissionError("sharing violation")
        original_replace(source, destination)

    monkeypatch.setattr(frontend_build.os, "replace", replace_with_persistent_sharing_violation)
    monkeypatch.setattr(frontend_build.time, "sleep", sleep_delays.append)

    result = frontend_build.ensure_frontend_build(tmp_path)

    active = json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))
    copied_release = frontend_build.frontend_releases_dir(tmp_path) / active["release"]
    assert active["release"] == copied_release.name
    assert active["release"].startswith(f"release-{result['buildKey']}-")
    assert (copied_release / "assets" / "app.js").read_text(encoding="utf-8") == "new"
    assert frontend_build._is_complete_release(copied_release, build_key=result["buildKey"])
    assert not any(path.name.startswith("stage-") for path in frontend_build.frontend_releases_dir(tmp_path).iterdir())
    assert sleep_delays == []


def test_publish_copy_failure_keeps_previous_active_release_and_cleans_partial_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)
    monkeypatch.setattr(frontend_build, "FRONTEND_PUBLISH_RETRY_TIMEOUT_SECONDS", 0.0)
    original_copytree = frontend_build.shutil.copytree

    def persistent_sharing_violation(source: Path | str, destination: Path | str) -> None:
        if Path(source).name.startswith("stage-") and Path(destination).name.startswith("release-"):
            raise PermissionError("sharing violation")
        os.replace(source, destination)

    def copy_then_fail(source: Path | str, destination: Path | str, *args: object, **kwargs: object) -> Path:
        original_copytree(source, destination, *args, **kwargs)
        raise RuntimeError("copy failed")

    monkeypatch.setattr(frontend_build.os, "replace", persistent_sharing_violation)
    monkeypatch.setattr(frontend_build.shutil, "copytree", copy_then_fail)

    with pytest.raises(RuntimeError, match="copy failed"):
        frontend_build.ensure_frontend_build(tmp_path)

    active = json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))
    assert active["release"] == "release-old"
    assert not any(path.name.startswith("stage-") for path in frontend_build.frontend_releases_dir(tmp_path).iterdir())
    assert not any(path.name.startswith("release-") and path.name != "release-old" for path in frontend_build.frontend_releases_dir(tmp_path).iterdir())


def test_publish_copy_validation_failure_keeps_previous_active_release_and_cleans_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)
    monkeypatch.setattr(frontend_build, "FRONTEND_PUBLISH_RETRY_TIMEOUT_SECONDS", 0.0)
    original_complete_release = frontend_build._is_complete_release

    def persistent_sharing_violation(source: Path | str, destination: Path | str) -> None:
        if Path(source).name.startswith("stage-") and Path(destination).name.startswith("release-"):
            raise PermissionError("sharing violation")
        os.replace(source, destination)

    def copied_release_is_incomplete(path: Path, *, build_key: str | None = None) -> bool:
        if path.name.startswith("release-") and path.name != "release-old":
            return False
        return original_complete_release(path, build_key=build_key)

    monkeypatch.setattr(frontend_build.os, "replace", persistent_sharing_violation)
    monkeypatch.setattr(frontend_build, "_is_complete_release", copied_release_is_incomplete)

    with pytest.raises(RuntimeError, match="Copied frontend release failed validation"):
        frontend_build.ensure_frontend_build(tmp_path)

    active = json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))
    assert active["release"] == "release-old"
    assert not any(path.name.startswith("stage-") for path in frontend_build.frontend_releases_dir(tmp_path).iterdir())
    assert not any(path.name.startswith("release-") and path.name != "release-old" for path in frontend_build.frontend_releases_dir(tmp_path).iterdir())


def test_publish_non_retryable_os_error_preserves_previous_active_release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)
    original_replace = frontend_build.os.replace
    sleep_delays: list[float] = []

    def replace_with_disk_error(source: Path | str, destination: Path | str) -> None:
        if Path(source).name.startswith("stage-") and Path(destination).name.startswith("release-"):
            raise OSError("disk error")
        original_replace(source, destination)

    monkeypatch.setattr(frontend_build.os, "replace", replace_with_disk_error)
    monkeypatch.setattr(frontend_build.time, "sleep", sleep_delays.append)
    monkeypatch.setattr(frontend_build.shutil, "copytree", lambda *_args, **_kwargs: pytest.fail("copy fallback was invoked"))

    with pytest.raises(OSError, match="disk error"):
        frontend_build.ensure_frontend_build(tmp_path)

    active = json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))
    assert active["release"] == "release-old"
    assert sleep_delays == []


def test_gc_frontend_releases_preserves_active_serving_and_recent_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    now = time.time()
    active = _release(tmp_path, "release-active", key="active")
    serving = _release(tmp_path, "release-serving", key="serving")
    removable = _release(tmp_path, "release-removable", key="removable")
    recent = _release(tmp_path, "release-recent", key="recent")
    _activate(tmp_path, active.name, key="active")
    fingerprint_path = tmp_path / ".runtime" / "running-code-fingerprint.json"
    fingerprint_path.parent.mkdir(parents=True, exist_ok=True)
    fingerprint_path.write_text(
        json.dumps({
            "schemaVersion": 1,
            "servingFrontendRelease": serving.name,
            "pid": 101,
            "createTime": 1.0,
            "executable": "python.exe",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(frontend_build, "inspect_process_identity", lambda _identity: {"status": "match"})
    os.utime(active, (now - 10_000, now - 10_000))
    os.utime(serving, (now - 10_000, now - 10_000))
    os.utime(removable, (now - 10_000, now - 10_000))
    os.utime(recent, (now - 10, now - 10))

    result = frontend_build.gc_frontend_releases(
        tmp_path,
        now=now,
        release_retention_seconds=3600,
        keep_release_count=0,
    )

    assert active.is_dir()
    assert serving.is_dir()
    assert not removable.exists()
    assert recent.is_dir()
    assert removable.name in result["removed"]
    assert active.name in result["skipped"]
    assert serving.name in result["skipped"]


def test_gc_frontend_releases_preserves_all_releases_when_lease_identity_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    now = time.time()
    active = _release(tmp_path, "release-active", key="active")
    serving = _release(tmp_path, "release-serving", key="serving")
    removable = _release(tmp_path, "release-removable", key="removable")
    _activate(tmp_path, active.name, key="active")
    lease_path = frontend_build.serving_frontend_lease_path(
        tmp_path,
        pid=303,
        create_time=3.0,
    )
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text(
        json.dumps({
            "schemaVersion": 1,
            "servingFrontendRelease": serving.name,
            "pid": 303,
            "createTime": 3.0,
            "executable": "python.exe",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(frontend_build, "inspect_process_identity", lambda _identity: {"status": "unknown"})
    for path in (active, serving, removable):
        os.utime(path, (now - 10_000, now - 10_000))

    result = frontend_build.gc_frontend_releases(
        tmp_path,
        now=now,
        release_retention_seconds=3600,
        keep_release_count=0,
    )

    assert result["leaseStatus"] == "unknown"
    assert active.is_dir()
    assert serving.is_dir()
    assert removable.is_dir()
    assert result["removed"] == []


def test_gc_frontend_releases_removes_only_expired_staging_directories(tmp_path: Path) -> None:
    now = time.time()
    old_stage = frontend_build.create_staging_release(tmp_path)
    fresh_stage = frontend_build.create_staging_release(tmp_path)
    os.utime(old_stage, (now - 7200, now - 7200))

    result = frontend_build.gc_frontend_releases(
        tmp_path,
        now=now,
        stage_retention_seconds=3600,
        keep_release_count=0,
    )

    assert not old_stage.exists()
    assert fresh_stage.is_dir()
    assert old_stage.name in result["removed"]
    assert fresh_stage.name in result["skipped"]


def test_damaged_matching_release_is_not_reactivated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    key = frontend_build.compute_build_key(frontend_build.build_inputs(tmp_path))
    damaged = _release(tmp_path, f"release-{key}", key=key)
    (damaged / "assets" / "app.js").unlink()
    _activate(tmp_path, damaged.name, key=key)
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)

    frontend_build.ensure_frontend_build(tmp_path)

    active = json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))
    assert active["release"] != damaged.name
    assert active["release"].startswith(f"release-{key}-")
    assert damaged.is_dir()
    assert (frontend_build.resolve_active_frontend_dist(tmp_path) / "assets" / "app.js").read_text(encoding="utf-8") == "new"


def test_source_change_during_build_does_not_publish_mixed_release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    web = _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")

    def mutate_after_vite(command: list[str], *, cwd: Path, label: str) -> str:
        result = _successful_runner(command, cwd=cwd, label=label)
        if label == "vite build":
            (web / "src" / "App.tsx").write_text("export const app = 99;\n", encoding="utf-8")
        return result

    monkeypatch.setattr(frontend_build, "_run_checked", mutate_after_vite)
    with pytest.raises(RuntimeError, match="inputs changed while building"):
        frontend_build.ensure_frontend_build(tmp_path)

    assert json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))["release"] == "release-old"


def test_save_and_revert_during_build_does_not_publish_transient_release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    web = _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    source = web / "src" / "App.tsx"
    original = source.read_text(encoding="utf-8")
    original_mtime = source.stat().st_mtime_ns

    def save_and_revert_after_vite(command: list[str], *, cwd: Path, label: str) -> str:
        result = _successful_runner(command, cwd=cwd, label=label)
        if label == "vite build":
            source.write_text("export const app = 'transient';\n", encoding="utf-8")
            source.write_text(original, encoding="utf-8")
            os.utime(source, ns=(original_mtime + 1_000_000_000, original_mtime + 1_000_000_000))
        return result

    monkeypatch.setattr(frontend_build, "_run_checked", save_and_revert_after_vite)
    with pytest.raises(RuntimeError, match="inputs changed while building"):
        frontend_build.ensure_frontend_build(tmp_path)

    assert json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))["release"] == "release-old"


def test_pointer_rejects_path_escape(tmp_path: Path) -> None:
    _write_project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.html").write_text("outside", encoding="utf-8")
    pointer = frontend_build.active_release_path(tmp_path)
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"release": "../outside"}), encoding="utf-8")

    assert frontend_build.resolve_active_frontend_dist(tmp_path) == tmp_path / "web" / "dist"


def test_branch_instance_readiness_uses_the_active_release(tmp_path: Path) -> None:
    _write_project(tmp_path)
    _release(tmp_path, "release-active")
    _activate(tmp_path, "release-active")

    assert _bundled_frontend_ready({"path": str(tmp_path)}) is True


def test_hot_restart_backup_includes_the_active_release_directory() -> None:
    assert "web/.vibelution-builds" in hot_restart_backup.BACKUP_TARGETS


def test_stale_build_lock_is_reclaimed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lock = frontend_build.frontend_build_lock_path(tmp_path)
    lock.mkdir(parents=True)
    (lock / "holder.json").write_text(json.dumps({"pid": 123}), encoding="utf-8")
    monkeypatch.setattr(frontend_build, "_pid_is_alive", lambda _pid: False)

    with frontend_build.frontend_build_lock(tmp_path) as acquired:
        assert acquired["waited"] is True
        assert lock.is_dir()
    assert not lock.exists()


def test_build_lock_reclaims_an_unfinished_directory_only_after_grace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(frontend_build, "LOCK_INITIALIZATION_GRACE_SECONDS", 0.0)
    lock = frontend_build.frontend_build_lock_path(tmp_path)
    lock.mkdir(parents=True)

    with frontend_build.frontend_build_lock(tmp_path) as acquired:
        holder = json.loads((lock / "holder.json").read_text(encoding="utf-8"))
        assert acquired["waited"] is True
        assert holder["pid"] == os.getpid()
    assert not lock.exists()


def test_build_lock_does_not_remove_a_replacement_owner_on_release(tmp_path: Path) -> None:
    lock = frontend_build.frontend_build_lock_path(tmp_path)
    with frontend_build.frontend_build_lock(tmp_path):
        original = json.loads((lock / "holder.json").read_text(encoding="utf-8"))
        assert original["token"]
        shutil.rmtree(lock)
        lock.mkdir()
        (lock / "holder.json").write_text(
            json.dumps({"pid": os.getpid(), "startedAt": time.time(), "token": "replacement"}),
            encoding="utf-8",
        )
    assert lock.is_dir()
    shutil.rmtree(lock)


def test_missing_compiler_entries_trigger_dependency_recovery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    calls: list[str] = []

    def runner(command: list[str], *, cwd: Path, label: str) -> str:
        calls.append(label)
        return _successful_runner(command, cwd=cwd, label=label)

    monkeypatch.setattr(frontend_build, "_node_command", lambda: "node")
    monkeypatch.setattr(frontend_build, "_npm_cli", lambda _node: "npm-cli.js")
    monkeypatch.setattr(frontend_build, "_run_checked", runner)

    frontend_build.ensure_frontend_build(tmp_path)

    assert calls == ["node npm-cli.js ci", "tsc -b", "vite build"]


def test_checked_build_timeout_terminates_the_owned_process_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class TimedOutProcess:
        returncode: int | None = None

        def communicate(self, *, timeout: float) -> tuple[str, str]:
            assert timeout == 900
            raise subprocess.TimeoutExpired(["node", "tsc", "-b"], timeout)

    process = TimedOutProcess()
    terminated: list[object] = []
    monkeypatch.setattr(frontend_build.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(frontend_build, "terminate_process_tree", lambda candidate: terminated.append(candidate))

    with pytest.raises(RuntimeError, match=r"tsc -b failed: TimeoutExpired"):
        frontend_build._run_checked(["node", "tsc", "-b"], cwd=tmp_path, label="tsc -b")

    assert terminated == [process]


def test_maintenance_reset_treats_active_releases_as_rebuildable_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "web" / ".vibelution-builds" / "release-key").mkdir(parents=True)
    monkeypatch.setattr(maintenance_reset, "PROJECT_ROOT", tmp_path)

    candidates = maintenance_reset._collect_web_dist()

    assert {candidate.path for candidate in candidates} == {
        tmp_path / "web" / "dist",
        tmp_path / "web" / ".vibelution-builds",
    }
    releases = next(candidate for candidate in candidates if candidate.path.name == ".vibelution-builds")
    assert releases.missing is False


def test_python_launcher_and_runtime_manager_delegate_to_the_shared_builder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[Path, str | None]] = []

    def fake_ensure(root: Path, *, package_manager: str | None = None) -> dict[str, object]:
        calls.append((Path(root), package_manager))
        return {
            "skipped": True,
            "rebuilt": False,
            "buildKey": "key-1",
            "dist": str(tmp_path / "release-key-1"),
            "provenance": {"schemaVersion": 2, "buildKey": "key-1"},
        }

    monkeypatch.setattr(frontend_build, "ensure_frontend_build", fake_ensure)
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        launcher,
        "_runtime_source_identity",
        lambda: {"projectRoot": str(tmp_path), "branch": "main", "commit": "a" * 40, "frontendTree": "tree"},
    )
    monkeypatch.setattr(launcher, "_assert_runtime_source_identity", lambda identity: identity)
    launcher_result = launcher._ensure_frontend_build()

    monkeypatch.setattr(daemon, "PROJECT_ROOT", tmp_path)
    events: list[str] = []
    monkeypatch.setattr(daemon, "_append_event", lambda event, payload: events.append(event))
    runtime_result = daemon._preflight_frontend_build_for_restart("command-1")
    explicit_root = tmp_path / "explicit-root"
    explicit_root_result = daemon._preflight_frontend_build_for_restart("command-2", project_root=explicit_root)

    assert launcher_result["buildKey"] == "key-1"
    assert runtime_result["skipped"] is True
    assert explicit_root_result["skipped"] is True
    assert calls == [(tmp_path, "npm"), (tmp_path, None), (explicit_root.resolve(), None)]
    assert events == [
        "workbench.restart.build_preflight_skipped_current",
        "workbench.restart.build_preflight_skipped_current",
    ]


# --- governed runtime home migration for serving-frontend leases ---

def _governed_frontend_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a fully migrated governed project; return (root, runtime_home)."""
    from vibelution_storage import (
        PROJECTS_HOME_ENV,
        resolve_project_storage_paths,
        storage_migration_state_path,
    )

    projects_home = tmp_path / "projects-home"
    project_root = tmp_path / "checkout"
    project_root.mkdir(parents=True)
    identity = project_root / ".vibelution" / "project.json"
    identity.parent.mkdir(parents=True)
    identity.write_text(json.dumps({"schemaVersion": 1, "projectId": "leases-project"}), encoding="utf-8")
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    target = resolve_project_storage_paths(project_root, projects_home=projects_home)
    marker = storage_migration_state_path(target)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "completed",
                "projectId": target.project_id,
                "instanceId": target.instance_id,
            }
        ),
        encoding="utf-8",
    )
    return project_root, target.runtime


def test_serving_leases_dir_follows_governed_runtime_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root, runtime_home = _governed_frontend_project(tmp_path, monkeypatch)
    assert frontend_build.serving_frontend_leases_dir(project_root) == (
        runtime_home / frontend_build.SERVING_FRONTEND_LEASES_DIR_NAME
    )
    # Pre-governance checkouts keep resolving to checkout .runtime.
    legacy_root = tmp_path / "legacy-checkout"
    legacy_root.mkdir()
    assert frontend_build.serving_frontend_leases_dir(legacy_root) == (
        legacy_root / ".runtime" / frontend_build.SERVING_FRONTEND_LEASES_DIR_NAME
    )


def test_gc_scans_legacy_lease_dir_and_never_deletes_fingerprints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = time.time()
    project_root, runtime_home = _governed_frontend_project(tmp_path, monkeypatch)
    active = _release(project_root, "release-active", key="active")
    served_from_governed = _release(project_root, "release-governed", key="governed")
    served_from_legacy = _release(project_root, "release-legacy", key="legacy")
    removable = _release(project_root, "release-removable", key="removable")
    _activate(project_root, active.name, key="active")

    governed_lease = frontend_build.serving_frontend_lease_path(
        project_root, pid=404, create_time=4.0
    )
    governed_lease.parent.mkdir(parents=True, exist_ok=True)
    governed_lease.write_text(
        json.dumps({
            "schemaVersion": 1,
            "servingFrontendRelease": served_from_governed.name,
            "pid": 404,
            "createTime": 4.0,
            "executable": "python.exe",
        }),
        encoding="utf-8",
    )
    legacy_lease = (
        project_root / ".runtime" / frontend_build.SERVING_FRONTEND_LEASES_DIR_NAME / "lease-505-5000.json"
    )
    legacy_lease.parent.mkdir(parents=True)
    legacy_lease.write_text(
        json.dumps({
            "schemaVersion": 1,
            "servingFrontendRelease": served_from_legacy.name,
            "pid": 505,
            "createTime": 5.0,
            "executable": "python.exe",
        }),
        encoding="utf-8",
    )
    # Both fingerprint copies carry a verifiable live backend identity so the
    # scan stays in the "verified" branch; GC must still never delete them.
    governed_fingerprint = runtime_home / "running-code-fingerprint.json"
    governed_fingerprint.parent.mkdir(parents=True, exist_ok=True)
    governed_fingerprint.write_text(
        json.dumps({
            "schemaVersion": 1,
            "servingFrontendRelease": active.name,
            "pid": 404,
            "createTime": 4.0,
            "executable": "python.exe",
        }),
        encoding="utf-8",
    )
    legacy_fingerprint = project_root / ".runtime" / "running-code-fingerprint.json"
    legacy_fingerprint.write_text(
        json.dumps({
            "schemaVersion": 1,
            "servingFrontendRelease": served_from_legacy.name,
            "pid": 505,
            "createTime": 5.0,
            "executable": "python.exe",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(frontend_build, "inspect_process_identity", lambda _identity: {"status": "match"})
    os.utime(removable, (now - 10_000, now - 10_000))

    result = frontend_build.gc_frontend_releases(
        project_root,
        now=now,
        release_retention_seconds=3600,
        keep_release_count=0,
    )

    # A lease left behind at the pre-migration location still protects its
    # release from deletion.
    assert result["leaseStatus"] == "verified"
    assert served_from_legacy.is_dir()
    assert served_from_governed.is_dir()
    assert active.is_dir()
    assert not removable.exists()
    # Fingerprint copies are never treated as GC-managed leases.
    assert governed_fingerprint.is_file()
    assert legacy_fingerprint.is_file()
