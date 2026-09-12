"""Canonical artifacts and real Ledger delivery; no external model or GPU."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.research.operator_optimization.plan import OptimizationPlan
from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.ledger import KnowledgeInvocationRecord
from core.web.services.team_workflow.operator_optimization import (
    knowledge,
    planning,
)
from core.web.services.team_workflow.operator_optimization.store import (
    CampaignConflict,
    read_campaign,
)
from core.web.services.team_workflow.research_runtime import (
    human_acceptance_artifact as acceptance,
)
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    build_canonical_ref,
)
from tests import test_operator_optimization_budget as budget_fixtures
from tests import test_operator_optimization_discussion as discussion_fixtures
from tests import test_operator_optimization_rounds as round_fixtures
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
    open_ledger_store,
)
from tests.test_operator_optimization_discussion import _save_selected

activity = budget_fixtures.activity
baseline_ready = round_fixtures.ready
discussion_case = discussion_fixtures.discussion_case


@pytest.fixture
def ready(activity, baseline_ready):
    campaign, run, calls = baseline_ready
    protocol = {
        "protocolId": "tuning",
        "split": "tuning",
        "cases": [
            {
                "caseId": "small",
                "rows": 32,
                "columns": 128,
                "dtype": "float32",
                "seed": 1,
            }
        ],
    }
    _, ref = knowledge._write_readback(
        activity[0],
        run.run_id,
        kind="operator_measurement_protocol",
        identity="full-protocol",
        payload=protocol,
    )
    frozen = json.loads(run.input_snapshot_json)
    frozen["evaluationContract"].update(
        protocolArtifactHash=ref.sha256, protocolHash=sha256_hex(protocol)
    )
    run.input_snapshot_json = json.dumps(frozen)
    return campaign, run, calls


@pytest.fixture
def handoff(activity, discussion_case, monkeypatch, tmp_path):
    from core.research.workflow.definition_registry import definition_identity
    from core.research.workflow.operator_optimization_definition import (
        build_operator_definition,
    )

    _, run, payload = discussion_case
    store = open_ledger_store(tmp_path / "handoff.sqlite")
    definition = definition_identity(build_operator_definition())
    record = replace(
        build_run_record(
            run_id=run.run_id,
            team_id=activity[0],
            workflow_id="operator-optimization",
            status="running",
        ),
        project_id=activity[1],
        question_id="OPERATOR-SOFTMAX",
        input_snapshot_json=run.input_snapshot_json,
        workflow_version_id=definition.workflowVersionId,
        structure_hash=definition.structureHash,
        active_node_id="optimization_knowledge",
    )
    store.submit(lambda u: u.repository.insert_run(record), force_flush=True).result()
    monkeypatch.setattr(knowledge, "get_write_store", lambda: store)
    yield run, payload, store
    store.close()


def selected(activity, handoff, *, gaps=False):
    run, payload, store = handoff
    payload["evidenceGaps"] = ["Check occupancy guidance"] if gaps else []
    _save_selected(activity[0], run.run_id, payload, provenance={})
    return run, payload, store


def plan_for(activity, run_id):
    inputs = planning.planning_input(activity[0], run_id)
    return OptimizationPlan(
        planId="plan-one",
        **{
            key: inputs[key]
            for key in (
                "optimizationCampaignId",
                "roundId",
                "hypothesisRef",
                "knowledgeRef",
                "protocolRef",
                "baselineCandidateRef",
                "parentCandidateRef",
            )
        },
        candidateRef=inputs["parentCandidateRef"],
        objective="Verify repeatability of the fixed candidate",
        evaluation="Paired frozen protocol",
        prediction="No regression",
        counterevidence="Incorrect output or repeatable slowdown",
        evidenceAssessment="Existing paired observations; no new external claims",
        trialCount=1,
        trialTimeoutSeconds=30,
    )


def test_no_gaps_freezes_real_observations_and_plan_without_calls(activity, handoff):
    run, _, _ = selected(activity, handoff)
    request_ref, request = knowledge.prepare_knowledge_request(activity[0], run.run_id)
    assert knowledge.prepare_knowledge_request(activity[0], run.run_id) == (
        request_ref,
        request,
    )
    ref = knowledge.publish_knowledge_snapshot(activity[0], run.run_id)
    assert knowledge.publish_knowledge_snapshot(activity[0], run.run_id) == ref
    assert (
        knowledge.load_knowledge_snapshot(activity[0], run.run_id).mode
        == "existing_observations"
    )
    plan = plan_for(activity, run.run_id)
    plan_ref = planning.freeze_optimization_plan(activity[0], run.run_id, plan)
    assert planning.freeze_optimization_plan(activity[0], run.run_id, plan) == plan_ref
    assert read_campaign(*activity).rounds[0].planRef == plan_ref


def test_gaps_do_not_turn_into_success_or_start_an_unbudgeted_child(activity, handoff):
    run, _, store = selected(activity, handoff, gaps=True)
    with pytest.raises(CampaignConflict, match="paid collection is not connected"):
        knowledge.publish_knowledge_snapshot(activity[0], run.run_id)
    assert read_campaign(*activity).rounds[0].knowledgeRef is None
    assert (
        store.read(lambda repo: repo.list_knowledge_invocations_for_parent(run.run_id))
        == []
    )


@pytest.mark.parametrize(
    "change",
    [
        "hypothesisRef",
        "knowledgeRef",
        "protocolRef",
        "trialCount",
        "trialTimeoutSeconds",
    ],
)
def test_plan_rejects_changed_sources_and_excess_budget(activity, handoff, change):
    run, _, _ = selected(activity, handoff)
    knowledge.publish_knowledge_snapshot(activity[0], run.run_id)
    payload = plan_for(activity, run.run_id).model_dump(mode="json")
    if change.endswith("Ref"):
        payload[change]["sha256"] = "e" * 64
    else:
        payload[change] = 12 if change == "trialCount" else 61
    with pytest.raises(CampaignConflict):
        planning.freeze_optimization_plan(
            activity[0], run.run_id, OptimizationPlan.model_validate(payload)
        )
    assert read_campaign(*activity).rounds[0].planRef is None


@pytest.mark.parametrize(
    "invalid", [None, "not_delivered", "wrong_request", "fresh_child", "revoked"]
)
def test_accepted_reuse_requires_matching_request_delivery_and_live_authority(
    activity, handoff, monkeypatch, invalid
):
    run, _, store = selected(activity, handoff, gaps=True)
    _, request = knowledge.prepare_knowledge_request(activity[0], run.run_id)
    fingerprints = knowledge.compute_invocation_fingerprints(
        **knowledge.knowledge_invocation_arguments(
            request, question_id="OPERATOR-SOFTMAX"
        )
    )
    package = {
        "accepted": True,
        "knowledgeItems": [{"knowledgeItemId": "item-one", "contentHash": "f" * 64}],
    }
    digest = sha256_hex(package)
    canonical = build_canonical_ref(
        kind="knowledge_package",
        team_id=activity[0],
        authority_run_id="source-run",
        content_hash=digest,
    )
    invocation = KnowledgeInvocationRecord(
        invocation_id="inv-one",
        parent_run_id=run.run_id,
        parent_node_id="optimization_knowledge",
        parent_node_run_id="knowledge-attempt",
        parent_attempt=1,
        question_id="OPERATOR-SOFTMAX",
        scope_hash=fingerprints["scopeHash"],
        request_hash="0" * 64
        if invalid == "wrong_request"
        else fingerprints["requestHash"],
        search_envelope_hash=fingerprints["searchEnvelopeHash"],
        requirements_hash=fingerprints["requirementsHash"],
        source_policy_version=request.sourcePolicyVersion,
        knowledge_child_run_id="child" if invalid == "fresh_child" else None,
        status="completed",
        knowledge_package_ref=canonical,
        package_content_hash=digest,
        handoff_state="accepted",
        error_json=None,
        created_at_ms=1,
        updated_at_ms=1,
    )

    def seed(u):
        u.repository.insert_knowledge_invocation(invocation)
        if invalid != "not_delivered":
            u.repository.insert_event(
                replace(
                    build_event_record(1, run_id=run.run_id),
                    event_type="knowledge_invocation_reused",
                    payload_json=json.dumps(
                        {
                            "invocationId": invocation.invocation_id,
                            "packageContentHash": digest,
                        }
                    ),
                )
            )

    store.submit(seed, force_flush=True).result()
    monkeypatch.setattr(
        acceptance, "load_scoped_artifact_payload", lambda *a, **k: package
    )
    if invalid is None or invalid == "revoked":
        knowledge.publish_knowledge_snapshot(activity[0], run.run_id)
        snapshot = knowledge.load_knowledge_snapshot(activity[0], run.run_id)
        assert snapshot.packages[0].invocationId == "inv-one"
        assert (
            snapshot.evidenceGaps == request.evidenceGaps
        )  # acceptance does not prove scientific adequacy
        if invalid == "revoked":
            monkeypatch.setattr(
                acceptance, "load_scoped_artifact_payload", lambda *a, **k: None
            )
            with pytest.raises(CampaignConflict, match="no longer readable"):
                planning.planning_input(activity[0], run.run_id)
    else:
        with pytest.raises(CampaignConflict, match="matching accepted package"):
            knowledge.publish_knowledge_snapshot(activity[0], run.run_id)


def test_request_identity_changes_for_gap_or_root_changes(activity, handoff):
    run, _, _ = selected(activity, handoff, gaps=True)
    request = knowledge.build_knowledge_request(activity[0], run.run_id)

    def fingerprint(value):
        return knowledge.compute_invocation_fingerprints(
            **knowledge.knowledge_invocation_arguments(
                value, question_id="OPERATOR-SOFTMAX"
            )
        )["requestHash"]

    assert fingerprint(request) != fingerprint(
        request.model_copy(update={"evidenceGaps": ("Different claim",)})
    )
    assert fingerprint(request) != fingerprint(
        request.model_copy(update={"managedSourceRootIds": ("other-root",)})
    )


@pytest.mark.parametrize("gaps", [False, True])
def test_system_executor_and_readiness_only_enable_verified_reuse(
    activity, handoff, gaps
):
    from core.research.workflow.operator_optimization_definition import (
        build_operator_definition,
    )
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        read_domain_artifact,
    )
    from core.web.services.team_workflow.research_runtime.readiness.operator_optimization import (
        evaluate_operator_node,
    )
    from core.web.services.team_workflow.research_runtime.real_domain_ports import (
        _execute_real_system_action,
    )
    from core.web.services.team_workflow.research_runtime.real_readiness_context import (
        RealDomainReadinessContext,
    )

    run, _, store = selected(activity, handoff, gaps=gaps)
    nodes = build_operator_definition().nodes
    context = RealDomainReadinessContext(store)
    verdict = evaluate_operator_node(store.get_run(run.run_id), nodes[1], None, context)
    assert verdict.ready is not gaps
    if gaps:
        assert "operator_knowledge_collection_budget_not_implemented" in {
            b.code for b in verdict.blockers
        }
    else:
        refs, meta = _execute_real_system_action(
            SimpleNamespace(
                node_id="optimization_knowledge",
                action_id="system-knowledge",
                run_id=run.run_id,
            ),
            input_snapshot=json.loads(run.input_snapshot_json),
            required_kinds=("optimization_knowledge",),
        )
        assert meta["runnerId"] == "operator_knowledge_reuse_v1"
        assert len(refs) == 1
        assert (
            read_domain_artifact(refs[0]["canonicalRef"]).content_hash
            == refs[0]["sha256"]
        )
        # Readiness never exposes an unbudgeted generic planning task.
        planning_verdict = evaluate_operator_node(
            store.get_run(run.run_id), nodes[2], None, context
        )
        assert "operator_plan_task_not_implemented" in {
            b.code for b in planning_verdict.blockers
        }


def test_discovers_existing_package_and_atomically_binds_current_round_without_child(
    activity, handoff, monkeypatch
):
    from core.web.services.team_workflow.research_runtime import (
        knowledge_sideflow_service as sideflow,
    )

    run, _, store = selected(activity, handoff, gaps=True)
    request = knowledge.build_knowledge_request(activity[0], run.run_id)
    old_request = request.model_copy(
        update={"runId": "previous-run", "roundId": "previous-round"}
    )
    args = knowledge.knowledge_invocation_arguments(
        old_request, question_id="OPERATOR-SOFTMAX"
    )
    fingerprints = sideflow.compute_invocation_fingerprints(**args)
    current = sideflow.compute_invocation_fingerprints(
        **knowledge.knowledge_invocation_arguments(
            request, question_id="OPERATOR-SOFTMAX"
        )
    )
    assert current["scopeHash"] == fingerprints["scopeHash"]
    assert current["requirementsHash"] == fingerprints["requirementsHash"]
    assert current["requestHash"] != fingerprints["requestHash"]
    package = {
        "accepted": True,
        "knowledgeItems": [
            {"knowledgeItemId": "prior-knowledge", "contentHash": "a" * 64}
        ],
    }
    digest = sha256_hex(package)
    canonical = build_canonical_ref(
        kind="knowledge_package",
        team_id=activity[0],
        authority_run_id="source-child",
        content_hash=digest,
    )
    source = KnowledgeInvocationRecord(
        invocation_id="source-invocation",
        parent_run_id="previous-run",
        parent_node_id="optimization_knowledge",
        parent_node_run_id="previous-node",
        parent_attempt=1,
        question_id="OPERATOR-SOFTMAX",
        scope_hash=fingerprints["scopeHash"],
        request_hash=fingerprints["requestHash"],
        search_envelope_hash=fingerprints["searchEnvelopeHash"],
        requirements_hash=fingerprints["requirementsHash"],
        source_policy_version=request.sourcePolicyVersion,
        knowledge_child_run_id="source-child",
        status="completed",
        knowledge_package_ref=canonical,
        package_content_hash=digest,
        handoff_state="accepted",
        error_json=None,
        created_at_ms=1,
        updated_at_ms=1,
    )

    def seed(u):
        u.repository.insert_run(
            replace(
                build_run_record(run_id="previous-run", team_id=activity[0]),
                project_id=activity[1],
            )
        )
        u.repository.insert_knowledge_invocation(source)
        u.repository.insert_event(
            replace(
                build_event_record(1, run_id="previous-run"),
                event_type="knowledge_result_absorbed",
                payload_json=json.dumps(
                    {"invocationId": source.invocation_id, "packageContentHash": digest}
                ),
            )
        )
        u.repository.insert_command(
            build_command_record(run_id=run.run_id, command_id="knowledge-command")
        )
        u.repository.insert_attempt(
            build_attempt_record(
                "actual-knowledge-attempt",
                run_id=run.run_id,
                node_id="optimization_knowledge",
                status="running",
                command_id="knowledge-command",
            )
        )

    store.submit(seed, force_flush=True).result()
    monkeypatch.setattr(
        acceptance, "load_scoped_artifact_payload", lambda *a, **k: package
    )
    monkeypatch.setattr(
        sideflow,
        "ensure_knowledge_child_run",
        lambda *a, **k: pytest.fail("reuse must not start a child"),
    )
    assert knowledge.knowledge_reuse_available(activity[0], run.run_id, request)
    ref = knowledge.publish_knowledge_snapshot(activity[0], run.run_id)
    assert knowledge.publish_knowledge_snapshot(activity[0], run.run_id) == ref
    invocations = store.read(
        lambda repo: repo.list_knowledge_invocations_for_parent(run.run_id)
    )
    assert len(invocations) == 1
    assert invocations[0].knowledge_child_run_id is None
    assert invocations[0].parent_node_run_id == "actual-knowledge-attempt"
    assert invocations[0].request_hash == current["requestHash"]
    plan = plan_for(activity, run.run_id)
    with pytest.raises(CampaignConflict, match="preserve every knowledge gap"):
        planning.freeze_optimization_plan(activity[0], run.run_id, plan)
    checked = OptimizationPlan.model_validate(
        {
            **plan.model_dump(mode="json"),
            "gapChecks": [
                {
                    "gap": request.evidenceGaps[0],
                    "experimentCheck": "Compare occupancy and paired latency under the frozen workload",
                }
            ],
        }
    )
    assert (
        planning.freeze_optimization_plan(activity[0], run.run_id, checked).kind
        == "optimization_plan"
    )


def test_reuse_only_miss_leaves_no_pending_invocation_or_child(
    activity, handoff, monkeypatch
):
    from core.web.services.team_workflow.research_runtime import (
        knowledge_sideflow_service as sideflow,
    )

    run, _, store = selected(activity, handoff, gaps=True)
    request = knowledge.build_knowledge_request(activity[0], run.run_id)
    monkeypatch.setattr(
        sideflow,
        "ensure_knowledge_child_run",
        lambda *a, **k: pytest.fail("unexpected paid child"),
    )
    with pytest.raises(sideflow.KnowledgeSideflowError, match="No reusable knowledge"):
        sideflow.ensure_knowledge_invocation(
            store,
            parent_run_id=run.run_id,
            parent_node_id="optimization_knowledge",
            reuse_only=True,
            **knowledge.knowledge_invocation_arguments(
                request, question_id="OPERATOR-SOFTMAX"
            ),
        )
    assert (
        store.read(lambda repo: repo.list_knowledge_invocations_for_parent(run.run_id))
        == []
    )


def test_native_system_dispatcher_completes_zero_call_knowledge_node(activity, handoff):
    from core.research.workflow.models import ActorKind
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        SystemActionAdapter,
    )
    from core.web.services.team_workflow.research_runtime.real_domain_ports import (
        RealDomainPorts,
    )
    from tests._support.workflow_ledger_helpers import build_outbox_record
    from tests.test_research_workflow_agent_anchor import _agent_action

    run, _, store = selected(activity, handoff)
    action = replace(
        _agent_action(),
        run_id=run.run_id,
        node_id="optimization_knowledge",
        node_run_id="knowledge-node",
        actor_kind=ActorKind.SYSTEM,
        action_kind="system_action",
    )

    def seed(u):
        u.repository.insert_command(
            build_command_record(run_id=run.run_id, command_id="knowledge-command")
        )
        u.repository.insert_attempt(
            build_attempt_record(
                "knowledge-node",
                run_id=run.run_id,
                node_id="optimization_knowledge",
                actor_kind="system",
                status="dispatching",
                command_id="knowledge-command",
            )
        )
        u.repository.insert_outbox(
            replace(
                build_outbox_record(action_id="knowledge-dispatch", run_id=run.run_id),
                command_id="knowledge-command",
                node_run_id="knowledge-node",
                action_kind="adapter_dispatch",
                payload_json=json.dumps(action.to_dict()),
            )
        )

    store.submit(seed, force_flush=True).result()
    ports = RealDomainPorts(store)
    registry = ActionRegistry()
    registry.register(SystemActionAdapter(ports))
    assert (
        AdapterDispatchWorker(store=store, registry=registry, ports=ports).run_once()
        == 1
    )
    attempt = store.latest_attempt(run.run_id, "optimization_knowledge")
    assert attempt.status == "succeeded", attempt.problem_json
    assert read_campaign(*activity).rounds[0].knowledgeRef is not None
    assert (
        store.read(lambda repo: repo.list_knowledge_invocations_for_parent(run.run_id))
        == []
    )
