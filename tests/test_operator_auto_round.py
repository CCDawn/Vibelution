"""Durable round close and native command acceptance without model/GPU work."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.research.operator_optimization.model_budget_contracts import (
    OperatorDiscussionBudget,
    OperatorModelCallBudget,
)
from core.research.workflow.models import AgentBindingLayers, ActorKind
from core.web.services.team_workflow.operator_optimization import (
    iteration,
    rounds,
    feedback,
    evaluation,
)
from core.web.services.team_workflow.operator_optimization.store import (
    read_campaign,
    update_campaign,
)
from core.web.services.team_workflow.research_runtime.block_projection import (
    sync_run_succeeded,
)
from core.web.services.team_workflow.research_runtime.event_publish_worker import (
    EventPublishWorker,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    WorkflowCommandService,
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
    base = baseline_ready[1]
    ledger = prepared[3]

    class Store:
        def get_run(self, run_id):
            return base if run_id == base.run_id else ledger.get_run(run_id)

        def __getattr__(self, name):
            return getattr(ledger, name)

    store = Store()
    monkeypatch.setattr(rounds.run_creation, "get_write_store", lambda: store)
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
                        "planning": OperatorModelCallBudget(**budget),
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
            terminal_reason="optimization_feedback_verified",
            node_id="optimization_feedback",
        )

    store.submit(close, force_flush=True).result()
    return (
        store,
        run_id,
        {"eventType": iteration.EVENT, "runId": run_id, "teamId": activity[0]},
        close,
    )


def test_terminal_transaction_enqueues_once_and_worker_starts_one_round(
    activity, completed
):
    store, run_id, payload, close = completed
    assert store.submit(close, force_flush=True).result() is False
    rows = store.read(
        lambda r: r.execute(
            "SELECT action_kind FROM outbox_actions WHERE run_id=?", (run_id,)
        ).fetchall()
    )
    assert rows == [("event_publish",)]
    worker = EventPublishWorker(store=store, now_provider=lambda: 2000)
    assert worker.run_once() == 1
    state = json.loads(store.get_run(run_id).input_snapshot_json)["operatorIteration"]
    assert state["status"] == "started"
    assert len(read_campaign(*activity).rounds) == 2
    assert (
        store.latest_attempt(state["nextRunId"], "optimization_discussion").attempt == 1
    )
    assert iteration.advance_iteration(store, payload, now_ms=3000) == state
    assert worker.run_once() == 0
    assert len(read_campaign(*activity).rounds) == 2


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
            "missing": {"planning": None},
        }[condition]
        return c.model_copy(update={"budget": c.budget.model_copy(update=fields)})

    update_campaign(
        *activity,
        expected_version=current.revision,
        command_key="stop-test",
        command={},
        transform=change,
    )
    result = iteration.advance_iteration(store, payload, now_ms=2000)
    assert result["status"] == "stopped"
    assert result["reason"]
    assert len(read_campaign(*activity).rounds) == 1


@pytest.mark.parametrize("checkpoint", ["prepared", "started"])
def test_recovers_after_creation_or_start_before_progress_write(
    activity, completed, monkeypatch, checkpoint
):
    store, _, payload, _ = completed
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
        iteration.advance_iteration(store, payload, now_ms=2000)
    result = iteration.advance_iteration(store, payload, now_ms=3000)
    assert result["status"] == "started"
    assert len(read_campaign(*activity).rounds) == 2
    assert (
        store.latest_attempt(result["nextRunId"], "optimization_discussion").attempt
        == 1
    )


def test_feedback_adapter_closes_run_and_never_enqueues_challenge_delivery(tmp_path):
    from tests._support.command_helpers import CommandHarness
    from tests._support.adapter_fakes import FakeDomainPorts
    from tests.test_research_workflow_adapter_idempotency import _action, _seed
    from core.research.workflow.operator_optimization_definition import (
        build_operator_definition,
    )
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
    )
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        SystemActionAdapter,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )
    from tests._support.workflow_ledger_helpers import FIXED_NOW_MS

    harness = CommandHarness(tmp_path / "terminal.sqlite")
    try:
        harness.seed_run(
            workflow_definition=build_operator_definition(), status="running"
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
        assert (
            run.status == "succeeded"
            and run.completion_kind == "operator_round_completed"
        )
        rows = harness.store.read(
            lambda r: r.execute("SELECT action_kind FROM outbox_actions").fetchall()
        )
        assert ("event_publish",) in rows
        assert ("delivery_orchestration",) not in rows
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
    result = iteration.advance_iteration(store, payload, now_ms=2000)
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
    result = iteration.advance_iteration(store, payload, now_ms=2000)
    assert result["reason"] == "model_budget_exhausted"
    assert len(read_campaign(*activity).rounds) == 1


def test_only_feedback_is_operator_round_terminal():
    from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
        _run_terminal_close_applies,
        _terminal_facts_for_close,
    )

    run = SimpleNamespace(workflow_id="operator-optimization")
    assert _run_terminal_close_applies(run, "optimization_feedback")
    assert not _run_terminal_close_applies(run, "operator_execution")
    assert not _run_terminal_close_applies(run, "operator_evaluation")
    assert _terminal_facts_for_close(run)[0] == "operator_round_completed"


def test_budget_must_cover_discussion_and_planning(activity, completed):
    store, _, payload, _ = completed
    current = read_campaign(*activity)
    # Each required phase costs at most 0.001, so this funds only one.
    update_campaign(
        *activity,
        expected_version=current.revision,
        command_key="partial-budget",
        command={},
        transform=lambda c: c.model_copy(
            update={"budget": c.budget.model_copy(update={"modelCostLimit": 0.0015})}
        ),
    )
    result = iteration.advance_iteration(store, payload, now_ms=2000)
    assert result["reason"] == "model_budget_exhausted"
    assert len(read_campaign(*activity).rounds) == 1
