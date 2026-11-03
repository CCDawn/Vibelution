import json
from types import SimpleNamespace

import pytest

from core.diagnostics import agent_log_context
from core.web.services import runtime_scene_service


def _snapshot_tree(root):
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(),
            path.stat().st_mtime_ns,
        ) if path.is_file() else None
        for path in root.rglob("*")
    }


def _seed_scene(tmp_path, monkeypatch, *, external=False, sidecars="stale"):
    project_root = tmp_path / "project"
    project_root.mkdir()
    logs_root = tmp_path / "external" / "logs" if external else project_root / "logs"
    scene_root = logs_root / "runtime_scenes"
    scene_dir = scene_root / "20260524T120001Z__read-only"
    scene_dir.mkdir(parents=True)
    (scene_dir / "manifest.json").write_text(
        json.dumps({
            "runtime_scene_id": "read-only",
            "started_at": "2026-05-24T12:00:01Z",
            "status": "running",
            "project_root": str(project_root),
            "package": {"index_key": "stale"},
        }),
        encoding="utf-8",
    )
    (scene_dir / "timeline.jsonl").write_text(
        json.dumps({
            "runtime_scene_id": "read-only",
            "ts": "2026-05-24T12:00:02Z",
            "seq": 1,
            "component": "backend",
            "phase": "startup",
            "event_code": "backend.start.failed",
            "level": "error",
            "outcome": "failed",
            "message": "Synthetic backend startup failed.",
            "fields": {},
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(runtime_scene_service, "_runtime_scene_root", lambda: scene_root)
    if sidecars == "stale":
        (scene_dir / "package_index.json").write_text('{"index_key":"stale"}', encoding="utf-8")
        (scene_dir / "summary.json").write_text(
            '{"package_id":"stale","diagnosis":{"severity":"info"}}', encoding="utf-8"
        )
    elif sidecars == "current":
        runtime_scene_service._update_runtime_scene_package_manifest(
            scene_dir, runtime_scene_service._load_scene_manifest(scene_dir)
        )
    return project_root, logs_root, scene_dir


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("sidecars", ["missing", "stale", "current"])
def test_runtime_scene_detail_keeps_files_unchanged_and_returns_fresh_diagnosis(
    tmp_path, monkeypatch, external, sidecars
):
    _seed_scene(tmp_path, monkeypatch, external=external, sidecars=sidecars)
    before = _snapshot_tree(tmp_path)

    for _ in range(2):
        detail = runtime_scene_service.get_runtime_scene_detail("read-only")
        assert detail["packageDiagnosis"]["severity"] == "error"
        assert detail["packageDiagnosis"]["firstSignal"]["eventCode"] == "backend.start.failed"
        assert detail["diagnosisSummary"]["activeClusterCount"] == 1
        assert "diagnosis-active-issue" in detail["packageIndex"]["tags"]
        assert detail["manifest"]["package"]["index_key"] == detail["packageIndex"]["indexKey"]

    assert _snapshot_tree(tmp_path) == before


def test_runtime_scene_prompt_index_does_not_write_scene_files(tmp_path, monkeypatch):
    _seed_scene(tmp_path, monkeypatch, external=True)
    with runtime_scene_service._RUNTIME_SCENE_PROMPT_INDEX_CACHE_LOCK:
        runtime_scene_service._RUNTIME_SCENE_PROMPT_INDEX_CACHE.clear()
    before = _snapshot_tree(tmp_path)

    prompt = runtime_scene_service.build_runtime_scene_prompt_index(limit=1)
    cached_prompt = runtime_scene_service.build_runtime_scene_prompt_index(limit=1)

    assert "backend.start.failed" in prompt
    assert "severity=error" in prompt
    assert cached_prompt == prompt
    assert _snapshot_tree(tmp_path) == before


def test_agent_log_context_cli_keeps_external_scene_files_unchanged(tmp_path, monkeypatch, capsys):
    from scripts import agent_log_context as cli

    project_root, logs_root, scene_dir = _seed_scene(tmp_path, monkeypatch, external=True)
    runtime_root = tmp_path / "external" / ".runtime"
    storage = SimpleNamespace(
        logs=logs_root,
        runtime=runtime_root,
        as_dict=lambda: {"logs": str(logs_root), "runtime": str(runtime_root)},
    )
    monkeypatch.setattr(agent_log_context, "resolve_active_project_storage_paths", lambda _root: storage)
    before = _snapshot_tree(tmp_path)

    assert cli.main(["--project", str(project_root), "--scene-id", "read-only"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["currentScene"]["runtimeSceneDir"] == str(scene_dir.resolve())
    assert payload["recentScenes"][0]["runtimeSceneId"] == "read-only"
    assert _snapshot_tree(tmp_path) == before
