#!/usr/bin/env python3
import json
from pathlib import Path

import core.launcher.service as launcher_service


def _seed_scene(tmp_path: Path) -> Path:
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260812T000000Z__launcher-test"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": "launcher-test",
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
    return scene_dir


def test_launcher_control_line_appended_to_scene_raw_log(tmp_path, monkeypatch):
    scene_dir = _seed_scene(tmp_path)
    monkeypatch.setattr(
        launcher_service, "_resolve_current_runtime_scene_dir", lambda: scene_dir
    )

    launcher_service._append_launcher_control_log_line(
        "launcher.bundle.start.requested",
        phase="start",
        outcome="observed",
        level="info",
        message="Launcher project bundle start requested.",
        event_at="2026-08-12T00:00:01Z",
    )

    log_path = scene_dir / "raw" / "launcher-control.log"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "launcher.bundle.start.requested" in lines[0]
    assert "phase=start" in lines[0]
    assert "outcome=observed" in lines[0]
    assert "2026-08-12T00:00:01Z" in lines[0]


def test_launcher_control_line_skipped_without_scene(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher_service, "_resolve_current_runtime_scene_dir", lambda: None)

    launcher_service._append_launcher_control_log_line(
        "launcher.bundle.start.requested",
        phase="start",
        outcome="observed",
        level="info",
        message="No scene available.",
        event_at="",
    )

    assert not (tmp_path / "launcher-control.log").exists()


def test_launcher_control_line_swallows_scene_resolution_failure(tmp_path, monkeypatch):
    def _boom():
        raise RuntimeError("scene root unavailable")

    monkeypatch.setattr(launcher_service, "_resolve_current_runtime_scene_dir", _boom)

    launcher_service._append_launcher_control_log_line(
        "launcher.bundle.start.failed",
        phase="start",
        outcome="failed",
        level="error",
        message="boom",
        event_at="",
    )


def test_record_launcher_event_degrades_gracefully_when_no_scene(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher_service, "_resolve_current_runtime_scene_dir", lambda: None)
    monkeypatch.setattr(
        launcher_service, "append_runtime_manager_file_event", lambda *a, **k: "2026-08-12T00:00:01Z"
    )

    launcher_service._record_launcher_event(
        "launcher.bundle.start.requested",
        phase="start",
        message="Launcher project bundle start requested.",
        fields={"source": "launcher_api"},
    )
