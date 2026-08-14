from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.infrastructure.storage_migration import (
    StorageMigrationError,
    apply_storage_migration,
    plan_storage_migration,
    rollback_storage_switch,
)
from vibelution_storage import (
    project_memory_migration_state_path,
    resolve_active_project_storage_paths,
    resolve_project_memory_home,
    resolve_project_storage_paths,
    storage_migration_state_path,
)


def _project(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    identity = project / ".vibelution" / "project.json"
    identity.parent.mkdir()
    identity.write_text(
        json.dumps({"schemaVersion": 1, "projectId": "test-vibelution"}) + "\n",
        encoding="utf-8",
    )
    projects_home = tmp_path / "external" / "projects"
    data_home = tmp_path / "legacy-operator-data"
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(projects_home))
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    return project, projects_home, data_home


def test_plan_maps_all_legacy_categories_without_writing(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    (data_home / "workspace").mkdir(parents=True)
    (data_home / "workspace" / "agent.json").write_text("data\n", encoding="utf-8")
    (project / ".runtime").mkdir()
    (project / ".runtime" / "state.json").write_text("runtime\n", encoding="utf-8")
    (project / "logs").mkdir()
    (project / "logs" / "app.log").write_text("log\n", encoding="utf-8")
    (project / ".docs" / "project-memory").mkdir(parents=True)
    (project / ".docs" / "project-memory" / "INDEX.md").write_text("memory\n", encoding="utf-8")

    plan = plan_storage_migration(project)

    assert {entry.category for entry in plan.entries} == {
        "operator_data",
        "runtime",
        "logs",
        "project_memory",
    }
    assert plan.total_files == 4
    assert plan.total_bytes > 0
    assert len(plan.aggregate_sha256) == 64
    assert not resolve_project_storage_paths(project).instance_home.exists()


def test_apply_copies_verifies_switches_and_keeps_legacy_data(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    runtime_source = project / ".runtime" / "state.json"
    runtime_source.parent.mkdir()
    runtime_source.write_text("runtime\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)

    result = apply_storage_migration(project)

    assert result["status"] == "completed"
    assert result["copiedFiles"] == 2
    assert (target.data / "workspace" / "agent.json").read_text(encoding="utf-8") == "data\n"
    assert (target.runtime / "state.json").read_text(encoding="utf-8") == "runtime\n"
    assert source.exists()
    assert runtime_source.exists()
    assert storage_migration_state_path(target).exists()
    assert project_memory_migration_state_path(target).exists()
    assert resolve_active_project_storage_paths(project) == target


def test_project_memory_switch_is_shared_with_linked_worktrees(tmp_path, monkeypatch):
    project, _projects_home, _data_home = _project(tmp_path, monkeypatch)
    legacy_memory = project / ".docs" / "project-memory"
    legacy_memory.mkdir(parents=True)
    (legacy_memory / "INDEX.md").write_text("memory\n", encoding="utf-8")
    linked = tmp_path / "linked-worktree"
    linked.mkdir()
    (linked / ".git").write_text(
        f"gitdir: {project / '.git' / 'worktrees' / 'linked-worktree'}\n",
        encoding="utf-8",
    )
    linked_identity = linked / ".vibelution" / "project.json"
    linked_identity.parent.mkdir()
    linked_identity.write_text(
        json.dumps({"schemaVersion": 1, "projectId": "test-vibelution"}) + "\n",
        encoding="utf-8",
    )

    assert resolve_project_memory_home(project) == legacy_memory
    assert resolve_project_memory_home(linked) == legacy_memory

    apply_storage_migration(project)
    target = resolve_project_storage_paths(project)

    assert (target.memory / "INDEX.md").read_text(encoding="utf-8") == "memory\n"
    assert resolve_project_memory_home(project) == target.memory
    assert resolve_project_memory_home(linked) == target.memory

    rollback_storage_switch(project)

    assert resolve_project_memory_home(project) == legacy_memory
    assert resolve_project_memory_home(linked) == legacy_memory


def test_independent_clones_register_memory_sources_without_cross_switching(
    tmp_path, monkeypatch
):
    projects_home = tmp_path / "external" / "projects"
    data_home = tmp_path / "legacy-operator-data"
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(projects_home))
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    clones = []
    for name, filename in (("clone-a", "A.md"), ("clone-b", "B.md")):
        clone = tmp_path / name
        (clone / ".git").mkdir(parents=True)
        identity = clone / ".vibelution" / "project.json"
        identity.parent.mkdir()
        identity.write_text(
            json.dumps({"schemaVersion": 1, "projectId": "test-vibelution"}) + "\n",
            encoding="utf-8",
        )
        memory = clone / ".docs" / "project-memory"
        memory.mkdir(parents=True)
        (memory / filename).write_text(f"{name}\n", encoding="utf-8")
        clones.append((clone, memory))
    (clone_a, memory_a), (clone_b, memory_b) = clones

    apply_storage_migration(clone_a)
    target = resolve_project_storage_paths(clone_a)

    assert resolve_project_memory_home(clone_a) == target.memory
    assert resolve_project_memory_home(clone_b) == memory_b
    marker_path = project_memory_migration_state_path(target)
    marker_after_a = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker_after_a["targetRoot"] == str(target.memory)
    assert [item["sourceRoot"] for item in marker_after_a["sources"]] == [str(memory_a)]

    apply_storage_migration(clone_b)

    assert resolve_project_memory_home(clone_b) == target.memory
    assert (target.memory / "A.md").read_text(encoding="utf-8") == "clone-a\n"
    assert (target.memory / "B.md").read_text(encoding="utf-8") == "clone-b\n"
    marker_after_b = json.loads(marker_path.read_text(encoding="utf-8"))
    assert {item["sourceRoot"] for item in marker_after_b["sources"]} == {
        str(memory_a),
        str(memory_b),
    }

    rollback = rollback_storage_switch(clone_a)

    assert rollback["projectMemoryRegistrationRemoved"] is True
    assert rollback["remainingProjectMemorySources"] == 1
    assert resolve_project_memory_home(clone_a) == memory_a
    assert resolve_project_memory_home(clone_b) == target.memory
    marker_after_rollback = json.loads(marker_path.read_text(encoding="utf-8"))
    assert [item["sourceRoot"] for item in marker_after_rollback["sources"]] == [str(memory_b)]


def test_independent_clone_memory_conflict_keeps_unregistered_clone_on_legacy(
    tmp_path, monkeypatch
):
    projects_home = tmp_path / "external" / "projects"
    data_home = tmp_path / "legacy-operator-data"
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(projects_home))
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    clones = []
    for name, content in (("clone-a", "memory-a\n"), ("clone-b", "memory-b\n")):
        clone = tmp_path / name
        (clone / ".git").mkdir(parents=True)
        identity = clone / ".vibelution" / "project.json"
        identity.parent.mkdir()
        identity.write_text(
            json.dumps({"schemaVersion": 1, "projectId": "test-vibelution"}) + "\n",
            encoding="utf-8",
        )
        memory = clone / ".docs" / "project-memory"
        memory.mkdir(parents=True)
        (memory / "INDEX.md").write_text(content, encoding="utf-8")
        clones.append((clone, memory))
    (clone_a, memory_a), (clone_b, memory_b) = clones

    apply_storage_migration(clone_a)
    target = resolve_project_storage_paths(clone_a)

    assert resolve_project_memory_home(clone_a) == target.memory
    assert resolve_project_memory_home(clone_b) == memory_b
    with pytest.raises(StorageMigrationError, match="destination conflicts"):
        apply_storage_migration(clone_b)

    assert resolve_project_memory_home(clone_b) == memory_b
    assert (memory_b / "INDEX.md").read_text(encoding="utf-8") == "memory-b\n"
    marker = json.loads(project_memory_migration_state_path(target).read_text(encoding="utf-8"))
    assert [item["sourceRoot"] for item in marker["sources"]] == [str(memory_a)]

def test_conflict_fails_without_switching_or_overwriting(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("legacy\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)
    destination = target.data / "workspace" / "agent.json"
    destination.parent.mkdir(parents=True)
    destination.write_text("newer\n", encoding="utf-8")

    with pytest.raises(StorageMigrationError, match="destination conflicts"):
        apply_storage_migration(project)

    assert destination.read_text(encoding="utf-8") == "newer\n"
    assert not storage_migration_state_path(target).exists()
    assert resolve_active_project_storage_paths(project).migrated is False


def test_rollback_archives_marker_without_deleting_copied_or_legacy_data(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)
    apply_storage_migration(project)

    result = rollback_storage_switch(project)

    assert result["rolledBack"] is True
    assert result["copiedDataRetained"] is True
    assert not storage_migration_state_path(target).exists()
    assert not project_memory_migration_state_path(target).exists()
    assert Path(str(result["archivedMarkerPath"])).exists()
    assert Path(str(result["archivedProjectMemoryMarkerPath"])).exists()
    assert (target.data / "workspace" / "agent.json").exists()
    assert source.exists()
    assert resolve_active_project_storage_paths(project).migrated is False
