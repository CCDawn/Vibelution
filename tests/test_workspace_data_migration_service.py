import os

import pytest

from core.web.services import workspace_data_migration_service as migration


def _seed_workspace(project_root, *, content: str = '{"agents":["new"]}\n'):
    source_workspace = project_root / "workspace"
    (source_workspace / "agents").mkdir(parents=True)
    (source_workspace / "agents" / "agents.json").write_text(content, encoding="utf-8")
    return source_workspace


def test_workspace_migration_apply_verifies_with_hash_and_writes_manifest(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    target_workspace = data_home / "workspace"
    _seed_workspace(project_root)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))

    report = migration.apply_workspace_migration(project_root=project_root)

    assert report["applied"] is True
    assert report["verified"]["ok"] is True
    assert (target_workspace / "agents" / "agents.json").read_text(encoding="utf-8") == '{"agents":["new"]}\n'
    manifest = target_workspace / migration.WORKSPACE_MANIFEST_NAME
    assert manifest.exists()
    assert report["manifest"]["totals"]["fileCount"] == 1
    assert report["manifest"]["treeHash"].startswith("sha256:")


def test_workspace_migration_verify_detects_same_size_content_change(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    source_workspace = _seed_workspace(project_root, content="abc\n")
    target_workspace = data_home / "workspace"
    (target_workspace / "agents").mkdir(parents=True)
    (target_workspace / "agents" / "agents.json").write_text("xyz\n", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))

    report = migration.verify_workspace_migration(project_root=project_root)

    assert report["verified"]["ok"] is False
    assert report["verified"]["mismatchCount"] == 1
    assert report["verified"]["mismatches"][0]["relativePath"] == "agents"
    assert source_workspace.exists()


