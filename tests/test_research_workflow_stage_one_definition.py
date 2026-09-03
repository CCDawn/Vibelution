"""Stage-one truncated workflow definition (challenge-cup-research@2.2.0-stage-one).

Covers the product decision that the challenge-cup hypothesis chain stops at
``hypothesis_design``: the truncated definition's graph shape, its snapshot
registration, the question-run creation version pin, and the stage-one
completion path (hypothesis_design success + closeout -> run succeeded).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.competition.stage_one_completion_policy import (
    load_stage_one_completion_policy,
    stage_one_policy_snapshot_for_definition,
)
from core.research.workflow import knowledge_sideflow_definition
from core.research.workflow.challenge_cup_graph import (
    build_challenge_cup_graph,
    graph_static_edge_pairs,
)
from core.research.workflow.challenge_cup_runtime import (
    build_formal_graph,
    successor_map_for_definition,
)
from core.research.workflow.definition import (
    build_challenge_cup_workflow_definition,
    definition_structure_hash,
)
from core.research.workflow.definition_registry import (
    definition_snapshot_payload,
    parse_snapshot_payload,
    registered_identities,
    resolve_definition_by_version_id,
    resolve_definition_for_run_record,
    snapshot_dir,
    workflow_version_id_for,
)
from core.research.workflow.models import ActorKind
from core.research.workflow.stage_one_definition import (
    STAGE_ONE_EDGE_IDS,
    STAGE_ONE_NODE_IDS,
    STAGE_ONE_SCHEMA_VERSION,
    build_stage_one_workflow_definition,
    stage_one_creation_definition,
)
from core.web.services.team_workflow.research_runtime import run_creation
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    configure_formal_write_runtime,
    reset_formal_write_runtime_for_tests,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    build_workflow_runtime,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
)

_STAGE_ONE_DEFINITION_ID = f"challenge-cup-research@{STAGE_ONE_SCHEMA_VERSION}"


# ---------------------------------------------------------------------------
# Definition shape
# ---------------------------------------------------------------------------


def test_stage_one_builder_keeps_only_the_seven_stage_one_nodes() -> None:
    definition = build_stage_one_workflow_definition()

    assert definition.workflowId == "challenge-cup-research"
    assert definition.schemaVersion == STAGE_ONE_SCHEMA_VERSION
    assert [node.nodeId for node in definition.nodes] == list(STAGE_ONE_NODE_IDS)
    assert [edge.edgeId for edge in definition.edges] == list(STAGE_ONE_EDGE_IDS)
    assert "e_hyp_proto" not in {edge.edgeId for edge in definition.edges}
    node_ids = set(STAGE_ONE_NODE_IDS)
    assert all(
        edge.fromNodeId in node_ids and edge.toNodeId in node_ids
        for edge in definition.edges
    )
    assert not any(node_id.startswith("protocol_") for node_id in node_ids)
    assert "smoke_gate" not in node_ids
    assert not node_ids & {
        "controlled_run",
        "result_evaluation",
        "iteration_decision",
        "version_governance",
        "candidate_promotion",
        "result_package",
    }


def test_stage_one_stages_drop_the_empty_execution_iteration() -> None:
    definition = build_stage_one_workflow_definition()

    assert [(stage.stageId.value, stage.nodeIds) for stage in definition.stages] == [
        (
            "knowledge_collection",
            (
                "problem_understanding",
                "source_finding",
                "source_extraction",
                "evidence_relations",
                "knowledge_ingestion",
                "knowledge_handoff",
            ),
        ),
        ("experiment_design", ("hypothesis_design",)),
    ]


def test_stage_one_hypothesis_design_is_the_only_terminal_node() -> None:
    definition = build_stage_one_workflow_definition()

    sources = {edge.fromNodeId for edge in definition.edges}
    terminals = [
        node.nodeId for node in definition.nodes if node.nodeId not in sources
    ]
    assert terminals == ["hypothesis_design"]
    assert successor_map_for_definition(definition)["hypothesis_design"] == ()
    assert successor_map_for_definition(definition)["knowledge_handoff"] == (
        "hypothesis_design",
    )
    # Both graph compilers accept the reduced definition and END at the
    # hypothesis closure node.
    build_challenge_cup_graph(definition)
    build_formal_graph(definition)
    assert graph_static_edge_pairs(definition) == tuple(
        (edge.fromNodeId, edge.toNodeId) for edge in definition.edges
    )


def test_stage_one_builder_is_pure_and_version_distinct() -> None:
    main_before = build_challenge_cup_workflow_definition()
    v3_before = knowledge_sideflow_definition.build_challenge_cup_workflow_definition_v3()

    definition = build_stage_one_workflow_definition()

    # The frozen 2.1.0/3.0.0 builders are untouched.
    assert build_challenge_cup_workflow_definition() == main_before
    assert (
        knowledge_sideflow_definition.build_challenge_cup_workflow_definition_v3()
        == v3_before
    )
    assert definition.structureHash == definition_structure_hash(definition)
    assert definition.schemaVersion not in {
        main_before.schemaVersion,
        v3_before.schemaVersion,
    }
    assert workflow_version_id_for(definition.structureHash) not in {
        workflow_version_id_for(main_before.structureHash),
        workflow_version_id_for(v3_before.structureHash),
    }
    # The entry node is unchanged, so question runs still start at
    # problem_understanding.
    first_agent = next(
        node.nodeId
        for node in definition.nodes
        if node.actorKind is ActorKind.AGENT
    )
    assert first_agent == "problem_understanding"


# ---------------------------------------------------------------------------
# Snapshot registration and resolution
# ---------------------------------------------------------------------------


def test_stage_one_snapshot_bootstraps_and_resolves() -> None:
    definition = build_stage_one_workflow_definition()
    payload = json.loads(
        (snapshot_dir() / f"challenge-cup-research@{STAGE_ONE_SCHEMA_VERSION}.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["contentHash"] == definition.structureHash
    assert payload["workflowVersionId"] == workflow_version_id_for(
        definition.structureHash
    )
    assert parse_snapshot_payload(payload) == definition

    identities = registered_identities("challenge-cup-research")
    versions = {
        resolve_definition_by_version_id(identity.workflowVersionId).schemaVersion
        for identity in identities
    }
    # The truncated stage-one version is registered next to the historical
    # 2.1.0 and 3.0.0 definitions (existing runs keep resolving).
    assert {"2.1.0", "3.0.0", STAGE_ONE_SCHEMA_VERSION} <= versions

    record = {
        "runId": "run-stage-one-definition",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": workflow_version_id_for(definition.structureHash),
        "structureHash": definition.structureHash,
        "completedNodeIds": ["knowledge_handoff"],
        "runtimeCurrentNodeIds": ["hypothesis_design"],
    }
    resolved = resolve_definition_for_run_record(record)
    assert resolved.schemaVersion == STAGE_ONE_SCHEMA_VERSION
    assert [node.nodeId for node in resolved.nodes] == list(STAGE_ONE_NODE_IDS)
    # protocol nodes are absent, so a protocol node reference fails closed.
    with pytest.raises(Exception) as excinfo:
        resolve_definition_for_run_record(
            {**record, "runtimeCurrentNodeIds": ["protocol_design"]}
        )
    assert "missingNodes" in str(excinfo.value)


def test_stage_one_creation_definition_registers_identity() -> None:
    definition, identity = stage_one_creation_definition()

    assert definition.schemaVersion == STAGE_ONE_SCHEMA_VERSION
    assert identity.workflowVersionId == workflow_version_id_for(
        definition.structureHash
    )
    assert identity in registered_identities("challenge-cup-research")
    assert definition_snapshot_payload(definition)["workflowVersionId"] == (
        identity.workflowVersionId
    )


# ---------------------------------------------------------------------------
# Question-run creation pins the truncated definition
# ---------------------------------------------------------------------------


def _baseline_run_input() -> dict[str, object]:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "research_workflow_v21_baseline_case.json"
    )
    return json.loads(fixture.read_text(encoding="utf-8"))["runInput"]


@pytest.fixture()
def ledger_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    reset_formal_write_runtime_for_tests()
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "checkpoints.sqlite",
    )
    configure_formal_write_runtime(
        store=runtime.store,
        command_service=runtime.command_service,
    )
    try:
        yield runtime
    finally:
        runtime.close()
        reset_formal_write_runtime_for_tests()


def test_create_run_pins_stage_one_definition_for_question_runs(
    ledger_runtime,
) -> None:
    definition = build_stage_one_workflow_definition()

    created = run_creation.create_run(
        "challenge-cup-research",
        run_input=_baseline_run_input(),
        idempotency_key="stage-one-create",
        workflow_definition=definition,
    )

    assert created["workflowVersionId"] == workflow_version_id_for(
        definition.structureHash
    )
    assert created["structureHash"] == definition.structureHash
    # Registry query evidence: the new run resolves to the truncated
    # stage-one definition through its pinned version identity.
    record = ledger_runtime.store.get_run(str(created["runId"]))
    assert record is not None
    resolved = resolve_definition_for_run_record(
        {
            "runId": record.run_id,
            "workflowId": record.workflow_id,
            "workflowVersionId": record.workflow_version_id,
            "structureHash": record.structure_hash,
            "completedNodeIds": [],
            "runtimeCurrentNodeIds": [record.active_node_id or ""],
        }
    )
    assert resolved.schemaVersion == STAGE_ONE_SCHEMA_VERSION


def test_default_create_run_keeps_rollout_default(
    ledger_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import knowledge_rollout

    monkeypatch.setattr(
        knowledge_rollout, "knowledge_sideflow_mode", lambda: "off"
    )
    main = build_challenge_cup_workflow_definition()

    created = run_creation.create_run(
        "challenge-cup-research",
        run_input=_baseline_run_input(),
        idempotency_key="rollout-default-create",
    )

    assert created["workflowVersionId"] == workflow_version_id_for(
        main.structureHash
    )
    assert created["workflowVersionId"] == "wv-9a4b74e7f21a"


def test_stage_one_policy_is_retargeted_for_the_truncated_definition() -> None:
    definition = build_stage_one_workflow_definition()
    tracked = load_stage_one_completion_policy().to_dict()
    run_input = {
        **_baseline_run_input(),
        "questionId": "SCI-091",
        "stageOneCompletionPolicy": tracked,
    }

    retargeted_input = run_creation._retarget_stage_one_policy_binding(
        run_input, definition
    )

    policy = retargeted_input["stageOneCompletionPolicy"]
    # The embedded policy names the definition that actually drives the run,
    # so the run-input contract and closeout identity checks match.
    assert policy["workflowDefinitionId"] == _STAGE_ONE_DEFINITION_ID
    assert policy["workflowDefinitionId"] != tracked["workflowDefinitionId"]
    assert policy["closureNodeId"] == tracked["closureNodeId"]
    assert policy["policySha256"] != tracked["policySha256"]
    assert stage_one_policy_snapshot_for_definition(
        policy,
        workflow_definition_id=_STAGE_ONE_DEFINITION_ID,
    ) == policy
    # The tracked-policy authorization scope (real batch scope) still binds:
    # the authorized copy is normalized with the same re-targeting.
    run_creation._require_stage_one_authorization_binding(
        retargeted_input,
        {"batchScope": {"stageOneCompletionPolicy": tracked}},
        workflow_definition_id=_STAGE_ONE_DEFINITION_ID,
    )
    with pytest.raises(ResearchWorkflowError) as excinfo:
        run_creation._require_stage_one_authorization_binding(
            retargeted_input,
            None,
            workflow_definition_id=_STAGE_ONE_DEFINITION_ID,
        )
    assert excinfo.value.code == "catalog_run_authorization_required"
    # A run pinned to 2.1.0 keeps the exact tracked identity (no rewrite).
    assert run_creation._retarget_stage_one_policy_binding(
        run_input, build_challenge_cup_workflow_definition()
    ) == run_input


def test_stage_one_policy_drift_fails_closed() -> None:
    definition = build_stage_one_workflow_definition()
    tracked = load_stage_one_completion_policy().to_dict()
    drifted = {
        **tracked,
        "requiredArtifactKinds": tracked["requiredArtifactKinds"][:-1],
    }
    run_input = {
        **_baseline_run_input(),
        "questionId": "SCI-091",
        "stageOneCompletionPolicy": drifted,
    }

    with pytest.raises(ResearchWorkflowError) as excinfo:
        run_creation._retarget_stage_one_policy_binding(run_input, definition)

    assert excinfo.value.code == "invalid_run_input"


# ---------------------------------------------------------------------------
# Completion path: hypothesis_design success closes the truncated run
# ---------------------------------------------------------------------------


def _stage_one_truncated_run(run_id: str = "run-stage-one-truncated"):
    import dataclasses

    from tests._support.workflow_ledger_helpers import build_run_record

    definition = build_stage_one_workflow_definition()
    tracked = load_stage_one_completion_policy().to_dict()
    policy = stage_one_policy_snapshot_for_definition(
        tracked,
        workflow_definition_id=f"{definition.workflowId}@{definition.schemaVersion}",
    )
    return dataclasses.replace(
        build_run_record(
            run_id=run_id,
            team_id="challenge-stage-one-team",
            workflow_id=definition.workflowId,
            workflow_version_id=workflow_version_id_for(definition.structureHash),
            status="running",
            last_event_sequence=1,
        ),
        project_id="challenge-stage-one-project",
        question_id="SCI-091",
        input_snapshot_json=json.dumps(
            {
                "teamId": "challenge-stage-one-team",
                "projectId": "challenge-stage-one-project",
                "questionId": "SCI-091",
                "stageOneCompletionPolicy": policy,
            }
        ),
        structure_hash=definition.structureHash,
        active_node_id="hypothesis_design",
    )


def test_closeout_identity_accepts_retargeted_policy_on_truncated_run() -> None:
    from core.web.services.team_workflow.research_runtime.node_execution_support import (
        NodeExecutionError,
    )
    from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
        _stage_one_policy,
    )

    record = {
        "runId": "run-stage-one-truncated",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": workflow_version_id_for(
            build_stage_one_workflow_definition().structureHash
        ),
        "structureHash": build_stage_one_workflow_definition().structureHash,
        "questionId": "SCI-091",
        "inputSnapshot": {
            "stageOneCompletionPolicy": stage_one_policy_snapshot_for_definition(
                load_stage_one_completion_policy().to_dict(),
                workflow_definition_id=_STAGE_ONE_DEFINITION_ID,
            )
        },
    }

    policy = _stage_one_policy(record)
    assert policy is not None
    assert policy.closureNodeId == "hypothesis_design"

    # The verbatim tracked 2.1.0 policy does NOT authorize a run pinned to
    # the truncated definition (identity mismatch stays fail-closed).
    mismatched = dict(record)
    mismatched["inputSnapshot"] = {
        "stageOneCompletionPolicy": load_stage_one_completion_policy().to_dict()
    }
    with pytest.raises(NodeExecutionError) as excinfo:
        _stage_one_policy(mismatched)
    assert excinfo.value.code == "stage_one_policy_mismatch"


def test_terminal_close_applies_and_facts_for_truncated_run() -> None:
    from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
        _run_terminal_close_applies,
    )
    from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
        stage_one_terminal_facts,
    )

    run = _stage_one_truncated_run()
    marker = {"stage_one_completion_state": "STAGE1_G1_ACCEPTED"}

    # hypothesis_design is the truncated definition's terminal node: with the
    # accepted stage-one marker the dispatch closes the run as succeeded.
    assert _run_terminal_close_applies(run, "hypothesis_design", marker) is True
    assert stage_one_terminal_facts(
        run, node_id="hypothesis_design", state_update=marker
    ) == ("stage_one_g1_accepted", "STAGE1_G1_ACCEPTED")
    # Without the server-authorized marker the terminal close does not fire.
    assert _run_terminal_close_applies(run, "hypothesis_design", {}) is False
    assert stage_one_terminal_facts(
        run, node_id="hypothesis_design", state_update={}
    ) is None


def test_hypothesis_design_success_succeeds_truncated_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.research.workflow.challenge_cup_runtime import (
        GraphDispatch,
        GraphDispatchResult,
    )
    from core.research.workflow.contracts import PendingAction
    from core.research.workflow.ledger import outbox as outbox_api
    from core.research.workflow.models import ActorKind
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        AgentActionAdapter,
    )
    from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
        GraphDispatchWorker,
    )
    from tests._support.adapter_fakes import FakeDomainPorts
    from tests._support.command_helpers import CommandHarness
    from tests._support.workflow_ledger_helpers import (
        FIXED_NOW_MS,
        build_attempt_record,
        build_command_record,
        build_event_record,
    )
    from tests.test_research_workflow_stage_one_closeout import _payloads

    run_id = "run-stage-one-truncated"
    action = PendingAction(
        action_id="act-stage-one-truncated",
        run_id=run_id,
        node_run_id=f"nr-{run_id}-hypothesis_design-a1",
        node_id="hypothesis_design",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="policy-stage-one",
    )
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        run = _stage_one_truncated_run(run_id)

        def mutate(uow) -> None:
            from core.research.workflow.ledger import OutboxRecord

            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id=f"evt-created-{run.run_id}",
                )
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-stage-one-truncated",
                    run_id=run.run_id,
                    team_id=run.team_id,
                    node_id="hypothesis_design",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id=action.node_run_id,
                    run_id=run.run_id,
                    node_id="hypothesis_design",
                    status="dispatching",
                    command_id="cmd-stage-one-truncated",
                )
            )
            uow.repository.insert_outbox(
                OutboxRecord(
                    action_id="adapter-stage-one-truncated",
                    run_id=run.run_id,
                    command_id="cmd-stage-one-truncated",
                    node_run_id=action.node_run_id,
                    action_kind="adapter_dispatch",
                    idempotency_key="adapter:stage-one-truncated",
                    payload_json=json.dumps(action.to_dict()),
                    status="pending",
                    attempt_count=0,
                    available_at_ms=FIXED_NOW_MS,
                    lease_owner=None,
                    lease_expires_at_ms=None,
                    last_problem_json=None,
                    created_at_ms=FIXED_NOW_MS,
                    updated_at_ms=FIXED_NOW_MS,
                )
            )
            policy = load_stage_one_completion_policy()
            for index, kind in enumerate(policy.requiredArtifactKinds):
                uow.repository.insert_artifact_receipt(
                    receipt_id=f"seed-stage-one-truncated-{index}",
                    run_id=run_id,
                    node_run_id=action.node_run_id,
                    team_id="challenge-stage-one-team",
                    artifact_kind=kind,
                    canonical_ref_json=json.dumps(
                        {
                            "canonicalRef": (
                                f"{kind}://challenge-stage-one-team/{run_id}/"
                                + "a" * 64
                            )
                        }
                    ),
                    artifact_version="1.0.0",
                    sha256="a" * 64,
                    domain_revision="revision-1",
                    materialized=1,
                    verified_at_ms=FIXED_NOW_MS,
                )

        harness.store.submit(mutate, force_flush=True).result(timeout=10)

        payloads = _payloads(run_id)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.stage_one_closeout._load_ledger_artifact_payload",
            lambda receipt: payloads[
                f"{receipt['artifactType']}:{receipt['artifactType']}-artifact"
            ],
        )
        approved_handoff = {
            "status": "idempotent",
            "workflowRunId": run_id,
            "questionId": "SCI-091",
            "recordId": f"SCI-091:{run_id}",
            "reviewStatus": "approved",
            "outputSha256": "e" * 64,
            "sourceResultPackageHash": "a" * 64,
            "resultPackage": {"canonicalHash": "b" * 64},
            "officialModelCall": True,
            "receiptStatus": "passed",
            "humanGates": {"allApproved": True, "approvedCount": 4},
        }
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.program_candidate_handoff.handoff_result_package_to_challenge_program",
            lambda **_kwargs: approved_handoff,
        )

        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            # The truncated definition gives hypothesis_design NO successor.
            successor_fn=lambda _node: (),
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )
        worker.run_once()

        # No phase-two handoff exists, and the accepted closeout rides the
        # graph resume with the terminal marker.
        handoff = harness.store.read(
            lambda repo: repo.get_handoff_by_from_node(run_id, action.node_run_id)
        )
        assert handoff is None
        outboxes = harness.store.list_pending_outbox(run_id)
        resume = next(
            item for item in outboxes if item.action_kind == "graph_dispatch"
        )
        resume_payload = json.loads(resume.payload_json)
        assert resume_payload["stateUpdate"]["stage_one_completion_state"] == (
            "STAGE1_G1_ACCEPTED"
        )

        leased = outbox_api.lease_ready_actions(
            harness.store,
            owner="graph-stage-one-truncated",
            now_ms=FIXED_NOW_MS + 2_000,
            lease_ms=5_000,
            action_kinds=("graph_dispatch",),
        )
        assert len(leased) == 1
        dispatch = GraphDispatch.from_payload(json.loads(leased[0].payload_json))
        GraphDispatchWorker(
            store=harness.store,
            coordinator=object(),  # _commit_dispatch does not call the coordinator.
            owner_id="graph-stage-one-truncated",
            now_provider=lambda: FIXED_NOW_MS + 2_100,
        )._commit_dispatch(
            leased[0],
            dispatch,
            GraphDispatchResult(
                dispatch_kind="resume_action",
                pending_action=None,
                next_node_ids=(),
                checkpoint_id="checkpoint-stage-one-truncated",
                state={"stage_one_completion_state": "STAGE1_G1_ACCEPTED"},
                completed=True,
            ),
        )

        closed_run = harness.store.get_run(run_id)
        assert closed_run is not None
        assert closed_run.status == "succeeded"
        assert closed_run.completion_kind == "stage_one_g1_accepted"
        assert closed_run.terminal_reason == "STAGE1_G1_ACCEPTED"
        assert harness.store.latest_attempt(run_id, "protocol_design") is None
    finally:
        harness.close()
