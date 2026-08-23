from __future__ import annotations

import json
import shutil
from pathlib import Path

import apsw
import pytest

import core.infrastructure.research_workflow_storage_migration as storage_migration
from core.infrastructure.research_workflow_storage_migration import (
    ResearchWorkflowMigrationError,
    acknowledge_proven_stale_runtime_quiescence,
    apply_research_workflow_migration,
    preview_research_workflow_migration,
    rollback_research_workflow_migration,
    verify_research_workflow_migration,
)
from vibelution_storage import (
    resolve_project_storage_paths,
    storage_migration_state_path,
)


def _fixture_roots(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    (project / ".vibelution").mkdir(parents=True)
    (project / ".vibelution" / "project.json").write_text(
        '{"schemaVersion":1,"projectId":"migration-test"}\n', encoding="utf-8"
    )
    operator_data = tmp_path / "Documents" / "Vibelution" / "data"
    projects_home = tmp_path / "AppData" / "Vibelution" / "projects"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(operator_data))
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(projects_home))
    paths = resolve_project_storage_paths(project, projects_home=projects_home)
    marker = storage_migration_state_path(paths)
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "completed",
                "projectId": paths.project_id,
                "instanceId": paths.instance_id,
            }
        ),
        encoding="utf-8",
    )
    source = operator_data / "research_workflows"
    target = paths.data / "research_workflows"
    source.mkdir(parents=True)
    return project, projects_home, source, target, marker


def _create_current_ledger(path: Path, *, include_blocked_run: bool = False) -> None:
    from core.research.workflow.ledger.store import WorkflowLedgerStore

    store = WorkflowLedgerStore(path)
    store.initialize()
    store.close()
    if not include_blocked_run:
        return
    connection = apsw.Connection(str(path))
    try:
        connection.execute(
            "INSERT INTO workflow_runs (run_id, team_id, workflow_id, workflow_version_id, thread_id, "
            "project_id, question_id, status, run_version, last_event_sequence, input_snapshot_json, "
            "input_snapshot_hash, safety_limits_json, binding_snapshot_set_id, active_node_id, "
            "parent_run_id, forked_from_checkpoint_id, completion_kind, terminal_reason, blocked_problem_json, "
            "created_at_ms, updated_at_ms, completed_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "run-882610596ddb",
                "team",
                "challenge_cup",
                "v1",
                "thread-key",
                "project",
                "SCI-091",
                "blocked",
                1,
                0,
                "{}",
                "a" * 64,
                "{}",
                "binding",
                None,
                None,
                None,
                None,
                "historical blocked run",
                '{"reason":"fixture"}',
                1,
                1,
                1,
            ),
        )
    finally:
        connection.close()


def _set_v5_checksum(path: Path, checksum: str) -> None:
    connection = apsw.Connection(str(path))
    try:
        connection.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = 5",
            (checksum,),
        )
    finally:
        connection.close()


def _make_empty_v4_ledger(path: Path) -> None:
    connection = apsw.Connection(str(path))
    try:
        connection.execute("DROP TABLE catalog_run_authorizations")
        connection.execute("DELETE FROM schema_migrations WHERE version = 5")
    finally:
        connection.close()


def _create_checkpoint(path: Path, *, include_rows: bool = True) -> None:
    connection = apsw.Connection(str(path))
    try:
        connection.execute(
            "CREATE TABLE checkpoints ("
            "thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', "
            "checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT, type TEXT, "
            "checkpoint BLOB, metadata BLOB, "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))"
        )
        connection.execute(
            "CREATE TABLE writes ("
            "thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', "
            "checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, idx INTEGER NOT NULL, "
            "channel TEXT NOT NULL, type TEXT, value BLOB, "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx))"
        )
        if include_rows:
            connection.execute(
                "INSERT INTO checkpoints(thread_id, checkpoint_ns, checkpoint_id, checkpoint) "
                "VALUES ('thread-1', '', 'checkpoint-1', 'snapshot')"
            )
            connection.execute(
                "INSERT INTO writes(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, value) "
                "VALUES ('thread-1', '', 'checkpoint-1', 'task-1', 0, 'state', 'value')"
            )
    finally:
        connection.close()


def _open_wal_checkpoint(path: Path) -> apsw.Connection:
    """Create a valid checkpoint bundle while retaining WAL/SHM sidecars."""

    connection = apsw.Connection(str(path))
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(
        "CREATE TABLE checkpoints ("
        "thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', "
        "checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT, type TEXT, "
        "checkpoint BLOB, metadata BLOB, "
        "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))"
    )
    connection.execute(
        "CREATE TABLE writes ("
        "thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', "
        "checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, idx INTEGER NOT NULL, "
        "channel TEXT NOT NULL, type TEXT, value BLOB, "
        "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx))"
    )
    connection.execute(
        "INSERT INTO checkpoints(thread_id, checkpoint_ns, checkpoint_id, checkpoint) "
        "VALUES ('thread-wal', '', 'checkpoint-wal', 'snapshot')"
    )
    connection.execute(
        "INSERT INTO writes(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, value) "
        "VALUES ('thread-wal', '', 'checkpoint-wal', 'task-wal', 0, 'state', 'value')"
    )
    return connection


def _table_values(path: Path, statement: str) -> list[tuple[object, ...]]:
    connection = apsw.Connection(str(path))
    try:
        return [tuple(row) for row in connection.execute(statement)]
    finally:
        connection.close()


def _apply_with_target_before_state(tmp_path: Path, monkeypatch):
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_current_ledger(source / "workflow-ledger.sqlite", include_blocked_run=True)
    _create_checkpoint(source / "checkpoints.sqlite")
    (source / "runs").mkdir()
    (source / "runs" / "run-1.json").write_text('{"runId":"run-1"}\n', encoding="utf-8")
    target.mkdir(parents=True)
    _create_current_ledger(target / "workflow-ledger.sqlite")
    _create_checkpoint(target / "checkpoints.sqlite", include_rows=False)
    result = apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    return project, projects_home, source, target, result


