"""Thin owner-scoped transport; all workflow state belongs to the service."""
from fastapi import APIRouter, HTTPException

from core.web.services.financial_backtest.contract import FinancialBacktestError
from core.web.services.financial_backtest.data import BacktestDataError
from core.web.services.financial_preferences_service import FinancialPreferenceError
from .financial_walk_forward_models import WalkForwardPage, WalkForwardPreviewRequest, WalkForwardWorkflow

router = APIRouter(tags=["financial-backtests"])


def _call(name: str, *args):
    from core.web.services.financial_backtest import walk_forward_service
    try:
        return getattr(walk_forward_service, name)(*args)
    except (FinancialBacktestError, BacktestDataError, FinancialPreferenceError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 422), detail=str(exc)) from exc


@router.post("/financial-backtests/{agent_id}/runs/{run_id}/walk-forward-preview", response_model=WalkForwardWorkflow)
def preview(agent_id: str, run_id: str, payload: WalkForwardPreviewRequest):
    return _call("create_walk_forward_preview", agent_id, run_id, payload.model_dump())


@router.get("/financial-backtests/{agent_id}/walk-forward", response_model=WalkForwardPage)
def list_workflows(agent_id: str):
    return _call("list_walk_forward_workflows", agent_id)


@router.get("/financial-backtests/{agent_id}/walk-forward/{workflow_id}", response_model=WalkForwardWorkflow)
def get_workflow(agent_id: str, workflow_id: str):
    return _call("get_walk_forward", agent_id, workflow_id)


@router.post("/financial-backtests/{agent_id}/walk-forward/{workflow_id}/start", response_model=WalkForwardWorkflow)
def start(agent_id: str, workflow_id: str):
    return _call("start_walk_forward", agent_id, workflow_id)


@router.post("/financial-backtests/{agent_id}/walk-forward/{workflow_id}/stop", response_model=WalkForwardWorkflow)
def stop(agent_id: str, workflow_id: str):
    return _call("stop_walk_forward", agent_id, workflow_id)


@router.post("/financial-backtests/{agent_id}/walk-forward/{workflow_id}/resume", response_model=WalkForwardWorkflow)
def resume(agent_id: str, workflow_id: str):
    return _call("resume_walk_forward", agent_id, workflow_id)


@router.post("/financial-backtests/{agent_id}/walk-forward/{workflow_id}/export")
def export(agent_id: str, workflow_id: str):
    return _call("export_walk_forward", agent_id, workflow_id)
