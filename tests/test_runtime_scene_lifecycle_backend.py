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
from pathlib import Path

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


def test_startup_wiring_prunes_overflow_and_protects_current_scene(tmp_path) -> None:
    from scripts import web_workbench

    for index in range(35):
        _seed_scene(tmp_path, index)

    result = web_workbench.open_runtime_scene_for_startup()

    assert result["retention"]["deletedCount"] == 6
    assert result["retention"]["keptCount"] == 30
    reference = result["runtimeScene"]
    assert reference["trigger"] == "backend_startup"
    current_dir = Path(reference["runtimeSceneDir"])
    assert current_dir.is_dir()
    assert runtime_scene_service._resolve_current_runtime_scene_dir() == current_dir.resolve()

    remaining = sorted(item.name for item in _scene_root(tmp_path).iterdir() if item.is_dir())
    assert len(remaining) == 30
    assert "20260518T120000Z__scene-00" not in remaining
    assert "20260518T120000Z__scene-05" not in remaining
    assert "20260518T120000Z__scene-06" in remaining
    assert current_dir.name in remaining


def test_startup_wiring_swallows_retention_failure(tmp_path, monkeypatch) -> None:
    from scripts import web_workbench

    def _boom(*args, **kwargs):
        raise RuntimeError("scene root unavailable")

    monkeypatch.setattr(runtime_scene_query, "_enforce_runtime_scene_retention", _boom)

    result = web_workbench.open_runtime_scene_for_startup()

    assert result["retention"] == {"error": "RuntimeError"}
    assert Path(result["runtimeScene"]["runtimeSceneDir"]).is_dir()


def test_main_calls_bootstrap_once_before_uvicorn(monkeypatch) -> None:
    from scripts import web_workbench

    calls: list[str] = []
    monkeypatch.setattr(
        web_workbench,
        "parse_args",
        lambda: argparse.Namespace(host="127.0.0.1", port=8000, open_browser=False, reload=False),
    )
    monkeypatch.setattr(
        web_workbench, "bootstrap_runtime_scene_for_workbench", lambda: calls.append("bootstrap")
    )
    monkeypatch.setattr(
        web_workbench.uvicorn,
        "run",
        lambda app, **kwargs: calls.append(f"uvicorn:{app}"),
    )

    web_workbench.main()

    assert calls == ["bootstrap", "uvicorn:core.web.app:app"]


def test_bootstrap_opens_scene_and_registers_exit_seal(tmp_path, monkeypatch) -> None:
    from scripts import web_workbench

    seal_calls: list[str] = []
    monkeypatch.setattr(
        web_workbench, "seal_runtime_scene_on_exit", lambda: seal_calls.append("exit")
    )

    web_workbench.bootstrap_runtime_scene_for_workbench()

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
