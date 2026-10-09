"""Thin HTTP boundary for owned historical AI backtest previews and runs."""

from fastapi import APIRouter, HTTPException, Query

from core.web.services import financial_backtest_service as service
from core.web.services.financial_backtest.contract import FinancialBacktestError
from core.web.services.financial_backtest.data import BacktestDataError
from core.web.services.financial_preferences_service import FinancialPreferenceError

from .financial_backtest_models import (
    FinancialBacktestCompareRequest,
    FinancialBacktestComparison,
    FinancialBacktestExport,
    FinancialBacktestExportRequest,
    FinancialBacktestForkPreviewRequest,
    FinancialBacktestPreview,
    FinancialBacktestPreviewRequest,
    FinancialBacktestResumeRequest,
    FinancialBacktestRun,
    FinancialBacktestRunPage,
    FinancialBacktestStartRequest,
)

router = APIRouter(tags=["financial-backtests"])
_ERRORS = (FinancialBacktestError, BacktestDataError, FinancialPreferenceError)


def _http_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=getattr(exc, "status_code", 422), detail=str(exc))


@router.post("/financial-backtests/{agent_id}/preview", response_model=FinancialBacktestPreview)
def preview(agent_id: str, payload: FinancialBacktestPreviewRequest) -> dict:
    try:
        return service.create_financial_backtest_preview(agent_id, payload.model_dump())
    except _ERRORS as exc:
        raise _http_error(exc) from exc


@router.post("/financial-backtests/{agent_id}/runs", response_model=FinancialBacktestRun)
def start(agent_id: str, payload: FinancialBacktestStartRequest) -> dict:
    try:
        return service.start_financial_backtest_run(agent_id, payload.clientRequestId, payload.previewId)
    except _ERRORS as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-backtests/{agent_id}/runs/{run_id}/fork-preview",
    response_model=FinancialBacktestPreview,
)
def fork_preview(
    agent_id: str,
    run_id: str,
    payload: FinancialBacktestForkPreviewRequest,
) -> dict:
    try:
        return service.create_financial_backtest_fork_preview(
            agent_id, run_id, payload.model_dump(exclude_unset=True)
        )
    except _ERRORS as exc:
        raise _http_error(exc) from exc


@router.post(
    "/financial-backtests/{agent_id}/runs/compare",
    response_model=FinancialBacktestComparison,
)
def compare(agent_id: str, payload: FinancialBacktestCompareRequest) -> dict:
    try:
        return service.compare_financial_backtest_runs(
            agent_id, payload.runIds, payload.axis
        )
    except _ERRORS as exc:
        raise _http_error(exc) from exc


@router.get("/financial-backtests/{agent_id}/runs", response_model=FinancialBacktestRunPage)
def list_runs(agent_id: str, limit: int = Query(default=30, ge=1, le=100), cursor: str = Query(default="", max_length=160)) -> dict:
    try:
        return service.list_financial_backtest_runs(agent_id, limit=limit, cursor=cursor)
    except _ERRORS as exc:
        raise _http_error(exc) from exc


@router.get("/financial-backtests/{agent_id}/runs/{run_id}", response_model=FinancialBacktestRun)
def get_run(agent_id: str, run_id: str) -> dict:
    try:
        return service.get_financial_backtest_run(agent_id, run_id)
    except _ERRORS as exc:
        raise _http_error(exc) from exc


@router.post("/financial-backtests/{agent_id}/runs/{run_id}/stop", response_model=FinancialBacktestRun)
def stop(agent_id: str, run_id: str) -> dict:
    try:
        return service.request_financial_backtest_stop(agent_id, run_id)
    except _ERRORS as exc:
        raise _http_error(exc) from exc


@router.post("/financial-backtests/{agent_id}/runs/{run_id}/resume", response_model=FinancialBacktestRun)
def resume(agent_id: str, run_id: str, payload: FinancialBacktestResumeRequest) -> dict:
    try:
        return service.resume_financial_backtest_run(agent_id, run_id, retry_unknown_decision_date=payload.retryUnknownDecisionDate, confirm_possible_duplicate_charge=payload.confirmPossibleDuplicateCharge)
    except _ERRORS as exc:
        raise _http_error(exc) from exc


@router.post("/financial-backtests/{agent_id}/runs/{run_id}/export", response_model=FinancialBacktestExport)
def export(agent_id: str, run_id: str, payload: FinancialBacktestExportRequest) -> dict:
    try:
        return service.export_financial_backtest_run(agent_id, run_id, payload.format)
    except _ERRORS as exc:
        raise _http_error(exc) from exc
