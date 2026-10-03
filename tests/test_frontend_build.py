from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import psutil
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


def test_build_inputs_scans_once_and_detects_added_changed_and_removed_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    web = _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    original_scan = frontend_build._production_input_paths
    scan_count = 0

    def count_scans(web_dir: Path) -> list[Path]:
        nonlocal scan_count
        scan_count += 1
        return original_scan(web_dir)

    monkeypatch.setattr(frontend_build, "_production_input_paths", count_scans)

    initial = frontend_build.build_inputs(tmp_path)
    assert scan_count == 1

    app = web / "src" / "App.tsx"
    app.write_text("export const app = 2;\n", encoding="utf-8")
    changed = frontend_build.build_inputs(tmp_path)
    assert scan_count == 2
    assert changed["productionInputDigest"] != initial["productionInputDigest"]
    assert frontend_build.compute_build_key(changed) != frontend_build.compute_build_key(initial)

    added_file = web / "src" / "NewModule.ts"
    added_file.write_text("export const value = 1;\n", encoding="utf-8")
    added = frontend_build.build_inputs(tmp_path)
    assert scan_count == 3
    assert added["productionInputCount"] == changed["productionInputCount"] + 1
    assert frontend_build.compute_build_key(added) != frontend_build.compute_build_key(changed)

    added_file.unlink()
    removed = frontend_build.build_inputs(tmp_path)
    assert scan_count == 4
    assert removed["productionInputCount"] == changed["productionInputCount"]
    assert frontend_build.compute_build_key(removed) == frontend_build.compute_build_key(changed)


def test_build_inputs_caches_commit_tree_but_rescans_working_files(monkeypatch, tmp_path):
    web = _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    monkeypatch.setattr(frontend_build, "_FRONTEND_TREE_CACHE", {})
    calls = []
    commit = "a" * 40
    tree = "b" * 40

    def capture_git(_root, args):
        calls.append(args)
        if args == ["rev-parse", "HEAD"]:
            return commit
        assert args == ["rev-parse", f"{commit}:web"]
        return tree

    monkeypatch.setattr(frontend_build, "_capture_git", capture_git)
    initial = frontend_build.build_inputs(tmp_path)
    cached = frontend_build.build_inputs(tmp_path)
    (web / "src" / "App.tsx").write_text("export const app = 99;\n", encoding="utf-8")
    changed = frontend_build.build_inputs(tmp_path)

    assert cached == initial
    assert changed["sourceCommit"] == commit
    assert changed["frontendTree"] == tree
    assert frontend_build.compute_build_key(changed) != frontend_build.compute_build_key(initial)
    assert changed["productionInputStateDigest"] != initial["productionInputStateDigest"]
    assert calls.count(["rev-parse", "HEAD"]) == 3
    assert calls.count(["rev-parse", f"{commit}:web"]) == 1


@pytest.mark.parametrize("object_id_length", [40, 64])
def test_commit_tree_cache_is_bound_to_checkout_and_pinned_commit(monkeypatch, tmp_path, object_id_length):
    monkeypatch.setattr(frontend_build, "_FRONTEND_TREE_CACHE", {})
    first_commit = "a" * object_id_length
    second_commit = "b" * object_id_length
    calls = []

    def capture_git(root, args):
        calls.append((root, args))
        assert args[0] == "rev-parse"
        assert args[1] in {f"{first_commit}:web", f"{second_commit}:web"}
        return ("c" if args[1].startswith(first_commit) else "d") * object_id_length

    monkeypatch.setattr(frontend_build, "_capture_git", capture_git)
    other_checkout = tmp_path / "other"
    assert frontend_build._frontend_tree_for_commit(tmp_path, first_commit) == "c" * object_id_length
    assert frontend_build._frontend_tree_for_commit(tmp_path, first_commit) == "c" * object_id_length
    assert frontend_build._frontend_tree_for_commit(tmp_path, second_commit) == "d" * object_id_length
    assert frontend_build._frontend_tree_for_commit(other_checkout, first_commit) == "c" * object_id_length
    assert len(calls) == 3


