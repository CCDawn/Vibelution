#!/usr/bin/env python3
import json
from pathlib import Path

from core.runtime_manager.scene_logging import enforce_runtime_scene_retention_on_startup
from core.web.services import runtime_scene_service


def _seed_scene(tmp_path: Path, index: int) -> Path:
    started = f"2026-05-18T12:{index // 60:02d}:{index % 60:02d}Z"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__scene-{index:02d}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": f"scene-{index:02d}",
                "started_at": started,
                "ended_at": "2026-05-18T13:00:00Z",
                "status": "stopped",
                "result": "explicit_stop",
                "trigger": "start",
                "session_mode": "managed",
                "project_root": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return scene_dir


def _remaining_scene_names(tmp_path: Path) -> list[str]:
    scene_root = tmp_path / "logs" / "runtime_scenes"
    if not scene_root.exists():
        return []
    return sorted(p.name for p in scene_root.iterdir() if p.is_dir())


def test_startup_retention_prunes_oldest_beyond_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    for i in range(35):
        _seed_scene(tmp_path, i)

    result = enforce_runtime_scene_retention_on_startup()

    assert result.get("deletedCount") == 5
    assert result.get("keptCount") == 30
    remaining = _remaining_scene_names(tmp_path)
    seed_remaining = [name for name in remaining if "__scene-" in name]
    assert len(seed_remaining) == 30
    assert "20260518T120000Z__scene-00" not in seed_remaining
    assert "20260518T120000Z__scene-04" not in seed_remaining
    assert "20260518T120000Z__scene-05" in seed_remaining
    assert "20260518T120000Z__scene-34" in seed_remaining


def test_startup_retention_noop_without_scene_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)

    result = enforce_runtime_scene_retention_on_startup()

    assert result.get("deletedCount") == 0
    assert _remaining_scene_names(tmp_path) == []


def test_startup_retention_swallows_enforce_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    from core.web.services.runtime_scene import query as runtime_scene_query

    def _boom(*args, **kwargs):
        raise RuntimeError("scene root unavailable")

    monkeypatch.setattr(runtime_scene_query, "_enforce_runtime_scene_retention", _boom)

    result = enforce_runtime_scene_retention_on_startup()

    assert result == {}
