"""Budget increases retain frozen calls and campaign-wide liabilities."""
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.web.services.team_workflow.operator_optimization import budget_extension as extension
from core.web.services.team_workflow.operator_optimization import model_budget
from core.web.services.team_workflow.operator_optimization.store import CampaignConflict, read_campaign, update_campaign
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_operator_optimization_budget import activity
from tests.test_operator_optimization_model_budget import _discussion_budget, _reserve_kwargs
from tests._support.workflow_ledger_helpers import open_ledger_store, build_run_record, build_command_record, build_attempt_record

@pytest.fixture
def setup(activity, tmp_path, monkeypatch):
    c = read_campaign(*activity)
    b = c.budget.model_copy(update={"modelCostLimit": 5.0, "currency": "USD", "discussion": _discussion_budget()})
    c = update_campaign(*activity, expected_version=c.revision, command_key="budget-fixture", command={},
        transform=lambda c: c.model_copy(update={"budget": b}))
    ledger = open_ledger_store(tmp_path / "budget.sqlite")
    run = replace(build_run_record(run_id="run1", team_id=activity[0], workflow_id="operator-optimization", status="blocked"),
        project_id=activity[1], input_snapshot_json=json.dumps({"researchObjectiveContract": {"optimizationCampaignId": activity[2]}}))
    ledger.submit(lambda uow: uow.repository.insert_run(run), force_flush=True).result()
    monkeypatch.setattr(extension, "get_write_store", lambda: ledger)
    yield c, ledger
    ledger.close()

def extend(activity, c, **overrides):
    args = {"model_cost_limit": 50, "token_limits": {"discussion": 3000},
        "expected_version": c.revision, "command_key": "increase"}
    args.update(overrides)
    with server_operator_scope("operator", roles=("operator",)):
        return extension.extend_model_budget(*activity, **args)

def test_extension_preserves_snapshot_and_replays(activity, setup):
    c, ledger = setup
    old = ledger.get_run("run1")
    new = extend(activity, c)
    assert new.budget.modelCostLimit == 50
    assert new.budget.discussion.tokenLimit == 3000
    assert new.budget.gpuSecondsLimit == c.budget.gpuSecondsLimit
    assert new.budget.maxRounds == c.budget.maxRounds
    assert ledger.get_run("run1") == old
    assert new.modelBudgetRevisions[0].previousBudget == c.budget
    assert new.modelBudgetRevisions[0].authorizedBy == "operator"
    assert extend(activity, c) == new
    with pytest.raises(CampaignConflict):
        extend(activity, c, command_key="stale")
    with pytest.raises(CampaignConflict):
        extend(activity, c, model_cost_limit=60)

def test_extension_requires_privilege_and_idle_run(activity, setup):
    c, ledger = setup
    with pytest.raises(PermissionError):
        extension.extend_model_budget(*activity, expected_version=c.revision, command_key="x", model_cost_limit=50, token_limits={})
    ledger.submit(lambda uow: uow.repository.update_run_status("run1", activity[0], "running", 10), force_flush=True).result()
    with pytest.raises(CampaignConflict, match="blocked"):
        extend(activity, c)
    assert read_campaign(*activity) == c

def test_extension_never_lowers_limits(activity, setup):
    c, _ = setup
    for args in ({"model_cost_limit": 4}, {"token_limits": {"discussion": 10}}, {"token_limits": {"planning": 2000}}):
        with pytest.raises(ValueError):
            extend(activity, c, **args)

def test_old_reservations_accumulate_after_authorized_increase(activity, setup):
    c, ledger = setup
    _seed(ledger, "node-old", 1)
    old_args = _reserve_kwargs(run_id="run1", node_run_id="node-old", campaign_id=activity[2], cost_limit="5")
    model_budget.reserve_model_budget(ledger, **old_args)
    ledger.submit(lambda uow: uow.repository.execute("UPDATE node_attempts SET status='failed', finished_at_ms=10 WHERE node_run_id='node-old'"), force_flush=True).result()
    old_row = ledger.read(lambda repo: repo.execute("SELECT reserved_json FROM budget_receipts").fetchone()[0])
    new = extend(activity, c)
    _seed(ledger, "node-new", 2)
    model_budget.reserve_model_budget(ledger, **_reserve_kwargs(run_id="run1", node_run_id="node-new", campaign_id=activity[2], cost_limit="50"))
    amount = ledger.read(lambda repo: model_budget._campaign_committed_amounts(SimpleNamespace(repository=repo), campaign_id=activity[2], currency="USD", model_cost_limit=Decimal(50)))
    assert amount == Decimal("0.0026")
    assert ledger.read(lambda repo: repo.execute("SELECT reserved_json FROM budget_receipts WHERE node_run_id='node-old'").fetchone()[0]) == old_row
    _seed(ledger, "node-fake", 3)
    with pytest.raises(model_budget.ModelBudgetError):
        model_budget.reserve_model_budget(ledger, **_reserve_kwargs(run_id="run1", node_run_id="node-fake", campaign_id=activity[2], cost_limit="500"))


def _seed(ledger, node, attempt):
    def mutate(uow):
        uow.repository.insert_command(build_command_record(command_id=node, run_id="run1", idempotency_key=node))
        uow.repository.insert_attempt(build_attempt_record(node, run_id="run1", node_id="optimization_discussion", attempt=attempt, command_id=node))
    ledger.submit(mutate, force_flush=True).result()


