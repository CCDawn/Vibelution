"""Backend startup runtime-scene lifecycle: start seal+create, idempotent seal,
retention wiring, and web_workbench pure-function wiring.

Scene root and pointer resolve through the service (``_runtime_scene_root``
and ``LAUNCHER_STATE_PATH.with_name("active-runtime-scene.json")``). The
conftest runtime isolation stack pins both to ``tmp_path`` for files importing
``core.web.services``, so these tests never touch the real AppData scene tree.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import pytest

from core.web.services import runtime_scene_service
from core.web.services.runtime_scene import lifecycle
from core.web.services.runtime_scene import query as runtime_scene_query


SCENE_ROOT_RELATIVE = Path("logs") / "runtime_scenes"
POINTER_RELATIVE = Path(".runtime") / "launcher" / "active-runtime-scene.json"


def _scene_root(tmp_path: Path) -> Path:
    return tmp_path / SCENE_ROOT_RELATIVE


def _pointer_path(tmp_path: Path) -> Path:
    return tmp_path / POINTER_RELATIVE


def _write_pointer(tmp_path: Path, reference: dict) -> None:
    pointer = _pointer_path(tmp_path)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")


def _seed_scene(
    tmp_path: Path,
    index: int,
    *,
    status: str = "stopped",
    ended_at: str = "2026-05-18T13:00:00Z",
) -> Path:
    started = f"2026-05-18T12:{index // 60:02d}:{index % 60:02d}Z"
    scene_dir = _scene_root(tmp_path) / f"20260518T120000Z__scene-{index:02d}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    for relative_dir in ("events", "raw", "conversations", "agent", "artifacts"):
        (scene_dir / relative_dir).mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": f"scene-{index:02d}",
                "started_at": started,
                "ended_at": ended_at if status == "stopped" else "",
                "status": status,
                "result": "explicit_stop" if status == "stopped" else "",
                "trigger": "start",
                "project_root": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return scene_dir


def test_start_seals_previous_scene_and_repoints_pointer(tmp_path) -> None:
    old_dir = _seed_scene(tmp_path, 1, status="running", ended_at="")
    _write_pointer(
        tmp_path,
        {
            "runtimeSceneId": "scene-01",
            "runtimeSceneDir": str(old_dir.resolve()),
            "startedAt": "2026-05-18T12:00:01Z",
            "launcherPid": 1234,
            "trigger": "start",
        },
    )
    assert runtime_scene_service.start_runtime_scene is lifecycle.start_runtime_scene
    assert runtime_scene_service.seal_active_runtime_scene is lifecycle.seal_active_runtime_scene

    reference = lifecycle.start_runtime_scene("backend_startup")

    old_manifest = json.loads((old_dir / "manifest.json").read_text(encoding="utf-8"))
    assert old_manifest["status"] == "stopped"
    assert old_manifest["result"] == "orphan_reconciled"
    assert old_manifest["ended_at"]
    assert old_manifest["started_at"] == "2026-05-18T12:00:01Z"

    assert len(reference["runtimeSceneId"]) == 12
    assert reference["trigger"] == "backend_startup"
    assert reference["launcherPid"] > 0
    new_dir = Path(reference["runtimeSceneDir"])
    assert new_dir.parent == _scene_root(tmp_path).resolve()
    for relative_dir in ("events", "raw", "conversations", "agent", "artifacts"):
        assert (new_dir / relative_dir).is_dir()
    new_manifest = json.loads((new_dir / "manifest.json").read_text(encoding="utf-8"))
    assert new_manifest["status"] == "running"
    assert new_manifest["runtime_scene_id"] == reference["runtimeSceneId"]
    assert new_manifest["project_root"] == str(tmp_path)

    assert json.loads(_pointer_path(tmp_path).read_text(encoding="utf-8")) == reference
    assert runtime_scene_service._resolve_current_runtime_scene_dir() == new_dir.resolve()


def test_seal_is_idempotent_after_first_seal(tmp_path) -> None:
    reference = lifecycle.start_runtime_scene("backend_startup")
    scene_dir = Path(reference["runtimeSceneDir"])

    first = lifecycle.seal_active_runtime_scene("backend_exited", "clean exit")
    assert first["sealed"] is True
    assert first["reason"] == "backend_exited"
    manifest_bytes = (scene_dir / "manifest.json").read_bytes()

    second = lifecycle.seal_active_runtime_scene("backend_exited", "clean exit")
    assert second == {
        "sealed": False,
        "reason": "already_sealed",
        "sceneDir": str(scene_dir),
    }
    assert (scene_dir / "manifest.json").read_bytes() == manifest_bytes


def test_seal_degrades_without_pointer_or_with_foreign_scene_dir(tmp_path) -> None:
    assert lifecycle.seal_active_runtime_scene("backend_exited", "x") == {
        "sealed": False,
        "reason": "active_scene_unavailable",
    }

    _write_pointer(
        tmp_path,
        {
            "runtimeSceneId": "foreign",
            "runtimeSceneDir": str(tmp_path.resolve()),
            "startedAt": "",
            "launcherPid": 0,
            "trigger": "start",
        },
    )
    assert lifecycle.seal_active_runtime_scene("backend_exited", "x") == {
        "sealed": False,
        "reason": "scene_dir_outside_root",
    }


def test_startup_wiring_opens_scene_quickly_then_retention_preserves_current_scene(tmp_path) -> None:
    from scripts import web_workbench

    for index in range(35):
        _seed_scene(tmp_path, index)

    result = web_workbench.open_runtime_scene_for_startup()

    # Scene creation remains on the entrypoint path; history scanning/deletion
    # is owned by the post-routes lifespan task.
    assert "retention" not in result
    reference = result["runtimeScene"]
    assert reference["trigger"] == "backend_startup"
    current_dir = Path(reference["runtimeSceneDir"])
    assert current_dir.is_dir()
    assert runtime_scene_service._resolve_current_runtime_scene_dir() == current_dir.resolve()

    remaining_before_retention = sorted(
        item.name for item in _scene_root(tmp_path).iterdir() if item.is_dir()
    )
    assert len(remaining_before_retention) == 36

    retention = runtime_scene_query._enforce_runtime_scene_retention()
    assert retention["deletedCount"] == 6
    assert retention["keptCount"] == 30
    remaining = sorted(item.name for item in _scene_root(tmp_path).iterdir() if item.is_dir())
    assert len(remaining) == 30
    assert "20260518T120000Z__scene-00" not in remaining
    assert "20260518T120000Z__scene-05" not in remaining
    assert "20260518T120000Z__scene-06" in remaining
    assert current_dir.name in remaining


def test_startup_wiring_does_not_run_retention_on_entrypoint_path(tmp_path, monkeypatch) -> None:
    from scripts import web_workbench

    retention_calls = []

    def _boom(*args, **kwargs):
        retention_calls.append((args, kwargs))
        raise RuntimeError("scene root unavailable")

    monkeypatch.setattr(runtime_scene_query, "_enforce_runtime_scene_retention", _boom)

    result = web_workbench.open_runtime_scene_for_startup()

    assert "retention" not in result
    assert retention_calls == []
    assert Path(result["runtimeScene"]["runtimeSceneDir"]).is_dir()


def test_retention_cooperative_stop_during_manifest_scan_leaves_history_untouched(
    tmp_path, monkeypatch
) -> None:
    for index in range(35):
        _seed_scene(tmp_path, index)

    original_load_manifest = runtime_scene_service._load_scene_manifest
    loaded_scenes = []
    stop_requested = False

    def load_manifest(scene_dir):
        nonlocal stop_requested
        manifest = original_load_manifest(scene_dir)
        loaded_scenes.append(scene_dir)
        if len(loaded_scenes) == 3:
            stop_requested = True
        return manifest

    monkeypatch.setattr(runtime_scene_service, "_load_scene_manifest", load_manifest)

    result = runtime_scene_query._enforce_runtime_scene_retention(
        should_stop=lambda: stop_requested
    )

    assert result == {"stopped": True}
    assert len(loaded_scenes) == 3
    assert len([path for path in _scene_root(tmp_path).iterdir() if path.is_dir()]) == 35


def test_retention_cooperative_stop_checks_before_each_delete(tmp_path, monkeypatch) -> None:
    for index in range(35):
        _seed_scene(tmp_path, index)
    before_names = {path.name for path in _scene_root(tmp_path).iterdir() if path.is_dir()}

    stop_requested = False
    original_rmtree = shutil.rmtree

    def remove_one_then_stop(path):
        nonlocal stop_requested
        original_rmtree(path)
        stop_requested = True

    monkeypatch.setattr(runtime_scene_query.shutil, "rmtree", remove_one_then_stop)

    result = runtime_scene_query._enforce_runtime_scene_retention(
        should_stop=lambda: stop_requested
    )

    assert result["deletedCount"] == 1
    assert result["stopped"] is True
    remaining_names = {path.name for path in _scene_root(tmp_path).iterdir() if path.is_dir()}
    removed_names = before_names - remaining_names
    assert len(removed_names) == 1
    assert result["deletedSceneIds"] == [next(iter(removed_names)).split("__", 1)[1]]


@pytest.mark.parametrize(("scene_opened", "expected_flag"), [(True, "1"), (False, "0")])
def test_main_scopes_deferred_retention_flag_around_uvicorn(
    monkeypatch, scene_opened: bool, expected_flag: str
) -> None:
    from scripts import web_workbench

    calls: list[str] = []
    monkeypatch.setattr(
        web_workbench,
        "parse_args",
        lambda: argparse.Namespace(host="127.0.0.1", port=8000, open_browser=False, reload=False),
    )
    monkeypatch.setattr(
        web_workbench, "bootstrap_runtime_scene_for_workbench", lambda: calls.append("bootstrap")
        or scene_opened
    )
    monkeypatch.delenv(web_workbench.DEFER_RUNTIME_SCENE_RETENTION_ENV, raising=False)

    def fake_create_server(app, *, host, port):
        assert host == "127.0.0.1" and port == 8000

        class FakeServer:
            def run(self):
                calls.append(
                    f"uvicorn:{app}:{os.environ.get(web_workbench.DEFER_RUNTIME_SCENE_RETENTION_ENV)}"
                )

        return FakeServer()

    monkeypatch.setattr(web_workbench, "create_workbench_server", fake_create_server)

    web_workbench.main()

    assert calls == ["bootstrap", f"uvicorn:core.web.app:app:{expected_flag}"]
    assert web_workbench.DEFER_RUNTIME_SCENE_RETENTION_ENV not in os.environ


def test_bootstrap_opens_scene_and_registers_exit_seal(tmp_path, monkeypatch) -> None:
    from scripts import web_workbench

    seal_calls: list[str] = []
    monkeypatch.setattr(
        web_workbench, "seal_runtime_scene_on_exit", lambda: seal_calls.append("exit")
    )

    assert web_workbench.bootstrap_runtime_scene_for_workbench() is True

    reference = web_workbench._startup_runtime_scene_reference
    assert isinstance(reference, dict)
    assert reference["trigger"] == "backend_startup"
    assert Path(reference["runtimeSceneDir"]).is_dir()
    assert json.loads(_pointer_path(tmp_path).read_text(encoding="utf-8")) == reference


def test_exit_seal_only_seals_scene_this_process_opened(tmp_path, monkeypatch) -> None:
    from scripts import web_workbench

    reference = lifecycle.start_runtime_scene("backend_startup")
    sealed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        lifecycle,
        "seal_active_runtime_scene",
        lambda result, reason: sealed.append((result, reason)) or {"sealed": True},
    )
    monkeypatch.setattr(web_workbench, "_startup_runtime_scene_reference", reference)

    web_workbench.seal_runtime_scene_on_exit()
    assert sealed == [("backend_exited", "Workbench backend process exited cleanly.")]

    sealed.clear()
    _write_pointer(
        tmp_path,
        {
            "runtimeSceneId": "newer-start-owns-this",
            "runtimeSceneDir": str(reference["runtimeSceneDir"]),
            "startedAt": reference["startedAt"],
            "launcherPid": 1,
            "trigger": "backend_startup",
        },
    )
    web_workbench.seal_runtime_scene_on_exit()
    assert sealed == []

    sealed.clear()
    monkeypatch.setattr(web_workbench, "_startup_runtime_scene_reference", None)
    web_workbench.seal_runtime_scene_on_exit()
    assert sealed == [("backend_exited", "Workbench backend process exited cleanly.")]