@pytest.mark.parametrize("failed_lookup", ["", "unavailable"])
def test_commit_tree_lookup_retries_failures_without_caching(monkeypatch, tmp_path, failed_lookup):
    monkeypatch.setattr(frontend_build, "_FRONTEND_TREE_CACHE", {})
    results = iter([failed_lookup, "b" * 40])
    calls = []

    def capture_git(_root, args):
        calls.append(args)
        return next(results)

    monkeypatch.setattr(frontend_build, "_capture_git", capture_git)
    assert frontend_build._frontend_tree_for_commit(tmp_path, "a" * 40) == failed_lookup
    assert frontend_build._frontend_tree_for_commit(tmp_path, "a" * 40) == "b" * 40
    assert frontend_build._frontend_tree_for_commit(tmp_path, "a" * 40) == "b" * 40
    assert len(calls) == 2


def test_commit_tree_cache_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(frontend_build, "_FRONTEND_TREE_CACHE", {})
    monkeypatch.setattr(frontend_build, "_FRONTEND_TREE_CACHE_LIMIT", 2)
    monkeypatch.setattr(frontend_build, "_capture_git", lambda root, args: "a" * 40)
    for index in range(3):
        frontend_build._frontend_tree_for_commit(tmp_path, f"{index:040x}")
    assert len(frontend_build._FRONTEND_TREE_CACHE) == 2


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
    assert active["release"] == f"release-{result['buildKey'][:16]}"
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
    assert active["release"] == f"release-{result['buildKey'][:16]}"
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
    assert active["release"].startswith(f"release-{result['buildKey'][:16]}-")
    assert (copied_release / "assets" / "app.js").read_text(encoding="utf-8") == "new"
    assert frontend_build._is_complete_release(copied_release, build_key=result["buildKey"])
    assert not any(path.name.startswith("stage-") for path in frontend_build.frontend_releases_dir(tmp_path).iterdir())
    assert sleep_delays == []


def test_publish_release_names_fit_the_staging_path_budget(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)
    monkeypatch.setattr(frontend_build, "FRONTEND_PUBLISH_RETRY_TIMEOUT_SECONDS", 0.0)
    original_replace = frontend_build.os.replace
    original_copytree = frontend_build.shutil.copytree

    def sharing_violation(source, destination):
        if Path(source).name.startswith("stage-"):
            raise PermissionError("sharing violation")
        return original_replace(source, destination)

    def bounded_copy(source, destination, *args, **kwargs):
        # Assets that fit in staging must not exceed MAX_PATH during fallback.
        assert len(Path(destination).name) <= len(Path(source).name)
        return original_copytree(source, destination, *args, **kwargs)

    monkeypatch.setattr(frontend_build.os, "replace", sharing_violation)
    monkeypatch.setattr(frontend_build.shutil, "copytree", bounded_copy)
    result = frontend_build.ensure_frontend_build(tmp_path)
    assert frontend_build._is_complete_release(Path(result["dist"]), build_key=result["buildKey"])


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
    damaged = _release(tmp_path, f"release-{key[:16]}", key=key)
    (damaged / "assets" / "app.js").unlink()
    _activate(tmp_path, damaged.name, key=key)
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)

    frontend_build.ensure_frontend_build(tmp_path)

    active = json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))
    assert active["release"] != damaged.name
    assert active["release"].startswith(f"release-{key[:16]}-")
    assert damaged.is_dir()
    assert (frontend_build.resolve_active_frontend_dist(tmp_path) / "assets" / "app.js").read_text(encoding="utf-8") == "new"


def test_release_prefix_collision_preserves_existing_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    key = frontend_build.compute_build_key(frontend_build.build_inputs(tmp_path))
    other_key = key[:16] + ("0" if key[16] != "0" else "1") + key[17:]
    existing = _release(tmp_path, f"release-{key[:16]}", key=other_key)
    _activate(tmp_path, existing.name, key=other_key)
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)

    result = frontend_build.ensure_frontend_build(tmp_path)

    assert Path(result["dist"]) != existing
    assert (existing / "assets" / "app.js").read_text(encoding="utf-8") == "old"
    assert frontend_build._is_complete_release(Path(result["dist"]), build_key=key)


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


