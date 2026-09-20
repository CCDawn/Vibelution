"""Team bundle export / import routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.team_bundle_service import (
    TeamBundleError,
    export_team_bundle,
    import_team_bundle,
)

router = APIRouter(tags=["team-bundles"])

_ERROR_STATUS: dict[str, int] = {
    "team_not_found": status.HTTP_404_NOT_FOUND,
    "unsupported_kind": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_schema_version": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_team": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_agents": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "invalid_agent": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


class TeamBundleImportPayload(BaseModel):
    bundle: dict[str, Any]
    dryRun: bool = True
    confirm: bool = Field(
        default=False,
        description="Required to execute an import whose bundle schema major exceeds the supported major.",
    )


@router.get("/teams/{team_id}/bundle")
def team_bundle_export(team_id: str) -> dict[str, Any]:
    try:
        return export_team_bundle(team_id)
    except TeamBundleError as error:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
            detail=str(error),
        ) from error


@router.post("/team-bundles/import")
def team_bundle_import(payload: TeamBundleImportPayload) -> dict[str, Any]:
    try:
        return import_team_bundle(
            payload.bundle,
            dry_run=bool(payload.dryRun),
            confirm=bool(payload.confirm),
        )
    except TeamBundleError as error:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
            detail=str(error),
        ) from error
