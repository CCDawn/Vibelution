"""Thin Team workflow routes: Challenge Cup DEV platform controls.

Handlers stay thin and declare explicit response models; behavior and team
storage resolution live behind the ``team_workflow_orchestration_service``
facade. The route layer never re-implements the plan allowlist or any fixture
lifecycle.
"""
from __future__ import annotations

from fastapi import HTTPException

from core.research.competition.catalog_execution import CatalogExecutionError
from core.research.competition.dev_control_batch import DevBatchError
from core.web.services.team_service import TeamNotFoundError
from core.web.services.team_workflow_orchestration_service import (
    ChallengeCupDevControlsError,
    DevControlsStorageError,
    DevFlowConflict,
    get_challenge_cup_dev_control_snapshot,
    run_challenge_cup_dev_batch,
    run_challenge_cup_dev_readiness,
)
from ._errors import _raise_team_workflow_route_error
from ._router import router
from .challenge_cup_dev_controls_models import (
    ChallengeCupDevBatchRunRequest,
    ChallengeCupDevBatchRunResponse,
    ChallengeCupDevControlSnapshotResponse,
    ChallengeCupDevReadinessRunRequest,
    ChallengeCupDevReadinessRunResponse,
)

_DEV_CONTROL_CONTRACT_ERRORS = (
    ChallengeCupDevControlsError,
    DevBatchError,
    CatalogExecutionError,
    ValueError,
)


@router.get(
    "/teams/{team_id}/workflow-orchestration/challenge-program/dev-controls",
    response_model=ChallengeCupDevControlSnapshotResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_dev_control_snapshot(team_id: str) -> dict:
    try:
        return get_challenge_cup_dev_control_snapshot(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DevControlsStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _DEV_CONTROL_CONTRACT_ERRORS as exc:
        _raise_team_workflow_route_error(
            "challenge_cup_dev_controls.snapshot", team_id, exc, status_code=422
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/dev-controls/readiness",
    response_model=ChallengeCupDevReadinessRunResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_dev_readiness_run(
    team_id: str,
    payload: ChallengeCupDevReadinessRunRequest,
) -> dict:
    try:
        return run_challenge_cup_dev_readiness(team_id, mode=payload.mode)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DevControlsStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _DEV_CONTROL_CONTRACT_ERRORS as exc:
        _raise_team_workflow_route_error(
            "challenge_cup_dev_controls.readiness", team_id, exc, status_code=422
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/challenge-program/dev-controls/batches/{plan_id}",
    response_model=ChallengeCupDevBatchRunResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_dev_batch_run(
    team_id: str,
    plan_id: str,
    payload: ChallengeCupDevBatchRunRequest,
) -> dict:
    try:
        return run_challenge_cup_dev_batch(
            team_id,
            plan_id,
            payload.maxItems,
            retry_failed=payload.retryFailed,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DevFlowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DevControlsStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _DEV_CONTROL_CONTRACT_ERRORS as exc:
        _raise_team_workflow_route_error(
            "challenge_cup_dev_controls.batch", team_id, exc, status_code=422
        )