@pytest.mark.parametrize("has_holder", [True, False])
def test_stale_lock_cleanup_failure_respects_wait_budget(monkeypatch, tmp_path, has_holder):
    lock = frontend_build.frontend_build_lock_path(tmp_path)
    lock.mkdir(parents=True)
    if has_holder:
        (lock / "holder.json").write_text(json.dumps({"pid": 123}), encoding="utf-8")
    os.utime(lock, (0, 0))
    monkeypatch.setattr(frontend_build, "_pid_is_alive", lambda _pid: False)
    clock = [0.0]
    sleeps = []
    cleanup_attempts = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    def reject_cleanup(path, *args, **kwargs):
        assert path == lock
        cleanup_attempts.append(path)
        # Also bound the regression itself if the retry loop ignores its clock.
        assert len(cleanup_attempts) <= 4, "stale-lock cleanup spun without waiting"
        raise PermissionError("lock directory is temporarily busy")

    monkeypatch.setattr(frontend_build.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(frontend_build.time, "sleep", sleep)
    monkeypatch.setattr(frontend_build.shutil, "rmtree", reject_cleanup)
    with pytest.raises(TimeoutError, match="frontend build lock"):
        with frontend_build.frontend_build_lock(tmp_path, timeout_seconds=0.2):
            pytest.fail("a busy stale lock must not be acquired")
    assert len(sleeps) >= 2
    assert cleanup_attempts
    assert lock.is_dir()


def test_stale_build_lock_is_reclaimed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lock = frontend_build.frontend_build_lock_path(tmp_path)
    lock.mkdir(parents=True)
    (lock / "holder.json").write_text(json.dumps({"pid": 123}), encoding="utf-8")
    monkeypatch.setattr(frontend_build, "_pid_is_alive", lambda _pid: False)

    with frontend_build.frontend_build_lock(tmp_path) as acquired:
        assert acquired["waited"] is True
        assert lock.is_dir()
    assert not lock.exists()


def _terminated_child_pid() -> int:
    hidden = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden,
    )
    process.terminate()
    process.wait(timeout=15)
    return process.pid


def test_pid_is_alive_reports_the_current_process() -> None:
    assert frontend_build._pid_is_alive(os.getpid()) is True


def test_pid_is_alive_reports_a_terminated_process_as_dead() -> None:
    assert frontend_build._pid_is_alive(_terminated_child_pid()) is False


def test_pid_is_alive_rejects_non_positive_pids() -> None:
    assert frontend_build._pid_is_alive(0) is False
    assert frontend_build._pid_is_alive(-1) is False


def test_stale_lock_with_a_dead_holder_pid_is_reclaimed_by_the_real_probe(tmp_path: Path) -> None:
    dead_pid = _terminated_child_pid()
    lock = frontend_build.frontend_build_lock_path(tmp_path)
    lock.mkdir(parents=True)
    (lock / "holder.json").write_text(json.dumps({"pid": dead_pid}), encoding="utf-8")

    with frontend_build.frontend_build_lock(tmp_path) as acquired:
        assert acquired["waited"] is True
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


