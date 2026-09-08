from dataclasses import replace

from core.research.workflow.models import ActorKind
from core.research.workflow.operator_optimization_definition import build_operator_definition
from core.web.services.team_workflow.research_runtime.action_registry import ActionRegistry
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import AdapterDispatchWorker
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import SystemActionAdapter
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS
from tests.test_research_workflow_adapter_idempotency import _action, _seed


def test_verified_baseline_closes_run_without_research_delivery(tmp_path):
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(workflow_definition=build_operator_definition(baseline=True), status="running")
        action = replace(_action(), node_id="operator_baseline", node_run_id="nr-baseline-1",
            actor_kind=ActorKind.SYSTEM, action_kind="system_action:operator_baseline")
        _seed(harness, action)
        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(SystemActionAdapter(ports, node_id="operator_baseline"))
        worker = AdapterDispatchWorker(store=harness.store, registry=registry, ports=ports,
            successor_fn=lambda node: (), now_provider=lambda: FIXED_NOW_MS + 1000)
        worker.run_once()
        run = harness.store.get_run("run-test")
        assert run.status == "succeeded"
        assert run.completion_kind == "baseline_measured"
        assert run.terminal_reason == "baseline_measurement_verified"
        def rows(uow):
            return uow.repository.execute("SELECT action_kind FROM outbox_actions WHERE run_id = ?", ("run-test",)).fetchall()
        actions = harness.store.submit(rows, force_flush=True).result(timeout=10)
        assert not any("delivery" in row[0] for row in actions)
        worker.run_once()
        assert harness.store.get_run("run-test").completion_kind == "baseline_measured"
    finally:
        harness.close()


def test_start_route_pins_campaign_baseline_and_uses_canonical_command(activity, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes.team_workflows import research_runtime as runtime_routes
    from core.web.routes.team_workflows.operator_optimization import router
    from core.web.services.team_workflow.operator_optimization.store import read_campaign, update_campaign
    from core.research.workflow.contracts import WorkflowCommandKind
    campaign = read_campaign(*activity)
    update_campaign(*activity, expected_version=campaign.revision, command_key="prepare-fixture",
        command={"fixture": True}, transform=lambda c: c.model_copy(update={"baselineRunId": "run1"}))
    calls = []
    def submit(**kwargs):
        calls.append(kwargs)
        return {"commandId": "cmd1", "runId": "run1", "status": "accepted"}
    monkeypatch.setattr(runtime_routes, "_submit_workflow_command", submit)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post(f"/teams/{activity[0]}/workflow-orchestration/research-projects/{activity[1]}"
        f"/operator-experiments/{activity[2]}/baseline/start", json={"idempotencyKey": "start1", "expectedRunVersion": 1})
    assert response.status_code == 200, response.text
    assert response.json() == {"commandId": "cmd1", "runId": "run1", "status": "accepted"}
    assert calls[0]["run_id"] == "run1"
    assert calls[0]["node_id"] == "operator_baseline"
    assert calls[0]["kind"] == WorkflowCommandKind.START_NODE


from tests.test_operator_optimization_budget import activity
