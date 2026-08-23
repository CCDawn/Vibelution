"""Thin Team workflow routes: Challenge Cup real catalog batch controls.

Handlers stay thin and declare explicit response models; behavior, fail-closed
authorization and team storage resolution live in the
``challenge_cup_real_batch`` service. The route layer never re-implements the
plan allowlist, gate progression or the circuit breaker.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from core.research.competition.catalog_execution import CatalogExecutionError
from core.research.competition.real_control_batch import RealBatchError
from core.web.services.team_service import TeamNotFoundError
from core.web.services.team_workflow.challenge_cup_real_batch import (
    ChallengeCupRealBatchError,
    RealBatchStorageError,
    cancel_real_batch,
    get_real_batch_status,
    poll_real_batch,
    record_catalog_run_authorization,
    start_real_batch,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    require_privileged_server_operator,
    server_operator_scope_from_http,
)

from ._errors import _raise_team_workflow_route_error
from ._router import router
from .challenge_cup_real_batch_models import (
    ChallengeCupRealBatchAuthorizationRequest,
    ChallengeCupRealBatchAuthorizationResponse,
    ChallengeCupRealBatchCancelRequest,
    ChallengeCupRealBatchPollResponse,
    ChallengeCupRealBatchProjectionResponse,
    ChallengeCupRealBatchStartRequest,
    ChallengeCupRealBatchStartResponse,
)

_REAL_BATCH_CONTRACT_ERRORS = (
    ChallengeCupRealBatchError,
    RealBatchError,
    CatalogExecutionError,
    ValueError,
)

_REAL_BATCH_ERROR_STATUS = {
    "confirmation_required": 428,
    "platform_not_authorized": 409,
    "catalog_run_authorization_required": 409,
    "catalog_run_authorization_invalid": 422,
    "previous_gate_incomplete": 409,
    "batch_cancelled": 409,
    "batch_not_found": 404,
    "invalid_max_items": 422,
}


def _raise_real_batch_route_error(operation: str, team_id: str, exc: Exception) -> None:
    code = getattr(exc, "code", "")
    status_code = _REAL_BATCH_ERROR_STATUS.get(str(code), 422)
    _raise_team_workflow_route_error(operation, team_id, exc, status_code=status_code)


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/real-batches/{plan_id}/authorize",
    response_model=ChallengeCupRealBatchAuthorizationResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_real_batch_authorize(
    team_id: str,
    plan_id: str,
    request: Request,
    payload: ChallengeCupRealBatchAuthorizationRequest | None = None,
) -> dict:
    """Persist approval from the authenticated server-side operator only."""

    _ = payload
    try:
        with server_operator_scope_from_http(request):
            operator = require_privileged_server_operator(command="authorize_catalog_run")
            return record_catalog_run_authorization(
                team_id,
                plan_id=plan_id,
                approved_by=operator.operator_id,
            )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc) or "command_forbidden"},
        ) from exc
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RealBatchStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _REAL_BATCH_CONTRACT_ERRORS as exc:
        _raise_real_batch_route_error("challenge_cup_real_batch.authorize", team_id, exc)


@router.get(
    "/teams/{team_id}/workflow-orchestration/challenge-program/real-batches/{plan_id}",
    response_model=ChallengeCupRealBatchProjectionResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_real_batch_status(team_id: str, plan_id: str) -> dict:
    try:
        return get_real_batch_status(team_id, plan_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RealBatchStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _REAL_BATCH_CONTRACT_ERRORS as exc:
        _raise_real_batch_route_error("challenge_cup_real_batch.status", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/real-batches/{plan_id}/start",
    response_model=ChallengeCupRealBatchStartResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_real_batch_start(
    team_id: str,
    plan_id: str,
    payload: ChallengeCupRealBatchStartRequest,
) -> dict:
    try:
        return start_real_batch(
            team_id,
            plan_id=plan_id,
            confirmed=payload.confirmed,
            concurrency=payload.concurrency,
            max_items=payload.maxItems,
            failure_budget=payload.failureBudget,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RealBatchStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _REAL_BATCH_CONTRACT_ERRORS as exc:
        _raise_real_batch_route_error("challenge_cup_real_batch.start", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/real-batches/{plan_id}/poll",
    response_model=ChallengeCupRealBatchPollResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_real_batch_poll(team_id: str, plan_id: str) -> dict:
    try:
        return poll_real_batch(team_id, plan_id=plan_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RealBatchStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _REAL_BATCH_CONTRACT_ERRORS as exc:
        _raise_real_batch_route_error("challenge_cup_real_batch.poll", team_id, exc)


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/real-batches/{plan_id}/cancel",
    response_model=ChallengeCupRealBatchProjectionResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_real_batch_cancel(
    team_id: str,
    plan_id: str,
    payload: ChallengeCupRealBatchCancelRequest,
) -> dict:
    try:
        return cancel_real_batch(team_id, plan_id=plan_id, confirmed=payload.confirmed)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RealBatchStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _REAL_BATCH_CONTRACT_ERRORS as exc:
        _raise_real_batch_route_error("challenge_cup_real_batch.cancel", team_id, exc)
