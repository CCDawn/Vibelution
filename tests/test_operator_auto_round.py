"""Durable round close and native command acceptance without model/GPU work."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.research.operator_optimization.model_budget_contracts import (
    OperatorDiscussionBudget,
    OperatorModelCallBudget,
)
from core.research.workflow.models import ActorKind, AgentBindingLayers
from core.web.services.team_workflow.operator_optimization import (
    evaluation,
    feedback,
    discussion,
    iteration,
    knowledge,
    rounds,
)
from core.web.services.team_workflow.operator_optimization.store import (
    CampaignConflict,
    read_campaign,
    update_campaign,
)
from core.web.services.team_workflow.research_runtime.block_projection import (
    sync_run_succeeded,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    WorkflowCommandService,
)
from core.web.services.team_workflow.research_runtime.event_publish_worker import (
    EventPublishWorker,
)
from tests import test_operator_evaluation_feedback as fixtures
from tests.test_operator_optimization_rounds import actual_create_run

activity = fixtures.activity
baseline_ready = fixtures.baseline_ready
ready = fixtures.ready
discussion_case = fixtures.discussion_case
handoff = fixtures.handoff
proposal = fixtures.proposal
prepared = fixtures.prepared


@pytest.fixture
def completed(activity, prepared, baseline_ready, tmp_path, monkeypatch):
    fixtures.measure(prepared, monkeypatch, ["failed", "fast"])
    evaluation.publish_evaluation(
        fixtures.node(prepared, "operator_evaluation"), prepared[1]
    )
    feedback.publish_feedback(
        fixtures.node(prepared, "optimization_feedback"), prepared[1]
    )
    decision_node = fixtures.node(prepared, "optimization_decision")
    base = baseline_ready[1]
    ledger = prepared[3]

    class Store:
        def get_run(self, run_id):
            return base if run_id == base.run_id else ledger.get_run(run_id)

        def __getattr__(self, name):
            return getattr(ledger, name)

    store = Store()
    monkeypatch.setattr(rounds.run_creation, "get_write_store", lambda: store)
    monkeypatch.setattr(discussion, "get_write_store", lambda: store)
    monkeypatch.setattr(knowledge, "get_write_store", lambda: store)
    monkeypatch.setattr(rounds.run_creation, "create_run", actual_create_run)
    monkeypatch.setattr(
        rounds.run_creation, "research_workflow_data_root", lambda: tmp_path
    )
    monkeypatch.setattr(
        rounds.run_creation,
        "effective_binding_layers",
        lambda *a, **k: AgentBindingLayers(
            workflowDefaults={"experiment_planner": "planner-fixture"}
        ),
    )
    # Native command writes, controlled readiness; no graph worker is started.
    commands = WorkflowCommandService(
        store=store,
        readiness_context=lambda: None,
        readiness_service=SimpleNamespace(
            evaluate=lambda *a, **k: SimpleNamespace(ready=True)
        ),
    )
    monkeypatch.setattr(iteration, "get_command_service", lambda: commands)
    budget = dict(
        tokenLimit=1000,
        maxCalls=2,
        maxOutputTokensPerCall=100,
        prices=[
            {
                "modelRef": "fixture/model",
                "priceVersion": "v1",
                "currency": "CNY",
                "inputPerMillion": 1,
                "outputPerMillion": 1,
            }
        ],
    )
    current = read_campaign(*activity)
    update_campaign(
        *activity,
        expected_version=current.revision,
        command_key="test-model-budget",
        command={},
        transform=lambda c: c.model_copy(
            update={
                "budget": c.budget.model_copy(
                    update={
                        "discussion": OperatorDiscussionBudget(**budget),
                        "knowledge": OperatorModelCallBudget(**budget),
                        "planning": OperatorModelCallBudget(**budget),
                        "decision": OperatorModelCallBudget(**budget),
                    }
                )
            }
        ),
    )
    run_id = prepared[0].run_id

    def close(u):
        return sync_run_succeeded(
            u,
            run_id=run_id,
            now_ms=1000,
            completion_kind="operator_round_completed",
            terminal_reason="optimization_decision_verified",
            node_id=decision_node.node_id,
        )

    store.submit(close, force_flush=True).result()
    return (
        store,
        run_id,
        {"eventType": iteration.EVENT, "runId": run_id, "teamId": activity[0]},
        close,
    )


def test_terminal_transaction_enqueues_one_research_decision_without_starting_round(
    activity, completed
):
    from core.research.operator_optimization.decision import (
        OperatorIterationDecisionProposal,
    )
    from core.web.services.team_workflow.operator_optimization.decision_output import (
        decision_task_input,
        materialize_iteration_decision,
    )

    store, run_id, payload, close = completed
    assert store.submit(close, force_flush=True).result() is False
    rows = store.read(
        lambda r: r.execute(
            "SELECT action_kind FROM outbox_actions WHERE run_id=?", (run_id,)
        ).fetchall()
    )
    assert rows == [("event_publish",)]
    inputs = decision_task_input(activity[0], run_id)
    materialize_iteration_decision(
        activity[0],
        run_id,
        OperatorIterationDecisionProposal(
            inputHash=inputs["inputHash"],
            kind="stop",
            reason="the bounded test has enough evidence to stop",
        ),
        decided_by="fixture-decision-agent",
    )
    worker = EventPublishWorker(store=store, now_provider=lambda: 2000)
    assert worker.run_once() == 1
    state = json.loads(store.get_run(run_id).input_snapshot_json)["operatorDecision"]
    assert state["status"] == "stopped"
    assert state["decisionId"].startswith("decision-")
    assert state["decision"]["decidedBy"] == "fixture-decision-agent"
    assert len(read_campaign(*activity).rounds) == 1
    assert iteration.advance_iteration(store, payload, now_ms=3000) == state
    assert worker.run_once() == 0
    assert len(read_campaign(*activity).rounds) == 1


def test_discuss_decision_starts_stage_three_at_discussion_with_frozen_seed(
    activity, completed
):
    store, _, payload, _ = completed
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "discuss",
            "reason": "new evidence supports another bounded experiment",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["status"] == "started"
    assert len(read_campaign(*activity).rounds) == 2
    assert (
        store.latest_attempt(result["nextRunId"], "optimization_discussion").attempt
        == 1
    )
    next_run = store.get_run(result["nextRunId"])
    snapshot = json.loads(next_run.input_snapshot_json)
    context = snapshot["researchObjectiveContract"]
    assert context["experimentStage"] == "experiment_iteration"
    assert context["stage2SeedRef"]["kind"] == "operator_stage2_seed"
    seed = rounds.read_stage2_seed(activity[0], context["stage2SeedRef"])
    assert seed.sourceRunId == payload["runId"]
    assert seed.evaluationRef.sha256
    assert seed.feedbackRef.sha256


@pytest.mark.parametrize(
    ("kind", "node_id"),
    [
        ("discuss", "optimization_discussion"),
        ("collect_knowledge", "optimization_knowledge"),
        ("plan_candidate", "optimization_plan"),
        ("retest", "operator_execution"),
        ("repair_baseline", "operator_baseline"),
        ("stop", None),
    ],
)
def test_stage_three_actions_have_one_canonical_route(kind, node_id):
    assert iteration.iteration_route_for_action(kind) == node_id


def test_legacy_continue_is_not_a_stage_three_action(activity, completed):
    store, _, payload, _ = completed
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    with pytest.raises(CampaignConflict, match="Research decision is invalid"):
        iteration.apply_iteration_decision(
            store,
            payload,
            {
                "decisionId": requested["decisionId"],
                "kind": "continue",
                "reason": "legacy binary action",
                "decidedBy": "fixture-decision-agent",
            },
            now_ms=2100,
        )
    assert len(read_campaign(*activity).rounds) == 1


def test_collect_knowledge_reuses_exact_hypothesis_and_starts_only_knowledge(
    activity, completed
):
    from core.web.services.team_workflow.operator_optimization.knowledge import (
        build_knowledge_request,
    )

    store, _, payload, _ = completed
    source = read_campaign(*activity).rounds[-1]
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "collect_knowledge",
            "reason": "the selected mechanism still has a targeted evidence gap",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["status"] == "started"
    assert store.latest_attempt(result["nextRunId"], "optimization_discussion") is None
    assert store.latest_attempt(result["nextRunId"], "optimization_knowledge") is not None
    current = read_campaign(*activity).rounds[-1]
    assert current.hypothesisRef == source.hypothesisRef
    next_run = store.get_run(current.runId)
    next_context = json.loads(next_run.input_snapshot_json)["researchObjectiveContract"]
    assert next_context["roundId"] == current.roundId
    assert next_run.project_id == activity[1]
    request = build_knowledge_request(activity[0], current.runId)
    assert request.hypothesisRef == source.hypothesisRef
    assert request.roundId == current.roundId


def test_plan_candidate_reuses_verified_handoff_and_starts_only_planning(
    activity, completed
):
    from core.web.services.team_workflow.operator_optimization.planning_output import (
        planning_task_input,
    )

    store, _, payload, _ = completed
    source = read_campaign(*activity).rounds[-1]
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "plan_candidate",
            "reason": "the existing evidence can discriminate a new managed candidate",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["status"] == "started"
    assert store.latest_attempt(result["nextRunId"], "optimization_discussion") is None
    assert store.latest_attempt(result["nextRunId"], "optimization_knowledge") is None
    assert store.latest_attempt(result["nextRunId"], "optimization_plan") is not None
    current = read_campaign(*activity).rounds[-1]
    assert current.hypothesisRef == source.hypothesisRef
    assert current.knowledgeRef == source.knowledgeRef
    inputs = planning_task_input(activity[0], current.runId)
    assert inputs["roundId"] == current.roundId
    assert inputs["hypothesisRef"] == source.hypothesisRef.model_dump(mode="json")


def test_retest_binds_source_plan_to_new_round_and_starts_only_execution(
    activity, completed
):
    from core.research.operator_optimization.plan import OptimizationPlan
    from core.web.services.team_workflow.operator_optimization.knowledge import read_ref

    store, _, payload, _ = completed
    source = read_campaign(*activity).rounds[-1]
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "retest",
            "reason": "repeat the frozen candidate to distinguish measurement noise",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["status"] == "started"
    assert store.latest_attempt(result["nextRunId"], "optimization_plan") is None
    assert store.latest_attempt(result["nextRunId"], "operator_execution") is not None
    current = read_campaign(*activity).rounds[-1]
    plan = OptimizationPlan.model_validate(
        read_ref(activity[0], current.runId, current.planRef)
    )
    source_plan = OptimizationPlan.model_validate(
        read_ref(activity[0], source.runId, source.planRef)
    )
    assert plan.roundId == current.roundId
    assert plan.candidateRef == source_plan.candidateRef
    assert plan.protocolRef == current.protocolRef


def test_baseline_repair_creates_new_version_without_reusing_old_measurements(
    activity, completed, monkeypatch
):
    from core.web.services.team_workflow.operator_optimization import baseline

    store, _, payload, _ = completed
    monkeypatch.setattr(
        baseline,
        "inspect_cuda_environment",
        lambda: {"deviceKind": "cuda", "deviceName": "fixture"},
    )
    before = read_campaign(*activity)
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "repair_baseline",
            "reason": "the measurement baseline is invalid",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["status"] == "started"
    assert len(read_campaign(*activity).rounds) == 1
    repaired = read_campaign(*activity)
    assert len(repaired.baselineVersions) == 2
    assert repaired.baselineVersions[-1].status == "prepared"
    assert repaired.baselineVersions[-1].repairEvidenceRefs == (
        before.rounds[-1].evaluationRef,
        before.rounds[-1].feedbackRef,
    )
    assert repaired.activeBaselineVersionId == repaired.baselineVersions[0].baselineVersionId
    assert repaired.baselineRef == before.baselineRef
    assert repaired.bestCandidateRef == before.bestCandidateRef


def test_explicit_legacy_migration_creates_v2_run_and_preserves_source(
    activity, completed
):
    from core.research.workflow.definition_registry import registered_definitions, definition_identity
    from core.web.services.team_workflow.operator_optimization.migration import (
        migrate_stage2_run_to_stage3,
    )

    store, run_id, _, _ = completed
    legacy = next(
        definition_identity(item)
        for item in registered_definitions()
        if item.workflowId == "operator-optimization" and item.schemaVersion == "1.1.0"
    )
    store.submit(
        lambda u: u.repository.execute(
            "UPDATE workflow_runs SET workflow_version_id=? WHERE run_id=?",
            (legacy.workflowVersionId, run_id),
        ),
        force_flush=True,
    ).result()
    source_before = store.get_run(run_id)
    campaign = read_campaign(*activity)
    migrated = migrate_stage2_run_to_stage3(
        *activity,
        source_run_id=run_id,
        initial_action="discuss",
        expected_version=campaign.revision,
        command_key="migrate-stage2",
    )
    replay = migrate_stage2_run_to_stage3(
        *activity,
        source_run_id=run_id,
        initial_action="discuss",
        expected_version=campaign.revision,
        command_key="migrate-stage2",
    )
    assert replay == migrated
    assert len(migrated.rounds) == len(campaign.rounds) + 1
    next_run = store.get_run(migrated.activeRunId)
    assert next_run.workflow_version_id != source_before.workflow_version_id
    seed = rounds.read_stage2_seed(activity[0], migrated.rounds[-1].stage2SeedRef)
    assert seed.sourceRunId == run_id
    assert store.get_run(run_id) == source_before


def test_plan_candidate_rejects_configuration_already_attempted_in_seed(
    activity, completed
):
    from core.research.operator_optimization.plan import (
        OptimizationPlan,
        OptimizationPlanContent,
        OptimizationPlanProposal,
    )
    from core.web.services.team_workflow.operator_optimization import planning_output
    from core.web.services.team_workflow.operator_optimization.knowledge import read_ref

    store, _, payload, _ = completed
    source = read_campaign(*activity).rounds[-1]
    source_plan = OptimizationPlan.model_validate(
        read_ref(activity[0], source.runId, source.planRef)
    )
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "plan_candidate",
            "reason": "plan a discriminating managed candidate",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    inputs = planning_output.planning_task_input(activity[0], result["nextRunId"])
    content = {
        field: getattr(source_plan, field)
        for field in OptimizationPlanContent.model_fields
    }
    proposal = OptimizationPlanProposal(
        inputHash=inputs["inputHash"],
        candidate=source_plan.candidateRef.candidate,
        **content,
    )
    with pytest.raises(CampaignConflict, match="already attempted"):
        planning_output.materialize_optimization_plan(
            activity[0], result["nextRunId"], proposal
        )


def test_promoted_parent_disables_reuse_actions_and_requires_new_discussion(
    activity, completed
):
    from core.research.operator_optimization.plan import OptimizationPlan
    from core.web.services.team_workflow.operator_optimization.decision_output import (
        decision_task_input,
    )
    from core.web.services.team_workflow.operator_optimization.knowledge import read_ref

    store, _, payload, _ = completed
    current = read_campaign(*activity)
    source = current.rounds[-1]
    plan = OptimizationPlan.model_validate(
        read_ref(activity[0], source.runId, source.planRef)
    )
    update_campaign(
        *activity,
        expected_version=current.revision,
        command_key="promote-parent-for-routing",
        command={},
        transform=lambda campaign: campaign.model_copy(
            update={"bestCandidateRef": plan.candidateRef}
        ),
    )
    inputs = decision_task_input(activity[0], source.runId)
    assert inputs["actionPolicy"]["availableActions"] == ["discuss", "stop"]
    assert inputs["actionPolicy"]["blockedActions"]["retest"] == (
        "parent candidate changed"
    )
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "retest",
            "reason": "attempt to reuse a stale parent plan",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "iteration_parent_candidate_changed"
    assert len(read_campaign(*activity).rounds) == 1


def test_stop_decision_does_not_create_or_start_next_round(activity, completed):
    store, _, payload, _ = completed
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "stop",
            "reason": "expected ROI is below the experiment threshold",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["status"] == "stopped"
    assert result["reason"] == "expected ROI is below the experiment threshold"
    assert len(read_campaign(*activity).rounds) == 1


def test_decision_replay_is_idempotent_and_conflicting_rewrite_is_rejected(
    activity, completed
):
    store, _, payload, _ = completed
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    decision = {
        "decisionId": requested["decisionId"],
        "kind": "stop",
        "reason": "current evidence is sufficient",
        "decidedBy": "fixture-decision-agent",
    }
    first = iteration.apply_iteration_decision(
        store, payload, decision, now_ms=2100
    )
    assert iteration.apply_iteration_decision(
        store, payload, decision, now_ms=2200
    ) == first
    with pytest.raises(CampaignConflict, match="immutable"):
        iteration.apply_iteration_decision(
            store,
            payload,
            {**decision, "reason": "rewrite the accepted reason"},
            now_ms=2300,
        )
    assert len(read_campaign(*activity).rounds) == 1


def test_decision_output_is_bound_to_exact_feedback_and_replays(activity, completed):
    from core.research.operator_optimization.decision import (
        OperatorIterationDecisionArtifact,
        OperatorIterationDecisionProposal,
    )
    from core.web.services.team_workflow.operator_optimization.decision_output import (
        decision_task_input,
        materialize_iteration_decision,
    )
    from core.web.services.team_workflow.operator_optimization.knowledge import read_ref

    store, run_id, payload, _ = completed
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    inputs = decision_task_input(activity[0], run_id)
    proposal = OperatorIterationDecisionProposal(
        inputHash=inputs["inputHash"],
        kind="stop",
        reason="measured candidate is slower than the accepted baseline",
    )
    first = materialize_iteration_decision(
        activity[0], run_id, proposal, decided_by="decision-agent"
    )
    assert materialize_iteration_decision(
        activity[0], run_id, proposal, decided_by="decision-agent"
    ) == first
    artifact = OperatorIterationDecisionArtifact.model_validate(
        read_ref(activity[0], run_id, first)
    )
    assert artifact.decision.decisionId == requested["decisionId"]
    assert artifact.feedbackRef.model_dump(mode="json") == requested["feedbackRef"]
    with pytest.raises(CampaignConflict, match="different feedback"):
        materialize_iteration_decision(
            activity[0],
            run_id,
            proposal.model_copy(update={"inputHash": "f" * 64}),
            decided_by="decision-agent",
        )


@pytest.mark.parametrize(
    "condition", ["paused", "cancelled", "rounds", "gpu", "model", "missing"]
)
def test_stops_before_creating_a_round(activity, completed, condition):
    store, _, payload, _ = completed
    current = read_campaign(*activity)

    def change(c):
        if condition in {"paused", "cancelled"}:
            return c.model_copy(update={"status": condition})
        fields = {
            "rounds": {"maxRounds": 1},
            "gpu": {"gpuSecondsLimit": 1},
            "model": {"modelCostLimit": 0.00001},
            "missing": {"discussion": None},
        }[condition]
        return c.model_copy(update={"budget": c.budget.model_copy(update=fields)})

    update_campaign(
        *activity,
        expected_version=current.revision,
        command_key="stop-test",
        command={},
        transform=change,
    )
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "discuss",
            "reason": "attempt another bounded discussion",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["status"] == "stopped"
    assert result["reason"]
    assert len(read_campaign(*activity).rounds) == 1


@pytest.mark.parametrize("checkpoint", ["prepared", "started"])
def test_recovers_after_creation_or_start_before_progress_write(
    activity, completed, monkeypatch, checkpoint
):
    store, _, payload, _ = completed
    requested = iteration.advance_iteration(store, payload, now_ms=1900)
    decision = {
        "decisionId": requested["decisionId"],
        "kind": "discuss",
        "reason": "continue bounded optimization",
        "decidedBy": "fixture-decision-agent",
    }
    save = iteration._save
    crashed = []

    def interrupt(s, run_id, state):
        matches = state.get("nextRunId") and (
            state["status"] == "started"
            if checkpoint == "started"
            else state["status"] == "preparing"
        )
        if matches and not crashed:
            crashed.append(True)
            raise RuntimeError("crash after durable side effect")
        return save(s, run_id, state)

    monkeypatch.setattr(iteration, "_save", interrupt)
    with pytest.raises(RuntimeError, match="crash"):
        iteration.apply_iteration_decision(
            store, payload, decision, now_ms=2000
        )
    result = iteration.apply_iteration_decision(
        store, payload, decision, now_ms=3000
    )
    assert result["status"] == "started"
    assert len(read_campaign(*activity).rounds) == 2
    assert (
        store.latest_attempt(result["nextRunId"], "optimization_discussion").attempt
        == 1
    )


@pytest.mark.parametrize(
    ("workflow_version_id", "expected_status", "expects_event"),
    [
        ("wv-aa7cb4f2d3cc", "succeeded", True),
        ("wv-1c26116e7323", "running", False),
    ],
)
def test_feedback_adapter_closes_only_when_pinned_definition_ends_at_feedback(
    tmp_path, monkeypatch, workflow_version_id, expected_status, expects_event
):
    from core.research.workflow.definition_registry import (
        resolve_definition_by_version_id,
    )
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        SystemActionAdapter,
    )
    from tests._support.adapter_fakes import FakeDomainPorts
    from tests._support.command_helpers import CommandHarness
    from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
    from tests.test_research_workflow_adapter_idempotency import _action, _seed

    harness = CommandHarness(tmp_path / "terminal.sqlite")
    try:
        harness.seed_run(
            workflow_definition=resolve_definition_by_version_id(workflow_version_id),
            status="running",
        )
        action = replace(
            _action(),
            node_id="optimization_feedback",
            node_run_id="feedback-1",
            actor_kind=ActorKind.SYSTEM,
            action_kind="system_action:optimization_feedback",
        )
        _seed(harness, action)
        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(SystemActionAdapter(ports, node_id="optimization_feedback"))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda node: (),
            now_provider=lambda: FIXED_NOW_MS + 1000,
        )
        worker.run_once()
        run = harness.store.get_run("run-test")
        assert run.status == expected_status
        assert run.completion_kind == (
            "operator_round_completed" if expects_event else None
        )
        assert run.terminal_reason == (
            "optimization_feedback_verified" if expects_event else None
        )
        rows = harness.store.read(
            lambda r: r.execute("SELECT action_kind FROM outbox_actions").fetchall()
        )
        assert (("event_publish",) in rows) is expects_event
        assert ("delivery_orchestration",) not in rows
        if expects_event:
            from core.web.services.team_workflow.operator_optimization import (
                iteration as iteration_service,
            )

            delivered = []
            monkeypatch.setattr(
                iteration_service,
                "advance_iteration",
                lambda store, payload, *, now_ms: delivered.append(payload)
                or {"status": "requested"},
            )
            publisher = EventPublishWorker(
                store=harness.store,
                now_provider=lambda: FIXED_NOW_MS + 2000,
            )
            assert publisher.run_once() == 1
            assert delivered == [
                {
                    "eventType": "operator_round_completed",
                    "runId": "run-test",
                    "teamId": "research-team",
                }
            ]
    finally:
        harness.close()


def test_native_readiness_refusal_does_not_create_attempt(
    activity, completed, monkeypatch
):
    store, _, payload, _ = completed
    service = WorkflowCommandService(
        store=store,
        readiness_context=lambda: None,
        readiness_service=SimpleNamespace(
            evaluate=lambda *a, **k: SimpleNamespace(ready=False)
        ),
    )
    monkeypatch.setattr(iteration, "get_command_service", lambda: service)
    requested = iteration.advance_iteration(store, payload, now_ms=1900)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "discuss",
            "reason": "continue bounded optimization",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2000,
    )
    assert result["status"] == "blocked"
    assert store.latest_attempt(result["nextRunId"], "optimization_discussion") is None


def test_reserved_model_usage_prevents_next_round(activity, completed):
    from core.web.services.team_workflow.operator_optimization.model_budget import (
        reserve_model_budget,
    )

    store, run_id, payload, _ = completed
    campaign = read_campaign(*activity)
    budget = campaign.budget.model_copy(
        update={
            "discussion": campaign.budget.discussion.model_copy(
                update={"tokenLimit": 10_000_000}
            )
        }
    )
    reserve_model_budget(
        store,
        run_id=run_id,
        node_run_id="optimization_feedback",
        optimization_campaign_id=campaign.optimizationCampaignId,
        round_id=campaign.rounds[0].roundId,
        campaign_budget=budget,
        budget_kind="discussion",
    )
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "discuss",
            "reason": "attempt another bounded discussion",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["reason"] == "model_budget_exhausted"
    assert len(read_campaign(*activity).rounds) == 1


def test_operator_round_terminal_follows_pinned_workflow_version():
    from core.research.operator_optimization.decision import is_stage3_operator_run
    from core.research.workflow.definition_registry import definition_identity
    from core.research.workflow.operator_optimization_definition import (
        build_operator_definition,
    )
    from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
        _run_terminal_close_applies,
        _terminal_facts_for_close,
    )

    legacy_run = SimpleNamespace(
        workflow_id="operator-optimization",
        workflow_version_id="wv-aa7cb4f2d3cc",
    )
    current_run = SimpleNamespace(
        workflow_id="operator-optimization",
        workflow_version_id="wv-1c26116e7323",
    )

    assert _run_terminal_close_applies(legacy_run, "optimization_feedback")
    assert not _run_terminal_close_applies(legacy_run, "optimization_decision")
    assert not _run_terminal_close_applies(current_run, "optimization_feedback")
    assert _run_terminal_close_applies(current_run, "optimization_decision")
    assert _terminal_facts_for_close(legacy_run) == (
        "operator_round_completed",
        "optimization_feedback_verified",
    )
    assert _terminal_facts_for_close(current_run) == (
        "operator_round_completed",
        "optimization_decision_verified",
    )
    assert not is_stage3_operator_run(legacy_run)
    assert not is_stage3_operator_run(current_run)
    stage3 = definition_identity(build_operator_definition())
    assert is_stage3_operator_run(
        SimpleNamespace(workflow_version_id=stage3.workflowVersionId)
    )


def test_persisted_stop_is_applied_after_decision_budget_is_exhausted(
    activity, completed
):
    store, _, payload, _ = completed
    current = read_campaign(*activity)
    # The decision has already happened when the terminal event is consumed.
    update_campaign(
        *activity,
        expected_version=current.revision,
        command_key="partial-budget",
        command={},
        transform=lambda c: c.model_copy(
            update={"budget": c.budget.model_copy(update={"modelCostLimit": 0.0005})}
        ),
    )
    requested = iteration.advance_iteration(store, payload, now_ms=2000)
    assert requested["status"] == "requested"
    result = iteration.apply_iteration_decision(
        store,
        payload,
        {
            "decisionId": requested["decisionId"],
            "kind": "stop",
            "reason": "the completed evidence is sufficient",
            "decidedBy": "fixture-decision-agent",
        },
        now_ms=2100,
    )
    assert result["status"] == "stopped"
    assert result["reason"] == "the completed evidence is sufficient"
    assert len(read_campaign(*activity).rounds) == 1
