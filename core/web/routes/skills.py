"""Skill library routes for the local web workbench."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.web.services.skill_service import get_skill_detail, get_skill_library


router = APIRouter(tags=["skills"])


@router.get("/skills")
def skills_library() -> dict:
    return get_skill_library()


@router.get("/skills/{command}")
def skills_detail(command: str) -> dict:
    try:
        return get_skill_detail(command)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
