"""Pet space routes."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from core.web.services.pet_service import PetActionError, apply_pet_action, get_pet_summary


router = APIRouter(tags=["pet"])


class PetActionRequest(BaseModel):
    action: str


@router.get("/pet/summary")
def pet_summary() -> dict:
    return get_pet_summary()


@router.post("/pet/actions")
def pet_action(payload: PetActionRequest) -> dict:
    try:
        return apply_pet_action(payload.action)
    except PetActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
