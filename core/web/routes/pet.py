"""Pet space routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.web.routes.pet_models import (
    PetActionRequest,
    PetActionResponse,
    PetActivityResponse,
    PetSummaryResponse,
)
from core.web.services import pet_activity_service
from core.web.services.pet_service import PetActionError, apply_pet_action, get_pet_summary


router = APIRouter(tags=["pet"])


@router.get(
    "/pet/summary",
    response_model=PetSummaryResponse,
    response_model_exclude_unset=True,
)
def pet_summary() -> dict:
    return get_pet_summary()


@router.get(
    "/pet/activity",
    response_model=PetActivityResponse,
)
def pet_activity() -> dict:
    return pet_activity_service.get_pet_activity()


@router.post(
    "/pet/actions",
    response_model=PetActionResponse,
    response_model_exclude_unset=True,
)
def pet_action(payload: PetActionRequest) -> dict:
    try:
        return apply_pet_action(payload.action)
    except PetActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
