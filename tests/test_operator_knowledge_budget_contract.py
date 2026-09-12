"""Contracts and Ledger bridge for the operator knowledge collection budget."""

from decimal import Decimal

import pytest

from core.research.operator_optimization.contracts import CampaignBudget
from core.research.operator_optimization.model_budget_contracts import (
    OperatorDiscussionBudget,
    OperatorModelCallBudget,
)
from core.web.services.team_workflow.operator_optimization.model_budget import (
    ModelBudgetError,
    reserve_model_budget,
)
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
    open_ledger_store,
)


def _price():
    return {
        "modelRef": "qwen/operator",
        "priceVersion": "price-v1",
        "currency": "USD",
        "inputPerMillion": 1.0,
        "outputPerMillion": 2.0,
    }


def _knowledge_budget(*, max_calls=1):
    return OperatorModelCallBudget(
        tokenLimit=100,
        maxOutputTokensPerCall=20,
        maxCalls=max_calls,
        prices=[_price()],
    )


def _seed_parent(store, run_id, node_run_id):
    from tests._support.workflow_ledger_helpers import build_event_record, build_run_record

    def mutate(uow):
        uow.repository.insert_run(build_run_record(run_id=run_id))
        uow.repository.insert_event(build_event_record(1, run_id=run_id, event_id=f"event-{run_id}"))
        command_id = f"command-{node_run_id}"
        uow.repository.insert_command(build_command_record(command_id=command_id, run_id=run_id))
        uow.repository.insert_attempt(build_attempt_record(
            node_run_id, run_id=run_id, node_id="knowledge", command_id=command_id,
            status="dispatching",
        ))

    store.submit(mutate, force_flush=True).result(timeout=10)


def _kwargs(run_id, node_run_id, budget, limit="0.0002"):
    return {
        "run_id": run_id,
        "node_run_id": node_run_id,
        "optimization_campaign_id": "campaign-knowledge",
        "round_id": "round-1",
        "knowledge_budget": budget,
        "model_cost_limit": Decimal(limit),
        "campaign_currency": "USD",
        "model_ref": "qwen/operator",
        "policy_hash": "policy-v1",
    }


def test_knowledge_budget_allows_one_call_but_discussion_requires_two():
    assert _knowledge_budget().maxCalls == 1
    with pytest.raises(ValueError):
        OperatorDiscussionBudget(
            tokenLimit=100, maxOutputTokensPerCall=20, maxCalls=1, prices=[_price()]
        )


def test_campaign_budget_exposes_explicit_optional_knowledge_budget():
    campaign = CampaignBudget(knowledge=_knowledge_budget())
    assert campaign.knowledge is not None
    assert campaign.knowledge.maxCalls == 1


def test_knowledge_reservations_share_campaign_ceiling_across_real_node_runs(tmp_path):
    store = open_ledger_store(tmp_path / "knowledge.sqlite3")
    try:
        _seed_parent(store, "run-1", "node-1")
        _seed_parent(store, "run-2", "node-2")
        first = reserve_model_budget(store, **_kwargs("run-1", "node-1", _knowledge_budget()))
        assert first["reservedAmount"] == Decimal("0.00012")
        with pytest.raises(ModelBudgetError) as exc_info:
            reserve_model_budget(store, **_kwargs("run-2", "node-2", _knowledge_budget()))
        assert exc_info.value.code == "operator_model_budget_limit_reached"
    finally:
        store.close()


def test_knowledge_budget_does_not_implicitly_use_discussion_budget(tmp_path):
    store = open_ledger_store(tmp_path / "knowledge.sqlite3")
    try:
        _seed_parent(store, "run-1", "node-1")
        with pytest.raises(ModelBudgetError) as exc_info:
            reserve_model_budget(
                store,
                run_id="run-1",
                node_run_id="node-1",
                optimization_campaign_id="campaign-knowledge",
                round_id="round-1",
                discussion_budget=OperatorDiscussionBudget(
                    tokenLimit=100, maxOutputTokensPerCall=20, maxCalls=2, prices=[_price()]
                ),
                model_cost_limit=Decimal("0.002"),
                campaign_currency="USD",
                model_ref="qwen/operator",
                budget_kind="knowledge",
            )
        assert exc_info.value.code == "operator_model_budget_contract_conflict"
    finally:
        store.close()


def test_reservation_replay_cannot_switch_budget_kind(tmp_path):
    store = open_ledger_store(tmp_path / "knowledge.sqlite3")
    try:
        _seed_parent(store, "run-1", "node-1")
        reserve_model_budget(store, **_kwargs("run-1", "node-1", _knowledge_budget()))
        replay = _kwargs("run-1", "node-1", _knowledge_budget())
        replay["knowledge_budget"] = None
        replay["discussion_budget"] = OperatorDiscussionBudget(
            tokenLimit=100, maxOutputTokensPerCall=20, maxCalls=2, prices=[_price()]
        )
        replay["budget_kind"] = "discussion"
        with pytest.raises(ModelBudgetError) as exc_info:
            reserve_model_budget(store, **replay)
        assert exc_info.value.code == "operator_model_binding_mismatch"
    finally:
        store.close()
