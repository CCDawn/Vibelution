"""Team template API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.team_template_service import (
    TeamTemplateError,
    get_team_template,
    instantiate_team_template,
    list_team_templates,
)


router = APIRouter(tags=["team-templates"])


class TeamTemplateInstantiatePayload(BaseModel):
    name: str = Field("", max_length=160)


@router.get("/team-templates")
def team_template_list() -> dict:
    return list_team_templates()


@router.get("/team-templates/{template_id}")
def team_template_detail(template_id: str) -> dict:
    try:
        return get_team_template(template_id)
    except TeamTemplateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/team-templates/{template_id}/instantiate", status_code=status.HTTP_201_CREATED)
def team_template_instantiate(template_id: str, payload: TeamTemplateInstantiatePayload) -> dict:
    try:
        return instantiate_team_template(template_id, name=payload.name)
    except TeamTemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
