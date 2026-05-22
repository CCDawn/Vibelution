import json

from core.web.services import runtime_scene_service


def test_runtime_scene_event_writes_standalone_package_index(tmp_path, monkeypatch):
    scene_id = "scene-package-index"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / f"20260518T120000Z__{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": scene_id,
                "started_at": "2026-05-18T12:00:00Z",
                "status": "running",
                "trigger": "start",
                "session_mode": "managed",
                "package": {
                    "schema_version": 2,
                    "timeline_path": "timeline.jsonl",
                    "lifecycle_path": "lifecycle.jsonl",
                    "raw_dir": "raw",
                    "conversations_dir": "conversations",
                    "agent_dir": "agent",
                    "artifacts_dir": "artifacts",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "runtimeSceneId": scene_id,
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    response = runtime_scene_service.record_runtime_scene_event(
        "work_run",
        "state",
        "work_run.snapshot.persisted",
        message="Snapshot persisted",
        level="info",
        outcome="succeeded",
        fields={"runId": "run-1"},
        lifecycle=True,
    )

    assert response["accepted"] is True
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    package_index = json.loads((scene_dir / "package_index.json").read_text(encoding="utf-8"))
    assert manifest["package"]["package_index_path"] == "package_index.json"
    assert package_index["schema_version"] == 1
    assert package_index["package_id"] == scene_id
    assert package_index["index_key"] == manifest["package"]["index_key"]
    assert package_index["search_text"] == manifest["package"]["search_text"]
    assert package_index["timeline_path"] == "timeline.jsonl"
    assert package_index["lifecycle_path"] == "lifecycle.jsonl"
