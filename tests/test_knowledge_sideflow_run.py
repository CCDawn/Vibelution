"""Knowledge sideflow child WorkflowRun: definitions, invocations, lineage.

Covers Task 3's child-run surface:
- sideflow (1.0.0) and main-flow (3.0.0) definitions register through the
  snapshots and resolve fail-closed per run;
- invocation call idempotency vs knowledge reuse (two separate decisions);
- child run creation leaves the parent run untouched except ONE appended
  event;
- the five-node sideflow advances through real checkpoint/attempt commits and
  the producer's event_publish row lands in the SAME transaction as the
  child terminal facts.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.research.workflow.challenge_cup_runtime import (
    ChallengeCupGraphCoordinator,
)
from core.research.workflow.contracts.knowledge_sideflow import (
    KnowledgeResultAvailablePayload,
    knowledge_result_dedup_key,
)
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import (
    definition_snapshot_payload,
    parse_snapshot_payload,
    register_or_resolve,
    registered_identities,
    resolve_definition_by_version_id,
    resolve_definition_for_run_record,
    snapshot_dir,
)
from core.research.workflow.knowledge_sideflow_definition import (
    CHALLENGE_CUP_RESEARCH_SCHEMA_VERSION_V3,
    KNOWLEDGE_SIDEFLOW_NODE_IDS,
    KNOWLEDGE_SIDEFLOW_SCHEMA_VERSION,
    KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
    build_challenge_cup_workflow_definition_v3,
    build_knowledge_sideflow_workflow_definition,
)
from core.research.workflow.models import WorkflowStageId
from core.research.workflow.ledger.schema import SCHEMA_VERSION
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_event_record

from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
    KnowledgeSideflowError,
    absorb_knowledge_result,
    compute_invocation_fingerprints,
    ensure_knowledge_invocation,
    knowledge_sideflow_child_run_id,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    from core.research.workflow.definition_registry import reset_registry_for_tests

    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def _main_version_id() -> str:
    return register_or_resolve(build_challenge_cup_workflow_definition()).workflowVersionId


def _seed_parent(harness: GraphHarness, run_id: str = "run-parent") -> None:
    harness.commands.seed_run(
        run_id,
        workflow_id="challenge-cup-research",
        workflow_version_id=_main_version_id(),
        status="running",
    )


def _request_kwargs(**overrides):
    kwargs = {
        "question_id": "SCI-096",
        "parent_node_id": "hypothesis_design",
        "scope": {"questionId": "SCI-096", "projectId": "challenge-sci-096"},
        "search_envelope": {"keywords": ["evaporation", "cooling"], "limits": {"topK": 5}},
        "requirements": {"minSources": 3},
        "source_policy_version": "1",
    }
    kwargs.update(overrides)
    return kwargs


def _invoke(harness: GraphHarness, parent_run_id: str = "run-parent", **overrides):
    return ensure_knowledge_invocation(
        harness.commands.store,
        parent_run_id=parent_run_id,
        parent_node_run_id="nr-run-parent-hypothesis_design-a1",
        parent_attempt=1,
        now_provider=lambda: FIXED_NOW_MS + 1000,
        **_request_kwargs(**overrides),
    )


def _child_rows(harness: GraphHarness):
    return harness.commands.store.submit(
        lambda uow: uow.repository.execute(
            "SELECT run_id, workflow_id, parent_run_id, completion_kind, status "
            "FROM workflow_runs WHERE workflow_id = ? ORDER BY run_id",
            (KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,),
        ).fetchall(),
        force_flush=True,
    ).result(timeout=10)


def _invocation_row(harness: GraphHarness, invocation_id: str):
    return harness.commands.store.submit(
        lambda uow: uow.repository.get_knowledge_invocation(invocation_id),
        force_flush=True,
    ).result(timeout=10)


def _outbox_rows(harness: GraphHarness, run_id: str, action_kind: str):
    return harness.commands.store.submit(
        lambda uow: uow.repository.execute(
            "SELECT action_id, status, payload_json, idempotency_key FROM outbox_actions "
            "WHERE run_id = ? AND action_kind = ? ORDER BY created_at_ms, action_id",
            (run_id, action_kind),
        ).fetchall(),
        force_flush=True,
    ).result(timeout=10)


# --------------------------------------------------------------------------
# Definitions: registration, snapshots, pinned resolution
# --------------------------------------------------------------------------


def test_sideflow_and_v3_definitions_bootstrap_and_pin(tmp_path: Path) -> None:
    identities = registered_identities()
    by_workflow = {identity.workflowId: identity for identity in identities}
    assert KNOWLEDGE_SIDEFLOW_WORKFLOW_ID in by_workflow
    assert "challenge-cup-research" in by_workflow

    sideflow = build_knowledge_sideflow_workflow_definition()
    resolved = resolve_definition_by_version_id(
        by_workflow[KNOWLEDGE_SIDEFLOW_WORKFLOW_ID].workflowVersionId
    )
    assert resolved.structureHash == sideflow.structureHash
    assert [node.nodeId for node in resolved.nodes] == list(KNOWLEDGE_SIDEFLOW_NODE_IDS)
    assert resolved.schemaVersion == KNOWLEDGE_SIDEFLOW_SCHEMA_VERSION
    handoff = next(node for node in resolved.nodes if node.nodeId == "knowledge_handoff")
    assert handoff.actorKind.value == "human"
    edge_pairs = [(edge.fromNodeId, edge.toNodeId) for edge in resolved.edges]
    assert edge_pairs == [
        ("source_finding", "source_extraction"),
        ("source_extraction", "evidence_relations"),
        ("evidence_relations", "knowledge_ingestion"),
        ("knowledge_ingestion", "knowledge_handoff"),
    ]

    v3 = build_challenge_cup_workflow_definition_v3()
    assert v3.workflowId == "challenge-cup-research"
    assert v3.schemaVersion == CHALLENGE_CUP_RESEARCH_SCHEMA_VERSION_V3
    assert len(v3.nodes) == 12
    v3_ids = {node.nodeId for node in v3.nodes}
    assert "problem_understanding" in v3_ids
    assert not (v3_ids & set(KNOWLEDGE_SIDEFLOW_NODE_IDS))
    v3_edges = {(edge.edgeId, edge.fromNodeId, edge.toNodeId) for edge in v3.edges}
    assert ("e_problem_hypothesis", "problem_understanding", "hypothesis_design") in v3_edges
    assert all(edge.edgeId != "e_kc_hypothesis" for edge in v3.edges)
    # 知识搜集已移出主流程：3.0.0 首阶段不再沿用 knowledge_collection 命名
    first_stage = v3.stages[0]
    assert first_stage.stageId == WorkflowStageId.PROBLEM_UNDERSTANDING
    assert first_stage.label == "问题理解"
    assert first_stage.nodeIds == ("problem_understanding",)
    assert all(stage.stageId != WorkflowStageId.KNOWLEDGE_COLLECTION for stage in v3.stages)
    entry_node = next(node for node in v3.nodes if node.nodeId == "problem_understanding")
    assert entry_node.stageId == WorkflowStageId.PROBLEM_UNDERSTANDING


def test_default_definition_stays_2_1_0() -> None:
    default = build_challenge_cup_workflow_definition()
    assert default.schemaVersion == "2.1.0"
    assert len(default.nodes) == 17


def test_snapshots_on_disk_parse_and_match_builders(tmp_path: Path) -> None:
    sideflow_payload = json.loads(
        (snapshot_dir() / "challenge-cup-knowledge-sideflow@1.0.0.json").read_text(
            encoding="utf-8"
        )
    )
    v3_payload = json.loads(
        (snapshot_dir() / f"challenge-cup-research@{CHALLENGE_CUP_RESEARCH_SCHEMA_VERSION_V3}.json").read_text(
            encoding="utf-8"
        )
    )
    parsed_sideflow = parse_snapshot_payload(sideflow_payload)
    parsed_v3 = parse_snapshot_payload(v3_payload)
    assert parsed_sideflow == build_knowledge_sideflow_workflow_definition()
    assert parsed_v3 == build_challenge_cup_workflow_definition_v3()
    assert sideflow_payload == definition_snapshot_payload(parsed_sideflow)


def test_sideflow_run_record_resolves_pinned_definition(tmp_path: Path) -> None:
    sideflow = build_knowledge_sideflow_workflow_definition()
    identity = register_or_resolve(sideflow)
    definition = resolve_definition_for_run_record(
        {
            "runId": "run-sideflow",
            "workflowId": KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
            "workflowVersionId": identity.workflowVersionId,
            "structureHash": identity.structureHash,
            "completedNodeIds": ["source_finding"],
            "runtimeCurrentNodeIds": [],
        }
    )
    assert definition.structureHash == sideflow.structureHash
    with pytest.raises(Exception, match="missingNodes"):
        resolve_definition_for_run_record(
            {
                "runId": "run-sideflow",
                "workflowId": KNOWLEDGE_SIDEFLOW_WORKFLOW_ID,
                "workflowVersionId": identity.workflowVersionId,
                "structureHash": identity.structureHash,
                "completedNodeIds": ["iteration_decision"],
                "runtimeCurrentNodeIds": [],
            }
        )


def test_sideflow_and_v3_graphs_compile_with_pinned_entry(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    from core.web.services.team_workflow.research_runtime.checkpoint_lifecycle import (
        prepare_initial_checkpoint,
    )

    sideflow = build_knowledge_sideflow_workflow_definition()
    sideflow_identity = register_or_resolve(sideflow)
    coordinator = ChallengeCupGraphCoordinator(checkpoint_path)
    prepare_initial_checkpoint(
        str(checkpoint_path), "thread-sf", definition=sideflow
    )
    snap = coordinator.snapshot("thread-sf", sideflow_identity.workflowVersionId)
    assert snap["nextNodeIds"] == ["source_finding"]

    v3 = build_challenge_cup_workflow_definition_v3()
    v3_identity = register_or_resolve(v3)
    prepare_initial_checkpoint(str(checkpoint_path), "thread-v3", definition=v3)
    snap_v3 = coordinator.snapshot("thread-v3", v3_identity.workflowVersionId)
    assert snap_v3["nextNodeIds"] == ["problem_understanding"]


# --------------------------------------------------------------------------
# Invocations: call idempotency and knowledge reuse
# --------------------------------------------------------------------------


def test_invocation_call_idempotency_replays_same_invocation_and_child(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        first = _invoke(harness)
        assert first["replayed"] is False
        assert first["reused"] is False
        assert first["childRunId"]

        second = _invoke(harness)
        assert second["replayed"] is True
        assert second["invocation"].invocation_id == first["invocation"].invocation_id
        assert second["childRunId"] == first["childRunId"]
        assert len(_child_rows(harness)) == 1
    finally:
        harness.close()


def test_knowledge_reuse_references_existing_package_without_new_child(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        first = _invoke(harness)
        invocation = first["invocation"]
        # Simulate a completed source invocation with a consumable package.
        harness.commands.store.submit(
            lambda uow: uow.repository.update_knowledge_invocation(
                invocation.invocation_id,
                FIXED_NOW_MS + 5,
                status="completed",
                knowledge_package_ref=json.dumps({"artifactId": "art-kp-1"}),
                package_content_hash="a" * 64,
                handoff_state="accepted",
            ),
            force_flush=True,
        ).result(timeout=10)

        # Same request from a DIFFERENT parent node: not a call replay, but
        # knowledge reuse — a new invocation row referencing the same package,
        # no second child run.
        reused = _invoke(harness, parent_node_id="protocol_review")
        assert reused["replayed"] is False
        assert reused["reused"] is True
        assert reused["childRunId"] is None
        assert reused["invocation"].invocation_id != invocation.invocation_id
        assert reused["invocation"].knowledge_package_ref == json.dumps(
            {"artifactId": "art-kp-1"}
        )
        assert reused["invocation"].package_content_hash == "a" * 64
        assert reused["invocation"].handoff_state == "accepted"
        assert len(_child_rows(harness)) == 1
        events = harness.commands.store.list_events("run-parent")
        assert any(
            event.event_type == "knowledge_invocation_reused" for event in events
        )

        # A completed+accepted source is required for reuse: failing every
        # completed source invocation forces a fresh child run.
        harness.commands.store.submit(
            lambda uow: (
                uow.repository.update_knowledge_invocation(
                    reused["invocation"].invocation_id,
                    FIXED_NOW_MS + 6,
                    status="failed",
                    error_json=json.dumps({"code": "x"}),
                ),
                uow.repository.update_knowledge_invocation(
                    invocation.invocation_id,
                    FIXED_NOW_MS + 6,
                    status="failed",
                    error_json=json.dumps({"code": "x"}),
                ),
            ),
            force_flush=True,
        ).result(timeout=10)
        third = _invoke(harness, parent_node_id="protocol_freeze")
        assert third["reused"] is False
        assert third["childRunId"]
    finally:
        harness.close()


def test_invocation_rejects_question_mismatch(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        with pytest.raises(KnowledgeSideflowError, match="question"):
            _invoke(harness, question_id="SCI-OTHER")
    finally:
        harness.close()


def test_request_hash_follows_request_content_not_lineage(tmp_path: Path) -> None:
    base = compute_invocation_fingerprints(
        question_id="SCI-096",
        scope={"a": 1},
        search_envelope={"keywords": ["b", "a"]},
        requirements={"r": 1},
        source_policy_version="1",
    )
    # Keyword order is irrelevant (facade canonicalization).
    other = compute_invocation_fingerprints(
        question_id="SCI-096",
        scope={"a": 1},
        search_envelope={"keywords": ["a", "b"]},
        requirements={"r": 1},
        source_policy_version="1",
    )
    assert base == other
    changed = compute_invocation_fingerprints(
        question_id="SCI-096",
        scope={"a": 1},
        search_envelope={"keywords": ["a", "b"]},
        requirements={"r": 2},
        source_policy_version="1",
    )
    assert changed["requestHash"] != base["requestHash"]
    assert changed["searchEnvelopeHash"] == base["searchEnvelopeHash"]


# --------------------------------------------------------------------------
# Child run creation: parent only appends an event
# --------------------------------------------------------------------------


def test_child_run_creation_moves_parent_nothing_but_events(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        store = harness.commands.store
        before = store.get_run("run-parent")
        before_events = store.list_events("run-parent")

        result = _invoke(harness)
        child_run_id = result["childRunId"]
        assert child_run_id == knowledge_sideflow_child_run_id(
            result["invocation"].invocation_id
        )

        after = store.get_run("run-parent")
        # Parent version / status / active node / checkpoint lineage: untouched.
        assert after.run_version == before.run_version
        assert after.status == before.status
        assert after.active_node_id == before.active_node_id
        assert after.last_event_sequence == before.last_event_sequence + 1
        after_events = store.list_events("run-parent")
        assert [event.event_type for event in after_events] == [
            *[event.event_type for event in before_events],
            "knowledge_invocation_created",
        ]
        created_event = after_events[-1]
        payload = json.loads(created_event.payload_json)
        assert payload["invocationId"] == result["invocation"].invocation_id
        assert payload["childRunId"] == child_run_id

        child = store.get_run(child_run_id)
        assert child is not None
        assert child.parent_run_id == "run-parent"
        assert child.workflow_id == KNOWLEDGE_SIDEFLOW_WORKFLOW_ID
        assert child.completion_kind == "knowledge_sideflow"
        assert child.status == "running"
        assert child.active_node_id == "source_finding"
        assert child.thread_id == child_run_id
        identity = register_or_resolve(build_knowledge_sideflow_workflow_definition())
        assert child.workflow_version_id == identity.workflowVersionId
        assert child.structure_hash == identity.structureHash
        snapshot = json.loads(child.input_snapshot_json)
        assert snapshot["invocationId"] == result["invocation"].invocation_id
        assert snapshot["parentRunId"] == "run-parent"

        # First node is durably scheduled: attempt + graph_dispatch pending.
        attempt = store.latest_attempt(child_run_id, "source_finding")
        assert attempt is not None and attempt.status == "starting"
        dispatch_rows = _outbox_rows(harness, child_run_id, "graph_dispatch")
        assert len(dispatch_rows) == 1 and dispatch_rows[0][1] == "pending"

        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status == "child_created"
        assert invocation.knowledge_child_run_id == child_run_id
    finally:
        harness.close()


def test_child_run_creation_is_crash_replay_idempotent(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        first = _invoke(harness)
        events_after_first = len(harness.commands.store.list_events("run-parent"))
        # Re-run ensure for the same invocation record: no duplicate child
        # run, no duplicate parent event.
        child_run_id = harness.commands.store.submit(
            lambda uow: None, force_flush=True
        )
        _ = child_run_id
        from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
            ensure_knowledge_child_run,
        )

        replayed = ensure_knowledge_child_run(
            harness.commands.store,
            _invocation_row(harness, first["invocation"].invocation_id),
            now_provider=lambda: FIXED_NOW_MS + 1000,
        )
        assert replayed == first["childRunId"]
        assert len(_child_rows(harness)) == 1
        assert len(harness.commands.store.list_events("run-parent")) == events_after_first
    finally:
        harness.close()


def test_problem_understanding_success_auto_ensures_sideflow_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The v3 post-commit hook performs only one local, non-blocking ensure."""

    from types import SimpleNamespace

    from core.web.services.team_workflow.research_runtime import (
        workflow_artifact_store,
    )
    from core.web.services.team_workflow.research_runtime.knowledge_sideflow_trigger import (
        KnowledgeSideflowTrigger,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "config.settings.get_config",
        lambda: SimpleNamespace(
            research=SimpleNamespace(
                knowledge_sideflow=SimpleNamespace(mode="on")
            )
        ),
    )
    harness = GraphHarness(tmp_path)
    try:
        v3 = build_challenge_cup_workflow_definition_v3()
        identity = register_or_resolve(v3)
        harness.commands.seed_run(
            "run-parent",
            workflow_id="challenge-cup-research",
            workflow_version_id=identity.workflowVersionId,
            structure_hash=identity.structureHash,
            status="running",
        )
        workflow_artifact_store.put_workflow_artifact(
            "research-team",
            kind="problem_understanding",
            workflow_run_id="run-parent",
            source_collection_run_id="source-1",
            artifact_identity="nr-problem-a1",
            payload={
                "scope": "Evaluate predictive coding for redundant spike reduction.",
                "subquestions": ["Which redundancy metrics change?"],
                "assumptions": ["Comparable encoding budget"],
                "known_unknowns": ["Energy benefit under sparse workloads"],
                "human_gate": {
                    "required": True,
                    "decision": "approved",
                    "rationale": "Scope is testable.",
                },
            },
        )
        trigger = KnowledgeSideflowTrigger(
            store=harness.commands.store,
            command_service=harness.commands.command_service,
            now_provider=lambda: FIXED_NOW_MS + 3000,
        )

        first = trigger.on_node_succeeded(
            run_id="run-parent",
            node_id="problem_understanding",
            node_run_id="nr-problem-a1",
        )
        second = trigger.on_node_succeeded(
            run_id="run-parent",
            node_id="problem_understanding",
            node_run_id="nr-problem-a1",
        )

        assert first["status"] == "submitted"
        assert first["childRunId"]
        assert second["status"] == "replayed"
        assert second["invocationId"] == first["invocationId"]
        assert second["childRunId"] == first["childRunId"]
        assert len(_child_rows(harness)) == 1
    finally:
        harness.close()


