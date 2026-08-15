"""Skill library routes for the local web workbench."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.web.routes.skills_models import SkillLibraryDetailResponse, SkillLibraryResponse
from core.web.services.skill_service import get_skill_detail, get_skill_library


router = APIRouter(tags=["skills"])


@router.get(
    "/skills",
    response_model=SkillLibraryResponse,
    response_model_exclude_unset=True,
)
def skills_library() -> dict:
    return get_skill_library()


@router.get(
    "/skills/{command}",
    response_model=SkillLibraryDetailResponse,
    response_model_exclude_unset=True,
)
def skills_detail(command: str) -> dict:
    try:
        return get_skill_detail(command)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
