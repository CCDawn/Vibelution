import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.logs import router as logs_router
from core.web.services import runtime_scene_service
from core.web.services.runtime_scene import query as runtime_scene_query


def _write_scene(root: Path, project_root: Path, index: int) -> Path:
    started = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=index)
    scene_id = f"scene-{index:02d}"
    scene_dir = root / f"{started.strftime('%Y%m%dT%H%M%SZ')}__{scene_id}"
    scene_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "runtime_scene_id": scene_id,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "ended_at": (started + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        "status": "stopped",
        "trigger": "internal-start",
        "project_root": str(project_root),
    }
    (scene_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return scene_dir


@pytest.mark.parametrize(
    ("delete_error", "remove_before_error", "expected_kept_count"),
    [
        (PermissionError, False, 31),
        (FileNotFoundError, True, 30),
    ],
)
def test_runtime_scene_list_survives_retention_delete_races(
    tmp_path,
    monkeypatch,
    delete_error,
    remove_before_error,
    expected_kept_count,
):
    runtime_scene_root = tmp_path / "logs" / "runtime_scenes"
    runtime_scene_root.mkdir(parents=True)
    oldest_scene = _write_scene(runtime_scene_root, tmp_path, 0)
    for index in range(1, 31):
        _write_scene(runtime_scene_root, tmp_path, index)

    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True)
    launcher_state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)

    real_rmtree = shutil.rmtree
    delete_attempts: list[Path] = []

    def simulated_delete(path, *args, **kwargs):
        scene_path = Path(path)
        delete_attempts.append(scene_path)
        if remove_before_error:
            real_rmtree(scene_path, *args, **kwargs)
        raise delete_error("simulated concurrent retention failure")

    monkeypatch.setattr(
        runtime_scene_query,
        "shutil",
        SimpleNamespace(rmtree=simulated_delete),
    )
    warning_messages: list[str] = []
    monkeypatch.setattr(
        runtime_scene_query._debug_logger,
        "warning",
        lambda message: warning_messages.append(str(message)),
    )

    retention_results: list[dict] = []
    enforce = runtime_scene_query._enforce_runtime_scene_retention

    def capture_retention_result(*args, **kwargs):
        result = enforce(*args, **kwargs)
        retention_results.append(result)
        return result

    monkeypatch.setattr(
        runtime_scene_service,
        "_enforce_runtime_scene_retention",
        capture_retention_result,
    )

    app = FastAPI()
    app.include_router(logs_router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/logs/runtime-scenes")

    assert response.status_code == 200, response.text
    assert len(response.json()) == expected_kept_count
    assert delete_attempts == [oldest_scene]
    result = retention_results[-1]
    assert result["deletedCount"] == 0
    assert result["deletedSceneIds"] == []
    assert result["keptCount"] == expected_kept_count
    assert oldest_scene.exists() is (not remove_before_error)
    assert len(warning_messages) == 1
    assert delete_error.__name__ in warning_messages[0]
    assert "=1" in warning_messages[0]
    assert "scene-00" not in warning_messages[0]


def test_runtime_scene_detail_and_content_support_external_storage_paths(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime_scene_root = tmp_path / "external-storage" / "logs" / "runtime_scenes"
    runtime_scene_root.mkdir(parents=True)
    scene_dir = _write_scene(runtime_scene_root, project_root, 1)
    raw_dir = scene_dir / "raw"
    raw_dir.mkdir()
    (raw_dir / "backend.stdout.log").write_text("external scene log\n", encoding="utf-8")

    launcher_state_path = project_root / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True)
    launcher_state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(runtime_scene_service, "_runtime_scene_root", lambda: runtime_scene_root.resolve())

    app = FastAPI()
    app.include_router(logs_router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as client:
        detail_response = client.get("/api/logs/runtime-scenes/scene-01")
        content_response = client.get(
            "/api/logs/runtime-scenes/scene-01/content",
            params={"path": "raw/backend.stdout.log"},
        )

    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["manifestPath"] == (scene_dir / "manifest.json").resolve().as_posix()
    assert content_response.status_code == 200, content_response.text
    assert content_response.json()["rootPath"] == scene_dir.resolve().as_posix()
    assert content_response.json()["content"].replace("\r\n", "\n") == "external scene log\n"
