"""WorkflowDefinitionRegistry: per-run version pinning (fail-closed)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from core.research.workflow.definition import (
    build_challenge_cup_workflow_definition,
    definition_structure_hash,
)
from core.research.workflow.definition_registry import (
    DefinitionIdentity,
    UnknownWorkflowDefinitionVersion,
    WorkflowDefinitionHashMismatch,
    WorkflowDefinitionNodeMismatch,
    WorkflowDefinitionSnapshotInvalid,
    bootstrap_builtin_definitions,
    bootstrap_definitions_from_dir,
    definition_snapshot_payload,
    parse_snapshot_payload,
    register_definition,
    register_definition_snapshot,
    register_or_resolve,
    registered_identities,
    reset_registry_for_tests,
    resolve_definition,
    resolve_definition_for_run_record,
    snapshot_dir,
    workflow_version_id_for,
)
from core.research.workflow.ledger import RunRecord, WorkflowLedgerStore
from core.research.workflow.ledger.schema import MIGRATIONS, Migration
from core.research.workflow.models import (
    ActorKind,
    GateKind,
    WorkflowDefinition,
    WorkflowEdgeSpec,
    WorkflowNodeSpec,
    WorkflowStageId,
)
from core.web.services.team_workflow.research_runtime.checkpoint_lifecycle import (
    advance_checkpoint,
    fork_checkpoint_at_node,
    prepare_initial_checkpoint,
)
from core.web.services.team_workflow.research_runtime.run_fork import (
    build_child_run_skeleton,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def build_variant_definition() -> WorkflowDefinition:
    """A test-only older version with observable topology differences.

    Differences from 2.1.0: an extra node ``legacy_smoke_echo`` in the last
    stage and ``source_finding`` routing to ``evidence_relations`` instead of
    ``source_extraction``.  Used to prove a run pinned to this version keeps
    being driven by the old graph.
    """
    base = build_challenge_cup_workflow_definition()
    extra_node = WorkflowNodeSpec(
        nodeId="legacy_smoke_echo",
        stageId=WorkflowStageId.EXECUTION_ITERATION,
        label="旧版试跑回声",
        actorKind=ActorKind.SYSTEM,
        primaryRoleKey="formal_runner",
    )
    nodes = (*base.nodes, extra_node)
    stages = tuple(
        dataclasses.replace(stage, nodeIds=(*stage.nodeIds, "legacy_smoke_echo"))
        if stage.stageId is WorkflowStageId.EXECUTION_ITERATION
        else stage
        for stage in base.stages
    )
    edges = [
        (
            WorkflowEdgeSpec(
                edgeId=edge.edgeId,
                fromNodeId=edge.fromNodeId,
                toNodeId="evidence_relations",
                label=edge.label,
                gateKind=edge.gateKind,
                requiredArtifactKinds=edge.requiredArtifactKinds,
                requiresHumanAccept=edge.requiresHumanAccept,
            )
            if edge.edgeId == "e_find_extract"
            else edge
        )
        for edge in base.edges
    ]
    edges.append(
        WorkflowEdgeSpec(
            "e_legacy_echo",
            "legacy_smoke_echo",
            "result_package",
            "回声",
            GateKind.AUTO,
            (),
        )
    )
    draft = WorkflowDefinition(
        workflowId=base.workflowId,
        schemaVersion="2.0.9-test",
        label="挑战杯科研流程（测试旧版）",
        stages=stages,
        nodes=nodes,
        edges=tuple(edges),
    )
    return dataclasses.replace(draft, structureHash=definition_structure_hash(draft))


def pinned_run_record(definition: WorkflowDefinition, run_id: str = "run-pinned") -> dict:
    identity = register_or_resolve(definition)
    return {
        "runId": run_id,
        "workflowId": definition.workflowId,
        "workflowVersionId": identity.workflowVersionId,
        "structureHash": definition.structureHash,
        "completedNodeIds": [],
        "runtimeCurrentNodeIds": [],
    }


# --------------------------------------------------------------------------
# Snapshot bootstrap and consistency with definition.py
# --------------------------------------------------------------------------


def test_builtin_snapshot_matches_current_definition_build() -> None:
    identities = bootstrap_builtin_definitions()
    current = build_challenge_cup_workflow_definition()
    payload = json.loads(
        (snapshot_dir() / "challenge-cup-research@2.1.0.json").read_text(encoding="utf-8")
    )
    assert payload["contentHash"] == definition_structure_hash(current)
    assert payload["snapshotKind"] == "workflow_definition_snapshot"
    parsed = parse_snapshot_payload(payload)
    assert parsed == current
    assert DefinitionIdentity(
        workflowId=current.workflowId,
        workflowVersionId=workflow_version_id_for(current.structureHash),
        structureHash=current.structureHash,
    ) in identities
    # snapshot is pure structure: no secrets, paths, or runtime data
    raw = (snapshot_dir() / "challenge-cup-research@2.1.0.json").read_text(encoding="utf-8")
    assert "\\" not in raw
    assert "http://" not in raw and "https://" not in raw


def test_registry_roundtrip() -> None:
    current = build_challenge_cup_workflow_definition()
    identity = register_or_resolve(current)
    assert identity.workflowVersionId == f"wv-{current.structureHash[:12]}"
    resolved = resolve_definition(
        workflow_id=current.workflowId,
        workflow_version_id=identity.workflowVersionId,
        structure_hash=current.structureHash,
    )
    assert resolved == current
    assert identity in registered_identities(current.workflowId)
    # re-register is idempotent
    assert register_or_resolve(current) == identity


# --------------------------------------------------------------------------
# Tamper / corruption fail-closed
# --------------------------------------------------------------------------


def test_tampered_snapshot_payload_is_blocked() -> None:
    current = build_challenge_cup_workflow_definition()
    payload = definition_snapshot_payload(current)
    nodes = [dict(item) for item in payload["definition"]["nodes"]]
    nodes[0]["label"] = "被篡改的节点"
    tampered = {**payload, "definition": {**payload["definition"], "nodes": nodes}}
    with pytest.raises(WorkflowDefinitionHashMismatch):
        register_definition_snapshot(tampered)


def test_snapshot_without_content_hash_is_blocked() -> None:
    payload = definition_snapshot_payload(build_challenge_cup_workflow_definition())
    broken = {k: v for k, v in payload.items() if k != "contentHash"}
    with pytest.raises(WorkflowDefinitionSnapshotInvalid):
        register_definition_snapshot(broken)


def test_corrupt_snapshot_file_blocks_bootstrap(tmp_path: Path) -> None:
    (tmp_path / "challenge-cup-research@2.1.0.json").write_text(
        "{not json at all", encoding="utf-8"
    )
    with pytest.raises(WorkflowDefinitionSnapshotInvalid):
        bootstrap_definitions_from_dir(tmp_path)


def test_snapshot_filename_without_version_blocks_bootstrap(tmp_path: Path) -> None:
    (tmp_path / "challenge-cup-research.json").write_text("{}", encoding="utf-8")
    with pytest.raises(WorkflowDefinitionSnapshotInvalid):
        bootstrap_definitions_from_dir(tmp_path)


# --------------------------------------------------------------------------
# Version pinning of checkpoint operations
# --------------------------------------------------------------------------


def test_run_pinned_to_old_version_advances_with_old_graph(tmp_path: Path) -> None:
    old_definition = build_variant_definition()
    record = pinned_run_record(old_definition, run_id="run-old")
    db = tmp_path / "checkpoints.sqlite"
    checkpoint_id = prepare_initial_checkpoint(
        str(db), "thread-old", definition=old_definition
    )
    pinned = resolve_definition_for_run_record(record)
    assert pinned == old_definition
    _, scheduled = advance_checkpoint(
        str(db),
        thread_id="thread-old",
        checkpoint_id=checkpoint_id,
        completed_node_id="source_finding",
        state_patch={
            "current_node_id": "source_finding",
            "completed_node_ids": ["source_finding"],
        },
        definition=pinned,
    )
    # old topology: source_finding -> evidence_relations (not source_extraction)
    assert scheduled == ["evidence_relations"]


def test_run_pinned_to_2_1_0_keeps_snapshot_graph_while_variant_registered() -> None:
    variant = build_variant_definition()
    register_or_resolve(variant)
    current = build_challenge_cup_workflow_definition()
    record = pinned_run_record(current, run_id="run-current")
    assert record["structureHash"] != variant.structureHash
    resolved = resolve_definition_for_run_record(record)
    assert resolved == current


def test_fork_uses_parent_pinned_graph_and_inherits_version(tmp_path: Path) -> None:
    old_definition = build_variant_definition()
    parent_record = pinned_run_record(old_definition, run_id="run-old")
    parent_record["threadId"] = "thread-old"
    db = tmp_path / "checkpoints.sqlite"
    checkpoint_id = prepare_initial_checkpoint(
        str(db), "thread-old", definition=old_definition
    )
    # give the parent thread real state so the checkpoint is forkable
    checkpoint_id, _ = advance_checkpoint(
        str(db),
        thread_id="thread-old",
        checkpoint_id=checkpoint_id,
        completed_node_id="source_finding",
        state_patch={
            "current_node_id": "source_finding",
            "completed_node_ids": ["source_finding"],
        },
        definition=old_definition,
    )
    child_record = build_child_run_skeleton(
        parent=parent_record,
        decision={"decisionId": "dec-1"},
        fork_checkpoint_id=checkpoint_id,
        utc_now=lambda: "2026-01-01T00:00:00Z",
        child_run_id="run-child",
    )
    # fork copied the parent's version identity
    assert child_record["workflowVersionId"] == parent_record["workflowVersionId"]
    assert child_record["structureHash"] == old_definition.structureHash
    assert resolve_definition_for_run_record(child_record) == old_definition
    # fork compiles the parent's pinned graph: only valid on the old topology
    child_checkpoint_id = fork_checkpoint_at_node(
        str(db),
        source_thread_id="thread-old",
        source_checkpoint_id=checkpoint_id,
        child_thread_id="thread-child",
        predecessor_node_id="source_finding",
        resume_node_id="evidence_relations",
        state_patch={"current_node_id": "source_finding"},
        definition=resolve_definition_for_run_record(parent_record),
    )
    assert child_checkpoint_id


# --------------------------------------------------------------------------
# Fail-closed resolution with diagnostics
# --------------------------------------------------------------------------


def test_unknown_version_fails_closed_with_diagnostics() -> None:
    bootstrap_builtin_definitions()
    record = {
        "runId": "run-legacy",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-00000000dead",
        "structureHash": "0" * 64,
        "completedNodeIds": [],
        "runtimeCurrentNodeIds": [],
    }
    with pytest.raises(UnknownWorkflowDefinitionVersion) as excinfo:
        resolve_definition_for_run_record(record)
    message = str(excinfo.value)
    assert "run-legacy" in message
    assert "wv-00000000dead" in message
    assert "registeredVersions" in message


def test_structure_hash_mismatch_fails_closed() -> None:
    bootstrap_builtin_definitions()
    current = build_challenge_cup_workflow_definition()
    record = {
        "runId": "run-drift",
        "workflowId": current.workflowId,
        "workflowVersionId": workflow_version_id_for(current.structureHash),
        "structureHash": "f" * 64,
        "completedNodeIds": [],
        "runtimeCurrentNodeIds": [],
    }
    with pytest.raises(WorkflowDefinitionHashMismatch) as excinfo:
        resolve_definition_for_run_record(record)
    assert "run-drift" in str(excinfo.value)


def test_node_set_mismatch_fails_closed() -> None:
    bootstrap_builtin_definitions()
    variant = build_variant_definition()
    register_or_resolve(variant)
    current = build_challenge_cup_workflow_definition()
    record = {
        "runId": "run-mixed",
        "workflowId": current.workflowId,
        "workflowVersionId": workflow_version_id_for(current.structureHash),
        "structureHash": current.structureHash,
        "completedNodeIds": ["legacy_smoke_echo"],
        "runtimeCurrentNodeIds": [],
    }
    with pytest.raises(WorkflowDefinitionNodeMismatch) as excinfo:
        resolve_definition_for_run_record(record)
    assert "legacy_smoke_echo" in str(excinfo.value)


def test_register_operations_entry_point_restores_old_version() -> None:
    # Simulate ops rebuilding an old version from its snapshot payload.
    old_definition = build_variant_definition()
    payload = definition_snapshot_payload(old_definition)
    identity = register_definition_snapshot(payload)
    assert identity == DefinitionIdentity(
        workflowId=old_definition.workflowId,
        workflowVersionId=workflow_version_id_for(old_definition.structureHash),
        structureHash=old_definition.structureHash,
    )
    assert resolve_definition(
        workflow_id=old_definition.workflowId,
        workflow_version_id=identity.workflowVersionId,
        structure_hash=old_definition.structureHash,
    ) == old_definition


def test_register_definition_without_hash_is_blocked() -> None:
    draft = dataclasses.replace(build_challenge_cup_workflow_definition(), structureHash="")
    with pytest.raises(WorkflowDefinitionSnapshotInvalid):
        register_definition(draft)


# --------------------------------------------------------------------------
# Ledger v6 migration: workflow_runs.structure_hash
# --------------------------------------------------------------------------


def _v6_migration() -> Migration:
    return next(m for m in MIGRATIONS if m.version == 6)


def test_ledger_v6_migration_exists_and_is_additive() -> None:
    migration = _v6_migration()
    assert len(migration.statements) == 1
    assert "ADD COLUMN structure_hash" in migration.statements[0]
    assert "DEFAULT ''" in migration.statements[0]


def test_ledger_run_record_roundtrips_structure_hash(tmp_path: Path) -> None:
    store = WorkflowLedgerStore(tmp_path / "ledger.sqlite3")
    store.open()
    try:
        current = build_challenge_cup_workflow_definition()
        record = RunRecord(
            run_id="run-pinned",
            team_id="research-team",
            workflow_id=current.workflowId,
            workflow_version_id=workflow_version_id_for(current.structureHash),
            thread_id="thread-pinned",
            project_id="proj-1",
            question_id="SCI-096",
            status="created",
            run_version=1,
            last_event_sequence=0,
            input_snapshot_json="{}",
            input_snapshot_hash="a" * 64,
            safety_limits_json="{}",
            binding_snapshot_set_id="binding-1",
            active_node_id=None,
            parent_run_id=None,
            forked_from_checkpoint_id=None,
            completion_kind=None,
            terminal_reason=None,
            blocked_problem_json=None,
            created_at_ms=1,
            updated_at_ms=1,
            completed_at_ms=None,
            structure_hash=current.structureHash,
        )
        store.submit(
            lambda uow: uow.repository.insert_run(record), force_flush=True
        ).result(timeout=10)
        loaded = store.submit(
            lambda uow: uow.repository.get_run("run-pinned"), force_flush=True
        ).result(timeout=10)
        assert loaded is not None and loaded.structure_hash == current.structureHash
    finally:
        store.close()


def test_ledger_v5_database_upgrades_in_place_with_empty_hash(tmp_path: Path) -> None:
    import apsw

    path = tmp_path / "ledger.sqlite3"
    store = WorkflowLedgerStore(path)
    store.open()
    store.close()

    # Revert the DB to the v5 shape: drop the column and forget migration 6.
    connection = apsw.Connection(str(path))
    connection.execute("DELETE FROM schema_migrations WHERE version = 6")
    connection.execute("ALTER TABLE workflow_runs DROP COLUMN structure_hash")
    connection.close()

    store = WorkflowLedgerStore(path)
    store.open()
    try:
        record = RunRecord(
            run_id="run-v5-legacy",
            team_id="research-team",
            workflow_id="challenge-cup-research",
            workflow_version_id="wv-9a4b74e7f21a",
            thread_id="thread-v5-legacy",
            project_id="proj-1",
            question_id="SCI-096",
            status="created",
            run_version=1,
            last_event_sequence=0,
            input_snapshot_json="{}",
            input_snapshot_hash="a" * 64,
            safety_limits_json="{}",
            binding_snapshot_set_id="binding-1",
            active_node_id=None,
            parent_run_id=None,
            forked_from_checkpoint_id=None,
            completion_kind=None,
            terminal_reason=None,
            blocked_problem_json=None,
            created_at_ms=1,
            updated_at_ms=1,
            completed_at_ms=None,
        )
        store.submit(
            lambda uow: uow.repository.insert_run(record), force_flush=True
        ).result(timeout=10)
        loaded = store.submit(
            lambda uow: uow.repository.get_run("run-v5-legacy"), force_flush=True
        ).result(timeout=10)
        assert loaded is not None
        # old rows pin by workflowVersionId only; hash stays empty and
        # resolution by version id still succeeds against the registry.
        assert loaded.structure_hash == ""
    finally:
        store.close()