def test_preview_uses_only_research_workflows_scope(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    (source / "runs").mkdir()
    (source / "runs" / "run-1.json").write_text('{"runId":"run-1"}\n', encoding="utf-8")
    (source / "challenge_cup_real_batch" / "real-1.json").parent.mkdir()
    (source / "challenge_cup_real_batch" / "real-1.json").write_text("{}\n", encoding="utf-8")
    result = preview_research_workflow_migration(
        project_root=project,
        source_root=source,
        target_root=target,
        projects_home=projects_home,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        sample_delay_seconds=0,
    )
    assert result.source_root == source.resolve()
    assert result.target_root == target.resolve()
    assert result.allowed_assets == ("checkpoints.sqlite", "runs", "workflow-ledger.sqlite")
    assert "challenge_cup_real_batch/real-1.json" in result.excluded_assets


def test_preview_rejects_unknown_workflow_sqlite_asset(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    unknown = source / "workflow-checkpoints.sqlite"
    unknown.write_bytes(b"not an allowlisted asset")
    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert {
        (str(item["code"]), str(item.get("relativePath") or ""))
        for item in result.blockers
    } >= {("unknown_asset", "workflow-checkpoints.sqlite")}


def test_zero_byte_legacy_workflow_checkpoint_is_recorded_as_excluded_placeholder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    (source / "workflow-checkpoints.sqlite").write_bytes(b"")

    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )

    assert result.ready
    assert "workflow-checkpoints.sqlite" in result.excluded_assets
    assert not any(item.relative_path == "workflow-checkpoints.sqlite" for item in result.entries)
    assert any(
        item["code"] == "legacy_placeholder_excluded"
        and item["relativePath"] == "workflow-checkpoints.sqlite"
        for item in result.warnings
    )


def test_stale_runtime_lock_and_source_collection_snapshot_are_warnings_when_idle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, _source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    stale_guard = {
        "ok": True,
        "blockers": [],
        "activeWork": {"blocking": False, "uncertain": False, "claims": []},
        "runtimeWriters": {
            "blocking": True,
            "uncertain": False,
            "writers": [
                {
                    "kind": "runtime_manager_lock",
                    "path": "runtime-manager/daemon.lock",
                    "pid": 38628,
                },
            ],
        },
        "runtimeManager": {
            "daemonRunning": False,
            "managerPid": 38628,
            "runtimeState": "idle",
            "workbench": {"observedState": "closed"},
        },
        "launcher": {"blocking": False, "uncertain": False, "alive": False, "observedState": "idle"},
        "sourceCollectionSnapshots": [
            {
                "runId": "dprun-stale",
                "status": "running",
                "currentPhase": "searching",
                "processId": 38628,
            }
        ],
    }

    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: stale_guard,
    )

    assert result.ready
    warning_codes = {str(item["code"]) for item in result.warnings}
    assert "stale_runtime_manager_lock" in warning_codes
    assert "stale_source_collection_snapshot" in warning_codes


def test_active_claims_remain_blockers_even_with_stale_runtime_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, _source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    guard = {
        "ok": False,
        "blockers": [{"code": "active_work_present", "claims": [{"claimId": "claim-live"}]}],
        "activeWork": {
            "blocking": True,
            "uncertain": False,
            "claims": [{"claimId": "claim-live"}],
        },
        "runtimeWriters": {
            "blocking": True,
            "uncertain": False,
            "writers": [{"kind": "runtime_manager_lock", "pid": 38628}],
        },
        "runtimeManager": {"daemonRunning": False, "managerPid": 38628, "runtimeState": "idle"},
        "launcher": {"blocking": False, "uncertain": False, "alive": False, "observedState": "idle"},
        "sourceCollectionSnapshots": [{"runId": "dprun-stale", "status": "running"}],
    }

    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: guard,
    )

    assert not result.ready
    assert any(item["code"] == "active_work_present" for item in result.blockers)


