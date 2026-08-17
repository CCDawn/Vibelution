from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from core.infrastructure.storage_migration import (
    StorageMigrationEntry,
    StorageMigrationError,
    apply_storage_migration,
    assess_post_cutover_delta,
    assess_storage_migration_readiness,
    plan_storage_migration,
    rollback_storage_switch,
)
from core.infrastructure import storage_migration as storage_migration_module
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


def _sqlite_quarantine_dirs(parent: Path) -> list[Path]:
    return [
        path
        for path in parent.iterdir()
        if path.is_dir()
        and path.name.startswith(storage_migration_module._SQLITE_QUARANTINE_DIR_PREFIX)
    ]


def test_sqlite_readiness_does_not_create_source_sidecars(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()
    source_members = storage_migration_module._sqlite_bundle_paths(database)
    before = {
        path.name: path.read_bytes() if path.is_file() else None for path in source_members
    }

    readiness = assess_storage_migration_readiness(project)

    after = {
        path.name: path.read_bytes() if path.is_file() else None for path in source_members
    }
    assert readiness["ready"] is True
    assert readiness["sqliteIntegrity"]["ok"] is True
    assert readiness["quiescence"]["stable"] is True
    assert after == before


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


def test_plan_keeps_operator_data_canonical_and_archives_project_workspace_conflict(
    tmp_path, monkeypatch
):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    operator_source = data_home / "workspace" / "agents" / "agents.json"
    operator_source.parent.mkdir(parents=True)
    operator_source.write_text('{"agents":["operator"]}\n', encoding="utf-8")
    project_source = project / "workspace" / "agents" / "agents.json"
    project_source.parent.mkdir(parents=True)
    project_source.write_text('{"agents":["project"]}\n', encoding="utf-8")
    target = resolve_project_storage_paths(project)

    plan = plan_storage_migration(project)

    entries = {entry.category: entry for entry in plan.entries}
    assert plan.archived_conflicts == 1
    assert Path(entries["operator_data"].destination) == (
        target.data / "workspace" / "agents" / "agents.json"
    )
    assert Path(entries["project_workspace_conflict_archive"].destination) == (
        target.data
        / "backups"
        / "storage-source-conflicts"
        / "project_workspace"
        / "agents"
        / "agents.json"
    )
    assert not target.instance_home.exists()


def test_plan_reports_unreadable_legacy_source_without_raw_traceback(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agents" / "agents.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}\n", encoding="utf-8")

    def deny_read(path):
        raise PermissionError("locked")

    monkeypatch.setattr(
        "core.infrastructure.storage_migration._sha256_file",
        deny_read,
    )

    with pytest.raises(StorageMigrationError, match=r"cannot read legacy source.*agents\.json"):
        plan_storage_migration(project)


def test_plan_skips_ephemeral_lock_files_and_reports_the_count(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    durable = data_home / "workspace" / "chat" / "chat_state.json"
    durable.parent.mkdir(parents=True)
    durable.write_text("{}\n", encoding="utf-8")
    lock = durable.with_name(".chat_state.lock")
    lock.write_text("", encoding="utf-8")

    plan = plan_storage_migration(project)

    assert plan.skipped_ephemeral_files == 1
    assert [entry.relative_path for entry in plan.entries] == [
        "workspace/chat/chat_state.json"
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path contract")
def test_copy_and_verify_supports_windows_extended_length_destination(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("long-path\n", encoding="utf-8")
    destination = tmp_path / "target"
    for index in range(5):
        destination /= f"segment-{index}-" + ("x" * 48)
    destination /= "destination.json"
    assert len(str(destination)) > 260
    entry = StorageMigrationEntry(
        source=str(source),
        destination=str(destination),
        category="project_backups",
        relative_path="destination.json",
        size=source.stat().st_size,
        sha256=storage_migration_module._sha256_file(source),
    )

    copied, reused = storage_migration_module._copy_and_verify_entries((entry,))

    assert (copied, reused) == (1, 0)
    assert storage_migration_module._io_path(destination).read_text(encoding="utf-8") == (
        "long-path\n"
    )


def test_apply_preserves_project_workspace_conflict_as_recoverable_archive(
    tmp_path, monkeypatch
):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    operator_source = data_home / "workspace" / "agents" / "agents.json"
    operator_source.parent.mkdir(parents=True)
    operator_source.write_text('{"agents":["operator"]}\n', encoding="utf-8")
    project_source = project / "workspace" / "agents" / "agents.json"
    project_source.parent.mkdir(parents=True)
    project_source.write_text('{"agents":["project"]}\n', encoding="utf-8")
    target = resolve_project_storage_paths(project)

    result = apply_storage_migration(project)

    canonical = target.data / "workspace" / "agents" / "agents.json"
    archive = (
        target.data
        / "backups"
        / "storage-source-conflicts"
        / "project_workspace"
        / "agents"
        / "agents.json"
    )
    assert result["status"] == "completed"
    assert result["archivedConflicts"] == 1
    assert result["skippedEphemeralFiles"] == 0
    assert canonical.read_text(encoding="utf-8") == '{"agents":["operator"]}\n'
    assert archive.read_text(encoding="utf-8") == '{"agents":["project"]}\n'
    assert operator_source.exists()
    assert project_source.exists()
    assert resolve_active_project_storage_paths(project) == target


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
    with pytest.raises(StorageMigrationError, match="destination_conflict"):
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

    with pytest.raises(StorageMigrationError, match="destination_conflict"):
        apply_storage_migration(project)

    assert destination.read_text(encoding="utf-8") == "newer\n"
    assert not storage_migration_state_path(target).exists()
    assert resolve_active_project_storage_paths(project).migrated is False


def test_readiness_blocks_active_claim_and_apply(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    registry = project / ".docs" / "project-memory" / "agent-registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "workClaims": {
                    "claim-1": {
                        "status": "active",
                        "branch": "codex/test",
                        "worktree": str(project),
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is False
    assert readiness["cachePolicy"] == "cold_rebuild"
    assert any(blocker["code"] == "active_work_present" for blocker in readiness["blockers"])
    with pytest.raises(StorageMigrationError, match="readiness blocked"):
        apply_storage_migration(project)


def test_readiness_fail_closed_when_runtime_manager_state_unreadable(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)
    manager_dir = target.runtime / "runtime-manager"
    manager_dir.mkdir(parents=True)
    (manager_dir / "state.json").write_text("{not-json", encoding="utf-8")

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is False
    assert any(
        blocker["code"] == "runtime_writer_state_uncertain" for blocker in readiness["blockers"]
    )


def test_readiness_blocks_destination_conflict_without_apply(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("legacy\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)
    destination = target.data / "workspace" / "agent.json"
    destination.parent.mkdir(parents=True)
    destination.write_text("newer\n", encoding="utf-8")

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is False
    assert readiness["destinationConflicts"]
    assert any(blocker["code"] == "destination_conflict" for blocker in readiness["blockers"])


def test_apply_aborts_when_source_changes_without_marker(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("legacy\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)
    original_plan = plan_storage_migration(project)

    original_copy = storage_migration_module._copy_and_verify_entries

    def mutate_then_copy(*args, **kwargs):
        source.write_text("changed\n", encoding="utf-8")
        return original_copy(*args, **kwargs)

    monkeypatch.setattr(storage_migration_module, "_copy_and_verify_entries", mutate_then_copy)

    with pytest.raises(StorageMigrationError, match="legacy source changed during copy"):
        apply_storage_migration(project)

    assert not storage_migration_state_path(target).exists()
    assert _plan_signature(plan_storage_migration(project)) != _plan_signature(original_plan)


def test_sqlite_bundle_is_discovered_copied_and_sidecars_are_not_plan_entries(
    tmp_path, monkeypatch
):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()
    target = resolve_project_storage_paths(project)

    plan = plan_storage_migration(project)
    bundles = storage_migration_module._discover_sqlite_bundles(plan)

    assert bundles
    assert all(not entry.relative_path.endswith("-wal") for entry in plan.entries)
    apply_storage_migration(project)
    copied = target.data / "workspace" / "state.sqlite"
    assert copied.exists()
    ok, detail = storage_migration_module._sqlite_quick_check(copied)
    assert ok, detail


def test_corrupt_sqlite_blocks_readiness_and_apply(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "broken.sqlite"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"not-a-database")
    target = resolve_project_storage_paths(project)

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is False
    assert any(blocker["code"] == "sqlite_integrity_failed" for blocker in readiness["blockers"])
    with pytest.raises(StorageMigrationError, match="readiness blocked"):
        apply_storage_migration(project)
    assert not storage_migration_state_path(target).exists()


def test_legacy_cache_is_not_migrated_and_readiness_reports_cold_rebuild(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    cache_file = project / ".cache" / "stale.bin"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"stale")

    plan = plan_storage_migration(project)
    readiness = assess_storage_migration_readiness(project)

    assert all(
        str(resolve_project_storage_paths(project).cache).lower()
        not in entry.destination.lower()
        for entry in plan.entries
    )
    assert readiness["cachePolicy"] == "cold_rebuild"
    assert readiness["ready"] is True


def test_apply_re_runs_readiness_gate(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    calls = {"count": 0}
    original = storage_migration_module.assess_storage_migration_readiness

    def counting_readiness(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        storage_migration_module,
        "assess_storage_migration_readiness",
        counting_readiness,
    )

    apply_storage_migration(project)

    assert calls["count"] >= 1


def test_rollback_rejects_post_cutover_delta_and_keeps_marker(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)
    apply_storage_migration(project)
    target.runtime.mkdir(parents=True, exist_ok=True)
    (target.runtime / "post-cutover.txt").write_text("new write\n", encoding="utf-8")

    with pytest.raises(StorageMigrationError, match="reverse_delta_reconcile_required"):
        rollback_storage_switch(project)

    assert storage_migration_state_path(target).exists()
    assert resolve_active_project_storage_paths(project).migrated is True


def _plan_signature(plan):
    return storage_migration_module._plan_signature(plan)


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


def _sqlite_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def test_bundle_signature_changes_when_only_wal_changes(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    plan_after_first = plan_storage_migration(project)
    entry = next(entry for entry in plan_after_first.entries if entry.relative_path.endswith("state.sqlite"))
    first_signature = entry.bundle_fingerprint
    first_main_hash = entry.sha256
    connection.execute("INSERT INTO t VALUES (2)")
    connection.commit()
    plan_after_second = plan_storage_migration(project)
    entry_after_second = next(
        entry for entry in plan_after_second.entries if entry.relative_path.endswith("state.sqlite")
    )
    connection.close()

    assert entry_after_second.bundle_fingerprint != first_signature
    assert entry_after_second.sha256 == first_main_hash


def test_destination_conflict_when_target_missing_wal_with_committed_data(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    target = resolve_project_storage_paths(project)
    destination = target.data / "workspace" / "state.sqlite"
    destination.parent.mkdir(parents=True)
    shutil.copy2(database, destination)
    connection.execute("INSERT INTO t VALUES (2)")
    connection.commit()
    source_rows = connection.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    connection.close()
    destination_rows = sqlite3.connect(destination).execute("SELECT COUNT(*) FROM t").fetchone()[0]

    readiness = assess_storage_migration_readiness(project)

    assert source_rows == 2
    assert destination_rows == 1
    assert readiness["ready"] is False
    assert any(blocker["code"] == "destination_conflict" for blocker in readiness["blockers"])
    with pytest.raises(StorageMigrationError, match="destination_conflict"):
        apply_storage_migration(project)
    assert not storage_migration_state_path(target).exists()


def test_apply_fails_closed_when_wal_changes_during_copy(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    target = resolve_project_storage_paths(project)
    original_copy2 = shutil.copy2

    def copy2_then_commit(src, dst, *args, **kwargs):
        result = original_copy2(src, dst, *args, **kwargs)
        if str(src).endswith("-wal") and Path(dst).parent.name.startswith(
            ".migration-staging-"
        ):
            connection.execute("INSERT INTO t VALUES (2)")
            connection.commit()
        return result

    monkeypatch.setattr(shutil, "copy2", copy2_then_commit)

    with pytest.raises(StorageMigrationError, match=storage_migration_module.SQLITE_BUNDLE_CHANGED_DURING_COPY):
        apply_storage_migration(project)

    copied = target.data / "workspace" / "state.sqlite"
    assert not storage_migration_state_path(target).exists()
    assert not copied.exists()
    assert not copied.with_name(copied.name + "-wal").exists()
    assert not copied.with_name(copied.name + "-shm").exists()
    assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    connection.close()


def test_sqlite_bundle_copies_all_members_with_matching_rows(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.execute("INSERT INTO t VALUES (2)")
    connection.commit()
    source_rows = connection.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    source_members = storage_migration_module._sqlite_bundle_paths(database)
    source_before = {
        path.name: path.read_bytes() if path.is_file() else None for path in source_members
    }
    assert source_before[database.name + "-wal"] is not None
    assert source_before[database.name + "-shm"] is not None
    target = resolve_project_storage_paths(project)

    apply_storage_migration(project)

    source_after = {
        path.name: path.read_bytes() if path.is_file() else None for path in source_members
    }
    copied = target.data / "workspace" / "state.sqlite"
    copied_wal = copied.with_name(copied.name + "-wal")
    assert copied.exists()
    assert copied_wal.exists()
    ok, detail = storage_migration_module._sqlite_quick_check(copied)
    assert ok, detail
    with sqlite3.connect(copied) as copied_connection:
        destination_rows = copied_connection.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    assert source_after == source_before
    assert destination_rows == source_rows == 2
    connection.close()


def test_rollback_delta_detects_new_file_in_target_memory(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    memory = project / ".docs" / "project-memory"
    memory.mkdir(parents=True)
    (memory / "INDEX.md").write_text("memory\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)
    apply_storage_migration(project)
    (target.memory / "post-cutover.md").write_text("new memory\n", encoding="utf-8")

    with pytest.raises(StorageMigrationError, match="reverse_delta_reconcile_required"):
        rollback_storage_switch(project)

    assert storage_migration_state_path(target).exists()


def test_rollback_delta_detects_wal_shm_change(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    target = resolve_project_storage_paths(project)
    apply_storage_migration(project)
    copied = target.data / "workspace" / "state.sqlite"
    copied_wal = copied.with_name(copied.name + "-wal")
    copied_wal.write_bytes(copied_wal.read_bytes() + b"delta")

    with pytest.raises(StorageMigrationError, match="reverse_delta_reconcile_required"):
        rollback_storage_switch(project)

    assert storage_migration_state_path(target).exists()


def test_readiness_blocked_log_excludes_absolute_paths(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    registry = project / ".docs" / "project-memory" / "agent-registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"workClaims": {"claim-1": {"status": "active", "branch": "codex/test"}}}) + "\n",
        encoding="utf-8",
    )
    captured: list[dict[str, object]] = []

    def capture_event(event_name, payload, **kwargs):
        if event_name == "storage_migration.readiness_blocked":
            captured.append(dict(payload))

    monkeypatch.setattr(
        "core.runtime_manager.scene_logging.append_runtime_manager_file_event",
        capture_event,
    )

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is False
    assert captured
    payload = captured[0]
    assert payload["action"] == "apply"
    assert payload["reasonCodes"]
    assert payload["blockerCount"] >= 1
    assert payload.get("projectId") == "test-vibelution"
    assert "projectRoot" not in payload
    serialized = json.dumps(payload)
    assert str(project.resolve()) not in serialized


def test_sqlite_destination_conflict_preserves_preexisting_bundle(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    target = resolve_project_storage_paths(project)
    destination = target.data / "workspace" / "state.sqlite"
    destination.parent.mkdir(parents=True)
    shutil.copy2(database, destination)
    connection.execute("INSERT INTO t VALUES (2)")
    connection.commit()
    destination_wal = destination.with_name(destination.name + "-wal")
    if destination_wal.exists():
        destination_wal.unlink()
    before_main = destination.read_bytes()
    before_wal = destination_wal.read_bytes() if destination_wal.exists() else b""

    with pytest.raises(StorageMigrationError, match="destination_conflict"):
        apply_storage_migration(project)

    assert destination.read_bytes() == before_main
    assert (
        destination_wal.read_bytes() if destination_wal.exists() else b""
    ) == before_wal
    assert not storage_migration_state_path(target).exists()
    connection.close()


def test_readiness_blocks_orphan_sqlite_sidecars_without_main(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()
    target = resolve_project_storage_paths(project)
    orphan_wal = target.data / "workspace" / "state.sqlite-wal"
    orphan_wal.parent.mkdir(parents=True)
    orphan_wal.write_bytes(b"orphan-wal")

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is False
    assert any(blocker["code"] == "destination_conflict" for blocker in readiness["blockers"])


def test_apply_blocks_orphan_sqlite_sidecars_without_main(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()
    target = resolve_project_storage_paths(project)
    orphan_wal = target.data / "workspace" / "state.sqlite-wal"
    orphan_wal.parent.mkdir(parents=True)
    orphan_wal.write_bytes(b"orphan-wal")

    with pytest.raises(StorageMigrationError, match="destination_conflict"):
        apply_storage_migration(project)

    assert orphan_wal.read_bytes() == b"orphan-wal"
    assert not storage_migration_state_path(target).exists()


def test_sqlite_promote_is_no_clobber_when_destination_member_appears(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    target = resolve_project_storage_paths(project)
    destination = target.data / "workspace" / "state.sqlite"
    destination_wal = destination.with_name(destination.name + "-wal")
    original_link = os.link

    def link_with_concurrent_wal_at_atomic_promote(src, dst):
        dst_path = Path(dst)
        if dst_path.name.endswith("-wal"):
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.write_bytes(b"concurrent-wal")
        return original_link(src, dst)

    monkeypatch.setattr(os, "link", link_with_concurrent_wal_at_atomic_promote)

    with pytest.raises(
        StorageMigrationError,
        match=storage_migration_module.SQLITE_BUNDLE_DESTINATION_CONFLICT,
    ):
        apply_storage_migration(project)

    assert destination_wal.read_bytes() == b"concurrent-wal"
    assert not destination.exists()
    assert not storage_migration_state_path(target).exists()
    connection.close()


def test_sqlite_promote_atomic_no_clobber_preserves_concurrent_target_at_link_race(
    tmp_path, monkeypatch
):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    target = resolve_project_storage_paths(project)
    destination = target.data / "workspace" / "state.sqlite"
    original_link = os.link

    def link_with_concurrent_main_at_atomic_promote(src, dst):
        dst_path = Path(dst)
        if dst_path.name == "state.sqlite":
            dst_io = storage_migration_module._io_path(dst_path)
            dst_io.parent.mkdir(parents=True, exist_ok=True)
            dst_io.write_bytes(b"concurrent-main")
        return original_link(src, dst)

    monkeypatch.setattr(os, "link", link_with_concurrent_main_at_atomic_promote)

    with pytest.raises(
        StorageMigrationError,
        match=storage_migration_module.SQLITE_BUNDLE_DESTINATION_CONFLICT,
    ):
        apply_storage_migration(project)

    assert storage_migration_module._io_path(destination).read_bytes() == b"concurrent-main"
    assert not storage_migration_state_path(target).exists()
    connection.close()


def test_sqlite_promote_cleanup_skips_concurrently_replaced_members(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    target = resolve_project_storage_paths(project)
    destination = target.data / "workspace" / "state.sqlite"
    destination_wal = destination.with_name(destination.name + "-wal")
    original_atomic = storage_migration_module._atomic_promote_staged_member
    original_link = os.link

    def atomic_replace_main_after_promote(staged_io, final_io):
        promoted = original_atomic(staged_io, final_io)
        if Path(final_io).name == "state.sqlite":
            storage_migration_module._io_path(final_io).unlink()
            storage_migration_module._io_path(final_io).write_bytes(b"replaced-main")
        return promoted

    def link_with_concurrent_wal_at_atomic_promote(src, dst):
        dst_path = Path(dst)
        if dst_path.name.endswith("-wal"):
            dst_io = storage_migration_module._io_path(dst_path)
            dst_io.parent.mkdir(parents=True, exist_ok=True)
            dst_io.write_bytes(b"concurrent-wal")
        return original_link(src, dst)

    monkeypatch.setattr(
        storage_migration_module,
        "_atomic_promote_staged_member",
        atomic_replace_main_after_promote,
    )
    monkeypatch.setattr(os, "link", link_with_concurrent_wal_at_atomic_promote)

    with pytest.raises(
        StorageMigrationError,
        match=storage_migration_module.SQLITE_BUNDLE_DESTINATION_CONFLICT,
    ):
        apply_storage_migration(project)

    assert storage_migration_module._io_path(destination).read_bytes() == b"replaced-main"
    assert storage_migration_module._io_path(destination_wal).read_bytes() == b"concurrent-wal"
    assert not storage_migration_state_path(target).exists()
    connection.close()


def test_rollback_linked_promotion_preserves_concurrent_final_replacement(tmp_path):
    staged = tmp_path / "staged.sqlite"
    final = tmp_path / "final.sqlite"
    staged.write_bytes(b"promoted-content")
    os.link(staged, final)
    final.unlink()
    final.write_bytes(b"replacement-bytes")

    storage_migration_module._rollback_linked_promotion(
        storage_migration_module._io_path(staged),
        storage_migration_module._io_path(final),
    )

    assert final.read_bytes() == b"replacement-bytes"


def test_rollback_linked_promotion_removes_attempt_linked_final(tmp_path):
    staged = tmp_path / "staged.sqlite"
    final = tmp_path / "final.sqlite"
    staged.write_bytes(b"promoted-content")
    os.link(staged, final)

    storage_migration_module._rollback_linked_promotion(
        storage_migration_module._io_path(staged),
        storage_migration_module._io_path(final),
    )

    assert not final.exists()
    assert staged.exists()


def test_rollback_linked_promotion_preserves_replacement_at_delete_boundary(
    tmp_path, monkeypatch
):
    staged = tmp_path / "staged.sqlite"
    final = tmp_path / "final.sqlite"
    staged.write_bytes(b"promoted-content")
    os.link(staged, final)
    original_unlink = Path.unlink
    injected = {"done": False}

    def unlink_inject_replacement(self, missing_ok=False):
        if (
            not injected["done"]
            and self.name == storage_migration_module._SQLITE_QUARANTINE_MEMBER_NAME
        ):
            injected["done"] = True
            final.write_bytes(b"replacement-at-boundary")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_inject_replacement)

    storage_migration_module._rollback_linked_promotion(
        storage_migration_module._io_path(staged),
        storage_migration_module._io_path(final),
    )

    assert final.read_bytes() == b"replacement-at-boundary"
    assert staged.read_bytes() == b"promoted-content"
    assert _sqlite_quarantine_dirs(tmp_path) == []


def test_restore_claimed_sqlite_member_preserves_concurrent_destination_at_restore_boundary(
    tmp_path, monkeypatch
):
    member_path = tmp_path / "state.sqlite"
    quarantine = tmp_path / ".vibelution-storage-migration-cleanup-test-claim"
    quarantine.write_bytes(b"quarantined-foreign")
    original_link = os.link

    def link_inject_destination(src, dst):
        dst_path = Path(dst)
        if dst_path.name == member_path.name:
            member_path.write_bytes(b"concurrent-destination")
        return original_link(src, dst)

    monkeypatch.setattr(os, "link", link_inject_destination)

    storage_migration_module._restore_claimed_sqlite_member(
        storage_migration_module._io_path(member_path),
        storage_migration_module._io_path(quarantine),
    )

    assert member_path.read_bytes() == b"concurrent-destination"
    assert quarantine.read_bytes() == b"quarantined-foreign"


def test_cleanup_attempt_sqlite_members_preserves_replacement_at_delete_boundary(
    tmp_path, monkeypatch
):
    member_path = tmp_path / "state.sqlite"
    member_path.write_bytes(b"attempt-bytes")
    stat = member_path.stat()
    sha256 = storage_migration_module._sha256_file(member_path)
    member = storage_migration_module._PromotedSqliteMember(
        path=str(member_path.resolve()),
        device=int(stat.st_dev),
        inode=int(stat.st_ino),
        size=int(stat.st_size),
        sha256=sha256,
    )
    original_replace = os.replace

    def replace_then_inject_replacement(src, dst):
        original_replace(src, dst)
        if Path(str(src)) == storage_migration_module._io_path(member_path):
            member_path.write_bytes(b"replacement-at-boundary")

    monkeypatch.setattr(os, "replace", replace_then_inject_replacement)

    storage_migration_module._cleanup_attempt_sqlite_members([member])

    assert member_path.read_bytes() == b"replacement-at-boundary"
    assert _sqlite_quarantine_dirs(tmp_path) == []


def test_cleanup_foreign_quarantine_is_under_member_parent_and_remains_recoverable(
    tmp_path, monkeypatch
):
    member_dir = tmp_path / "workspace"
    member_dir.mkdir()
    member_path = member_dir / "state.sqlite"
    member_path.write_bytes(b"foreign-on-disk")
    attempt_source = member_dir / "attempt-source.sqlite"
    attempt_source.write_bytes(b"attempt-bytes")
    attempt_stat = attempt_source.stat()
    member = storage_migration_module._PromotedSqliteMember(
        path=str(member_path.resolve()),
        device=int(attempt_stat.st_dev),
        inode=int(attempt_stat.st_ino),
        size=int(attempt_stat.st_size),
        sha256=storage_migration_module._sha256_file(attempt_source),
    )
    original_link = os.link
    target_dst = storage_migration_module._io_path(member_path)

    def link_inject_concurrent_destination(src, dst):
        if Path(str(dst)) == target_dst:
            member_path.write_bytes(b"concurrent-destination")
        return original_link(src, dst)

    monkeypatch.setattr(os, "link", link_inject_concurrent_destination)

    storage_migration_module._cleanup_attempt_sqlite_members([member])

    assert member_path.read_bytes() == b"concurrent-destination"
    assert _sqlite_quarantine_dirs(tmp_path) == []
    quarantine_dirs = _sqlite_quarantine_dirs(member_dir)
    assert len(quarantine_dirs) == 1
    assert (
        quarantine_dirs[0]
        / storage_migration_module._SQLITE_QUARANTINE_MEMBER_NAME
    ).read_bytes() == b"foreign-on-disk"


def test_cleanup_attempt_sqlite_members_removes_attempt_owned_members(tmp_path):
    member_dir = tmp_path / "workspace"
    member_dir.mkdir()
    member_path = member_dir / "state.sqlite"
    member_path.write_bytes(b"attempt-bytes")
    stat = member_path.stat()
    member = storage_migration_module._PromotedSqliteMember(
        path=str(member_path.resolve()),
        device=int(stat.st_dev),
        inode=int(stat.st_ino),
        size=int(stat.st_size),
        sha256=storage_migration_module._sha256_file(member_path),
    )

    storage_migration_module._cleanup_attempt_sqlite_members([member])

    assert not member_path.exists()
    assert _sqlite_quarantine_dirs(member_dir) == []
    assert _sqlite_quarantine_dirs(tmp_path) == []


def test_rollback_delta_old_manifest_expected_uses_manifest_main_only(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    target = resolve_project_storage_paths(project)
    apply_storage_migration(project)
    connection.close()
    marker = json.loads(storage_migration_state_path(target).read_text(encoding="utf-8"))
    manifest_path = Path(str(marker["manifestPath"]))
    rewritten: list[str] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if str(row.get("relative_path") or "").endswith("state.sqlite"):
            row.pop("bundle_fingerprint", None)
            row.pop("bundle_members", None)
        rewritten.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    manifest_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    entries = storage_migration_module._read_manifest_entries(manifest_path)
    sqlite_entry = next(entry for entry in entries if entry.relative_path.endswith("state.sqlite"))
    expected = storage_migration_module._manifest_expected_bundle_snapshot(sqlite_entry)

    assert expected.members[1].present is False
    assert expected.members[2].present is False
    delta = assess_post_cutover_delta(target, marker)

    assert delta["detected"] is True
    assert delta["reasonCode"] == "reverse_delta_reconcile_required"


def test_sqlite_copy_failure_cleans_only_attempt_created_members(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    target = resolve_project_storage_paths(project)
    decoy = target.data / "workspace" / "decoy.sqlite"
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(b"decoy-main")
    decoy_wal = decoy.with_name(decoy.name + "-wal")
    decoy_wal.write_bytes(b"decoy-wal")
    destination = target.data / "workspace" / "state.sqlite"
    destination_wal = destination.with_name(destination.name + "-wal")
    original_link = os.link

    def link_with_wal_race_at_atomic_promote(src, dst):
        dst_path = Path(dst)
        if dst_path.name.endswith("-wal"):
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.write_bytes(b"race-wal")
        return original_link(src, dst)

    monkeypatch.setattr(os, "link", link_with_wal_race_at_atomic_promote)

    with pytest.raises(
        StorageMigrationError,
        match=storage_migration_module.SQLITE_BUNDLE_DESTINATION_CONFLICT,
    ):
        apply_storage_migration(project)

    assert decoy.read_bytes() == b"decoy-main"
    assert decoy_wal.read_bytes() == b"decoy-wal"
    assert not destination.exists()
    assert destination_wal.read_bytes() == b"race-wal"
    assert not storage_migration_state_path(target).exists()
    connection.close()


def test_readiness_and_apply_fail_closed_when_source_changes_during_quiescence_window(
    tmp_path, monkeypatch
):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)
    original_sleep = storage_migration_module._quiescence_sleep
    counter = {"n": 0}

    def write_during_window(seconds):
        counter["n"] += 1
        source.write_text(f"change {counter['n']}\n", encoding="utf-8")
        return original_sleep(seconds)

    monkeypatch.setattr(storage_migration_module, "_quiescence_sleep", write_during_window)

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is False
    assert readiness["quiescence"]["stable"] is False
    assert readiness["quiescence"]["sampleCount"] >= 2
    assert readiness["quiescence"]["reasonCode"] == "source_changed_during_quiescence_window"
    assert any(
        blocker["code"] == "source_changed_during_quiescence_window"
        for blocker in readiness["blockers"]
    )
    with pytest.raises(StorageMigrationError, match="readiness blocked"):
        apply_storage_migration(project)
    assert not storage_migration_state_path(target).exists()


def test_reapply_invokes_readiness_gate_and_blocks_on_non_quiescent_window(
    tmp_path, monkeypatch
):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    source = data_home / "workspace" / "agent.json"
    source.parent.mkdir(parents=True)
    source.write_text("data\n", encoding="utf-8")
    target = resolve_project_storage_paths(project)
    calls = {"count": 0}
    original_readiness = storage_migration_module.assess_storage_migration_readiness

    def counting_readiness(*args, **kwargs):
        calls["count"] += 1
        return original_readiness(*args, **kwargs)

    monkeypatch.setattr(
        storage_migration_module,
        "assess_storage_migration_readiness",
        counting_readiness,
    )
    first = apply_storage_migration(project)

    assert first["status"] == "completed"
    assert calls["count"] >= 1

    original_sleep = storage_migration_module._quiescence_sleep
    counter = {"n": 0}

    def write_during_window(seconds):
        counter["n"] += 1
        source.write_text(f"reapply change {counter['n']}\n", encoding="utf-8")
        return original_sleep(seconds)

    monkeypatch.setattr(storage_migration_module, "_quiescence_sleep", write_during_window)

    with pytest.raises(StorageMigrationError, match="readiness blocked"):
        apply_storage_migration(project)

    assert calls["count"] >= 2
    assert storage_migration_state_path(target).exists()
    assert resolve_active_project_storage_paths(project) == target


def test_sqlite_readiness_runs_quick_check_and_integrity_check(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is True
    assert readiness["quiescence"]["stable"] is True
    checks = readiness["sqliteIntegrity"]["checks"]
    sqlite_checks = [
        check
        for check in checks
        if str(check.get("path") or "").endswith("state.sqlite")
    ]
    assert {"quick_check", "integrity_check", "bundle_stable"} <= {
        check["pragma"] for check in sqlite_checks
    }


def test_sqlite_integrity_check_failure_blocks_readiness_and_apply(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()
    target = resolve_project_storage_paths(project)
    original_integrity = storage_migration_module._sqlite_integrity_check

    def failing_integrity(path):
        if str(path).endswith("state.sqlite"):
            return False, "integrity mismatch"
        return original_integrity(path)

    monkeypatch.setattr(
        storage_migration_module,
        "_sqlite_integrity_check",
        failing_integrity,
    )

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is False
    assert any(
        blocker["code"] == "sqlite_integrity_failed" for blocker in readiness["blockers"]
    )
    with pytest.raises(StorageMigrationError, match="readiness blocked"):
        apply_storage_migration(project)
    assert not storage_migration_state_path(target).exists()


def test_copy_verification_fails_closed_on_destination_integrity_mismatch(
    tmp_path, monkeypatch
):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "state.sqlite"
    database.parent.mkdir(parents=True)
    connection = _sqlite_database(database)
    connection.execute("CREATE TABLE t (value INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()
    target = resolve_project_storage_paths(project)
    destination = target.data / "workspace" / "state.sqlite"
    original_full = storage_migration_module._sqlite_full_integrity

    def fail_destination_integrity(path):
        ok, detail = original_full(path)
        if ok and storage_migration_module._same_path(Path(path), destination):
            return False, "integrity mismatch"
        return ok, detail

    monkeypatch.setattr(
        storage_migration_module,
        "_sqlite_full_integrity",
        fail_destination_integrity,
    )

    with pytest.raises(StorageMigrationError, match="integrity"):
        apply_storage_migration(project)

    assert not storage_migration_state_path(target).exists()
    assert not destination.exists()
    assert not destination.with_name(destination.name + "-wal").exists()
    assert not destination.with_name(destination.name + "-shm").exists()


def test_sqlite_integrity_failure_evidence_is_bounded(tmp_path, monkeypatch):
    project, _projects_home, data_home = _project(tmp_path, monkeypatch)
    database = data_home / "workspace" / "broken.sqlite"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"not-a-database")

    readiness = assess_storage_migration_readiness(project)

    assert readiness["ready"] is False
    assert any(
        blocker["code"] == "sqlite_integrity_failed" for blocker in readiness["blockers"]
    )
    bound = storage_migration_module._SQLITE_INTEGRITY_EVIDENCE_BOUND
    for failure in readiness["sqliteIntegrity"]["failures"]:
        assert len(str(failure.get("detail") or "")) <= bound + 64