def test_graph_success_hook_runs_after_commit_and_never_blocks_mainline(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        observed: list[tuple[str, str, str]] = []

        def hook(*, run_id: str, node_id: str, node_run_id: str) -> None:
            attempt = harness.commands.store.latest_attempt(run_id, node_id)
            assert attempt is not None
            assert attempt.status == "succeeded"
            observed.append((run_id, node_id, node_run_id))
            raise RuntimeError("sideflow trigger unavailable")

        harness.worker._node_success_hook = hook
        harness.enqueue_graph_dispatch("run-parent", "problem_understanding", 1)
        assert harness.worker.run_once() == 1
        pending = harness.latest_adapter_pending("run-parent")
        assert pending is not None
        payload = json.loads(pending.payload_json)
        harness.resume(
            run_id="run-parent",
            node_id="problem_understanding",
            attempt=1,
            action_id=str(payload["actionId"]),
        )
        harness.consume_adapter(pending.action_id)

        assert harness.worker.run_once() == 1
        assert observed == [
            (
                "run-parent",
                "problem_understanding",
                "nr-run-parent-problem_understanding-a1",
            )
        ]
        assert (
            harness.commands.store.latest_attempt(
                "run-parent", "problem_understanding"
            ).status
            == "succeeded"
        )
    finally:
        harness.close()


# --------------------------------------------------------------------------
# Five-node advance + producer transaction
# --------------------------------------------------------------------------


def _walk_child_to_handoff(harness: GraphHarness, child_run_id: str):
    version_id = harness.commands.store.get_run(child_run_id).workflow_version_id
    pending = None
    for _ in range(16):
        harness.worker.run_once()
        pending = harness.latest_adapter_pending(child_run_id)
        if pending is None:
            continue
        payload = json.loads(pending.payload_json)
        node_id = str(payload["nodeId"])
        if node_id == "knowledge_handoff":
            return pending
        harness.resume(
            run_id=child_run_id,
            node_id=node_id,
            attempt=int(payload["attempt"]),
            action_id=str(payload["actionId"]),
        )
        harness.consume_adapter(pending.action_id)
    raise AssertionError("sideflow walk did not reach knowledge_handoff")


def _accept_handoff(harness: GraphHarness, child_run_id: str, pending) -> None:
    payload = json.loads(pending.payload_json)
    # Durable package evidence must exist BEFORE the human accepts, or the
    # producer fail-closes instead of publishing a handoff.
    harness.commands.store.submit(
        lambda uow: uow.repository.insert_artifact_receipt(
            receipt_id="rcpt-kp-1",
            run_id=child_run_id,
            node_run_id=f"nr-{child_run_id}-knowledge_ingestion-a1",
            team_id="research-team",
            artifact_kind="knowledge_package",
            canonical_ref_json=json.dumps({"artifactId": "art-kp-1"}),
            artifact_version="1",
            sha256="b" * 64,
            domain_revision="rev-1",
            materialized=1,
            verified_at_ms=FIXED_NOW_MS + 5,
        ),
        force_flush=True,
    ).result(timeout=10)
    harness.resume(
        run_id=child_run_id,
        node_id="knowledge_handoff",
        attempt=int(payload["attempt"]),
        action_id=str(payload["actionId"]),
    )
    harness.consume_adapter(pending.action_id)
    for _ in range(4):
        harness.worker.run_once()


def test_five_node_advance_publishes_result_in_child_terminal_transaction(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        result = _invoke(harness)
        child_run_id = result["childRunId"]

        pending = _walk_child_to_handoff(harness, child_run_id)
        _accept_handoff(harness, child_run_id, pending)

        store = harness.commands.store
        child = store.get_run(child_run_id)
        assert child.status == "succeeded"
        assert child.completion_kind == "knowledge_sideflow"

        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status == "completed"
        assert invocation.handoff_state == "accepted"
        assert invocation.package_content_hash == "b" * 64

        # Producer outbox row exists, pending delivery, with the typed payload.
        rows = _outbox_rows(harness, child_run_id, "event_publish")
        assert len(rows) == 1 and rows[0][1] == "pending"
        payload = KnowledgeResultAvailablePayload.from_dict(json.loads(rows[0][2]))
        assert payload.producerRunId == child_run_id
        assert payload.consumerRunId == "run-parent"
        assert payload.invocationId == result["invocation"].invocation_id
        assert payload.packageContentHash == "b" * 64
        assert payload.dedupKey == knowledge_result_dedup_key(
            payload.invocationId, "b" * 64
        )
        assert rows[0][3].startswith("event_publish:knowledge_result_available:")

        child_events = store.list_events(child_run_id)
        assert any(
            event.event_type == "knowledge_result_published" for event in child_events
        )
        # Nothing absorbed yet: the parent is only touched by the consumer.
        parent_events = store.list_events("run-parent")
        assert not any(
            event.event_type == "knowledge_result_absorbed"
            for event in parent_events
        )
    finally:
        harness.close()


def test_producer_facts_and_outbox_row_commit_atomically(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        result = _invoke(harness)
        child_run_id = result["childRunId"]
        store = harness.commands.store

        def mutate_with_crash(uow):
            from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
                record_knowledge_sideflow_child_success,
            )

            record_knowledge_sideflow_child_success(
                uow, run_id=child_run_id, now_ms=FIXED_NOW_MS + 9
            )
            raise RuntimeError("simulated crash before commit")

        with pytest.raises(RuntimeError, match="simulated crash"):
            store.submit(mutate_with_crash, force_flush=True).result(timeout=10)

        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status != "completed"
        assert invocation.package_content_hash is None
        assert _outbox_rows(harness, child_run_id, "event_publish") == []

        from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
            record_knowledge_sideflow_child_success,
        )

        # Seed the missing package evidence and replay: everything lands
        # together once the transaction commits.
        store.submit(
            lambda uow: uow.repository.insert_artifact_receipt(
                receipt_id="rcpt-kp-atomic",
                run_id=child_run_id,
                node_run_id=f"nr-{child_run_id}-source_finding-a1",
                team_id="research-team",
                artifact_kind="knowledge_package",
                canonical_ref_json="{}",
                artifact_version="1",
                sha256="c" * 64,
                domain_revision="rev-1",
                materialized=1,
                verified_at_ms=FIXED_NOW_MS + 5,
            ),
            force_flush=True,
        ).result(timeout=10)
        dedup_key = store.submit(
            lambda uow: record_knowledge_sideflow_child_success(
                uow, run_id=child_run_id, now_ms=FIXED_NOW_MS + 10
            ),
            force_flush=True,
        ).result(timeout=10)
        assert dedup_key == knowledge_result_dedup_key(
            result["invocation"].invocation_id, "c" * 64
        )
        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status == "completed"
        assert invocation.package_content_hash == "c" * 64
        assert len(_outbox_rows(harness, child_run_id, "event_publish")) == 1
    finally:
        harness.close()


def test_child_without_package_evidence_never_fakes_handoff(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        result = _invoke(harness)
        child_run_id = result["childRunId"]

        pending = _walk_child_to_handoff(harness, child_run_id)
        payload = json.loads(pending.payload_json)
        # Human accepts WITHOUT any knowledge_package artifact receipt.
        harness.resume(
            run_id=child_run_id,
            node_id="knowledge_handoff",
            attempt=int(payload["attempt"]),
            action_id=str(payload["actionId"]),
        )
        harness.consume_adapter(pending.action_id)
        for _ in range(4):
            harness.worker.run_once()

        invocation = _invocation_row(harness, result["invocation"].invocation_id)
        assert invocation.status == "failed"
        error = json.loads(invocation.error_json or "{}")
        assert error["code"] == "knowledge_package_missing"
        assert _outbox_rows(harness, child_run_id, "event_publish") == []
        assert not any(
            event.event_type == "knowledge_result_absorbed"
            for event in harness.commands.store.list_events("run-parent")
        )
    finally:
        harness.close()


# --------------------------------------------------------------------------
# Consumer validation basics (cross-run event coverage continues in
# test_knowledge_cross_run_events.py)
# --------------------------------------------------------------------------


def test_absorb_validates_payload_lineage_fail_closed(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        result = _invoke(harness)
        child_run_id = result["childRunId"]
        with pytest.raises(KnowledgeSideflowError):
            absorb_knowledge_result(
                harness.commands.store,
                {
                    "eventType": "knowledge_result_available",
                    "producerRunId": child_run_id,
                    "consumerRunId": "run-parent",
                    "invocationId": result["invocation"].invocation_id,
                    "knowledgePackageRef": "x",
                    "packageContentHash": "b" * 64,
                    "sourceManifestRef": "",
                    "handoffDecisionRef": "",
                    "correlationId": "corr",
                },
                now_provider=lambda: FIXED_NOW_MS + 20,
            )
    finally:
        harness.close()


def test_sideflow_package_loader_requires_parent_lineage_and_matching_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        human_acceptance_artifact,
    )
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        build_canonical_ref,
    )
    from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
        canonical_sha256,
    )

    package = {
        "accepted": True,
        "candidateId": "candidate-1",
        "knowledgeBaseId": "kb-1",
        "knowledgeItems": [
            {"knowledgeItemId": "ki-1", "contentHash": "e" * 64}
        ],
    }
    package_hash = canonical_sha256(package)
    invocation = SimpleNamespace(
        invocation_id="kinv-1",
        parent_run_id="run-parent",
        status="completed",
        handoff_state="accepted",
        package_content_hash=package_hash,
        knowledge_package_ref=json.dumps(
            {
                "canonicalRef": build_canonical_ref(
                    kind="knowledge_package",
                    team_id="research-team",
                    authority_run_id="run-child",
                    content_hash=package_hash,
                )
            }
        ),
        knowledge_child_run_id="run-child",
    )
    event = SimpleNamespace(
        event_type="knowledge_result_absorbed",
        payload_json=json.dumps(
            {
                "invocationId": "kinv-1",
                "packageContentHash": package_hash,
            }
        ),
    )

    class Repo:
        def list_knowledge_invocations_for_parent(self, _parent_run_id: str):
            return [invocation]

        def list_knowledge_delivery_event_payloads(self, _parent_run_id: str):
            return [event.payload_json]

    class Store:
        def read(self, callback):
            return callback(Repo())

    monkeypatch.setattr(
        human_acceptance_artifact,
        "load_scoped_artifact_payload",
        lambda *_args, **_kwargs: package,
    )

    loaded = human_acceptance_artifact.load_accepted_knowledge_packages_from_invocations(
        Store(), team_id="research-team", parent_run_id="run-parent"
    )
    assert [item["invocationId"] for item in loaded] == ["kinv-1"]

    invocation.parent_run_id = "run-other"
    assert (
        human_acceptance_artifact.load_accepted_knowledge_packages_from_invocations(
            Store(), team_id="research-team", parent_run_id="run-parent"
        )
        == []
    )
    invocation.parent_run_id = "run-parent"
    invocation.package_content_hash = "f" * 64
    assert (
        human_acceptance_artifact.load_accepted_knowledge_packages_from_invocations(
            Store(), team_id="research-team", parent_run_id="run-parent"
        )
        == []
    )


