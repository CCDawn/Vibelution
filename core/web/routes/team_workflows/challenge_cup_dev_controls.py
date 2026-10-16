"""Thin Team workflow routes: Challenge Cup DEV platform controls.

Handlers stay thin and declare explicit response models; behavior and team
storage resolution live behind the ``team_workflow_orchestration_service``
facade. The route layer never re-implements the plan allowlist or any fixture
lifecycle.
"""
from __future__ import annotations

from fastapi import HTTPException

from core.research.competition.catalog_execution import CatalogExecutionError
from core.web.services.team_service import TeamNotFoundError
from core.web.services.team_workflow_orchestration_service import (
    ChallengeCupDevControlsError,
    DevControlsStorageError,
    DevFlowConflict,
    get_challenge_cup_catalog_overview,
    get_challenge_cup_token_usage,
)
from ._errors import _raise_team_workflow_route_error
from ._router import router
from .challenge_cup_dev_controls_models import (
    ChallengeCupCatalogOverviewResponse,
    ChallengeCupTokenUsageResponse,
)

_DEV_CONTROL_CONTRACT_ERRORS = (
    ChallengeCupDevControlsError,
    CatalogExecutionError,
    ValueError,
)


@router.get(
    "/teams/{team_id}/workflow-orchestration/challenge-program/catalog-overview",
    response_model=ChallengeCupCatalogOverviewResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_catalog_overview(team_id: str) -> dict:
    try:
        return get_challenge_cup_catalog_overview(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DevFlowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DevControlsStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _DEV_CONTROL_CONTRACT_ERRORS as exc:
        _raise_team_workflow_route_error(
            "challenge_cup_dev_controls.catalog_overview", team_id, exc, status_code=422
        )


@router.get(
    "/teams/{team_id}/workflow-orchestration/challenge-program/token-usage",
    response_model=ChallengeCupTokenUsageResponse,
    response_model_exclude_unset=True,
)
def challenge_cup_token_usage(team_id: str) -> dict:
    try:
        return get_challenge_cup_token_usage(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DevFlowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DevControlsStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except _DEV_CONTROL_CONTRACT_ERRORS as exc:
        _raise_team_workflow_route_error(
            "challenge_cup_dev_controls.token_usage", team_id, exc, status_code=422
        )
