#!/usr/bin/env python3
import json
from pathlib import Path

from core.web.services import runtime_scene_service
from core.web.services.runtime_scene import record as runtime_scene_record


def _seed_active_scene(tmp_path: Path) -> Path:
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260812T000000Z__summary-refresh-test"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": "summary-refresh-test",
                "started_at": "2026-08-12T00:00:00Z",
                "ended_at": "",
                "status": "running",
                "result": "explicit_stop",
                "trigger": "start",
                "session_mode": "managed",
                "project_root": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    launcher_dir = tmp_path / ".runtime" / "launcher"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    (launcher_dir / "active-runtime-scene.json").write_text(
        json.dumps(
            {
                "runtimeSceneDir": str(scene_dir),
                "runtimeSceneId": "summary-refresh-test",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return scene_dir


def test_active_scene_summary_refreshed_when_due(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    runtime_scene_service._last_scene_package_refresh_at = 0.0
    scene_dir = _seed_active_scene(tmp_path)

    refreshed = runtime_scene_record._refresh_active_scene_package_if_due(scene_dir)

    assert refreshed is True
    assert (scene_dir / "summary.json").exists()
    assert (scene_dir / "package_index.json").exists()
    summary = json.loads((scene_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary.get("package_id") == "summary-refresh-test"


def test_active_scene_summary_throttled_within_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    runtime_scene_service._last_scene_package_refresh_at = 1e18
    scene_dir = _seed_active_scene(tmp_path)

    refreshed = runtime_scene_record._refresh_active_scene_package_if_due(scene_dir)

    assert refreshed is False
    assert not (scene_dir / "summary.json").exists()


def test_scene_event_write_refreshes_summary_after_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    runtime_scene_service._last_scene_package_refresh_at = 0.0
    scene_dir = _seed_active_scene(tmp_path)

    result = runtime_scene_service.record_runtime_scene_event(
        "backend",
        "startup",
        "backend.api.ready",
        message="backend ready",
        level="info",
        outcome="succeeded",
    )

    assert result.get("accepted") is True
    assert (scene_dir / "summary.json").exists()
    summary = json.loads((scene_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary.get("package_id") == "summary-refresh-test"


def test_scene_event_can_defer_periodic_summary_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    scene_dir = _seed_active_scene(tmp_path)

    result = runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        "queue",
        "command_queue.command_claimed",
        message="runtime manager claimed lifecycle command",
        level="info",
        outcome="started",
        lifecycle=True,
        refresh_package_if_due=False,
    )

    assert result.get("accepted") is True
    assert result.get("projectionRefresh") == "deferred"
    assert not (scene_dir / "summary.json").exists()
    assert not (scene_dir / "package_index.json").exists()
    rows = [
        json.loads(line)
        for line in (scene_dir / "events" / "runtime_manager.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["event_code"] == "command_queue.command_claimed"


def test_deferred_periodic_refresh_keeps_warning_projection_immediate(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "_last_scene_package_refresh_at", 0.0)
    scene_dir = _seed_active_scene(tmp_path)
    full_projection_calls: list[Path] = []
    monkeypatch.setattr(
        runtime_scene_service,
        "_update_runtime_scene_package_manifest",
        lambda scene, manifest: full_projection_calls.append(scene),
    )

    result = runtime_scene_service.record_runtime_scene_event(
        "runtime_manager",
        "consistency",
        "workbench.consistency.orphaned_browser_detected",
        message="orphaned browser detected",
        level="warning",
        outcome="observed",
        lifecycle=True,
        refresh_package_if_due=False,
    )

    assert result.get("accepted") is True
    assert result.get("projectionRefresh") == "full"
    assert full_projection_calls == [scene_dir]