def test_successful_build_retries_transient_lock_release_before_next_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    web = _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    (web / "node_modules" / "typescript" / "bin").mkdir(parents=True)
    (web / "node_modules" / "typescript" / "bin" / "tsc").write_text("", encoding="utf-8")
    (web / "node_modules" / "vite" / "bin").mkdir(parents=True)
    (web / "node_modules" / "vite" / "bin" / "vite.js").write_text("", encoding="utf-8")
    monkeypatch.setattr(frontend_build, "_node_command", lambda: "node")
    monkeypatch.setattr(frontend_build, "_npm_cli", lambda _node: "npm-cli.js")
    monkeypatch.setattr(frontend_build, "_run_checked", _successful_runner)

    original_release = frontend_build._release_build_lock
    release_calls: list[tuple[Path, str]] = []

    def transient_release_failure(path: Path, token: str) -> bool:
        release_calls.append((path, token))
        if len(release_calls) == 1:
            return False
        return original_release(path, token)

    monkeypatch.setattr(frontend_build, "_release_build_lock", transient_release_failure)
    key = frontend_build._pending_build_cleanup_key(tmp_path)
    lock_dir = frontend_build.frontend_build_lock_path(tmp_path)
    try:
        first = frontend_build.ensure_frontend_build(tmp_path, lock_timeout_seconds=0.0)

        assert first["rebuilt"] is True
        published_pointer = json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))
        assert published_pointer["release"] != "release-old"
        pending = frontend_build._PENDING_BUILD_CLEANUPS[key]
        assert pending["owner"] is None
        assert pending["stage"] is None
        assert pending["lockToken"] == release_calls[0][1]
        assert lock_dir.is_dir()

        second = frontend_build.ensure_frontend_build(tmp_path, lock_timeout_seconds=0.0)

        assert second["rebuilt"] is False
        assert second["skipped"] is True
        assert frontend_build._PENDING_BUILD_CLEANUPS.get(key) is None
        assert not lock_dir.exists()
        assert json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8")) == published_pointer
        assert len(release_calls) == 3
    finally:
        with frontend_build._PENDING_BUILD_CLEANUPS_LOCK:
            leftovers = frontend_build._PENDING_BUILD_CLEANUPS.pop(key, None)
        if leftovers is not None:
            frontend_build._release_build_lock(leftovers["lockPath"], leftovers["lockToken"])


def test_pending_build_lock_cleanup_preserves_a_replacement_owner(tmp_path: Path) -> None:
    lock_dir = frontend_build.frontend_build_lock_path(tmp_path)
    key = frontend_build._pending_build_cleanup_key(tmp_path)
    try:
        with frontend_build.frontend_build_lock(tmp_path) as lock_state:
            original_token = lock_state["token"]
            frontend_build._retain_pending_build_cleanup(
                tmp_path,
                lock_state,
                stage=None,
                owner=None,
            )

        shutil.rmtree(lock_dir)
        lock_dir.mkdir()
        (lock_dir / "holder.json").write_text(
            json.dumps({"pid": os.getpid(), "startedAt": time.time(), "token": "replacement"}),
            encoding="utf-8",
        )

        frontend_build._retry_pending_build_cleanup(tmp_path, timeout_seconds=1.0)

        replacement = json.loads((lock_dir / "holder.json").read_text(encoding="utf-8"))
        assert original_token != replacement["token"]
        assert replacement["token"] == "replacement"
        assert lock_dir.is_dir()
        assert key not in frontend_build._PENDING_BUILD_CLEANUPS
    finally:
        with frontend_build._PENDING_BUILD_CLEANUPS_LOCK:
            frontend_build._PENDING_BUILD_CLEANUPS.pop(key, None)
        if lock_dir.exists():
            shutil.rmtree(lock_dir)


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
        stdin = stdout = stderr = None

        def wait(self, *, timeout: float) -> None:
            assert 0 < timeout <= frontend_build.FRONTEND_BUILD_TIMEOUT_SECONDS
            raise subprocess.TimeoutExpired(["node", "tsc", "-b"], timeout)

        def poll(self) -> int | None:
            return self.returncode

    class TimedOutOwner:
        def __init__(self, process: TimedOutProcess) -> None:
            self.process = process
            self.terminated: list[float] = []
            self.closed: list[float] = []

        def terminate(self, *, timeout: float) -> bool:
            self.terminated.append(timeout)
            self.process.returncode = -1
            return True

        def close(self, *, timeout: float) -> None:
            self.closed.append(timeout)

    process = TimedOutProcess()
    owner = TimedOutOwner(process)
    monkeypatch.setattr(frontend_build.OwnedProcess, "spawn", lambda *args, **kwargs: owner)

    with pytest.raises(RuntimeError, match=r"tsc -b failed: TimeoutExpired"):
        frontend_build._run_checked(["node", "tsc", "-b"], cwd=tmp_path, label="tsc -b")

    assert len(owner.terminated) == 1
    assert len(owner.closed) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment")
