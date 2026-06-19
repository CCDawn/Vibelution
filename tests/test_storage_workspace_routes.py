from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import workspace_data_migration_service as migration


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _seed_workspace(project_root):
    source_workspace = project_root / "workspace"
    (source_workspace / "memory").mkdir(parents=True)
    (source_workspace / "memory" / "tasks.json").write_text('{"tasks":[1]}\n', encoding="utf-8")
    return source_workspace


def test_storage_workspace_migration_route_flow(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    _seed_workspace(project_root)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)
    client = _client()

    status = client.get("/api/storage/workspace-migration/status")
    preview = client.post("/api/storage/workspace-migration/preview", json={})
    apply = client.post("/api/storage/workspace-migration/apply", json={})
    verify = client.post("/api/storage/workspace-migration/verify", json={})

    assert status.status_code == 200, status.text
    assert status.json()["migrationNeeded"] is True
    assert preview.status_code == 200, preview.text
    assert preview.json()["totals"]["itemCount"] == 1
    assert apply.status_code == 200, apply.text
    assert apply.json()["verified"]["ok"] is True
    assert verify.status_code == 200, verify.text
    assert verify.json()["verified"]["ok"] is True
    assert (data_home / "workspace" / migration.WORKSPACE_MANIFEST_NAME).exists()


def test_storage_legacy_workspace_cleanup_route_requires_verified_migration(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    _seed_workspace(project_root)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)
    client = _client()

    blocked = client.post(
        "/api/storage/legacy-workspace/cleanup-execute",
        json={"confirmationPhrase": migration.LEGACY_WORKSPACE_CLEANUP_CONFIRMATION},
    )

    assert blocked.status_code == 422
    assert "migration_not_verified" in blocked.text


def test_storage_legacy_workspace_cleanup_route_deletes_after_apply_and_confirmation(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    source_workspace = _seed_workspace(project_root)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)
    client = _client()

    applied = client.post("/api/storage/workspace-migration/apply", json={})
    preview = client.post("/api/storage/legacy-workspace/cleanup-preview")
    deleted = client.post(
        "/api/storage/legacy-workspace/cleanup-execute",
        json={"confirmationPhrase": migration.LEGACY_WORKSPACE_CLEANUP_CONFIRMATION},
    )

    assert applied.status_code == 200, applied.text
    assert preview.status_code == 200, preview.text
    assert preview.json()["canExecute"] is True
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"]["status"] == "deleted"
    assert not source_workspace.exists()
    assert (data_home / "workspace" / "memory" / "tasks.json").exists()