def test_empty_target_checkpoint_placeholder_is_archived_replaced_and_restorable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_checkpoint(source / "checkpoints.sqlite")
    target.mkdir(parents=True)
    target_checkpoint = target / "checkpoints.sqlite"
    target_checkpoint.write_bytes(b"")

    preview = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert preview.ready

    applied = apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    manifest = Path(str(applied["manifestPath"]))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    entry = next(item for item in payload["assets"] if item["relativePath"] == "checkpoints.sqlite")
    before_archive = Path(str(entry["targetBefore"]["archive_path"]))
    assert before_archive.read_bytes() == b""
    assert _table_values(target_checkpoint, "SELECT thread_id FROM checkpoints") == [("thread-1",)]

    rolled_back = rollback_research_workflow_migration(
        project,
        projects_home=projects_home,
        manifest_path=manifest,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert rolled_back["ok"] is True
    assert target_checkpoint.read_bytes() == b""
    assert not target_checkpoint.with_name("checkpoints.sqlite-wal").exists()
    assert not target_checkpoint.with_name("checkpoints.sqlite-shm").exists()


def test_empty_target_ledger_with_zero_wal_and_stale_shm_replaces_whole_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_current_ledger(source / "workflow-ledger.sqlite", include_blocked_run=True)
    target.mkdir(parents=True)
    target_ledger = target / "workflow-ledger.sqlite"
    _create_current_ledger(target_ledger)
    target_ledger.with_name("workflow-ledger.sqlite-shm").write_bytes(b"stale-shm")

    preview = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert preview.ready

    applied = apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    manifest = Path(str(applied["manifestPath"]))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    entry = next(item for item in payload["assets"] if item["relativePath"] == "workflow-ledger.sqlite")
    before_archive = Path(str(entry["targetBefore"]["archive_path"]))
    assert before_archive.with_name(before_archive.name + "-shm").read_bytes() == b"stale-shm"
    assert not target_ledger.with_name("workflow-ledger.sqlite-shm").exists()

    rolled_back = rollback_research_workflow_migration(
        project,
        projects_home=projects_home,
        manifest_path=manifest,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert rolled_back["ok"] is True
    assert target_ledger.with_name("workflow-ledger.sqlite-shm").read_bytes() == b"stale-shm"


def test_preview_rejects_target_ledger_sidecar(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_current_ledger(source / "workflow-ledger.sqlite")
    target.mkdir(parents=True)
    (target / "workflow-ledger.sqlite-shm").write_bytes(b"")
    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert any(
        item["code"] == "orphan_or_active_target_sqlite_sidecar"
        and str(item["path"]).endswith("workflow-ledger.sqlite")
        for item in result.blockers
    )


def test_apply_backup_integrity_verify_and_source_preservation(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, _target, marker = _fixture_roots(tmp_path, monkeypatch)
    ledger = source / "workflow-ledger.sqlite"
    _create_current_ledger(ledger, include_blocked_run=True)
    checkpoint = source / "checkpoints.sqlite"
    _create_checkpoint(checkpoint)
    (source / "runs").mkdir()
    (source / "runs" / "run-1.json").write_text('{"runId":"run-1","status":"blocked"}\n', encoding="utf-8")
    envelope = source / "challenge_cup_real_batch" / "real-1.json"
    envelope.parent.mkdir()
    envelope.write_text('{"batchId":"real-1"}\n', encoding="utf-8")
    source_bytes = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    marker_before = marker.read_bytes()
    result = apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert result["ok"] is True
    assert Path(str(result["manifestPath"])).is_file()
    assert marker.read_bytes() == marker_before
    assert {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    } == source_bytes
    assert (source / "challenge_cup_real_batch" / "real-1.json").read_text(encoding="utf-8") == '{"batchId":"real-1"}\n'
    verification = verify_research_workflow_migration(
        project,
        projects_home=projects_home,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert verification["ok"] is True
    assert verification["keyRuns"]["run-882610596ddb"] == "blocked"


def test_empty_target_schema_can_be_promoted_but_nonempty_target_refuses(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_current_ledger(source / "workflow-ledger.sqlite", include_blocked_run=True)
    target.mkdir(parents=True)
    _create_current_ledger(target / "workflow-ledger.sqlite", include_blocked_run=False)
    apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    second_data = tmp_path / "other-source"
    second_source = second_data / "research_workflows"
    second_source.mkdir(parents=True)
    _create_current_ledger(second_source / "workflow-ledger.sqlite", include_blocked_run=True)
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(second_data))
    with pytest.raises(ResearchWorkflowMigrationError):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )


def test_ledger_v5_checksum_mismatch_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    ledger = source / "workflow-ledger.sqlite"
    _create_current_ledger(ledger)
    target.mkdir(parents=True)
    _create_current_ledger(target / "workflow-ledger.sqlite")
    _set_v5_checksum(ledger, "future")
    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    blocker_codes = {str(item["code"]) for item in result.blockers}
    assert "ledger_v5_checksum_rejected" in blocker_codes
    assert "ledger_v5_validator_unavailable" not in blocker_codes
    with pytest.raises(ResearchWorkflowMigrationError):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )


def test_legacy_v5_schema_drift_is_rejected_by_ledger_authority(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from core.research.workflow.ledger.schema import V5_LEGACY_CHECKSUM

    project, projects_home, source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    ledger = source / "workflow-ledger.sqlite"
    _create_current_ledger(ledger)
    _set_v5_checksum(ledger, V5_LEGACY_CHECKSUM)
    connection = apsw.Connection(str(ledger))
    try:
        connection.execute("DROP INDEX idx_catalog_run_authorizations_lookup")
    finally:
        connection.close()

    preview = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    blocker_codes = {str(item["code"]) for item in preview.blockers}
    assert any(code.startswith("ledger_v5_validator_rejected:") for code in blocker_codes)
    assert "ledger_v5_validator_unavailable" not in blocker_codes
    with pytest.raises(ResearchWorkflowMigrationError):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )


def test_legacy_v5_source_can_replace_empty_v5_target(tmp_path: Path, monkeypatch) -> None:
    from core.research.workflow.ledger.schema import V5_LEGACY_CHECKSUM

    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    source_ledger = source / "workflow-ledger.sqlite"
    _create_current_ledger(source_ledger, include_blocked_run=True)
    _set_v5_checksum(source_ledger, V5_LEGACY_CHECKSUM)
    target.mkdir(parents=True)
    target_ledger = target / "workflow-ledger.sqlite"
    _create_current_ledger(target_ledger)

    preview = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert preview.ready
    result = apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert result["ok"] is True
    assert _table_values(
        target_ledger,
        "SELECT checksum FROM schema_migrations WHERE version = 5",
    ) == [(V5_LEGACY_CHECKSUM,)]


def test_v5_source_refuses_empty_v4_target(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_current_ledger(source / "workflow-ledger.sqlite")
    target.mkdir(parents=True)
    target_ledger = target / "workflow-ledger.sqlite"
    _create_current_ledger(target_ledger)
    _make_empty_v4_ledger(target_ledger)

    preview = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert any(
        item["code"] == "target_sqlite_conflict" and item["schemaVersion"] == 4
        for item in preview.blockers
    )
    with pytest.raises(ResearchWorkflowMigrationError):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )


def test_rollback_requires_no_post_cutover_delta(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_current_ledger(source / "workflow-ledger.sqlite", include_blocked_run=True)
    apply = apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    target_ledger = Path(str(apply["targetRoot"])) / "workflow-ledger.sqlite"
    connection = apsw.Connection(str(target_ledger))
    try:
        connection.execute("PRAGMA user_version = 7")
    finally:
        connection.close()
    with pytest.raises(ResearchWorkflowMigrationError, match="post-cutover delta"):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=Path(str(apply["manifestPath"])),
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        ("sourceRoot", "manifest source root is not the operator Documents root"),
        ("targetRoot", "manifest target root is not the canonical project root"),
    ),
)
def test_rollback_rejects_manifest_root_mismatch_before_staging(
    tmp_path: Path,
    monkeypatch,
    field: str,
    expected: str,
) -> None:
    project, projects_home, _source, _target, apply = _apply_with_target_before_state(tmp_path, monkeypatch)
    manifest = Path(str(apply["manifestPath"]))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload[field] = str(tmp_path / "wrong-root")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    def staging_must_not_start(*_args, **_kwargs):
        pytest.fail("rollback staging must not start for an unbound manifest")

    monkeypatch.setattr(storage_migration, "_stage_rollback_plans", staging_must_not_start)
    with pytest.raises(ResearchWorkflowMigrationError, match=expected):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=manifest,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )


@pytest.mark.parametrize(
    ("relative_path", "evidence_path"),
    (
        ("runs/run-1.json", ("exists",)),
        ("runs/run-1.json", ("sha256",)),
        ("checkpoints.sqlite", ("bundleFingerprint",)),
        ("checkpoints.sqlite", ("sqlite", "schema_digest")),
        ("checkpoints.sqlite", ("sqlite", "row_counts")),
    ),
)
def test_verify_rejects_incomplete_target_after_evidence(
    tmp_path: Path,
    monkeypatch,
    relative_path: str,
    evidence_path: tuple[str, ...],
) -> None:
    project, projects_home, _source, _target, apply = _apply_with_target_before_state(tmp_path, monkeypatch)
    manifest = Path(str(apply["manifestPath"]))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    entry = next(item for item in payload["assets"] if item["relativePath"] == relative_path)
    evidence = entry["targetAfter"]
    for part in evidence_path[:-1]:
        evidence = evidence[part]
    del evidence[evidence_path[-1]]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ResearchWorkflowMigrationError, match="target-after evidence is incomplete"):
        verify_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=manifest,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )


def test_apply_promotion_failure_restores_previously_promoted_targets(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_current_ledger(source / "workflow-ledger.sqlite", include_blocked_run=True)
    _create_checkpoint(source / "checkpoints.sqlite")
    (source / "runs").mkdir()
    run = source / "runs" / "run-1.json"
    run.write_text('{"runId":"run-1"}\n', encoding="utf-8")
    target.mkdir(parents=True)
    target_ledger = target / "workflow-ledger.sqlite"
    target_checkpoint = target / "checkpoints.sqlite"
    _create_current_ledger(target_ledger)
    _create_checkpoint(target_checkpoint, include_rows=False)
    real_replace = storage_migration.os.replace
    failed_once = False

    def fail_ledger_promotion(source_path, destination):
        nonlocal failed_once
        if (
            not failed_once
            and Path(destination) == target_ledger
            and Path(source_path).name.endswith(".staging")
        ):
            failed_once = True
            raise OSError("simulated promotion failure")
        return real_replace(source_path, destination)

    monkeypatch.setattr(storage_migration.os, "replace", fail_ledger_promotion)
    with pytest.raises(OSError, match="simulated promotion failure"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert _table_values(target_ledger, "SELECT run_id FROM workflow_runs") == []
    assert _table_values(target_checkpoint, "SELECT thread_id FROM checkpoints") == []
    assert not (target / "runs" / "run-1.json").exists()
    assert not (target / "migration").exists()


def test_apply_manifest_failure_restores_promoted_targets(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, _source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    source = _source
    _create_current_ledger(source / "workflow-ledger.sqlite", include_blocked_run=True)
    _create_checkpoint(source / "checkpoints.sqlite")
    (source / "runs").mkdir()
    (source / "runs" / "run-1.json").write_text('{"runId":"run-1"}\n', encoding="utf-8")
    target.mkdir(parents=True)
    target_ledger = target / "workflow-ledger.sqlite"
    target_checkpoint = target / "checkpoints.sqlite"
    _create_current_ledger(target_ledger)
    _create_checkpoint(target_checkpoint, include_rows=False)

    def fail_manifest(_path: Path, _payload: dict[str, object]) -> None:
        raise RuntimeError("simulated manifest write failure")

    monkeypatch.setattr(storage_migration, "_atomic_json", fail_manifest)
    with pytest.raises(RuntimeError, match="simulated manifest write failure"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert _table_values(target_ledger, "SELECT run_id FROM workflow_runs") == []
    assert _table_values(target_checkpoint, "SELECT thread_id FROM checkpoints") == []
    assert not (target / "runs" / "run-1.json").exists()
    assert not (target / "migration").exists()


def test_rollback_stages_all_targets_before_any_promotion(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, _source, target, apply = _apply_with_target_before_state(tmp_path, monkeypatch)
    payload = json.loads(Path(str(apply["manifestPath"])).read_text(encoding="utf-8"))
    ledger_entry = next(item for item in payload["assets"] if item["relativePath"] == "workflow-ledger.sqlite")
    ledger_archive = Path(str(ledger_entry["targetBefore"]["archive_path"]))
    real_copy = storage_migration._copy_sqlite_bundle_archive

    def fail_ledger_restore_stage(
        source_path: Path,
        destination: Path,
        *,
        allow_empty_main: bool = False,
    ) -> None:
        if Path(source_path) == ledger_archive:
            raise OSError("simulated rollback staging failure")
        real_copy(source_path, destination, allow_empty_main=allow_empty_main)

    monkeypatch.setattr(storage_migration, "_copy_sqlite_bundle_archive", fail_ledger_restore_stage)
    with pytest.raises(OSError, match="simulated rollback staging failure"):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=Path(str(apply["manifestPath"])),
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert _table_values(target / "checkpoints.sqlite", "SELECT thread_id FROM checkpoints") == [("thread-1",)]
    assert (target / "runs" / "run-1.json").is_file()


def test_rollback_promotion_failure_restores_post_cutover_targets(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, _source, target, apply = _apply_with_target_before_state(tmp_path, monkeypatch)
    target_ledger = target / "workflow-ledger.sqlite"
    real_replace = storage_migration.os.replace
    failed = False

    def fail_once_during_rollback(source_path, destination):
        nonlocal failed
        if not failed and Path(destination) == target_ledger and Path(source_path).name.endswith(".staging"):
            failed = True
            raise OSError("simulated rollback promotion failure")
        return real_replace(source_path, destination)

    monkeypatch.setattr(storage_migration.os, "replace", fail_once_during_rollback)
    with pytest.raises(OSError, match="simulated rollback promotion failure"):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=Path(str(apply["manifestPath"])),
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert _table_values(target_ledger, "SELECT status FROM workflow_runs WHERE run_id = 'run-882610596ddb'") == [
        ("blocked",)
    ]
    assert _table_values(target / "checkpoints.sqlite", "SELECT thread_id FROM checkpoints") == [("thread-1",)]
    assert (target / "runs" / "run-1.json").is_file()


def test_rollback_refuses_tampered_target_before_archive(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, _source, target, apply = _apply_with_target_before_state(tmp_path, monkeypatch)
    payload = json.loads(Path(str(apply["manifestPath"])).read_text(encoding="utf-8"))
    ledger_entry = next(item for item in payload["assets"] if item["relativePath"] == "workflow-ledger.sqlite")
    archive = Path(str(ledger_entry["targetBefore"]["archive_path"]))
    connection = apsw.Connection(str(archive))
    try:
        connection.execute("PRAGMA user_version = 9")
    finally:
        connection.close()
    with pytest.raises(ResearchWorkflowMigrationError, match="archive hash mismatch"):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=Path(str(apply["manifestPath"])),
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert _table_values(
        target / "workflow-ledger.sqlite", "SELECT status FROM workflow_runs WHERE run_id = 'run-882610596ddb'"
    ) == [("blocked",)]


def test_verify_requires_quiescence_and_checks_sqlite_schema_and_bundle(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, _source, target, apply = _apply_with_target_before_state(tmp_path, monkeypatch)
    manifest = Path(str(apply["manifestPath"]))
    with pytest.raises(ResearchWorkflowMigrationError, match="quiescence"):
        verify_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=manifest,
            quiescence_probe=lambda _project: {"ok": False, "blockers": [{"code": "active_work_present"}]},
        )
    connection = apsw.Connection(str(target / "workflow-ledger.sqlite"))
    try:
        connection.execute("CREATE TABLE schema_drift (id INTEGER PRIMARY KEY)")
    finally:
        connection.close()
    (target / "checkpoints.sqlite-wal").write_bytes(b"unexpected sidecar")
    verification = verify_research_workflow_migration(
        project,
        projects_home=projects_home,
        manifest_path=manifest,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    codes = {str(item["code"]) for item in verification["failures"]}
    assert "target_schema_digest_mismatch" in codes
    assert "target_bundle_fingerprint_mismatch" in codes


def test_incomplete_checkpoint_schema_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    connection = apsw.Connection(str(source / "checkpoints.sqlite"))
    try:
        connection.execute("CREATE TABLE checkpoints (thread_id TEXT PRIMARY KEY)")
    finally:
        connection.close()
    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert any(item["code"] == "checkpoint_schema_unknown" for item in result.blockers)


def test_checkpoint_column_schema_drift_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    checkpoint = source / "checkpoints.sqlite"
    _create_checkpoint(checkpoint)
    connection = apsw.Connection(str(checkpoint))
    try:
        connection.execute("ALTER TABLE checkpoints ADD COLUMN drift TEXT")
    finally:
        connection.close()
    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert any(item["code"] == "checkpoint_schema_unknown" for item in result.blockers)


def test_preview_preserves_real_sqlite_bundle_metadata(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    checkpoint = source / "checkpoints.sqlite"
    connection = _open_wal_checkpoint(checkpoint)
    try:
        sidecars = tuple(
            path
            for path in (
                checkpoint.with_name(checkpoint.name + "-wal"),
                checkpoint.with_name(checkpoint.name + "-shm"),
            )
            if path.is_file()
        )
        assert sidecars, "fixture must retain a WAL/SHM sidecar"
        before = {
            path: (path.stat().st_mtime_ns, path.read_bytes())
            for path in sidecars
        }
        result = preview_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
        assert result.ready
        assert {
            path: (path.stat().st_mtime_ns, path.read_bytes())
            for path in sidecars
        } == before
    finally:
        connection.close()


def test_default_manifest_selection_uses_latest_committed_timestamp(
    tmp_path: Path,
) -> None:
    target = tmp_path / "research_workflows"
    migration = target / "migration"
    migration.mkdir(parents=True)
    (migration / "rwm-z-old.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "committed",
                "migrationId": "rwm-z-old",
                "statusTransitions": [
                    {"status": "committed", "at": "2026-08-23T10:00:00Z"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (migration / "rwm-a-new.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "committed",
                "migrationId": "rwm-a-new",
                "statusTransitions": [
                    {"status": "committed", "at": "2026-08-23T11:00:00Z"}
                ],
            }
        ),
        encoding="utf-8",
    )
    selected = storage_migration._find_manifest(target)
    assert selected.name == "rwm-a-new.json"


def test_rollback_reads_archive_path_from_legacy_v1_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, _source, target, apply = _apply_with_target_before_state(tmp_path, monkeypatch)
    manifest = Path(str(apply["manifestPath"]))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    migration_id = str(payload["migrationId"])
    legacy_root = target.parent / "research_workflow_migration_backups" / migration_id / "target-before"
    for item in payload["assets"]:
        before = item["targetBefore"]
        if not before["existed"]:
            continue
        legacy_archive = legacy_root / Path(item["relativePath"])
        legacy_archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(before["archive_path"]), legacy_archive)
        before["archive_path"] = str(legacy_archive)
    payload["targetBeforeArchive"] = str(legacy_root)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = rollback_research_workflow_migration(
        project,
        projects_home=projects_home,
        manifest_path=manifest,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert result["ok"] is True
    assert result["status"] == "rolled_back"


def test_rollback_blocks_legacy_manifest_without_archive_root_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, _source, _target, apply = _apply_with_target_before_state(tmp_path, monkeypatch)
    manifest = Path(str(apply["manifestPath"]))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload.pop("targetBeforeArchive", None)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ResearchWorkflowMigrationError, match="archive"):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=manifest,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )


@pytest.mark.parametrize("with_sidecars", (False, True))
def test_empty_sqlite_main_is_fail_closed(
    tmp_path: Path,
    monkeypatch,
    with_sidecars: bool,
) -> None:
    project, projects_home, source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    checkpoint = source / "checkpoints.sqlite"
    checkpoint.write_bytes(b"")
    if with_sidecars:
        checkpoint.with_name(checkpoint.name + "-wal").write_bytes(b"wal")
        checkpoint.with_name(checkpoint.name + "-shm").write_bytes(b"shm")

    preview = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert any(
        item["code"] == "sqlite_empty_main" and item["relativePath"] == "checkpoints.sqlite"
        for item in preview.blockers
    )
    with pytest.raises(ResearchWorkflowMigrationError):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )


def test_target_empty_checkpoint_main_is_replaceable_placeholder(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_checkpoint(source / "checkpoints.sqlite")
    target.mkdir(parents=True)
    (target / "checkpoints.sqlite").write_bytes(b"")

    preview = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert preview.ready
    assert not any(
        item["code"] == "target_empty_sqlite_main" and str(item["path"]).endswith("checkpoints.sqlite")
        for item in preview.blockers
    )


class _SimulatedProcessCrash(BaseException):
    pass


def test_raw_not_ready_guard_cannot_be_normalized_to_ready(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, _source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)

    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": False, "blockers": []},
    )

    assert not result.ready
    assert any(item["code"] == "quiescence_guard_not_ready" for item in result.blockers)


def test_ready_claim_is_recovered_as_active_work_blocker(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, _source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)

    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {
            "ok": True,
            "blockers": [],
            "activeWork": {
                "blocking": False,
                "uncertain": False,
                "claims": [{"claimId": "claim-ready", "status": "ready"}],
            },
        },
    )

    assert not result.ready
    assert any(item["code"] == "active_work_present" for item in result.blockers)


@pytest.mark.parametrize(
    "runtime_evidence",
    (
        {"workbench": {"backendPortListening": True}},
        {"workbench": {"backendPortOwnerPid": 43210, "backendPortOwnerResidual": True}},
        {"residualProcesses": {"count": 1, "items": [{"pid": 43210}]}},
    ),
)
def test_runtime_residual_evidence_keeps_stale_lock_blocking(
    tmp_path: Path,
    monkeypatch,
    runtime_evidence: dict[str, object],
) -> None:
    project, projects_home, _source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    guard = {
        "ok": True,
        "blockers": [{"code": "runtime_writers_active"}],
        "activeWork": {"blocking": False, "uncertain": False, "claims": []},
        "runtimeWriters": {
            "blocking": True,
            "uncertain": False,
            "writers": [{"kind": "runtime_manager_lock", "pid": 43210}],
        },
        "runtimeManager": {"daemonRunning": False, **runtime_evidence},
        "launcher": {"blocking": False, "uncertain": False, "alive": False},
    }

    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: guard,
    )

    assert not result.ready
    assert any(item["code"] == "runtime_writers_active" for item in result.blockers)
    assert not any(item["code"] == "stale_runtime_manager_lock" for item in result.warnings)


def test_placeholder_rejects_directory_sidecar_members(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    legacy = source / "workflow-checkpoints.sqlite"
    legacy.write_bytes(b"")
    legacy.with_name(legacy.name + "-wal").mkdir()
    _create_checkpoint(source / "checkpoints.sqlite")
    target.mkdir(parents=True)
    target_checkpoint = target / "checkpoints.sqlite"
    target_checkpoint.write_bytes(b"")
    target_checkpoint.with_name(target_checkpoint.name + "-shm").mkdir()

    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )

    assert "workflow-checkpoints.sqlite" not in result.excluded_assets
    assert any(item["code"] == "unknown_asset" for item in result.blockers)
    assert any(item["code"] == "target_sqlite_bundle_member_unsafe" for item in result.blockers)


def test_apply_recovers_persistent_journal_after_main_replace_crash(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_checkpoint(source / "checkpoints.sqlite")
    target.mkdir(parents=True)
    target_checkpoint = target / "checkpoints.sqlite"
    target_checkpoint.write_bytes(b"")
    journal = target.parent / ".rwm-j.json"
    real_replace = storage_migration.os.replace
    crashed = False

    def crash_after_main_replace(source_path, destination_path):
        nonlocal crashed
        if not crashed and Path(destination_path) == target_checkpoint and Path(source_path).name.endswith(".staging"):
            real_replace(source_path, destination_path)
            crashed = True
            raise _SimulatedProcessCrash("crash after main")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(storage_migration.os, "replace", crash_after_main_replace)
    with pytest.raises(_SimulatedProcessCrash, match="crash after main"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert journal.is_file()
    blocked_preview = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert any(item["code"] == "unfinished_promotion_journal" for item in blocked_preview.blockers)
    assert journal.is_file(), "preview must never recover or remove a journal"

    monkeypatch.setattr(storage_migration.os, "replace", real_replace)
    result = apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert result["ok"] is True
    assert not journal.exists()
    assert _table_values(target_checkpoint, "SELECT thread_id FROM checkpoints") == [("thread-1",)]


def test_apply_recovers_persistent_journal_after_sidecar_finalize_crash(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_current_ledger(source / "workflow-ledger.sqlite", include_blocked_run=True)
    target.mkdir(parents=True)
    target_ledger = target / "workflow-ledger.sqlite"
    _create_current_ledger(target_ledger)
    target_shm = target_ledger.with_name(target_ledger.name + "-shm")
    target_shm.write_bytes(b"stale-shm")
    journal = target.parent / ".rwm-j.json"
    real_finish = storage_migration._finish_sqlite_bundle_promotion
    crashed = False

    def crash_after_sidecar_finalize(stage: Path, destination: Path) -> None:
        nonlocal crashed
        real_finish(stage, destination)
        if not crashed and destination == target_ledger:
            crashed = True
            raise _SimulatedProcessCrash("crash after sidecar")

    monkeypatch.setattr(storage_migration, "_finish_sqlite_bundle_promotion", crash_after_sidecar_finalize)
    with pytest.raises(_SimulatedProcessCrash, match="crash after sidecar"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert journal.is_file()
    assert not target_shm.exists()

    monkeypatch.setattr(storage_migration, "_finish_sqlite_bundle_promotion", real_finish)
    result = apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert result["ok"] is True
    assert not journal.exists()
    assert not target_shm.exists()


def test_completed_manifest_wins_over_stale_journal_after_manifest_crash(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    source_ledger = source / "workflow-ledger.sqlite"
    _create_current_ledger(source_ledger, include_blocked_run=True)
    journal = target.parent / ".rwm-j.json"
    real_atomic_json = storage_migration._atomic_json
    crashed = False

    def crash_after_completed_manifest(path: Path, payload: dict[str, object]) -> None:
        nonlocal crashed
        real_atomic_json(path, payload)
        if not crashed and path.parent.name == "migration" and payload.get("status") == "completed":
            crashed = True
            raise _SimulatedProcessCrash("crash after manifest")

    monkeypatch.setattr(storage_migration, "_atomic_json", crash_after_completed_manifest)
    with pytest.raises(_SimulatedProcessCrash, match="crash after manifest"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert journal.is_file()
    assert _table_values(target / "workflow-ledger.sqlite", "SELECT status FROM workflow_runs") == [("blocked",)]

    connection = apsw.Connection(str(source_ledger))
    try:
        connection.execute("UPDATE workflow_runs SET status = 'succeeded'")
    finally:
        connection.close()
    monkeypatch.setattr(storage_migration, "_atomic_json", real_atomic_json)
    with pytest.raises(ResearchWorkflowMigrationError, match="target_sqlite_conflict"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert not journal.exists()
    assert _table_values(target / "workflow-ledger.sqlite", "SELECT status FROM workflow_runs") == [("blocked",)]


def test_apply_journal_recovery_refuses_concurrent_sqlite_bundle_delta(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_checkpoint(source / "checkpoints.sqlite")
    target.mkdir(parents=True)
    target_checkpoint = target / "checkpoints.sqlite"
    target_checkpoint.write_bytes(b"")
    target_wal = target_checkpoint.with_name(target_checkpoint.name + "-wal")
    journal = target.parent / ".rwm-j.json"
    real_replace = storage_migration.os.replace
    crashed = False

    def crash_after_main_replace(source_path, destination_path):
        nonlocal crashed
        if not crashed and Path(destination_path) == target_checkpoint and Path(source_path).name.endswith(".staging"):
            real_replace(source_path, destination_path)
            crashed = True
            raise _SimulatedProcessCrash("crash before journal recovery")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(storage_migration.os, "replace", crash_after_main_replace)
    with pytest.raises(_SimulatedProcessCrash, match="crash before journal recovery"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    promoted_sha = storage_migration._sha256_file(target_checkpoint)
    target_wal.write_bytes(b"foreign-wal")

    monkeypatch.setattr(storage_migration.os, "replace", real_replace)
    with pytest.raises(ResearchWorkflowMigrationError, match="journal recovery target delta"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )

    assert journal.is_file()
    assert storage_migration._sha256_file(target_checkpoint) == promoted_sha
    assert target_wal.read_bytes() == b"foreign-wal"


def test_apply_journal_recovery_refuses_concurrent_sqlite_main_delta(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_checkpoint(source / "checkpoints.sqlite")
    target.mkdir(parents=True)
    target_checkpoint = target / "checkpoints.sqlite"
    target_checkpoint.write_bytes(b"")
    journal = target.parent / ".rwm-j.json"
    real_replace = storage_migration.os.replace
    crashed = False

    def crash_after_main_replace(source_path, destination_path):
        nonlocal crashed
        if not crashed and Path(destination_path) == target_checkpoint and Path(source_path).name.endswith(".staging"):
            real_replace(source_path, destination_path)
            crashed = True
            raise _SimulatedProcessCrash("crash before main delta")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(storage_migration.os, "replace", crash_after_main_replace)
    with pytest.raises(_SimulatedProcessCrash, match="crash before main delta"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    target_checkpoint.write_bytes(b"foreign-main")

    monkeypatch.setattr(storage_migration.os, "replace", real_replace)
    with pytest.raises(ResearchWorkflowMigrationError, match="journal recovery target delta"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )

    assert journal.is_file()
    assert target_checkpoint.read_bytes() == b"foreign-main"


def test_apply_journal_recovery_refuses_concurrent_sqlite_shm_delta(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_checkpoint(source / "checkpoints.sqlite")
    target.mkdir(parents=True)
    target_checkpoint = target / "checkpoints.sqlite"
    target_checkpoint.write_bytes(b"")
    target_shm = target_checkpoint.with_name(target_checkpoint.name + "-shm")
    journal = target.parent / ".rwm-j.json"
    real_replace = storage_migration.os.replace
    crashed = False

    def crash_after_main_replace(source_path, destination_path):
        nonlocal crashed
        if not crashed and Path(destination_path) == target_checkpoint and Path(source_path).name.endswith(".staging"):
            real_replace(source_path, destination_path)
            crashed = True
            raise _SimulatedProcessCrash("crash before shm delta")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(storage_migration.os, "replace", crash_after_main_replace)
    with pytest.raises(_SimulatedProcessCrash, match="crash before shm delta"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    promoted_sha = storage_migration._sha256_file(target_checkpoint)
    target_shm.write_bytes(b"foreign-shm")

    monkeypatch.setattr(storage_migration.os, "replace", real_replace)
    with pytest.raises(ResearchWorkflowMigrationError, match="journal recovery target delta"):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )

    assert journal.is_file()
    assert storage_migration._sha256_file(target_checkpoint) == promoted_sha
    assert target_shm.read_bytes() == b"foreign-shm"


@pytest.mark.parametrize("sidecar_kind", ("regular", "directory", "reparse"))
def test_apply_observation_refuses_sidecar_when_sqlite_main_disappears_after_staging(
    tmp_path: Path,
    monkeypatch,
    sidecar_kind: str,
) -> None:
    project, projects_home, source, target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_checkpoint(source / "checkpoints.sqlite")
    target.mkdir(parents=True)
    target_checkpoint = target / "checkpoints.sqlite"
    target_checkpoint.write_bytes(b"")
    target_sidecar = target_checkpoint.with_name(target_checkpoint.name + "-shm")
    journal = target.parent / ".rwm-j.json"
    real_finish = storage_migration._finish_sqlite_bundle_promotion
    real_is_reparse = storage_migration._is_reparse
    injected = False

    def finish_then_inject_sidecar(stage: Path, destination: Path) -> None:
        nonlocal injected
        real_finish(stage, destination)
        if injected or destination != target_checkpoint:
            return
        injected = True
        destination.unlink()
        if sidecar_kind == "directory":
            target_sidecar.mkdir()
        else:
            target_sidecar.write_bytes(b"foreign-sidecar")
        if sidecar_kind == "reparse":
            monkeypatch.setattr(
                storage_migration,
                "_is_reparse",
                lambda path: Path(path) == target_sidecar or real_is_reparse(path),
            )

    monkeypatch.setattr(storage_migration, "_finish_sqlite_bundle_promotion", finish_then_inject_sidecar)
    with pytest.raises(
        ResearchWorkflowMigrationError,
        match="migration failed and persistent journal recovery was incomplete",
    ):
        apply_research_workflow_migration(
            project,
            projects_home=projects_home,
            sample_delay_seconds=0,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )

    assert journal.is_file()
    assert not target_checkpoint.exists()
    assert target_sidecar.exists()
    if sidecar_kind != "directory":
        assert target_sidecar.read_bytes() == b"foreign-sidecar"


@pytest.mark.parametrize("foreign_role", ("main", "wal", "shm"))
def test_rollback_journal_recovery_refuses_concurrent_sqlite_bundle_delta(
    tmp_path: Path,
    monkeypatch,
    foreign_role: str,
) -> None:
    project, projects_home, _source, target, applied = _apply_with_target_before_state(tmp_path, monkeypatch)
    manifest = Path(str(applied["manifestPath"]))
    target_checkpoint = target / "checkpoints.sqlite"
    journal = target.parent / ".rwm-j.json"
    real_replace = storage_migration.os.replace
    crashed = False

    def crash_after_rollback_main_replace(source_path, destination_path):
        nonlocal crashed
        if not crashed and Path(destination_path) == target_checkpoint and Path(source_path).name.endswith(".staging"):
            real_replace(source_path, destination_path)
            crashed = True
            raise _SimulatedProcessCrash("crash during rollback")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(storage_migration.os, "replace", crash_after_rollback_main_replace)
    with pytest.raises(_SimulatedProcessCrash, match="crash during rollback"):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=manifest,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    rollback_main_sha = storage_migration._sha256_file(target_checkpoint)
    assert _table_values(target_checkpoint, "SELECT thread_id FROM checkpoints") == []
    foreign_path = (
        target_checkpoint
        if foreign_role == "main"
        else target_checkpoint.with_name(target_checkpoint.name + f"-{foreign_role}")
    )
    foreign_payload = f"foreign-{foreign_role}".encode()
    foreign_path.write_bytes(foreign_payload)

    monkeypatch.setattr(storage_migration.os, "replace", real_replace)
    with pytest.raises(ResearchWorkflowMigrationError, match="journal recovery target delta"):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=manifest,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )

    assert journal.is_file()
    assert foreign_path.read_bytes() == foreign_payload
    if foreign_role != "main":
        assert storage_migration._sha256_file(target_checkpoint) == rollback_main_sha


@pytest.mark.parametrize("foreign_role", ("main", "wal", "shm"))
def test_rollback_refuses_foreign_bundle_delta_after_journal_persisted(
    tmp_path: Path,
    monkeypatch,
    foreign_role: str,
) -> None:
    project, projects_home, _source, target, applied = _apply_with_target_before_state(tmp_path, monkeypatch)
    manifest = Path(str(applied["manifestPath"]))
    target_checkpoint = target / "checkpoints.sqlite"
    target_ledger = target / "workflow-ledger.sqlite"
    ledger_main_sha = storage_migration._sha256_file(target_ledger)
    journal = target.parent / ".rwm-j.json"
    real_write_journal = storage_migration._write_promotion_journal
    injected = False

    def write_journal_then_inject_delta(*args, **kwargs):
        nonlocal injected
        payload = real_write_journal(*args, **kwargs)
        if not injected and kwargs.get("operation") == "rollback":
            injected = True
            foreign_path = (
                target_ledger
                if foreign_role == "main"
                else target_ledger.with_name(target_ledger.name + f"-{foreign_role}")
            )
            foreign_path.write_bytes(f"foreign-{foreign_role}".encode())
        return payload

    monkeypatch.setattr(
        storage_migration,
        "_write_promotion_journal",
        write_journal_then_inject_delta,
    )
    with pytest.raises(
        ResearchWorkflowMigrationError,
        match="rollback failed and persistent journal recovery was incomplete",
    ):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=manifest,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )

    foreign_path = (
        target_ledger
        if foreign_role == "main"
        else target_ledger.with_name(target_ledger.name + f"-{foreign_role}")
    )
    assert journal.is_file()
    assert foreign_path.read_bytes() == f"foreign-{foreign_role}".encode()
    assert _table_values(target_checkpoint, "SELECT thread_id FROM checkpoints") == [("thread-1",)]
    if foreign_role != "main":
        assert storage_migration._sha256_file(target_ledger) == ledger_main_sha
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "completed"


def test_default_guard_does_not_upgrade_stale_raw_writers_to_ready(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import core.infrastructure.storage_migration as shared_storage_migration

    project, projects_home, _source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    monkeypatch.setattr(
        shared_storage_migration,
        "_probe_active_work",
        lambda _project: {"blocking": False, "uncertain": False, "claims": []},
    )
    monkeypatch.setattr(
        shared_storage_migration,
        "_probe_runtime_writers",
        lambda _project: {
            "blocking": True,
            "uncertain": False,
            "writers": [
                {"kind": "runtime_manager_lock", "path": "runtime-manager/daemon.lock"},
                {"kind": "work_run", "runKind": "source_collection_run", "runId": "dprun-stale"},
            ],
        },
    )
    monkeypatch.setattr(
        shared_storage_migration,
        "_probe_launcher_state",
        lambda _project: {"blocking": False, "uncertain": False, "alive": False},
    )
    monkeypatch.setattr(
        storage_migration,
        "_probe_source_collection_snapshots",
        lambda _project: {
            "blocking": False,
            "uncertain": False,
            "snapshots": [{"runId": "dprun-stale", "status": "running"}],
        },
    )
    monkeypatch.setattr(storage_migration, "_runtime_manager_live", lambda _project, _guard: (False, {}))

    result = preview_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
    )

    assert not result.ready
    assert any(item["code"] == "quiescence_guard_not_ready" for item in result.blockers)
    assert any(item["code"] == "stale_runtime_manager_lock" for item in result.warnings)

    acknowledged = acknowledge_proven_stale_runtime_quiescence(project)
    assert acknowledged["ok"] is True
    assert acknowledged["blockers"] == []
    assert acknowledged["operatorAcknowledgement"] == {
        "kind": "proven_stale_runtime_only",
        "warningCodes": ["stale_runtime_manager_lock", "stale_source_collection_snapshot"],
        "warningCount": 3,
    }
    assert any(
        item["code"] == "proven_stale_runtime_operator_acknowledged"
        for item in acknowledged["warnings"]
    )


def test_rollback_rechecks_guard_and_target_delta_after_staging(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, _source, target, apply = _apply_with_target_before_state(tmp_path, monkeypatch)
    manifest = Path(str(apply["manifestPath"]))
    real_stage = storage_migration._stage_rollback_plans

    def stage_then_change_target(*args, **kwargs):
        stages = real_stage(*args, **kwargs)
        (target / "runs" / "run-1.json").write_text('{"runId":"foreign"}\n', encoding="utf-8")
        return stages

    monkeypatch.setattr(storage_migration, "_stage_rollback_plans", stage_then_change_target)
    with pytest.raises(ResearchWorkflowMigrationError, match="target changed during rollback staging"):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=manifest,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "completed"
    assert (target / "runs" / "run-1.json").read_text(encoding="utf-8") == '{"runId":"foreign"}\n'


def test_legacy_placeholder_evidence_is_manifested_and_rechecked(tmp_path: Path, monkeypatch) -> None:
    project, projects_home, source, _target, _marker = _fixture_roots(tmp_path, monkeypatch)
    _create_current_ledger(source / "workflow-ledger.sqlite", include_blocked_run=True)
    legacy = source / "workflow-checkpoints.sqlite"
    legacy.write_bytes(b"")

    applied = apply_research_workflow_migration(
        project,
        projects_home=projects_home,
        sample_delay_seconds=0,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    manifest = Path(str(applied["manifestPath"]))
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    excluded = next(item for item in payload["excludedAssets"] if item["relativePath"] == legacy.name)
    assert excluded["classification"] == "legacy_placeholder_excluded"
    assert excluded["sourceEvidence"] == {
        "exists": True,
        "noSidecars": True,
        "sha256": storage_migration._sha256_file(legacy),
        "size": 0,
        "sourceFingerprint": payload["sourceFingerprint"],
    }
    assert any(item["code"] == "legacy_placeholder_excluded" for item in payload["warnings"])

    legacy.write_bytes(b"changed")
    verification = verify_research_workflow_migration(
        project,
        projects_home=projects_home,
        manifest_path=manifest,
        quiescence_probe=lambda _project: {"ok": True, "blockers": []},
    )
    assert any(item["code"] == "excluded_legacy_placeholder_changed" for item in verification["failures"])
    with pytest.raises(ResearchWorkflowMigrationError, match="legacy placeholder evidence changed"):
        rollback_research_workflow_migration(
            project,
            projects_home=projects_home,
            manifest_path=manifest,
            quiescence_probe=lambda _project: {"ok": True, "blockers": []},
        )