def test_checked_build_retires_child_after_root_exits_with_inherited_pipe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "child.pid"
    parent_script = tmp_path / "spawn_child_then_exit.py"
    parent_script.write_text(
        "import subprocess,sys\n"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])\n"
        "open(sys.argv[1],'w',encoding='ascii').write(str(p.pid))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(frontend_build, "FRONTEND_BUILD_TIMEOUT_SECONDS", 2.0)
    owners: list[frontend_build.OwnedProcess] = []
    original_spawn = frontend_build.OwnedProcess.spawn

    def capture_owner(*args: object, **kwargs: object) -> frontend_build.OwnedProcess:
        owner = original_spawn(*args, **kwargs)
        owners.append(owner)
        return owner

    monkeypatch.setattr(frontend_build.OwnedProcess, "spawn", capture_owner)
    original_retire = frontend_build._retire_build_process
    retirement_observations: list[dict[str, object]] = []

    def observe_retirement(
        owner: frontend_build.OwnedProcess | None,
        readers: list[threading.Thread],
        *,
        timeout: float,
    ) -> bool:
        job = owner._job if owner is not None else None
        active_before = job.active_count() if job is not None else None
        retired = original_retire(owner, readers, timeout=timeout)
        try:
            active_after = job.active_count() if job is not None else None
        except OSError as exc:
            active_after = f"{type(exc).__name__}: {exc}"
        retirement_observations.append({
            "retired": retired,
            "jobActiveBefore": active_before,
            "jobActiveAfter": active_after,
            "jobHandleClosed": job is not None and job._handle is None,
            "rootReturnCode": owner.process.poll() if owner is not None else None,
            "timeout": timeout,
        })
        return retired

    monkeypatch.setattr(frontend_build, "_retire_build_process", observe_retirement)
    errors: list[BaseException] = []

    def run_build_command() -> None:
        try:
            frontend_build._run_checked(
                [sys.executable, str(parent_script), str(pid_file)],
                cwd=tmp_path,
                label="tsc -b",
            )
        except BaseException as exc:
            errors.append(exc)

    runner = threading.Thread(target=run_build_command, name="frontend-build-test-runner", daemon=True)
    child_pid: int | None = None
    try:
        runner.start()
        deadline = time.monotonic() + 8.0
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pid_file.exists(), "root process did not start its child"
        child_pid = int(pid_file.read_text(encoding="ascii"))
        child = psutil.Process(child_pid)
        child_created_at = child.create_time()
        child_status_before = child.status()
        assert owners, "OwnedProcess was not created"
        root = owners[0].process
        while root.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert root.returncode == 0, "test root must exit before its child"
        assert owners[0]._job is not None, "Windows Job Object must own the child"
        assert psutil.pid_exists(child_pid), "child should still be alive while keeping the output pipe open"

        runner.join(timeout=8.0)
        assert not runner.is_alive(), "build command did not finish after its shared deadline"
        assert len(errors) == 1 and "TimeoutExpired" in str(errors[0])
        final_child: dict[str, object] | None = None
        retirement_check_started = time.monotonic()
        process_deadline = time.monotonic() + 2.0
        while time.monotonic() < process_deadline:
            try:
                current_child = psutil.Process(child_pid)
                current_created_at = current_child.create_time()
                final_child = {
                    "pid": child_pid,
                    "createTime": current_created_at,
                    "status": current_child.status(),
                    "sameProcess": current_created_at == child_created_at,
                }
                if current_created_at != child_created_at:
                    break
            except psutil.NoSuchProcess:
                final_child = None
                break
            time.sleep(0.02)
        retirement_check_seconds = time.monotonic() - retirement_check_started
        assert retirement_observations and retirement_observations[0]["retired"] is True, (
            f"Job retirement failed: {retirement_observations}"
        )
        job_active_before = retirement_observations[0]["jobActiveBefore"]
        assert isinstance(job_active_before, int) and job_active_before >= 1, (
            f"the child was not contained by the expected Job: {retirement_observations}"
        )
        assert retirement_observations[0]["jobActiveAfter"] == 0
        assert retirement_observations[0]["jobHandleClosed"] is True
        assert not (final_child and final_child["sameProcess"]), (
            "the Windows Job must retire the inherited-pipe child; "
            f"before={{'pid': {child_pid}, 'createTime': {child_created_at}, 'status': {child_status_before}}}, "
            f"after={final_child}, retirement={retirement_observations}, "
            f"waited={retirement_check_seconds:.3f}s"
        )
        assert not any(
            thread.name.startswith("frontend-build-output-") and thread.is_alive()
            for thread in threading.enumerate()
        )
    finally:
        readers = list(getattr(errors[-1], "readers", []) or []) if errors else []
        if owners and not owners[0].process._handle.closed:
            frontend_build._retire_build_process(owners[0], readers, timeout=5.0)
        if runner.is_alive():
            runner.join(timeout=8.0)
        if child_pid is not None and psutil.pid_exists(child_pid):
            try:
                child = psutil.Process(child_pid)
                child.kill()
                psutil.wait_procs([child], timeout=3.0)
            except psutil.Error:
                pass


