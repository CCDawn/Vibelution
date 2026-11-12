"""Skill library routes for the local web workbench."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.web.routes.skills_models import (
    SkillLibraryDetailResponse,
    SkillLibraryResponse,
    SkillLibrarySourcesResponse,
    SkillLibrarySyncRequest,
    SkillLibrarySyncResponse,
)
from core.web.services.skill_library_service import (
    SkillLibraryError,
    list_managed_sources,
    sync_managed_sources,
)
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
def skills_detail(command: str, source: str = Query("")) -> dict:
    try:
        return get_skill_detail(command, source=source)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/skill-library/sources",
    response_model=SkillLibrarySourcesResponse,
    response_model_exclude_unset=True,
)
def skill_library_sources() -> dict:
    return list_managed_sources()


@router.post(
    "/skill-library/sync",
    response_model=SkillLibrarySyncResponse,
    response_model_exclude_unset=True,
)
def skill_library_sync(payload: SkillLibrarySyncRequest) -> dict:
    try:
        return sync_managed_sources(repo=payload.repo)
    except SkillLibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
