from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibelution_storage import (
    PROJECTS_HOME_ENV,
    ProjectIdentityError,
    ProjectStorageMigrationStateError,
    ensure_project_storage,
    instance_id_for_project,
    legacy_project_storage_paths,
    load_project_identity,
    resolve_active_project_storage_paths,
    resolve_project_data_home,
    resolve_project_memory_home,
    resolve_project_storage_paths,
    resolve_project_workspace_home,
    project_memory_migration_state_path,
    storage_migration_state_path,
)
from core.infrastructure.codex_sandbox.environment import sandbox_temp_root


def _write_identity(project_root: Path, project_id: str = "test-vibelution") -> Path:
    path = project_root / ".vibelution" / "project.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schemaVersion": 1, "projectId": project_id}) + "\n",
        encoding="utf-8",
    )
    return path


def test_project_identity_is_read_from_tracked_source_file(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    source = _write_identity(project_root, "ccdawn-vibelution")

    identity = load_project_identity(project_root)

    assert identity.project_id == "ccdawn-vibelution"
    assert identity.schema_version == 1
    assert identity.source_path == source


def test_missing_or_invalid_project_identity_fails_without_generating_source_files(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(ProjectIdentityError, match="missing tracked project identity"):
        load_project_identity(project_root)
    assert list(project_root.iterdir()) == []

    _write_identity(project_root, "Invalid Project Id")
    with pytest.raises(ProjectIdentityError, match="invalid projectId"):
        load_project_identity(project_root)


def test_mutable_paths_are_external_and_instance_isolated(monkeypatch, tmp_path):
    projects_home = tmp_path / "local-app-data" / "projects"
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    first = tmp_path / "first-checkout"
    second = tmp_path / "second-checkout"
    first.mkdir()
    second.mkdir()
    _write_identity(first)
    _write_identity(second)

    first_paths = resolve_project_storage_paths(first)
    second_paths = resolve_project_storage_paths(second)

    assert first_paths.project_home == projects_home / "test-vibelution"
    assert first_paths.instance_id == instance_id_for_project(first)
    assert first_paths.instance_home == first_paths.project_home / "instances" / first_paths.instance_id
    assert first_paths.data == first_paths.instance_home / "data"
    assert first_paths.workspace == first_paths.data / "workspace"
    assert first_paths.runtime == first_paths.instance_home / "runtime"
    assert first_paths.logs == first_paths.instance_home / "logs"
    assert first_paths.cache == first_paths.instance_home / "cache"
    assert first_paths.memory == first_paths.project_home / "memory"
    assert second_paths.instance_id != first_paths.instance_id
    assert second_paths.instance_home != first_paths.instance_home
    assert second_paths.memory == first_paths.memory


def test_ensure_project_storage_does_not_create_checkout_artifacts(monkeypatch, tmp_path):
    projects_home = tmp_path / "external" / "projects"
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    project_root = tmp_path / "project"
    project_root.mkdir()
    identity_path = _write_identity(project_root)
    before = {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }

    paths = ensure_project_storage(resolve_project_storage_paths(project_root))

    assert all(path.is_dir() for path in (paths.data, paths.runtime, paths.logs, paths.memory, paths.cache))
    after = {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }
    assert after == before == {identity_path.relative_to(project_root): identity_path.read_bytes()}


def test_project_data_defaults_to_canonical_root_and_honors_explicit_env(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_identity(project_root)
    projects_home = tmp_path / "project-state"
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    monkeypatch.delenv("VIBELUTION_DATA_HOME", raising=False)
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "missing-config.toml"))

    canonical = resolve_project_storage_paths(project_root)
    assert resolve_project_data_home(project_root) == canonical.data
    assert resolve_project_workspace_home(project_root) == canonical.data / "workspace"

    explicit = tmp_path / "operator-selected-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(explicit))
    assert resolve_project_data_home(project_root) == explicit


def test_primary_checkout_keeps_legacy_paths_until_verified_migration(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    _write_identity(project_root)
    legacy_runtime = project_root / ".runtime"
    legacy_runtime.mkdir()
    (legacy_runtime / "state.json").write_text("{}\n", encoding="utf-8")
    projects_home = tmp_path / "project-state"
    legacy_data = tmp_path / "legacy-data"
    legacy_data.mkdir()
    (legacy_data / "agents.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(legacy_data))

    target = resolve_project_storage_paths(project_root)
    active_before = resolve_active_project_storage_paths(project_root)

    assert active_before == legacy_project_storage_paths(project_root, target=target)
    assert active_before.runtime == legacy_runtime
    assert active_before.data == legacy_data
    assert active_before.migrated is False

    state_path = storage_migration_state_path(target)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "completed",
                "projectId": target.project_id,
                "instanceId": target.instance_id,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert resolve_active_project_storage_paths(project_root) == target


def test_present_invalid_storage_marker_fails_closed_without_legacy_fallback(
    monkeypatch, tmp_path
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    _write_identity(project_root)
    legacy_runtime = project_root / ".runtime"
    legacy_runtime.mkdir()
    (legacy_runtime / "state.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(tmp_path / "project-state"))

    target = resolve_project_storage_paths(project_root)
    marker_path = storage_migration_state_path(target)
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ProjectStorageMigrationStateError,
        match="storage_migration_marker_invalid",
    ):
        resolve_active_project_storage_paths(project_root)

    marker_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "completed",
                "projectId": target.project_id,
                "instanceId": "wrong-instance",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ProjectStorageMigrationStateError,
        match="storage_migration_marker_invalid",
    ):
        resolve_active_project_storage_paths(project_root)


def test_linked_worktree_uses_integration_root_legacy_memory_before_shared_switch(
    monkeypatch, tmp_path
):
    integration_root = tmp_path / "project"
    integration_root.mkdir()
    (integration_root / ".git" / "worktrees" / "linked").mkdir(parents=True)
    _write_identity(integration_root)
    legacy_memory = integration_root / ".docs" / "project-memory"
    legacy_memory.mkdir(parents=True)
    (legacy_memory / "INDEX.md").write_text("memory\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text(
        f"gitdir: {integration_root / '.git' / 'worktrees' / 'linked'}\n",
        encoding="utf-8",
    )
    _write_identity(linked)
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(tmp_path / "project-state"))

    assert resolve_project_memory_home(linked) == legacy_memory


def test_project_memory_marker_requires_matching_target_and_source(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    _write_identity(project_root)
    legacy_memory = project_root / ".docs" / "project-memory"
    legacy_memory.mkdir(parents=True)
    (legacy_memory / "INDEX.md").write_text("memory\n", encoding="utf-8")
    projects_home = tmp_path / "project-state"
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))
    target = resolve_project_storage_paths(project_root)
    marker_path = project_memory_migration_state_path(target)
    marker_path.parent.mkdir(parents=True)

    def write_marker(*, target_root: Path, source_root: Path) -> None:
        marker_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "status": "completed",
                    "projectId": target.project_id,
                    "targetRoot": str(target_root),
                    "sources": [{"sourceRoot": str(source_root)}],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    marker_path.write_text("{not-json\n", encoding="utf-8")
    with pytest.raises(
        ProjectStorageMigrationStateError,
        match="project_memory_migration_marker_invalid",
    ):
        resolve_project_memory_home(project_root)

    write_marker(target_root=tmp_path / "wrong-target", source_root=legacy_memory)
    with pytest.raises(
        ProjectStorageMigrationStateError,
        match="project_memory_migration_marker_invalid",
    ):
        resolve_project_memory_home(project_root)

    write_marker(target_root=target.memory, source_root=tmp_path / "other-clone-memory")
    assert resolve_project_memory_home(project_root) == legacy_memory

    write_marker(target_root=target.memory, source_root=legacy_memory)
    assert resolve_project_memory_home(project_root) == target.memory


def test_codex_sandbox_temp_is_external_for_identified_checkout(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_identity(project_root)
    projects_home = tmp_path / "project-state"
    monkeypatch.setenv(PROJECTS_HOME_ENV, str(projects_home))

    temp_root = sandbox_temp_root(project_root)

    assert temp_root.is_relative_to(projects_home)
    assert not temp_root.is_relative_to(project_root)