def test_pending_build_cleanup_keeps_stage_and_lock_until_next_call_retries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    web = tmp_path / "web"
    (web / "node_modules" / "typescript" / "bin").mkdir(parents=True)
    (web / "node_modules" / "typescript" / "bin" / "tsc").write_text("", encoding="utf-8")
    (web / "node_modules" / "vite" / "bin").mkdir(parents=True)
    (web / "node_modules" / "vite" / "bin" / "vite.js").write_text("", encoding="utf-8")
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    monkeypatch.setattr(frontend_build, "_node_command", lambda: "node")
    monkeypatch.setattr(frontend_build, "FRONTEND_BUILD_TIMEOUT_SECONDS", 5.0)

    events: list[str] = []
    clock: list[float] | None = None
    observed_deadlines: list[float | None] = []

    class RetryOwner:
        def __init__(self) -> None:
            self.process = type("Process", (), {"stdin": None, "stdout": None, "stderr": None})()

        def terminate(self, *, timeout: float) -> bool:
            events.append("cleanup")
            if clock is not None:
                clock[0] += 2.0
            return True

        def close(self, *, timeout: float) -> None:
            events.append("owner-closed")

    owner = RetryOwner()
    first_command = True

    def runner(command: list[str], *, cwd: Path, label: str) -> str:
        nonlocal first_command
        events.append(label)
        observed_deadlines.append(frontend_build._FRONTEND_BUILD_DEADLINE.get())
        if first_command:
            first_command = False
            raise frontend_build._PendingBuildCleanupError(
                "synthetic unconfirmed process cleanup",
                owner=owner,  # type: ignore[arg-type]
                readers=[],
            )
        return _successful_runner(command, cwd=cwd, label=label)

    monkeypatch.setattr(frontend_build, "_run_checked", runner)
    key = frontend_build._pending_build_cleanup_key(tmp_path)
    lock_timeouts: list[float] = []
    try:
        with pytest.raises(frontend_build._PendingBuildCleanupError):
            frontend_build.ensure_frontend_build(tmp_path)

        entry = frontend_build._PENDING_BUILD_CLEANUPS[key]
        stage = entry["stage"]
        lock_dir = frontend_build.frontend_build_lock_path(tmp_path)
        assert isinstance(stage, Path) and stage.is_dir()
        assert lock_dir.is_dir()
        assert json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))["release"] == "release-old"

        original_lock = frontend_build.frontend_build_lock

        def record_lock(*args: object, **kwargs: object):
            events.append("lock")
            lock_timeouts.append(float(kwargs["timeout_seconds"]))
            return original_lock(*args, **kwargs)

        monkeypatch.setattr(frontend_build, "frontend_build_lock", record_lock)
        events.clear()
        observed_deadlines.clear()
        clock = [100.0]
        monkeypatch.setattr(frontend_build.time, "monotonic", lambda: clock[0])
        result = frontend_build.ensure_frontend_build(tmp_path)
        assert events[:3] == ["cleanup", "owner-closed", "lock"]
        assert lock_timeouts == [3.0]
        assert observed_deadlines == [105.0, 105.0]
        assert result["rebuilt"] is True
        assert not stage.exists()
        assert not lock_dir.exists()
        assert key not in frontend_build._PENDING_BUILD_CLEANUPS
        assert json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))["release"] != "release-old"
    finally:
        with frontend_build._PENDING_BUILD_CLEANUPS_LOCK:
            leftovers = frontend_build._PENDING_BUILD_CLEANUPS.pop(key, None)
        if leftovers is not None:
            frontend_build._retire_build_process(leftovers.get("owner"), leftovers.get("readers") or [], timeout=5.0)
            leftover_stage = leftovers.get("stage")
            if isinstance(leftover_stage, Path):
                shutil.rmtree(leftover_stage, ignore_errors=True)
            frontend_build._release_build_lock(leftovers["lockPath"], leftovers["lockToken"])