def test_workspace_migration_status_is_manifest_based_and_shallow(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    target_workspace = data_home / "workspace"
    _seed_workspace(project_root)
    (target_workspace / "agents").mkdir(parents=True)
    (target_workspace / "agents" / "agents.json").write_text('{"agents":["old"]}\n', encoding="utf-8")
    (target_workspace / "memory").mkdir(parents=True)
    (target_workspace / "memory" / "memory.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)
    migration.finalize_external_workspace(
        data_home=data_home,
        enforce_required_top_level_entries=True,
    )

    def fail_full_verify(**_kwargs):
        raise AssertionError("status must not run source-target full verification")

    monkeypatch.setattr(migration, "verify_workspace_migration", fail_full_verify)

    status = migration.get_workspace_migration_status(project_root=project_root)

    assert status["verification"]["ok"] is True
    assert status["verification"]["verificationMode"] == "target_manifest_presence_and_required_entries"
    assert status["source"]["summaryMode"] == "shallow"
    assert status["target"]["summaryMode"] == "shallow"
    assert status["legacyCleanup"]["canExecute"] is False
    assert status["legacyCleanup"]["requiresPreview"] is True


def test_workspace_migration_status_detects_missing_required_source_entries(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    target_workspace = data_home / "workspace"
    _seed_workspace(project_root)
    (project_root / "workspace" / "modes").mkdir()
    (project_root / "workspace" / "modes" / "chat.json").write_text('{"mode":"chat"}\n', encoding="utf-8")
    (target_workspace / "agents").mkdir(parents=True)
    (target_workspace / "agents" / "agents.json").write_text('{"agents":["new"]}\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)
    migration.finalize_external_workspace(
        data_home=data_home,
        enforce_required_top_level_entries=True,
    )

    status = migration.get_workspace_migration_status(project_root=project_root)

    assert status["verification"]["ok"] is False
    assert "target_missing_required_entry:modes" in status["verification"]["blockedReasons"]
    assert status["verification"]["requiredTopLevelEntries"] == ["agents", "modes"]


def test_finalize_external_workspace_uses_project_root_context(tmp_path, monkeypatch):
    other_root = tmp_path / "other-project"
    other_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()

    data_home = tmp_path / "operator-data"
    data_home.mkdir()
    target_workspace = data_home / "workspace"
    (target_workspace / "memory").mkdir(parents=True)
    (target_workspace / "memory" / "memory.json").write_text("{}\n", encoding="utf-8")

    # Source workspace under other_root is empty so default required list is empty.
    monkeypatch.setattr(migration, "PROJECT_ROOT", other_root)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))

    default_finalized = migration.finalize_external_workspace(data_home=data_home)
    assert default_finalized["verification"]["ok"] is True

    # Source workspace under project_root contains required directories.
    (project_root / "workspace" / "agents").mkdir(parents=True)
    (project_root / "workspace" / "modes").mkdir(parents=True)
    override_finalized = migration.finalize_external_workspace(
        data_home=data_home,
        project_root=project_root,
        enforce_required_top_level_entries=True,
    )

    assert override_finalized["verification"]["ok"] is False
    assert "target_missing_required_entry:modes" in override_finalized["verification"]["blockedReasons"]
    assert override_finalized["verification"]["requiredTopLevelEntries"] == ["agents", "modes"]


def test_legacy_workspace_cleanup_requires_verified_target(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    _seed_workspace(project_root)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))

    preview = migration.preview_legacy_workspace_cleanup(project_root=project_root)

    assert preview["canExecute"] is False
    assert "target_workspace_missing" in preview["blockedReasons"]
    assert "migration_not_verified" in preview["blockedReasons"]
    with pytest.raises(migration.WorkspaceDataMigrationError):
        migration.execute_legacy_workspace_cleanup(
            project_root=project_root,
            confirmation_phrase=migration.LEGACY_WORKSPACE_CLEANUP_CONFIRMATION,
        )


def test_legacy_workspace_cleanup_deletes_only_after_verified_target_and_exact_phrase(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    source_workspace = _seed_workspace(project_root)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    migration.apply_workspace_migration(project_root=project_root)

    with pytest.raises(migration.WorkspaceDataMigrationError):
        migration.execute_legacy_workspace_cleanup(project_root=project_root, confirmation_phrase="delete")

    preview = migration.preview_legacy_workspace_cleanup(project_root=project_root)
    assert preview["canExecute"] is True
    result = migration.execute_legacy_workspace_cleanup(
        project_root=project_root,
        confirmation_phrase=migration.LEGACY_WORKSPACE_CLEANUP_CONFIRMATION,
    )

    assert result["deleted"]["status"] == "deleted"
    assert not source_workspace.exists()
    assert (data_home / "workspace" / "agents" / "agents.json").exists()


def test_legacy_workspace_cleanup_allows_manifest_verified_target_without_source_equality(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    source_workspace = _seed_workspace(project_root)
    (source_workspace / "debug-noise.log").write_text("old noisy data", encoding="utf-8")
    target_workspace = data_home / "workspace"
    (target_workspace / "memory").mkdir(parents=True)
    (target_workspace / "memory" / "memory.json").write_text("{}\n", encoding="utf-8")
    (target_workspace / "agents").mkdir(parents=True)
    (target_workspace / "agents" / "agents.json").write_text('{"agents":["legacy-only"]}\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)
    finalized = migration.finalize_external_workspace(data_home=data_home)

    assert finalized["verification"]["ok"] is True
    preview = migration.preview_legacy_workspace_cleanup(project_root=project_root)
    result = migration.execute_legacy_workspace_cleanup(
        project_root=project_root,
        confirmation_phrase=migration.LEGACY_WORKSPACE_CLEANUP_CONFIRMATION,
    )

    assert preview["canExecute"] is True
    assert preview["verification"]["verificationMode"] == "target_manifest_self_check"
    assert result["deleted"]["status"] == "deleted"
    assert not source_workspace.exists()
    assert (target_workspace / "memory" / "memory.json").exists()
    assert not (target_workspace / "agents" / "agents.json").exists()


def test_legacy_workspace_cleanup_checks_source_required_entries_not_manifest(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    _seed_workspace(project_root)
    (project_root / "workspace" / "modes").mkdir()
    (project_root / "workspace" / "modes" / "chat.json").write_text('{"mode":"chat"}\n', encoding="utf-8")
    target_workspace = data_home / "workspace"
    (target_workspace / "agents").mkdir(parents=True)
    (target_workspace / "agents" / "agents.json").write_text('{"agents":["legacy-only"]}\n', encoding="utf-8")
    migration.write_workspace_manifest(target_workspace, required_top_level_entries=["agents"])
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)

    preview = migration.preview_legacy_workspace_cleanup(project_root=project_root)

    assert preview["canExecute"] is False
    assert "target_missing_required_entry:modes" in preview["blockedReasons"]


def test_legacy_workspace_cleanup_blocks_required_entry_file_instead_of_directory(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    _seed_workspace(project_root)
    (project_root / "workspace" / "modes").mkdir()
    (project_root / "workspace" / "modes" / "chat.json").write_text('{"mode":"chat"}\n', encoding="utf-8")
    target_workspace = data_home / "workspace"
    (target_workspace / "agents").mkdir(parents=True)
    (target_workspace / "agents" / "agents.json").write_text('{"agents":["legacy-only"]}\n', encoding="utf-8")
    (target_workspace / "modes").write_text("legacy file instead of dir", encoding="utf-8")
    migration.write_workspace_manifest(target_workspace, required_top_level_entries=["agents", "modes"])
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)

    preview = migration.preview_legacy_workspace_cleanup(project_root=project_root)

    assert preview["canExecute"] is False
    assert "target_missing_required_entry:modes" in preview["blockedReasons"]


def test_legacy_workspace_cleanup_blocks_stale_target_manifest(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    _seed_workspace(project_root)
    target_workspace = data_home / "workspace"
    (target_workspace / "memory").mkdir(parents=True)
    (target_workspace / "memory" / "memory.json").write_text("{}\n", encoding="utf-8")
    (target_workspace / "agents").mkdir(parents=True)
    (target_workspace / "agents" / "agents.json").write_text('{"agents":["legacy-only"]}\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)
    migration.finalize_external_workspace(data_home=data_home)
    (target_workspace / "memory" / "memory.json").write_text('{"changed":true}\n', encoding="utf-8")

    preview = migration.preview_legacy_workspace_cleanup(project_root=project_root)

    assert preview["canExecute"] is False
    assert "target_manifest_mismatch" in preview["blockedReasons"]
    assert "migration_not_verified" in preview["blockedReasons"]


def test_legacy_workspace_cleanup_retries_readonly_delete_errors(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    source_workspace = _seed_workspace(project_root)
    readonly_file = source_workspace / "readonly.bin"
    readonly_file.write_text("locked once", encoding="utf-8")
    target_workspace = data_home / "workspace"
    (target_workspace / "memory").mkdir(parents=True)
    (target_workspace / "memory" / "memory.json").write_text("{}\n", encoding="utf-8")
    (target_workspace / "agents").mkdir(parents=True)
    (target_workspace / "agents" / "agents.json").write_text('{"agents":["legacy-only"]}\n', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(migration, "PROJECT_ROOT", project_root)
    migration.finalize_external_workspace(data_home=data_home)
    original_rmtree = migration.shutil.rmtree
    calls = {"count": 0}

    def fake_rmtree(path, *, onexc=None):
        calls["count"] += 1
        if onexc and readonly_file.exists():
            onexc(os.unlink, str(readonly_file), PermissionError("readonly"))
        return original_rmtree(path)

    monkeypatch.setattr(migration.shutil, "rmtree", fake_rmtree)

    result = migration.execute_legacy_workspace_cleanup(
        project_root=project_root,
        confirmation_phrase=migration.LEGACY_WORKSPACE_CLEANUP_CONFIRMATION,
    )

    assert calls["count"] == 1
    assert result["deleted"]["status"] == "deleted"
    assert not source_workspace.exists()


def test_legacy_workspace_cleanup_blocks_symlink_entries(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    data_home = tmp_path / "operator-data"
    source_workspace = _seed_workspace(project_root)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    migration.apply_workspace_migration(project_root=project_root)
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    try:
        (source_workspace / "outside-link.txt").symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    preview = migration.preview_legacy_workspace_cleanup(project_root=project_root)

    assert preview["canExecute"] is False
    assert "legacy_workspace_contains_symlink" in preview["blockedReasons"]
