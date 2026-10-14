"""Archived workflows retain formal reads without opening a mutation runtime."""

from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.ledger import WorkflowLedgerStore
from core.web.services.team_workflow.research_runtime import formal_read_runtime, runtime_factory
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    FormalWriteRuntimeUnavailable,
    WorkflowMigrationRequired,
    get_command_service,
    get_write_store,
)
from core.web.services.team_workflow.research_runtime.real_readiness_context import (
    RealDomainReadinessContext,
    _budget_consumed_from_ledger,
    _run_ids_for,
)
from tests._support.workflow_ledger_helpers import build_attempt_record, build_command_record, build_event_record, build_run_record


def _seed_archive(path: Path) -> None:
    store = WorkflowLedgerStore(path)
    store.open()
    try:
        version = register_or_resolve(build_challenge_cup_workflow_definition()).workflowVersionId
        record = replace(build_run_record(workflow_version_id=version, status="archived"),
                         last_event_sequence=1)
        def seed(uow):
            uow.repository.insert_run(record)
            uow.repository.insert_command(build_command_record())
            uow.repository.insert_attempt(build_attempt_record(node_run_id="node-test"))
            uow.repository.insert_event(build_event_record(sequence=1))
            uow.repository.insert_budget_receipt(
                receipt_id="receipt-archive", run_id="run-test", node_run_id="node-test",
                reservation_id="reservation-archive", stage_id="knowledge_collection",
                policy_hash="policy", reserved_json='{"tokens":17,"toolCalls":2}',
                created_at_ms=record.created_at_ms,
            )
        store.submit(seed, force_flush=True).result(timeout=10)
    finally:
        store.close()


def test_archive_initializes_formal_reads_without_writer_or_workers(tmp_path, monkeypatch):
    path = tmp_path / "workflow-ledger.sqlite"
    _seed_archive(path)
    before = path.read_bytes()
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("VIBELUTION_CHALLENGE_ARCHIVE_MODE", "1")
    runtime_factory.stop_production_workflow_runtime()

    def forbidden(*args, **kwargs):
        pytest.fail("archive reads must not initialize a writer, coordinator or pump")
    monkeypatch.setattr(WorkflowLedgerStore, "open", forbidden)
    monkeypatch.setattr(WorkflowLedgerStore, "initialize", forbidden)
    monkeypatch.setattr(runtime_factory, "WorkflowOutboxPump", forbidden)
    monkeypatch.setattr(runtime_factory, "ChallengeCupGraphCoordinator", forbidden)
    try:
        assert runtime_factory.start_production_workflow_runtime() == "archive_mode"
        query = formal_read_runtime.get_query_service()
        assert query.list_runs(team_id="research-team", workflow_id="challenge-cup-research")["runs"][0]["runId"] == "run-test"
        assert query.get_snapshot(team_id="research-team", run_id="run-test").run.status == "archived"
        events = formal_read_runtime.get_event_replay_service().list_events(
            team_id="research-team", run_id="run-test", after_sequence=0, limit=10,
        )
        assert len(events.events) == 1
        assert formal_read_runtime.get_event_stream_service() is not None
        assert runtime_factory.production_workflow_runtime() is None
        assert runtime_factory._PUMP is None
        assert query._store._writer is None
        assert runtime_factory.start_production_workflow_runtime() == "archive_mode"
        assert formal_read_runtime.get_query_service() is query
        with pytest.raises(FormalWriteRuntimeUnavailable):
            get_command_service()
        with pytest.raises(FormalWriteRuntimeUnavailable):
            get_write_store()
        with pytest.raises(Exception, match="readonly|read.only"):
            query._store.read(lambda repo: repo.execute("DELETE FROM workflow_runs"))
    finally:
        runtime_factory.stop_production_workflow_runtime()
    assert path.read_bytes() == before
    with pytest.raises(formal_read_runtime.FormalReadRuntimeUnavailable):
        formal_read_runtime.get_query_service()


def test_readiness_facts_work_on_reader_only_store(tmp_path):
    path = tmp_path / "workflow-ledger.sqlite"
    _seed_archive(path)
    store = WorkflowLedgerStore(path)
    try:
        context = RealDomainReadinessContext(store)
        assert context.recovery_blocker_codes("run-test") == []
        assert context.incoming_handoffs("run-test", "problem_understanding") == []
        assert _run_ids_for(store, "research-team") == ["run-test"]
        assert _budget_consumed_from_ledger(store, "run-test", stage_id="knowledge_collection")["tokens"] == 17
        assert context.accepted_knowledge_invocations("research-team", "run-test") == []
        assert store._writer is None
    finally:
        store.close()


def test_archive_missing_ledger_fails_closed_without_creating_database(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("VIBELUTION_CHALLENGE_ARCHIVE_MODE", "1")
    runtime_factory.stop_production_workflow_runtime()
    try:
        assert runtime_factory.start_production_workflow_runtime() == "unavailable"
        with pytest.raises(formal_read_runtime.FormalReadRuntimeUnavailable):
            formal_read_runtime.get_query_service()
        assert not (tmp_path / "workflow-ledger.sqlite").exists()
    finally:
        runtime_factory.stop_production_workflow_runtime()


def test_archive_respects_unactivated_legacy_migration(tmp_path, monkeypatch):
    path = tmp_path / "workflow-ledger.sqlite"
    _seed_archive(path)
    before = path.read_bytes()
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "run-legacy.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("VIBELUTION_CHALLENGE_ARCHIVE_MODE", "1")
    runtime_factory.stop_production_workflow_runtime()
    before_paths = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    try:
        assert runtime_factory.start_production_workflow_runtime() == "migration_required"
        with pytest.raises(WorkflowMigrationRequired):
            formal_read_runtime.get_query_service()
        assert path.read_bytes() == before
        assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before_paths

        # An operator may activate migration before retrying initialization.
        # This test-only manifest must restore reads without enabling writes.
        from core.research.workflow.migration.manifest import write_manifest
        write_manifest(tmp_path, {"status": "activated"})
        assert runtime_factory.start_production_workflow_runtime() == "archive_mode"
        assert formal_read_runtime.get_query_service().list_runs(
            team_id="research-team", workflow_id="challenge-cup-research"
        )["runs"]
        with pytest.raises(FormalWriteRuntimeUnavailable):
            get_command_service()
    finally:
        runtime_factory.stop_production_workflow_runtime()


def test_archive_stop_preserves_another_read_facade_owner(tmp_path, monkeypatch):
    path = tmp_path / "workflow-ledger.sqlite"
    _seed_archive(path)
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("VIBELUTION_CHALLENGE_ARCHIVE_MODE", "1")
    runtime_factory.stop_production_workflow_runtime()
    replacement = WorkflowLedgerStore(path)
    try:
        assert runtime_factory.start_production_workflow_runtime() == "archive_mode"
        original = formal_read_runtime.get_query_service()
        formal_read_runtime.configure_formal_read_runtime(
            store=replacement, readiness_service=original._readiness,
            readiness_context=lambda: RealDomainReadinessContext(replacement),
        )
        replacement_query = formal_read_runtime.get_query_service()
        runtime_factory.stop_production_workflow_runtime()
        assert formal_read_runtime.get_query_service() is replacement_query
        assert replacement_query.list_runs(team_id="research-team", workflow_id="challenge-cup-research")["runs"]
    finally:
        runtime_factory.stop_production_workflow_runtime()
        formal_read_runtime.release_formal_read_runtime(replacement)
        replacement.close()