def test_knowledge_delivery_query_is_not_limited_to_first_500_events(
    tmp_path: Path,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)

        def mutate(uow) -> None:
            base_sequence = uow.repository.latest_event_sequence("run-parent")
            uow.repository.advance_last_sequence(
                "run-parent", 501, FIXED_NOW_MS + 10
            )
            for offset in range(1, 501):
                sequence = base_sequence + offset
                uow.repository.insert_event(
                    build_event_record(
                        sequence,
                        run_id="run-parent",
                        event_id=f"evt-noise-{sequence}",
                        event_type="workflow.noise",
                    )
                )
            uow.repository.insert_event(
                replace(
                    build_event_record(
                        base_sequence + 501,
                        run_id="run-parent",
                        event_id="evt-knowledge-late",
                        event_type="knowledge_result_absorbed",
                    ),
                    payload_json=json.dumps(
                        {
                            "invocationId": "kinv-late",
                            "packageContentHash": "f" * 64,
                        }
                    ),
                )
            )

        harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)
        assert len(harness.commands.store.list_events("run-parent")) == 500
        payloads = harness.commands.store.read(
            lambda repo: repo.list_knowledge_delivery_event_payloads("run-parent")
        )
        assert [json.loads(item)["invocationId"] for item in payloads] == [
            "kinv-late"
        ]
    finally:
        harness.close()


def test_ledger_schema_is_v7() -> None:
    assert SCHEMA_VERSION == 7