def test_old_frozen_limit_cannot_borrow_increased_capacity(activity, setup):
    c, ledger = setup
    _seed(ledger, "old", 1)
    model_budget.reserve_model_budget(ledger, **_reserve_kwargs(run_id="run1", node_run_id="old", campaign_id=activity[2], cost_limit="5"))
    ledger.submit(lambda uow: uow.repository.execute("UPDATE node_attempts SET status='failed', finished_at_ms=10"), force_flush=True).result()
    extend(activity, c)
    _seed(ledger, "new", 2)
    large = _discussion_budget(token_limit=6_000_000)
    model_budget.reserve_model_budget(ledger, **_reserve_kwargs(run_id="run1", node_run_id="new", campaign_id=activity[2], cost_limit="50", budget=large))
    _seed(ledger, "stale", 3)
    with pytest.raises(model_budget.ModelBudgetError, match="exceeded"):
        model_budget.reserve_model_budget(ledger, **_reserve_kwargs(run_id="run1", node_run_id="stale", campaign_id=activity[2], cost_limit="5"))


def test_unfinished_attempt_blocks_extension(activity, setup):
    c, ledger = setup
    _seed(ledger, "active", 1)
    with pytest.raises(CampaignConflict, match="unfinished"):
        extend(activity, c)
    assert read_campaign(*activity) == c


def test_budget_extension_http_permission_and_scope(activity, setup, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes.team_workflows.operator_optimization import router
    c, _ = setup
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    path = f"/teams/{activity[0]}/workflow-orchestration/research-projects/{activity[1]}/operator-experiments/{activity[2]}/budget/extend"
    payload = {"expectedCampaignVersion": c.revision, "idempotencyKey": "http", "modelCostLimit": 50, "tokenLimits": {"discussion": 3000}}
    monkeypatch.setattr("core.web.control.validate_control_request", lambda request: "missing")
    assert client.post(path, json=payload).status_code == 403
    monkeypatch.setattr("core.web.control.validate_control_request", lambda request: None)
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["budget"]["discussion"]["tokenLimit"] == 3000
    assert client.post(path, json=payload).json() == response.json()
    assert client.post(path, json={**payload, "idempotencyKey": "stale"}).status_code == 409


def test_first_receipt_rejects_unauthorized_limit(activity, setup):
    _, ledger = setup
    _seed(ledger, "first", 1)
    with pytest.raises(model_budget.ModelBudgetError, match="authorization"):
        model_budget.reserve_model_budget(ledger, **_reserve_kwargs(run_id="run1", node_run_id="first", campaign_id=activity[2], cost_limit="500"))
    assert ledger.read(lambda repo: repo.execute("SELECT count(*) FROM budget_receipts").fetchone()[0]) == 0


def test_increase_call_limit_preserves_frozen_budget(activity, setup):
    c, _ = setup
    new = extend(activity, c, call_limits={"discussion": 12})
    assert new.budget.discussion.maxCalls == 12
    assert new.modelBudgetRevisions[-1].previousBudget.discussion.maxCalls == 3
    with pytest.raises(ValueError):
        extend(activity, new, call_limits={"discussion": 2}, command_key="lower")


def test_waiting_parent_can_extend_only_when_exact_child_is_stopped(activity, setup):
    from tests._support.workflow_ledger_helpers import build_outbox_record
    c, ledger = setup
    _seed(ledger, "waiter", 1)
    def seed(uow):
        uow.repository.execute("UPDATE node_attempts SET node_id='optimization_knowledge' WHERE node_run_id='waiter'")
        problem = {"code": "operator_knowledge_child_pending", "child": {"childRunId": "child"}}
        uow.repository.execute("UPDATE workflow_runs SET active_node_id='optimization_knowledge', blocked_problem_json=? WHERE run_id='run1'", (json.dumps(problem),))
        child = replace(build_run_record(run_id="child", team_id=activity[0], workflow_id="challenge-cup-knowledge-sideflow", status="running", parent_run_id="run1"), project_id=activity[1])
        uow.repository.insert_run(child)
        uow.repository.insert_outbox(replace(build_outbox_record(run_id="run1", command_id="waiter", action_kind="adapter_dispatch"), node_run_id="waiter"))
    ledger.submit(seed, force_flush=True).result()
    with pytest.raises(CampaignConflict, match="child"):
        extend(activity, c)
    ledger.submit(lambda uow: uow.repository.update_run_status("child", activity[0], "blocked", 20), force_flush=True).result()
    with pytest.raises(CampaignConflict, match="invocation"):
        extend(activity, c)
    from core.research.workflow.ledger.records import KnowledgeInvocationRecord
    invocation = KnowledgeInvocationRecord(
        invocation_id="kinv", parent_run_id="run1", parent_node_id="optimization_knowledge",
        parent_node_run_id="waiter", parent_attempt=1, question_id="q", scope_hash="scope",
        request_hash="request", search_envelope_hash="search", requirements_hash="requirements",
        source_policy_version="v1", knowledge_child_run_id="child", status="running",
        knowledge_package_ref=None, package_content_hash=None, handoff_state="pending",
        error_json=None, created_at_ms=1, updated_at_ms=1)
    ledger.submit(lambda uow: uow.repository.insert_knowledge_invocation(invocation), force_flush=True).result()
    with pytest.raises(CampaignConflict, match="pending dispatch"):
        extend(activity, c)
    ledger.submit(lambda uow: uow.repository.execute("UPDATE outbox_actions SET status='failed' WHERE run_id='run1'"), force_flush=True).result()
    for field, value in (("parent_node_run_id", "other"), ("parent_attempt", 2), ("parent_node_id", "other")):
        ledger.submit(lambda uow: uow.repository.execute(f"UPDATE knowledge_invocations SET {field}=?", (value,)), force_flush=True).result()
        with pytest.raises(CampaignConflict, match="invocation"):
            extend(activity, c)
        ledger.submit(lambda uow: uow.repository.execute(f"UPDATE knowledge_invocations SET {field}=?", (getattr(invocation, field),)), force_flush=True).result()
    assert extend(activity, c).budget.modelCostLimit == 50
