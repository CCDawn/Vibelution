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
    resolve_definition_by_version_id,
    resolve_definition_for_run_record,
    resolve_historical_definition,
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
from core.web.services.team_workflow.research_runtime.agent_task_artifact_builder import (
    _source_artifact_ids,
)
from core.web.services.team_workflow.research_runtime.handoff_builder import (
    build_handoff_record,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def build_variant_definition() -> WorkflowDefinition:
    """A test-only custom definition with observable topology differences.

    It adds ``snapshot_smoke_echo`` in the last
    stage and ``source_finding`` routing to ``evidence_relations`` instead of
    ``source_extraction``. Used to prove registry pinning without adding a
    second built-in Challenge Cup version.
    """
    base = build_challenge_cup_workflow_definition()
    extra_node = WorkflowNodeSpec(
        nodeId="snapshot_smoke_echo",
        stageId=WorkflowStageId.EXECUTION_ITERATION,
        label="快照试跑回声",
        actorKind=ActorKind.SYSTEM,
        primaryRoleKey="formal_runner",
    )
    nodes = (*base.nodes, extra_node)
    stages = tuple(
        dataclasses.replace(stage, nodeIds=(*stage.nodeIds, "snapshot_smoke_echo"))
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
            "e_snapshot_echo",
            "snapshot_smoke_echo",
            "result_package",
            "回声",
            GateKind.AUTO,
            (),
        )
    )
    draft = WorkflowDefinition(
        workflowId=base.workflowId,
        schemaVersion="3.0.0-test",
        label="挑战杯科研流程（测试快照）",
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


def test_current_downstream_artifact_and_handoff_use_pinned_definition() -> None:
    definition = build_challenge_cup_workflow_definition()
    record = pinned_run_record(definition, run_id="run-v3-downstream")
    record["artifactManifests"] = [
        {"artifactId": "problem_understanding:current"},
        {"artifactId": "knowledge_package:legacy-default"},
    ]

    assert _source_artifact_ids(record, "hypothesis_design") == [
        "problem_understanding:current"
    ]
    handoff = build_handoff_record(
        run_id=record["runId"],
        workflow_id=record["workflowId"],
        workflow_version_id=record["workflowVersionId"],
        from_node_id="problem_understanding",
        status="pending",
        definition=definition,
    )
    assert handoff["toNodeId"] == "hypothesis_design"
    assert handoff["edgeId"] == "e_problem_hypothesis"


# --------------------------------------------------------------------------
# Snapshot bootstrap and consistency with definition.py
# --------------------------------------------------------------------------


def test_builtin_snapshot_matches_current_definition_build() -> None:
    identities = bootstrap_builtin_definitions()
    current = build_challenge_cup_workflow_definition()
    payload = json.loads(
        (snapshot_dir() / "challenge-cup-research@3.0.0.json").read_text(encoding="utf-8")
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
    assert [
        item
        for item in identities
        if item.workflowId == "challenge-cup-research"
    ] == [
        DefinitionIdentity(
            workflowId=current.workflowId,
            workflowVersionId=workflow_version_id_for(current.structureHash),
            structureHash=current.structureHash,
        )
    ]
    # snapshot is pure structure: no secrets, paths, or runtime data
    raw = (snapshot_dir() / "challenge-cup-research@3.0.0.json").read_text(encoding="utf-8")
    assert "\\" not in raw
    assert "http://" not in raw and "https://" not in raw


@pytest.mark.parametrize(
    ("version_id", "structure_hash", "schema_version"),
    [
        (
            "wv-9a4b74e7f21a",
            "9a4b74e7f21a409c55ed2ef0faf4a61f9c777368b775da3c666c8a8cfc320d53",
            "2.1.0",
        ),
        (
            "wv-dc2772597d64",
            "dc2772597d64f047ef36a0bbb2add78adf4134b8d8c5442cdfcdc5e1fbd75378",
            "2.2.0-stage-one",
        ),
    ],
)
def test_retired_definition_is_projection_only_and_never_registered(
    version_id: str,
    structure_hash: str,
    schema_version: str,
) -> None:
    legacy = resolve_historical_definition(
        workflow_id="challenge-cup-research",
        workflow_version_id=version_id,
        structure_hash=structure_hash,
        run_id="run-retired-v21",
    )
    assert legacy.schemaVersion == schema_version
    assert "source_finding" in {node.nodeId for node in legacy.nodes}
    assert {
        identity.workflowVersionId
        for identity in registered_identities("challenge-cup-research")
    } == {
        workflow_version_id_for(build_challenge_cup_workflow_definition().structureHash)
    }
    with pytest.raises(UnknownWorkflowDefinitionVersion):
        resolve_definition_by_version_id(version_id)


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
    (tmp_path / "challenge-cup-research@3.0.0.json").write_text(
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


def test_run_pinned_to_current_keeps_snapshot_graph_while_variant_registered() -> None:
    variant = build_variant_definition()
    register_or_resolve(variant)
    current = build_challenge_cup_workflow_definition()
    record = pinned_run_record(current, run_id="run-current")
    assert record["structureHash"] != variant.structureHash
    resolved = resolve_definition_for_run_record(record)
    assert resolved == current


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
        "completedNodeIds": ["snapshot_smoke_echo"],
        "runtimeCurrentNodeIds": [],
    }
    with pytest.raises(WorkflowDefinitionNodeMismatch) as excinfo:
        resolve_definition_for_run_record(record)
    assert "snapshot_smoke_echo" in str(excinfo.value)


def test_register_operations_entry_point_loads_explicit_snapshot() -> None:
    custom_definition = build_variant_definition()
    payload = definition_snapshot_payload(custom_definition)
    identity = register_definition_snapshot(payload)
    assert identity == DefinitionIdentity(
        workflowId=custom_definition.workflowId,
        workflowVersionId=workflow_version_id_for(custom_definition.structureHash),
        structureHash=custom_definition.structureHash,
    )
    assert resolve_definition(
        workflow_id=custom_definition.workflowId,
        workflow_version_id=identity.workflowVersionId,
        structure_hash=custom_definition.structureHash,
    ) == custom_definition


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
