"""Explicit model-budget increases; frozen invocations keep their old limits."""
from __future__ import annotations

from decimal import Decimal

from core.research.operator_optimization.contracts import ModelBudgetRevision
from ..research_runtime.formal_write_runtime import get_write_store
from ..research_runtime.operator_authorization import require_privileged_server_operator
from .store import CampaignConflict, _service, update_campaign


def extend_model_budget(team_id, project_id, campaign_id, *, expected_version,
                        command_key, model_cost_limit, token_limits):
    operator = require_privileged_server_operator(command="extend_budget")
    amount = Decimal(str(model_cost_limit))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("A finite positive model cost limit is required")
    if set(token_limits) - {"discussion", "knowledge", "planning"}:
        raise ValueError("Only model stage token limits can be increased")

    def increase(campaign):
        if not campaign.budget.authorized or not campaign.authorizedBy or campaign.status != "running":
            raise CampaignConflict("An authorized running campaign is required")
        ledger = get_write_store()
        def check_idle(repo):
            run = repo.get_run(campaign.activeRunId)
            if (run is None or run.team_id != team_id or run.project_id != project_id
                    or run.workflow_id != "operator-optimization" or run.status != "blocked"):
                raise CampaignConflict("Model budget can only increase while the active run is blocked")
            if any(a.finished_at_ms is None for a in repo.list_attempts(run.run_id)):
                raise CampaignConflict("An unfinished node attempt still owns the model budget")
            if repo.execute("SELECT 1 FROM outbox_actions WHERE run_id=? AND status IN ('pending','leased') LIMIT 1", (run.run_id,)).fetchone():
                raise CampaignConflict("A pending dispatch still owns the model budget")
        ledger.read(check_idle)
        old = campaign.budget
        if amount < Decimal(str(old.modelCostLimit)):
            raise ValueError("Model cost limit cannot be lowered")
        updates = {"modelCostLimit": float(amount)}
        for stage, tokens in token_limits.items():
            policy = getattr(old, stage)
            if policy is None or type(tokens) is not int or tokens < policy.tokenLimit:
                raise ValueError("An existing stage token limit can only be increased")
            updates[stage] = policy.model_copy(update={"tokenLimit": tokens})
        budget = old.model_copy(update=updates)
        if budget == old:
            raise ValueError("Budget increase must change a limit")
        revision = ModelBudgetRevision(previousBudget=old, budget=budget,
            authorizedBy=operator.operator_id, authorizedAt=_service().utc_now_iso(),
            campaignVersion=campaign.revision + 1)
        return campaign.model_copy(update={"budget": budget,
            "modelBudgetRevisions": (*campaign.modelBudgetRevisions, revision)})

    return update_campaign(team_id, project_id, campaign_id, expected_version=expected_version,
        command_key=command_key, command={"action": "extend_model_budget", "operatorId": operator.operator_id,
            "modelCostLimit": str(amount), "tokenLimits": token_limits}, transform=increase)


def authorized_model_limits(repo, *, run_id, campaign_id, currency):
    """Resolve history from persisted campaign identity, never a caller cap list."""
    from core.research.operator_optimization.contracts import OptimizationCampaign
    from .store import _load
    run = repo.get_run(run_id)
    if run is None:
        raise CampaignConflict("Budget receipt has no owning run")
    # Atomic JSON replacement permits a coherent read without taking the
    # campaign mutex inside the Ledger writer (the opposite lock order).
    campaign = OptimizationCampaign.model_validate(_load(run.team_id, run.project_id, campaign_id)["campaign"])
    if not campaign.authorizedBy or not campaign.budget.authorized or campaign.budget.currency != currency:
        raise CampaignConflict("Campaign model budget is not authorized")
    history = campaign.modelBudgetRevisions
    expected = history[0].previousBudget if history else campaign.budget
    limits = {Decimal(str(expected.modelCostLimit))}
    for revision in history:
        if revision.previousBudget != expected or revision.budget.currency != currency:
            raise CampaignConflict("Campaign budget authorization chain differs")
        if revision.budget.modelCostLimit < expected.modelCostLimit:
            raise CampaignConflict("Campaign budget authorization lowered its limit")
        expected = revision.budget
        limits.add(Decimal(str(expected.modelCostLimit)))
    if expected != campaign.budget:
        raise CampaignConflict("Campaign budget differs from its authorized history")
    return limits
