from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.infrastructure import git_memory
from core.launcher import developer_mode
from core.launcher import service as launcher_service
from core.web.routes import launcher as web_launcher_routes


def test_developer_mode_defaults_off_and_launcher_persists_external_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    events = []
    monkeypatch.setattr(
        developer_mode,
        "append_runtime_manager_file_event",
        lambda event_code, payload, **kwargs: events.append((event_code, payload)) or "2026-06-13T00:00:00+00:00",
    )

    setting = developer_mode.get_developer_mode_setting(config_path=config_path)

    assert setting["enabled"] is False
    assert setting["defaulted"] is True

    response = developer_mode.update_developer_mode_setting(
        True,
        base_hash=setting["configHash"],
        config_path=config_path,
    )

    saved = config_path.read_text(encoding="utf-8")
    assert response["ok"] is True
    assert response["setting"]["enabled"] is True
    assert "[launcher.developer_mode]" in saved
    assert "enabled = true" in saved
    assert 'updated_by = "launcher"' in saved
    assert events[-1][0] == "launcher.developer_mode.updated"


def test_developer_cleanup_preview_is_blocked_when_mode_off(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.setattr(launcher_service, "PROJECT_ROOT", project_root)
    app = FastAPI()
    app.include_router(web_launcher_routes.router, prefix="/api")
    client = TestClient(app)

    response = client.post("/api/launcher/developer-mode/cleanup/preview", json={"action": "quick_clean"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "mode_disabled"


def test_developer_cleanup_plan_requires_confirm_and_matching_hash(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\n[launcher.developer_mode]\nenabled = true\n", encoding="utf-8")
    project_root = tmp_path / "project"
    cache_dir = project_root / "core" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "module.pyc").write_bytes(b"cache")
    plan_dir = tmp_path / "plans"

    preview = developer_mode.preview_cleanup_plan(
        "quick_clean",
        config_path=config_path,
        project_root=project_root,
        plan_dir=plan_dir,
    )
    plan = preview["plan"]

    try:
        developer_mode.apply_cleanup_plan(
            "quick_clean",
            plan_id=plan["planId"],
            plan_hash=plan["planHash"],
            confirm=False,
            config_path=config_path,
            project_root=project_root,
            plan_dir=plan_dir,
        )
    except developer_mode.DeveloperCleanupPlanError as exc:
        assert exc.code == "confirm_required"
    else:
        raise AssertionError("expected confirm gate")

    try:
        developer_mode.apply_cleanup_plan(
            "quick_clean",
            plan_id=plan["planId"],
            plan_hash="bad-hash",
            confirm=True,
            config_path=config_path,
            project_root=project_root,
            plan_dir=plan_dir,
        )
    except developer_mode.DeveloperCleanupPlanError as exc:
        assert exc.code == "plan_hash_mismatch"
    else:
        raise AssertionError("expected plan hash gate")

    applied = developer_mode.apply_cleanup_plan(
        "quick_clean",
        plan_id=plan["planId"],
        plan_hash=plan["planHash"],
        confirm=True,
        config_path=config_path,
        project_root=project_root,
        plan_dir=plan_dir,
    )

    assert applied["ok"] is True
    assert applied["action"] == "quick_clean"
    assert len(applied["applied"]) == 1
    assert not cache_dir.exists()


def test_developer_db_compact_uses_git_memory_prune_entrypoint(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\n[launcher.developer_mode]\nenabled = true\n", encoding="utf-8")
    project_root = tmp_path / "project"
    db_path = project_root / "workspace" / "agent_brain.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"sqlite placeholder")
    plan_dir = tmp_path / "plans"
    calls = []
    monkeypatch.setattr(
        git_memory,
        "prune_worktree_snapshots",
        lambda keep_latest=None, vacuum=False: calls.append((keep_latest, vacuum)) or {"deletedSnapshots": 3},
    )

    preview = developer_mode.preview_cleanup_plan(
        "db_compact",
        config_path=config_path,
        project_root=project_root,
        plan_dir=plan_dir,
    )
    plan = preview["plan"]
    result = developer_mode.apply_cleanup_plan(
        "db_compact",
        plan_id=plan["planId"],
        plan_hash=plan["planHash"],
        confirm=True,
        config_path=config_path,
        project_root=project_root,
        plan_dir=plan_dir,
    )

    assert result["ok"] is True
    assert calls == [(developer_mode.WORKTREE_SNAPSHOT_KEEP_LATEST, True)]
    assert result["applied"][0]["dbStats"] == {"deletedSnapshots": 3}


def test_developer_mode_status_is_readable_from_launcher_status(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[launcher]\n[launcher.developer_mode]\nenabled = true\nupdated_by = \"launcher\"\n", encoding="utf-8")
    monkeypatch.setattr(launcher_service, "CONFIG_PATH", config_path)
    monkeypatch.setattr(launcher_service, "get_launcher_startup_settings", lambda: {"configHash": "startup"})
    monkeypatch.setattr(launcher_service, "get_workbench_window_mode_setting", lambda: {"mode": "fullscreen"})
    monkeypatch.setattr(launcher_service, "_runtime_manager_state", lambda: {})
    monkeypatch.setattr(launcher_service, "_load_launcher_state", lambda: {})
    monkeypatch.setattr(launcher_service, "_observed_workbench", lambda: {})
    monkeypatch.setattr(launcher_service, "_workbench_payload", lambda **kwargs: {})
    monkeypatch.setattr(launcher_service, "launcher_active_work_runs", lambda: [])
    monkeypatch.setattr(launcher_service, "_runtime_manager_payload", lambda state: {})
    monkeypatch.setattr(launcher_service, "_lifecycle_proof", lambda **kwargs: {})
    monkeypatch.setattr(launcher_service, "_project_bundle_from_workbench", lambda *args, **kwargs: {})
    monkeypatch.setattr(launcher_service, "_control_plane_evidence", lambda: {})
    monkeypatch.setattr(launcher_service, "_guardian_adapter_from_workbench", lambda **kwargs: {})

    payload = launcher_service.get_launcher_status()

    assert payload["settings"]["developerMode"]["enabled"] is True
    assert payload["settings"]["developerMode"]["controller"] == "launcher"
