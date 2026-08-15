"""Pet space routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.web.routes.pet_models import PetActionRequest, PetActionResponse, PetSummaryResponse
from core.web.services.pet_service import PetActionError, apply_pet_action, get_pet_summary


router = APIRouter(tags=["pet"])


@router.get(
    "/pet/summary",
    response_model=PetSummaryResponse,
    response_model_exclude_unset=True,
)
def pet_summary() -> dict:
    return get_pet_summary()


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
