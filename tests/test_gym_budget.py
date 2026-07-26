import pytest

from core.gym import BudgetLimitExceeded, BudgetUsage, EvolutionBudget, EvolutionBudgetLedger


def test_budget_ledger_is_idempotent_and_recovers_without_duplicate_charge():
    budget = EvolutionBudget(max_candidates=2, max_model_calls=3, max_cost=5.0)
    ledger = EvolutionBudgetLedger(budget)

    assert ledger.consume("candidate:a", BudgetUsage(candidates=1, model_calls=1, cost=2.0)) is True
    assert ledger.consume("candidate:a", BudgetUsage(candidates=1, model_calls=1, cost=2.0)) is False
    assert ledger.usage == BudgetUsage(candidates=1, model_calls=1, cost=2.0)

    recovered = EvolutionBudgetLedger.from_snapshot(budget, ledger.to_snapshot())
    assert recovered.consume("candidate:a", BudgetUsage(candidates=1, model_calls=1, cost=2.0)) is False
    assert recovered.consume("candidate:b", BudgetUsage(candidates=1, model_calls=2, cost=3.0)) is True

    with pytest.raises(BudgetLimitExceeded, match="max_candidates"):
        recovered.consume("candidate:c", BudgetUsage(candidates=1))