def test_frontend_build_deadline_covers_lock_install_and_both_build_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    _release(tmp_path, "release-old")
    _activate(tmp_path, "release-old")
    monkeypatch.setattr(frontend_build, "_node_command", lambda: "node")
    monkeypatch.setattr(frontend_build, "_npm_cli", lambda _node: "npm-cli.js")
    monkeypatch.setattr(frontend_build, "FRONTEND_BUILD_TIMEOUT_SECONDS", 5.0)

    clock = [100.0]
    monkeypatch.setattr(frontend_build.time, "monotonic", lambda: clock[0])
    original_lock = frontend_build.frontend_build_lock
    lock_timeouts: list[float] = []

    @contextmanager
    def delayed_lock(project_root: Path | str, *, timeout_seconds: float):
        lock_timeouts.append(timeout_seconds)
        with original_lock(project_root, timeout_seconds=timeout_seconds) as lock:
            clock[0] += 2.0
            yield lock

    monkeypatch.setattr(frontend_build, "frontend_build_lock", delayed_lock)
    deadlines: list[float | None] = []

    def runner(command: list[str], *, cwd: Path, label: str) -> str:
        deadlines.append(frontend_build._FRONTEND_BUILD_DEADLINE.get())
        clock[0] += 1.0
        return _successful_runner(command, cwd=cwd, label=label)

    monkeypatch.setattr(frontend_build, "_run_checked", runner)
    with pytest.raises(RuntimeError, match="deadline expired"):
        frontend_build.ensure_frontend_build(tmp_path, lock_timeout_seconds=1000.0)

    assert lock_timeouts == [5.0]
    assert deadlines == [105.0, 105.0, 105.0]
    assert json.loads(frontend_build.active_release_path(tmp_path).read_text(encoding="utf-8"))["release"] == "release-old"
    assert not any(path.name.startswith("stage-") for path in frontend_build.frontend_releases_dir(tmp_path).iterdir())


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


def test_generated_vite_config_is_not_a_build_input(monkeypatch, tmp_path):
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    before = frontend_build.build_inputs(tmp_path)
    (tmp_path / "web" / "vite.config.js").write_text("// stale generated output", encoding="utf-8")
    after = frontend_build.build_inputs(tmp_path)
    assert frontend_build.compute_build_key(before) == frontend_build.compute_build_key(after)
    assert before["productionInputStateDigest"] == after["productionInputStateDigest"]


def test_release_build_selects_typescript_config(monkeypatch, tmp_path):
    _write_project(tmp_path)
    _stub_build_identity(monkeypatch)
    commands = []

    def run(command, *, cwd, label):
        commands.append((label, command))
        return _successful_runner(command, cwd=cwd, label=label)

    monkeypatch.setattr(frontend_build, "_run_checked", run)
    frontend_build.ensure_frontend_build(tmp_path)
    command = next(command for label, command in commands if label == "vite build")
    assert command[command.index("--config") + 1] == "vite.config.ts"
